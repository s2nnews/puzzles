/* Runtime self-test for index.html.
 *
 * `node --check` only catches SYNTAX. It cannot catch a function that is
 * referenced but never defined, or a parameter that was never added — which
 * is exactly how a broken build shipped on 2026-08-11: the Total ROAS tile
 * read `ctx.emailRev` while buildModel still had the signature (a, p). The
 * tile threw, apply() died before setting the date inputs, and the dashboard
 * silently froze on its hardcoded snapshot dates while still looking live.
 *
 * So this actually RUNS the page's functions against the committed feeds.
 *
 *     node dashboard/selftest.js
 */
const fs = require('fs'), path = require('path');
const DIR = __dirname;
const html = fs.readFileSync(path.join(DIR, 'index.html'), 'utf8');
const src = (html.match(/<script[^>]*>([\s\S]*?)<\/script>/g) || [])
  .map(b => b.replace(/^<script[^>]*>/, '').replace(/<\/script>$/, '')).join('\n;\n');

const el = () => ({ innerHTML:'', textContent:'', value:'', style:{}, dataset:{}, min:'', max:'',
  addEventListener(){}, querySelector:()=>el(), querySelectorAll:()=>[],
  classList:{add(){},remove(){}}, closest:()=>null, focus(){}, click(){},
  setAttribute(){}, removeAttribute(){}, offsetParent:null });
global.document = { getElementById:()=>el(), querySelector:()=>el(), querySelectorAll:()=>[],
  scripts:[], addEventListener(){}, documentElement:el(), body:el(), createElement:()=>el() };
global.window = global;
global.location = { search:'' };
global.fetch = () => Promise.resolve({ json: () => Promise.resolve([]) });
global.setTimeout = () => 0;

eval(src);

const read = f => JSON.parse(fs.readFileSync(path.join(DIR, f), 'utf8'));
DAILY_DATA = read('data.json');
CHANNEL_DATA = read('channels.json');
CAMPAIGN_DATA = read('campaigns.json');
try { QUIZ_DATA = read('quiz-cohort.json'); } catch (e) {}
try { LEADGEN_DATA = read('leadgen.json'); } catch (e) {}
try { GSC_DATA = read('search-console.json'); } catch (e) {}
try { RANK_DATA = read('rank-tracking.json'); } catch (e) {}
try { EMAIL_DATA = read('email-campaigns.json'); } catch (e) {}

const last = DAILY_DATA[DAILY_DATA.length - 1].Date;
const minus = (d, n) => new Date(new Date(d + 'T00:00:00') - n * 86400000)
  .toISOString().slice(0, 10);

let failures = 0;
const check = (name, fn) => {
  try { const v = fn(); console.log('  ok   ' + name + (v === undefined ? '' : '  ' + v)); }
  catch (e) { console.log('  FAIL ' + name + '  ' + e.message); failures++; }
};

console.log('Feeds end ' + last);

// Every preset the picker offers, plus the no-context path.
[7, 30, 90, 365].forEach(n => {
  const from = minus(last, n - 1), to = last;
  check('range ' + n + 'd', () => {
    const inR = DAILY_DATA.filter(r => r.Date >= from && r.Date <= to);
    if (!inR.length) return 'no rows';
    const m = buildModel(aggregate(inR), aggregate(inR), { emailRev: emailRevenueIn(from, to) });
    ['money', 'mktg', 'profit', 'funnel', 'wf'].forEach(k => {
      if (!Array.isArray(m[k]) || !m[k].length) throw new Error('empty model.' + k);
    });
    m.money.concat(m.mktg, m.profit).forEach(t => {
      if (t.val === undefined || t.val === null) throw new Error('tile "' + t.label + '" has no value');
      if (String(t.val).includes('undefined') || String(t.val).includes('NaN'))
        throw new Error('tile "' + t.label + '" renders ' + t.val);
      if (t.pv && (String(t.pv).includes('undefined') || String(t.pv).includes('NaN')))
        throw new Error('tile "' + t.label + '" sub-label renders ' + t.pv);
    });
    return m.mktg.find(t => t.label.startsWith('Total ROAS')).val;
  });
});

// buildModel must survive a caller that passes no context at all.
check('buildModel without ctx', () => {
  const inR = DAILY_DATA.filter(r => r.Date >= minus(last, 29));
  buildModel(aggregate(inR), aggregate(inR));
  return 'no throw';
});

// Checked by identifier, not global[...]: eval() puts function declarations in
// the enclosing scope rather than on global, so a global[] lookup reports every
// one of them missing. That false alarm is itself worth the comment.
const NAMES = ['renderModel','renderCampaigns','renderTraffic','renderEmail',
  'renderQuizCohort','renderLeadgen','renderSearchConsole','renderRanks',
  'paintSubStats','emailRevenueIn','costing','buildModel','aggregate'];
// dropTotalDeltas is deliberately absent: it lives inside initPicker(), so it
// is not global and a check for it would fail forever.
check('every renderer is defined', () => {
  const missing = NAMES.filter(f => eval('typeof ' + f) !== 'function');
  if (missing.length) throw new Error('not defined: ' + missing.join(', '));
  return NAMES.length + ' checked';
});

// The acquisition panel actually RENDERED, not merely defined. It divides one
// live feed by another, so a missing helper or a bad denominator shows up here
// as NaN or undefined in the HTML rather than as a thrown error.
check('acquisition panel renders', () => {
  let out = '';
  const host = el();
  Object.defineProperty(host, 'innerHTML',
    { get: () => out, set: v => { out = v; } });
  const realGet = document.getElementById;
  document.getElementById = id => (id === 'leadgen' ? host : el());
  try { renderLeadgen(); } finally { document.getElementById = realGet; }
  if (!out) throw new Error('rendered nothing');
  ['NaN', 'undefined', 'Invalid Date', '$Infinity'].forEach(bad => {
    if (out.includes(bad)) throw new Error('renders ' + bad);
  });
  const cells = (out.match(/<td\b/g) || []).length;
  if (!cells) throw new Error('no table rows');
  return cells + ' cells';
});

// Both halves of "true cost each" must be countable, or the panel is quoting a
// number it cannot support.
check('paid subscribers are windowed', () => {
  if (typeof paidLeadsIn !== 'function') throw new Error('paidLeadsIn missing');
  const all = paidLeadsIn('', '');
  if (all === null) return 'no daily rows, falls back to cohort total';
  const cohort = ((QUIZ_DATA && QUIZ_DATA.cohorts) || {})['meta-paid'] || {};
  if (cohort.leads !== undefined && all !== cohort.leads)
    throw new Error('daily rows sum to ' + all + ' but the cohort says ' + cohort.leads);
  return all + ' paid, all time';
});

// The organic chart draws two series on two axes off one feed. A NaN in a
// path attribute renders as an invisible line, not an error, so assert the
// SVG itself rather than trusting the call not to throw.
check('organic search chart renders', () => {
  let out = '';
  const host = el();
  Object.defineProperty(host, 'innerHTML', { get: () => out, set: v => { out = v; } });
  const realGet = document.getElementById;
  document.getElementById = id => (id === 'gsc' ? host : el());
  try { renderSearchConsole(); } finally { document.getElementById = realGet; }
  if (!out) throw new Error('rendered nothing');
  if (!GSC_DATA || GSC_DATA.length < 2) return 'no feed, showed the empty state';
  ['NaN', 'undefined', 'Infinity'].forEach(bad => {
    if (out.includes(bad)) throw new Error('renders ' + bad);
  });
  const paths = (out.match(/<path /g) || []).length;
  if (paths < 4) throw new Error('expected 4 series paths, got ' + paths);
  return GSC_DATA.length + ' days, ' + paths + ' paths';
});

// A 7-day average must never plot a partial window: a 3-day mean drawn on the
// same line as a 7-day one understates the start of every series.
check('moving average has no half-windows', () => {
  const avg = movingAvg([1, 2, 3, 4, 5, 6, 7, 8], 7);
  if (avg.slice(0, 6).some(v => v !== null)) throw new Error('plotted a partial window');
  if (Math.abs(avg[6] - 4) > 1e-9) throw new Error('wrong mean: ' + avg[6]);
  if (Math.abs(avg[7] - 5) > 1e-9) throw new Error('wrong mean: ' + avg[7]);
  return 'ok';
});

// CTR is a 0-1 fraction. If a percentage ever leaks into the feed the average
// CTR tile silently reads 100x high, so guard the range here.
check('search console feed is sane', () => {
  if (!GSC_DATA || !GSC_DATA.length) return 'no feed';
  GSC_DATA.forEach(r => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(r.Date)) throw new Error('bad date ' + r.Date);
    if (r.CTR !== '' && r.CTR > 1) throw new Error('CTR ' + r.CTR + ' is not a fraction');
    if (r.Clicks > r.Impressions) throw new Error(r.Date + ': more clicks than impressions');
  });
  const dates = GSC_DATA.map(r => r.Date);
  if (new Set(dates).size !== dates.length) throw new Error('duplicate dates');
  return GSC_DATA.length + ' rows, ' + dates[0] + ' to ' + dates[dates.length - 1];
});

check('rank panel renders', () => {
  let out = '';
  const host = el();
  Object.defineProperty(host, 'innerHTML', { get: () => out, set: v => { out = v; } });
  const realGet = document.getElementById;
  document.getElementById = id => (id === 'ranks' ? host : el());
  try { renderRanks(); } finally { document.getElementById = realGet; }
  if (!out) throw new Error('rendered nothing');
  ['NaN', 'undefined', 'Infinity'].forEach(bad => {
    if (out.includes(bad)) throw new Error('renders ' + bad);
  });
  return (out.match(/<tr>/g) || []).length + ' rows';
});

// THE regression guard for this panel. The tool's own average moved 12.36 to
// 9.00 only because it dropped its worst keyword from the second reading. If
// constantSetAvg ever compares unequal keyword sets again, this catches it.
check('averages use a constant keyword set', () => {
  const mk = (date, pairs) => ({ date, kw: Object.fromEntries(
    Object.entries(pairs).map(([k, v]) => [k, { Position: v }])) });
  const a = mk('2026-08-02', { good: 2, mid: 10, awful: 35 });
  const b = mk('2026-08-09', { good: 2, mid: 10 });          // awful not re-read
  const r = constantSetAvg(a, b);
  if (r.n !== 2) throw new Error('compared ' + r.n + ' keywords, expected 2');
  if (r.from !== 6 || r.to !== 6)
    throw new Error('reported ' + r.from + ' -> ' + r.to + ', expected 6 -> 6 (unchanged)');
  if (!r.dropped.includes('awful')) throw new Error('did not report the dropped keyword');
  // The naive average would be (2+10+35)/3 = 15.67 -> (2+10)/2 = 6, a fake win.
  if (constantSetAvg(a, a).from !== 47 / 3) throw new Error('self-compare should keep all three');
  return 'constant set enforced';
});

// Not-ranking must never be scored as position 0, which would read as better
// than first place and drag every average toward zero.
check('not-ranking is excluded, not scored zero', () => {
  if (!RANK_DATA || !RANK_DATA.length) return 'no feed';
  RANK_DATA.forEach(r => {
    if (r.Position !== '' && !(r.Position > 0))
      throw new Error(r.Keyword + ' has position ' + JSON.stringify(r.Position));
  });
  const dates = [...new Set(RANK_DATA.map(r => r.Date))].sort();
  return dates.length + ' readings, ' + dates[0] + ' to ' + dates[dates.length - 1];
});

// The email table renders, and every column lines up. The unsub column was
// added to a table whose subtotal rows spell their cells out one by one, so a
// header and a body that disagree is a live risk here, not a theoretical one.
check('email campaign table renders', () => {
  let out = '';
  const host = el();
  Object.defineProperty(host, 'innerHTML', { get: () => out, set: v => { out = v; } });
  const realGet = document.getElementById;
  document.getElementById = id => (id === 'email-campaigns' ? host : el());
  try { renderEmail(); } finally { document.getElementById = realGet; }
  if (!out) throw new Error('rendered nothing');
  ['NaN', 'undefined', 'Invalid Date', '$Infinity'].forEach(bad => {
    if (out.includes(bad)) throw new Error('renders ' + bad);
  });
  const cols = (out.match(/<th\b/g) || []).length;
  const trs = out.split('<tr').slice(2);   // slice(0) is pre-table, (1) is the header
  trs.forEach((tr, i) => {
    const n = (tr.match(/<td\b/g) || []).length;
    if (n !== cols) throw new Error('row ' + (i + 1) + ' has ' + n + ' cells, header has ' + cols);
  });
  return trs.length + ' rows x ' + cols + ' cols';
});

// THE REGRESSION THIS FILE EXISTS FOR, second instance. On 2026-08-18 a
// campaign was deleted from Omnisend, vanished from /api/campaigns, and its
// row stopped refreshing while the merge kept serving the snapshot taken two
// hours after the send: 27.5% open and $330 against a real 68% and $988. It
// looked live and was not. Rows are keyed on campaign ID now and sourced from
// the analytics report, which retains deleted campaigns — so a duplicate ID,
// or a row with no ID at all, means the merge key has been weakened and the
// same freeze is available again.
check('every campaign row has a unique ID', () => {
  if (!EMAIL_DATA || !EMAIL_DATA.length) throw new Error('no feed');
  const missing = EMAIL_DATA.filter(r => !r.ID);
  if (missing.length)
    throw new Error(missing.length + ' row(s) with no ID, e.g. ' + missing[0].Campaign);
  const ids = EMAIL_DATA.map(r => r.ID);
  const dupes = ids.filter((v, i) => ids.indexOf(v) !== i);
  if (dupes.length) throw new Error('duplicate ID: ' + dupes[0]);
  return ids.length + ' distinct';
});

// Open rate is unique openers over sent, which is what the Omnisend UI shows.
// Reading the API's own openRate while bucketing by day returned roughly a
// third of the truth, and summing per-day unique counts returns more than the
// list: the 11 Aug send reads 87.7% that way against a true 72.3%. Anything
// over 100% means someone has gone back to summing buckets.
check('email rates are plausible fractions', () => {
  let worst = 0;
  EMAIL_DATA.forEach(r => {
    ['Open rate', 'Click rate'].forEach(k => {
      const v = +r[k];
      if (!(v >= 0 && v <= 1))
        throw new Error(r.Campaign + ' has ' + k + ' = ' + r[k] + ' (want a 0-1 fraction)');
    });
    if ((+r['Click rate'] || 0) > (+r['Open rate'] || 0) + 1e-9)
      throw new Error(r.Campaign + ' clicks more than it opens');
    worst = Math.max(worst, +r['Open rate'] || 0);
  });
  return EMAIL_DATA.length + ' sends, top open rate ' + (worst * 100).toFixed(1) + '%';
});

console.log(failures ? '\nFAILED (' + failures + ')' : '\nAll passed');
process.exit(failures ? 1 : 0);
