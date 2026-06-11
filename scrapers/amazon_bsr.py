"""Daily demand-signal snapshot for the Premium Puzzles Index.

Walks the Jigsaw Puzzles category listing (sorted by review rank), captures
listing-level fields for up to N products, then visits each product detail
page for the category Best Seller Rank. One SQLite row per (run_date, asin).

Usage:
    python scrapers/amazon_bsr.py                  # full run, 100 products
    python scrapers/amazon_bsr.py --max-products 10 --no-detail   # quick smoke test
"""

import argparse
import random
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.amazon.com.au"
CATEGORY_SEARCH = BASE_URL + "/s?rh=n%3A5030920051&s=review-rank&page={page}"
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "raw" / "amazon_bsr.db"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

KNOWN_BRANDS = [
    "Ravensburger", "Funbox", "Cobble Hill", "Gibsons", "Blue Opal",
    "Clementoni", "Educa", "Schmidt", "Holdson", "Eurographics",
    "Galison", "Mudpuppy", "Buffalo Games", "Trefl", "Heye", "Jumbo",
    "Wasgij", "Springbok", "White Mountain", "Pomegranate", "Piatnik",
    "Cra-Z-Art", "Hinkler", "Crown", "Wentworth", "Magic Puzzle Company",
    "Melissa & Doug", "New York Puzzle Company", "Bookish",
]

# Title spellings that differ from the canonical brand name.
BRAND_ALIASES = {
    "melissa and doug": "Melissa & Doug",
    "new york puzzle": "New York Puzzle Company",
}

CAPTCHA_MARKERS = ("api-services-support@amazon.com", "Robot Check", "Enter the characters you see")


def polite_sleep(min_s: float, max_s: float) -> None:
    time.sleep(random.uniform(min_s, max_s))


def fetch(session: requests.Session, url: str, min_s: float, max_s: float,
          max_retries: int = 3) -> str | None:
    """GET with UA rotation, CAPTCHA detection, and backoff. None on give-up."""
    for attempt in range(1, max_retries + 1):
        session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "en-AU,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        try:
            resp = session.get(url, timeout=30)
        except requests.RequestException as exc:
            print(f"  request error ({attempt}/{max_retries}): {exc}", file=sys.stderr)
            polite_sleep(min_s * attempt, max_s * attempt)
            continue
        if resp.status_code == 200 and not any(m in resp.text for m in CAPTCHA_MARKERS):
            return resp.text
        reason = "CAPTCHA" if resp.status_code == 200 else f"HTTP {resp.status_code}"
        wait = random.uniform(20, 40) * attempt
        print(f"  blocked ({reason}), attempt {attempt}/{max_retries}, waiting {wait:.0f}s",
              file=sys.stderr)
        time.sleep(wait)
    return None


def parse_brand(title: str) -> str | None:
    low = title.lower()
    for alias, canonical in BRAND_ALIASES.items():
        if alias in low:
            return canonical
    for brand in KNOWN_BRANDS:
        if brand.lower() in low:
            return brand
    return title.split()[0] if title else None


def parse_piece_count(title: str) -> int | None:
    m = re.search(r"(\d{2,5})\s*[- ]?\s*(?:pc|pcs|piece|pieces)\b", title, re.IGNORECASE)
    return int(m.group(1)) if m else None


def parse_listing_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    products = []
    for card in soup.select('div[data-component-type="s-search-result"]'):
        asin = card.get("data-asin")
        if not asin:
            continue

        title_el = card.select_one("h2 span") or card.select_one("h2")
        title = title_el.get_text(strip=True) if title_el else None
        if not title:
            continue

        price = None
        price_el = card.select_one("span.a-price > span.a-offscreen")
        if price_el:
            m = re.search(r"[\d,]+\.?\d*", price_el.get_text())
            if m:
                price = float(m.group().replace(",", ""))

        rating = None
        rating_el = card.select_one("span.a-icon-alt")
        if rating_el:
            m = re.match(r"([\d.]+)", rating_el.get_text(strip=True))
            if m:
                rating = float(m.group(1))

        reviews = None
        for el in card.select("a[aria-label], span[aria-label]"):
            m = re.match(r"^([\d,]+)\s+ratings?$", el.get("aria-label", "").strip())
            if m:
                reviews = int(m.group(1).replace(",", ""))
                break
        if reviews is None:
            el = card.select_one("span.s-underline-text")
            if el:
                txt = el.get_text(strip=True).strip("()").replace(",", "")
                if txt.isdigit():
                    reviews = int(txt)

        products.append({
            "asin": asin,
            "title": title,
            "brand": parse_brand(title),
            "price_aud": price,
            "avg_rating": rating,
            "review_count": reviews,
            "piece_count": parse_piece_count(title),
        })
    return products


def parse_bsr(html: str) -> int | None:
    """Category Best Seller Rank from a product detail page.

    Must run on extracted text, not raw HTML: the category name sits inside
    an anchor tag, so the number and "in Jigsaw Puzzles" are split by markup.
    """
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    m = re.search(r"([\d,]+)\s+in\s+Jigsaw Puzzles", text)
    return int(m.group(1).replace(",", "")) if m else None


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bsr_snapshots (
            run_date     TEXT NOT NULL,
            scraped_at   TEXT NOT NULL,
            asin         TEXT NOT NULL,
            title        TEXT,
            brand        TEXT,
            search_rank  INTEGER,
            bsr          INTEGER,
            review_count INTEGER,
            avg_rating   REAL,
            price_aud    REAL,
            piece_count  INTEGER,
            PRIMARY KEY (run_date, asin)
        )
    """)
    return conn


def main() -> int:
    ap = argparse.ArgumentParser(description="Snapshot puzzle demand signals (source A)")
    ap.add_argument("--max-products", type=int, default=100)
    ap.add_argument("--no-detail", action="store_true",
                    help="skip product detail pages (no BSR, much faster)")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--delay-min", type=float, default=2.0)
    ap.add_argument("--delay-max", type=float, default=5.0)
    args = ap.parse_args()

    run_date = date.today().isoformat()
    session = requests.Session()
    products: list[dict] = []

    page = 1
    while len(products) < args.max_products and page <= 7:
        url = CATEGORY_SEARCH.format(page=page)
        print(f"Listing page {page} ...")
        # A 200 with zero product cards is a soft block (empty shell /
        # unmarked CAPTCHA variant), not a layout change — retry it too.
        batch = []
        for attempt in range(1, 4):
            html = fetch(session, url, args.delay_min, args.delay_max)
            if html:
                batch = parse_listing_page(html)
                if batch:
                    break
            wait = random.uniform(30, 60) * attempt
            print(f"  empty page {page} (attempt {attempt}/3), waiting {wait:.0f}s",
                  file=sys.stderr)
            time.sleep(wait)
        if not batch:
            print(f"  giving up on page {page}", file=sys.stderr)
            break
        products.extend(batch)
        print(f"  +{len(batch)} products ({len(products)} total)")
        page += 1
        polite_sleep(args.delay_min, args.delay_max)

    products = products[: args.max_products]
    if not products:
        print("No products captured — layout change or hard block. Nothing written.",
              file=sys.stderr)
        return 1

    if not args.no_detail:
        print(f"Fetching BSR from {len(products)} detail pages ...")
        for i, p in enumerate(products, 1):
            html = fetch(session, f"{BASE_URL}/dp/{p['asin']}",
                         args.delay_min, args.delay_max)
            p["bsr"] = parse_bsr(html) if html else None
            if i % 10 == 0 or i == len(products):
                print(f"  {i}/{len(products)} detail pages done")
            polite_sleep(args.delay_min, args.delay_max)
    else:
        for p in products:
            p["bsr"] = None

    conn = init_db(args.db)
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        for rank, p in enumerate(products, 1):
            conn.execute(
                """INSERT OR REPLACE INTO bsr_snapshots
                   (run_date, scraped_at, asin, title, brand, search_rank, bsr,
                    review_count, avg_rating, price_aud, piece_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (run_date, scraped_at, p["asin"], p["title"], p["brand"], rank,
                 p["bsr"], p["review_count"], p["avg_rating"], p["price_aud"],
                 p["piece_count"]),
            )
    conn.close()

    with_bsr = sum(1 for p in products if p["bsr"])
    print(f"Done: {len(products)} products written for {run_date} "
          f"({with_bsr} with BSR) -> {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
