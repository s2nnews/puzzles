# Data sources — where every column comes from

_The Cockpit Daily sheet is one date-keyed row per day. Columns A–P are the
original set; Q–V were appended for the marketing dashboard. Keep this order —
the published CSV and `index.html` both rely on the header names._

## Column map (Daily tab)
| Col | Header | Source |
|----|--------|--------|
| A (0) | Date | key |
| B (1) | Orders | Shopify (ShopifyQL `sales`) |
| C (2) | Gross sales | Shopify |
| D (3) | Discounts | Shopify |
| E (4) | Returns | Shopify |
| F (5) | Net sales | Shopify |
| G (6) | Total sales | Shopify |
| H (7) | AOV | Shopify |
| I (8) | Sessions | Shopify (ShopifyQL `sessions`) |
| J (9) | Sessions with cart adds | Shopify |
| K (10) | Sessions reached checkout | Shopify |
| L (11) | Sessions completed checkout | Shopify |
| M (12) | Conversion rate | Shopify (derived) |
| N (13) | Email subscribes | Omnisend |
| O (14) | Email unsubscribes | Omnisend |
| P (15) | Net subscriber growth | Omnisend (derived) |
| Q (16) | **Meta spend** | **Meta via Porter** (free, 30-day rolling) |
| R (17) | **Meta conv value** | **Meta via Porter** |
| S (18) | **Puzzles sold** (units) | Shopify Orders GraphQL (`currentSubtotalLineItemsQuantity`) — needs `read_orders` scope |
| T (19) | Subscriber list size | Omnisend (segment member count; today's row only) |
| U (20) | Shipping charged | Shopify (`shipping_charges`) |
| V (21) | **Shipping cost** | **ShipStation** v1 REST (`shipmentCost` + `insuranceCost` by shipDate) |

## Meta = Porter only
We use **Porter for exactly one thing: Meta (Facebook) ads**, on the **free**
tier, which retains a **rolling 30 days**. That 30-day limit is *why* the sheet
exists: once a day's Meta spend is written into the sheet it's kept permanently,
so history never rolls off. Do **not** add other Porter connectors or a paid
Porter plan — Meta rolling-30 is the whole use.

- Porter account: Premium Puzzles Australia; Meta ad account `act_1349938757036613`.
- Pull via the Porter connection (fields prefixed `facebook_ads_*`, e.g.
  `facebook_ads_spend`, `facebook_ads_value_omni_purchase`).

## Google = native, not Porter
There is **no Google Ads account in Porter** and we don't want one. Google Ads
retains full history natively, connected directly (Looker's Google Ads
connector, or a Google-native Sheets connection). In the current HTML dashboard,
Google Ads spend / ROAS are carried as "latest known" CONFIG constants
(`CONFIG.googleSpend`, `CONFIG.googleRev`) rather than per-day sheet columns.
Session/funnel data is Shopify's session report (not GA4) as currently built.

## "Latest known" values in index.html (not yet per-day in the sheet)
These live in the `CONFIG` block of `index.html` and update less often. Move
them into their own daily columns later if you want them range-aware:
- Google Ads spend / revenue / clicks
- Gross-margin % (36.9%, measured on the ~54% of sales with cost loaded)
- 12-month LTV, repeat-customer rate
- Email campaign table, revenue-by-channel, traffic-by-source donut
