#!/usr/bin/env python3
"""Nightly data collector for the marketing dashboard.

Builds dashboard/data.json (one object per day, sorted by Date ascending)
from Shopify (sales, sessions funnel, units), Omnisend (subscriber growth),
ShipStation (shipping cost) and an optional Porter CSV export (Meta spend /
conversion value). The dashboard page fetches ./data.json directly.

Reads config from environment variables, falling back to dashboard/.env
(KEY=VALUE lines). Fails loudly on API errors rather than writing partial
garbage; sources whose keys are absent leave their columns blank ("").

stdlib + requests only.
"""

import csv
import io
import json
import os
import sys
import time
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(HERE, "data.json")
SYDNEY = ZoneInfo("Australia/Sydney")
SHOPIFY_API_VERSION = "2025-07"

COLUMNS = [
    "Date", "Orders", "Gross sales", "Discounts", "Returns", "Net sales",
    "Total sales", "AOV", "Sessions", "Sessions with cart adds",
    "Sessions reached checkout", "Sessions completed checkout",
    "Conversion rate", "Email subscribes", "Email unsubscribes",
    "Net subscriber growth", "Meta spend", "Meta conv value", "Puzzles sold",
    "Subscriber list size", "Shipping charged", "Shipping cost",
]


def die(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


def load_dotenv():
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.split(" #")[0].strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), value)


def http_retry(call, tries=5):
    """Run a requests call, retrying on 429/5xx with backoff."""
    for attempt in range(tries):
        resp = call()
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = float(resp.headers.get("Retry-After") or 2 ** attempt)
            time.sleep(min(wait, 60))
            continue
        return resp
    return resp


def to_num(value):
    if value is None or value == "":
        return ""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return ""
    return int(f) if f == int(f) else round(f, 2)


# ---------------------------------------------------------------- Shopify

def shopify_graphql(store, token, query, variables=None):
    url = "https://%s/admin/api/%s/graphql.json" % (store, SHOPIFY_API_VERSION)
    resp = http_retry(lambda: requests.post(
        url, json={"query": query, "variables": variables or {}},
        headers={"X-Shopify-Access-Token": token}, timeout=60))
    if resp.status_code != 200:
        die("Shopify HTTP %s: %s" % (resp.status_code, resp.text[:400]))
    data = resp.json()
    if data.get("errors"):
        die("Shopify GraphQL errors: %s" % json.dumps(data["errors"])[:600])
    return data["data"]


def shopifyql(store, token, ql):
    """Run a ShopifyQL query, return list of row dicts keyed by column name.

    On API version 2025-07 shopifyqlQuery returns { parseErrors,
    tableData { columns, rows } } directly (no TableResponse fragment);
    rows is a JSON scalar: a list of dicts keyed by column name, values
    as strings (or null).
    """
    gql = ("query($q: String!) { shopifyqlQuery(query: $q) { parseErrors "
           "tableData { columns { name } rows } } }")
    node = shopify_graphql(store, token, gql, {"q": ql})["shopifyqlQuery"]
    if node.get("parseErrors"):
        die("ShopifyQL parse errors for [%s]: %s" % (ql, node["parseErrors"]))
    table = node.get("tableData") or {}
    return table.get("rows") or []


def fetch_sales(store, token, days):
    ql = ("FROM sales SHOW orders, gross_sales, discounts, returns, "
          "net_sales, total_sales, average_order_value, shipping_charges "
          "TIMESERIES day SINCE -%dd UNTIL today" % days)
    out = {}
    for row in shopifyql(store, token, ql):
        out[row["day"][:10]] = row
    if not out:
        die("Shopify sales query returned no rows")
    return out


def fetch_sessions(store, token, days):
    ql = ("FROM sessions SHOW sessions, sessions_with_cart_additions, "
          "sessions_that_reached_checkout, sessions_that_completed_checkout "
          "TIMESERIES day SINCE -%dd UNTIL today" % days)
    return {row["day"][:10]: row for row in shopifyql(store, token, ql)}


def fetch_units(store, token, since):
    """Sum line-item units per Sydney day from the Orders API."""
    gql = ("query($q: String!, $cursor: String) { "
           "orders(first: 250, query: $q, after: $cursor) { "
           "pageInfo { hasNextPage endCursor } "
           "nodes { createdAt currentSubtotalLineItemsQuantity } } }")
    # created_at filters in UTC; go a day wide and bucket by Sydney date.
    q = "created_at:>=%s" % (since - timedelta(days=1)).isoformat()
    units, cursor = {}, None
    while True:
        data = shopify_graphql(store, token, gql, {"q": q, "cursor": cursor})
        conn = data["orders"]
        for node in conn["nodes"]:
            created = datetime.fromisoformat(node["createdAt"].replace("Z", "+00:00"))
            day = created.astimezone(SYDNEY).date().isoformat()
            units[day] = units.get(day, 0) + (node["currentSubtotalLineItemsQuantity"] or 0)
        if not conn["pageInfo"]["hasNextPage"]:
            return units
        cursor = conn["pageInfo"]["endCursor"]


# --------------------------------------------------------------- Omnisend

def fetch_omnisend(api_key, since, today):
    """Daily subscribedEmail/unsubscribedEmail via /v5/analytics/statistics.

    The API takes {queries:[...]} with a required timestamp dimension; at day
    granularity a query spans at most 60 days and must not cross a calendar
    year, so the window is chunked. `to` is exclusive.
    """
    out = {}
    start, end = since, today + timedelta(days=1)
    while start < end:
        year_end = date(start.year + 1, 1, 1)
        stop = min(start + timedelta(days=60), end, year_end)
        frm = datetime.combine(start, dtime.min, SYDNEY).isoformat()
        if stop == year_end and stop != end:
            to = datetime.combine(stop - timedelta(days=1), dtime(23, 59, 59), SYDNEY).isoformat()
        else:
            to = datetime.combine(stop, dtime.min, SYDNEY).isoformat()
        body = {"queries": [{
            "alias": "subscriber-growth",
            "metrics": [{"name": "subscribedEmail"}, {"name": "unsubscribedEmail"}],
            "dimensions": [{"name": "timestamp", "granularity": "day"}],
            "dateRange": {"from": frm, "to": to},
        }]}
        resp = http_retry(lambda: requests.post(
            "https://api.omnisend.com/v5/analytics/statistics",
            json=body, headers={"X-API-KEY": api_key}, timeout=60))
        if resp.status_code != 200:
            die("Omnisend HTTP %s: %s" % (resp.status_code, resp.text[:400]))
        for block in resp.json().get("statistics", []):
            for row in block.get("rows", []):
                day = row["timestamp"][:10]
                out[day] = (int(row.get("subscribedEmail") or 0),
                            int(row.get("unsubscribedEmail") or 0))
        start = stop
        time.sleep(1)  # rate limit: 10 requests/min
    return out


# ------------------------------------------------------------- ShipStation

def fetch_shipstation(api_key, api_secret, since, today):
    """Sum shipmentCost + insuranceCost per shipDate, skipping voided."""
    out, page = {}, 1
    while True:
        resp = http_retry(lambda: requests.get(
            "https://ssapi.shipstation.com/shipments",
            params={"shipDateStart": since.isoformat(),
                    "shipDateEnd": today.isoformat(),
                    "pageSize": 500, "page": page},
            auth=(api_key, api_secret), timeout=60))
        if resp.status_code != 200:
            die("ShipStation HTTP %s: %s" % (resp.status_code, resp.text[:400]))
        body = resp.json()
        for sh in body.get("shipments", []):
            if sh.get("voided"):
                continue
            day = (sh.get("shipDate") or "")[:10]
            if not day:
                continue
            cost = float(sh.get("shipmentCost") or 0) + float(sh.get("insuranceCost") or 0)
            out[day] = round(out.get(day, 0) + cost, 2)
        if page >= int(body.get("pages") or 1):
            return out
        page += 1
        time.sleep(1)


# ------------------------------------------------------- Meta (Porter CSV)

def fetch_meta(src):
    """Optional Porter export (URL or local path), columns date,spend,conv_value."""
    if src.startswith("http://") or src.startswith("https://"):
        resp = http_retry(lambda: requests.get(src, timeout=60))
        if resp.status_code != 200:
            die("META_CSV HTTP %s: %s" % (resp.status_code, resp.text[:200]))
        text = resp.text
    else:
        with open(src, encoding="utf-8-sig") as f:
            text = f.read()
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        raw = row.get("date", "")
        day = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"):
            try:
                day = datetime.strptime(raw[:10], fmt).date().isoformat()
                break
            except ValueError:
                pass
        if not day:
            continue
        out[day] = (to_num(row.get("spend")), to_num(row.get("conv_value")))
    return out


# ------------------------------------------------------------------- main

def main():
    load_dotenv()
    store = os.environ.get("SHOPIFY_STORE", "").strip()
    token = os.environ.get("SHOPIFY_TOKEN", "").strip()
    if not store or not token:
        die("SHOPIFY_STORE and SHOPIFY_TOKEN are required (dashboard/.env or env)")
    if "." not in store:
        store += ".myshopify.com"
    days = int(os.environ.get("DAYS") or 120)
    today = datetime.now(SYDNEY).date()
    since = today - timedelta(days=days)

    print("Collecting %d days (%s to %s) for %s" % (days, since, today, store))
    sales = fetch_sales(store, token, days)
    sessions = fetch_sessions(store, token, days)
    units = fetch_units(store, token, since)
    print("Shopify: %d sales days, %d session days, %d unit days"
          % (len(sales), len(sessions), len(units)))

    omni_key = os.environ.get("OMNISEND_API_KEY", "").strip()
    omni = fetch_omnisend(omni_key, since, today) if omni_key else {}
    print("Omnisend: %d days" % len(omni) if omni_key
          else "Omnisend: no OMNISEND_API_KEY, leaving email columns blank")

    ss_key = os.environ.get("SHIPSTATION_API_KEY", "").strip()
    ss_secret = os.environ.get("SHIPSTATION_API_SECRET", "").strip()
    ship = fetch_shipstation(ss_key, ss_secret, since, today) if ss_key and ss_secret else {}
    print("ShipStation: %d ship days" % len(ship) if ss_key and ss_secret
          else "ShipStation: no keys, leaving Shipping cost blank")

    meta_src = os.environ.get("META_CSV", "").strip()
    meta = fetch_meta(meta_src) if meta_src else {}
    print("Meta: %d days" % len(meta) if meta_src
          else "Meta: no META_CSV, leaving Meta columns blank")

    rows = []
    for day in sorted(sales):
        s = sales[day]
        sess = sessions.get(day, {})
        n_sessions = int(sess.get("sessions") or 0)
        completed = int(sess.get("sessions_that_completed_checkout") or 0)
        subs, unsubs = omni.get(day, ("", ""))
        m_spend, m_value = meta.get(day, ("", ""))
        row = {
            "Date": day,
            "Orders": to_num(s.get("orders")),
            "Gross sales": to_num(s.get("gross_sales")),
            "Discounts": to_num(s.get("discounts")),
            "Returns": to_num(s.get("returns")),
            "Net sales": to_num(s.get("net_sales")),
            "Total sales": to_num(s.get("total_sales")),
            "AOV": to_num(s.get("average_order_value")),
            "Sessions": to_num(sess.get("sessions")),
            "Sessions with cart adds": to_num(sess.get("sessions_with_cart_additions")),
            "Sessions reached checkout": to_num(sess.get("sessions_that_reached_checkout")),
            "Sessions completed checkout": to_num(sess.get("sessions_that_completed_checkout")),
            "Conversion rate": round(completed / n_sessions, 4) if n_sessions else "",
            "Email subscribes": subs,
            "Email unsubscribes": unsubs,
            "Net subscriber growth": subs - unsubs if subs != "" else "",
            "Meta spend": m_spend,
            "Meta conv value": m_value,
            "Puzzles sold": units.get(day, 0),
            "Subscriber list size": "",
            "Shipping charged": to_num(s.get("shipping_charges")),
            "Shipping cost": ship.get(day, ""),
        }
        rows.append({k: row[k] for k in COLUMNS})

    with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rows, f, indent=1)
        f.write("\n")
    print("Wrote %d rows (%s to %s) to %s"
          % (len(rows), rows[0]["Date"], rows[-1]["Date"], OUT_PATH))


if __name__ == "__main__":
    main()
