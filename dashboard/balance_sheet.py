"""Build dashboard/balance-sheet.json: the high-level balance sheet.

    python dashboard/balance_sheet.py

Two halves, and the split is the whole design.

**The manual half** is what only Michael knows: cash at bank, PayPal, what is
owed to each supplier, what has been ordered and paid for but has not physically
arrived. Nothing reads those from an API because no API holds them. They live in
the `manual` block of `balance-sheet.json`, Michael edits them, and this script
never overwrites them.

**The derived half** is pulled fresh every run: stock on hand at cost and at
retail from the Shopify Admin API, and the Shopify Capital position computed
from the daily takings already sitting in `data.json`.

## Why the manual block survives without a secret

`balance-sheet.json` is gitignored and rides inside `feeds.enc` exactly like the
other feeds, so `decrypt.py` lays it back down on a CI runner before this script
runs. The manual figures therefore persist in the encrypted bundle and need no
repo secret of their own. Edit them locally, run `encrypt.py`, push.

**If the file is absent this script refuses to invent one.** A balance sheet
built from defaults would render a confident page of fiction, which is worse
than no page at all. See rule 7 in CLAUDE.md.

## The stock line, and the gap it is here to close

Shopify inventory is set from what physically arrived, never from a supplier
invoice. That rule is right and it is not negotiable, but it means stock paid
for and still in transit is invisible in Shopify **by design**. Carried at
Shopify alone the business looks poorer than it is every time it buys. So
`stock_ordered_not_received` is a manual asset line fed from invoices, and its
matching creditor sits on the other side.

Stock is carried **at cost**, which is the conservative basis and the correct
one. `stock_retail` is reported alongside it as memo only: it is what the shelf
would realise at full price, and the difference is unrealised margin, not an
asset.

## Not GST registered

Confirmed 2026-09-01. There is no GST payable, no input credit, and purchase GST
is a real cost already inside the unit costs Shopify holds. Do not add a GST
line to this sheet until registration actually happens, which is compulsory
above $75k of turnover and is getting closer.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
OUT = HERE / "balance-sheet.json"
DAILY = HERE / "data.json"
API_VERSION = "2025-07"


def load_dotenv():
    """Read dashboard/.env, the same way collect.py and encrypt.py do."""
    path = HERE / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(),
                              value.split(" #")[0].strip().strip('"').strip("'"))


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------- Shopify

VARIANTS_Q = """
query($after: String) {
  productVariants(first: 250, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      price
      inventoryQuantity
      inventoryItem { unitCost { amount } }
      product { status }
    }
  }
}
"""


def stock_on_hand(store, token):
    """Units, cost value and retail value of everything with positive stock.

    Negative quantities are floored at zero rather than netted off. A negative
    is a historical over-sell on a discontinued line, not stock we can sell, and
    letting it subtract would quietly understate the shelf.

    `cost_missing_skus` is reported because a variant with no unit cost loaded
    contributes retail but no cost, so the cost total is an understatement by
    exactly that much. The dashboard says so on the tile rather than hiding it.
    """
    url = "https://%s/admin/api/%s/graphql.json" % (store, API_VERSION)
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    units = cost = retail = 0.0
    skus = missing = 0
    after = None
    while True:
        r = requests.post(url, headers=headers, timeout=60,
                          json={"query": VARIANTS_Q, "variables": {"after": after}})
        r.raise_for_status()
        payload = r.json()
        if "errors" in payload:
            sys.exit("Shopify rejected the stock query: %s"
                     % json.dumps(payload["errors"]))
        block = payload["data"]["productVariants"]
        for node in block["nodes"]:
            qty = node.get("inventoryQuantity") or 0
            if qty <= 0:
                continue
            unit_cost = (node.get("inventoryItem") or {}).get("unitCost") or {}
            unit_cost = num(unit_cost.get("amount"))
            skus += 1
            units += qty
            cost += unit_cost * qty
            retail += num(node.get("price")) * qty
            if unit_cost == 0:
                missing += 1
        if not block["pageInfo"]["hasNextPage"]:
            break
        after = block["pageInfo"]["endCursor"]
        time.sleep(0.4)

    return {
        "units": int(units),
        "skus": skus,
        "cost": round(cost, 2),
        "retail": round(retail, 2),
        "cost_missing_skus": missing,
    }


# ---------------------------------------------------------------- Capital

def capital_position(cfg):
    """Estimate what is left to remit on the Shopify Capital advance.

    Repayment is 25% of daily takings, so the amount repaid is derivable from
    the daily sales already in `data.json` without a second API call. This is an
    **estimate and the file says so**: the haircut is taken on turnover settled
    through Shopify, so any order paid another way is not in the base, and the
    real figure is the one on the Capital page in the admin.

    Michael confirmed the refinancing threshold is **51% repaid**, 2026-09-01.
    """
    if not DAILY.exists():
        return None
    rows = json.loads(DAILY.read_text(encoding="utf-8"))
    drawn_on = cfg.get("drawn_on", "")
    taken = sum(num(r.get("Total sales")) for r in rows
                if str(r.get("Date", "")) >= drawn_on)

    total = num(cfg.get("total_remittance"))
    haircut = num(cfg.get("haircut")) or 0.25
    repaid = min(taken * haircut, total)
    threshold = num(cfg.get("refinance_threshold")) or 0.51

    return {
        "advance": num(cfg.get("advance")),
        "fee": num(cfg.get("fee")),
        "total_remittance": total,
        "drawn_on": drawn_on,
        "haircut": haircut,
        "turnover_since_drawn": round(taken, 2),
        "repaid_estimate": round(repaid, 2),
        "outstanding_estimate": round(total - repaid, 2),
        "pct_repaid": round(repaid / total, 4) if total else 0,
        "refinance_threshold": threshold,
        "refinance_gap": round(max(total * threshold - repaid, 0), 2),
        "basis": "25%% of Total sales since %s, from data.json. An estimate: "
                 "the haircut applies to turnover settled through Shopify. "
                 "The exact figure is on the Capital page in the admin."
                 % (drawn_on or "the advance date"),
    }


# ---------------------------------------------------------------- assemble

def main() -> int:
    load_dotenv()

    if not OUT.exists():
        sys.exit(
            "balance-sheet.json is missing, so there are no manual figures to "
            "build on.\nRefusing to invent them: cash at bank and creditor "
            "balances exist nowhere else.\nOn a runner it is decrypt.py that "
            "restores this file, so check that ran first."
        )

    sheet = json.loads(OUT.read_text(encoding="utf-8"))
    manual = sheet.get("manual")
    if not manual:
        sys.exit("balance-sheet.json has no `manual` block. Nothing to build on.")

    store = os.environ.get("SHOPIFY_STORE", "")
    token = os.environ.get("SHOPIFY_TOKEN", "")
    if not store or not token:
        sys.exit("SHOPIFY_STORE and SHOPIFY_TOKEN are required for the stock line.")
    if not store.endswith(".myshopify.com"):
        store += ".myshopify.com"

    stock = stock_on_hand(store, token)
    capital = capital_position(manual.get("capital", {}))

    assets = [
        {"label": "Cash at bank", "amount": num(manual.get("cash_at_bank")),
         "source": "manual, %s" % manual.get("updated", "undated")},
        {"label": "PayPal", "amount": num(manual.get("paypal")),
         "source": "manual, %s" % manual.get("updated", "undated")},
        {"label": "Stock on hand, at cost", "amount": stock["cost"],
         "source": "Shopify, live. %s units across %s SKUs"
                   % (f"{stock['units']:,}", f"{stock['skus']:,}")},
    ]
    for item in manual.get("stock_ordered_not_received", []):
        assets.append({
            "label": "Ordered, not received: %s" % item.get("name", "?"),
            "amount": num(item.get("amount")),
            "source": item.get("note", "manual"),
        })

    liabilities = []
    if capital:
        liabilities.append({
            "label": "Shopify Capital, remaining",
            "amount": capital["outstanding_estimate"],
            "source": "estimated, %.0f%% repaid" % (capital["pct_repaid"] * 100),
        })
    for item in manual.get("creditors", []):
        liabilities.append({
            "label": item.get("name", "?"),
            "amount": num(item.get("amount")),
            "source": ("due %s" % item["due"]) if item.get("due") else "manual",
            "due": item.get("due", ""),
            "note": item.get("note", ""),
        })

    total_assets = round(sum(a["amount"] for a in assets), 2)
    total_liabilities = round(sum(l["amount"] for l in liabilities), 2)

    sheet["as_at"] = date.today().isoformat()
    sheet["derived"] = {"stock": stock, "capital": capital}
    sheet["assets"] = assets
    sheet["liabilities"] = liabilities
    sheet["totals"] = {
        "assets": total_assets,
        "liabilities": total_liabilities,
        "net_assets": round(total_assets - total_liabilities, 2),
        # Memo only. Stock is carried at cost; this is what the same shelf
        # realises at full price, and the gap is margin that has not happened.
        "stock_retail_memo": stock["retail"],
        "unrealised_margin_memo": round(stock["retail"] - stock["cost"], 2),
    }

    OUT.write_text(json.dumps(sheet, indent=1) + "\n", encoding="utf-8")

    print("  + balance-sheet.json  as at %s" % sheet["as_at"])
    print("      assets      $%12s" % f"{total_assets:,.2f}")
    print("      liabilities $%12s" % f"{total_liabilities:,.2f}")
    print("      net assets  $%12s" % f"{sheet['totals']['net_assets']:,.2f}")
    if stock["cost_missing_skus"]:
        print("      ! %d in-stock SKUs carry no unit cost, so cost is understated"
              % stock["cost_missing_skus"])
    if capital:
        print("      capital %.0f%% repaid, $%s to the %.0f%% refinance point"
              % (capital["pct_repaid"] * 100,
                 f"{capital['refinance_gap']:,.0f}",
                 capital["refinance_threshold"] * 100))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
