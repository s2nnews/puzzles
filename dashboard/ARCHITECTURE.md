# Premium Puzzles — Marketing Dashboard: Architecture

_Last updated: 29 Jul 2026. This doc exists so any future session (or person)
can pick this up without re-deriving it. If you change the system, update this._

## What it is

A single-page marketing dashboard for **Premium Puzzles Australia** (Shopify
store, `premiumpuzzlesau.myshopify.com`) at
<https://s2nnews.github.io/puzzles/dashboard/> — public, no login.

It shows sales, the session→purchase funnel, marketing efficiency (spend, ROAS,
CPC, CAC), per-campaign performance, a profit waterfall (contribution after
COGS, shipping, packaging, marketing), subscriber health and email performance,
with a date-range picker that recomputes everything for any range.

## The stack, end to end

```text
  Shopify Orders API ─┐
  Omnisend REST ──────┤
  ShipStation v1 ─────┤     GitHub Actions (hourly, :05)
  Porter published ───┤──▶  dashboard/collect.py  ──▶  data.json
    CSV (Sheet) ──────┘            │                   campaigns.json
       ▲                           └──▶ commits to main
       │ daily 19:00 / 19:20 UTC                    │
  Porter blend ◀── Meta Ads + GA4 + Google Ads      ▼
                                            GitHub Pages
                                                  │
                                     dashboard/index.html
                                     (fetches both JSON files)
```

Nothing is live. The page reads two static JSON files; they are as fresh as the
last Action run. See "Refresh cadence".

**The Google Sheet + Apps Script pipeline described in older docs is RETIRED.**
So is Looker Studio. `DATA-SOURCES.md`'s column→source map is still broadly
useful, but this file and `STATUS.md` are authoritative.

## Refresh cadence, and who writes what

| Writer | Writes | When (UTC) |
| --- | --- | --- |
| Porter export → `Sheet1` tab | Meta + GA4 + Google Ads daily rows | every 3h at :00 |
| Porter export → `campaigns` tab | per-campaign rows, both platforms | every 3h at :10 |
| Porter export → `channels` tab | GA4 sessions/revenue per channel group | every 3h at :20 |
| GitHub Action `dashboard-data` | all eight JSON feeds | every 2h at :25 |
| Cloud routine `daily SEO feed refresh` | the 3 connector-fed CSVs | daily, 22:00 (08:00 AEST) |
| `run_daily.py` (laptop) | Puzzle Index files only | at logon + 10:30 daily |

**Why these intervals.** Shopify, Omnisend and ShipStation are read live on
every Action run, so the sales side genuinely changes between runs — that is
what justifies a frequent cadence. The ad and funnel columns cannot be fresher
than Porter's sheet, so running the Action far more often than Porter only
re-reads identical numbers and adds commit noise. Worst-case staleness is about
3h for ad/funnel data and 2h for sales. Google Ads is itself ingested with a
delay and is only really settled for yesterday, so chasing minutes there buys
nothing.

**The Action is the SINGLE WRITER of the dashboard files.** `run_daily.py`
deliberately does not build or publish them — two writers on one file caused
real divergence on 29 Jul 2026. It only rebases onto origin first (`sync()`).

Actions minutes are free and unlimited on public repos, so hourly costs nothing.
GitHub runs schedules best-effort and delays them under load, so "hourly" means
roughly hourly. To force a refresh: **Run workflow** on the dashboard-data
Action.

## Data sources, and who owns which column

| Columns | Source | Notes |
| --- | --- | --- |
| Orders, gross/net/total sales, AOV, discounts, returns, shipping charged, units | Shopify **Orders API** | ShopifyQL is plan-gated, see below |
| Sessions, cart adds, checkouts, purchases, conversion rate | **GA4** via Porter | from 15 Jul 2026 |
| Meta spend / conv value / clicks / conversions | **Meta Ads** via Porter | from 15 Jul 2026 |
| Google spend / conv value / clicks / conversions | **Google Ads** via Porter | from 21 Jul 2026 |
| Per-campaign spend, revenue, conversions, clicks, impressions | Both ad platforms via Porter | `campaigns.json` |
| Traffic donut + revenue by channel | **GA4 channel groups** via Porter | `channels.json` |
| Email subscribes / unsubscribes | **Omnisend** | full history |
| Shipping cost | **ShipStation** | Premium Puzzles store only |
| Gross margin, LTV, repeat rate, packaging | Modelled constants in `index.html` | do NOT vary by range |

Anything still hardcoded should be treated as suspect until proven otherwise:
the sales-trend sparkline and the email-campaign table are the remaining
static blocks.

### Why Shopify sales are derived, not reported

`shopifyqlQuery` is **denied to any app on the Shopify Basic plan** — it demands
Level 2 protected-customer-data access, which Basic cannot grant. So daily sales
are derived from the Orders API instead, validated to **0.07%** against 121 days
of real ShopifyQL history before ShopifyQL was lost.

The identity `total_sales == net_sales + shipping_charges` holds **to the cent
across every day**. That is the regression test for the whole derivation — if it
ever drifts, the Orders-API maths is wrong.

### Accounting conventions (decided 28 Jul 2026)

- **Every money column is GST-inclusive.** Premium Puzzles is not registered for
  GST, so the tax charged is revenue kept. (Worth confirming with the accountant
  as turnover approaches the $75k threshold.)
- **Returns follow the money actually refunded**, split into its shipping part
  and the rest. Refund line-item subtotals are deliberately not used: a
  restock-without-refund would otherwise book revenue loss that never happened.
- **Shipping cost counts Premium Puzzles shipments only.** The ShipStation
  account also ships `funbox.fun` (store 125784) and Manual Orders (120002);
  counting them overstated the bleed by ~$1,520 over 120 days and pushed
  recovery from 66% down to 46%. Controlled by `SHIPSTATION_STORE_IDS`,
  default `120003`.
- **Gross margin is a modelled constant: 46.4%.** Shopify reports 36.9% at
  supplier list price; stock is bought ~20% under list, so a conservative 15%
  comes off cost: `1 − (1 − 0.369) × 0.85`. Cost is ex-GST on invoices but bears
  GST that cannot be reclaimed, and revenue is GST-inclusive, so the two 10%s
  cancel and the same rate applies. **It cannot vary by date range** — only 58%
  of units sold have a cost recorded in Shopify. Filling that gap is what would
  make margin genuinely range-aware.
- **Paid CAC divides by the platforms' own conversion counts**, not attributed
  revenue ÷ AOV. The old estimate read ~16 orders against 11 real conversions
  and could never tie out. Spend and conversions now match the campaign table
  exactly.

## Files

| File | Role |
| --- | --- |
| `index.html` | The dashboard. Self-contained; fetches the two JSON files. |
| `collect.py` | The collector. stdlib + requests only. |
| `data.json` | One row per day, 26 fixed columns. **The long-term store.** |
| `campaigns.json` | One row per day/platform/campaign. Also a long-term store. |
| `channels.json` | GA4 channel groups per day. |
| `email-campaigns.json` | Per-send email performance, Omnisend + seeded Klaviyo history. |
| `quiz-cohort.json` | Quiz leads by day and source, and what they went on to spend. |
| `leadgen.json` | Built from `leadgen.csv`. Meta's own lead count and the GA4 quiz funnel. |
| `search-console.json` | Organic clicks, impressions, CTR and position per day. |
| `rank-tracking.json` | One row per tracked keyword per weekly reading. Read daily. |
| `porter_feed.csv` | Offline fallback if `PORTER_CSV` is unset. Not used in production. |
| `campaigns.csv` | Offline fallback if `CAMPAIGNS_CSV` is unset. Not used in production. |
| `search-console.csv` | Seed **and** current source for the organic chart. See the caveat below. |
| `rank-tracking.csv` | The rank history. Agent-refreshed daily, new readings weekly. |
| `.env.example` | Template. Copy to `.env` (gitignored). |
| `selftest.js` | Runs the page's functions against the committed feeds. `node dashboard/selftest.js`. |
| `../.github/workflows/dashboard.yml` | The two-hourly refresh. |

**Every file in that list that `collect.py` writes must also be named in the
workflow's `git add`.** Eight are written; the line named three until 2026-08-13,
so `email-campaigns.json`, `quiz-cohort.json` and `leadgen.json` were rebuilt on
the runner every two hours and discarded with the container. The published page
served whatever a human last committed. The failure is silent by construction:
the collector logs success, the workflow reports success, and only the file's
git history shows it has not moved. **Adding a new output means editing two
files, not one.**

Anything that runs `collect.py` outside the Action must have the same
credentials, or it will regress the files it cannot fetch. A local run without
`PORTER_CSV` / `CAMPAIGNS_CSV` / `CHANNELS_CSV` silently falls back to the
committed sample CSVs and overwrites live Porter rows with them. Check
`git diff` before committing a locally-generated feed.

**Deleting a bad row means deleting it from BOTH the CSV and the JSON.** The
merge below never drops a row it has already published, which is exactly right
for a feed that only carries a trailing window and exactly wrong when you are
correcting bad data: remove it from the CSV alone and the next run restores it
from the JSON. Hit on 2026-08-14 removing a provisional Search Console day.

### Why the JSON files are the long-term store

Porter's free tier keeps only a **rolling 30 days**. `merge_previous` therefore
**never overwrites an existing value with a blank**, and days outside the
current window are carried forward untouched. The JSON on disk is the history;
Porter only ever supplies the trailing window. Delete those files and you lose
everything before ~30 days ago, permanently.

**And for a while, that is exactly what was happening.** These files stopped
being committed when `encrypt.py` landed: only `feeds.enc` goes to git now and
the plaintext is gitignored, so a CI checkout arrived with nothing to merge
onto and every run rebuilt each feed from its upstream window alone. Nothing
failed and nothing said so. `channels.json` simply sat at a fixed ~276 rows,
sliding forward one day at a time, until on 2026-08-31 the GA4 coverage had
walked to 2 August and the Total ROAS tile refused to compute on a 1-31 August
range. The tile was right; the feed under it had become a 30-day window.

`decrypt.py` now runs **before** `collect.py` in the workflow and lays the
previous bundle's plaintext back down, so the merge has its base again. The
rule to keep: **whatever holds the history must exist on the runner before
`collect.py` starts.** It is `feeds.enc` that is committed, so it is
`feeds.enc` that has to be unpacked first.

The one exception is `Shipping cost`: when ShipStation runs, a day with no
Premium Puzzles shipment is written as `0`, not blank, so a superseded figure
cannot be resurrected by the merge.

## The balance sheet panel

Added 2026-09-01. Everything else on this page is a **flow** over a date range.
The balance sheet is a **stock at an instant**, so it is deliberately not wired
to the date picker, the same way the Search Console and rank panels render off
their own series.

`dashboard/balance_sheet.py` writes `balance-sheet.json`, which is gitignored
and rides inside `feeds.enc` like every other feed. It is built in two halves:

- **The manual half.** Cash at bank, PayPal, creditor balances and stock ordered
  but not received. No API holds any of these. They live in the `manual` block
  of `balance-sheet.json`, Michael edits them by hand, and the script never
  overwrites them. They persist across CI runs because `decrypt.py` restores the
  file from the bundle before anything else runs, which is why this needs **no
  repo secret of its own**.
- **The derived half.** Stock on hand at cost and at retail, pulled live from
  the Shopify Admin API, and the Shopify Capital position computed from the
  `Total sales` column already in `data.json`.

**Stock is carried at cost.** The retail figure is a memo line and is never
added into assets: the gap between them is margin that has not happened yet.
`selftest.js` asserts both that the sheet balances and that no asset line is
carrying the retail figure, because that is the one error nobody would catch by
eye.

**The Capital line is an estimate and says so on the tile.** Repayment is 25% of
daily takings, so it is derivable from `data.json`, but the haircut applies to
turnover settled through Shopify and the exact figure is on the Capital page in
the admin. Refinancing eligibility is at **51% repaid**, confirmed by Michael
2026-09-01.

To update the manual figures:

```bash
# edit the `manual` block by hand, then
python dashboard/balance_sheet.py
python dashboard/encrypt.py
git add dashboard/feeds.enc && git commit && git push
```

## Configuration

Set in `dashboard/.env` locally, and as **repo secrets** for the Action
(Settings → Secrets and variables → Actions). Everything matching
`dashboard/.env*` is gitignored except `.env.example` — **this repo is public**.

| Name | Required | Purpose |
| --- | --- | --- |
| `SHOPIFY_STORE` | yes | e.g. `premiumpuzzlesau.myshopify.com` |
| `SHOPIFY_TOKEN` | yes* | Admin API token (`shppa_`/`shpat_`), needs `read_orders` |
| `SHOPIFY_CLIENT_ID` / `SHOPIFY_CLIENT_SECRET` | * | Alternative: Dev Dashboard app, exchanged for a 24h token |
| `OMNISEND_API_KEY` | yes | subscriber movement |
| `SHIPSTATION_API_KEY` / `_SECRET` | yes | carrier cost |
| `PORTER_CSV` | yes | published CSV of the feed sheet's `Sheet1` tab |
| `CAMPAIGNS_CSV` | yes | published CSV of the `campaigns` tab |
| `CHANNELS_CSV` | yes | published CSV of the `channels` tab |
| `SHIPSTATION_STORE_IDS` | no | default `120003` |
| `DAYS` | no | days to build, default 120 |
| `OMNISEND_DAYS` | no | days to refresh, default 45 |

\* Either `SHOPIFY_TOKEN` **or** the client-credentials pair.

## Porter

Free tier is **3 accounts + 30-day lookback**; destinations are free. Meta, GA4
and Google Ads is exactly 3, so there is **no headroom** — a fourth connector
tips you into paid.

**Only Meta genuinely needs Porter.** Google Ads links natively into GA4, and
GA4 has a free API with full history. If Porter ever starts charging, disconnect
GA4 and Google Ads from it, keep Meta only, and pull the rest from GA4 directly.

| Asset | ID |
| --- | --- |
| Blend "Premium Puzzles Dashboard Feed" | `9d0fa432-b119-4108-9cf3-752650090633` |
| Daily export → `Sheet1` | `060ac338-aa12-4127-95d4-4bbf94299201` |
| Campaign export → `campaigns` | `2a6bfdec-6366-48b3-90da-40a67646ad7b` |
| Channel export → `channels` | `9e18c134-bfe5-4d2e-a7a2-a7ae8eed9131` |
| Feed spreadsheet | `1M-g3Wjhhf-KoqPa6tDj5nQj2xKE-yPolD1Va0zYLa48` |
| Porter account | `info@premiumpuzzles.com.au` |

### Traps that have already cost time

1. **`worksheet_id` must be `<spreadsheet_id>__<sheet_name>`.** Passing `0` or a
   spreadsheet name fails with "Invalid sheet identifier format".
2. **Porter cannot create a tab.** Exporting to a tab that does not exist fails
   with "Sheet 'x' not found". Create it by hand first.
3. **`blend_export.create` reports success even when the run then fails.** Always
   check `get_blend` → `recent_executions` for the actual status.
4. **The published CSV's headers are `<connector> <label>`** — "Meta Ads Amount
   spent", "GA4 Sessions", "Google Ads Cost" — and **both click columns are
   labelled "Clicks"**. The connector prefix is what tells them apart.
   `collect.py` resolves all three dialects (our snake_case, bare labels,
   prefixed labels).
5. **Never hardcode a chart that reads as live.** The traffic donut and the
   revenue-by-channel table were hardcoded until 29 Jul 2026 and had reality
   backwards: they claimed Direct was 63% of sessions and Email 3%, when GA4
   reports Email as the largest channel by both sessions and revenue and
   Direct at ~11%. It sat there looking authoritative for weeks. Michael
   caught it only because he knew his email sends pull thousands of sessions.
   Anything on the page that is a fixed assumption must say so on its face —
   the gross-margin tile now reads "assumption · fixed for every range".
6. **Silent staleness is the failure mode to fear.** If headers stop matching,
   nothing errors: zero columns map, `merge_previous` keeps the last good values
   on screen, and the dashboard looks perfectly healthy while frozen. Every run
   therefore logs `Porter: mapped N columns` and prints unrecognised header
   names. **If a feed looks stuck, check that line first.**

### Campaign export shape

Adding both `google_ads_campaign_name` and `facebook_ads_campaign_name` to one
query yields **sparse rows, not a cross product**: each row names one platform's
campaign and leaves the other blank. `collect.py` pivots that wide shape into
the narrow `Date, Platform, Campaign, …` records the page expects.

## Other gotchas worth keeping

- **Omnisend** analytics is `POST /api/analytics/statistics` with header
  `Omnisend-Version: 2026-03-15` (the `/v5/...` path 404s). Max 60 days per
  query at day granularity — use **59**, because a DST transition inside the
  window pushes the absolute span over 60 and it rejects. The cap is **55
  requests/day**, which is why `OMNISEND_DAYS` defaults to 45 (one call).
- **2026-07-07** shows +24,059 / −21,007 email subs: that is the
  Klaviyo→Omnisend migration, not organic growth.
- **The funnel steps at 15 Jul 2026** where GA4 takes over from Shopify
  sessions. GA4 runs ~12% lower on sessions by definition; checkouts and
  purchases agree closely. Not a traffic drop.
- **Google Ads ingests with a delay.** Today's figures move for hours. Judge
  yesterday and earlier.
- **Shopify Basic cannot use ShopifyQL from an app, at all.** Legacy custom apps
  issue `shppa_` tokens (fine, same as `shpat_`). Dev Dashboard apps need scopes
  in a _released_ version AND "Use legacy install flow" OFF, or the install
  grants zero scopes.

## The one rule that matters

**Claude never handles API keys or secrets.** Mike pastes them into `.env` and
into GitHub secrets. Claude wires everything _around_ the secrets, and the code
never logs a URL or token — only header names and mapped-column counts.


---

# Metric rules, added 2026-08-11

A full rebuild of the metrics layer. These are the decisions a change to any
figure has to respect. Written after several of them were got wrong first.
Commercial reasoning and the private-side detail live in the owner's
knowledge base (`kb/business/marketing-dashboard.md` in the private repo);
what follows is everything needed to work on this code.

## Every range starts at the 15 June 2026 handover

`CONFIG.ownershipStart`. The store changed owner then, and the previous
owner's trading was clearance at negative gross margin. Including it does not
blur the picture, it inverts it: the same 90-day window read 11.1% margin and
MINUS $1,088 contribution with it, 40.9% and PLUS $2,318 without.

The comparison window is floored too. When that makes it shorter than the
current range, deltas on TOTALS are dropped (and the inline "$X prev" stripped
with them) because totals are only comparable across equal-length windows;
rate deltas are kept. Repeat rate and 12-month customer value are deliberately
NOT floored, being trailing-12-month customer measures.

## Gross margin is measured; only the uncosted gap is modelled

`costing()`. Real Shopify unit costs stand as themselves and ONLY the revenue
with no cost loaded is plugged at `CONFIG.fallbackMarginPct`. Deliberately not
"measure a rate on costed lines and apply it to everything" — that assumes
uncosted stock earns what costed stock earns.

Gross profit is `net sales − COGS`, subtracted not multiplied; margin is that
over net sales. The two tie by construction.

Cost is GST-INCLUSIVE, matching the revenue basis, because Premium Puzzles is
not GST-registered and cannot reclaim purchase GST.

## Total ROAS excludes email

`Total ROAS (ex-email)` = non-email revenue ÷ TOTAL ad spend. The email list
was inherited, so its revenue is not caused by current advertising and plain
MER rose whenever the newsletter had a good week. Denominator is total spend
so it extends to new ad platforms without change.

Returns `null` and renders a dash when GA4 channel data does not cover the
whole range, rather than subtracting only the email it can see.

## Lead-gen campaigns are not in the ROAS table

`CONFIG.leadGenCampaigns`. They have no purchase revenue, so a ROAS table
scores them zero and red. They live in their own table, judged on cost per
subscriber against `CONFIG.targetCostPerSubscriber`.

## Planned list pruning is excluded from organic net

`CONFIG.listHygiene`, keyed by date. Exclusion is BY DECLARATION, never by
size: an undeclared spike stays in the number and is flagged for review,
because "unusually large" is also what a real problem looks like.

## Traps that produced wrong numbers here

- **`discountedTotalSet` excludes ORDER-level discounts.** Lines summed higher
  than the order subtotal (#PP27919: $109.93 vs $98.94 after a $10.99 code),
  overstating revenue against unchanged cost and flattering margin on exactly
  the discounted sales where margin is being given away. Line revenue is
  rescaled to the order subtotal. Any recomputation of margin from line items
  needs this, and it always errs flatteringly.
- **Omnisend rate metrics break when bucketed by day.** A `timestamp`
  dimension buckets opens by the day they happened while `sent` lands on the
  send day. Warm-up Day 1 read 51.1% that way against a true 84.8%. Query
  campaign rates with no timestamp dimension.
- **`to_num()` rounds to 2dp** — it turned an 84.78% open rate into 85%. Not
  for rates stored as fractions.
- **Shopify `unitCost` is undated**, so today's cost is applied to old sales.
- **This app cannot read customer PII** (Shopify gates it above the Basic
  plan), so the collector sees customer tags, dates and orders but never an
  email. All filtering is tag-based, including the `qa-test` exclusion.
- **Duplicate element ids fail silently.** The email table and the ads table
  both used `id="campaigns"` and one overwrote the other. Check after editing:

```bash
python -c "import re;s=open('index.html',encoding='utf-8').read();u=set(re.findall(r\"getElementById\('([^']+)'\)\",s));d=set(re.findall(r'id=\"([^\"]+)\"',s));print('missing',sorted(u-d));print('dupes',sorted(i for i in d if s.count('id=\"%s\"'%i)>1))"
```

## Attribution, and why the quiz cohort exists

Last-click cannot tell you whether an ad produced a customer: a lead who signs
up from an ad and buys three weeks later off a newsletter is credited to email
by GA4, Shopify and Omnisend alike. The durable link is the CONTACT — the quiz
writes an acquisition tag onto the Shopify customer and it stays there. So
`fetch_quiz_cohorts` walks customers to their orders, counting only orders
placed AFTER signup. Revenue per lead is the figure cost per lead must sit
under.

Leads are counted on the `quiz-lead` tag. `puzzler-quiz` is the hidden field's
DEFAULT, written only when the tag builder throws, so counting it counts the
failures — which is exactly the mistake that once made this read 1 lead when
there were 9.

## Organic search, and the one feed that does not refresh itself

`search-console.json` drives the organic chart at the bottom of the page. It is
the only unpaid-demand series here, and it exists because the dashboard could
otherwise say nothing at all about whether the SEO work is doing anything.

**`SEARCH_CONSOLE_CSV` is not set, so `search-console.csv` is currently the
source, not just a fallback, and it does not advance on its own.** It was seeded
on 2026-08-13 with 14 July to 12 August pulled from Search Console through the
OpenSEO connector, which cannot run on the Action runner.

Given the whole point of this file's history is that a silently stale feed is
worse than no feed, the chart **states how many days behind it is** whenever
that exceeds four days, which is past Search Console's own 2 to 3 day lag. It
cannot go quietly stale the way the quiz panel did.

To finish it, in order:

1. Authorise the **Google Search Console** connector in Porter (`list_connectors`
   reports it available and `connected: false`, so this is an OAuth Michael has
   to click).
2. `blend_export.create` with dimensions `[date]` and the clicks, impressions,
   CTR and position metrics, to a new worksheet tab.
3. Publish that tab and add its CSV URL as the `SEARCH_CONSOLE_CSV` repo secret.

No code change is needed at step 3. The parser already accepts either a
published URL or the local file, reads Search Console's own header names, and
takes CTR as a fraction or a percentage. `write_rows` merges on `Date`, so the
committed file keeps history beyond whatever trailing window the export carries.

To refresh it by hand in the meantime, `get_search_console_performance` with
`dimensions: ["date"]` returns exactly the five columns the CSV holds.

**Always pass `dataState: "final"`, never `"all"`.** Search Console serves its
last two or three days as provisional and revises them upward for days
afterwards. `"final"` simply omits those days, and the `write_rows` merge picks
them up on a later run once they settle. `"all"` writes a partial number into a
file that is the permanent history, and nothing ever corrects it.

Caught on 2026-08-14, having already happened twice: 12 August was stored at 32
clicks from a provisional read and finalises at **48**, and 13 August read 11
clicks one morning and 13 the next. Both provisional rows were removed. The
store now ends at the last finalised day, so it will normally sit about three
days behind, which is why the panel's staleness warning is set at four.

## Rank tracking, and why the average is computed here rather than read

`rank-tracking.json` holds **one row per keyword per weekly reading**. It never
stores an average, and the page never displays the tool's own.

**The reason, from the day this was built.** Ubersuggest reported average
position improving from **12.36 to 9.00** between 2 and 9 August, a 3.4-place
gain. It was not one. It dropped `wasgij` (position 35) out of the second
reading and averaged 10 keywords against the first reading's 11. Like-for-like
across the ten present in both it was **10.10 to 9.00**, and even that was
almost entirely one keyword moving 27 to 14 while the rest drifted slightly
worse. Strip that keyword too and it went backwards, 8.22 to 8.44.

So `constantSetAvg()` compares only keywords carrying a position in **both**
readings, reports how many were excluded, and names them. There is a selftest
that fails if it ever compares unequal sets again. A keyword tracked but absent
from the top 100 stores a blank position, counted in coverage and kept out of
position maths, because scoring it 0 would read as better than first place.

**The panel refuses to draw a trend under four readings** and says so. Two
points is not a line, and week-to-week movement of a few places is SERP noise.

**Agent-refreshed, daily, by a scheduled cloud routine.**
`trig_013W6cKkjGUf8u8HYUes8CeR`, "Puzzles dashboard: daily SEO feed refresh",
08:00 AEST every day (`0 22 * * *` UTC).

Daily rather than weekly even though **rank tracking** is the only one of the
three that cannot go faster, because Ubersuggest itself only recalculates once
a week. The other two move daily and weekly made them wrong in a specific way:
Search Console finalises new days continuously, so a weekly grab left the chart
missing days Google had already settled, and `leadgen.csv` carries the lead
count while ad spend comes off the 2-hourly feed, so a weekly lead count kept
the two halves of that panel at different ages and fired its own drift warning
most of the week. On the six days Ubersuggest has nothing new the routine says
so and leaves the file alone. It refreshes all three connector-fed
CSVs (this one, `search-console.csv`, `leadgen.csv`) and commits them. The
GitHub Action then rebuilds the JSON within two hours, so the routine
deliberately touches **only the CSVs** and never runs `collect.py`.

> **Was blocked, fixed 2026-08-14.** For its first two runs the routine did
> the work correctly and then failed to push with `403 Resource not accessible
> by integration`, on `git push` and on both GitHub MCP write paths. Reads
> worked throughout.
>
> **The diagnosis that wasted a day was wrong.** It looked like the Claude
> GitHub App needed `Contents: write`, and it does not: an installer cannot add
> permissions an App has not requested, and per the
> [docs](https://code.claude.com/docs/en/claude-code-on-the-web) that App is
> only there for PR webhooks and "is not a session-level access control".
> Cloud sessions get repository access from the connected GitHub account, by
> either authorising the App during web onboarding **or** running **`/web-setup`**
> in the terminal to sync the local `gh` token.
>
> **The fix was `/web-setup`, one command.** Verified by firing the routine
> manually: it pushed `e2cf9b6` as author "Claude". If a future cloud session
> or routine ever 403s on push, run `/web-setup` again before touching anything
> on GitHub.

That first run is also the proof the design works: all three connectors are
available in a headless cloud session, and it correctly left rank tracking and
search console alone (no new Ubersuggest reading until 16 August, and Search
Console still inside its 2 to 3 day lag) while updating only leadgen.

To refresh by hand instead:

```text
project_position_info
  project_id = <from Uber_Suggest list_projects>
  startDate / endDate, locId 2036, language en, device desktop
# append one row per keyword to rank-tracking.csv, dated the reading's date
```

**The tracked keyword list was rebuilt on 2026-08-13, before history started
accumulating**, which is the only safe time to change it. Removed `strand
puzzle` (the NYT Strands game, wrong intent), `custom puzzles` (off-strategy),
`free jigsaw puzzles for adults` (free-seekers do not buy) and `jigsaw games for
adults` (leans to play-online intent), none of which ranked. Added `ravensburger
puzzles` (5,400/mo, difficulty 10, the biggest single prize on the site),
`puzzle board` and `jigsaw puzzle board` (5,400 and 2,400/mo, both transactional,
both spiking to 12,100 and 5,400 in December), `australian jigsaw puzzles`
(1,600/mo, the differentiator), `2000 piece puzzle`, `3000 piece puzzle`,
`gibsons puzzles` and `clementoni puzzles`. 19 of 25 slots used.

**Changing that list again resets comparability.** Do it deliberately, note the
date, and expect the constant-set average to shrink for a week or two.

## Still manual, but do not type it from Ads Manager

`leadgen.csv`, and only four things in it: Meta's own lead count, link clicks,
landing-page views, and the GA4 quiz funnel. `facebook_ads_lead` is not in the
Porter blend's export, and `update_blend` exposes accounts and data sources but
not the metric list, so it cannot be added to the existing export.

**It is still a two-minute job through the Porter connector, and typing it out
of Ads Manager by hand is what let it sit frozen for two days.** The recipe,
which produces every column:

```text
# spend, impressions, reach, clicks, link_clicks, landing_page_views, leads
execute_action facebook_ads.insights_get
  account_id = <the Premium Puzzles Australia ref from list_accounts>
  object_id  = act_1349938757036613
  level      = campaign
  fields     = campaign_name,spend,impressions,reach,clicks,inline_link_clicks,actions
  time_range = {"since":"YYYY-MM-DD","until":"YYYY-MM-DD"}
# read landing_page_view and lead out of the returned actions[] array

# quiz_start, quiz_complete
query_data
  accounts   = [<the GA4 property ref>]
  metrics    = [google_analytics_4_eventCount]
  dimensions = [google_analytics_4_eventName, google_analytics_4_sessionCampaignName]
  filters    = [{field: google_analytics_4_eventName, operator: contains, value: quiz}]
# take the rows whose campaign is the UTM the ads carry, e.g. quiz-leadgen-2026-08
```

Match the `from` / `to` to the window the campaign feed covers, so the panel is
comparing the same days on both sides, and set `as_at` to the day you pulled it.

**Full automation is available and nobody has taken it.** `blend_export.create`
accepts an explicit `metrics` array, unlike `update_blend`, and
`facebook_ads_lead` is a valid blend metric. So a fourth export off the same
blend, writing lead count and GA4 event counts to a fourth worksheet, would
remove this file entirely. It needs one thing this repo cannot do for itself:
the published CSV URL added as a `LEADGEN_CSV` secret. **This is a better path
than the Meta system-user token that was previously proposed**, because it needs
no new credential on either side.

Everything else on that panel is live. **Spend, impressions and clicks come
from `campaigns.json`, and the subscriber count from `quiz-cohort.json`**, so
the CSV's own `spend` column is a fallback only.

That mix is why the panel windows its own arithmetic. Cost per subscriber is
computed over **the days the spend feed actually covers**, not all time, for
two reasons: the cohort total carries paid leads from 2024 and 2025 that
predate the campaign, and the live half runs ahead of the hand-typed half
whenever the CSV is not refreshed. On 2026-08-13 the live subscriber count was
two days ahead of a frozen Porter export, which would have divided 59
subscribers by three days of spend and reported a cost per subscriber roughly
four times better than reality. The panel now states the shared window and
warns when the feeds are different ages.

Refreshing `leadgen.csv` is a real task with a real deadline, not a nicety:
the "gave an email" and quiz-funnel columns stop being comparable to the live
subscriber column the moment the campaign moves on.
