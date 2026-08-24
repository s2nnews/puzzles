"""The Ravensburger 1000 Index — a constant-basket real-price series for puzzles.

The rest of the Index measures *demand*. This measures *price*: hold the product
completely still for a decade, then ask whether it actually got dearer.

WHY THIS IS NOT "MINUTES OF WORK" ANY MORE
------------------------------------------
The first version of this index divided the puzzle price by the national minimum
wage and reported that a puzzle had become 13.7% cheaper. That was wrong twice.

1. The minimum wage is the most flattering denominator available. It was lifted
   deliberately faster than general wages through the 2022-24 inflation episode,
   rising 44.6% over the period against 27.6% for the Wage Price Index. Choosing
   it inflated the result to about 2.3x the defensible number.
2. It was justified as "the Big Mac Index method". It is not. The Big Mac Index
   is a purchasing power parity measure comparing one good across countries at
   market exchange rates; it uses no wage series at all. The "minutes of work"
   framing belongs to UBS's Prices and Earnings report, and that uses average net
   earnings across many occupations, never a minimum wage.

There is also a methodological point that outranks both. The price side of this
index is a constant-basket, constant-quality construction. Median and average
earnings series are not constant-quality: they move with the mix of who is
working and for how many hours. Pairing a constant-basket numerator with a
composition-shifting denominator is inconsistent. The CPI and the Wage Price
Index are both constant-quality by design, which is why they are used here.

So the headline is now the plainest question available, and the one that needs no
wage series: **did the puzzle rise faster or slower than prices in general?**

CONSTRUCTION
------------
Prices: the RRP of Ravensburger 1000-piece titles listed continuously since 2017,
read from archived Australian retail pages via the Internet Archive, one snapshot
per year.

The RRP is Ravensburger's own national figure, not a number the stockist sets,
which is why reading it from a single archive is not the weakness it looks like.
The data shows it directly: unrelated titles step to identical new prices in the
same year (three moved 49.95 -> 52.95 together, then 52.95 -> 54.99 together),
which is a brand-wide revision rather than one shop repricing. The discounted
series IS the shop's own decision, and is reported separately for that reason.

This repo is public, so the stockist is not named in it; set
PUZZLE_PRICE_SOURCE_HOST to re-scrape.

Index: a matched-model chain index, the construction the ABS uses for the CPI.
For each consecutive pair of years, take every title priced in BOTH years,
compute each title's own price ratio, take the geometric mean, and chain the
links. A title only ever contributes a change measured against itself, so titles
entering or leaving the range cannot create a false jump.

Deflators: pulled live from the ABS Data API, March quarter of each year, which
is the quarter the archive snapshots cluster in.
  CPI  All groups, Australia, original
  WPI  Total hourly rates of pay excluding bonuses, all sectors, all industries

The minimum wage is retained ONLY as a sensitivity row, so the published output
shows what the answer would have been under a denominator we rejected.

Usage:
    python pipeline/affordability.py              # cached prices + cached ABS
    python pipeline/affordability.py --refresh    # re-scrape the archive
    python pipeline/affordability.py --refresh-abs

Writes:
    data/raw/affordability_raw.json    cached price observations (gitignored)
    data/raw/abs_deflators.json        cached ABS series (gitignored)
    data/processed/affordability.json  the derived series (committed)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
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
ABS_RAW = ROOT / "data" / "raw" / "abs_deflators.json"
OUT = ROOT / "data" / "processed" / "affordability.json"

BASE_YEAR = "2017"
QUARTER = "Q1"          # March quarter: where the archive snapshots cluster
PIECES = 1000
UA = "Mozilla/5.0 (compatible; PremiumPuzzlesIndex/1.0; price research)"

# Host whose archived listings the basket is read from. THIS REPO IS PUBLIC, so
# the retailer is not named here: set PUZZLE_PRICE_SOURCE_HOST in the local
# environment before running with --refresh. Rebuilding from cache needs nothing.
SOURCE_HOST = os.environ.get("PUZZLE_PRICE_SOURCE_HOST", "")

# Median list price of the basket in the base year. The chain index supplies the
# movement; this converts it back into dollars.
BASE_MEDIAN_PRICE = 39.95

# Sensitivity row only. NOT a denominator we publish against. See module docstring.
# Source: Fair Work Commission annual wage review decisions, effective 1 July.
MIN_WAGE = {
    "2017": 18.29, "2018": 18.93, "2019": 19.49, "2020": 19.84,
    "2021": 20.33, "2022": 21.38, "2023": 23.23, "2024": 24.10,
    "2025": 24.95, "2026": 26.44,
}

ABS_API = "https://data.api.abs.gov.au/rest/data"
CPI_KEY = "CPI/1.10001.10.50.Q"      # index numbers, all groups, original, Australia
WPI_FILTER = {
    "Measure": "Quarterly Index",
    "Index": "Total hourly rates of pay excluding bonuses",
    "Sector": "Private and Public",
    "Industry": "All Industries",
    "Adjustment Type": "Original",
    "Region": "Australia",
}


# --------------------------------------------------------------------------
# fetching
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


def load_deflators(refresh: bool) -> dict[str, dict[str, float]]:
    """CPI and WPI quarterly index numbers, straight from the ABS Data API."""
    if not refresh and ABS_RAW.exists():
        return json.loads(ABS_RAW.read_text(encoding="utf-8"))

    print("Fetching CPI and WPI from the ABS Data API...")
    cpi_csv = fetch(f"{ABS_API}/{CPI_KEY}?startPeriod=2016-Q1&format=csvfilewithlabels")
    wpi_csv = fetch(f"{ABS_API}/WPI/all?startPeriod=2016-Q1&format=csvfilewithlabels")
    if not cpi_csv or not wpi_csv:
        raise SystemExit("ABS Data API unreachable and no cache present.")

    cpi = {r["TIME_PERIOD"]: float(r["OBS_VALUE"])
           for r in csv.DictReader(io.StringIO(cpi_csv))}
    wpi = {r["TIME_PERIOD"]: float(r["OBS_VALUE"])
           for r in csv.DictReader(io.StringIO(wpi_csv))
           if all(r.get(k) == v for k, v in WPI_FILTER.items())}
    if not cpi or not wpi:
        raise SystemExit("ABS returned no rows for CPI or WPI; check the series keys.")

    data = {"cpi": cpi, "wpi": wpi}
    ABS_RAW.parent.mkdir(parents=True, exist_ok=True)
    ABS_RAW.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"  CPI {len(cpi)} quarters, WPI {len(wpi)} quarters")
    return data


# --------------------------------------------------------------------------
# scraping
# --------------------------------------------------------------------------

def cdx(url_pattern: str, extra: str = "") -> list[list[str]]:
    """Query the Internet Archive CDX index. Returns [[timestamp, original], ...]."""
    body = fetch(f"http://web.archive.org/cdx/search/cdx?url={url_pattern}"
                 f"&output=json&filter=statuscode:200{extra}")
    if not body:
        return []
    try:
        rows = json.loads(body)
    except json.JSONDecodeError:
        return []
    return rows[1:] if len(rows) > 1 else []


def discover_basket() -> list[str]:
    """1000-piece product URLs archived both early (2017/18) and late (2025/26).
    Those are the titles that never left the shelf, so they can anchor the chain."""
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
    basket = [u for u, y in years_by_url.items()
              if y & {"2017", "2018"} and y & {"2025", "2026"}]
    print(f"  candidate product URLs: {len(years_by_url)}")
    print(f"  constant-basket members: {len(basket)}")
    return sorted(basket)


PRICE_BLOCK = re.compile(r'<p class="price".*?</p>', re.S)
PRICE_BLOCK_FALLBACK = re.compile(r'class="price".{0,500}', re.S)
MONEY = re.compile(r"\$([\d,]+\.\d{2})")
SOLD_OUT = re.compile(r"out of stock|sold ?out|notify me", re.I)


def read_price(url: str, timestamp: str) -> dict | None:
    """List and street price from one archived product page. The template shows a
    struck-through list price beside a selling price, so the highest money token
    in the price block is the list price and the lowest is the street price."""
    html = fetch(f"http://web.archive.org/web/{timestamp}/https://{url}")
    if not html:
        return None
    block = PRICE_BLOCK.search(html) or PRICE_BLOCK_FALLBACK.search(html)
    if not block:
        return None
    values = [float(v.replace(",", "")) for v in MONEY.findall(block.group(0))]
    values = [v for v in values if 5 < v < 300]   # drop shipping thresholds etc
    if not values:
        return None
    return {"list": max(values), "street": min(values),
            "sold_out": bool(SOLD_OUT.search(html))}


def scrape() -> dict[str, dict[str, dict]]:
    basket = discover_basket()

    def one(url: str) -> tuple[str, dict[str, dict]]:
        series: dict[str, dict] = {}
        seen: dict[str, str] = {}
        for row in cdx(url, "&fl=timestamp&collapse=timestamp:6"):
            seen.setdefault(row[0][:4], row[0])
        for year, ts in seen.items():
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

def chain_index(observations, field: str) -> tuple[dict[str, float], dict[str, int]]:
    """Matched-model chain index, base year = 100. Also returns the number of
    titles behind each link, which is the honest measure of how strong it is."""
    years = sorted({y for s in observations.values() for y in s})
    if BASE_YEAR not in years:
        raise SystemExit(f"base year {BASE_YEAR} missing from observations")

    levels = {BASE_YEAR: 100.0}
    matches: dict[str, int] = {}
    level, previous = 100.0, BASE_YEAR

    for year in [y for y in years if y > BASE_YEAR]:
        ratios = []
        for s in observations.values():
            if previous in s and year in s:
                a, b = s[previous][field], s[year][field]
                if a and b:
                    ratios.append(b / a)
        if not ratios:
            continue        # no overlap: skip rather than invent a level
        link = math.exp(sum(math.log(r) for r in ratios) / len(ratios))
        level *= link
        levels[year] = round(level, 1)
        matches[year] = len(ratios)
        previous = year
    return levels, matches


def build(observations, deflators) -> dict:
    price, matches = chain_index(observations, "list")
    street, _ = chain_index(observations, "street")
    cpi, wpi = deflators["cpi"], deflators["wpi"]

    def q(series, year):
        return series.get(f"{year}-{QUARTER}")

    years = [y for y in sorted(price) if q(cpi, y) and q(wpi, y)]
    last = years[-1]
    cpi0, wpi0 = q(cpi, BASE_YEAR), q(wpi, BASE_YEAR)
    cpi_now = q(cpi, last)

    series = []
    for y in years:
        cpi_i = q(cpi, y) / cpi0 * 100
        wpi_i = q(wpi, y) / wpi0 * 100
        nominal = BASE_MEDIAN_PRICE * price[y] / 100
        series.append({
            "year": int(y),
            "price_index": price[y],
            "street_index": street.get(y),
            "cpi_index": round(cpi_i, 1),
            "wpi_index": round(wpi_i, 1),
            "minwage_index": round(MIN_WAGE[y] / MIN_WAGE[BASE_YEAR] * 100, 1),
            "real_index": round(price[y] / cpi_i * 100, 1),
            "nominal_price": round(nominal, 2),
            "real_price": round(nominal * cpi_now / q(cpi, y), 2),
            "cents_per_piece": round(nominal / PIECES * 100, 2),
            "matched_titles": matches.get(y),
        })

    first, latest = series[0], series[-1]
    g_price = latest["price_index"] / 100
    g_cpi = latest["cpi_index"] / 100
    g_wpi = latest["wpi_index"] / 100
    g_mw = latest["minwage_index"] / 100

    return {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "base_year": int(BASE_YEAR),
        "pieces": PIECES,
        "basket_size": len(observations),
        "headline": {
            "nominal_change_pct": round((g_price - 1) * 100, 1),
            "cpi_change_pct": round((g_cpi - 1) * 100, 1),
            "real_change_pct": round((g_price / g_cpi - 1) * 100, 1),
            "wpi_change_pct": round((g_wpi - 1) * 100, 1),
            "vs_wages_pct": round((g_price / g_wpi - 1) * 100, 1),
            "price_then_in_today_dollars": first["real_price"],
            "price_now": latest["nominal_price"],
            "cents_per_piece": latest["cents_per_piece"],
        },
        # Published deliberately: the answer moves a long way with the denominator,
        # and hiding that is how the first version of this index went wrong.
        "sensitivity": [
            {"denominator": "Consumer Price Index",
             "note": "general prices; the headline measure",
             "change_pct": round((g_cpi - 1) * 100, 1),
             "puzzle_vs_it_pct": round((g_price / g_cpi - 1) * 100, 1)},
            {"denominator": "Wage Price Index",
             "note": "wages, constant quality; matches this index's construction",
             "change_pct": round((g_wpi - 1) * 100, 1),
             "puzzle_vs_it_pct": round((g_price / g_wpi - 1) * 100, 1)},
            {"denominator": "National minimum wage",
             "note": "rejected: lifted deliberately faster than general wages",
             "change_pct": round((g_mw - 1) * 100, 1),
             "puzzle_vs_it_pct": round((g_price / g_mw - 1) * 100, 1)},
        ],
        "series": series,
    }


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="re-scrape the archive")
    ap.add_argument("--refresh-abs", action="store_true", help="re-fetch ABS deflators")
    args = ap.parse_args()

    deflators = load_deflators(args.refresh_abs)

    if args.refresh or not RAW.exists():
        print("Scraping archived listings (this takes several minutes)...")
        observations = scrape()
        RAW.parent.mkdir(parents=True, exist_ok=True)
        RAW.write_text(json.dumps(observations, indent=1), encoding="utf-8")
    else:
        observations = json.loads(RAW.read_text(encoding="utf-8"))
        print(f"Using cached {RAW.name}. Pass --refresh to re-scrape.")

    observations = {u: s for u, s in observations.items() if s}
    data = build(observations, deflators)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")

    h = data["headline"]
    print(f"\nThe Ravensburger 1000 Index, base {data['base_year']} = 100 "
          f"({data['basket_size']} titles)")
    print(f"  RRP                 {h['nominal_change_pct']:+.1f}%")
    print(f"  CPI                 {h['cpi_change_pct']:+.1f}%")
    print(f"  REAL CHANGE         {h['real_change_pct']:+.1f}%")
    print(f"  wages (WPI)         {h['wpi_change_pct']:+.1f}%  -> vs wages "
          f"{h['vs_wages_pct']:+.1f}%")
    print(f"\n  ${BASE_MEDIAN_PRICE:.2f} in {data['base_year']} is "
          f"${h['price_then_in_today_dollars']:.2f} in today's money. "
          f"Today it lists at ${h['price_now']:.2f}.")
    print("\n  sensitivity:")
    for row in data["sensitivity"]:
        print(f"    {row['denominator']:24s} {row['change_pct']:+6.1f}%  "
              f"-> puzzle {row['puzzle_vs_it_pct']:+.1f}%   ({row['note']})")
    print(f"\nWrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
