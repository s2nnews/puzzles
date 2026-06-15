"""Bake data/processed/index.json into a self-contained dashboard.

Produces web/puzzle_index.html with the data embedded, so it works when
double-clicked offline (no server, no CORS). When served online it also
auto-freshens from the repo's raw index.json. The same file is what gets
embedded on the Shopify page.

Usage:
    python web/build_chart.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "data" / "processed" / "index.json"
TEMPLATE = ROOT / "web" / "template.html"
OUT = ROOT / "web" / "puzzle_index.html"


def main() -> int:
    if not INDEX.exists():
        print(f"{INDEX} missing — run pipeline/aggregate.py first", file=sys.stderr)
        return 1
    data = INDEX.read_text(encoding="utf-8")
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__INDEX_DATA__", data)
            .replace("__BUILT_AT__", built_at))
    OUT.write_text(html, encoding="utf-8")
    kb = len(html.encode("utf-8")) / 1024
    print(f"Built {OUT} ({kb:.0f} KB) from Index as of "
          f"{json.loads(data)['as_of']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
