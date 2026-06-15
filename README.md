# Premium Puzzles Index

A daily market intelligence pipeline for the Australian jigsaw puzzle market,
built by [Premium Puzzles](https://premiumpuzzles.com.au).

The Index treats the puzzle market the way a quant treats an equity market:
titles are constituents, brands are sectors, and demand signals are prices.
It answers questions no supplier or competitor can:

- Is overall puzzle demand growing or shrinking right now?
- Which brands are gaining share, and which are bleeding it?
- Is this market broad-based, or is it an S&P 500 run by a Magnificent Seven
  of hit titles?
- Which specific puzzles are breaking out before the trade catches on?

## How it works

Scrapers collect public demand signals daily across retail, search, and
community platforms. The pipeline aggregates them into a composite score per
title, brand sub-indices, and a headline **Puzzle Market Index** level. The
scoring methodology and weights are the proprietary part.

```
scrapers/   -> data/raw/ (local only, never committed)
pipeline/   -> data/processed/index.json (the published output)
web/        -> interactive visualisations embedded on the website
```

The only data published from this repo is the derived index in
`data/processed/index.json`. Raw source data stays local.

## Status

Collection layer (four sources) and the Index scoring engine are built and
running. `python run_daily.py` collects today's due sources and rebuilds
`data/processed/index.json`. A daily local task + a GitHub Actions cron keep
it fresh (see `docs/OPERATIONS.md`). The web visualisation is the remaining
piece. Model: `docs/INDEX_DESIGN.md`. Hard-won scraping knowledge:
`docs/SCRAPING_LEARNINGS.md`.
