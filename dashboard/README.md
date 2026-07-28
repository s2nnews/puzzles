# Premium Puzzles — Marketing Dashboard

A one-page, always-on marketing dashboard for Premium Puzzles Australia. Sales,
funnel, margin, the profit waterfall, subscribers and email, with a date-range
picker that recomputes every daily metric for any range and its previous
period.

**Live:** <https://s2nnews.github.io/puzzles/dashboard/>

It's a single static `index.html` served by GitHub Pages. The page reads
`./data.json`, an array of one object per day, which a Python collector
rebuilds every night. No Google Sheet, no Apps Script, no login.

Background docs: `ARCHITECTURE.md` (system design), `DATA-SOURCES.md`
(which column comes from where), `STATUS.md` (state and next steps). Where
they mention the Google Sheet / Apps Script pipeline, that path is retired;
this README describes the current system.

## How the data flows

1. `collect.py` pulls the daily series from the source APIs:
   sales and the sessions funnel via ShopifyQL, units sold via the Orders
   API (bucketed by Sydney day), subscriber growth from the email platform,
   and shipping cost per ship date from ShipStation. Meta spend and
   conversion value come from an optional CSV export (`META_CSV`); those two
   columns stay blank until it's configured.
2. It writes `data.json` (sorted by Date ascending, blanks = ""; the page
   treats blanks as 0).
3. `.github/workflows/dashboard.yml` runs the collector nightly (~06:00
   Sydney), and commits `data.json` when it changed. GitHub Pages redeploys
   automatically.

## Running the collector locally

```sh
pip install -r dashboard/requirements.txt
cp dashboard/.env.example dashboard/.env   # fill in the keys
python dashboard/collect.py
```

Config comes from the environment or `dashboard/.env` (gitignored). The same
names are the repo's Actions secrets: `SHOPIFY_STORE`, `SHOPIFY_TOKEN`
(Admin API, scopes `read_orders` + `read_reports`), `OMNISEND_API_KEY`,
`SHIPSTATION_API_KEY`, `SHIPSTATION_API_SECRET`, optional `META_CSV`,
optional `DAYS` (default 120).

## What's live vs. "latest known"

Fully range-aware from the daily feed: total sales, orders, net sales, AOV,
returns, the funnel, conversion rate, subscribers, the shipping bleed,
Meta spend/ROAS (once `META_CSV` is set), the contribution waterfall and
both trend charts.

Shown as "latest known" until they get their own daily columns: Google Ads
spend/ROAS, gross-margin %, 12-month LTV, repeat rate, the email campaign
table, revenue-by-channel and the traffic donut.

## Privacy

The Pages URL and `data.json` are reachable by anyone who has the link;
that's what makes no-login sharing possible. The numbers aren't indexed or
advertised, but they aren't access-controlled either. If you later want to
gate it, a passphrase layer or Cloudflare Access can sit in front without
changing any of this.

## Files

- `index.html` — the dashboard (what Pages serves).
- `data.json` — the daily feed the page reads. Rebuilt nightly; don't edit
  by hand.
- `collect.py` — the collector. stdlib + requests only.
- `.env.example` — template for local keys. Copy to `.env` (gitignored).
- `ARCHITECTURE.md`, `DATA-SOURCES.md`, `STATUS.md` — background docs.
- `../.github/workflows/dashboard.yml` — the nightly refresh.
