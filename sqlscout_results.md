# SqlScout Analysis Report

**Platform**: Snowflake | **Window**: 7 days | **Total**: 775 queries, 254 distinct patterns | **Cost**: 310.4 credits, 437 GB scanned

**User context**: Fivetran ingestion, daily freshness, dbt transformation layer, ~$1K-$10K/day spend.

## 1. Executive Summary

The single biggest problem is `SELECT * FROM raw.stripe.payments` -- 50 full-table scans by two data engineers burning **70 credits (23% of weekly spend)** and scanning 83 GB on an L-sized warehouse. The second biggest is that Looker and Tableau are running the **same hand-written SQL 155 times per week** for regional daily revenue -- a textbook materialization opportunity that would collapse ~250 BI queries into a single daily refresh. Combined, three targeted fixes would cut roughly **40-50% of weekly credit consumption** with no application changes.

## 2. Biggest Offenders

### Users burning the most credits

| User | Role | Queries | Credits | Avg runtime | Primary warehouse |
|---|---|---|---|---|---|
| **ALEX_KUMAR** | DATA_ENGINEER | 38 | 51.2 | 28.3s | WH_ETL_L |
| **TABLEAU_SERVICE** | TABLEAU | 191 | 48.6 | 10.0s | WH_TABLEAU |
| **JORDAN_LEE** | DATA_ENGINEER | 31 | 34.3 | 22.9s | WH_ETL_L |
| **LOOKER_SERVICE** | LOOKER | 249 | 31.3 | 6.4s | WH_LOOKER |
| **EMMA_DAVIS** | DATA_SCIENTIST | 16 | 28.2 | 30.9s (max 104s) | WH_DS_2XL |
| **NOAH_MARTINEZ** | DATA_SCIENTIST | 20 | 25.9 | 26.3s (max 101s) | WH_DS_XL |

**What this tells us:**
- The two ETL engineers (ALEX + JORDAN) are the single largest cost center but they only run 69 queries -- meaning each one is massively expensive. They're hammering `raw.stripe.payments`.
- Tableau + Looker together = 440 queries (57% of volume) but only 80 credits (26% of cost) -- they're cheap individually but *chronically repetitive*. Materialization will wipe out huge swaths of this.
- Data scientists run <40 queries but burn 54 credits on 2XL/XL warehouses with max runtimes exceeding 100 seconds -- these are exploratory ML feature builds that are shape-different but semantically near-identical.

### Slowest query patterns (by avg runtime)

1. `SELECT * FROM raw.stripe.payments WHERE created_at >= ?` -- **29s avg, 50 execs, 70 credits** (the worst)
2. Tableau's 5-way join across orders/customers/products/regions/items -- **19s avg, 55 execs, 31 credits**
3. Customer LTV rollup by SARAH/MIKE -- **12s avg, 43 execs, 11 credits**

### Warehouse inefficiencies

- **WH_ETL_L: 77.8 credits on 64 queries** -- highest total spend, driven by `SELECT *` scans that don't need an L-sized warehouse if the tables were pruned properly.
- **WH_DS_2XL: 1.62 credits/query average** -- highest per-query cost. EMMA runs a 2XL for ad hoc ML features. This is only justified if the queries actually need the parallelism.

## 3. Top Recommendations

### HIGH priority

#### R1. Eliminate `SELECT *` on raw.stripe.payments -- enforce column pruning

**Addresses**: fingerprints `14748e7dcac58cd0...` (50x, 70 cr), `1fb1bdccae5afdaa...` (2x), several one-off column-subset variants (~10 more executions).

**Problem**: `SELECT * FROM raw.stripe.payments` is being run every few hours by the ETL team. The table has ~16 columns; most downstream uses only need `payment_id, customer_id, amount, payment_status, created_at`. 50 scans × 1.6 GB = 83 GB/week scanned unnecessarily.

**Action**:
```sql
-- 1. Build a pruned incremental Dynamic Table
CREATE OR REPLACE DYNAMIC TABLE analytics.staging.payments_recent
  TARGET_LAG = '1 hour'
  WAREHOUSE = WH_ETL_L
AS
SELECT
    payment_id,
    customer_id,
    amount,
    currency,
    payment_status,
    payment_method,
    fee_amount,
    net_amount,
    created_at,
    updated_at
FROM raw.stripe.payments
WHERE created_at >= DATEADD(day, -30, CURRENT_DATE());

-- 2. Add clustering on raw.stripe.payments (if >1GB, which it appears to be)
ALTER TABLE raw.stripe.payments CLUSTER BY (created_at);
```

**Expected impact**: ~60 credits/week saved (86% reduction on this pattern). Bytes scanned drops from 83 GB to ~5 GB for downstream queries.

**Refresh**: Dynamic Table auto-refreshes every hour.

**Risk**: LOW. If engineers actually need metadata/failure columns, they can still query `raw.stripe.payments` directly -- but we should audit those uses (fingerprints `7797ac41...`, `5ee11407...`, etc. show column subsets including failure_message, failure_code -- these are legit debugging queries that can keep using the raw table).

---

#### R2. Materialize the daily revenue by region query (Looker + Tableau's #1 dashboard)

**Addresses**: fingerprint `4bcbda3cbc240f99...` (155x, 12 cr, 13.5 GB scanned).

**Problem**: The exact same query -- regional daily revenue aggregation -- is executed 155 times per week (22x/day) across two BI services. Every single execution re-scans `fact_orders` joined to `dim_regions`. This is the textbook case for a Dynamic Table.

**Action**:
```sql
CREATE OR REPLACE DYNAMIC TABLE analytics.marts.daily_revenue_by_region
  TARGET_LAG = '1 hour'
  WAREHOUSE = WH_ETL_L
  CLUSTER BY (day, region_name)
AS
SELECT
    r.region_name,
    DATE_TRUNC('day', o.order_date) AS day,
    SUM(o.total_amount) AS daily_revenue,
    COUNT(DISTINCT o.customer_id) AS unique_buyers,
    COUNT(*) AS order_count
FROM analytics.sales.fact_orders o
JOIN analytics.sales.dim_regions r ON o.region_id = r.region_id
WHERE o.order_status = 'completed'
GROUP BY r.region_name, DATE_TRUNC('day', o.order_date);

-- Then point Looker/Tableau at this table instead of the join
```

**Expected impact**: ~11 credits/week saved on this pattern alone. BI dashboards load ~3-5x faster (sub-second vs 4.6s avg).

**Refresh**: Dynamic Table with 1h lag fits "daily freshness" requirement with headroom.

**Risk**: LOW. You already use dbt -- implement this as a dbt model with `materialized='dynamic_table'` instead of hand-writing the DDL.

**dbt model version** (recommended given their dbt context):
```sql
-- models/marts/daily_revenue_by_region.sql
{{ config(
    materialized='dynamic_table',
    snowflake_warehouse='WH_ETL_L',
    target_lag='1 hour',
    cluster_by=['day', 'region_name']
) }}

SELECT
    r.region_name,
    DATE_TRUNC('day', o.order_date) AS day,
    SUM(o.total_amount) AS daily_revenue,
    COUNT(DISTINCT o.customer_id) AS unique_buyers,
    COUNT(*) AS order_count
FROM {{ ref('fact_orders') }} o
JOIN {{ ref('dim_regions') }} r ON o.region_id = r.region_id
WHERE o.order_status = 'completed'
GROUP BY 1, 2
```

---

#### R3. Materialize the weekly executive KPI rollup

**Addresses**: fingerprint `07aef86a1330b894...` (95x, 9 cr).

**Problem**: Tableau and Looker both run this weekly revenue rollup 95 times/week. Same join pattern, same aggregation, small result set.

**Action**: Same pattern as R2 -- dbt model materialized as a Dynamic Table (weekly grain means you could even run it daily).

**Expected impact**: ~9 credits/week saved. Dashboard refresh becomes instantaneous.

**Risk**: LOW.

---

### MEDIUM priority

#### R4. Pre-join the Tableau "full order detail" OBT

**Addresses**: fingerprint `d20fa52ece04edbd...` (55x, 31 cr, 46 GB scanned).

**Problem**: Tableau's detail-level dashboard joins 5 tables on every refresh. 55 executions × 5-table join = a lot of redundant work. Total credits (31) are second only to R1 in cost.

**Action**:
```sql
CREATE OR REPLACE DYNAMIC TABLE analytics.marts.order_detail_wide
  TARGET_LAG = '2 hours'
  WAREHOUSE = WH_ETL_L
  CLUSTER BY (order_date, region_name)
AS
SELECT
    o.order_id, o.order_date, o.order_status, o.total_amount,
    c.customer_name, c.email, c.customer_segment,
    r.region_name,
    oi.product_id, oi.quantity, oi.unit_price, oi.discount_amount,
    p.product_name, p.product_category
FROM analytics.sales.fact_orders o
JOIN analytics.sales.dim_customers c ON o.customer_id = c.customer_id
JOIN analytics.sales.dim_regions r ON o.region_id = r.region_id
JOIN analytics.sales.fact_order_items oi ON o.order_id = oi.order_id
JOIN analytics.sales.dim_products p ON oi.product_id = p.product_id
WHERE o.order_date >= DATEADD(day, -90, CURRENT_DATE());
```

**Expected impact**: ~25 credits/week saved. Tableau's heaviest dashboard loads 5-10x faster.

**Refresh**: 2h lag is fine (this is a daily-freshness org).

**Risk**: MEDIUM. Wide tables have higher storage cost, but this is the dominant join pattern across 4 other ad hoc query clusters too (`31d8b80752ca...`, `e4209ce2778...`, `29ce2d7742...`, `157911d2391...`). Building it once pays dividends.

---

#### R5. Customer LTV rollup table (analyst saved queries)

**Addresses**: fingerprint `d02632acc075ffcf...` (43x, 11 cr) -- SARAH and MIKE's recurring LTV query.

**Action**:
```sql
CREATE OR REPLACE DYNAMIC TABLE analytics.marts.customer_lifetime_value
  TARGET_LAG = '6 hours'
  WAREHOUSE = WH_ANALYTICS_M
AS
SELECT
    c.customer_id, c.customer_name, c.email,
    c.signup_date, c.customer_segment,
    COUNT(o.order_id) AS total_orders,
    SUM(o.total_amount) AS lifetime_value,
    AVG(o.total_amount) AS avg_order_value,
    MAX(o.order_date) AS last_order_date,
    DATEDIFF('day', MAX(o.order_date), CURRENT_DATE()) AS days_since_last_order
FROM analytics.sales.dim_customers c
LEFT JOIN analytics.sales.fact_orders o ON c.customer_id = o.customer_id
GROUP BY 1, 2, 3, 4, 5;
```

**Expected impact**: ~10 credits/week. Analysts get sub-second results on what's currently a 12-second query.

**Risk**: LOW.

---

### LOW priority (still worth doing)

#### R6. Clustering on `fact_orders` by `order_date`

**Problem**: Almost every analytical query filters on `o.order_date >= X`. Currently doing 4-19 second table scans. Clustering by date enables partition pruning.

**Action**:
```sql
ALTER TABLE analytics.sales.fact_orders CLUSTER BY (order_date);
-- Validate after:
SELECT SYSTEM$CLUSTERING_INFORMATION('analytics.sales.fact_orders');
```

**Expected impact**: 20-50% reduction in bytes scanned on any date-filtered query. Compounds with materialization savings.

**Risk**: LOW, but requires confirming the table is >1GB (highly likely given 437 GB total weekly scan volume dominated by this table).

#### R7. Clustering on `raw.stripe.payments` by `created_at`

Included inside R1 but worth calling out independently if R1 isn't adopted.

#### R8. Investigate EMMA and NOAH's ML feature queries

**Problem**: 7+ clusters (`cbde4da7...`, `6897ee23...`, `78dc3723...`, `5c2b1530...`, `cb509934...`, `75c88fc4...`, `4efba2d3...`, `9425f080...`) are all one-off variants of "aggregate customer order metrics with slightly different column sets" on a 2XL warehouse. Each runs once but costs 3-7 credits. Combined: ~40 credits/week on essentially the same underlying computation.

**Action**: Build a single wide customer feature table that includes *all* the metrics they might want:
```sql
CREATE OR REPLACE DYNAMIC TABLE analytics.marts.customer_features_90d
  TARGET_LAG = '12 hours'
  WAREHOUSE = WH_ETL_L
AS
SELECT
    c.customer_id, c.customer_segment,
    DATEDIFF('day', c.signup_date, CURRENT_DATE()) AS account_age_days,
    COUNT(o.order_id) AS order_count_90d,
    SUM(o.total_amount) AS spend_90d,
    AVG(o.total_amount) AS avg_order_90d,
    STDDEV(o.total_amount) AS stddev_order_90d,
    MAX(o.total_amount) AS max_order_90d,
    MIN(o.total_amount) AS min_order_90d,
    COUNT(DISTINCT DATE_TRUNC('week', o.order_date)) AS active_weeks,
    COUNT(DISTINCT o.region_id) AS regions_ordered_from,
    SUM(CASE WHEN o.order_status = 'returned' THEN 1 ELSE 0 END) AS return_count
FROM analytics.sales.dim_customers c
LEFT JOIN analytics.sales.fact_orders o
    ON c.customer_id = o.customer_id
    AND o.order_date >= DATEADD(day, -90, CURRENT_DATE())
GROUP BY c.customer_id, c.customer_segment, c.signup_date;
```

**Expected impact**: 30-40 credits/week, and DS users move from WH_DS_2XL to WH_ANALYTICS_S for simple feature lookups.

**Risk**: MEDIUM. DS workflows often need columns not anticipated; add a feedback loop with EMMA/NOAH and be prepared to extend the table.

## 4. Patterns Skipped

- **Single-execution exploratory queries (40+ clusters, ~20 credits combined)**: These are one-offs from analysts and data scientists -- not worth materializing. Their costs are high individually (3-7 credits each) but won't repeat. The real fix is R8 above, which addresses the *pattern family* rather than specific queries.
- **`SELECT * FROM dim_customers WHERE customer_id = ?` (cluster 9, 4x, 3.2 cr)**: Low frequency and dbt/engineers need full rows for debugging. Not a materialization candidate. Consider **Search Optimization Service** if this grows, but 4 executions doesn't justify the SOS maintenance cost yet.
- **HR headcount, supplier spend, warehouse metering queries**: Low volume, low cost, stable daily patterns -- not worth touching.
- **Marketing attribution (cluster 8, 27x, 6 cr)**: On the edge. At $1-10K/day spend, 6 credits isn't urgent, but if it grows to 50+/week it becomes a dbt model candidate.

## 5. Cost Analysis

**Current weekly spend**: 310 credits (roughly $620-$1,240/week depending on credit price).

**Savings from HIGH priority recommendations (R1-R3)**: ~80 credits/week (**26% reduction**).

**Savings adding MEDIUM (R4-R5)**: +35 credits (**37% total reduction**).

**Savings adding LOW (R6-R8)**: +40 credits (**50% total reduction**, accounting for R8 cannibalization of some DS queries).

| Pattern | Before | After | Savings |
|---|---|---|---|
| `SELECT * raw.payments` | 70 cr | ~10 cr | **60** |
| Daily revenue by region | 12 cr | ~1 cr | 11 |
| Weekly exec KPIs | 9 cr | ~1 cr | 8 |
| Tableau full-detail OBT | 31 cr | ~6 cr | 25 |
| Customer LTV | 11 cr | ~1 cr | 10 |
| DS feature builds (consolidated) | 40 cr | ~5 cr | 35 |
| **Total estimated savings** | | | **~150 cr/week** |

At $1K/day spend, that's ~$300-400/week saved, or ~$15-20K/year from a ~1-2 day engineering investment.

## 6. Access Patterns

**Governance observations**:

- **BI service accounts dominate query volume** (LOOKER 249 + TABLEAU 191 = 57% of all queries, 26% of cost). Healthy pattern -- these should stay on dedicated warehouses (WH_LOOKER, WH_TABLEAU).
- **Data engineers (ALEX, JORDAN, TAYLOR) consume 34% of credits with just 75 queries** -- classic "few expensive scans" anti-pattern, concentrated on raw.stripe.payments. Fixing R1 reshapes this dramatically.
- **Data scientists on 2XL/XL warehouses**: Justified if feature pipelines need the parallelism; not justified for the aggregation patterns shown. R8 moves them to smaller warehouses.
- **DBT_PROD role only shows 3 queries** -- either dbt isn't running much this week, or dbt's transformation queries are being captured under other users. Worth confirming.
- **Cross-schema access looks healthy**: `analytics.sales.*` for BI, `raw.stripe.*` for engineers, `marketing.public.*` for attribution analysts. No suspicious cross-domain reads.
- **No "who touches what" governance concerns** in this sample.

## 7. Implementation Checklist

Suggested order, dependencies in parentheses:

1. **Confirm table sizes** (prerequisite to clustering recommendations):
   ```sql
   SELECT table_name, bytes/1024/1024/1024 AS gb
   FROM analytics.sales.information_schema.tables
   WHERE table_name IN ('FACT_ORDERS', 'FACT_ORDER_ITEMS');
   SELECT bytes/1024/1024/1024 FROM raw.stripe.information_schema.tables WHERE table_name='PAYMENTS';
   ```

2. **Audit R1's column usage**: grep the last 30 days of `raw.stripe.payments` queries for which columns are actually read. Build the Dynamic Table's column list from that -- don't guess.

3. **Ship R1 (payments Dynamic Table + clustering)** -- biggest single win. Requires:
   - `GRANT OWNERSHIP ON TABLE raw.stripe.payments TO ROLE SYSADMIN;` (if clustering)
   - `CREATE SCHEMA IF NOT EXISTS analytics.staging;`
   - Update ETL jobs to point at `analytics.staging.payments_recent` instead of `raw.stripe.payments`

4. **Ship R2 + R3 as dbt models** -- you already have the dbt stack, so these should be PRs not ad hoc DDL. One PR per model, materialized as dynamic tables.

5. **Validate after R2/R3**: Look for fingerprints `4bcbda3cbc240f99` and `07aef86a1330b894` to drop out of next week's SqlScout run. They should become near-zero.

6. **Ship R4 (Tableau OBT)** after R2/R3 land -- it's larger and depends on storage monitoring.

7. **Ship R5 (customer LTV)** as a dbt model.

8. **Apply R6 (clustering on `fact_orders`)** -- one `ALTER TABLE` command. Validate with `SYSTEM$CLUSTERING_INFORMATION` after a day.

9. **Build R8 (customer feature table)** with input from EMMA and NOAH on which columns they actually use. Iterate.

10. **Re-run `/sqlscout --sample`** (or against live data) in a week to measure delta.

**Validation queries for each recommendation**:
```sql
-- After R1:
SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE query_text ILIKE 'SELECT * FROM raw.stripe.payments%'
  AND start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP());
-- Should be near zero.

-- After R2:
SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE query_text ILIKE '%fact_orders%dim_regions%group by%region_name%date_trunc%'
  AND start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP());
-- Should drop by ~90%.
```
