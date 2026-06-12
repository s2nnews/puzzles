"""Build data/retailer_urls.json: tracked title -> product URLs per retailer.

Matches tracked-title phrases against retailer sitemap URL slugs. Sitemap URL
lists live in data/raw/{retailer}_product_urls.txt (refreshed by re-running
the sitemap harvest; see scrapers/retailer_stock.py --refresh-sitemaps).

Search pages on these retailers are bot-walled or client-rendered, but
product pages are server-rendered with schema.org availability for SEO —
so stock checking is URL-driven, and this map is the bridge.

Usage:
    python pipeline/build_retailer_urls.py
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scrapers"))
from common import DATA_DIR, RAW_DIR, clean_title_query, load_tracked_titles

RETAILERS = ["bigw", "puzzlepalace"]
OUT_FILE = DATA_DIR / "retailer_urls.json"


def slug_words(phrase: str) -> list[str]:
    """'Sarah's Stunning Stamps' -> ['sarahs', 'stunning', 'stamps']"""
    phrase = phrase.lower().replace("'", "")
    words = re.split(r"[^a-z0-9]+", phrase)
    return [w for w in words if w and w not in ("the", "a", "no")]


def match(title: str, urls: list[str]) -> list[str]:
    words = slug_words(clean_title_query(title))
    hits = []
    for url in urls:
        slug = url.lower()
        if all(w in slug for w in words):
            hits.append(url)
    return hits


def main() -> int:
    titles = load_tracked_titles()
    result: dict[str, dict[str, list[str]]] = {}
    for retailer in RETAILERS:
        src = RAW_DIR / f"{retailer}_product_urls.txt"
        if not src.exists():
            print(f"skipping {retailer}: {src} missing (run sitemap harvest first)",
                  file=sys.stderr)
            continue
        urls = src.read_text(encoding="utf-8").splitlines()
        for t in titles:
            hits = match(t["title"], urls)
            if hits:
                result.setdefault(t["title"], {})[retailer] = hits
            print(f"  {retailer:<13} {t['title']:<42} {len(hits)} match(es)")

    OUT_FILE.write_text(json.dumps(result, indent=2), encoding="utf-8")
    matched = len(result)
    print(f"Done: {matched}/{len(titles)} titles matched somewhere -> {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
