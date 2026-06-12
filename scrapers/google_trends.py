"""Search-interest signal for the Premium Puzzles Index (weekly cadence).

Pulls relative search interest for category, brand, and artist terms via
pytrends, for AU and worldwide. Worldwide is the lead indicator: titles
trending globally before they trend here. Appends long-format rows to a
dated CSV in data/raw/.

Usage:
    python scrapers/google_trends.py             # all terms, AU + worldwide
    python scrapers/google_trends.py --limit 4   # smoke test
"""

import argparse
import csv
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RAW_DIR

CATEGORY_TERMS = [
    "jigsaw puzzles australia",
    "1000 piece puzzle",
    "ravensburger puzzle",
    "funbox puzzle",
    "cobble hill puzzle",
    "gibsons puzzle",
    "my haven puzzle",
    "colin thompson puzzle",
    "aimee stewart puzzle",
]
GEOS = [("AU", "AU"), ("", "WORLD")]
TIMEFRAME = "today 3-m"
BATCH = 5  # Trends compares at most 5 terms per request


def main() -> int:
    ap = argparse.ArgumentParser(description="Search-interest snapshot (source B)")
    ap.add_argument("--limit", type=int, default=None, help="only first N terms (smoke test)")
    ap.add_argument("--out", type=Path,
                    default=RAW_DIR / f"google_trends_{date.today().isoformat()}.csv")
    args = ap.parse_args()

    from pytrends.request import TrendReq  # import here: slow + network-touching

    terms = CATEGORY_TERMS[: args.limit] if args.limit else CATEGORY_TERMS

    rows = []
    for geo, geo_label in GEOS:
        # Fresh client per geo: a shared instance reuses cached widget state
        # and silently serves the first geo's data for every later one.
        # No retries kwarg: pytrends' internal Retry uses a kwarg removed in
        # urllib3 2.x (method_whitelist). We do our own retrying below.
        pytrends = TrendReq(hl="en-AU", tz=-600)
        for i in range(0, len(terms), BATCH):
            batch = terms[i : i + BATCH]
            print(f"{geo_label}: {batch}")
            try:
                pytrends.build_payload(batch, timeframe=TIMEFRAME, geo=geo)
                df = pytrends.interest_over_time()
            except Exception as exc:  # pytrends raises many flavours; treat all as backoff
                print(f"  trends error: {exc} — waiting 60s and retrying once", file=sys.stderr)
                time.sleep(60)
                try:
                    pytrends.build_payload(batch, timeframe=TIMEFRAME, geo=geo)
                    df = pytrends.interest_over_time()
                except Exception as exc2:
                    print(f"  giving up on batch: {exc2}", file=sys.stderr)
                    continue
            if df.empty:
                print("  empty frame, skipping", file=sys.stderr)
                continue
            for ts, row in df.iterrows():
                for term in batch:
                    if term in row:
                        rows.append({
                            "date": ts.date().isoformat(),
                            "term": term,
                            "geo": geo_label,
                            "interest": int(row[term]),
                        })
            time.sleep(10)  # Trends rate-limits hard; be slow

    if not rows:
        print("No trends data captured.", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "term", "geo", "interest"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Done: {len(rows)} rows ({len(terms)} terms x {len(GEOS)} geos) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
