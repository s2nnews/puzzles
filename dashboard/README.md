# Premium Puzzles — Marketing Dashboard

A one-page, always-on marketing dashboard for Premium Puzzles Australia. Sales,
funnel, margin, the profit waterfall, subscribers and email — with a date-range
picker that recomputes every sheet-backed metric for any range and its previous
period.

**Live:** https://s2nnews.github.io/puzzles/dashboard/

It's a single static `index.html` — no server, no build step. It fetches its
numbers from a **published CSV** of the "Cockpit Daily" Google Sheet, so the
date picker can recompute any range in the browser. Anyone with the link can
open it (no login) — good for family and collaborators.

> **Read the docs before changing anything:** `ARCHITECTURE.md` (the whole
> system + all IDs/URLs), `DATA-SOURCES.md` (which column comes from where),
> `STATUS.md` (current state, gaps, next steps, credential boundary).

## Current state (read this — it's honest)
- The **dashboard is live** and correctly reads the sheet's published CSV.
- **But the sheet is currently a static snapshot** (frozen to values, stuck at
  26 Jul 2026). The daily auto-refresh that would keep it live **has not been
  deployed yet** — so it does *not* refresh every morning today. Making it
  self-updating is the open task; see `STATUS.md`.
- Three columns (Meta spend/conv, Puzzles sold, Shipping cost) are still blank
  for the same reason — the refresh that fills them hasn't run.

## Data sources (see DATA-SOURCES.md for the column map)
- **Shopify** — sales, orders, AOV, session funnel, units
- **Omnisend** — subscribers, campaigns
- **Meta → Porter** (free, rolling 30-day) — the *only* thing Porter is used for
- **Google Ads** — native connector / "latest known" in the dashboard CONFIG
- **ShipStation** — carrier shipping cost (the "bleed")

## What's live vs. "latest known"
Fully range-aware from the daily sheet (once it's refreshing): total sales,
orders, net sales, AOV, returns, the funnel, conversion rate, subscribers, the
shipping bleed, Meta spend/ROAS, the contribution waterfall and both trend
charts. Carried as "latest known" CONFIG constants until they get their own
daily columns: Google Ads spend/ROAS, gross-margin %, 12-month LTV, repeat rate,
the email campaign table, revenue-by-channel and the traffic donut.

## Setup (already done)
1. Sheet's Daily tab published to web as CSV — done.
2. CSV URL pasted into `index.html` (`var SHEET_CSV_URL = '…'`) — done.
3. GitHub Pages enabled (Deploy from branch `main` / root) — done.

## Files
- `index.html` — the dashboard (what Pages serves).
- `ARCHITECTURE.md`, `DATA-SOURCES.md`, `STATUS.md` — the docs.
- `apps-script/MarketingDashboardRefresh.gs` — the daily-refresh script, **drafted
  but not yet deployed** (kept for when we stand up the live refresh).
