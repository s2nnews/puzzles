# puzzles — Claude Code project context

This repo is the **Premium Puzzles Index**: a market-intelligence pipeline
that treats the AU jigsaw puzzle market like an asset market. Read
`docs/INDEX_DESIGN.md` first — it is the authoritative model (signals,
weights, index construction, build order).

This repo is **public**. Rules that follow from that:

- `data/raw/` is gitignored. Never commit raw scraped data, only the derived
  `data/processed/index.json`.
- No supplier names, wholesale prices, margins, or Shopify sales figures in
  any committed file. Full business context lives in the parent working
  folder's CLAUDE.md (local only, outside this repo).
- Public-facing language: the Index is "derived from multiple public data
  sources across retail, search, and community platforms". Never name a
  source platform in published outputs (index.json, charts, site copy).

Conventions:

- Python, stdlib + requests/bs4/pandas. Keep it boring and dependency-light.
- Scrapers are polite: 2–5s sleeps, UA rotation, CAPTCHA detect + backoff,
  fail loudly rather than writing partial garbage.
- SQLite for raw storage, one snapshot table per source, primary key on
  (run_date, entity) so re-runs are idempotent.
- Local-first: scrapers run on Michael's PC during validation; GitHub
  Actions cron comes only after the data has been eyeballed for ~a week.

Owner: Michael ("the Puzzle King"). He thinks in global-macro terms —
concentration, breadth, regimes, rotation. Frame analytics and naming that
way.
