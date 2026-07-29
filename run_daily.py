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
# Order matters: dict order is run order, and the dashboard goes FIRST. It
# takes ~1 minute and publishes immediately, so a scraper stalling on a
# block (or the laptop closing mid-run) can no longer cost us the day's
# dashboard refresh — which is exactly what happened on 2026-07-29.
JOBS = {
    "dashboard": (["dashboard/collect.py"],
                  lambda d: True),  # marketing dashboard data.json (needs dashboard/.env)
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


def done_today(name: str) -> bool:
    """True if this source already has data for today — so a re-trigger
    (e.g. an at-logon run after the daily one) is a cheap no-op rather than
    a redundant scrape. SQLite sources key on run_date; Trends write a dated
    CSV."""
    import sqlite3
    today = date.today().isoformat()
    db_table = {
        "amazon": ("amazon_bsr.db", "bsr_snapshots"),
        "ebay":   ("ebay_sold.db", "ebay_snapshots"),
        "stock":  ("retailer_stock.db", "stock_snapshots"),
        "reddit": ("reddit_signals.db", "reddit_snapshots"),
    }
    if name in db_table:
        db, table = db_table[name]
        path = ROOT / "data" / "raw" / db
        if not path.exists():
            return False
        try:
            con = sqlite3.connect(path)
            n = con.execute(f"select count(*) from {table} where run_date=?",
                            (today,)).fetchone()[0]
            con.close()
            return n > 0
        except sqlite3.Error:
            return False
    if name in ("trends", "global"):
        stem = "google_trends" if name == "trends" else "global_trends"
        return (ROOT / "data" / "raw" / f"{stem}_{today}.csv").exists()
    if name == "dashboard":
        # collect.py rewrites data.json on every run — mtime date marks it done.
        path = ROOT / "dashboard" / "data.json"
        return (path.exists()
                and date.fromtimestamp(path.stat().st_mtime).isoformat() == today)
    return False


def sync() -> None:
    """Rebase onto origin before building anything.

    The hourly GitHub Action also writes dashboard/data.json, so this machine
    is not the only writer. Pulling first (and discarding any uncommitted
    data.json, which collect.py regenerates anyway from the pulled file's
    history) keeps the two from diverging into a merge conflict nobody is
    watching. Offline is fine — the build still runs, the push just waits."""
    print("\n=== sync ===", flush=True)
    try:
        subprocess.run(["git", "checkout", "--", "dashboard/data.json"],
                       cwd=ROOT, check=False)
        subprocess.run(["git", "pull", "--rebase", "--autostash"],
                       cwd=ROOT, check=True)
        print("=== sync: up to date with origin ===", flush=True)
    except Exception as exc:  # noqa: BLE001 — never let sync kill the job
        subprocess.run(["git", "rebase", "--abort"], cwd=ROOT, check=False)
        print(f"=== sync: skipped ({exc}) — building on the local copy ===",
              flush=True)


INDEX_FILES = [
    "data/processed/index.json",
    "web/puzzle_index.html",
    "web/puzzle_index_basic.html",
    "web/puzzle_index_global.html",
]
DASHBOARD_FILES = ["dashboard/data.json"]


def publish(today: date, files: list[str], label: str = "publish") -> bool:
    """Commit + push built files so the live site (which reads origin/main)
    updates. A push failure (e.g. offline) logs but never fails the job — the
    next run will catch up. This is the step that keeps the public pages
    current; without it the pipeline rebuilds locally but nothing ships.

    Called twice: once right after the dashboard job so its refresh is safe
    even if a later scraper stalls or the machine sleeps, and once at the end
    for the Index."""
    print(f"\n=== {label} ===", flush=True)
    try:
        subprocess.run(["git", "add", *files], cwd=ROOT, check=True)
        # Nothing staged means the build produced no changes — skip quietly.
        if subprocess.run(["git", "diff", "--cached", "--quiet"],
                          cwd=ROOT).returncode == 0:
            print(f"=== {label}: nothing to commit ===", flush=True)
            return True
        subprocess.run(["git", "commit", "-m",
                        f"data: refresh {label} {today.isoformat()}"],
                       cwd=ROOT, check=True)
        subprocess.run(["git", "push"], cwd=ROOT, check=True)
        print(f"=== {label}: pushed to origin ===", flush=True)
        return True
    except Exception as exc:  # noqa: BLE001 — never let publish kill the job
        print(f"=== {label}: FAILED ({exc}) — site not updated this run ===",
              flush=True)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily Index collection + build")
    ap.add_argument("--only", choices=list(JOBS), help="run just this source")
    ap.add_argument("--skip", nargs="+", choices=list(JOBS), default=[],
                    help="sources to skip (e.g. --skip ebay on cloud IPs)")
    ap.add_argument("--force", action="store_true",
                    help="ignore cadence, run every source")
    ap.add_argument("--no-build", action="store_true",
                    help="skip the index rebuild at the end")
    ap.add_argument("--no-push", action="store_true",
                    help="skip committing + pushing the rebuilt Index to git")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    today = date.today()
    if args.only:
        due = [args.only]
    else:
        due = [n for n, (_, pred) in JOBS.items() if args.force or pred(today)]
    due = [n for n in due if n not in args.skip]

    # Skip sources already collected today, so the task can fire often (daily
    # trigger + at-logon) and only ever does the work that's still outstanding.
    # --force / --only override this.
    skipped_done = []
    if not args.force and not args.only:
        outstanding = [n for n in due if not done_today(n)]
        skipped_done = [n for n in due if n not in outstanding]
        due = outstanding

    print(f"{today} ({today:%A}) — due: {', '.join(due) or 'none'}"
          + (f" · already done: {', '.join(skipped_done)}" if skipped_done else ""))
    if args.dry_run:
        return 0

    if not args.no_push:
        sync()

    results = {}
    for n in due:
        results[n] = run(n, JOBS[n][0])
        # Ship the dashboard the moment it is built. Everything after this is
        # slow scraping that can stall or be cut short; the day's marketing
        # numbers should not be hostage to it.
        if n == "dashboard" and results[n] and not args.no_push:
            publish(today, DASHBOARD_FILES, "dashboard")

    built = True
    if not args.no_build:
        built = run("aggregate", ["pipeline/aggregate.py"])
        if built:
            run("chart", ["web/build_chart.py"])  # non-critical: refresh the dashboard

    # Publish the fresh Index to git so the live site picks it up. Gated on a
    # successful build so we never push a half-baked or empty index.
    if built and not args.no_build and not args.no_push:
        publish(today, INDEX_FILES + DASHBOARD_FILES, "Index")

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
