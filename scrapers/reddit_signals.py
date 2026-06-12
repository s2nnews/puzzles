"""Community mention velocity for the Premium Puzzles Index.

Counts posts in the last 30 days mentioning each tracked title and brand in
r/Jigsawpuzzles, via the public RSS search endpoint. The JSON API has been
403'd for anonymous use since the 2023 API changes, but RSS still serves
without credentials — capped at 25 entries per query, which is fine for
niche titles (the cap binding IS the signal that something is hot).

Usage:
    python scrapers/reddit_signals.py            # full tracked list
    python scrapers/reddit_signals.py --limit 5  # smoke test
"""

import argparse
import re
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RAW_DIR, USER_AGENTS, clean_title_query, load_tracked_titles, polite_sleep

SEARCH_RSS = "https://www.reddit.com/r/Jigsawpuzzles/search.rss"
DEFAULT_DB = RAW_DIR / "reddit_signals.db"
MAX_ENTRIES = 25  # RSS hard cap per query


def search_mentions(session: requests.Session, query: str) -> int | None:
    """Number of posts matching `query` in the last month (capped at 25).
    None if all attempts failed."""
    params = {"q": query, "restrict_sr": 1, "sort": "new", "t": "month",
              "limit": MAX_ENTRIES}
    import random
    for attempt in range(1, 4):
        session.headers["User-Agent"] = random.choice(USER_AGENTS)
        try:
            resp = session.get(SEARCH_RSS, params=params, timeout=30)
        except requests.RequestException as exc:
            print(f"  request error: {exc}", file=sys.stderr)
            polite_sleep(10, 20)
            continue
        if resp.status_code == 200:
            return len(re.findall(r"<entry>", resp.text))
        print(f"  HTTP {resp.status_code} for {query!r} "
              f"(attempt {attempt}/3), backing off", file=sys.stderr)
        polite_sleep(20 * attempt, 40 * attempt)
    return None


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reddit_snapshots (
            run_date       TEXT NOT NULL,
            scraped_at     TEXT NOT NULL,
            entity_type    TEXT NOT NULL,   -- 'title' | 'brand'
            entity         TEXT NOT NULL,
            query          TEXT,
            mentions_30d   INTEGER,         -- capped at 25 by the RSS endpoint
            total_score    INTEGER,         -- unavailable via RSS, kept for future
            total_comments INTEGER,         -- unavailable via RSS, kept for future
            PRIMARY KEY (run_date, entity_type, entity)
        )
    """)
    return conn


def main() -> int:
    ap = argparse.ArgumentParser(description="Community mention snapshot (source D)")
    ap.add_argument("--limit", type=int, default=None, help="only first N titles (smoke test)")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()

    titles = load_tracked_titles()
    if args.limit:
        titles = titles[: args.limit]
    brands = sorted({t["brand"] for t in titles})

    targets = [("title", t["title"], f'"{clean_title_query(t["title"])}"') for t in titles]
    targets += [("brand", b, b) for b in brands]

    session = requests.Session()
    run_date = date.today().isoformat()
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = init_db(args.db)
    written = failed = 0
    for entity_type, entity, query in targets:
        mentions = search_mentions(session, query)
        if mentions is None:
            failed += 1
            continue
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO reddit_snapshots
                   (run_date, scraped_at, entity_type, entity, query,
                    mentions_30d, total_score, total_comments)
                   VALUES (?,?,?,?,?,?,NULL,NULL)""",
                (run_date, scraped_at, entity_type, entity, query, mentions),
            )
        written += 1
        capped = " (capped)" if mentions >= MAX_ENTRIES else ""
        print(f"  {entity_type:<5} {entity:<40} mentions={mentions}{capped}")
        # Anonymous RSS rate-limits around 1 req / 10s; slower = fewer 429 retries.
        polite_sleep(12, 20)
    conn.close()

    print(f"Done: {written} entities written for {run_date} ({failed} failed) -> {args.db}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
