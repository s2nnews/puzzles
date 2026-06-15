# Operations — running the Index

## One command

```
python run_daily.py
```

`run_daily.py` is the only entry point. It decides which sources are due
today, runs each in isolation (one failure never stops the rest), and
rebuilds `data/processed/index.json`. Useful flags:

| Flag | Effect |
|---|---|
| `--dry-run` | print today's plan, run nothing |
| `--only amazon` | force a single source now |
| `--skip ebay` | run today's due set minus some sources (cloud uses this) |
| `--force` | ignore cadence, run every source |
| `--no-build` | collect only, don't rebuild the Index |

## Cadence (why each source runs when it does)

Matched to each signal's real information rate. Over-collecting a slow
signal just trips bot walls for no extra resolution
(see `SCRAPING_LEARNINGS.md`).

| Source | When | Why |
|---|---|---|
| Amazon BSR | daily | the only genuinely daily signal (live sales rank) |
| eBay sold | daily, rotating ~5 titles | 30/90-day windows; full set cycles ~weekly, stays under the wall |
| Retailer stock | Mon / Wed / Fri | stable day-to-day |
| Reddit | Monday | 30-day mention window; daily hammering triggers the 429→timeout spiral |
| Google Trends | Thursday | weekly relative interest |

## Two runners — and why it's split

**eBay must stay on this PC.** Its bot wall punishes datacenter IPs far
harder than a residential one. Everything else is cloud-safe.

### Local (primary today): Windows Task Scheduler
Runs the *full* set including eBay, on this PC's residential IP.

```
powershell -ExecutionPolicy Bypass -File scripts\register_local_task.ps1
```

Registers a daily 06:05 task. Needs the PC on and awake at run time.
Test immediately: `Start-ScheduledTask -TaskName PremiumPuzzlesIndex`.

### Cloud (laptop-independent): GitHub Actions
`.github/workflows/daily.yml` runs the robust sources (everything except
eBay) at a fixed 20:00 UTC / 06:00 Sydney, then commits the refreshed
`index.json` back to the repo — which is what the website reads. The fixed
UTC time also keeps the BSR series comparable (absolute sales rank drifts
with time of day).

**Open validation:** datacenter IPs may get blocked on Amazon/Reddit where
this PC isn't. First scheduled run tells us. If Amazon proves unreliable
from Actions, keep it on the local runner and let the cloud job handle the
gentler sources (stock / Reddit / Trends) plus the index build.

## The block-handling built into the scrapers

- **Amazon**: probabilistic empty-shell block in streaks → whole-pass retry
  with a fresh session, up to 4 passes (`--run-attempts`).
- **eBay**: sticky wall after ~5 quick queries → rotation + 30–60s spacing.
- **Reddit**: ~1 req/10s, 429s heal with backoff; weekly cadence avoids the
  escalation to connection timeouts.
- **Trends**: long 429 cooldowns; retry-once-then-skip, picked up next run.

A failed source is logged and skipped; it never writes partial/garbage data
(stock failures record `unknown`, never `out_of_stock`).
