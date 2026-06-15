"""Global puzzle-demand signal for the Premium Puzzles Index (weekly).

Uses Google Trends' interest-by-region, which ranks every country's relative
search interest on ONE comparable scale — the methodologically clean way to
compare markets across the globe (unlike separate per-geo time series, which
are each self-normalised). Averages a few category terms to damp single-term
noise, and writes per-country interest to a dated CSV.

The "major markets" filtering happens downstream (aggregate.py); here we
store the full country list so the raw signal stays complete.

Usage:
    python scrapers/global_trends.py
"""

import argparse
import csv
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RAW_DIR

TERMS = ["jigsaw puzzle", "1000 piece puzzle"]
TIMEFRAME = "today 12-m"


def main() -> int:
    ap = argparse.ArgumentParser(description="Global per-country demand (source F)")
    ap.add_argument("--out", type=Path,
                    default=RAW_DIR / f"global_trends_{date.today().isoformat()}.csv")
    args = ap.parse_args()

    from pytrends.request import TrendReq

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for term in TERMS:
        print(f"interest_by_region: {term!r}")
        df = None
        for attempt in range(2):
            try:
                pt = TrendReq(hl="en-US", tz=0)  # fresh client per term
                pt.build_payload([term], timeframe=TIMEFRAME, geo="")
                df = pt.interest_by_region(resolution="COUNTRY", inc_low_vol=True)
                break
            except Exception as exc:
                print(f"  trends error: {exc} — waiting 60s", file=sys.stderr)
                time.sleep(60)
        if df is None or df.empty:
            print(f"  no data for {term!r}, skipping", file=sys.stderr)
            continue
        for country, val in df[term].items():
            v = float(val)
            if v <= 0:
                continue
            totals[country] = totals.get(country, 0.0) + v
            counts[country] = counts.get(country, 0) + 1
        time.sleep(12)  # Trends rate-limits hard

    if not totals:
        print("No global data captured.", file=sys.stderr)
        return 1

    # Mean interest across the terms that registered for each country,
    # then rescale so the strongest market = 100.
    means = {c: totals[c] / counts[c] for c in totals}
    top = max(means.values()) or 1.0
    rows = sorted(((c, round(v / top * 100, 1)) for c, v in means.items()),
                  key=lambda kv: -kv[1])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["country", "interest"])
        w.writerows(rows)
    au = next((i + 1 for i, (c, _) in enumerate(rows) if c == "Australia"), None)
    print(f"Done: {len(rows)} countries -> {args.out} "
          f"(Australia global rank {au})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
