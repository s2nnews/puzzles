"""Cadence-aware orchestrator for the Premium Puzzles Index.

One entry point for the daily job (cron or local Task Scheduler). It decides
which sources are due today, runs each in isolation (one failure never stops
the rest), then rebuilds the Index. Cadence is matched to each signal's real
information rate — collecting a 30-day-window signal daily just trips blocks
for no extra resolution (see docs/SCRAPING_LEARNINGS.md).

  Amazon BSR : daily      — the only genuinely daily signal (live sales rank)
  eBay sold  : daily       — but a rotating ~5-title slice (30/90d windows)
  Stock      : Mon/Wed/Fri — stable day-to-day
  Reddit     : Monday      — 30-day mention window; daily hammering = 429 spiral
  Trends     : Thursday    — weekly relative interest
  aggregate  : always last — rebuild index.json from whatever is fresh

Usage:
    python run_daily.py                # run everything due today
    python run_daily.py --only amazon  # force one source now
    python run_daily.py --force        # run all sources regardless of cadence
    python run_daily.py --dry-run      # print the plan, run nothing
"""

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

# name -> (script args, due-today predicate). weekday(): Mon=0 .. Sun=6.
JOBS = {
    "amazon": (["scrapers/amazon_bsr.py", "--max-products", "100"],
               lambda d: True),
    "ebay":   (["scrapers/ebay_sold.py"],
               lambda d: True),  # internal rotation keeps it light
    "stock":  (["scrapers/retailer_stock.py", "--retailer", "puzzlepalace"],
               lambda d: d.weekday() in (0, 2, 4)),
    "reddit": (["scrapers/reddit_signals.py"],
               lambda d: d.weekday() == 0),
    "trends": (["scrapers/google_trends.py"],
               lambda d: d.weekday() == 3),
    "global": (["scrapers/global_trends.py"],
               lambda d: d.weekday() == 4),  # Fri — a day off trends to spare rate limits
}


def run(name: str, script_args: list[str]) -> bool:
    print(f"\n=== {name} ===", flush=True)
    proc = subprocess.run([PY, *script_args], cwd=ROOT)
    ok = proc.returncode == 0
    print(f"=== {name}: {'OK' if ok else f'FAILED (exit {proc.returncode})'} ===",
          flush=True)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily Index collection + build")
    ap.add_argument("--only", choices=list(JOBS), help="run just this source")
    ap.add_argument("--skip", nargs="+", choices=list(JOBS), default=[],
                    help="sources to skip (e.g. --skip ebay on cloud IPs)")
    ap.add_argument("--force", action="store_true",
                    help="ignore cadence, run every source")
    ap.add_argument("--no-build", action="store_true",
                    help="skip the index rebuild at the end")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    today = date.today()
    if args.only:
        due = [args.only]
    else:
        due = [n for n, (_, pred) in JOBS.items() if args.force or pred(today)]
    due = [n for n in due if n not in args.skip]

    print(f"{today} ({today:%A}) — sources due: {', '.join(due) or 'none'}")
    if args.dry_run:
        return 0

    results = {n: run(n, JOBS[n][0]) for n in due}

    built = True
    if not args.no_build:
        built = run("aggregate", ["pipeline/aggregate.py"])
        if built:
            run("chart", ["web/build_chart.py"])  # non-critical: refresh the dashboard

    ok = sum(results.values())
    print(f"\nSummary {today}: {ok}/{len(results)} sources ok"
          + ("" if not results else
             " [" + ", ".join(f"{n}={'ok' if v else 'FAIL'}"
                              for n, v in results.items()) + "]")
          + (f", index {'rebuilt' if built else 'BUILD FAILED'}"
             if not args.no_build else ""))
    # Non-zero only if everything that ran failed, or the build failed — a
    # single flaky source shouldn't fail the whole cron.
    return 0 if ((ok or not results) and built) else 1


if __name__ == "__main__":
    sys.exit(main())
