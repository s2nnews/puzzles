# Premium Puzzles — Marketing Dashboard: Architecture

_Last updated: 27 Jul 2026. This doc exists so any future session (or person)
can pick this up without re-deriving it. If you change the system, update this._

## What it is
A single-page marketing dashboard for **Premium Puzzles Australia** (Shopify
store, `premiumpuzzlesau.myshopify.com`). It shows sales, the session→purchase
funnel, marketing efficiency (spend, ROAS, CPC, CAC), a profit waterfall
(contribution after COGS, shipping, packaging, marketing), subscriber health and
email performance — with a date-range picker.

## The stack, end to end
```
  Data sources (APIs / connectors)
        │
        ├── Shopify Admin API  → sales, orders, AOV, session funnel, units
        ├── Omnisend REST      → subscriber movement, campaigns
        ├── Meta  → via PORTER  → ad spend + purchase conv value (free, 30-day rolling)
        ├── Google Ads          → spend / ROAS (native Looker connector; full history)
        └── ShipStation v1 REST → carrier shipping cost (the "bleed")
        │
        ▼
  Google Sheet  "Premium Puzzles - Cockpit Daily (Shopify + Omnisend)"
        │   one date-keyed row per day (the single source of truth)
        │   Published to web as CSV  (File → Share → Publish to web → Daily tab → CSV)
        ▼
  Static HTML dashboard  (dashboard/index.html)
        │   fetches the published CSV on load; date picker recomputes any range
        ▼
  GitHub Pages  →  https://s2nnews.github.io/puzzles/dashboard/   (public, no login)
```

Historically the same sheet also fed a **Looker Studio** report ("Premium
Puzzles — Marketing Cockpit (GA4)"). The custom HTML dashboard replaced Looker
because Looker couldn't fit the desired one-page owner's layout. The sheet is the
shared backbone for both.

## Accounts (important — things live in different logins)
| Thing | Where it lives |
|---|---|
| Google Sheets (Cockpit Daily, Cockpit Newsletters) | **info@premiumpuzzles.com.au** (Google account, shows as **/u/5** in URLs) |
| Looker Studio report | same **info@** account (/u/5) |
| GitHub repo + Pages site | **s2nnews** GitHub org/user (this is a *GitHub* login, separate from Google) |
| Shopify / Omnisend / Porter / ShipStation | the store's own accounts; keys pasted by Mike |

Note: the GitHub repo `s2nnews/puzzles` is Mike's **Puzzle Index** project
(Amazon/eBay/Reddit/Trends scrapers → `index.json`, driven by `run_daily.py`).
The dashboard lives in its own **`dashboard/`** subfolder so it never collides
with that project. `run_daily.py` has nothing to do with the marketing sheet.

## Key IDs and URLs
| Asset | ID / URL |
|---|---|
| Cockpit Daily sheet | `1XgrRrj1H2nNblo0X1EkxCd3ItTW6QbsMU0TYRt0swnU` |
| Cockpit Newsletters sheet | `1Nx13NwyCkqvoH63eDfsobOAjd8SWNjZHoIrZFr30s34` (tab `Campaigns`) |
| Looker report | `29e9cfdd-5844-45e2-a2d9-e3c8b5812ab5` (at /u/5) |
| Published CSV feed (Daily tab) | `https://docs.google.com/spreadsheets/d/e/2PACX-1vSzdmaC7SAzqHutrEGDxKQ4OIEZTJWRTpXGn5fKRq0DeDnxX21qPy52naaM-Z_PLRDllnGPUdxTlMqO/pub?gid=0&single=true&output=csv` |
| Live dashboard | `https://s2nnews.github.io/puzzles/dashboard/` |
| Repo folder | `github.com/s2nnews/puzzles` → `dashboard/` |

## The one rule that matters
**Claude never handles API keys or secrets.** All keys/tokens are pasted by Mike
into whatever runs the refresh (e.g. Apps Script → Project Settings → Script
properties). Claude wires everything *around* the secrets. See `STATUS.md` for
the exact list of credentials and who does what.
