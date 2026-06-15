"""Bake data/processed/index.json into a self-contained dashboard.

Produces web/puzzle_index.html with the data embedded, so it works when
double-clicked offline (no server, no CORS). When served online it also
auto-freshens from the repo's raw index.json. The same file is what gets
embedded on the Shopify page.

Usage:
    python web/build_chart.py
"""

import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "data" / "processed" / "index.json"
LOGO = ROOT / "web" / "assets" / "premium-puzzles-logo.png"

# (template, output): the full dashboard and the basic brand-only version
# (logo + title + Brand Dominance chart) for newsletters / early embeds.
BUILDS = [
    (ROOT / "web" / "template.html",        ROOT / "web" / "puzzle_index.html"),
    (ROOT / "web" / "template_basic.html",  ROOT / "web" / "puzzle_index_basic.html"),
    (ROOT / "web" / "template_global.html", ROOT / "web" / "puzzle_index_global.html"),
]


def logo_data_uri() -> str:
    """Base64 PNG data URI for the logo so the page is fully self-contained.
    PNG (not AVIF) for universal browser support, incl. data-URI rendering."""
    if not LOGO.exists():
        return ""
    b64 = base64.b64encode(LOGO.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def main() -> int:
    if not INDEX.exists():
        print(f"{INDEX} missing — run pipeline/aggregate.py first", file=sys.stderr)
        return 1
    data = INDEX.read_text(encoding="utf-8")
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    logo = logo_data_uri()
    as_of = json.loads(data)["as_of"]
    for template, out in BUILDS:
        if not template.exists():
            print(f"skip {out.name}: {template.name} missing", file=sys.stderr)
            continue
        html = (template.read_text(encoding="utf-8")
                .replace("__INDEX_DATA__", data)
                .replace("__BUILT_AT__", built_at)
                .replace("__LOGO_DATA__", logo))
        out.write_text(html, encoding="utf-8")
        print(f"Built {out.name} ({len(html.encode('utf-8'))/1024:.0f} KB) "
              f"from Index as of {as_of}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
