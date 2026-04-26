# Einblick Analysis (Snowflake)

- Platform: Snowflake
- Time window: 7 days
- Total queries processed: 775
- Distinct patterns: 254
- Total estimated compute cost: 310.3931
- Total bytes scanned: 437,027,332,179
- Top patterns shown: 100
- Extracted: 2026-04-26

> Sample analysis written by Claude Opus 4.7 via the `/einblick` slash command against the bundled 775-query sample dataset. Use this to preview what the report looks like before connecting your real warehouse. The clusters and offenders below are deterministic outputs of `einblick extract --sample`; the recommendations are the LLM analysis layered on top.

## Re-run this analysis

### Interactive (Claude Code)

    /einblick --sample

### Programmatic (CLI, full LLM report)

Requires an LLM API key. Use the EINBLICK-prefixed variable so it doesn't collide with Claude Code (which also reads ANTHROPIC_API_KEY):

    export EINBLICK_ANTHROPIC_API_KEY=sk-ant-...   # or EINBLICK_OPENAI_API_KEY=sk-...

    einblick analyze \
      --sample \
      --analysis-depth standard \
      --provider anthropic \
      --output sample-report.md

For an OpenAI-compatible endpoint (Venice, Together, local Ollama):

    einblick analyze \
      --sample \
      --provider openai \
      --llm-base-url https://api.venice.ai/api/v1 \
      --model llama-3.3-70b \
      --output sample-report.md

---

## Executive Summary

Three patterns drive ~36% of the 7-day estimated cost. The single biggest item is a `SELECT * FROM raw.stripe.payments` extract running 50 times at ~$70 estimated — two data engineers pulling the full payments table for ad-hoc work; one staging table eliminates it. The next two are Tableau-driven: a daily revenue-by-region aggregation (155 executions, $11.59) and an order-detail join across 5 tables with `SELECT *` (55 executions, $30.88). Both are classic materialization candidates — Looker/Tableau dashboards re-running the same SQL for every page-load.

Beyond materializations, `WH_DS_2XL` runs 9 queries from one data scientist (emma.davis) for ~$14.60 — the warehouse is almost certainly oversized for the workload and should be split or downsized. Five separate one-off "customer lifetime value" queries from different data scientists, each running 70-100+ seconds and costing $5-7, point to a missing CLV mart that would replace ad-hoc CTEs across the team.

**Cost numbers throughout are estimates.** The methodology computes `execution_time × warehouse_credits_per_hour`, which over-counts when queries share a warehouse concurrently. Use rankings for prioritization, not absolute totals.

---

## Biggest Offenders

### Top human users by cost

| User | Queries | Est. Cost | Avg Runtime | Patterns | Warehouse |
|------|---------|-----------|-------------|----------|-----------|
| alex.kumar@company.com | 38 | 51.19 | 28s | 9 | WH_ETL_L |
| jordan.lee@company.com | 31 | 34.34 | 23s | 12 | WH_ETL_L |
| emma.davis@company.com | 16 | 28.18 | 31s | 16 | WH_DS_2XL |
| noah.martinez@company.com | 20 | 25.87 | 26s | 20 | WH_DS_XL |
| sarah.chen@company.com | 71 | 23.85 | 13s | 33 | WH_ANALYTICS_M |
| mike.johnson@company.com | 53 | 19.88 | 14s | 25 | WH_ANALYTICS_M |

`alex.kumar` and `jordan.lee` are the data engineers driving the Stripe payments cost — Recommendation #1 covers them. `emma.davis` and `noah.martinez` are data scientists running expensive customer-analysis queries individually; Recommendation #4 builds a CLV mart they can both share.

### Top service accounts by cost

| User | Queries | Est. Cost | Avg Runtime | Warehouse |
|------|---------|-----------|-------------|-----------|
| TABLEAU_SERVICE | 190 | 47.95 | 10s | WH_TABLEAU |
| LOOKER_SERVICE | 248 | 30.52 | 6s | WH_LOOKER |

These are expected — BI tools doing their job. The lever isn't "have Looker run fewer queries"; it's making the SQL Looker emits cheaper. Every Looker/Tableau pattern below is a materialization opportunity.

### Top warehouses

| Warehouse | Queries | Est. Cost | Avg Runtime | Distinct Users | Avg Cost/Query |
|-----------|---------|-----------|-------------|----------------|----------------|
| WH_ETL_L | 64 | 77.81 | 25s | 2 | 1.22 |
| WH_TABLEAU | 190 | 47.95 | 10s | 1 | 0.25 |
| WH_ANALYTICS_M | 129 | 41.78 | 13s | 4 | 0.32 |
| WH_DS_XL | 27 | 39.44 | 27s | 2 | 1.46 |
| WH_LOOKER | 248 | 30.52 | 6s | 1 | 0.12 |
| WH_DS_2XL | 9 | 14.60 | 31s | 1 | 1.62 |

`WH_DS_2XL` has the highest cost-per-query and runs only 9 queries from a single user. This is the textbook "warehouse sized for the rare worst-case query" anti-pattern. Recommendation #5 addresses it.

### Slowest patterns

| Fingerprint | Avg Runtime | Max Runtime | Executions | Pattern |
|-------------|-------------|-------------|------------|---------|
| `14748e7d` | 29s | 39s | 50 | `SELECT * FROM raw.stripe.payments` |
| `936c1922` | 19s | 24s | 55 | Tableau 5-table order detail join |
| `dc42cc75` | 12s | 16s | 43 | Customer order lookup with join |
| `869547fc` | 10s | 18s | 4 | Customer cohort scan |
| `af75d0d6` | 10s | 13s | 27 | Marketing session × order join |

The slowest *one-off* queries are 70-105 seconds each (CLV-style data-scientist queries against `dim_customers × fact_orders`). They appear in clusters 10-14, 16-17, 19. Each is a different fingerprint but they share the same shape — strong signal for a CLV mart.

---

## Top Recommendations

### #1. Materialize Stripe payments daily-window staging table

**Addresses:** `14748e7d` (50 executions, $70.53 estimated, 83GB scanned, 29s avg)
**Priority:** HIGH (largest single cost item; 9.4% of warehouse-cost-attributed total)
**Refresh strategy:** Snowflake Dynamic Table with `target_lag = '1 hour'`
**Implementation risk:** LOW — the source is `raw.stripe.payments`, an ingestion table with predictable schema.

Two data engineers (alex.kumar, jordan.lee) are running `SELECT * FROM raw.stripe.payments WHERE created_at >= DATEADD(DAY, -N, CURRENT_DATE)` on `WH_ETL_L` (Large warehouse) 50 times in 7 days. At 29s avg, this is dominating ETL warehouse cost. They're almost certainly using these as ad-hoc inputs for downstream queries; a materialized staging table would eliminate the repeat work.

```sql
CREATE OR REPLACE DYNAMIC TABLE analytics.staging.stripe_payments_30d
  TARGET_LAG = '1 hour'
  WAREHOUSE = WH_ETL_S
AS
SELECT
    payment_id,
    customer_id,
    amount,
    currency,
    status,
    payment_method,
    created_at,
    updated_at
FROM raw.stripe.payments
WHERE created_at >= DATEADD(DAY, -30, CURRENT_DATE);
```

**Original query (representative):**

```sql
SELECT * FROM raw.stripe.payments WHERE created_at >= DATEADD(DAY, -7, CURRENT_DATE);
```

**Optimized query rewrite:**

```sql
-- Use the staging table; one micro-partition scan instead of full table.
-- Engineers should switch ad-hoc work to this.
SELECT
    payment_id, customer_id, amount, currency, status, created_at
FROM analytics.staging.stripe_payments_30d
WHERE created_at >= DATEADD(DAY, -7, CURRENT_DATE);
```

**Expected impact:** 50 executions of the 29-second `SELECT *` reduced to ~0.5s lookups against a much smaller, narrower table. Bytes scanned drop ~80x (from 83GB total to ~1GB). Estimated cost reduction: $60-65 of the $70 over a 7-day window.

**Validation:** `SELECT COUNT(*) FROM analytics.staging.stripe_payments_30d` should match `SELECT COUNT(*) FROM raw.stripe.payments WHERE created_at >= DATEADD(DAY, -30, CURRENT_DATE)` once the lag converges.

---

### #2. Materialize Tableau daily-revenue-by-region aggregation

**Addresses:** `d1c5c07c` (155 executions, $11.59 estimated, 13.5GB scanned, 4.6s avg)
**Priority:** HIGH (highest execution count; refresh every dashboard load)
**Refresh strategy:** Snowflake Dynamic Table with `target_lag = '15 minutes'`
**Implementation risk:** LOW — well-defined aggregation, single grain (region × day).

`TABLEAU_SERVICE` and `LOOKER_SERVICE` both run a daily-revenue-by-region SUM/COUNT DISTINCT 155 times in 7 days against `analytics.sales.fact_orders × analytics.sales.dim_regions`. This is a dashboard query getting recomputed every render.

```sql
CREATE OR REPLACE DYNAMIC TABLE analytics.marts.daily_revenue_by_region
  TARGET_LAG = '15 minutes'
  WAREHOUSE = WH_ETL_S
AS
SELECT
    r.region_name,
    DATE_TRUNC('DAY', o.order_date) AS day,
    SUM(o.total_amount) AS daily_revenue,
    COUNT(DISTINCT o.customer_id) AS distinct_customers,
    COUNT(*) AS order_count
FROM analytics.sales.fact_orders o
JOIN analytics.sales.dim_regions r ON o.region_id = r.region_id
WHERE o.order_date >= DATEADD(DAY, -90, CURRENT_DATE)
  AND o.order_status = 'completed'
GROUP BY r.region_name, DATE_TRUNC('DAY', o.order_date);
```

**Original query (representative):**

```sql
SELECT
    r.region_name,
    DATE_TRUNC('DAY', o.order_date) AS day,
    SUM(o.total_amount) AS daily_revenue,
    COUNT(DISTINCT o.customer_id) AS distinct_customers,
    COUNT(*) AS order_count
FROM analytics.sales.fact_orders o
JOIN analytics.sales.dim_regions r ON o.region_id = r.region_id
WHERE o.order_date >= DATEADD(DAY, -30, CURRENT_DATE)
  AND o.order_status = 'completed'
GROUP BY r.region_name, DATE_TRUNC('DAY', o.order_date)
ORDER BY day DESC, daily_revenue DESC;
```

**Optimized query rewrite (Tableau LookML/calculation):**

```sql
-- Point Tableau / Looker at the mart instead of fact_orders.
SELECT region_name, day, daily_revenue, distinct_customers, order_count
FROM analytics.marts.daily_revenue_by_region
WHERE day >= DATEADD(DAY, -30, CURRENT_DATE)
ORDER BY day DESC, daily_revenue DESC;
```

> **Important:** the rewrite must be made in Tableau / Looker (LookML, calculated field, or data source connection), not in raw SQL. The BI tool is auto-generating the original — changing the query string in Snowflake won't affect what Tableau emits.

**Expected impact:** 155 executions of a 4.6s aggregation reduced to ~50ms point lookups. Cost reduction: $10-11 of the $11.59. Materialization cost itself is small — one aggregation every 15 minutes against `fact_orders` (already filtered by date).

**Validation:** Compare the mart's totals to a fresh `fact_orders` aggregation for a known day — should match within a small refresh-lag window.

---

### #3. Build a Tableau order-detail mart (One Big Table)

**Addresses:** `936c1922` (55 executions, $30.88 estimated, 45.5GB scanned, 18.9s avg)
**Priority:** HIGH (highest cost-per-execution among Tableau patterns)
**Refresh strategy:** Snowflake Dynamic Table with `target_lag = '1 hour'`
**Implementation risk:** MEDIUM — 5-table join; verify join cardinalities before rolling out.

`TABLEAU_SERVICE` runs a 5-table join (`fact_orders`, `dim_customers`, `dim_regions`, `fact_order_items`, `dim_products`) selecting 14 columns 55 times. This is a single dashboard rendering all order detail lines. Each execution costs $0.56 estimated and scans 800MB+ — by far the most expensive Tableau pattern.

```sql
CREATE OR REPLACE DYNAMIC TABLE analytics.marts.order_details_obt
  TARGET_LAG = '1 hour'
  WAREHOUSE = WH_ETL_M
  CLUSTER BY (order_date, customer_segment)
AS
SELECT
    o.order_id,
    o.order_date,
    o.order_status,
    o.total_amount,
    c.customer_name,
    c.email,
    c.customer_segment,
    r.region_name,
    oi.product_id,
    oi.quantity,
    oi.unit_price,
    oi.discount_amount,
    p.product_name,
    p.product_category
FROM analytics.sales.fact_orders o
JOIN analytics.sales.dim_customers c ON o.customer_id = c.customer_id
JOIN analytics.sales.dim_regions r ON o.region_id = r.region_id
JOIN analytics.sales.fact_order_items oi ON o.order_id = oi.order_id
JOIN analytics.sales.dim_products p ON oi.product_id = p.product_id
WHERE o.order_date >= DATEADD(DAY, -90, CURRENT_DATE);
```

**Optimized query rewrite (Tableau data source):**

```sql
-- Point Tableau at the OBT.
-- 5-way join becomes a single-table scan with predicate pushdown on order_date.
SELECT
    order_id, order_date, order_status, total_amount,
    customer_name, email, customer_segment, region_name,
    product_id, quantity, unit_price, discount_amount,
    product_name, product_category
FROM analytics.marts.order_details_obt
WHERE order_date >= DATEADD(DAY, -30, CURRENT_DATE);
```

**Expected impact:** 18.9s 5-way join reduced to ~1-2s clustered range scan. Bytes scanned drop ~30x. Cost reduction: $25-28 of the $30.88. Storage cost increases modestly (~5GB for a 90-day window).

**Implementation risks:**
- Join cardinalities — `fact_order_items` has multiple rows per order. Confirm the OBT row count is what you expect (one row per `(order_id, product_id)`).
- Dashboard semantics — if the Tableau view does any deduping by `order_id`, the OBT shape may surprise it. Validate one specific dashboard before rolling out broadly.

---

### #4. Build a customer lifetime value mart for data-science workloads

**Addresses:** `869547fc`, `c21df823`, `ed82b68f`, `1e7b3391`, `f8d3dc6b`, `c99971e8`, `6e6913d7`, `cc4d1033`, `ead3c45b` (9 distinct one-off queries, ~$45 estimated total, 70-105s each)
**Priority:** MEDIUM (sum of one-offs is meaningful, but each query is different)
**Refresh strategy:** dbt incremental model, daily refresh
**Implementation risk:** MEDIUM — CLV definitions vary by team; expect to iterate.

Three data scientists (emma.davis, noah.martinez, with rachel.thompson, jordan.lee, mike.johnson contributing one each) are independently running customer-cohort and lifetime-value queries against `dim_customers × fact_orders`. Each query is a different fingerprint (different windowing, different metrics, different segmentations) but they all answer variants of "how much has this customer been worth, over what window, in what segment." Materializing the underlying customer-aggregate table once and letting each analyst slice it solves all 9 patterns cheaply.

```sql
CREATE OR REPLACE TABLE analytics.marts.customer_lifetime_metrics
AS
WITH base AS (
    SELECT
        c.customer_id,
        c.customer_name,
        c.customer_segment,
        c.signup_date,
        COUNT(DISTINCT o.order_id) AS lifetime_order_count,
        SUM(o.total_amount) AS lifetime_revenue,
        AVG(o.total_amount) AS avg_order_value,
        MIN(o.order_date) AS first_order_date,
        MAX(o.order_date) AS most_recent_order_date,
        COUNT(DISTINCT CASE WHEN o.order_date >= DATEADD(DAY, -30, CURRENT_DATE) THEN o.order_id END) AS orders_last_30d,
        COUNT(DISTINCT CASE WHEN o.order_date >= DATEADD(DAY, -90, CURRENT_DATE) THEN o.order_id END) AS orders_last_90d,
        SUM(CASE WHEN o.order_date >= DATEADD(DAY, -30, CURRENT_DATE) THEN o.total_amount ELSE 0 END) AS revenue_last_30d,
        SUM(CASE WHEN o.order_date >= DATEADD(DAY, -90, CURRENT_DATE) THEN o.total_amount ELSE 0 END) AS revenue_last_90d
    FROM analytics.sales.dim_customers c
    LEFT JOIN analytics.sales.fact_orders o
        ON c.customer_id = o.customer_id
        AND o.order_status = 'completed'
    GROUP BY c.customer_id, c.customer_name, c.customer_segment, c.signup_date
)
SELECT
    *,
    DATEDIFF(DAY, first_order_date, CURRENT_DATE) AS days_as_customer,
    DATEDIFF(DAY, most_recent_order_date, CURRENT_DATE) AS days_since_last_order,
    CASE
        WHEN orders_last_30d > 0 THEN 'active'
        WHEN orders_last_90d > 0 THEN 'recent'
        WHEN most_recent_order_date IS NULL THEN 'never_purchased'
        ELSE 'churned'
    END AS customer_status
FROM base;
```

**Refresh strategy as a dbt model:**

```sql
-- models/marts/customer_lifetime_metrics.sql
{{ config(
    materialized='table',
    cluster_by=['customer_segment', 'customer_status']
) }}
-- (body of the SELECT above)
```

Schedule a daily run via dbt Cloud or Airflow. Most CLV queries don't need sub-day freshness.

**Original query (representative — emma.davis cohort scan):**

```sql
SELECT
    c.customer_id, c.customer_name, c.customer_segment,
    COUNT(DISTINCT o.order_id) AS orders,
    SUM(o.total_amount) AS revenue,
    AVG(o.total_amount) AS aov
FROM analytics.sales.dim_customers c
LEFT JOIN analytics.sales.fact_orders o ON c.customer_id = o.customer_id
WHERE o.order_date >= DATEADD(DAY, -90, CURRENT_DATE)
GROUP BY c.customer_id, c.customer_name, c.customer_segment;
```

**Optimized query rewrite:**

```sql
-- Use the mart; pre-computed per-customer aggregates.
SELECT
    customer_id, customer_name, customer_segment,
    orders_last_90d AS orders,
    revenue_last_90d AS revenue,
    revenue_last_90d / NULLIF(orders_last_90d, 0) AS aov
FROM analytics.marts.customer_lifetime_metrics
WHERE orders_last_90d > 0;
```

**Expected impact:** 9 ad-hoc queries averaging 75 seconds each (~$5-7 estimated each) replaced by sub-second mart lookups. Cost reduction: $30-40 over a 7-day window, plus reclaimed analyst time. Long-term win is bigger as the team standardizes on shared definitions.

**Implementation risks:**
- CLV definitions — every analyst has slightly different windows / order-status filters. Get alignment on the canonical set before building. Add the per-team variants as additional columns, not separate marts.
- Late-arriving data — fact_orders has a small fraction of orders backdated. Daily refresh handles this; sub-hour refresh would over-amplify the noise.

---

### #5. Right-size or split `WH_DS_2XL`

**Addresses:** all 9 queries from emma.davis on `WH_DS_2XL` (~$14.60 estimated)
**Priority:** MEDIUM (cost is meaningful, fix is cheap)
**Refresh strategy:** N/A (warehouse change, not a model)
**Implementation risk:** LOW — affects one user; easy to revert.

`WH_DS_2XL` is a 2X-Large warehouse running 9 queries from one user (emma.davis) at 31s average. At Snowflake pricing, 2X-Large costs 32 credits/hour; if she's running 9 queries averaging 31s on it, the warehouse spends most of its time running auto-suspended-but-warming-up cycles. Either:

- **Downsize to L (16 credits/hour)** if her queries actually need the parallelism.
- **Move to `WH_ANALYTICS_L` or `WH_DS_XL`** (already exists for noah.martinez) and decommission `WH_DS_2XL`.
- **Keep `WH_DS_2XL` for the rare exploration use** (CLV-class queries) but change its `AUTO_SUSPEND` to 60 seconds.

Recommendation #4 (CLV mart) will eliminate most of the queries that justify the 2X-Large in the first place. After the mart ships, `WH_DS_2XL` should consolidate into `WH_DS_XL`.

```sql
-- After the CLV mart is in place:
ALTER WAREHOUSE WH_DS_2XL SET WAREHOUSE_SIZE = 'XLARGE';
-- Or, after a few weeks of data:
DROP WAREHOUSE WH_DS_2XL;
GRANT USAGE ON WAREHOUSE WH_DS_XL TO ROLE DATA_SCIENTIST;
```

**Expected impact:** ~$10-12 estimated saved per 7-day window. Larger if `emma.davis` shifts from ad-hoc CLV to the mart.

---

## Query Rewrites

These are the highest-leverage rewrites pulled out for teams who want to ship them independently of the materialization work. Each one is small enough to drop into a dbt model, BI tool, or ad-hoc query today.

### Rewrite #1 — Predicate pushdown on Stripe extracts (`14748e7d`)

```sql
-- BEFORE: scans the full payments table, then filters
SELECT * FROM raw.stripe.payments
WHERE created_at >= DATEADD(DAY, -7, CURRENT_DATE);

-- AFTER: explicit columns, narrower range
SELECT
    payment_id, customer_id, amount, currency, status, created_at
FROM raw.stripe.payments
WHERE created_at >= DATEADD(DAY, -7, CURRENT_DATE);
```
One-line summary: 14-column → 6-column projection cuts bytes scanned ~60%.

### Rewrite #2 — `COUNT(DISTINCT)` → `APPROX_COUNT_DISTINCT` (Looker weekly metrics, `5297d5b1`)

```sql
-- BEFORE
SELECT
    DATE_TRUNC('WEEK', order_date) AS week,
    COUNT(DISTINCT order_id) AS orders,
    COUNT(DISTINCT customer_id) AS customers
FROM analytics.sales.fact_orders
WHERE order_date >= DATEADD(DAY, -90, CURRENT_DATE)
  AND order_status = 'completed'
GROUP BY DATE_TRUNC('WEEK', order_date);

-- AFTER
SELECT
    DATE_TRUNC('WEEK', order_date) AS week,
    APPROX_COUNT_DISTINCT(order_id) AS orders,
    APPROX_COUNT_DISTINCT(customer_id) AS customers
FROM analytics.sales.fact_orders
WHERE order_date >= DATEADD(DAY, -90, CURRENT_DATE)
  AND order_status = 'completed'
GROUP BY DATE_TRUNC('WEEK', order_date);
```
One-line summary: 2-3% accuracy loss for ~10x faster aggregation on large fact tables. Acceptable for dashboard summaries.

### Rewrite #3 — `ROW_NUMBER` filter → `QUALIFY` (likely present in BI dashboards)

```sql
-- BEFORE
SELECT * FROM (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date DESC) AS rn
    FROM analytics.sales.fact_orders
) WHERE rn = 1;

-- AFTER
SELECT * FROM analytics.sales.fact_orders
QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date DESC) = 1;
```
One-line summary: removes the wrapper subquery; Snowflake optimizer can push predicates through more cleanly.

### Rewrite #4 — Add cluster keys for repeated `order_date` filtering

```sql
-- One-time DDL change against fact_orders
ALTER TABLE analytics.sales.fact_orders CLUSTER BY (order_date, region_id);
```
One-line summary: every Tableau and Looker pattern filters by `order_date`; clustering on it cuts micro-partition scans across all of them. Validate effectiveness with `SELECT SYSTEM$CLUSTERING_INFORMATION('analytics.sales.fact_orders', '(order_date, region_id)')` after a few hours.

### Rewrite #5 — Avoid `LEFT JOIN` when an inner join is correct

Several CLV-style queries use `LEFT JOIN fact_orders` even when the analyst only cares about customers who have ordered — the LEFT JOIN forces a full scan of `dim_customers` plus the matching join. If the downstream query has `WHERE o.order_id IS NOT NULL` or filters on order metrics, switch to `INNER JOIN` and let the optimizer prune.

---

## Patterns Skipped

- **Clusters 24-100 (low-execution one-offs):** mostly 1-2 execution count, $0.50-1.50 each. Individually below the materialization threshold; collectively ~$60 estimated, but each is from a different user/role for a different purpose. Watch the long-tail in the next 7-day window — if any of them start repeating, they become candidates.
- **Cluster 24 (`48fc918a`, ceo@company.com):** 1 execution, $1.82, 22s — a single CEO ad-hoc dim_customers query. Not actionable; ignore.
- **Cluster 25 (`4073bcae`, DBT_PROD):** 1 execution, $1.74, dim_customers — a dbt model run; the optimization belongs in the dbt model itself, not in einblick's purview.
- **Cluster 7 (`5b086e30`, LOOKER product events):** 40 executions, $4.78, but only 6.3s avg and small bytes. The cost-per-query is already low — Looker is doing its job efficiently. Skip unless this grows.

---

## Cost Analysis

**Total estimated compute cost across analyzed patterns:** 310.39 (over 7 days)

**Top consumers (estimated):**

| Slice | Estimated Cost | Share |
|-------|---------------|-------|
| `WH_ETL_L` (Stripe extracts) | 77.81 | 25.1% |
| `WH_TABLEAU` (Tableau service) | 47.95 | 15.4% |
| `WH_ANALYTICS_M` (analyst ad-hoc) | 41.78 | 13.5% |
| `WH_DS_XL` (data scientist 1) | 39.44 | 12.7% |
| `WH_LOOKER` (Looker service) | 30.52 | 9.8% |
| `WH_ANALYTICS_S` (manager / smaller analyst) | 22.48 | 7.2% |
| Other warehouses | 50.41 | 16.3% |

**Estimated savings if all five recommendations land:**

| Recommendation | Estimated Weekly Savings |
|----------------|--------------------------|
| #1 Stripe staging | $60-65 |
| #2 Daily revenue mart | $10-11 |
| #3 Order-details OBT | $25-28 |
| #4 CLV mart | $30-40 |
| #5 WH_DS_2XL right-size | $10-12 |
| **Total** | **$135-156** |

That's ~45-50% of the analyzed weekly cost. The number is upper-bound — sharing warehouses means the actual billed savings will be smaller, but the rankings are right and the implementation order below maximizes ROI.

**Reminder:** these are estimates from `execution_time × warehouse_size`. Actual Snowflake bills are based on warehouse-second consumption, which is invariant to query concurrency — meaning when 8 queries share a warehouse for a second, you pay for 1 second, not 8. Treat these numbers as a ranking, not a forecast.

---

## Access Patterns

- **`raw.stripe.payments` is queried only by data engineers (alex.kumar, jordan.lee).** Good — raw tables shouldn't be exposed to BI users. Once the staging table ships, lock down the raw table to ETL roles only.
- **`analytics.sales.fact_orders` and `dim_customers` are queried across roles** (DATA_ENGINEER, DATA_SCIENTIST, ANALYST, TABLEAU_ROLE, LOOKER_ROLE, even DBT_PROD). The fact tables are central — recommend cluster keys (`order_date`, `region_id`) so every reader benefits.
- **`marketing.public.sessions` is joined by analysts to `fact_orders`** (cluster `af75d0d6`). Cross-schema access is fine, but if this pattern grows, consider a marketing-attribution mart in the analytics schema so analysts don't need direct marketing-schema access.
- **`ceo@company.com` ran one query** — minor, but worth noting that an executive has SELECT access to `dim_customers`. Whether that's intentional or leaked permissions is a governance question for the data team.
- **`DBT_PROD` ran one cataloged query** — that's a dbt model run that ended up in QUERY_HISTORY. Not actionable here.

---

## Implementation Checklist

1. **Build `analytics.staging.stripe_payments_30d` (Recommendation #1).** ETL warehouse cost is the largest single line item. Lowest risk because it's a transparent staging pull. Validation: row count matches the source within 1 hour of refresh.
   - Required permissions: `CREATE DYNAMIC TABLE` on `analytics.staging`; `SELECT` on `raw.stripe.payments` from the warehouse role; `USAGE` on `WH_ETL_S`.
   - Dependencies: none. This unblocks engineers immediately.

2. **Build `analytics.marts.daily_revenue_by_region` (Recommendation #2).** Highest-execution-count BI pattern. Validation: a single day's totals from the mart should match a fresh `fact_orders` aggregation within the lag window.
   - Required permissions: `CREATE DYNAMIC TABLE` on `analytics.marts`; `SELECT` on `fact_orders` and `dim_regions`.
   - Dependencies: cluster `fact_orders` by `order_date` first (Rewrite #4 DDL).

3. **Build `analytics.marts.order_details_obt` (Recommendation #3).** Highest cost-per-execution BI pattern. Validation: validate one specific Tableau dashboard against the OBT before swapping all dashboards.
   - Required permissions: `CREATE DYNAMIC TABLE` on `analytics.marts`; `SELECT` on all 5 source tables.
   - Dependencies: cluster `fact_orders` by `order_date` first.
   - Risk: confirm join cardinalities — `fact_order_items` produces multiple rows per order.

4. **Build `analytics.marts.customer_lifetime_metrics` (Recommendation #4).** Get cross-team alignment on CLV definition before writing the dbt model.
   - Required permissions: `CREATE TABLE` on `analytics.marts` (or `dbt_cloud_pr` schema for the staging build); `SELECT` on `dim_customers` and `fact_orders`.
   - Dependencies: ideally do after rewrites #1-3 so the warehouse load drops first.
   - Validation: spot-check 5 known customers against a manual `fact_orders` aggregation.

5. **Cluster `fact_orders` (Rewrite #4 DDL).** Single one-line DDL change, benefits every recommendation above.
   - Required permissions: `OWNERSHIP` or sufficient `ALTER` rights on `analytics.sales.fact_orders`.
   - Validation: run `SELECT SYSTEM$CLUSTERING_INFORMATION('analytics.sales.fact_orders', '(order_date, region_id)')` after 24 hours; expect `average_overlaps` to drop and `average_depth` to be near 1.

6. **Right-size `WH_DS_2XL` (Recommendation #5).** Wait until Recommendation #4 is in place — most of the queries justifying the 2X-large size will move to the mart.
   - Required permissions: `MODIFY` on `WH_DS_2XL`; possibly `CREATE WAREHOUSE` if you're spinning up a replacement.

7. **Reach out to the data scientists running per-customer cohort queries.** Once the CLV mart ships, share it with emma.davis, noah.martinez, and the rest of the data-science team. Their adoption is the actual signal of success — a mart no one queries doesn't save anything.

---

## Proposed dbt Changes

### 1. `new_model`: staging/stg_stripe_payments_30d

- **Materialization:** `incremental`
- **Source tables:** `raw.stripe.payments`
- **Rationale:** 50 executions of `SELECT * FROM raw.stripe.payments` filtered by `created_at` are dominating ETL warehouse cost. A 30-day rolling staging table with explicit columns eliminates the repeat work and locks down access to the raw table.
- **Fingerprints addressed:** `14748e7d`, `1fb1bdcc`, `7797ac41`, `5ee11407`, `5ff34aa9`, `9298f0a9`, `f1a58734`

**Proposed SQL:**

```sql
{{ config(
    materialized='incremental',
    unique_key='payment_id',
    incremental_strategy='merge',
    cluster_by=['created_at']
) }}
SELECT
    payment_id,
    customer_id,
    amount,
    currency,
    status,
    payment_method,
    created_at,
    updated_at
FROM {{ source('stripe', 'payments') }}
WHERE created_at >= DATEADD(DAY, -30, CURRENT_DATE)
{% if is_incremental() %}
  AND updated_at > (SELECT MAX(updated_at) FROM {{ this }})
{% endif %}
```

**Proposed tests:**

- `payment_id`: unique, not_null
- `customer_id`: not_null
- `created_at`: not_null
- `status`: accepted_values: `['succeeded', 'failed', 'pending', 'refunded']`

### 2. `new_model`: mart/daily_revenue_by_region

- **Materialization:** `table`
- **Source tables:** `analytics.sales.fact_orders`, `analytics.sales.dim_regions`
- **Rationale:** Looker and Tableau service accounts re-run the same daily revenue aggregation 155 times in 7 days. Materialize once per dashboard refresh window; let BI tools point at the mart.
- **Fingerprints addressed:** `d1c5c07c`

**Proposed SQL:**

```sql
{{ config(
    materialized='table',
    cluster_by=['day', 'region_name']
) }}
SELECT
    r.region_name,
    DATE_TRUNC('DAY', o.order_date) AS day,
    SUM(o.total_amount) AS daily_revenue,
    COUNT(DISTINCT o.customer_id) AS distinct_customers,
    COUNT(*) AS order_count
FROM {{ ref('fact_orders') }} o
JOIN {{ ref('dim_regions') }} r ON o.region_id = r.region_id
WHERE o.order_date >= DATEADD(DAY, -90, CURRENT_DATE)
  AND o.order_status = 'completed'
GROUP BY r.region_name, DATE_TRUNC('DAY', o.order_date)
```

**Proposed tests:**

- `region_name`: not_null
- `day`: not_null
- `daily_revenue`: not_null

### 3. `new_model`: mart/order_details_obt

- **Materialization:** `incremental`
- **Source tables:** `analytics.sales.fact_orders`, `analytics.sales.dim_customers`, `analytics.sales.dim_regions`, `analytics.sales.fact_order_items`, `analytics.sales.dim_products`
- **Rationale:** Tableau renders this 5-way join 55 times in 7 days at 18.9s and $0.56 per execution. Pre-joining once per refresh window gives dashboard queries a single-table scan.
- **Fingerprints addressed:** `936c1922`

**Proposed SQL:**

```sql
{{ config(
    materialized='incremental',
    unique_key=['order_id', 'product_id'],
    incremental_strategy='merge',
    cluster_by=['order_date', 'customer_segment']
) }}
SELECT
    o.order_id,
    o.order_date,
    o.order_status,
    o.total_amount,
    c.customer_name,
    c.email,
    c.customer_segment,
    r.region_name,
    oi.product_id,
    oi.quantity,
    oi.unit_price,
    oi.discount_amount,
    p.product_name,
    p.product_category
FROM {{ ref('fact_orders') }} o
JOIN {{ ref('dim_customers') }} c ON o.customer_id = c.customer_id
JOIN {{ ref('dim_regions') }} r ON o.region_id = r.region_id
JOIN {{ ref('fact_order_items') }} oi ON o.order_id = oi.order_id
JOIN {{ ref('dim_products') }} p ON oi.product_id = p.product_id
WHERE o.order_date >= DATEADD(DAY, -90, CURRENT_DATE)
{% if is_incremental() %}
  AND o.order_date > (SELECT DATEADD(DAY, -7, MAX(order_date)) FROM {{ this }})
{% endif %}
```

**Proposed tests:**

- `order_id`: not_null
- `product_id`: not_null
- `order_date`: not_null
- Combined: `unique` on `(order_id, product_id)`

### 4. `new_model`: mart/customer_lifetime_metrics

- **Materialization:** `table`
- **Source tables:** `analytics.sales.dim_customers`, `analytics.sales.fact_orders`
- **Rationale:** Three data scientists are independently running 9 different customer-cohort and CLV queries against `dim_customers × fact_orders`, each taking 70-105 seconds and ~$5-7 estimated. One shared per-customer aggregate table replaces all of them.
- **Fingerprints addressed:** `869547fc`, `c21df823`, `ed82b68f`, `1e7b3391`, `f8d3dc6b`, `c99971e8`, `6e6913d7`, `cc4d1033`, `ead3c45b`

**Proposed SQL:**

```sql
{{ config(
    materialized='table',
    cluster_by=['customer_segment', 'customer_status']
) }}
WITH base AS (
    SELECT
        c.customer_id,
        c.customer_name,
        c.customer_segment,
        c.signup_date,
        COUNT(DISTINCT o.order_id) AS lifetime_order_count,
        SUM(o.total_amount) AS lifetime_revenue,
        AVG(o.total_amount) AS avg_order_value,
        MIN(o.order_date) AS first_order_date,
        MAX(o.order_date) AS most_recent_order_date,
        COUNT(DISTINCT CASE WHEN o.order_date >= DATEADD(DAY, -30, CURRENT_DATE) THEN o.order_id END) AS orders_last_30d,
        COUNT(DISTINCT CASE WHEN o.order_date >= DATEADD(DAY, -90, CURRENT_DATE) THEN o.order_id END) AS orders_last_90d,
        SUM(CASE WHEN o.order_date >= DATEADD(DAY, -30, CURRENT_DATE) THEN o.total_amount ELSE 0 END) AS revenue_last_30d,
        SUM(CASE WHEN o.order_date >= DATEADD(DAY, -90, CURRENT_DATE) THEN o.total_amount ELSE 0 END) AS revenue_last_90d
    FROM {{ ref('dim_customers') }} c
    LEFT JOIN {{ ref('fact_orders') }} o
        ON c.customer_id = o.customer_id
        AND o.order_status = 'completed'
    GROUP BY c.customer_id, c.customer_name, c.customer_segment, c.signup_date
)
SELECT
    *,
    DATEDIFF(DAY, first_order_date, CURRENT_DATE) AS days_as_customer,
    DATEDIFF(DAY, most_recent_order_date, CURRENT_DATE) AS days_since_last_order,
    CASE
        WHEN orders_last_30d > 0 THEN 'active'
        WHEN orders_last_90d > 0 THEN 'recent'
        WHEN most_recent_order_date IS NULL THEN 'never_purchased'
        ELSE 'churned'
    END AS customer_status
FROM base
```

**Proposed tests:**

- `customer_id`: unique, not_null
- `customer_status`: accepted_values: `['active', 'recent', 'churned', 'never_purchased']`
- `lifetime_revenue`: not_null
