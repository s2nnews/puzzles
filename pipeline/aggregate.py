"""Build the Premium Puzzles Index from the raw signal databases.

Produces data/processed/index.json: the published artifact the website reads.

The headline Index is a category-level demand index built from marketplace
sales-rank + review data (our densest, cleanest source), framed exactly like
an equity index — titles are constituents, brands are sectors. Tracked-title
signals (retailer stock, community mentions) enrich individual titles where
they match, but the market-internals (concentration, breadth, regime) come
from the full category cross-section.

Absolute, interpretable transforms (not per-day renormalisation) so the index
level can actually rise and fall like a real index.

Usage:
    python pipeline/aggregate.py
"""

import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scrapers"))
from common import DATA_DIR, RAW_DIR  # noqa: E402

OUT_FILE = DATA_DIR / "processed" / "index.json"
AMAZON_DB = RAW_DIR / "amazon_bsr.db"
STOCK_DB = RAW_DIR / "retailer_stock.db"
REDDIT_DB = RAW_DIR / "reddit_signals.db"

# Substantial markets for the global view. interest_by_region ranks every
# country (143 of them), but tiny territories spike on relative interest
# (Dominica, Malta, Isle of Man...), so the headline "where does AU rank"
# is read against this curated set of significant economies/populations.
# The raw CSV keeps all countries; this only governs display.
MAJOR_MARKETS = {
    "United States", "United Kingdom", "Australia", "New Zealand", "Canada",
    "Ireland", "Germany", "France", "Italy", "Spain", "Netherlands", "Belgium",
    "Switzerland", "Austria", "Sweden", "Norway", "Denmark", "Finland",
    "Poland", "Portugal", "Greece", "Czechia", "Hungary", "Romania",
    "Japan", "South Korea", "China", "India", "Singapore", "Malaysia",
    "Indonesia", "Philippines", "Thailand", "Vietnam", "Hong Kong", "Taiwan",
    "South Africa", "Brazil", "Mexico", "Argentina", "Chile",
    "United Arab Emirates", "Saudi Arabia", "Israel", "Turkey",
}

KNOWN_BRANDS = [
    "Ravensburger", "Funbox", "Cobble Hill", "Gibsons", "Blue Opal",
    "Clementoni", "Educa", "Schmidt", "Holdson", "Eurographics", "Galison",
    "Mudpuppy", "Buffalo Games", "Trefl", "Heye", "Jumbo", "Wasgij",
    "Springbok", "White Mountain", "Pomegranate", "Magic Puzzle Company",
    "Melissa & Doug", "New York Puzzle Company", "Chronicle Books",
]


def rank_score(bsr: int | None) -> float | None:
    """Absolute 0-100 demand score from sales rank. BSR 1 -> 100, 10 -> 90,
    100 -> 80, 1k -> 70, 10k -> 60. Lower rank = stronger sales = higher score."""
    if not bsr or bsr < 1:
        return None
    return max(0.0, min(100.0, 100.0 - 10.0 * math.log10(bsr)))


def canonical_brand(raw: str | None) -> str:
    """Known brand or 'Other'. No first-word guessing — that leaked title
    words ('Jan', 'Cross', 'Studio') in as fake brands."""
    if not raw:
        return "Other"
    low = raw.lower()
    for b in KNOWN_BRANDS:
        if b.lower() in low:
            return b
    return "Other"


def load_amazon() -> tuple[list[str], dict]:
    """(sorted days, {asin: {day: row}}) for products that carry a BSR."""
    conn = sqlite3.connect(AMAZON_DB)
    conn.row_factory = sqlite3.Row
    days = [r[0] for r in conn.execute(
        "select distinct run_date from bsr_snapshots order by run_date")]
    by_asin: dict = defaultdict(dict)
    for r in conn.execute("select * from bsr_snapshots"):
        by_asin[r["asin"]][r["run_date"]] = r
    conn.close()
    return days, by_asin


def latest_stock_pressure() -> dict[str, float]:
    """{title: out-of-stock fraction across its tracked listings} on the
    latest stock run. A title OOS everywhere = 1.0 (max demand pressure)."""
    if not STOCK_DB.exists():
        return {}
    conn = sqlite3.connect(STOCK_DB)
    day = conn.execute("select max(run_date) from stock_snapshots").fetchone()[0]
    pressure: dict[str, list] = defaultdict(list)
    for title, status in conn.execute(
            "select title, status from stock_snapshots where run_date=? "
            "and status in ('in_stock','out_of_stock')", (day,)):
        pressure[title].append(1.0 if status == "out_of_stock" else 0.0)
    conn.close()
    return {t: sum(v) / len(v) for t, v in pressure.items() if v}


def latest_mentions() -> dict[str, int]:
    if not REDDIT_DB.exists():
        return {}
    conn = sqlite3.connect(REDDIT_DB)
    day = conn.execute("select max(run_date) from reddit_snapshots").fetchone()[0]
    out = {ent: m for ent, m in conn.execute(
        "select entity, mentions_30d from reddit_snapshots "
        "where run_date=? and entity_type='brand'", (day,))}
    conn.close()
    return out


def build_global() -> dict | None:
    """Global puzzle-demand block from the latest global_trends CSV: per-country
    search interest, filtered to major markets, with Australia's world rank."""
    files = sorted(RAW_DIR.glob("global_trends_*.csv"))
    if not files:
        return None
    src = files[-1]
    rows = []
    with open(src, encoding="utf-8") as f:
        next(f, None)  # header
        for line in f:
            country, interest = line.rsplit(",", 1)
            rows.append((country.strip(), float(interest)))
    majors = [(c, v) for c, v in rows if c in MAJOR_MARKETS]
    if not majors:
        return None
    # Rescale so the strongest major market = 100 (clean bar axis).
    top = max(v for _, v in majors) or 1.0
    majors = sorted(((c, round(v / top * 100, 1)) for c, v in majors),
                    key=lambda kv: -kv[1])
    au_rank = next((i + 1 for i, (c, _) in enumerate(majors) if c == "Australia"), None)
    au_val = next((v for c, v in majors if c == "Australia"), None)
    as_of = src.stem.replace("global_trends_", "")
    return {
        "as_of": as_of,
        "measure": "English-language search interest ('jigsaw puzzle', "
                   "'1000 piece puzzle'), indexed to the strongest major market",
        "au_rank": au_rank,
        "au_value": au_val,
        "major_markets": len(majors),
        "countries": [{"country": c, "interest": v, "is_au": c == "Australia"}
                      for c, v in majors],
        "note": "Measured on English search terms, so it reflects the "
                "English-speaking puzzle market (where Australia competes) and "
                "under-weights markets that search in their own language "
                "(Germany, France, Japan).",
    }


def main() -> int:
    days, by_asin = load_amazon()
    if len(days) < 1:
        print("No Amazon data — nothing to build.", file=sys.stderr)
        return 1
    today = days[-1]
    prev = days[-2] if len(days) > 1 else None
    inception = days[0]

    # Index constituents: products with a BSR on both inception and today,
    # so the level series is measured on a fixed basket.
    constituents = [a for a, rows in by_asin.items()
                    if inception in rows and today in rows
                    and rows[inception]["bsr"] and rows[today]["bsr"]]

    def level_for(day: str, equal_weight: bool = False) -> float:
        num = den = 0.0
        for a in constituents:
            row = by_asin[a].get(day)
            if not row or not row["bsr"]:
                continue
            sc = rank_score(row["bsr"])
            w = 1.0 if equal_weight else max(row["review_count"] or 0, 1)
            num += sc * w
            den += w
        return num / den if den else 0.0

    base_cap = level_for(inception) or 1.0
    base_ew = level_for(inception, equal_weight=True) or 1.0
    index_series = [
        {"date": d,
         "level": round(level_for(d) / base_cap * 100, 2),
         "equal_weight": round(level_for(d, equal_weight=True) / base_ew * 100, 2)}
        for d in days
    ]

    # Market internals on the full current cross-section (not just constituents).
    current = [rows[today] for rows in by_asin.values() if today in rows]
    reviews = [(r["review_count"] or 0) for r in current]
    total_rev = sum(reviews) or 1
    top7 = sum(sorted(reviews, reverse=True)[:7]) / total_rev

    brand_rev: dict[str, float] = defaultdict(float)
    for r in current:
        brand_rev[canonical_brand(r["brand"])] += (r["review_count"] or 0)
    hhi = sum((v / total_rev) ** 2 for v in brand_rev.values())

    # Breadth: share of constituents that gained RELATIVE strength vs prior
    # day. Absolute BSR drifts with scrape time-of-day (a common-mode shift
    # that made 68/72 "worsen" on raw deltas); ranking each day's BSRs
    # cross-sectionally and comparing percentiles cancels that drift, giving
    # a market-neutral advance/decline line.
    def bsr_percentiles(day: str) -> dict[str, float]:
        ranked = sorted(
            (a for a in constituents
             if by_asin[a].get(day) and by_asin[a][day]["bsr"]),
            key=lambda a: by_asin[a][day]["bsr"])  # best BSR first
        n = len(ranked)
        return {a: 1.0 - i / (n - 1) for i, a in enumerate(ranked)} if n > 1 else {}

    breadth = None
    if prev:
        pct_now, pct_prev = bsr_percentiles(today), bsr_percentiles(prev)
        shared = [a for a in pct_now if a in pct_prev]
        if shared:
            improved = sum(pct_now[a] > pct_prev[a] for a in shared)
            breadth = round(100 * improved / len(shared), 1)

    mom_7d = round(index_series[-1]["level"] - index_series[0]["level"], 2)
    if breadth is None:
        regime = "insufficient_history"
    elif mom_7d >= 0 and breadth >= 50:
        regime = "expansion"
    elif mom_7d < 0 and breadth < 50:
        regime = "contraction"
    else:
        regime = "rotation"

    # Brand sub-indices: review-weighted mean rank_score today, rebased to
    # inception=100 per brand (sectors).
    def brand_level(day: str) -> dict[str, float]:
        num: dict[str, float] = defaultdict(float)
        den: dict[str, float] = defaultdict(float)
        for a in constituents:
            row = by_asin[a].get(day)
            if not row or not row["bsr"]:
                continue
            b = canonical_brand(row["brand"])
            w = max(row["review_count"] or 0, 1)
            num[b] += rank_score(row["bsr"]) * w
            den[b] += w
        return {b: num[b] / den[b] for b in num if den[b]}

    bl_now, bl_base = brand_level(today), brand_level(inception)
    brand_indices = {b: round(bl_now[b] / bl_base[b] * 100, 1)
                     for b in bl_now if b in bl_base and bl_base[b]}

    # Per-title rows for the visualisation (full current cross-section).
    stock_pressure = latest_stock_pressure()
    mentions = latest_mentions()
    titles = []
    for r in sorted(current, key=lambda x: (x["bsr"] or 1e9)):
        prow = by_asin[r["asin"]].get(prev) if prev else None
        rev_vel = ((r["review_count"] or 0) - (prow["review_count"] or 0)) if prow else None
        sc = rank_score(r["bsr"])
        titles.append({
            "asin": r["asin"],
            "title": r["title"],
            "brand": canonical_brand(r["brand"]),
            "piece_count": r["piece_count"],
            "index_score": round(sc, 1) if sc is not None else None,
            "bsr": r["bsr"],
            "review_count": r["review_count"],
            "review_velocity_1d": rev_vel,
            "avg_rating": r["avg_rating"],
            "price_au": r["price_aud"],
            "brand_mentions_30d": mentions.get(canonical_brand(r["brand"])),
        })

    payload = {
        "as_of": today,
        "inception": inception,
        "days_of_history": len(days),
        "market": {
            "index_level": index_series[-1]["level"],
            "equal_weight_level": index_series[-1]["equal_weight"],
            "index_mom": mom_7d,
            "cap_vs_equal_spread": round(
                index_series[-1]["level"] - index_series[-1]["equal_weight"], 2),
            "top7_share": round(top7, 3),
            "hhi_brands": round(hhi, 4),
            "breadth_pct": breadth,
            "regime": regime,
            "constituents": len(constituents),
            "universe": len(current),
            "brand_indices": dict(sorted(brand_indices.items(),
                                         key=lambda kv: -kv[1])),
        },
        "index_series": index_series,
        "titles": titles,
        "global": build_global(),
        "disclaimer": "The Premium Puzzles Index is derived from multiple "
                      "public data sources across retail, search, and "
                      "community platforms.",
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    m = payload["market"]
    print(f"Index built for {today}: level={m['index_level']} "
          f"(EW {m['equal_weight_level']}), regime={m['regime']}, "
          f"top7={m['top7_share']:.0%}, breadth={m['breadth_pct']}%, "
          f"{len(titles)} titles -> {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
