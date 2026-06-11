# Puzzle Market Index — Design

The framing is deliberately global-macro: the AU puzzle market is treated as
an asset market. Titles are constituents, brands are sectors, demand proxies
are prices. Every analytic below has a direct equity-market analogue, which
also makes it instantly narratable in the newsletter.

## 1. Demand proxies (per title, per day)

| Signal | Proxy for | Cadence | Notes |
|---|---|---|---|
| Marketplace sales rank (inverted, log-scaled) | Current sales velocity | Daily | The highest-signal source. Log scale because rank 5→10 means far more than 500→505. |
| Review-count delta (7d) | Realised sales | Daily | Reviews are a lagging but *cumulative* sales proxy; the 7-day delta is the cleanest "volume" series we have. |
| Search interest (AU + worldwide) | Forward demand / awareness | Weekly | Worldwide series gives the "trending globally, not yet here" lead indicator. |
| Competitor stock-outs | Demand pressure / scarcity | Daily | A title that goes and stays out of stock across retailers is being bought faster than it's replenished. |
| Community mention velocity | Enthusiast attention | Weekly | Early-adopter signal; enthusiasts move before the mass market. |

## 2. Title score

Initial weights (tunable):

```
title_score = 0.40 * rank_score        # inverted, log-scaled sales rank
            + 0.25 * trend_score       # AU search interest, 0-100
            + 0.20 * stock_pressure    # out-of-stock breadth across retailers
            + 0.15 * community_score   # mention velocity z-score
```

Each component is normalised to 0–100 cross-sectionally before weighting.
Also computed per title: `momentum` (7-day change in score) and
`global_signal` (worldwide search interest, the lead indicator).

## 3. Index construction

- **Puzzle Market Index (headline):** review-velocity-weighted average of
  title scores across the tracked universe, rebased to 100 at inception.
  Review-velocity weighting is the analogue of cap weighting: big sellers
  move the index more.
- **Equal-weight index:** same constituents, equal weights. The spread
  between cap-weight and equal-weight is the first concentration tell,
  exactly as in equities.
- **Brand sub-indices:** Ravensburger, Funbox, Cobble Hill, Gibsons,
  Blue Opal, Other. These are the "sectors".

## 4. Market-internals layer (the macro dashboard)

- **Top-7 share:** fraction of total review velocity captured by the top 7
  titles. The "Magnificent Seven" question, answered daily.
- **HHI (Herfindahl-Hirschman):** concentration across brands and across
  titles. Rising HHI = hit-driven market; falling = broad-based demand.
- **Breadth:** % of titles with improving sales rank week-over-week
  (advance/decline line for puzzles).
- **Stock-out diffusion index:** % of tracked titles out of stock at one or
  more retailers. The demand-pressure gauge.
- **Regime classification:** expansion / contraction / rotation, from index
  momentum + breadth together. Breadth-confirmed uptrend = expansion;
  rising index on falling breadth = narrow hit-driven rally.

## 5. Relative rotation (flagship visual candidate)

RRG-style quadrant: each title (or brand) plotted by relative strength vs
the index (x) against the momentum of that relative strength (y), with
trails. Quadrants: Improving → Leading → Weakening → Lagging. This shows
*rotation* — which titles are coming, which are going — which a static
bubble chart cannot.

The original bubble chart (momentum × score × review volume) remains the
simplest mobile-friendly fallback and may ship first.

## 6. Outputs

`data/processed/index.json`, one object per title plus a `market` block:

```json
{
  "as_of": "2026-06-11",
  "market": {
    "index_level": 112.4,
    "index_mom_7d": 1.8,
    "equal_weight_level": 104.1,
    "top7_share": 0.41,
    "hhi_titles": 0.062,
    "breadth_pct": 58,
    "stockout_diffusion": 0.22,
    "regime": "expansion",
    "brand_indices": {"Ravensburger": 118.0, "Funbox": 96.2}
  },
  "titles": [
    {
      "title": "My Haven No.7: The Beach Hut",
      "brand": "Ravensburger",
      "piece_count": 1000,
      "index_score": 87.3,
      "momentum": 4.2,
      "rs_ratio": 103.1,
      "rs_momentum": 1.4,
      "review_count": 843,
      "avg_rating": 4.8,
      "price_au": 39.99,
      "global_signal": 72,
      "last_updated": "2026-06-11"
    }
  ]
}
```

## 7. Build order

1. **Done:** daily snapshot scraper → SQLite (`scrapers/amazon_bsr.py`).
   Needs ~7 days of history before momentum and review-delta series exist.
2. Search-interest scraper (weekly, pytrends, AU + worldwide).
3. Retailer stock scraper (Big W / Myer / Toy Universe, playwright).
4. Community mention scraper (weekly).
5. `pipeline/aggregate.py` + `pipeline/export.py` → index.json.
6. GitHub Actions cron (after local validation period).
7. Web visualisation (RRG and/or bubble chart) for Shopify embed.

## 8. Disclosure posture

Public statement: "The Premium Puzzles Index is derived from multiple public
data sources across retail, search, and community platforms." Raw source
data is never published; only derived scores leave this repo. The weighting
methodology is the IP.
