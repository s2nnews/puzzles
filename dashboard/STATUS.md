# Status & next steps

_Snapshot: 28 Jul 2026 (late). Update this whenever state changes._

## What's working right now

- **Dashboard is LIVE and public:** <https://s2nnews.github.io/puzzles/dashboard/>
  (GitHub Pages, no login — shareable with family / collaborators).
- **The Google Sheet + Apps Script pipeline is RETIRED.** The page reads
  `./data.json` from the repo and `collect.py` (stdlib + requests) rebuilds
  it from the source APIs. Mentions of the published-CSV / Apps Script path
  in `ARCHITECTURE.md` / `DATA-SOURCES.md` describe the old system.
- **Refresh is hourly, from GitHub Actions** (`.github/workflows/dashboard.yml`,
  :05 past the hour; Actions minutes are free on public repos). It is the
  SINGLE WRITER of `dashboard/data.json` and `dashboard/campaigns.json` —
  `run_daily.py` no longer builds or publishes them, it only rebases onto
  origin in `sync()`. Two writers on one file had already caused divergence.
  To force a refresh, use "Run workflow" on the dashboard-data Action.
- **A campaign table** ranks every campaign that spent in the selected range
  by spend, showing ROAS, cost/conversion and CPC, fed by
  `campaigns.csv` → `campaigns.json`.
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

## Fully automatic as of 29 Jul 2026

Every column now refreshes hourly with no human in the loop: Shopify,
Omnisend and ShipStation direct from their APIs, and Meta / GA4 / Google Ads
via two Porter exports into a published Google Sheet.

## Open action for Mike

**Add a `channels` tab** to the feed spreadsheet (same as `campaigns`),
publish it as CSV, and set the `CHANNELS_CSV` secret. Export
`9e18c134-bfe5-4d2e-a7a2-a7ae8eed9131` already targets it. Until then the
traffic donut and the revenue-by-channel table run off the committed
`channels.csv`, which will go stale.

## The gap

1. **`PORTER_CSV` is DONE — the daily/funnel feed is fully automatic.**
   Blend `9d0fa432-b119-4108-9cf3-752650090633` → export
   `92f57adc-291c-4d84-bd5e-934d944e4b02` → sheet
   `1M-g3Wjhhf-KoqPa6tDj5nQj2xKE-yPolD1Va0zYLa48`, 19:00 UTC daily,
   published as CSV and read via the `PORTER_CSV` secret. Confirmed
   "Porter: mapped 10 columns" in the Action log.

   **`CAMPAIGNS_CSV` is DONE too.** Export
   `2a6bfdec-6366-48b3-90da-40a67646ad7b` → the `campaigns` tab, 19:20 UTC
   daily, published as CSV. Confirmed "Campaigns: wide feed, 12 columns
   across Google, Meta" in the Action log. Nothing on the dashboard is
   hand-maintained any more; `porter_feed.csv` and `campaigns.csv` remain
   only as offline fallbacks.

   Gotchas, both cost real time once: `worksheet_id` must be
   `<spreadsheet_id>__<sheet_name>` (Porter cannot create the spreadsheet),
   and the published CSV's headers are `<connector> <label>` — "Meta Ads
   Amount spent", "GA4 Sessions" — with BOTH click columns labelled
   "Clicks". The connector prefix is what tells them apart. If a feed ever
   goes stale, check the log for "Porter: mapped N columns": a wrong header
   maps 0 and `merge_previous` then keeps the last good values on screen,
   so the dashboard looks fine while quietly freezing.

   **Porter free tier = 3 accounts + 30-day lookback.** Meta, GA4 and Google
   Ads is exactly 3; destinations are free. No headroom. Only Meta genuinely
   needs Porter — Google Ads links natively into GA4, and GA4 has a free API
   with full history, so that is the escape route if Porter starts charging.
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
