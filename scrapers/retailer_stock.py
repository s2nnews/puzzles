"""Competitor stock-pressure signal for the Premium Puzzles Index.

Checks each tracked title's product page(s) at AU retailers and records
schema.org availability + price. URL-driven: search pages are bot-walled
or client-rendered, product pages are server-rendered for SEO. The URL map
comes from pipeline/build_retailer_urls.py.

A failed fetch is recorded as status 'unknown', never as out-of-stock —
conflating the two would poison the stock-pressure series.

Usage:
    python scrapers/retailer_stock.py                      # all retailers
    python scrapers/retailer_stock.py --retailer puzzlepalace
"""

import argparse
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_DIR, RAW_DIR, fetch, polite_sleep

URL_MAP = DATA_DIR / "retailer_urls.json"
DEFAULT_DB = RAW_DIR / "retailer_stock.db"

# Per-retailer session warm-up page (Akamai et al. want cookies before
# they'll serve a product page to a non-browser client).
WARMUP = {"bigw": "https://www.bigw.com.au/"}


def parse_availability(html: str) -> tuple[str, float | None]:
    """(status, price) from schema.org Product JSON-LD; text fallback."""
    for m in re.finditer(
            r"<script type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
            html, re.DOTALL):
        try:
            d = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        graph = d.get("@graph", [d]) if isinstance(d, dict) else d
        for it in graph:
            t = it.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                o = it.get("offers", [{}])
                o = o[0] if isinstance(o, list) else o
                avail = (o.get("availability") or "").rsplit("/", 1)[-1].lower()
                price = o.get("price")
                price = float(price) if price not in (None, "") else None
                if "instock" in avail or "limitedavailability" in avail:
                    return "in_stock", price
                if "outofstock" in avail or "soldout" in avail or "discontinued" in avail:
                    return "out_of_stock", price
    low = html.lower()
    if "out of stock" in low or "sold out" in low:
        return "out_of_stock", None
    if "add to cart" in low or "in stock" in low:
        return "in_stock", None
    return "unknown", None


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_snapshots (
            run_date   TEXT NOT NULL,
            scraped_at TEXT NOT NULL,
            retailer   TEXT NOT NULL,
            title      TEXT NOT NULL,
            url        TEXT NOT NULL,
            status     TEXT NOT NULL,   -- in_stock | out_of_stock | unknown
            price      REAL,
            PRIMARY KEY (run_date, retailer, url)
        )
    """)
    return conn


def main() -> int:
    ap = argparse.ArgumentParser(description="Retailer stock snapshot (source C)")
    ap.add_argument("--retailer", default=None, help="only this retailer")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--delay-min", type=float, default=8.0)
    ap.add_argument("--delay-max", type=float, default=15.0)
    args = ap.parse_args()

    if not URL_MAP.exists():
        print(f"{URL_MAP} missing — run pipeline/build_retailer_urls.py first",
              file=sys.stderr)
        return 1
    url_map = json.loads(URL_MAP.read_text(encoding="utf-8"))

    run_date = date.today().isoformat()
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = init_db(args.db)
    sessions: dict[str, requests.Session] = {}
    counts = {"in_stock": 0, "out_of_stock": 0, "unknown": 0}

    for title, retailers in url_map.items():
        for retailer, urls in retailers.items():
            if args.retailer and retailer != args.retailer:
                continue
            if retailer not in sessions:
                sessions[retailer] = requests.Session()
                warm = WARMUP.get(retailer)
                if warm:
                    fetch(sessions[retailer], warm, max_retries=1)
                    polite_sleep(2, 4)
            for url in urls:
                html = fetch(sessions[retailer], url, max_retries=2)
                status, price = parse_availability(html) if html else ("unknown", None)
                with conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO stock_snapshots
                           (run_date, scraped_at, retailer, title, url, status, price)
                           VALUES (?,?,?,?,?,?,?)""",
                        (run_date, scraped_at, retailer, title, url, status, price),
                    )
                counts[status] += 1
                print(f"  {retailer:<13} {title:<40} {status:<13} ${price}")
                polite_sleep(args.delay_min, args.delay_max)
    conn.close()

    print(f"Done {run_date}: {counts} -> {args.db}")
    return 0 if (counts["in_stock"] + counts["out_of_stock"]) else 1


if __name__ == "__main__":
    sys.exit(main())
