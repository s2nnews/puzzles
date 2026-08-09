#!/usr/bin/env python3
"""Nightly data collector for the marketing dashboard.

Builds dashboard/data.json (one object per day, sorted by Date ascending)
from Shopify (sales, sessions funnel, units), Omnisend (subscriber growth),
ShipStation (shipping cost) and an optional Porter CSV export (Meta spend /
conversion value). The dashboard page fetches ./data.json directly.

Shopify strategy: ShopifyQL (the sales/sessions datasets) is tried first,
but on the Basic plan third-party apps are denied `shopifyqlQuery` (it
requires Level 2 protected-customer-data access, which Basic doesn't offer).
When denied, daily sales metrics are DERIVED from the Orders API instead
(validated against ShopifyQL history), and the sessions funnel is left
blank — it has no API source on Basic; existing values in data.json are
preserved, and GA4 is the intended future source.

Merged output never overwrites an existing non-blank value with a blank,
so one source having an outage (or no API) doesn't erase history.

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
CAMPAIGNS_PATH = os.path.join(HERE, "campaigns.json")
CHANNELS_PATH = os.path.join(HERE, "channels.json")
SYDNEY = ZoneInfo("Australia/Sydney")
SHOPIFY_API_VERSION = "2025-07"
# ShipStation stores whose shipments are Premium Puzzles' own cost. The same
# account also ships funbox.fun (125784) and "Manual Orders" (120002, PP
# shipments with no matching Shopify revenue). Override with
# SHIPSTATION_STORE_IDS, e.g. "120003,120002" to fold manual orders back in.
SHIPSTATION_PP_STORES = "120003"

COLUMNS = [
    "Date", "Orders", "Gross sales", "Discounts", "Returns", "Net sales",
    "Total sales", "AOV", "Sessions", "Sessions with cart adds",
    "Sessions reached checkout", "Sessions completed checkout",
    "Conversion rate", "Email subscribes", "Email unsubscribes",
    "Net subscriber growth", "Meta spend", "Meta conv value", "Puzzles sold",
    "Subscriber list size", "Shipping charged", "Shipping cost",
    # Added once Google Ads went live again and GA4 became the funnel source.
    "Meta clicks", "Google spend", "Google conv value", "Google clicks",
    # Platform-reported conversion COUNTS, so paid CAC is a real division
    # rather than attributed-revenue / AOV.
    "Meta conversions", "Google conversions",
]

# Porter feed header -> data.json column(s). The feed carries Meta Ads, GA4
# and Google Ads on one date-keyed row (one Porter blend, all three
# connectors), and arrives in one of two dialects:
#   - the hand-written CSV's snake_case names, or
#   - Porter's own export labels ("Amount spent", "Cost", ...).
# Porter labels BOTH click columns "Clicks", so a value is a LIST and the
# nth occurrence of a header takes the nth entry. Column order in the export
# is Meta first, then Google — matching the blend's field order.
PORTER_MAP = {
    # our own CSV
    "meta_spend": ["Meta spend"],
    "meta_conv_value": ["Meta conv value"],
    "meta_clicks": ["Meta clicks"],
    "cart_adds": ["Sessions with cart adds"],
    "purchases": ["Sessions completed checkout"],
    "google_spend": ["Google spend"],
    "google_conv_value": ["Google conv value"],
    "google_clicks": ["Google clicks"],
    # Porter's display labels
    "amount spent": ["Meta spend"],
    "purchase conversion value": ["Meta conv value"],
    "clicks": ["Meta clicks", "Google clicks"],
    "add to carts": ["Sessions with cart adds"],
    "ecommerce purchases": ["Sessions completed checkout"],
    "cost": ["Google spend"],
    "conversions value": ["Google conv value"],
    # Porter's raw field ids
    "facebook_ads_spend": ["Meta spend"],
    "facebook_ads_value_omni_purchase": ["Meta conv value"],
    "facebook_ads_clicks": ["Meta clicks"],
    "facebook_ads_omni_purchase": ["Meta conversions"],
    "google_ads_conversions": ["Google conversions"],
    "meta_conversions": ["Meta conversions"],
    "google_conversions": ["Google conversions"],
    "google_analytics_4_sessions": ["Sessions"],
    "google_analytics_4_addtocarts": ["Sessions with cart adds"],
    "google_analytics_4_checkouts": ["Sessions reached checkout"],
    "google_analytics_4_ecommercepurchases": ["Sessions completed checkout"],
    "google_ads_cost_micros": ["Google spend"],
    "google_ads_conversions_value": ["Google conv value"],
    "google_ads_clicks": ["Google clicks"],
    # shared by every dialect
    "sessions": ["Sessions"],
    "checkouts": ["Sessions reached checkout"],
}


# Porter's Sheets export prefixes each label with the connector's display
# name: "Meta Ads Amount spent", "GA4 Sessions", "Google Ads Cost". The
# prefix is what disambiguates the two "Clicks" columns, so prefer it.
PORTER_PREFIXES = {
    "meta ads": "meta", "facebook ads": "meta", "meta": "meta",
    "google ads": "google",
    "ga4": "ga4", "google analytics 4": "ga4", "google analytics": "ga4",
}
PORTER_LABELS = {
    ("meta", "amount spent"): "Meta spend",
    ("meta", "spend"): "Meta spend",
    ("meta", "purchase conversion value"): "Meta conv value",
    ("meta", "clicks"): "Meta clicks",
    ("meta", "omni purchase"): "Meta conversions",
    ("meta", "purchases"): "Meta conversions",
    ("google", "cost"): "Google spend",
    ("google", "amount spent"): "Google spend",
    ("google", "conversions value"): "Google conv value",
    ("google", "conversions"): "Google conversions",
    ("google", "clicks"): "Google clicks",
    ("ga4", "sessions"): "Sessions",
    ("ga4", "add to carts"): "Sessions with cart adds",
    ("ga4", "checkouts"): "Sessions reached checkout",
    ("ga4", "ecommerce purchases"): "Sessions completed checkout",
}


def porter_target(header, seen):
    """Resolve one feed header to a data.json column, or None.

    Tries an exact alias first (our own CSV and Porter's raw field ids),
    then the "<connector> <label>" form. `seen` counts repeats so a dialect
    that labels both click columns plainly "Clicks" still splits Meta from
    Google by column order."""
    name = " ".join((header or "").strip().lower().split())
    if not name or name == "date":
        return None
    for key in (name, name.replace(" ", "_")):
        options = PORTER_MAP.get(key)
        if options:
            n = seen.get(key, 0)
            if n >= len(options):
                return None
            seen[key] = n + 1
            return options[n]
    for prefix in sorted(PORTER_PREFIXES, key=len, reverse=True):
        if name.startswith(prefix + " "):
            col = PORTER_LABELS.get((PORTER_PREFIXES[prefix],
                                     name[len(prefix) + 1:]))
            if col:
                return col
    return None


def parse_day(raw):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(raw[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return None


class ShopifyAccessDenied(Exception):
    pass


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


def sydney_day(iso_ts):
    ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return ts.astimezone(SYDNEY).date().isoformat()


# ---------------------------------------------------------------- Shopify

def shopify_token_from_client_credentials(store, client_id, client_secret):
    """Exchange client credentials for a 24h Admin token (Dev Dashboard apps).

    Requires the app to have its access scopes configured and to be installed
    on the store. Tokens expire after 24 hours, so every run exchanges anew.
    """
    resp = http_retry(lambda: requests.post(
        "https://%s/admin/oauth/access_token" % store,
        data={"client_id": client_id, "client_secret": client_secret,
              "grant_type": "client_credentials"},
        timeout=60))
    if resp.status_code != 200:
        die("Shopify client-credentials exchange failed (HTTP %s): %s\n"
            "Check the app's scopes are configured and it is installed on the store."
            % (resp.status_code, resp.text[:300]))
    body = resp.json()
    print("Shopify token via client credentials, scopes: %s" % body.get("scope", "?"))
    return body["access_token"]


def shopify_graphql(store, token, query, variables=None):
    url = "https://%s/admin/api/%s/graphql.json" % (store, SHOPIFY_API_VERSION)
    resp = http_retry(lambda: requests.post(
        url, json={"query": query, "variables": variables or {}},
        headers={"X-Shopify-Access-Token": token}, timeout=60))
    if resp.status_code != 200:
        die("Shopify HTTP %s: %s" % (resp.status_code, resp.text[:400]))
    data = resp.json()
    errors = data.get("errors")
    if errors:
        if all(e.get("extensions", {}).get("code") == "ACCESS_DENIED" for e in errors):
            raise ShopifyAccessDenied(errors[0].get("message", "access denied"))
        die("Shopify GraphQL errors: %s" % json.dumps(errors)[:600])
    return data["data"]


def shopifyql(store, token, ql):
    """Run a ShopifyQL query, return list of row dicts keyed by column name.

    On API version 2025-07 shopifyqlQuery returns { parseErrors,
    tableData { columns, rows } } directly (no TableResponse fragment);
    rows is a JSON scalar: a list of dicts keyed by column name, values
    as strings (or null). Raises ShopifyAccessDenied on plans/apps without
    Level 2 protected-customer-data access.
    """
    gql = ("query($q: String!) { shopifyqlQuery(query: $q) { parseErrors "
           "tableData { columns { name } rows } } }")
    node = shopify_graphql(store, token, gql, {"q": ql})["shopifyqlQuery"]
    if node.get("parseErrors"):
        die("ShopifyQL parse errors for [%s]: %s" % (ql, node["parseErrors"]))
    table = node.get("tableData") or {}
    return table.get("rows") or []


def fetch_shopifyql_sales(store, token, days):
    ql = ("FROM sales SHOW orders, gross_sales, discounts, returns, "
          "net_sales, total_sales, average_order_value, shipping_charges "
          "TIMESERIES day SINCE -%dd UNTIL today" % days)
    return {row["day"][:10]: row for row in shopifyql(store, token, ql)}


def fetch_shopifyql_sessions(store, token, days):
    ql = ("FROM sessions SHOW sessions, sessions_with_cart_additions, "
          "sessions_that_reached_checkout, sessions_that_completed_checkout "
          "TIMESERIES day SINCE -%dd UNTIL today" % days)
    return {row["day"][:10]: row for row in shopifyql(store, token, ql)}


ORDERS_GQL = (
    "query($q: String!, $cursor: String) { "
    "orders(first: 100, query: $q, after: $cursor) { "
    "pageInfo { hasNextPage endCursor } "
    "nodes { createdAt test taxesIncluded "
    "currentSubtotalLineItemsQuantity "
    "subtotalPriceSet { shopMoney { amount } } "
    "totalDiscountsSet { shopMoney { amount } } "
    "totalPriceSet { shopMoney { amount } } "
    "totalTaxSet { shopMoney { amount } } "
    "totalShippingPriceSet { shopMoney { amount } } "
    "refunds { createdAt totalRefundedSet { shopMoney { amount } } "
    "refundShippingLines(first: 10) { nodes { "
    "subtotalAmountSet { shopMoney { amount } } "
    "taxAmountSet { shopMoney { amount } } } } } } } }")


def _money(node, key):
    return float(((node.get(key) or {}).get("shopMoney") or {}).get("amount") or 0)


def fetch_orders(store, token, since):
    """One pass over the Orders API: units + derived daily sales metrics.

    Buckets by Sydney day. Every money column is GST-INCLUSIVE — Premium
    Puzzles is not registered for GST, so the tax it charges is revenue it
    keeps, and `total_sales` reconciles as net_sales + shipping_charges.
    (ShopifyQL reported these ex-GST; that is the one deliberate departure
    from its conventions.) Discounts and returns are negative.

    Orders (including cancelled ones) book their ORIGINAL amounts on the
    creation day; refunds land on the refund date, with refunded products
    going to returns and refunded shipping netting off shipping_charges.
    Shopify quotes refunded product subtotals GST-inclusive but refunded
    shipping subtotals ex-GST, hence the asymmetry below. Line-less custom
    refunds are booked in full to returns. The window reaches 90 days
    behind `since` so refunds against older orders land on their refund
    date.
    """
    q = "created_at:>=%s" % (since - timedelta(days=90)).isoformat()
    days = {}

    def bucket(day):
        return days.setdefault(day, {
            "orders": 0, "units": 0, "gross": 0.0, "discounts": 0.0,
            "returns": 0.0, "total": 0.0, "shipping": 0.0})

    cursor, n = None, 0
    while True:
        data = shopify_graphql(store, token, ORDERS_GQL, {"q": q, "cursor": cursor})
        conn = data["orders"]
        for node in conn["nodes"]:
            if node.get("test"):
                continue
            for refund in node.get("refunds") or []:
                # Returns follow the money actually refunded, split into its
                # shipping part and the rest. Line-item subtotals are not used:
                # a restock-without-refund posts $0 of lines-worth of goods and
                # would otherwise book revenue loss that never happened, and a
                # custom-amount refund has no lines at all.
                amount = _money(refund, "totalRefundedSet")
                if not amount:
                    continue
                ships = (refund.get("refundShippingLines") or {}).get("nodes") or []
                ship = min(sum(_money(sl, "subtotalAmountSet")
                               + _money(sl, "taxAmountSet") for sl in ships), amount)
                rb = bucket(sydney_day(refund["createdAt"]))
                rb["total"] -= amount
                rb["returns"] -= amount - ship
                rb["shipping"] -= ship
            n += 1
            b = bucket(sydney_day(node["createdAt"]))
            b["orders"] += 1
            b["units"] += node["currentSubtotalLineItemsQuantity"] or 0
            prod = _money(node, "subtotalPriceSet")
            disc = _money(node, "totalDiscountsSet")
            b["gross"] += prod + disc
            b["discounts"] -= disc
            b["shipping"] += _money(node, "totalShippingPriceSet")
            b["total"] += _money(node, "totalPriceSet")
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
    print("Orders API: %d orders scanned across %d days" % (n, len(days)))
    return days


def derived_sales_rows(order_days, since, today):
    """Shape Orders-API buckets like ShopifyQL sales rows for the merger."""
    out = {}
    day, one = since, timedelta(days=1)
    while day <= today:
        iso = day.isoformat()
        b = order_days.get(iso)
        if b:
            net = b["gross"] + b["discounts"] + b["returns"]
            out[iso] = {
                "orders": b["orders"],
                "gross_sales": round(b["gross"], 2),
                "discounts": round(b["discounts"], 2),
                "returns": round(b["returns"], 2),
                "net_sales": round(net, 2),
                "total_sales": round(b["total"], 2),
                "average_order_value": round(net / b["orders"], 3) if b["orders"] else None,
                "shipping_charges": round(b["shipping"], 2),
            }
        else:
            out[iso] = {"orders": 0, "gross_sales": 0, "discounts": 0,
                        "returns": 0, "net_sales": 0, "total_sales": 0,
                        "average_order_value": None, "shipping_charges": 0}
        day += one
    return out


# --------------------------------------------------------------- Omnisend

def fetch_omnisend(api_key, since, today):
    """Daily subscribedEmail/unsubscribedEmail via /api/analytics/statistics.

    The API takes {queries:[...]} with a required timestamp dimension; at day
    granularity a query spans at most 60 days and must not cross a calendar
    year, so the window is chunked. `to` is exclusive. Chunks are 59 days,
    not 60: an AEDT→AEST transition inside a chunk adds an hour to the
    absolute span, which the API rejects as "greater than 60 days".
    """
    out = {}
    start, end = since, today + timedelta(days=1)
    while start < end:
        year_end = date(start.year + 1, 1, 1)
        stop = min(start + timedelta(days=59), end, year_end)
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
            "https://api.omnisend.com/api/analytics/statistics",
            json=body,
            headers={"X-API-KEY": api_key, "Omnisend-Version": "2026-03-15"},
            timeout=60))
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


def omnisend_get(api_key, path):
    resp = http_retry(lambda: requests.get(
        "https://api.omnisend.com" + path,
        headers={"X-API-KEY": api_key, "Omnisend-Version": "2026-03-15"},
        timeout=60))
    if resp.status_code != 200:
        die("Omnisend HTTP %s on %s: %s" % (resp.status_code, path, resp.text[:400]))
    return resp.json()


# The condition shape that means "every contact subscribed on email" — the
# same population Omnisend's Contacts page calls "Email subscribers".
def _is_email_subscribers_segment(seg):
    groups = seg.get("conditionGroups") or []
    if len(groups) != 1:
        return False
    conditions = groups[0].get("conditions") or []
    if len(conditions) != 1:
        return False
    filters = conditions[0].get("filters") or []
    if conditions[0].get("entity") != "contact" or len(filters) != 1:
        return False
    f = filters[0]
    return (f.get("property") == "subscriptionStatus"
            and f.get("operator") == "equals"
            and f.get("value") == "subscribed"
            and "email" in (f.get("channels") or []))


def fetch_omnisend_list_size(api_key, segment_id=""):
    """Current mailable list size, via a segment's contactsCount.

    Omnisend's analytics API only exposes subscribe/unsubscribe EVENTS, so
    there is no metric for the standing list size. A segment whose only rule
    is subscriptionStatus == subscribed on email gives exactly the number the
    Contacts page shows as "Email subscribers" (NOT "Total contacts", which
    counts unsubscribed and non-email contacts too — 7,982 vs 8,296 on
    2026-08-09).

    Set OMNISEND_SEGMENT_ID to skip discovery and spend one request per run
    instead of two; the daily cap is 55. Returns None rather than dying if
    the segment is gone, so merge_previous keeps the last known value.
    """
    if not segment_id:
        segments = omnisend_get(api_key, "/api/segments?limit=50").get("segments") or []
        matches = [s for s in segments if _is_email_subscribers_segment(s)]
        if not matches:
            print("Omnisend: no 'subscribed on email' segment found — list size "
                  "left blank. Create one, or set OMNISEND_SEGMENT_ID.")
            return None
        segment_id = matches[0]["segmentID"]
        print("Omnisend: list-size segment '%s' (%s). Set OMNISEND_SEGMENT_ID=%s "
              "to skip this lookup." % (matches[0].get("name"), segment_id, segment_id))
        time.sleep(1)
    body = omnisend_get(api_key, "/api/segments/%s/statistics" % segment_id)
    count = body.get("contactsCount")
    return int(count) if count is not None else None


# ------------------------------------------------------------- ShipStation

def fetch_shipstation(api_key, api_secret, since, today, store_ids):
    """Sum shipmentCost + insuranceCost per shipDate, skipping voided.

    The account also ships for other stores (funbox.fun, Manual Orders),
    which would inflate the shipping bleed against Premium Puzzles' own
    revenue, so shipments are filtered to `store_ids`. What is excluded is
    reported rather than silently dropped.
    """
    out, page, skipped = {}, 1, {}
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
            store = str((sh.get("advancedOptions") or {}).get("storeId") or "")
            if store_ids and store not in store_ids:
                a = skipped.setdefault(store, [0, 0.0])
                a[0] += 1
                a[1] += cost
                continue
            out[day] = round(out.get(day, 0) + cost, 2)
        if page >= int(body.get("pages") or 1):
            break
        page += 1
        time.sleep(1)
    for store, (n, cost) in sorted(skipped.items()):
        print("  ShipStation: excluded store %s — %d shipments, $%.2f"
              % (store or "?", n, cost))
    return out


# ----------------------------------------------------------- Porter feed

def fetch_porter(src):
    """Porter blend export (URL or local path): Meta Ads + GA4 + Google Ads.

    Expected header: date plus any of PORTER_MAP's keys. Returns
    {day: {data.json column: value}} for whichever columns are present, so
    a feed missing a source simply leaves those columns to the merge.

    Porter's free tier only stores a rolling ~30 days; data.json is the
    long-term store, which is why merge_previous never blanks a value.
    """
    if src.startswith("http://") or src.startswith("https://"):
        resp = http_retry(lambda: requests.get(src, timeout=60))
        if resp.status_code != 200:
            die("PORTER_CSV HTTP %s: %s" % (resp.status_code, resp.text[:200]))
        text = resp.text
    else:
        if not os.path.isabs(src):
            src = os.path.join(HERE, src)
        if not os.path.exists(src):
            print("Porter: %s not found, leaving its columns blank" % src)
            return {}
        with open(src, encoding="utf-8-sig") as f:
            text = f.read()
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        print("Porter: feed is empty")
        return {}

    # Resolve each column position once, so duplicate headers stay distinct.
    date_at, targets, seen = None, {}, {}
    for i, raw in enumerate(header):
        if (raw or "").strip().lower() == "date" and date_at is None:
            date_at = i
            continue
        col = porter_target(raw, seen)
        if col:
            targets[i] = col
    if date_at is None:
        die("Porter feed has no 'date' column — headers were: %s" % header[:12])
    missing = sorted(set(sum(PORTER_MAP.values(), [])) - set(targets.values()))
    print("Porter: mapped %d columns%s"
          % (len(targets), (", missing " + ", ".join(missing)) if missing else ""))
    if missing:
        # Names only, never the URL — this is the difference between "the feed
        # is stale" and "the feed is fine", which is otherwise invisible
        # because merge_previous keeps the last good values on screen. Only
        # genuinely unrecognised headers, or the line misleads.
        unmapped = [h for i, h in enumerate(header)
                    if h and i != date_at and i not in targets]
        if unmapped:
            print("Porter: unrecognised headers %s" % unmapped[:16])

    out, dropped = {}, []
    for row in reader:
        if len(row) <= date_at:
            continue
        day = parse_day((row[date_at] or "").strip())
        if not day:
            continue
        vals = {col: to_num(row[i].strip())
                for i, col in targets.items() if i < len(row)}
        # An ALL-ZERO row is a broken read, not a real day: a live store never
        # records zero sessions, and a genuine pause shows up as one zero metric
        # beside non-zero others. Dropping it lets merge_previous keep the last
        # good values. Zeros — unlike blanks — otherwise overwrite, and on
        # 2026-07-30 that silently wiped a fortnight of ad and funnel data.
        if vals and not any(v not in ("", 0) for v in vals.values()):
            dropped.append(day)
            continue
        out[day] = vals
    if dropped:
        print("Porter: IGNORED %d all-zero row(s) (%s%s) — keeping prior values"
              % (len(dropped), ", ".join(dropped[:5]),
                 ", ..." if len(dropped) > 5 else ""))
    return out


CAMPAIGN_COLUMNS = ["Date", "Platform", "Campaign", "Spend", "Value",
                    "Clicks", "Impressions", "Conversions"]

# Porter's campaign export is WIDE: one row per day carrying both platforms'
# columns, with only one platform's campaign name filled in per row (adding
# both campaign dimensions gives sparse rows, not a cross product). Each
# header resolves to (platform, field) and rows are pivoted to the narrow
# CAMPAIGN_COLUMNS shape. The hand-written narrow CSV is still accepted.
CAMPAIGN_LABELS = {
    ("meta", "campaign"): ("Meta", "Campaign"),
    ("meta", "campaign name"): ("Meta", "Campaign"),
    ("meta", "amount spent"): ("Meta", "Spend"),
    ("meta", "purchase conversion value"): ("Meta", "Value"),
    ("meta", "omni purchase"): ("Meta", "Conversions"),
    ("meta", "purchases"): ("Meta", "Conversions"),
    ("meta", "clicks"): ("Meta", "Clicks"),
    ("meta", "impressions"): ("Meta", "Impressions"),
    ("google", "campaign"): ("Google", "Campaign"),
    ("google", "campaign name"): ("Google", "Campaign"),
    ("google", "cost"): ("Google", "Spend"),
    ("google", "conversions value"): ("Google", "Value"),
    ("google", "conversions"): ("Google", "Conversions"),
    ("google", "clicks"): ("Google", "Clicks"),
    ("google", "impressions"): ("Google", "Impressions"),
}


def campaign_target(header):
    """Resolve a wide-format header to (platform, field), or None."""
    name = " ".join((header or "").strip().lower().split())
    for prefix in sorted(PORTER_PREFIXES, key=len, reverse=True):
        if name.startswith(prefix + " "):
            platform = PORTER_PREFIXES[prefix]
            if platform == "ga4":
                return None
            return CAMPAIGN_LABELS.get((platform, name[len(prefix) + 1:]))
    return None


def fetch_campaigns(src):
    """Per-campaign ad rows: date,platform,campaign,spend,value,clicks,...

    One normalised table across platforms, so the page can rank campaigns
    against each other rather than only showing platform totals. Same
    URL-or-path handling as the Porter feed.
    """
    if src.startswith("http://") or src.startswith("https://"):
        resp = http_retry(lambda: requests.get(src, timeout=60))
        if resp.status_code != 200:
            die("CAMPAIGNS_CSV HTTP %s: %s" % (resp.status_code, resp.text[:200]))
        text = resp.text
    else:
        if not os.path.isabs(src):
            src = os.path.join(HERE, src)
        if not os.path.exists(src):
            print("Campaigns: %s not found, skipping" % src)
            return []
        with open(src, encoding="utf-8-sig") as f:
            text = f.read()
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        print("Campaigns: feed is empty")
        return []

    lower = [" ".join((h or "").strip().lower().split()) for h in header]
    date_at = lower.index("date") if "date" in lower else None
    if date_at is None:
        die("Campaigns feed has no 'date' column — headers were: %s" % header[:14])

    rows = []
    if "platform" in lower and "campaign" in lower:
        # Narrow, hand-written shape.
        idx = {n: i for i, n in enumerate(lower)}
        get = lambda r, n: r[idx[n]].strip() if n in idx and idx[n] < len(r) else ""
        for row in reader:
            day = parse_day(get(row, "date"))
            if not day or not get(row, "campaign"):
                continue
            rows.append({
                "Date": day, "Platform": get(row, "platform"),
                "Campaign": get(row, "campaign"),
                "Spend": to_num(get(row, "spend")), "Value": to_num(get(row, "value")),
                "Clicks": to_num(get(row, "clicks")),
                "Impressions": to_num(get(row, "impressions")),
                "Conversions": to_num(get(row, "conversions")),
            })
    else:
        # Wide Porter shape: pivot each row into one record per platform that
        # actually names a campaign on that row.
        targets = {}
        for i, h in enumerate(header):
            if i == date_at:
                continue
            t = campaign_target(h)
            if t:
                targets[i] = t
        platforms = sorted({p for p, _ in targets.values()})
        if not platforms:
            print("Campaigns: no recognised columns, headers were %s" % header[:14])
            return []
        print("Campaigns: wide feed, %d columns across %s"
              % (len(targets), ", ".join(platforms)))
        for row in reader:
            if len(row) <= date_at:
                continue
            day = parse_day((row[date_at] or "").strip())
            if not day:
                continue
            acc = {p: {} for p in platforms}
            for i, (platform, field) in targets.items():
                if i < len(row):
                    acc[platform][field] = (row[i] or "").strip()
            for platform, vals in acc.items():
                name = vals.get("Campaign", "")
                if not name:
                    continue
                rows.append({
                    "Date": day, "Platform": platform, "Campaign": name,
                    "Spend": to_num(vals.get("Spend")),
                    "Value": to_num(vals.get("Value")),
                    "Clicks": to_num(vals.get("Clicks")),
                    "Impressions": to_num(vals.get("Impressions")),
                    "Conversions": to_num(vals.get("Conversions")),
                })
    rows.sort(key=lambda r: (r["Date"], r["Platform"], r["Campaign"]))
    return rows


def write_campaigns(rows):
    """Write campaigns.json, keeping any older days already published.

    Same reasoning as merge_previous: Porter only retains ~30 days, so the
    committed file is the long-term store."""
    if not rows:
        return
    seen = {(r["Date"], r["Platform"], r["Campaign"]) for r in rows}
    if os.path.exists(CAMPAIGNS_PATH):
        try:
            with open(CAMPAIGNS_PATH, encoding="utf-8") as f:
                for old in json.load(f):
                    key = (old.get("Date"), old.get("Platform"), old.get("Campaign"))
                    if key not in seen and all(key):
                        rows.append({k: old.get(k, "") for k in CAMPAIGN_COLUMNS})
        except (ValueError, KeyError, TypeError):
            pass
    rows.sort(key=lambda r: (r["Date"], r["Platform"], r["Campaign"]))
    with open(CAMPAIGNS_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rows, f, indent=1)
        f.write("\n")
    names = sorted({r["Campaign"] for r in rows})
    print("Campaigns: %d rows across %d campaigns -> %s"
          % (len(rows), len(names), CAMPAIGNS_PATH))


CHANNEL_COLUMNS = ["Date", "Channel", "Sessions", "Purchases", "Revenue"]


def fetch_channels(src):
    """GA4 sessions/purchases/revenue per default channel group per day.

    This is what tells you email is the biggest channel rather than a rounding
    error — the donut it feeds was previously hardcoded and said the opposite.
    """
    if src.startswith("http://") or src.startswith("https://"):
        resp = http_retry(lambda: requests.get(src, timeout=60))
        if resp.status_code != 200:
            die("CHANNELS_CSV HTTP %s: %s" % (resp.status_code, resp.text[:200]))
        text = resp.text
    else:
        if not os.path.isabs(src):
            src = os.path.join(HERE, src)
        if not os.path.exists(src):
            print("Channels: %s not found, skipping" % src)
            return []
        with open(src, encoding="utf-8-sig") as f:
            text = f.read()

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return []
    lower = [" ".join((h or "").strip().lower().split()) for h in header]

    def find(*names):
        for n in names:
            for i, h in enumerate(lower):
                if h == n or h.endswith(" " + n):
                    return i
        return None

    at = {
        "Date": find("date"),
        "Channel": find("session default channel group", "default channel group",
                        "channel"),
        "Sessions": find("sessions"),
        "Purchases": find("ecommerce purchases", "purchases"),
        "Revenue": find("purchase revenue", "revenue"),
    }
    if at["Date"] is None or at["Channel"] is None:
        print("Channels: unrecognised headers %s" % header[:8])
        return []

    rows = []
    for row in reader:
        if len(row) <= max(i for i in at.values() if i is not None):
            continue
        day = parse_day((row[at["Date"]] or "").strip())
        name = (row[at["Channel"]] or "").strip()
        if not day or not name:
            continue
        # Same all-zero guard as the Porter feed: a channel with no sessions,
        # no purchases and no revenue carries no information.
        if not any(to_num(row[at[f]]) not in ("", 0)
                   for f in ("Sessions", "Purchases", "Revenue")
                   if at[f] is not None):
            continue
        rows.append({
            "Date": day, "Channel": name,
            "Sessions": to_num(row[at["Sessions"]]) if at["Sessions"] is not None else "",
            "Purchases": to_num(row[at["Purchases"]]) if at["Purchases"] is not None else "",
            "Revenue": to_num(row[at["Revenue"]]) if at["Revenue"] is not None else "",
        })
    rows.sort(key=lambda r: (r["Date"], r["Channel"]))
    return rows


def write_rows(path, rows, key_fields, columns, label):
    """Write a feed file, keeping any older rows already published.

    Porter only retains ~30 days, so the committed file is the long-term
    store — same reasoning as merge_previous."""
    if not rows:
        return
    seen = {tuple(r[k] for k in key_fields) for r in rows}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                for old in json.load(f):
                    k = tuple(old.get(f) for f in key_fields)
                    if k not in seen and all(k):
                        rows.append({c: old.get(c, "") for c in columns})
        except (ValueError, KeyError, TypeError):
            pass
    rows.sort(key=lambda r: tuple(str(r[k]) for k in key_fields))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rows, f, indent=1)
        f.write("\n")
    print("%s: %d rows -> %s" % (label, len(rows), os.path.basename(path)))


# ------------------------------------------------------------------- main

def merge_previous(rows):
    """Blank-preserving merge with the existing data.json.

    Any "" in a new row is filled from the previous file's value for that
    day; days present before but outside the new window are kept as-is.
    This is what preserves the sessions funnel history (no API source on
    the Basic plan) and rides out single-source outages.
    """
    if not os.path.exists(OUT_PATH):
        return rows
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            old = {r["Date"]: r for r in json.load(f)}
    except (ValueError, KeyError):
        return rows
    filled = 0
    by_date = {}
    for row in rows:
        prev = old.get(row["Date"])
        if prev:
            for col in COLUMNS:
                if row[col] == "" and prev.get(col, "") != "":
                    row[col] = prev[col]
                    filled += 1
        by_date[row["Date"]] = row
    kept = [r for d, r in old.items() if d not in by_date]
    if filled or kept:
        print("Merged previous data.json: %d blanks filled, %d older days kept"
              % (filled, len(kept)))
    merged = kept + rows
    merged.sort(key=lambda r: r["Date"])
    return merged


def main():
    load_dotenv()
    store = os.environ.get("SHOPIFY_STORE", "").strip()
    token = os.environ.get("SHOPIFY_TOKEN", "").strip()
    client_id = os.environ.get("SHOPIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()
    if not store or not (token or (client_id and client_secret)):
        die("SHOPIFY_STORE plus either SHOPIFY_TOKEN or SHOPIFY_CLIENT_ID + "
            "SHOPIFY_CLIENT_SECRET are required (dashboard/.env or env)")
    if "." not in store:
        store += ".myshopify.com"
    if not token:
        token = shopify_token_from_client_credentials(store, client_id, client_secret)
    days = int(os.environ.get("DAYS") or 120)
    today = datetime.now(SYDNEY).date()
    since = today - timedelta(days=days)

    print("Collecting %d days (%s to %s) for %s" % (days, since, today, store))

    sales = sessions = None
    try:
        sales = fetch_shopifyql_sales(store, token, days)
        sessions = fetch_shopifyql_sessions(store, token, days)
        print("Shopify: ShopifyQL OK (%d sales days)" % len(sales))
    except ShopifyAccessDenied as exc:
        print("ShopifyQL denied (%s...). Deriving sales from the Orders API; "
              "sessions funnel has no source on this plan." % str(exc)[:80])

    order_days = fetch_orders(store, token, since)
    units = {d: b["units"] for d, b in order_days.items()}
    if sales is None:
        sales = derived_sales_rows(order_days, since, today)
    if sessions is None:
        sessions = {}

    # Omnisend allows only 55 requests/DAY. One <=59-day chunk is one request,
    # so a short window keeps hourly runs (24/day) well inside the cap while
    # merge_previous holds the older history. Widen it for a one-off backfill.
    omni_key = os.environ.get("OMNISEND_API_KEY", "").strip()
    omni_days = int(os.environ.get("OMNISEND_DAYS") or 45)
    omni_since = max(since, today - timedelta(days=omni_days))
    omni = fetch_omnisend(omni_key, omni_since, today) if omni_key else {}
    print("Omnisend: %d days" % len(omni) if omni_key
          else "Omnisend: no OMNISEND_API_KEY, leaving email columns blank")

    # A point-in-time reading, so it is stamped on today's row only. Older
    # days keep whatever was recorded when they were today, which is what
    # turns this column into a real list-size history over time.
    list_size = (fetch_omnisend_list_size(
        omni_key, os.environ.get("OMNISEND_SEGMENT_ID", "").strip())
        if omni_key else None)
    if list_size is not None:
        print("Omnisend: list size %d (email subscribers) as at %s"
              % (list_size, today))

    ss_key = os.environ.get("SHIPSTATION_API_KEY", "").strip()
    ss_secret = os.environ.get("SHIPSTATION_API_SECRET", "").strip()
    store_ids = {s.strip() for s in os.environ.get(
        "SHIPSTATION_STORE_IDS", SHIPSTATION_PP_STORES).split(",") if s.strip()}
    ship_ran = bool(ss_key and ss_secret)
    ship = (fetch_shipstation(ss_key, ss_secret, since, today, store_ids)
            if ship_ran else {})
    print("ShipStation: %d ship days" % len(ship) if ss_key and ss_secret
          else "ShipStation: no keys, leaving Shipping cost blank")

    porter_src = (os.environ.get("PORTER_CSV", "").strip()
                  or os.environ.get("META_CSV", "").strip()
                  or "porter_feed.csv")
    porter = fetch_porter(porter_src)
    print("Porter feed: %d days from %s" % (len(porter), porter_src))

    write_campaigns(fetch_campaigns(
        os.environ.get("CAMPAIGNS_CSV", "").strip() or "campaigns.csv"))
    write_rows(CHANNELS_PATH,
               fetch_channels(os.environ.get("CHANNELS_CSV", "").strip()
                              or "channels.csv"),
               ("Date", "Channel"), CHANNEL_COLUMNS, "Channels")

    rows = []
    for day in sorted(sales):
        s = sales[day]
        sess = sessions.get(day, {})
        n_sessions = int(sess.get("sessions") or 0)
        completed = int(sess.get("sessions_that_completed_checkout") or 0)
        subs, unsubs = omni.get(day, ("", ""))
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
            "Meta spend": "",
            "Meta conv value": "",
            "Puzzles sold": units.get(day, 0),
            "Subscriber list size": (list_size if list_size is not None
                                     and day == today.isoformat() else ""),
            "Shipping charged": to_num(s.get("shipping_charges")),
            # A day ShipStation covered with no Premium Puzzles shipment cost
            # $0, not "unknown" — writing 0 rather than a blank also stops
            # merge_previous resurrecting a superseded figure.
            "Shipping cost": ship.get(day, 0 if ship_ran else ""),
            "Meta clicks": "",
            "Google spend": "",
            "Google conv value": "",
            "Google clicks": "",
            "Meta conversions": "",
            "Google conversions": "",
        }
        # Porter owns the ad columns, and the funnel wherever it reaches:
        # GA4 is the only funnel source now that ShopifyQL sessions are
        # plan-gated, so its values take precedence over older Shopify ones.
        for col, value in porter.get(day, {}).items():
            if value != "":
                row[col] = value
        n_sessions = int(row["Sessions"] or 0)
        completed = int(row["Sessions completed checkout"] or 0)
        row["Conversion rate"] = round(completed / n_sessions, 4) if n_sessions else ""
        rows.append({k: row[k] for k in COLUMNS})

    rows = merge_previous(rows)

    with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rows, f, indent=1)
        f.write("\n")
    print("Wrote %d rows (%s to %s) to %s"
          % (len(rows), rows[0]["Date"], rows[-1]["Date"], OUT_PATH))


if __name__ == "__main__":
    main()
