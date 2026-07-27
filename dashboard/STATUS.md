# Status & next steps

_Snapshot: 27 Jul 2026. Update this whenever state changes._

## What's working right now
- **Dashboard is LIVE and public:** https://s2nnews.github.io/puzzles/dashboard/
  (GitHub Pages, no login — shareable with family / collaborators).
- It reads the **published CSV** of the Cockpit Daily sheet, so the date-range
  picker recomputes every sheet-backed metric for any range + its prior period.
- Sales, orders, AOV, net sales, returns, the funnel, conversion, the
  contribution waterfall and the trend charts are all driven from the sheet.

## The gap (be honest about this)
1. **The sheet is a FROZEN snapshot, not a live feed.** During the earlier build
   the Daily columns (A–P) were populated and then **frozen to static values**
   (Ctrl+Shift+V paste-values) for the old Looker setup. Freezing severed the
   live link. So the data is currently stuck at **26 Jul 2026** and does not
   auto-update.
2. **The daily-refresh script was never deployed.** A Google Apps Script
   (`MarketingDashboardRefresh.gs`) was written to pull Shopify + Omnisend +
   Meta(Porter) + ShipStation into the sheet daily. It was handed over as
   "paste your keys and deploy" — but it was **never actually deployed**
   (confirmed: no Apps Script is bound to the sheet; the account's project list
   is empty of it). This is why nothing refreshes the sheet.
3. **Three columns are blank** (Meta spend/conv, Puzzles sold, Shipping cost)
   for the same single reason: the refresh that fills them never ran.

## To make it genuinely live + complete
Reconnect the Cockpit Daily sheet to its sources so it refreshes daily, then let
the published CSV carry it to the dashboard automatically:

- **Meta** → Porter (free, 30-day) — see `DATA-SOURCES.md`.
- **Google / sessions** → Shopify session report as built (or GA4 if we decide
  to switch — open question below).
- **Shopify sales + units** → Shopify Admin API.
- **Omnisend** → Omnisend REST.
- **Shipping cost** → ShipStation.

**Do NOT** run a full-sheet-clearing refresh alongside another writer — one
writer only, or they fight. Right now there is no live writer, so standing up
one clean refresh is safe.

## Credential boundary (unchangeable)
Claude never sees or types API keys. Mike pastes these into the refresh's
Script Properties:
- `SHOPIFY_TOKEN` — must include the **`read_orders`** scope (units pull needs it)
- `OMNISEND_API_KEY`
- `SHIPSTATION_API_KEY` + `SHIPSTATION_API_SECRET`
- Meta: via **Porter** (already authorized in Porter — no raw token to mint)

## Open decisions (confirm before building)
1. **Sessions source:** keep Shopify's session report (as built), or switch the
   funnel to **GA4**? Mike has referred to a "Google source" — clarify whether
   that means GA4 for traffic or just the Google Ads channel.
2. **Refresh runner:** the drafted Apps Script (Mike pastes ~4 keys), vs a
   Porter Google-Sheets export for Meta plus a lighter script for the rest.

## Housekeeping done
- Custom-domain error on GitHub Pages: cleared.
- `dashboard/README.md` "Live" link points at `/puzzles/` — should be
  `/puzzles/dashboard/`. Fix on next repo edit.

## Fast facts for next time (so we don't re-derive)
- Sheet is owned by **info@premiumpuzzles.com.au** (Google /u/5), NOT the
  michael@ login.
- The `s2nnews/puzzles` repo is the **Puzzle Index** project; the dashboard is
  an isolated `dashboard/` subfolder. `run_daily.py` does not touch the sheet.
- Published CSV URL and all IDs are in `ARCHITECTURE.md`.
