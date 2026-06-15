"""Realised-transaction signal for the Premium Puzzles Index.

For each tracked title, scrapes the sold/completed listings search on the
AU marketplace and records how many units sold in the last 30/90 days plus
the median sold price. This is the only source that shows actual
transactions rather than rank or attention proxies.

Usage:
    python scrapers/ebay_sold.py             # full tracked list
    python scrapers/ebay_sold.py --limit 3   # smoke test
"""

import argparse
import re
import sqlite3
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (RAW_DIR, clean_title_query, fetch, load_tracked_titles,
                    make_soup, polite_sleep)

SEARCH_URL = "https://www.ebay.com.au/sch/i.html"
DEFAULT_DB = RAW_DIR / "ebay_sold.db"
BLOCK_MARKERS = ("Pardon our interruption", "Reference ID:", "challenge-form")


def parse_sold_listings(html: str) -> list[dict]:
    """Sold items: price + sold date, newest first."""
    soup = make_soup(html)
    items = []
    for card in soup.select("li.s-item, li.s-card"):
        text = card.get_text(" ", strip=True)
        if "Shop on eBay" in text:  # placeholder card eBay injects first
            continue
        m_date = re.search(r"Sold\s+(\d{1,2}\s+\w{3}\s+\d{4})", text)
        if not m_date:
            continue
        try:
            sold = datetime.strptime(m_date.group(1), "%d %b %Y").date()
        except ValueError:
            continue
        m_price = re.search(r"AU \$([\d,]+\.?\d*)", text)
        price = float(m_price.group(1).replace(",", "")) if m_price else None
        title_el = card.select_one(".s-item__title, .s-card__title")
        item_title = title_el.get_text(" ", strip=True) if title_el else text
        items.append({"sold_date": sold, "price": price, "title": item_title})
    return items


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ebay_snapshots (
            run_date          TEXT NOT NULL,
            scraped_at        TEXT NOT NULL,
            title             TEXT NOT NULL,
            brand             TEXT,
            query             TEXT,
            sold_30d          INTEGER,
            sold_90d          INTEGER,
            median_price_30d  REAL,
            PRIMARY KEY (run_date, title)
        )
    """)
    return conn


def main() -> int:
    ap = argparse.ArgumentParser(description="Sold-listing snapshot (source E)")
    ap.add_argument("--limit", type=int, default=None, help="only first N titles (smoke test)")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    # eBay's bot wall goes sticky after ~5 quick queries and blocks for hours.
    # Sold-counts are 30/90-day windows, so a title doesn't need daily refresh:
    # rotate a small slice each day (default 5) and the full set still cycles
    # roughly weekly while staying under the wall. Slice is date-derived so
    # it's deterministic and stateless (cron-safe).
    ap.add_argument("--rotate", type=int, default=5,
                    help="titles per run; 0 = all (set cycles ~weekly)")
    ap.add_argument("--delay-min", type=float, default=30.0)
    ap.add_argument("--delay-max", type=float, default=60.0)
    args = ap.parse_args()

    titles = load_tracked_titles()
    if args.limit:
        titles = titles[: args.limit]
    elif args.rotate and args.rotate < len(titles):
        n = len(titles)
        start = (date.today().toordinal() * args.rotate) % n
        idx = [(start + i) % n for i in range(args.rotate)]
        titles = [titles[i] for i in idx]
        print(f"Rotating: titles {idx} of {n} today")

    session = requests.Session()
    run_date = date.today().isoformat()
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    today = date.today()
    conn = init_db(args.db)
    written = failed = 0

    for t in titles:
        query = f"{t['brand']} {clean_title_query(t['title'])} puzzle"
        url = (f"{SEARCH_URL}?_nkw={requests.utils.quote(query)}"
               f"&LH_Sold=1&LH_Complete=1&_ipg=240")
        html = fetch(session, url, block_markers=BLOCK_MARKERS)
        if html is None:
            print(f"  FAILED {t['title']}", file=sys.stderr)
            failed += 1
            continue
        items = parse_sold_listings(html)
        # eBay search is fuzzy (a series query returns sibling titles);
        # count only listings whose own title contains the distinctive phrase.
        phrase = clean_title_query(t["title"]).lower()
        loose = len(items)
        items = [i for i in items if phrase in i["title"].lower()]
        last_30 = [i for i in items if (today - i["sold_date"]).days <= 30]
        last_90 = [i for i in items if (today - i["sold_date"]).days <= 90]
        prices = [i["price"] for i in last_30 if i["price"]]
        median_30 = round(statistics.median(prices), 2) if prices else None
        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO ebay_snapshots
                   (run_date, scraped_at, title, brand, query,
                    sold_30d, sold_90d, median_price_30d)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (run_date, scraped_at, t["title"], t["brand"], query,
                 len(last_30), len(last_90), median_30),
            )
        written += 1
        print(f"  {t['title']:<40} sold30={len(last_30):<3} sold90={len(last_90):<3} "
              f"med=${median_30} (matched {len(items)}/{loose} listings)")
        polite_sleep(args.delay_min, args.delay_max)
    conn.close()

    print(f"Done: {written} titles written for {run_date} ({failed} failed) -> {args.db}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
