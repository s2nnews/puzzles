# Status & next steps

_Snapshot: 28 Jul 2026 (late). Update this whenever state changes._

## What's working right now

- **Dashboard is LIVE and public:** <https://s2nnews.github.io/puzzles/dashboard/>
  (GitHub Pages, no login — shareable with family / collaborators).
- **The Google Sheet + Apps Script pipeline is RETIRED.** The page reads
  `./data.json` from the repo and `collect.py` (stdlib + requests) rebuilds
  it from the source APIs. Mentions of the published-CSV / Apps Script path
  in `ARCHITECTURE.md` / `DATA-SOURCES.md` describe the old system.
- **Refresh cadence is the laptop, not the cloud.** `run_daily.py` has a
  `dashboard` job that runs `collect.py` once a day on the existing at-logon
  Task Scheduler trigger, and publishes `data.json` alongside the Index
  files. The GitHub Actions cron is commented out (no repo secrets set);
  `workflow_dispatch` still works.
- `data.json` covers **2026-03-30 to 2026-07-28**: sales, orders, AOV, units,
  email growth, shipping charged/cost, the GA4 funnel, and Meta + Google Ads
  spend / conversion value / clicks.

## Sources, and who owns which column

| Columns | Source | Notes |
| --- | --- | --- |
| Sales, orders, AOV, returns, shipping charged, units | Shopify **Orders API** | ShopifyQL is plan-gated (below) |
| Sessions, cart adds, checkouts, purchases, conversion | **GA4** via Porter | from 15 Jul 2026 onward |
| Meta spend / conv value / clicks | **Meta Ads** via Porter | from 15 Jul 2026 |
| Google spend / conv value / clicks | **Google Ads** via Porter | from 21 Jul 2026 (spend restarted) |
| Email subscribes / unsubscribes | **Omnisend** | full history |
| Shipping cost | **ShipStation** | full history |

Porter's free tier only stores a rolling ~30 days, so `collect.py`'s
`merge_previous` never overwrites an existing value with a blank: `data.json`
in git is the long-term store and Porter only supplies the trailing window.

## Accounting conventions (decided 28 Jul 2026)

- **Every money column is GST-inclusive.** Premium Puzzles is not registered
  for GST, so the tax it charges is revenue it keeps. `total_sales` equals
  `net_sales + shipping_charges` to the cent across all 121 days — that
  identity is the regression test for the Orders-API derivation.
- **Returns follow the money actually refunded**, split into its shipping
  part and the rest. Refund line-item subtotals are deliberately not used: a
  restock-without-refund would otherwise book revenue loss that never
  happened.
- **Shipping cost counts Premium Puzzles shipments only.** The ShipStation
  account also ships `funbox.fun` (store 125784) and Manual Orders (120002);
  including them overstated the bleed by ~$1,520 over 120 days. Controlled
  by `SHIPSTATION_STORE_IDS`, default `120003`.
- **Gross margin is a modelled constant: 46.4%.** Shopify reports 36.9% at
  supplier list price, and stock is bought ~20% under list, so a
  conservative 15% comes off cost: `1 − (1 − 0.369) × 0.85`. Cost is ex-GST
  on invoices but bears GST that cannot be reclaimed, and revenue is now
  GST-inclusive, so the two 10%s cancel and the same rate applies. It cannot
  vary by date range — only 58% of units sold have a cost recorded in
  Shopify, and filling that gap is what would make margin genuinely
  range-aware.

## The gap

1. **The Porter feed is refreshed by hand.** `dashboard/porter_feed.csv` was
   written from a live Porter pull. `run_daily.py` runs headless and cannot
   call the Porter MCP, so the feed only advances when someone refreshes it.
   Fix: create a Google Sheet, attach the scheduled export from blend
   `9d0fa432-b119-4108-9cf3-752650090633` (already created,
   destination_type `google_sheets`), publish it as CSV, and put that URL in
   `PORTER_CSV`. `blend_export.create` needs an existing `worksheet_id` —
   Porter cannot create the spreadsheet itself.
2. **Funnel discontinuity at 15 Jul 2026.** Before that date the funnel is
   Shopify sessions; from 15 Jul it is GA4, which runs ~12% lower on
   sessions (different session definition, consent/ad-blockers). Checkouts
   and purchases agree closely. Do not read the step as a traffic drop.
3. **`shopifyqlQuery` is denied on the Basic plan** — it demands Level 2
   protected-customer-data access, which Basic cannot grant, for any app.
   Sales are DERIVED from the Orders API instead, validated to 0.07% of
   ShopifyQL's own history over 121 days.
4. **Subscriber list size is blank** — no daily source wired yet (candidate:
   Omnisend contacts count, current day only).
5. **Actions secrets not set** — only needed if the nightly cloud run is
   re-enabled.

## Credential boundary (unchangeable)

Claude never sees or types API keys. Mike sets them in:

- Locally: `dashboard/.env` (copy from `.env.example`; gitignored).
- GitHub (only if the cron is re-enabled): repo Settings → Secrets and
  variables → Actions, same names.

Everything matching `dashboard/.env*` is gitignored except `.env.example`.
This repo is public — never commit a file holding live keys.

## Fast facts for next time (so we don't re-derive)

- Shopify **Basic** cannot use ShopifyQL from an app, at all. Legacy custom
  apps issue `shppa_` tokens (fine, same as `shpat_`); Dev Dashboard apps
  need scopes in a _released_ version AND "Use legacy install flow" OFF, or
  the install grants zero scopes.
- On Admin API 2025-07 `shopifyqlQuery` returns `{ parseErrors, tableData
  { columns, rows } }` directly — there is NO `TableResponse` type.
- Omnisend analytics: POST `/api/analytics/statistics` with header
  `Omnisend-Version: 2026-03-15` (the `/v5/...` path 404s). Max 60 days per
  query at day granularity — use 59, because a DST transition inside the
  window pushes the absolute span over 60 days and it rejects.
- 2026-07-07 shows +24,059 / −21,007 email subs: that is the
  Klaviyo→Omnisend list migration, not organic growth.
- Porter: one blend can span connectors and returns one row per date.
  Google Ads `google_ads_cost_micros` comes back already in dollars.
- The `s2nnews/puzzles` repo is the **Puzzle Index** project; the dashboard
  is an isolated `dashboard/` subfolder.
