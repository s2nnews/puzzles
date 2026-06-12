"""Community mention velocity for the Premium Puzzles Index.

For every tracked title and brand, counts posts in the last 30 days via the
public search JSON endpoint: in r/Jigsawpuzzles for titles, and brand terms
across the subreddit for brands. One row per (run_date, entity).

Usage:
    python scrapers/reddit_signals.py            # full tracked list
    python scrapers/reddit_signals.py --limit 5  # smoke test
"""

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RAW_DIR, clean_title_query, load_tracked_titles, polite_sleep

SEARCH_URL = "https://oauth.reddit.com/r/Jigsawpuzzles/search"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
DEFAULT_DB = RAW_DIR / "reddit_signals.db"
CREDS_FILE = RAW_DIR / "reddit_creds.json"  # gitignored; {"client_id":..,"client_secret":..}
USER_AGENT = "premium-puzzles-index/0.1 (market research)"


def get_token(session: requests.Session) -> str | None:
    """App-only OAuth token. Anonymous JSON access has been 403'd since the
    2023 API changes, so read-only search needs a (free) script app."""
    import os
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not client_id and CREDS_FILE.exists():
        creds = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
        client_id, client_secret = creds.get("client_id"), creds.get("client_secret")
    if not client_id or not client_secret:
        print(
            "Missing Reddit credentials. Create a free 'script' app at\n"
            "https://www.reddit.com/prefs/apps then either set\n"
            "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET env vars or write\n"
            f"{CREDS_FILE}\n"
            'as {"client_id": "...", "client_secret": "..."}',
            file=sys.stderr,
        )
        return None
    resp = session.post(TOKEN_URL, auth=(client_id, client_secret),
                        data={"grant_type": "client_credentials"}, timeout=30)
    if resp.status_code != 200:
        print(f"Token request failed: HTTP {resp.status_code} {resp.text[:200]}",
              file=sys.stderr)
        return None
    return resp.json().get("access_token")


def search_mentions(session: requests.Session, query: str) -> dict | None:
    """Posts matching `query` in the last month. None if request failed."""
    params = {"q": query, "restrict_sr": 1, "sort": "new", "t": "month", "limit": 100}
    for attempt in range(3):
        try:
            resp = session.get(SEARCH_URL, params=params, timeout=30)
        except requests.RequestException as exc:
            print(f"  request error: {exc}", file=sys.stderr)
            polite_sleep(10, 20)
            continue
        if resp.status_code == 200:
            posts = [c["data"] for c in resp.json().get("data", {}).get("children", [])]
            return {
                "mentions_30d": len(posts),
                "total_score": sum(p.get("score", 0) for p in posts),
                "total_comments": sum(p.get("num_comments", 0) for p in posts),
            }
        print(f"  HTTP {resp.status_code} for {query!r}, backing off", file=sys.stderr)
        polite_sleep(15 * (attempt + 1), 30 * (attempt + 1))
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
            mentions_30d   INTEGER,
            total_score    INTEGER,
            total_comments INTEGER,
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
    session.headers["User-Agent"] = USER_AGENT
    token = get_token(session)
    if token is None:
        return 1
    session.headers["Authorization"] = f"Bearer {token}"

    run_date = date.today().isoformat()
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = init_db(args.db)
    written = failed = 0
    for entity_type, entity, query in targets:
        result = search_mentions(session, query)
        if result is None:
            failed += 1
            continue
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO reddit_snapshots
                   (run_date, scraped_at, entity_type, entity, query,
                    mentions_30d, total_score, total_comments)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (run_date, scraped_at, entity_type, entity, query,
                 result["mentions_30d"], result["total_score"], result["total_comments"]),
            )
        written += 1
        print(f"  {entity_type:<5} {entity:<40} mentions={result['mentions_30d']:<4} "
              f"score={result['total_score']}")
        polite_sleep(2, 4)
    conn.close()

    print(f"Done: {written} entities written for {run_date} ({failed} failed) -> {args.db}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
