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
| GitHub Action `dashboard-data` | `data.json`, `campaigns.json` | every 2h at :25 |
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
| `porter_feed.csv` | Offline fallback if `PORTER_CSV` is unset. Not used in production. |
| `campaigns.csv` | Offline fallback if `CAMPAIGNS_CSV` is unset. Not used in production. |
| `.env.example` | Template. Copy to `.env` (gitignored). |
| `../.github/workflows/dashboard.yml` | The hourly refresh. |

### Why the JSON files are the long-term store

Porter's free tier keeps only a **rolling 30 days**. `merge_previous` therefore
**never overwrites an existing value with a blank**, and days outside the
current window are carried forward untouched. The committed JSON is the history;
Porter only ever supplies the trailing window. Delete those files and you lose
everything before ~30 days ago, permanently.

The one exception is `Shipping cost`: when ShipStation runs, a day with no
Premium Puzzles shipment is written as `0`, not blank, so a superseded figure
cannot be resurrected by the merge.

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
