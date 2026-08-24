"""The 1000-Piece Index — a constant-basket affordability series for puzzles.

The rest of the Index measures *demand*. This measures *price*, and does it the
way the Big Mac Index does: hold the product completely still, then ask how much
work it takes to buy one.

The basket is Ravensburger 1000-piece titles that were listed continuously by a
major Australian retailer from 2017 onward. Prices come from that retailer's
archived product pages via the Internet Archive, one snapshot per year. This
repo is public, so the retailer is not named anywhere in it: the host comes from
PUZZLE_PRICE_SOURCE_HOST in the local environment and is only needed to
re-scrape. Rebuilding the series from the cached raw file needs nothing.

Construction is a matched-model chain index, which is what the ABS uses for the
CPI: for each consecutive pair of years, take every title priced in BOTH years,
compute each title's own price ratio, take the geometric mean of those ratios,
and multiply the links together. A title only ever contributes a change measured
against itself, so titles entering or leaving the range can never create a false
jump in the level.

The denominator is the national minimum wage. It is the cleanest and most
quotable earnings series in Australia, it is set once a year by one body, and it
needs no seasonal adjustment or revision.

Usage:
    python pipeline/affordability.py              # use cache if present
    python pipeline/affordability.py --refresh    # re-scrape the archive

Writes:
    data/raw/affordability_raw.json        cached observations (gitignored)
    data/processed/affordability.json      the derived series (committed)
"""

from __future__ import annotations

import argparse
import json
import os
import math
import re
import sys
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "affordability_raw.json"
OUT = ROOT / "data" / "processed" / "affordability.json"

BASE_YEAR = "2017"
UA = "Mozilla/5.0 (compatible; PremiumPuzzlesIndex/1.0; price research)"

# Host whose archived listings the basket is read from. THIS REPO IS PUBLIC, so
# the retailer is not named here: set PUZZLE_PRICE_SOURCE_HOST in the local
# environment (or .env) before running with --refresh. The cached raw file and
# the derived series both keep working without it.
SOURCE_HOST = os.environ.get("PUZZLE_PRICE_SOURCE_HOST", "")

# National minimum wage, hourly, effective 1 July of the year shown.
# Source: Fair Work Commission annual wage review decisions.
MIN_WAGE = {
    "2017": 18.29, "2018": 18.93, "2019": 19.49, "2020": 19.84,
    "2021": 20.33, "2022": 21.38, "2023": 23.23, "2024": 24.10,
    "2025": 24.95, "2026": 26.44,
}

# Anchor level for the basket. The chain index gives movement; this converts it
# back into dollars. It is the median list price of the basket in the base year.
BASE_MEDIAN_PRICE = 39.95

PIECES = 1000


# --------------------------------------------------------------------------
# scraping
# --------------------------------------------------------------------------

def fetch(url: str, tries: int = 3, timeout: int = 150) -> str | None:
    """GET with retries. Returns None rather than raising, so one dead snapshot
    never kills a run."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
        except Exception:
            if attempt == tries - 1:
                return None
            time.sleep(5 * (attempt + 1))
    return None


def cdx(url_pattern: str, extra: str = "") -> list[list[str]]:
    """Query the Internet Archive CDX index. Returns [[timestamp, original], ...]."""
    q = (f"http://web.archive.org/cdx/search/cdx?url={url_pattern}"
         f"&output=json&filter=statuscode:200{extra}")
    body = fetch(q)
    if not body:
        return []
    try:
        rows = json.loads(body)
    except json.JSONDecodeError:
        return []
    return rows[1:] if len(rows) > 1 else []


def discover_basket() -> list[str]:
    """Find product URLs for 1000-piece Ravensburger titles that appear both
    early (2017/18) and late (2025/26). Those are the constant-basket members."""
    if not SOURCE_HOST:
        raise SystemExit(
            "PUZZLE_PRICE_SOURCE_HOST is not set, so there is nothing to scrape. "
            "Set it in the environment to re-scrape, or drop --refresh to rebuild "
            "the series from the cached raw file.")
    rows = cdx(f"{SOURCE_HOST}*",
               "&fl=timestamp,original"
               "&filter=original:.*ravensburger.*1000pc.*"
               "&collapse=timestamp:4&limit=60000")
    years_by_url: dict[str, set[str]] = defaultdict(set)
    for ts, original in rows:
        years_by_url[original.split("?")[0]].add(ts[:4])

    basket = [
        url for url, years in years_by_url.items()
        if years & {"2017", "2018"} and years & {"2025", "2026"}
    ]
    print(f"  candidate product URLs: {len(years_by_url)}")
    print(f"  constant-basket members: {len(basket)}")
    return sorted(basket)


def snapshots_by_year(url: str) -> dict[str, str]:
    """First archived snapshot in each calendar year for one product URL."""
    out: dict[str, str] = {}
    for row in cdx(url, "&fl=timestamp&collapse=timestamp:6"):
        out.setdefault(row[0][:4], row[0])
    return out


PRICE_BLOCK = re.compile(r'<p class="price".*?</p>', re.S)
PRICE_BLOCK_FALLBACK = re.compile(r'class="price".{0,500}', re.S)
MONEY = re.compile(r"\$([\d,]+\.\d{2})")
SOLD_OUT = re.compile(r"out of stock|sold ?out|notify me", re.I)


def read_price(url: str, timestamp: str) -> dict | None:
    """Pull list and street price out of one archived product page.

    The template shows a struck-through list price beside a selling price, so
    the highest money token in the price block is the list price and the lowest
    is the street price. When only one price shows, they are the same.
    """
    html = fetch(f"http://web.archive.org/web/{timestamp}/https://{url}")
    if not html:
        return None
    block = PRICE_BLOCK.search(html) or PRICE_BLOCK_FALLBACK.search(html)
    if not block:
        return None
    values = [float(v.replace(",", "")) for v in MONEY.findall(block.group(0))]
    # Guard against picking up shipping thresholds or gift-card denominations.
    values = [v for v in values if 5 < v < 300]
    if not values:
        return None
    return {
        "list": max(values),
        "street": min(values),
        "sold_out": bool(SOLD_OUT.search(html)),
    }


def scrape() -> dict[str, dict[str, dict]]:
    """Build {product_url: {year: observation}} for the whole basket."""
    basket = discover_basket()

    def one(url: str) -> tuple[str, dict[str, dict]]:
        series: dict[str, dict] = {}
        for year, ts in snapshots_by_year(url).items():
            obs = read_price(url, ts)
            if obs:
                obs["snapshot"] = ts
                series[year] = obs
            time.sleep(1)
        return url, series

    observations: dict[str, dict[str, dict]] = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        for url, series in pool.map(one, basket):
            observations[url] = series
            print(f"  {url.split('/')[-1][:46]:48s} {len(series)} years")
    return observations


# --------------------------------------------------------------------------
# index construction
# --------------------------------------------------------------------------

def chain_index(observations: dict[str, dict[str, dict]], field: str) -> tuple[dict[str, float], dict[str, int]]:
    """Matched-model chain index, base year = 100.

    Returns the level series and the number of matched titles behind each link,
    because the match count is the honest measure of how strong each link is.
    """
    years = sorted({y for series in observations.values() for y in series})
    if BASE_YEAR not in years:
        raise SystemExit(f"base year {BASE_YEAR} missing from observations")

    levels = {BASE_YEAR: 100.0}
    matches: dict[str, int] = {}
    level = 100.0
    previous = BASE_YEAR

    for year in [y for y in years if y > BASE_YEAR]:
        ratios = []
        for series in observations.values():
            if previous in series and year in series:
                before, after = series[previous][field], series[year][field]
                if before and after:
                    ratios.append(after / before)
        if not ratios:
            # No overlap. Skip the year rather than inventing a level for it,
            # and keep `previous` where it is so the next year bridges the gap.
            continue
        link = math.exp(sum(math.log(r) for r in ratios) / len(ratios))
        level *= link
        levels[year] = round(level, 1)
        matches[year] = len(ratios)
        previous = year

    return levels, matches


def build(observations: dict[str, dict[str, dict]]) -> dict:
    list_levels, list_matches = chain_index(observations, "list")
    street_levels, _ = chain_index(observations, "street")

    series = []
    for year in sorted(list_levels):
        wage = MIN_WAGE.get(year)
        if wage is None:
            continue
        price = BASE_MEDIAN_PRICE * list_levels[year] / 100
        wage_level = round(wage / MIN_WAGE[BASE_YEAR] * 100, 1)
        series.append({
            "year": int(year),
            "price_index": list_levels[year],
            "street_index": street_levels.get(year),
            "wage_index": wage_level,
            "list_price": round(price, 2),
            "cents_per_piece": round(price / PIECES * 100, 2),
            "minutes_of_work": round(price / wage * 60, 1),
            "matched_titles": list_matches.get(year),
        })

    first, last = series[0], series[-1]
    afford_change = (last["minutes_of_work"] / first["minutes_of_work"] - 1) * 100

    return {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "base_year": int(BASE_YEAR),
        "pieces": PIECES,
        "basket_size": len(observations),
        "headline": {
            "minutes_now": last["minutes_of_work"],
            "minutes_base": first["minutes_of_work"],
            "affordability_change_pct": round(afford_change, 1),
            "price_change_pct": round(last["price_index"] - 100, 1),
            "wage_change_pct": round(last["wage_index"] - 100, 1),
            "cents_per_piece": last["cents_per_piece"],
        },
        "series": series,
    }


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true",
                    help="re-scrape the archive instead of using the cache")
    args = ap.parse_args()

    if args.refresh or not RAW.exists():
        print("Scraping archived listings (this takes several minutes)...")
        observations = scrape()
        RAW.parent.mkdir(parents=True, exist_ok=True)
        RAW.write_text(json.dumps(observations, indent=1), encoding="utf-8")
        print(f"Cached {len(observations)} product histories to {RAW.name}")
    else:
        observations = json.loads(RAW.read_text(encoding="utf-8"))
        print(f"Using cached {RAW.name} ({len(observations)} product histories). "
              f"Pass --refresh to re-scrape.")

    # Drop products the scrape found nothing for, so they do not inflate basket_size.
    observations = {u: s for u, s in observations.items() if s}

    data = build(observations)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")

    h = data["headline"]
    print(f"\nThe 1000-Piece Index, base {data['base_year']} = 100")
    print(f"  basket           {data['basket_size']} titles")
    print(f"  price index      {h['price_change_pct']:+.1f}%")
    print(f"  wage index       {h['wage_change_pct']:+.1f}%")
    print(f"  work-time        {h['minutes_base']:.0f} min -> {h['minutes_now']:.0f} min "
          f"({h['affordability_change_pct']:+.1f}%)")
    print(f"\nWrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
