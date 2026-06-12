# Scraping Learnings — what the first two days taught us

Hard-won, tested-live knowledge from building the Index's collection layer
(2026-06-11/12). Read this before touching any scraper or adding a new
source. Every item here cost real debugging time; don't re-learn it.

## The big architectural discovery: sitemaps + product pages beat search pages

Retailer **search pages** are where the defences are: bot walls
(Big W / Akamai), client-side rendering with an empty server shell
(Big W, Myer, Puzzle Palace AJAX search). Fighting them with headless
browsers fails — Akamai kills headless Chromium *and* headless Edge at the
protocol level (`ERR_HTTP2_PROTOCOL_ERROR`) before a byte of HTML arrives.

Retailer **product pages**, by contrast, are server-rendered with
schema.org `Product` JSON-LD (availability + price) because they need
Google to index them. SEO is the chink in the armour: a retailer cannot
hide product pages from simple HTTP clients without hurting their ranking.

And **sitemaps** (linked from robots.txt) hand you every product URL for
free — 9,491 puzzle URLs from Big W, 2,694 products from Puzzle Palace,
including exact matches for tracked titles.

So the pattern, now encoded in `pipeline/build_retailer_urls.py` +
`scrapers/retailer_stock.py`:

1. Harvest product URLs from the sitemap (occasionally).
2. Match tracked titles to URL slugs (compare against the *de-hyphenated*
   slug so `artist's` → `artist-s` → `artists` still matches).
3. Check stock daily by fetching product pages and parsing JSON-LD.

Use this pattern for any new retailer before reaching for playwright.

## Every source has a different temper

| Source | Tolerance | Encoded as |
|---|---|---|
| Amazon AU | Brisk is fine: 100-product pass with 2–5s sleeps, twice, no blocks. Occasional soft block = HTTP 200 with zero product cards; retry it like a block, not a layout change. | `amazon_bsr.py` empty-page retry |
| Reddit RSS | ~1 request / 10s. 429s are routine and heal with backoff. | 12–20s sleeps |
| eBay AU | The harshest: bot wall goes **sticky after ~5 quick queries and then blocks for hours**. Once triggered, stop — retrying feeds it. | 30–60s between titles, default |
| Google Trends | Longest cooldown: a 429 outlasts polite 60–90s retries; can take 10+ min to hours. Don't hammer; let the next scheduled run pick it up. | retry-once-then-skip |
| Retailer product pages | Gentle daily volume (dozens of URLs) is fine. Big W needs a warmed session (homepage first, for Akamai cookies). | `WARMUP` map in `retailer_stock.py` |

Corollary: probing/debugging a source repeatedly in one sitting burns the
IP for that source — spread validation across days, or accept tomorrow's
run as the validation.

## Side doors that worked

- **Reddit**: anonymous JSON API is 403'd since the 2023 API changes, but
  **`search.rss` still serves without credentials** (cap: 25 entries per
  query, no scores). No OAuth app, no secrets in CI. The 25-cap binding is
  itself a signal (brand-level Ravensburger pegs it; titles sit at 0–2).
- **WooCommerce stores**: `/wp-json/wc/store/v1/products` was 401 here,
  but Yoast SEO means a `sitemap_index.xml` with full product URL lists.
- **Shopify stores** (none in the current set, for the future):
  `/products.json` and `/search/suggest.json` are public by default.

## Parsing gotchas that produced silently-wrong data

These are the dangerous ones — the run "succeeds" with bad numbers.

- **eBay fuzzy search inflates counts ~10x.** A query for one My Haven
  title returns sold listings for the *whole series*. Counts must be
  filtered to listings whose own title contains the distinctive phrase
  (`ebay_sold.py` prints `matched X/Y listings` so you can see the noise).
- **pytrends with a shared client reuses the first geo's data.** AU and
  WORLD series came back byte-identical until each geo got a **fresh
  `TrendReq` instance**. If two trends series look identical, suspect this
  before believing it.
- **pytrends + urllib3 2.x**: passing `retries=` to `TrendReq` crashes
  (`method_whitelist` was removed). Don't pass it; do your own retrying.
- **Amazon BSR must be parsed from extracted text, not raw HTML** — the
  category name sits inside an anchor, so regex on raw HTML never matches
  (`8,066 in <a>Jigsaw Puzzles</a>`).
- **Amazon review counts** live on `a[aria-label="113 ratings"]`, not a
  span; the fallback text is parenthesised `(113)`.
- **A failed stock fetch is `unknown`, never `out_of_stock`.** Conflating
  them poisons the stock-pressure series with phantom demand.

## Operational defaults now standard in this repo

- SQLite per source, snapshot table keyed `(run_date, entity)` →
  re-runs after interruption are idempotent overwrites, never duplicates.
- UA rotation + `Accept-Language: en-AU` on every scraper.
- Scrapers print what they matched/skipped; a silent success is treated
  as a bug.
- Windows console: set `PYTHONIOENCODING=utf-8` or unicode in titles
  (non-breaking hyphens, • bullets) crashes cp1252 printing mid-run.

## Market intel surfaced as a by-product (as of 2026-06-12)

- Puzzle Palace AU (dedicated puzzle retailer) had **6 of 7 tracked-title
  listings out of stock** — the entire My Haven range plus Cozy Retreat.
- eBay AU puzzles are mostly a **resale market** (median sold ≈ $10–28 vs
  ~$35 RRP) → median resale price is a *residual value* signal per title.
- Toy Universe is dead (invalid SSL cert on all hostnames) — replaced by
  Puzzle Palace in the retailer set.
- Retailer sitemaps revealed 4 untracked My Haven titles (Garden Kitchen,
  Tea Shed, Boho Retreat, Artist's Shed) — sitemap diffs double as a
  **new-release detector**, worth formalising later.
