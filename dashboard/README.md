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
   sales metrics and units derived from the Shopify Orders API (bucketed by
   Sydney day; ShopifyQL is tried first but is denied to third-party apps
   on the Basic plan), subscriber growth from the email platform, and
   shipping cost per ship date from ShipStation. The advertising funnel
   (GA4 sessions/cart/checkout/purchases, plus Meta and Google Ads spend,
   conversion value and clicks) comes from one Porter blend export read via
   `PORTER_CSV`, defaulting to `dashboard/porter_feed.csv`.
2. It writes `data.json` (sorted by Date ascending, blanks = ""; the page
   treats blanks as 0), merging over the previous file so an existing value
   is never replaced by a blank. That merge is what keeps history older than
   Porter's rolling 30-day free-tier window.
3. `run_daily.py` runs the collector once a day on the at-logon trigger and
   publishes `data.json` with the Index files, so the site updates whenever
   the laptop is opened. `.github/workflows/dashboard.yml` can do the same
   nightly in the cloud, but its cron is commented out.

## Running the collector locally

```sh
pip install -r dashboard/requirements.txt
cp dashboard/.env.example dashboard/.env   # fill in the keys
python dashboard/collect.py
```

Config comes from the environment or `dashboard/.env` (gitignored, as is
anything else matching `dashboard/.env*` — this repo is public). The same
names serve as Actions secrets: `SHOPIFY_STORE`, `SHOPIFY_TOKEN` (Admin API,
`read_orders`; or `SHOPIFY_CLIENT_ID` + `SHOPIFY_CLIENT_SECRET` for a Dev
Dashboard app), `OMNISEND_API_KEY`, `SHIPSTATION_API_KEY`,
`SHIPSTATION_API_SECRET`, optional `PORTER_CSV`, optional `DAYS`
(default 120).

## What's live vs. "latest known"

Fully range-aware from the daily feed: total sales, orders, net sales, AOV,
returns, the funnel, conversion rate, subscribers, the shipping bleed, ad
spend, blended ROAS, cost per click, Google and Meta ROAS, paid CAC, the
contribution waterfall and both trend charts.

Shown as "latest known" until they get their own daily columns: gross-margin
%, 12-month LTV, repeat rate, the email campaign table, revenue-by-channel
and the traffic donut.

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
- `porter_feed.csv` — GA4 + Meta + Google Ads daily rows from Porter. The
  default `PORTER_CSV`; point that at a published Sheet URL to automate it.
- `.env.example` — template for local keys. Copy to `.env` (gitignored).
- `ARCHITECTURE.md`, `DATA-SOURCES.md`, `STATUS.md` — background docs.
- `../.github/workflows/dashboard.yml` — the nightly refresh.
