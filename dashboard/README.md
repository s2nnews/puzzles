# Premium Puzzles — Marketing Dashboard

A one-page, always-on marketing dashboard for Premium Puzzles Australia. Sales,
funnel, margin, the profit waterfall, subscribers and email — with a date-range
picker that recomputes every sheet-backed metric for any range and its previous
period.

**Live:** https://s2nnews.github.io/puzzles/  *(after the one-time setup below)*

It's a single static `index.html` — no server, no build step. It reads its
numbers from a Google Sheet that a daily Apps Script keeps current, so the page
refreshes itself every morning. Anyone with the link can open it (great for
family and collaborators); there's no login.

## One-time setup (~5 min)

**1 · Publish the sheet's data as a public CSV**
In the Google Sheet that the daily script writes to: **File → Share → Publish to
web**. Under *Link*, choose the **Daily** tab and **Comma-separated values
(.csv)**, then **Publish**. Copy the URL it gives you (it looks like
`https://docs.google.com/spreadsheets/d/e/…/pub?gid=…&single=true&output=csv`).

**2 · Paste that URL into `index.html`**
Near the top of the `<script>` block, find:

```js
var SHEET_CSV_URL = '';
```

and put your CSV link between the quotes:

```js
var SHEET_CSV_URL = 'https://docs.google.com/spreadsheets/d/e/…/output=csv';
```

**3 · Enable GitHub Pages**
Repo **Settings → Pages → Build and deployment → Source: Deploy from a branch →
Branch: `main` / `/root` → Save.** After a minute the site is live at
`https://s2nnews.github.io/puzzles/`. Share that link with anyone.

That's it. The daily 6am trigger appends a row to the sheet; the published CSV
updates automatically; the page shows current numbers on every open. You only
touch the repo again if you want to change the dashboard itself.

## What's live vs. "latest known"

Fully range-aware from the daily sheet: total sales, orders, net sales, AOV,
returns, the funnel, conversion rate, subscribers, the shipping bleed, Meta
spend/ROAS, the contribution waterfall and both trend charts.

Shown as "latest known" until they get their own daily columns (a clean phase 2):
Google Ads spend/ROAS, gross-margin %, 12-month LTV, repeat rate, the email
campaign table, revenue-by-channel and the traffic donut.

## Privacy

The Pages URL and the published CSV are both reachable by anyone who has the
link — that's what makes no-login sharing possible. The numbers aren't indexed
or advertised, but they aren't access-controlled either. If you later want to
gate it, a passphrase layer or Cloudflare Access can sit in front without
changing any of this.

## Files

- `index.html` — the dashboard (this is what Pages serves).
- `apps-script/MarketingDashboardRefresh.gs` — the daily refresh that populates
  the sheet (already running in your Apps Script project; kept here for
  reference/version history).
