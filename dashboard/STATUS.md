# Status & next steps

_Snapshot: 28 Jul 2026 (evening). Update this whenever state changes._

## What's working right now
- **Dashboard is LIVE and public:** https://s2nnews.github.io/puzzles/dashboard/
  (GitHub Pages, no login — shareable with family / collaborators).
- **The Google Sheet + Apps Script pipeline is RETIRED.** The page now reads
  `./data.json` from the repo; `collect.py` (stdlib + requests) rebuilds it
  from the source APIs, and `.github/workflows/dashboard.yml` runs it nightly
  (~06:00 Sydney) and commits the result. Mentions of the published-CSV /
  Apps Script path in `ARCHITECTURE.md` / `DATA-SOURCES.md` describe the old
  system; the column→source map in `DATA-SOURCES.md` is still accurate.
- `data.json` currently covers **2026-03-30 to 2026-07-28** including sales,
  orders, AOV, funnel, conversion, units (Puzzles sold) and email
  subscribes/unsubscribes.

## The gap
1. **Actions secrets not yet set.** The nightly workflow needs repo secrets
   `SHOPIFY_STORE`, `SHOPIFY_TOKEN`, `OMNISEND_API_KEY`,
   `SHIPSTATION_API_KEY`, `SHIPSTATION_API_SECRET`, optional `META_CSV`.
   All keys are validated and working locally (dashboard/.env). Until the
   repo secrets are set the nightly run fails and the data stays at 28 Jul.
2. **Sessions funnel is frozen at 28 Jul.** `shopifyqlQuery` is denied to
   third-party apps on the Basic plan (it demands Level 2 protected
   customer data, which Basic cannot grant). Sales are now DERIVED from
   the Orders API instead (validated to 0.07% vs ShopifyQL history);
   sessions have no API source on Basic. Next step: GA4 as the funnel
   source. The merge logic preserves all existing funnel history.
3. **Meta spend / conv value are blank** — needs a Porter → Sheets/CSV export
   (columns: date,spend,conv_value) and its URL in `META_CSV`.
4. **Subscriber list size is blank** — no daily source wired yet (candidate:
   Omnisend contacts count for the current day only).

## Credential boundary (unchangeable)
Claude never sees or types API keys. Mike sets them in two places:
- Locally: `dashboard/.env` (copy from `.env.example`; gitignored).
- GitHub: repo Settings → Secrets and variables → Actions, same names.

## Open decisions
1. **Sessions source:** keep Shopify's sessions dataset (as built), or switch
   the funnel to GA4 later. ShopifyQL sessions works on API 2025-07 and is
   what collect.py uses today.
2. **Meta feed:** stand up the Porter export, or drop the Meta columns.

## Fast facts for next time (so we don't re-derive)
- On Admin API 2025-07 `shopifyqlQuery` returns `{ parseErrors, tableData
  { columns, rows } }` directly — there is NO `TableResponse` type to
  fragment on; `rows` is a JSON scalar (list of dicts keyed by column name,
  values as strings).
- Omnisend analytics: POST `/v5/analytics/statistics`, max 60 days per query
  at day granularity, ranges can't cross a calendar year, `to` is exclusive,
  10 req/min. 2026-07-07 shows +24,059 / −21,007 email subs — that's the
  Klaviyo→Omnisend list migration, not organic growth.
- The `s2nnews/puzzles` repo is the **Puzzle Index** project; the dashboard is
  an isolated `dashboard/` subfolder. `run_daily.py` does not touch it.
