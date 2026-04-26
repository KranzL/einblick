# SqlScout Analysis (Snowflake)

- Platform: Snowflake
- Time window: 7 days
- Total queries processed: 775
- Distinct patterns: 254
- Total credits: 310.3931
- Total bytes scanned: 437,027,332,179
- Top patterns shown: 25
- Extracted: 2026-04-17 11:17:06


## Biggest Offenders: Human Users by Credits

These are humans writing ad hoc queries. Optimizations here change user behavior and dashboard SQL.

| User | Queries | Credits | Avg Runtime | Max Runtime | Patterns | Primary Role | Primary Warehouse |
|------|---------|---------|-------------|-------------|----------|--------------|-------------------|
| alex.kumar@company.com | 38 | 51.1913 | 28269ms | 68,991ms | 9 | DATA_ENGINEER | WH_ETL_L |
| jordan.lee@company.com | 31 | 34.3437 | 22899ms | 36,079ms | 12 | DATA_ENGINEER | WH_ETL_L |
| emma.davis@company.com | 16 | 28.1753 | 30926ms | 104,453ms | 16 | DATA_SCIENTIST | WH_DS_2XL |
| noah.martinez@company.com | 20 | 25.8689 | 26308ms | 100,964ms | 20 | DATA_SCIENTIST | WH_DS_XL |
| sarah.chen@company.com | 71 | 23.8521 | 13311ms | 50,313ms | 33 | ANALYST | WH_ANALYTICS_M |
| mike.johnson@company.com | 53 | 19.8758 | 13749ms | 66,758ms | 25 | ANALYST | WH_ANALYTICS_M |
| james.wilson@company.com | 22 | 12.5133 | 20858ms | 51,178ms | 22 | ANALYST | WH_ANALYTICS_M |
| taylor.smith@company.com | 6 | 6.7561 | 24280ms | 59,150ms | 6 | DATA_ENGINEER | WH_ETL_XL |
| rachel.thompson@company.com | 26 | 6.3480 | 11356ms | 32,523ms | 26 | MANAGER | WH_ANALYTICS_S |
| priya.patel@company.com | 20 | 5.8354 | 11721ms | 24,257ms | 20 | ANALYST | WH_ANALYTICS_S |
| lisa.nguyen@company.com | 9 | 5.4013 | 18014ms | 47,924ms | 9 | ANALYST | WH_ANALYTICS_S |
| david.brown@company.com | 16 | 4.3256 | 11771ms | 23,954ms | 16 | MANAGER | WH_ANALYTICS_S |
| ceo@company.com | 5 | 3.9350 | 14299ms | 22,428ms | 5 | EXECUTIVE | WH_ANALYTICS_S |

## Biggest Offenders: Service Accounts by Credits

These are automated users (BI tools, ETL, dbt, etc. -- detected by lack of `@` in username). Their high cost is often expected; focus optimization on the *patterns* they run (dashboards, scheduled refreshes), not the users themselves.

| User | Queries | Credits | Avg Runtime | Max Runtime | Patterns | Primary Role | Primary Warehouse |
|------|---------|---------|-------------|-------------|----------|--------------|-------------------|
| TABLEAU_SERVICE | 190 | 47.9490 | 10053ms | 34,810ms | 23 | TABLEAU_ROLE | WH_TABLEAU |
| LOOKER_SERVICE | 248 | 30.5170 | 6401ms | 25,703ms | 17 | LOOKER_ROLE | WH_LOOKER |

## Biggest Offenders: Users by Total Runtime

| Type | User | Queries | Credits | Avg Runtime | Max Runtime | Primary Warehouse |
|------|------|---------|---------|-------------|-------------|-------------------|
| service | TABLEAU_SERVICE | 190 | 47.9490 | 10053ms | 34,810ms | WH_TABLEAU |
| service | LOOKER_SERVICE | 248 | 30.5170 | 6401ms | 25,703ms | WH_LOOKER |
| human | alex.kumar@company.com | 38 | 51.1913 | 28269ms | 68,991ms | WH_ETL_L |
| human | sarah.chen@company.com | 71 | 23.8521 | 13311ms | 50,313ms | WH_ANALYTICS_M |
| human | mike.johnson@company.com | 53 | 19.8758 | 13749ms | 66,758ms | WH_ANALYTICS_M |
| human | jordan.lee@company.com | 31 | 34.3437 | 22899ms | 36,079ms | WH_ETL_L |
| human | noah.martinez@company.com | 20 | 25.8689 | 26308ms | 100,964ms | WH_DS_XL |
| human | emma.davis@company.com | 16 | 28.1753 | 30926ms | 104,453ms | WH_DS_2XL |
| human | james.wilson@company.com | 22 | 12.5133 | 20858ms | 51,178ms | WH_ANALYTICS_M |
| human | rachel.thompson@company.com | 26 | 6.3480 | 11356ms | 32,523ms | WH_ANALYTICS_S |
| human | priya.patel@company.com | 20 | 5.8354 | 11721ms | 24,257ms | WH_ANALYTICS_S |
| human | david.brown@company.com | 16 | 4.3256 | 11771ms | 23,954ms | WH_ANALYTICS_S |
| human | lisa.nguyen@company.com | 9 | 5.4013 | 18014ms | 47,924ms | WH_ANALYTICS_S |
| human | taylor.smith@company.com | 6 | 6.7561 | 24280ms | 59,150ms | WH_ETL_XL |
| human | ceo@company.com | 5 | 3.9350 | 14299ms | 22,428ms | WH_ANALYTICS_S |

## Biggest Offenders: Warehouses

| Warehouse | Queries | Credits | Avg Runtime | Users | Avg Cost/Query |
|-----------|---------|---------|-------------|-------|----------------|
| WH_ETL_L | 64 | 77.8094 | 25262ms | 2 | 1.215772 |
| WH_TABLEAU | 190 | 47.9490 | 10053ms | 1 | 0.252363 |
| WH_ANALYTICS_M | 129 | 41.7800 | 12530ms | 4 | 0.323876 |
| WH_DS_XL | 27 | 39.4419 | 27342ms | 2 | 1.460810 |
| WH_LOOKER | 248 | 30.5170 | 6401ms | 1 | 0.123052 |
| WH_ANALYTICS_S | 67 | 22.4828 | 12550ms | 5 | 0.335564 |
| WH_ANALYTICS_L | 26 | 17.8238 | 24118ms | 2 | 0.685532 |
| WH_DS_2XL | 9 | 14.6023 | 31418ms | 1 | 1.622477 |
| WH_ETL_XL | 11 | 14.4818 | 28457ms | 2 | 1.316527 |
| WH_DBT | 3 | 2.5040 | 10272ms | 1 | 0.834674 |

## Biggest Offenders: Slowest Query Patterns

### Slow Pattern 1 (14748e7dcac58cd09e494a662c8410d3)
- Avg runtime: 29,289ms | Max: 39,017ms
- Executions: 50 | Credits: 70.5307
- Users: jordan.lee@company.com, alex.kumar@company.com
- Tables: raw.stripe.payments
```sql
SELECT * FROM RAW.STRIPE.PAYMENTS WHERE CREATED_AT >= DATEADD(DAY, -?, CURRENT_DATE)
```

### Slow Pattern 2 (d20fa52ece04edbd35c5a50e78ba6269)
- Avg runtime: 18,894ms | Max: 24,354ms
- Executions: 55 | Credits: 30.8793
- Users: TABLEAU_SERVICE
- Tables: analytics.sales.dim_customers, analytics.sales.dim_products, analytics.sales.dim_regions, analytics.sales.fact_order_items, analytics.sales.fact_orders
```sql
SELECT O.ORDER_ID, O.ORDER_DATE, O.ORDER_STATUS, O.TOTAL_AMOUNT, C.CUSTOMER_NAME, C.EMAIL, C.CUSTOMER_SEGMENT, R.REGION_NAME, OI.PRODUCT_ID, OI.QUANTITY, OI.UNIT_PRICE, OI.DISCOUNT_AMOUNT, P.PRODUCT_NAME, P.PRODUCT_CATEGORY FROM ANALYTICS.SALES.FACT_ORDERS AS O JOIN ANALYTICS.SALES.DIM_CUSTOMERS AS C ON O.CUSTOMER_ID = C.CUSTOMER_ID JOIN ANALYTICS.SALES.DIM_REGIONS AS R ON O.REGION_ID = R.REGION_ID JOIN ANALYTICS.SALES.FACT_ORDER_ITEMS AS OI ON O.ORDER_ID = OI.ORDER_ID JOIN ANALYTICS.SALES.DIM_PRODUCTS AS P ON OI.PRODUCT_ID = P.PRODUCT_ID WHERE O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE)
```

### Slow Pattern 3 (d02632acc075ffcf4b720a3b772af144)
- Avg runtime: 11,907ms | Max: 16,079ms
- Executions: 43 | Credits: 10.6972
- Users: mike.johnson@company.com, sarah.chen@company.com
- Tables: analytics.sales.dim_customers, analytics.sales.fact_orders
```sql
SELECT C.CUSTOMER_ID, C.CUSTOMER_NAME, C.EMAIL, C.SIGNUP_DATE, C.CUSTOMER_SEGMENT, COUNT(O.ORDER_ID), SUM(O.TOTAL_AMOUNT), AVG(O.TOTAL_AMOUNT), MAX(O.ORDER_DATE), DATEDIFF(DAY, MAX(O.ORDER_DATE), CURRENT_DATE) FROM ANALYTICS.SALES.DIM_CUSTOMERS AS C LEFT JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON C.CUSTOMER_ID = O.CUSTOMER_ID GROUP BY C.CUSTOMER_ID, C.CUSTOMER_NAME, C.EMAIL, C.SIGNUP_DATE, C.CUSTOMER_SEGMENT ORDER BY LIFETIME_VALUE DESC LIMIT ?
```

### Slow Pattern 4 (869547fc4e127f6422543b47093f2cfa)
- Avg runtime: 9,938ms | Max: 17,771ms
- Executions: 4 | Credits: 3.2300
- Users: rachel.thompson@company.com, jordan.lee@company.com, mike.johnson@company.com, DBT_PROD
- Tables: analytics.sales.dim_customers
```sql
SELECT * FROM ANALYTICS.SALES.DIM_CUSTOMERS WHERE CUSTOMER_ID = ?
```

### Slow Pattern 5 (20db487df422a37ef6f58697add2bc0a)
- Avg runtime: 9,911ms | Max: 12,672ms
- Executions: 27 | Credits: 6.1489
- Users: mike.johnson@company.com, sarah.chen@company.com
- Tables: analytics.sales.fact_orders, marketing.public.sessions
```sql
SELECT S.UTM_SOURCE, S.UTM_MEDIUM, S.UTM_CAMPAIGN, COUNT(DISTINCT S.SESSION_ID), COUNT(DISTINCT S.USER_ID), SUM(CASE WHEN S.CONVERTED THEN ? ELSE ? END), CAST(SUM(CASE WHEN S.CONVERTED THEN ? ELSE ? END) AS DOUBLE) / NULLIF(COUNT(DISTINCT S.USER_ID), ?), SUM(O.TOTAL_AMOUNT) FROM MARKETING.PUBLIC.SESSIONS AS S LEFT JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON S.USER_ID = O.CUSTOMER_ID AND O.ORDER_DATE = S.SESSION_DATE WHERE S.SESSION_DATE >= DATEADD(DAY, -?, CURRENT_DATE) GROUP BY S.UTM_SOURCE, S.UTM_MEDIUM, S.UTM_CAMPAIGN ORDER BY ATTRIBUTED_REVENUE DESC NULLS LAST
```

### Slow Pattern 6 (2256f9bc51ab6164b77c9526e87943c5)
- Avg runtime: 8,291ms | Max: 11,448ms
- Executions: 60 | Credits: 10.3139
- Users: LOOKER_SERVICE
- Tables: analytics.sales.dim_products, analytics.sales.fact_order_items, analytics.sales.fact_orders
```sql
SELECT P.PRODUCT_CATEGORY, P.PRODUCT_SUBCATEGORY, DATE_TRUNC('MONTH', O.ORDER_DATE), SUM(OI.QUANTITY), SUM(OI.QUANTITY * OI.UNIT_PRICE), SUM(OI.QUANTITY * (OI.UNIT_PRICE - P.COST_PRICE)), COUNT(DISTINCT O.CUSTOMER_ID) FROM ANALYTICS.SALES.FACT_ORDER_ITEMS AS OI JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON OI.ORDER_ID = O.ORDER_ID JOIN ANALYTICS.SALES.DIM_PRODUCTS AS P ON OI.PRODUCT_ID = P.PRODUCT_ID WHERE O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) GROUP BY P.PRODUCT_CATEGORY, P.PRODUCT_SUBCATEGORY, DATE_TRUNC('MONTH', O.ORDER_DATE) ORDER BY GROSS_REVENUE DESC
```

### Slow Pattern 7 (5b086e309110770bf540b68c2b05cc3c)
- Avg runtime: 6,301ms | Max: 7,970ms
- Executions: 40 | Credits: 4.7806
- Users: LOOKER_SERVICE
- Tables: analytics.product.fact_events
```sql
SELECT EVENT_DATE, EVENT_TYPE, PLATFORM, COUNT(*), COUNT(DISTINCT USER_ID) FROM ANALYTICS.PRODUCT.FACT_EVENTS WHERE EVENT_DATE >= DATEADD(DAY, -?, CURRENT_DATE) AND EVENT_TYPE IN ('?', '?', '?', '?') GROUP BY EVENT_DATE, EVENT_TYPE, PLATFORM ORDER BY EVENT_DATE DESC
```

### Slow Pattern 8 (07aef86a1330b894e352996214eb74fe)
- Avg runtime: 5,539ms | Max: 7,459ms
- Executions: 95 | Credits: 9.3325
- Users: TABLEAU_SERVICE, LOOKER_SERVICE
- Tables: analytics.sales.fact_orders
```sql
SELECT DATE_TRUNC('WEEK', O.ORDER_DATE), COUNT(DISTINCT O.ORDER_ID), COUNT(DISTINCT O.CUSTOMER_ID), SUM(O.TOTAL_AMOUNT), SUM(O.TOTAL_AMOUNT) / NULLIF(COUNT(DISTINCT O.CUSTOMER_ID), ?) FROM ANALYTICS.SALES.FACT_ORDERS AS O WHERE O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) AND O.ORDER_STATUS = '?' GROUP BY DATE_TRUNC('WEEK', O.ORDER_DATE) ORDER BY WEEK DESC
```

### Slow Pattern 9 (4bcbda3cbc240f999072b2b279669bbb)
- Avg runtime: 4,581ms | Max: 6,121ms
- Executions: 155 | Credits: 11.5876
- Users: TABLEAU_SERVICE, LOOKER_SERVICE
- Tables: analytics.sales.dim_regions, analytics.sales.fact_orders
```sql
SELECT R.REGION_NAME, DATE_TRUNC('DAY', O.ORDER_DATE), SUM(O.TOTAL_AMOUNT), COUNT(DISTINCT O.CUSTOMER_ID), COUNT(*) FROM ANALYTICS.SALES.FACT_ORDERS AS O JOIN ANALYTICS.SALES.DIM_REGIONS AS R ON O.REGION_ID = R.REGION_ID WHERE O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) AND O.ORDER_STATUS = '?' GROUP BY R.REGION_NAME, DATE_TRUNC('DAY', O.ORDER_DATE) ORDER BY DAY DESC, DAILY_REVENUE DESC
```

## Biggest Offenders: Most Data Scanned

### Heavy Scan 1 (14748e7dcac58cd09e494a662c8410d3)
- Avg runtime: 29,289ms
- Executions: 50 | Credits: 70.5307
- Users: alex.kumar@company.com, jordan.lee@company.com
- Tables: raw.stripe.payments
```sql
SELECT * FROM RAW.STRIPE.PAYMENTS WHERE CREATED_AT >= DATEADD(DAY, -?, CURRENT_DATE)
```

### Heavy Scan 2 (d20fa52ece04edbd35c5a50e78ba6269)
- Avg runtime: 18,894ms
- Executions: 55 | Credits: 30.8793
- Users: TABLEAU_SERVICE
- Tables: analytics.sales.dim_customers, analytics.sales.dim_products, analytics.sales.dim_regions, analytics.sales.fact_order_items, analytics.sales.fact_orders
```sql
SELECT O.ORDER_ID, O.ORDER_DATE, O.ORDER_STATUS, O.TOTAL_AMOUNT, C.CUSTOMER_NAME, C.EMAIL, C.CUSTOMER_SEGMENT, R.REGION_NAME, OI.PRODUCT_ID, OI.QUANTITY, OI.UNIT_PRICE, OI.DISCOUNT_AMOUNT, P.PRODUCT_NAME, P.PRODUCT_CATEGORY FROM ANALYTICS.SALES.FACT_ORDERS AS O JOIN ANALYTICS.SALES.DIM_CUSTOMERS AS C ON O.CUSTOMER_ID = C.CUSTOMER_ID JOIN ANALYTICS.SALES.DIM_REGIONS AS R ON O.REGION_ID = R.REGION_ID JOIN ANALYTICS.SALES.FACT_ORDER_ITEMS AS OI ON O.ORDER_ID = OI.ORDER_ID JOIN ANALYTICS.SALES.DIM_PRODUCTS AS P ON OI.PRODUCT_ID = P.PRODUCT_ID WHERE O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE)
```

### Heavy Scan 3 (d02632acc075ffcf4b720a3b772af144)
- Avg runtime: 11,907ms
- Executions: 43 | Credits: 10.6972
- Users: sarah.chen@company.com, mike.johnson@company.com
- Tables: analytics.sales.dim_customers, analytics.sales.fact_orders
```sql
SELECT C.CUSTOMER_ID, C.CUSTOMER_NAME, C.EMAIL, C.SIGNUP_DATE, C.CUSTOMER_SEGMENT, COUNT(O.ORDER_ID), SUM(O.TOTAL_AMOUNT), AVG(O.TOTAL_AMOUNT), MAX(O.ORDER_DATE), DATEDIFF(DAY, MAX(O.ORDER_DATE), CURRENT_DATE) FROM ANALYTICS.SALES.DIM_CUSTOMERS AS C LEFT JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON C.CUSTOMER_ID = O.CUSTOMER_ID GROUP BY C.CUSTOMER_ID, C.CUSTOMER_NAME, C.EMAIL, C.SIGNUP_DATE, C.CUSTOMER_SEGMENT ORDER BY LIFETIME_VALUE DESC LIMIT ?
```

### Heavy Scan 4 (4bcbda3cbc240f999072b2b279669bbb)
- Avg runtime: 4,581ms
- Executions: 155 | Credits: 11.5876
- Users: TABLEAU_SERVICE, LOOKER_SERVICE
- Tables: analytics.sales.dim_regions, analytics.sales.fact_orders
```sql
SELECT R.REGION_NAME, DATE_TRUNC('DAY', O.ORDER_DATE), SUM(O.TOTAL_AMOUNT), COUNT(DISTINCT O.CUSTOMER_ID), COUNT(*) FROM ANALYTICS.SALES.FACT_ORDERS AS O JOIN ANALYTICS.SALES.DIM_REGIONS AS R ON O.REGION_ID = R.REGION_ID WHERE O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) AND O.ORDER_STATUS = '?' GROUP BY R.REGION_NAME, DATE_TRUNC('DAY', O.ORDER_DATE) ORDER BY DAY DESC, DAILY_REVENUE DESC
```

### Heavy Scan 5 (2256f9bc51ab6164b77c9526e87943c5)
- Avg runtime: 8,291ms
- Executions: 60 | Credits: 10.3139
- Users: LOOKER_SERVICE
- Tables: analytics.sales.dim_products, analytics.sales.fact_order_items, analytics.sales.fact_orders
```sql
SELECT P.PRODUCT_CATEGORY, P.PRODUCT_SUBCATEGORY, DATE_TRUNC('MONTH', O.ORDER_DATE), SUM(OI.QUANTITY), SUM(OI.QUANTITY * OI.UNIT_PRICE), SUM(OI.QUANTITY * (OI.UNIT_PRICE - P.COST_PRICE)), COUNT(DISTINCT O.CUSTOMER_ID) FROM ANALYTICS.SALES.FACT_ORDER_ITEMS AS OI JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON OI.ORDER_ID = O.ORDER_ID JOIN ANALYTICS.SALES.DIM_PRODUCTS AS P ON OI.PRODUCT_ID = P.PRODUCT_ID WHERE O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) GROUP BY P.PRODUCT_CATEGORY, P.PRODUCT_SUBCATEGORY, DATE_TRUNC('MONTH', O.ORDER_DATE) ORDER BY GROSS_REVENUE DESC
```

### Heavy Scan 6 (07aef86a1330b894e352996214eb74fe)
- Avg runtime: 5,539ms
- Executions: 95 | Credits: 9.3325
- Users: TABLEAU_SERVICE, LOOKER_SERVICE
- Tables: analytics.sales.fact_orders
```sql
SELECT DATE_TRUNC('WEEK', O.ORDER_DATE), COUNT(DISTINCT O.ORDER_ID), COUNT(DISTINCT O.CUSTOMER_ID), SUM(O.TOTAL_AMOUNT), SUM(O.TOTAL_AMOUNT) / NULLIF(COUNT(DISTINCT O.CUSTOMER_ID), ?) FROM ANALYTICS.SALES.FACT_ORDERS AS O WHERE O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) AND O.ORDER_STATUS = '?' GROUP BY DATE_TRUNC('WEEK', O.ORDER_DATE) ORDER BY WEEK DESC
```

### Heavy Scan 7 (869547fc4e127f6422543b47093f2cfa)
- Avg runtime: 9,938ms
- Executions: 4 | Credits: 3.2300
- Users: jordan.lee@company.com, rachel.thompson@company.com, mike.johnson@company.com, DBT_PROD
- Tables: analytics.sales.dim_customers
```sql
SELECT * FROM ANALYTICS.SALES.DIM_CUSTOMERS WHERE CUSTOMER_ID = ?
```

### Heavy Scan 8 (20db487df422a37ef6f58697add2bc0a)
- Avg runtime: 9,911ms
- Executions: 27 | Credits: 6.1489
- Users: mike.johnson@company.com, sarah.chen@company.com
- Tables: analytics.sales.fact_orders, marketing.public.sessions
```sql
SELECT S.UTM_SOURCE, S.UTM_MEDIUM, S.UTM_CAMPAIGN, COUNT(DISTINCT S.SESSION_ID), COUNT(DISTINCT S.USER_ID), SUM(CASE WHEN S.CONVERTED THEN ? ELSE ? END), CAST(SUM(CASE WHEN S.CONVERTED THEN ? ELSE ? END) AS DOUBLE) / NULLIF(COUNT(DISTINCT S.USER_ID), ?), SUM(O.TOTAL_AMOUNT) FROM MARKETING.PUBLIC.SESSIONS AS S LEFT JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON S.USER_ID = O.CUSTOMER_ID AND O.ORDER_DATE = S.SESSION_DATE WHERE S.SESSION_DATE >= DATEADD(DAY, -?, CURRENT_DATE) GROUP BY S.UTM_SOURCE, S.UTM_MEDIUM, S.UTM_CAMPAIGN ORDER BY ATTRIBUTED_REVENUE DESC NULLS LAST
```

### Heavy Scan 9 (5b086e309110770bf540b68c2b05cc3c)
- Avg runtime: 6,301ms
- Executions: 40 | Credits: 4.7806
- Users: LOOKER_SERVICE
- Tables: analytics.product.fact_events
```sql
SELECT EVENT_DATE, EVENT_TYPE, PLATFORM, COUNT(*), COUNT(DISTINCT USER_ID) FROM ANALYTICS.PRODUCT.FACT_EVENTS WHERE EVENT_DATE >= DATEADD(DAY, -?, CURRENT_DATE) AND EVENT_TYPE IN ('?', '?', '?', '?') GROUP BY EVENT_DATE, EVENT_TYPE, PLATFORM ORDER BY EVENT_DATE DESC
```

---

## Top Query Patterns by Impact

### Pattern 1 (fingerprint: 14748e7dcac58cd09e494a662c8410d3)

- Executions: 50
- Users: alex.kumar@company.com, jordan.lee@company.com
- Roles: DATA_ENGINEER
- Warehouses: WH_ETL_L
- Total credits: 70.5307
- Avg execution time: 29289ms
- Total bytes scanned: 83,376,471,606
- Tables: raw.stripe.payments
- First seen: 2026-04-08 07:18:01
- Last seen: 2026-04-14 21:33:22
- Impact score: 3526.5369

```sql
SELECT * FROM RAW.STRIPE.PAYMENTS WHERE CREATED_AT >= DATEADD(DAY, -?, CURRENT_DATE)
```

### Pattern 2 (fingerprint: 4bcbda3cbc240f999072b2b279669bbb)

- Executions: 155
- Users: LOOKER_SERVICE, TABLEAU_SERVICE
- Roles: TABLEAU_ROLE, LOOKER_ROLE
- Warehouses: WH_LOOKER, WH_TABLEAU
- Total credits: 11.5876
- Avg execution time: 4581ms
- Total bytes scanned: 13,507,492,288
- Tables: analytics.sales.dim_regions, analytics.sales.fact_orders
- First seen: 2026-04-08 06:59:19
- Last seen: 2026-04-14 21:55:09
- Impact score: 1796.0774

```sql
SELECT R.REGION_NAME, DATE_TRUNC('DAY', O.ORDER_DATE), SUM(O.TOTAL_AMOUNT), COUNT(DISTINCT O.CUSTOMER_ID), COUNT(*) FROM ANALYTICS.SALES.FACT_ORDERS AS O JOIN ANALYTICS.SALES.DIM_REGIONS AS R ON O.REGION_ID = R.REGION_ID WHERE O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) AND O.ORDER_STATUS = '?' GROUP BY R.REGION_NAME, DATE_TRUNC('DAY', O.ORDER_DATE) ORDER BY DAY DESC, DAILY_REVENUE DESC
```

### Pattern 3 (fingerprint: d20fa52ece04edbd35c5a50e78ba6269)

- Executions: 55
- Users: TABLEAU_SERVICE
- Roles: TABLEAU_ROLE
- Warehouses: WH_TABLEAU
- Total credits: 30.8793
- Avg execution time: 18894ms
- Total bytes scanned: 45,505,653,074
- Tables: analytics.sales.dim_customers, analytics.sales.dim_products, analytics.sales.dim_regions, analytics.sales.fact_order_items, analytics.sales.fact_orders
- First seen: 2026-04-08 06:06:16
- Last seen: 2026-04-14 19:17:33
- Impact score: 1698.3623

```sql
SELECT O.ORDER_ID, O.ORDER_DATE, O.ORDER_STATUS, O.TOTAL_AMOUNT, C.CUSTOMER_NAME, C.EMAIL, C.CUSTOMER_SEGMENT, R.REGION_NAME, OI.PRODUCT_ID, OI.QUANTITY, OI.UNIT_PRICE, OI.DISCOUNT_AMOUNT, P.PRODUCT_NAME, P.PRODUCT_CATEGORY FROM ANALYTICS.SALES.FACT_ORDERS AS O JOIN ANALYTICS.SALES.DIM_CUSTOMERS AS C ON O.CUSTOMER_ID = C.CUSTOMER_ID JOIN ANALYTICS.SALES.DIM_REGIONS AS R ON O.REGION_ID = R.REGION_ID JOIN ANALYTICS.SALES.FACT_ORDER_ITEMS AS OI ON O.ORDER_ID = OI.ORDER_ID JOIN ANALYTICS.SALES.DIM_PRODUCTS AS P ON OI.PRODUCT_ID = P.PRODUCT_ID WHERE O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE)
```

### Pattern 4 (fingerprint: 07aef86a1330b894e352996214eb74fe)

- Executions: 95
- Users: TABLEAU_SERVICE, LOOKER_SERVICE
- Roles: LOOKER_ROLE, TABLEAU_ROLE
- Warehouses: WH_TABLEAU, WH_LOOKER
- Total credits: 9.3325
- Avg execution time: 5539ms
- Total bytes scanned: 11,533,850,307
- Tables: analytics.sales.fact_orders
- First seen: 2026-04-08 06:19:28
- Last seen: 2026-04-14 21:45:36
- Impact score: 886.5870

```sql
SELECT DATE_TRUNC('WEEK', O.ORDER_DATE), COUNT(DISTINCT O.ORDER_ID), COUNT(DISTINCT O.CUSTOMER_ID), SUM(O.TOTAL_AMOUNT), SUM(O.TOTAL_AMOUNT) / NULLIF(COUNT(DISTINCT O.CUSTOMER_ID), ?) FROM ANALYTICS.SALES.FACT_ORDERS AS O WHERE O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) AND O.ORDER_STATUS = '?' GROUP BY DATE_TRUNC('WEEK', O.ORDER_DATE) ORDER BY WEEK DESC
```

### Pattern 5 (fingerprint: 2256f9bc51ab6164b77c9526e87943c5)

- Executions: 60
- Users: LOOKER_SERVICE
- Roles: LOOKER_ROLE
- Warehouses: WH_LOOKER
- Total credits: 10.3139
- Avg execution time: 8291ms
- Total bytes scanned: 13,180,786,485
- Tables: analytics.sales.dim_products, analytics.sales.fact_order_items, analytics.sales.fact_orders
- First seen: 2026-04-08 09:53:57
- Last seen: 2026-04-14 20:14:34
- Impact score: 618.8361

```sql
SELECT P.PRODUCT_CATEGORY, P.PRODUCT_SUBCATEGORY, DATE_TRUNC('MONTH', O.ORDER_DATE), SUM(OI.QUANTITY), SUM(OI.QUANTITY * OI.UNIT_PRICE), SUM(OI.QUANTITY * (OI.UNIT_PRICE - P.COST_PRICE)), COUNT(DISTINCT O.CUSTOMER_ID) FROM ANALYTICS.SALES.FACT_ORDER_ITEMS AS OI JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON OI.ORDER_ID = O.ORDER_ID JOIN ANALYTICS.SALES.DIM_PRODUCTS AS P ON OI.PRODUCT_ID = P.PRODUCT_ID WHERE O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) GROUP BY P.PRODUCT_CATEGORY, P.PRODUCT_SUBCATEGORY, DATE_TRUNC('MONTH', O.ORDER_DATE) ORDER BY GROSS_REVENUE DESC
```

### Pattern 6 (fingerprint: d02632acc075ffcf4b720a3b772af144)

- Executions: 43
- Users: mike.johnson@company.com, sarah.chen@company.com
- Roles: ANALYST
- Warehouses: WH_ANALYTICS_M
- Total credits: 10.6972
- Avg execution time: 11907ms
- Total bytes scanned: 15,648,327,074
- Tables: analytics.sales.dim_customers, analytics.sales.fact_orders
- First seen: 2026-04-08 15:45:32
- Last seen: 2026-04-14 15:55:34
- Impact score: 459.9787

```sql
SELECT C.CUSTOMER_ID, C.CUSTOMER_NAME, C.EMAIL, C.SIGNUP_DATE, C.CUSTOMER_SEGMENT, COUNT(O.ORDER_ID), SUM(O.TOTAL_AMOUNT), AVG(O.TOTAL_AMOUNT), MAX(O.ORDER_DATE), DATEDIFF(DAY, MAX(O.ORDER_DATE), CURRENT_DATE) FROM ANALYTICS.SALES.DIM_CUSTOMERS AS C LEFT JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON C.CUSTOMER_ID = O.CUSTOMER_ID GROUP BY C.CUSTOMER_ID, C.CUSTOMER_NAME, C.EMAIL, C.SIGNUP_DATE, C.CUSTOMER_SEGMENT ORDER BY LIFETIME_VALUE DESC LIMIT ?
```

### Pattern 7 (fingerprint: 5b086e309110770bf540b68c2b05cc3c)

- Executions: 40
- Users: LOOKER_SERVICE
- Roles: LOOKER_ROLE
- Warehouses: WH_LOOKER
- Total credits: 4.7806
- Avg execution time: 6301ms
- Total bytes scanned: 7,195,969,663
- Tables: analytics.product.fact_events
- First seen: 2026-04-08 10:44:46
- Last seen: 2026-04-14 19:51:00
- Impact score: 191.2260

```sql
SELECT EVENT_DATE, EVENT_TYPE, PLATFORM, COUNT(*), COUNT(DISTINCT USER_ID) FROM ANALYTICS.PRODUCT.FACT_EVENTS WHERE EVENT_DATE >= DATEADD(DAY, -?, CURRENT_DATE) AND EVENT_TYPE IN ('?', '?', '?', '?') GROUP BY EVENT_DATE, EVENT_TYPE, PLATFORM ORDER BY EVENT_DATE DESC
```

### Pattern 8 (fingerprint: 20db487df422a37ef6f58697add2bc0a)

- Executions: 27
- Users: sarah.chen@company.com, mike.johnson@company.com
- Roles: ANALYST
- Warehouses: WH_ANALYTICS_M
- Total credits: 6.1489
- Avg execution time: 9911ms
- Total bytes scanned: 7,801,609,143
- Tables: analytics.sales.fact_orders, marketing.public.sessions
- First seen: 2026-04-08 07:00:36
- Last seen: 2026-04-14 20:31:02
- Impact score: 166.0211

```sql
SELECT S.UTM_SOURCE, S.UTM_MEDIUM, S.UTM_CAMPAIGN, COUNT(DISTINCT S.SESSION_ID), COUNT(DISTINCT S.USER_ID), SUM(CASE WHEN S.CONVERTED THEN ? ELSE ? END), CAST(SUM(CASE WHEN S.CONVERTED THEN ? ELSE ? END) AS DOUBLE) / NULLIF(COUNT(DISTINCT S.USER_ID), ?), SUM(O.TOTAL_AMOUNT) FROM MARKETING.PUBLIC.SESSIONS AS S LEFT JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON S.USER_ID = O.CUSTOMER_ID AND O.ORDER_DATE = S.SESSION_DATE WHERE S.SESSION_DATE >= DATEADD(DAY, -?, CURRENT_DATE) GROUP BY S.UTM_SOURCE, S.UTM_MEDIUM, S.UTM_CAMPAIGN ORDER BY ATTRIBUTED_REVENUE DESC NULLS LAST
```

### Pattern 9 (fingerprint: 869547fc4e127f6422543b47093f2cfa)

- Executions: 4
- Users: rachel.thompson@company.com, mike.johnson@company.com, DBT_PROD, jordan.lee@company.com
- Roles: DBT_ROLE, ANALYST, MANAGER, DATA_ENGINEER
- Warehouses: WH_ANALYTICS_S, WH_ANALYTICS_M, WH_ETL_L, WH_DBT
- Total credits: 3.2300
- Avg execution time: 9938ms
- Total bytes scanned: 9,071,677,286
- Tables: analytics.sales.dim_customers
- First seen: 2026-04-08 13:44:14
- Last seen: 2026-04-14 19:59:47
- Impact score: 12.9200

```sql
SELECT * FROM ANALYTICS.SALES.DIM_CUSTOMERS WHERE CUSTOMER_ID = ?
```

### Pattern 10 (fingerprint: cbde4da74e13d4f827386efeb1886811)

- Executions: 1
- Users: emma.davis@company.com
- Roles: DATA_SCIENTIST
- Warehouses: WH_DS_2XL
- Total credits: 7.4610
- Avg execution time: 104453ms
- Total bytes scanned: 5,424,923,241
- Tables: analytics.sales.dim_customers, analytics.sales.fact_orders
- First seen: 2026-04-09 13:11:04
- Last seen: 2026-04-09 13:11:04
- Impact score: 7.4610

```sql
SELECT MIN(O.TOTAL_AMOUNT), COUNT(O.ORDER_ID), C.CUSTOMER_ID, STDDEV(O.TOTAL_AMOUNT), AVG(O.TOTAL_AMOUNT), C.CUSTOMER_SEGMENT FROM ANALYTICS.SALES.DIM_CUSTOMERS AS C LEFT JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON C.CUSTOMER_ID = O.CUSTOMER_ID AND O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) GROUP BY C.CUSTOMER_ID, C.CUSTOMER_SEGMENT
```

### Pattern 11 (fingerprint: 6897ee239d382927173c76d7d8bff8b3)

- Executions: 1
- Users: noah.martinez@company.com
- Roles: DATA_SCIENTIST
- Warehouses: WH_DS_XL
- Total credits: 7.2117
- Avg execution time: 100964ms
- Total bytes scanned: 4,365,328,799
- Tables: analytics.sales.dim_customers, analytics.sales.fact_orders
- First seen: 2026-04-08 11:01:17
- Last seen: 2026-04-08 11:01:17
- Impact score: 7.2117

```sql
SELECT C.CUSTOMER_SEGMENT, DATEDIFF(DAY, C.SIGNUP_DATE, CURRENT_DATE), C.CUSTOMER_ID, SUM(O.TOTAL_AMOUNT), SUM(CASE WHEN O.ORDER_STATUS = '?' THEN ? ELSE ? END), AVG(O.TOTAL_AMOUNT), MAX(O.TOTAL_AMOUNT), MIN(O.TOTAL_AMOUNT), COUNT(DISTINCT DATE_TRUNC('WEEK', O.ORDER_DATE)), COUNT(DISTINCT O.REGION_ID), STDDEV(O.TOTAL_AMOUNT) FROM ANALYTICS.SALES.DIM_CUSTOMERS AS C LEFT JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON C.CUSTOMER_ID = O.CUSTOMER_ID AND O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) GROUP BY C.CUSTOMER_SEGMENT, C.CUSTOMER_ID
```

### Pattern 12 (fingerprint: 78dc3723cea6a6a57b9c552e8c10b1a1)

- Executions: 1
- Users: emma.davis@company.com
- Roles: DATA_SCIENTIST
- Warehouses: WH_DS_XL
- Total credits: 6.2590
- Avg execution time: 87625ms
- Total bytes scanned: 2,655,858,999
- Tables: analytics.sales.dim_customers, analytics.sales.fact_orders
- First seen: 2026-04-09 15:09:47
- Last seen: 2026-04-09 15:09:47
- Impact score: 6.2590

```sql
SELECT STDDEV(O.TOTAL_AMOUNT), C.CUSTOMER_ID, MAX(O.TOTAL_AMOUNT), COUNT(DISTINCT DATE_TRUNC('WEEK', O.ORDER_DATE)), AVG(O.TOTAL_AMOUNT), C.CUSTOMER_SEGMENT FROM ANALYTICS.SALES.DIM_CUSTOMERS AS C LEFT JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON C.CUSTOMER_ID = O.CUSTOMER_ID AND O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) GROUP BY C.CUSTOMER_ID, C.CUSTOMER_SEGMENT
```

### Pattern 13 (fingerprint: 5c2b1530b182e33ec870c37fb3fd1731)

- Executions: 1
- Users: noah.martinez@company.com
- Roles: DATA_SCIENTIST
- Warehouses: WH_DS_XL
- Total credits: 5.5013
- Avg execution time: 77018ms
- Total bytes scanned: 410,363,731
- Tables: analytics.sales.dim_customers, analytics.sales.fact_orders
- First seen: 2026-04-12 07:18:27
- Last seen: 2026-04-12 07:18:27
- Impact score: 5.5013

```sql
SELECT COUNT(DISTINCT DATE_TRUNC('WEEK', O.ORDER_DATE)), MIN(O.TOTAL_AMOUNT), COUNT(DISTINCT O.REGION_ID), C.CUSTOMER_ID, SUM(CASE WHEN O.ORDER_STATUS = '?' THEN ? ELSE ? END), COUNT(O.ORDER_ID), C.CUSTOMER_SEGMENT, STDDEV(O.TOTAL_AMOUNT), AVG(O.TOTAL_AMOUNT), SUM(O.TOTAL_AMOUNT), DATEDIFF(DAY, C.SIGNUP_DATE, CURRENT_DATE) FROM ANALYTICS.SALES.DIM_CUSTOMERS AS C LEFT JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON C.CUSTOMER_ID = O.CUSTOMER_ID AND O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) GROUP BY C.CUSTOMER_ID, C.CUSTOMER_SEGMENT
```

### Pattern 14 (fingerprint: cb50993433859c376bda1edf694f6ebb)

- Executions: 1
- Users: emma.davis@company.com
- Roles: DATA_SCIENTIST
- Warehouses: WH_DS_XL
- Total credits: 5.0141
- Avg execution time: 70196ms
- Total bytes scanned: 1,500,847,370
- Tables: analytics.sales.dim_customers, analytics.sales.fact_orders
- First seen: 2026-04-13 18:54:58
- Last seen: 2026-04-13 18:54:58
- Impact score: 5.0141

```sql
SELECT SUM(O.TOTAL_AMOUNT), AVG(O.TOTAL_AMOUNT), COUNT(DISTINCT O.REGION_ID), MAX(O.TOTAL_AMOUNT), COUNT(DISTINCT DATE_TRUNC('WEEK', O.ORDER_DATE)), STDDEV(O.TOTAL_AMOUNT), MIN(O.TOTAL_AMOUNT), COUNT(O.ORDER_ID), C.CUSTOMER_ID, C.CUSTOMER_SEGMENT, DATEDIFF(DAY, C.SIGNUP_DATE, CURRENT_DATE), SUM(CASE WHEN O.ORDER_STATUS = '?' THEN ? ELSE ? END) FROM ANALYTICS.SALES.DIM_CUSTOMERS AS C LEFT JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON C.CUSTOMER_ID = O.CUSTOMER_ID AND O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) GROUP BY C.CUSTOMER_ID, C.CUSTOMER_SEGMENT
```

### Pattern 15 (fingerprint: 1fb1bdccae5afdaac558df5a865b3c62)

- Executions: 2
- Users: taylor.smith@company.com, mike.johnson@company.com
- Roles: DATA_ENGINEER, ANALYST
- Warehouses: WH_ETL_XL, WH_ANALYTICS_M
- Total credits: 2.4262
- Avg execution time: 25272ms
- Total bytes scanned: 10,268,162,028
- Tables: raw.stripe.payments
- First seen: 2026-04-13 07:13:14
- Last seen: 2026-04-14 06:31:32
- Impact score: 4.8525

```sql
SELECT * FROM RAW.STRIPE.PAYMENTS WHERE CREATED_AT >= '?'
```

### Pattern 16 (fingerprint: 75c88fc4505645b96315b415292b7f73)

- Executions: 1
- Users: emma.davis@company.com
- Roles: DATA_SCIENTIST
- Warehouses: WH_DS_2XL
- Total credits: 3.7552
- Avg execution time: 52572ms
- Total bytes scanned: 2,741,071,498
- Tables: analytics.sales.dim_customers, analytics.sales.fact_orders
- First seen: 2026-04-13 18:20:31
- Last seen: 2026-04-13 18:20:31
- Impact score: 3.7552

```sql
SELECT MIN(O.TOTAL_AMOUNT), SUM(CASE WHEN O.ORDER_STATUS = '?' THEN ? ELSE ? END), COUNT(DISTINCT DATE_TRUNC('WEEK', O.ORDER_DATE)), AVG(O.TOTAL_AMOUNT), C.CUSTOMER_SEGMENT, STDDEV(O.TOTAL_AMOUNT) FROM ANALYTICS.SALES.DIM_CUSTOMERS AS C LEFT JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON C.CUSTOMER_ID = O.CUSTOMER_ID AND O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) GROUP BY C.CUSTOMER_SEGMENT
```

### Pattern 17 (fingerprint: 4efba2d371e6170e8530ef681e6b2dce)

- Executions: 1
- Users: noah.martinez@company.com
- Roles: DATA_SCIENTIST
- Warehouses: WH_DS_XL
- Total credits: 3.6855
- Avg execution time: 51597ms
- Total bytes scanned: 5,839,815,186
- Tables: analytics.sales.dim_customers, analytics.sales.fact_orders
- First seen: 2026-04-14 14:14:46
- Last seen: 2026-04-14 14:14:46
- Impact score: 3.6855

```sql
SELECT C.CUSTOMER_SEGMENT, COUNT(DISTINCT DATE_TRUNC('WEEK', O.ORDER_DATE)), MAX(O.TOTAL_AMOUNT), COUNT(O.ORDER_ID), MIN(O.TOTAL_AMOUNT), SUM(CASE WHEN O.ORDER_STATUS = '?' THEN ? ELSE ? END), STDDEV(O.TOTAL_AMOUNT), C.CUSTOMER_ID, SUM(O.TOTAL_AMOUNT) FROM ANALYTICS.SALES.DIM_CUSTOMERS AS C LEFT JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON C.CUSTOMER_ID = O.CUSTOMER_ID AND O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) GROUP BY C.CUSTOMER_SEGMENT, C.CUSTOMER_ID
```

### Pattern 18 (fingerprint: 7797ac41583caa401c0e2bcf153ee151)

- Executions: 1
- Users: alex.kumar@company.com
- Roles: DATA_ENGINEER
- Warehouses: WH_ETL_XL
- Total credits: 3.3116
- Avg execution time: 68991ms
- Total bytes scanned: 1,195,085,519
- Tables: raw.stripe.payments
- First seen: 2026-04-11 09:09:41
- Last seen: 2026-04-11 09:09:41
- Impact score: 3.3116

```sql
SELECT FAILURE_MESSAGE, FAILURE_CODE, METADATA, CUSTOMER_ID, RECEIPT_URL, FEE_AMOUNT, NET_AMOUNT, DESCRIPTION, PAYMENT_ID, PAYMENT_STATUS, UPDATED_AT FROM RAW.STRIPE.PAYMENTS WHERE CREATED_AT >= '?' AND PAYMENT_STATUS = '?' AND AMOUNT > ?
```

### Pattern 19 (fingerprint: 9425f0802ac3c63a89204e7039879562)

- Executions: 1
- Users: noah.martinez@company.com
- Roles: DATA_SCIENTIST
- Warehouses: WH_DS_XL
- Total credits: 3.2678
- Avg execution time: 45749ms
- Total bytes scanned: 4,085,232,588
- Tables: analytics.sales.dim_customers, analytics.sales.fact_orders
- First seen: 2026-04-09 10:32:14
- Last seen: 2026-04-09 10:32:14
- Impact score: 3.2678

```sql
SELECT SUM(CASE WHEN O.ORDER_STATUS = '?' THEN ? ELSE ? END), AVG(O.TOTAL_AMOUNT), C.CUSTOMER_SEGMENT, MAX(O.TOTAL_AMOUNT), COUNT(DISTINCT O.REGION_ID), STDDEV(O.TOTAL_AMOUNT), MIN(O.TOTAL_AMOUNT), C.CUSTOMER_ID, COUNT(DISTINCT DATE_TRUNC('WEEK', O.ORDER_DATE)), DATEDIFF(DAY, C.SIGNUP_DATE, CURRENT_DATE), COUNT(O.ORDER_ID) FROM ANALYTICS.SALES.DIM_CUSTOMERS AS C LEFT JOIN ANALYTICS.SALES.FACT_ORDERS AS O ON C.CUSTOMER_ID = O.CUSTOMER_ID AND O.ORDER_DATE >= DATEADD(DAY, -?, CURRENT_DATE) GROUP BY C.CUSTOMER_SEGMENT, C.CUSTOMER_ID
```

### Pattern 20 (fingerprint: 5ee11407e8eb0ff85abad02770d81a1d)

- Executions: 1
- Users: mike.johnson@company.com
- Roles: ANALYST
- Warehouses: WH_ANALYTICS_M
- Total credits: 3.2044
- Avg execution time: 66758ms
- Total bytes scanned: 1,051,941,341
- Tables: raw.stripe.payments
- First seen: 2026-04-09 14:07:20
- Last seen: 2026-04-09 14:07:20
- Impact score: 3.2044

```sql
SELECT FEE_AMOUNT, CREATED_AT, NET_AMOUNT, PAYMENT_METHOD, AMOUNT, STRIPE_CHARGE_ID, PAYMENT_ID, DESCRIPTION, PAYMENT_STATUS, CUSTOMER_ID FROM RAW.STRIPE.PAYMENTS WHERE CREATED_AT >= '?' AND PAYMENT_STATUS = '?'
```

### Pattern 21 (fingerprint: 5ff34aa910621527ed9532e90a598566)

- Executions: 1
- Users: alex.kumar@company.com
- Roles: DATA_ENGINEER
- Warehouses: WH_ETL_XL
- Total credits: 3.0864
- Avg execution time: 64299ms
- Total bytes scanned: 4,074,673,576
- Tables: raw.stripe.payments
- First seen: 2026-04-12 18:19:40
- Last seen: 2026-04-12 18:19:40
- Impact score: 3.0864

```sql
SELECT STRIPE_CHARGE_ID, FAILURE_MESSAGE, METADATA, AMOUNT, PAYMENT_METHOD, UPDATED_AT, DESCRIPTION FROM RAW.STRIPE.PAYMENTS WHERE CREATED_AT >= '?' AND AMOUNT > ?
```

### Pattern 22 (fingerprint: 9298f0a9697d8fb34949a446e23868c2)

- Executions: 1
- Users: taylor.smith@company.com
- Roles: DATA_ENGINEER
- Warehouses: WH_ETL_XL
- Total credits: 2.8392
- Avg execution time: 59150ms
- Total bytes scanned: 3,863,372,101
- Tables: raw.stripe.payments
- First seen: 2026-04-10 17:26:22
- Last seen: 2026-04-10 17:26:22
- Impact score: 2.8392

```sql
SELECT NET_AMOUNT, PAYMENT_ID, FAILURE_MESSAGE, FEE_AMOUNT, FAILURE_CODE, AMOUNT, PAYMENT_METHOD, METADATA FROM RAW.STRIPE.PAYMENTS WHERE CREATED_AT >= '?'
```

### Pattern 23 (fingerprint: f1a5873495feb7a987e6c125f64c7d9e)

- Executions: 1
- Users: mike.johnson@company.com
- Roles: ANALYST
- Warehouses: WH_ANALYTICS_M
- Total credits: 1.8506
- Avg execution time: 38554ms
- Total bytes scanned: 4,228,500,129
- Tables: raw.stripe.payments
- First seen: 2026-04-12 09:20:23
- Last seen: 2026-04-12 09:20:23
- Impact score: 1.8506

```sql
SELECT STRIPE_CHARGE_ID, CREATED_AT, CURRENCY, METADATA, FEE_AMOUNT, AMOUNT, PAYMENT_ID, RECEIPT_URL, FAILURE_MESSAGE, FAILURE_CODE, PAYMENT_STATUS, DESCRIPTION, NET_AMOUNT, CUSTOMER_ID, PAYMENT_METHOD, UPDATED_AT FROM RAW.STRIPE.PAYMENTS WHERE CREATED_AT >= '?'
```

### Pattern 24 (fingerprint: 48fc918a1f5db0b2b93bb109cc6d3de4)

- Executions: 1
- Users: ceo@company.com
- Roles: EXECUTIVE
- Warehouses: WH_ANALYTICS_S
- Total credits: 1.8223
- Avg execution time: 22428ms
- Total bytes scanned: 1,810,242,451
- Tables: analytics.sales.dim_customers
- First seen: 2026-04-08 17:54:27
- Last seen: 2026-04-08 17:54:27
- Impact score: 1.8223

```sql
SELECT PHONE_NUMBER, BILLING_ADDRESS, UPDATED_AT, LIFETIME_VALUE, SHIPPING_ADDRESS, SIGNUP_DATE, EMAIL, PREFERRED_CHANNEL, ACCOUNT_STATUS, CUSTOMER_ID, CREATED_AT FROM ANALYTICS.SALES.DIM_CUSTOMERS WHERE CUSTOMER_ID = ?
```

### Pattern 25 (fingerprint: 4073bcae988fec63f1c9c5cc5a2d0c56)

- Executions: 1
- Users: DBT_PROD
- Roles: DBT_ROLE
- Warehouses: WH_DBT
- Total credits: 1.7432
- Avg execution time: 21454ms
- Total bytes scanned: 1,767,953,982
- Tables: analytics.sales.dim_customers
- First seen: 2026-04-14 18:14:16
- Last seen: 2026-04-14 18:14:16
- Impact score: 1.7432

```sql
SELECT CREATED_AT, PHONE_NUMBER, CUSTOMER_ID, PREFERRED_CHANNEL, CUSTOMER_SEGMENT, LIFETIME_VALUE, BILLING_ADDRESS FROM ANALYTICS.SALES.DIM_CUSTOMERS WHERE CUSTOMER_ID = ?
```
