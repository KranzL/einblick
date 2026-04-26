import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "src"))

from sqlscout.aggregator import aggregate, export_json, export_markdown_summary
from sqlscout.models import RawQuery, SqlscoutConfig


USERS = {
    "sarah.chen@company.com":       ("ANALYST",         ["WH_ANALYTICS_M", "WH_ANALYTICS_L"]),
    "mike.johnson@company.com":     ("ANALYST",         ["WH_ANALYTICS_M"]),
    "priya.patel@company.com":      ("ANALYST",         ["WH_ANALYTICS_S", "WH_ANALYTICS_M"]),
    "james.wilson@company.com":     ("ANALYST",         ["WH_ANALYTICS_M", "WH_ANALYTICS_L"]),
    "lisa.nguyen@company.com":      ("ANALYST",         ["WH_ANALYTICS_S"]),
    "alex.kumar@company.com":       ("DATA_ENGINEER",   ["WH_ETL_L", "WH_ETL_XL"]),
    "jordan.lee@company.com":       ("DATA_ENGINEER",   ["WH_ETL_L"]),
    "taylor.smith@company.com":     ("DATA_ENGINEER",   ["WH_ETL_XL"]),
    "emma.davis@company.com":       ("DATA_SCIENTIST",  ["WH_DS_XL", "WH_DS_2XL"]),
    "noah.martinez@company.com":    ("DATA_SCIENTIST",  ["WH_DS_XL"]),
    "rachel.thompson@company.com":  ("MANAGER",         ["WH_ANALYTICS_S"]),
    "david.brown@company.com":      ("MANAGER",         ["WH_ANALYTICS_S"]),
    "ceo@company.com":              ("EXECUTIVE",       ["WH_ANALYTICS_S"]),
    "LOOKER_SERVICE":               ("LOOKER_ROLE",     ["WH_LOOKER"]),
    "TABLEAU_SERVICE":              ("TABLEAU_ROLE",    ["WH_TABLEAU"]),
    "DBT_PROD":                     ("DBT_ROLE",        ["WH_DBT"]),
    "FIVETRAN_PROD":                ("FIVETRAN_ROLE",   ["WH_FIVETRAN"]),
}

DATES = [
    "2026-03-15", "2026-03-20", "2026-03-25", "2026-04-01",
    "2026-04-05", "2026-04-07", "2026-04-10", "2026-04-12", "2026-04-14",
]
REGIONS = ["US-East", "US-West", "EU-West", "EU-Central", "APAC-Southeast", "LATAM"]
STATUSES = ["succeeded", "pending", "failed", "refunded"]
SEGMENTS = ["Enterprise", "Mid-Market", "SMB", "Consumer", "VIP"]
CATEGORIES = ["Electronics", "Clothing", "Home & Garden", "Sports", "Books", "Food"]
PRIORITIES = ["critical", "high", "medium", "low"]
PLATFORMS = ["web", "mobile_ios", "mobile_android", "api"]
EXPERIMENTS = ["exp_checkout_v2", "exp_pricing_test", "exp_onboarding_flow", "exp_search_ranking"]
CAMPAIGNS = ["spring_sale_2026", "brand_awareness_q2", "retargeting_lapsed", "influencer_push", "email_weekly"]
SOURCES = ["google", "facebook", "tiktok", "email", "direct", "organic", "referral"]
MEDIUMS = ["cpc", "organic", "email", "social", "referral", "display"]


def _pick_columns(rng, all_cols, min_cols=3):
    n = rng.randint(min_cols, len(all_cols))
    return rng.sample(all_cols, n)


def _col_list(cols):
    return ", ".join(cols)


def _maybe_alias(rng, col, alias):
    if rng.random() < 0.5:
        return f"{col} AS {alias}"
    return col


def gen_order_revenue(rng, date, region):
    all_cols = [
        "r.region_name",
        "DATE_TRUNC('day', o.order_date) AS day",
        "SUM(o.total_amount) AS daily_revenue",
        "COUNT(DISTINCT o.customer_id) AS unique_buyers",
        "COUNT(*) AS order_count",
        "AVG(o.total_amount) AS avg_order_value",
        "SUM(o.discount_amount) AS total_discounts",
        "SUM(o.total_amount) - SUM(o.discount_amount) AS net_revenue",
    ]
    cols = _pick_columns(rng, all_cols, 3)
    group_cols = [c for c in cols if "SUM" not in c and "COUNT" not in c and "AVG" not in c]
    group_by = ", ".join(group_cols) if group_cols else "r.region_name"

    where = f"o.order_date >= '{date}'"
    if rng.random() < 0.4:
        where += f" AND r.region_name = '{region}'"
    if rng.random() < 0.3:
        where += " AND o.order_status = 'completed'"

    return f"SELECT {_col_list(cols)} FROM analytics.sales.fact_orders o JOIN analytics.sales.dim_regions r ON o.region_id = r.region_id WHERE {where} GROUP BY {group_by} ORDER BY daily_revenue DESC"


def gen_customer_ltv(rng, segment, limit):
    base = [
        "c.customer_id",
        "c.customer_name",
        "c.email",
    ]
    optional = [
        "c.signup_date",
        "c.customer_segment",
        "c.phone_number",
        "c.billing_address",
        "c.preferred_channel",
    ]
    aggs = [
        "COUNT(o.order_id) AS total_orders",
        "SUM(o.total_amount) AS lifetime_value",
        "AVG(o.total_amount) AS avg_order_value",
        "MAX(o.order_date) AS last_order_date",
        "MIN(o.order_date) AS first_order_date",
        "DATEDIFF('day', MAX(o.order_date), CURRENT_DATE()) AS days_since_last_order",
        "COUNT(DISTINCT DATE_TRUNC('month', o.order_date)) AS active_months",
    ]
    selected_base = _pick_columns(rng, base, 2)
    selected_opt = _pick_columns(rng, optional, 1)
    selected_aggs = _pick_columns(rng, aggs, 2)
    all_selected = selected_base + selected_opt + selected_aggs
    group_cols = selected_base + selected_opt

    where = f"c.customer_segment = '{segment}'"
    if rng.random() < 0.4:
        where += f" HAVING lifetime_value > {rng.choice([100, 500, 1000, 5000])}"

    return f"SELECT {_col_list(all_selected)} FROM analytics.sales.dim_customers c LEFT JOIN analytics.sales.fact_orders o ON c.customer_id = o.customer_id WHERE {where} GROUP BY {_col_list(group_cols)} ORDER BY lifetime_value DESC LIMIT {limit}"


def gen_product_performance(rng, date):
    cols = [
        "p.product_category",
        "p.product_subcategory",
        "p.brand",
        "DATE_TRUNC('month', o.order_date) AS month",
        "SUM(oi.quantity) AS units_sold",
        "SUM(oi.quantity * oi.unit_price) AS gross_revenue",
        "SUM(oi.quantity * (oi.unit_price - p.cost_price)) AS gross_margin",
        "COUNT(DISTINCT o.customer_id) AS unique_buyers",
        "AVG(oi.unit_price) AS avg_selling_price",
        "SUM(oi.discount_amount) AS total_discounts",
    ]
    selected = _pick_columns(rng, cols, 4)
    group_cols = [c for c in selected if "SUM" not in c and "COUNT" not in c and "AVG" not in c]
    return f"SELECT {_col_list(selected)} FROM analytics.sales.fact_order_items oi JOIN analytics.sales.fact_orders o ON oi.order_id = o.order_id JOIN analytics.sales.dim_products p ON oi.product_id = p.product_id WHERE o.order_date >= '{date}' GROUP BY {_col_list(group_cols)} ORDER BY gross_revenue DESC"


def gen_full_order_detail(rng, date, date2, region):
    base = [
        "o.order_id", "o.order_date", "o.order_status", "o.total_amount",
    ]
    customer_cols = [
        "c.customer_name", "c.email", "c.customer_segment", "c.phone_number",
    ]
    item_cols = [
        "oi.product_id", "oi.quantity", "oi.unit_price", "oi.discount_amount",
        "(oi.quantity * oi.unit_price) - oi.discount_amount AS line_total",
    ]
    product_cols = [
        "p.product_name", "p.product_category", "p.brand", "p.sku",
    ]
    region_cols = [
        "r.region_name", "r.country",
    ]
    selected = (
        _pick_columns(rng, base, 2) +
        _pick_columns(rng, customer_cols, 1) +
        _pick_columns(rng, item_cols, 2) +
        _pick_columns(rng, product_cols, 1) +
        _pick_columns(rng, region_cols, 1)
    )

    where = f"o.order_date BETWEEN '{date}' AND '{date2}'"
    if rng.random() < 0.5:
        where += f" AND r.region_name = '{region}'"
    if rng.random() < 0.3:
        where += f" AND p.product_category = '{rng.choice(CATEGORIES)}'"

    return f"SELECT {_col_list(selected)} FROM analytics.sales.fact_orders o JOIN analytics.sales.dim_customers c ON o.customer_id = c.customer_id JOIN analytics.sales.dim_regions r ON o.region_id = r.region_id JOIN analytics.sales.fact_order_items oi ON o.order_id = oi.order_id JOIN analytics.sales.dim_products p ON oi.product_id = p.product_id WHERE {where}"


def gen_raw_payments_scan(rng, date, status):
    all_cols = [
        "payment_id", "customer_id", "amount", "currency", "payment_status",
        "payment_method", "created_at", "updated_at", "stripe_charge_id",
        "fee_amount", "net_amount", "description", "metadata",
        "failure_code", "failure_message", "receipt_url",
    ]
    if rng.random() < 0.35:
        cols = "*"
    else:
        cols = _col_list(_pick_columns(rng, all_cols, 4))

    where = f"created_at >= '{date}'"
    if rng.random() < 0.6:
        where += f" AND payment_status = '{status}'"
    if rng.random() < 0.3:
        where += f" AND amount > {rng.choice([100, 500, 1000, 5000])}"

    return f"SELECT {cols} FROM raw.stripe.payments WHERE {where}"


def gen_event_funnel(rng, date, platform):
    cols = [
        "event_date", "event_type", "platform",
        "COUNT(*) AS event_count",
        "COUNT(DISTINCT user_id) AS unique_users",
        "COUNT(DISTINCT session_id) AS unique_sessions",
        "AVG(event_duration_ms) AS avg_duration",
    ]
    selected = _pick_columns(rng, cols, 4)
    group_cols = [c for c in selected if "COUNT" not in c and "AVG" not in c]

    events = rng.sample(["page_view", "add_to_cart", "checkout_start", "purchase", "signup", "search", "product_view"], rng.randint(2, 5))
    event_list = ", ".join(f"'{e}'" for e in events)

    where = f"event_date >= '{date}' AND event_type IN ({event_list})"
    if rng.random() < 0.4:
        where += f" AND platform = '{platform}'"

    return f"SELECT {_col_list(selected)} FROM analytics.product.fact_events WHERE {where} GROUP BY {_col_list(group_cols)} ORDER BY event_date DESC"


def gen_customer_lookup(rng, customer_id):
    all_cols = [
        "customer_id", "customer_name", "email", "phone_number",
        "signup_date", "customer_segment", "billing_address",
        "shipping_address", "preferred_channel", "created_at",
        "updated_at", "loyalty_tier", "lifetime_value", "account_status",
    ]
    if rng.random() < 0.3:
        cols = "*"
    else:
        cols = _col_list(_pick_columns(rng, all_cols, 3))

    return f"SELECT {cols} FROM analytics.sales.dim_customers WHERE customer_id = {customer_id}"


def gen_marketing_attribution(rng, date):
    cols = [
        "s.utm_source", "s.utm_medium", "s.utm_campaign",
        "COUNT(DISTINCT s.session_id) AS sessions",
        "COUNT(DISTINCT s.user_id) AS unique_visitors",
        "SUM(CASE WHEN s.converted THEN 1 ELSE 0 END) AS conversions",
        "SUM(CASE WHEN s.converted THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(DISTINCT s.user_id), 0) AS conversion_rate",
        "SUM(o.total_amount) AS attributed_revenue",
        "AVG(o.total_amount) AS avg_order_value",
    ]
    selected = _pick_columns(rng, cols, 4)
    group_cols = [c for c in selected if "COUNT" not in c and "SUM" not in c and "AVG" not in c]
    return f"SELECT {_col_list(selected)} FROM marketing.public.sessions s LEFT JOIN analytics.sales.fact_orders o ON s.user_id = o.customer_id AND o.order_date = s.session_date WHERE s.session_date >= '{date}' GROUP BY {_col_list(group_cols)} ORDER BY attributed_revenue DESC NULLS LAST"


def gen_churn_risk(rng, inactive_days, limit):
    cols = [
        "c.customer_id", "c.customer_name", "c.customer_segment",
        "c.signup_date", "c.email",
        "MAX(o.order_date) AS last_order",
        "DATEDIFF('day', MAX(o.order_date), CURRENT_DATE()) AS days_inactive",
        "COUNT(o.order_id) AS total_orders",
        "SUM(o.total_amount) AS total_spend",
        "AVG(o.total_amount) AS avg_order_value",
        "STDDEV(o.total_amount) AS stddev_order_value",
    ]
    selected = _pick_columns(rng, cols, 5)
    group_cols = [c for c in selected if "MAX" not in c and "DATEDIFF" not in c and "COUNT" not in c and "SUM" not in c and "AVG" not in c and "STDDEV" not in c]
    return f"SELECT {_col_list(selected)} FROM analytics.sales.dim_customers c JOIN analytics.sales.fact_orders o ON c.customer_id = o.customer_id GROUP BY {_col_list(group_cols)} HAVING DATEDIFF('day', MAX(o.order_date), CURRENT_DATE()) > {inactive_days} ORDER BY total_spend DESC LIMIT {limit}"


def gen_support_tickets(rng, date):
    cols = [
        "DATE_TRUNC('day', t.created_at) AS day",
        "t.priority", "t.category", "t.assigned_team",
        "COUNT(*) AS ticket_count",
        "AVG(DATEDIFF('minute', t.created_at, t.first_response_at)) AS avg_first_response_min",
        "AVG(DATEDIFF('hour', t.created_at, t.resolved_at)) AS avg_resolution_hours",
        "SUM(CASE WHEN t.satisfaction_score >= 4 THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0) AS csat_rate",
    ]
    selected = _pick_columns(rng, cols, 4)
    group_cols = [c for c in selected if "COUNT" not in c and "AVG" not in c and "SUM" not in c]
    return f"SELECT {_col_list(selected)} FROM operations.support.tickets t WHERE t.created_at >= '{date}' GROUP BY {_col_list(group_cols)} ORDER BY day DESC"


def gen_exec_kpis(rng, date):
    cols = [
        "DATE_TRUNC('week', o.order_date) AS week",
        "COUNT(DISTINCT o.order_id) AS orders",
        "COUNT(DISTINCT o.customer_id) AS active_customers",
        "SUM(o.total_amount) AS revenue",
        "SUM(o.total_amount) / NULLIF(COUNT(DISTINCT o.customer_id), 0) AS revenue_per_customer",
        "SUM(o.discount_amount) AS total_discounts",
        "SUM(o.total_amount) - SUM(o.discount_amount) AS net_revenue",
    ]
    selected = _pick_columns(rng, cols, 4)
    group_cols = [c for c in selected if "COUNT" not in c and "SUM" not in c]
    return f"SELECT {_col_list(selected)} FROM analytics.sales.fact_orders o WHERE o.order_date >= '{date}' AND o.order_status = 'completed' GROUP BY {_col_list(group_cols)} ORDER BY week DESC"


def gen_ml_features(rng):
    cols = [
        "c.customer_id", "c.customer_segment",
        "DATEDIFF('day', c.signup_date, CURRENT_DATE()) AS account_age_days",
        "COUNT(o.order_id) AS order_count_90d",
        "SUM(o.total_amount) AS spend_90d",
        "AVG(o.total_amount) AS avg_order_90d",
        "STDDEV(o.total_amount) AS stddev_order_90d",
        "COUNT(DISTINCT DATE_TRUNC('week', o.order_date)) AS active_weeks",
        "MAX(o.total_amount) AS max_order_90d",
        "MIN(o.total_amount) AS min_order_90d",
        "COUNT(DISTINCT o.region_id) AS regions_ordered_from",
        "SUM(CASE WHEN o.order_status = 'returned' THEN 1 ELSE 0 END) AS return_count",
    ]
    selected = _pick_columns(rng, cols, 6)
    group_cols = [c for c in selected if "COUNT" not in c and "SUM" not in c and "AVG" not in c and "STDDEV" not in c and "MAX" not in c and "MIN" not in c and "DATEDIFF" not in c]
    return f"SELECT {_col_list(selected)} FROM analytics.sales.dim_customers c LEFT JOIN analytics.sales.fact_orders o ON c.customer_id = o.customer_id AND o.order_date >= DATEADD('day', -90, CURRENT_DATE()) GROUP BY {_col_list(group_cols)}"


def gen_warehouse_costs(rng, date):
    cols = [
        "warehouse_name",
        "DATE_TRUNC('hour', start_time) AS hour",
        "SUM(credits_used) AS hourly_credits",
        "AVG(credits_used) AS avg_credits",
        "COUNT(*) AS query_count",
        "MAX(credits_used) AS max_credits",
    ]
    selected = _pick_columns(rng, cols, 3)
    group_cols = [c for c in selected if "SUM" not in c and "AVG" not in c and "COUNT" not in c and "MAX" not in c]
    return f"SELECT {_col_list(selected)} FROM snowflake.account_usage.warehouse_metering_history WHERE start_time >= '{date}' GROUP BY {_col_list(group_cols)} ORDER BY hourly_credits DESC"


def gen_inventory(rng, date):
    cols = [
        "i.sku", "i.product_name", "i.warehouse_location",
        "i.current_stock", "i.reorder_point", "i.lead_time_days",
        "s.avg_daily_units",
        "ROUND(i.current_stock / NULLIF(s.avg_daily_units, 0), 1) AS days_of_stock",
    ]
    selected = _pick_columns(rng, cols, 4)
    return f"SELECT {_col_list(selected)} FROM operations.inventory.stock_levels i JOIN (SELECT product_id, AVG(quantity) AS avg_daily_units FROM analytics.sales.fact_order_items WHERE order_date >= DATEADD('day', -30, CURRENT_DATE()) GROUP BY product_id) s ON i.product_id = s.product_id WHERE i.current_stock <= i.reorder_point * 1.5 ORDER BY days_of_stock ASC"


def gen_supplier_spend(rng, date, date2):
    cols = [
        "s.supplier_name", "s.supplier_category", "s.supplier_region",
        "COUNT(po.po_id) AS po_count",
        "SUM(po.total_amount) AS total_spend",
        "AVG(po.total_amount) AS avg_po_value",
        "AVG(DATEDIFF('day', po.order_date, po.delivery_date)) AS avg_delivery_days",
        "MAX(po.order_date) AS last_order",
    ]
    selected = _pick_columns(rng, cols, 4)
    group_cols = [c for c in selected if "COUNT" not in c and "SUM" not in c and "AVG" not in c and "MAX" not in c]
    return f"SELECT {_col_list(selected)} FROM operations.procurement.purchase_orders po JOIN operations.procurement.suppliers s ON po.supplier_id = s.supplier_id WHERE po.order_date BETWEEN '{date}' AND '{date2}' AND po.status = 'delivered' GROUP BY {_col_list(group_cols)} ORDER BY total_spend DESC"


def gen_ab_test(rng, experiment_id, date):
    cols = [
        "experiment_id", "variant",
        "COUNT(DISTINCT user_id) AS users",
        "SUM(CASE WHEN converted THEN 1 ELSE 0 END) AS conversions",
        "SUM(CASE WHEN converted THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(DISTINCT user_id), 0) AS conversion_rate",
        "AVG(revenue) AS avg_revenue_per_user",
        "SUM(revenue) AS total_revenue",
        "STDDEV(revenue) AS stddev_revenue",
    ]
    selected = _pick_columns(rng, cols, 4)
    group_cols = [c for c in selected if "COUNT" not in c and "SUM" not in c and "AVG" not in c and "STDDEV" not in c]
    return f"SELECT {_col_list(selected)} FROM analytics.product.experiment_events WHERE experiment_id = '{experiment_id}' AND event_date >= '{date}' GROUP BY {_col_list(group_cols)} ORDER BY variant"


def gen_hr_headcount(rng):
    cols = [
        "d.department_name", "e.job_title", "e.location",
        "COUNT(*) AS headcount",
        "AVG(e.salary) AS avg_salary",
        "MIN(e.hire_date) AS earliest_hire",
        "SUM(CASE WHEN e.hire_date >= DATEADD('month', -3, CURRENT_DATE()) THEN 1 ELSE 0 END) AS new_hires_90d",
        "SUM(CASE WHEN e.hire_date >= DATEADD('month', -6, CURRENT_DATE()) THEN 1 ELSE 0 END) AS new_hires_180d",
    ]
    selected = _pick_columns(rng, cols, 4)
    group_cols = [c for c in selected if "COUNT" not in c and "AVG" not in c and "MIN" not in c and "SUM" not in c]
    return f"SELECT {_col_list(selected)} FROM hr.public.employees e JOIN hr.public.departments d ON e.department_id = d.department_id WHERE e.employment_status = 'active' GROUP BY {_col_list(group_cols)} ORDER BY department_name, headcount DESC"


def gen_table_metadata(rng):
    cols = [
        "table_catalog", "table_schema", "table_name",
        "row_count", "bytes", "last_altered", "created",
        "clustering_key", "retention_time",
    ]
    selected = _pick_columns(rng, cols, 4)
    min_rows = rng.choice([1000, 10000, 100000, 1000000])
    limit = rng.choice([25, 50, 100, 500])
    return f"SELECT {_col_list(selected)} FROM snowflake.account_usage.tables WHERE deleted IS NULL AND table_schema NOT IN ('INFORMATION_SCHEMA') AND row_count > {min_rows} ORDER BY bytes DESC LIMIT {limit}"


GENERATORS = [
    {"fn": lambda rng: gen_order_revenue(rng, rng.choice(DATES), rng.choice(REGIONS)),
     "users": ["sarah.chen@company.com", "mike.johnson@company.com", "priya.patel@company.com", "james.wilson@company.com", "lisa.nguyen@company.com", "LOOKER_SERVICE", "TABLEAU_SERVICE", "rachel.thompson@company.com", "david.brown@company.com"],
     "weight": 30, "avg_time_ms": 4500, "avg_bytes": 85_000_000, "avg_credits": 0.08},

    {"fn": lambda rng: gen_customer_ltv(rng, rng.choice(SEGMENTS), rng.choice([50, 100, 250, 500, 1000])),
     "users": ["sarah.chen@company.com", "mike.johnson@company.com", "priya.patel@company.com", "james.wilson@company.com", "emma.davis@company.com", "noah.martinez@company.com", "rachel.thompson@company.com"],
     "weight": 20, "avg_time_ms": 12000, "avg_bytes": 350_000_000, "avg_credits": 0.25},

    {"fn": lambda rng: gen_product_performance(rng, rng.choice(DATES)),
     "users": ["sarah.chen@company.com", "mike.johnson@company.com", "james.wilson@company.com", "LOOKER_SERVICE", "TABLEAU_SERVICE", "rachel.thompson@company.com", "david.brown@company.com"],
     "weight": 22, "avg_time_ms": 8500, "avg_bytes": 220_000_000, "avg_credits": 0.18},

    {"fn": lambda rng: gen_full_order_detail(rng, rng.choice(DATES), rng.choice(DATES), rng.choice(REGIONS)),
     "users": ["sarah.chen@company.com", "priya.patel@company.com", "james.wilson@company.com", "lisa.nguyen@company.com", "LOOKER_SERVICE", "TABLEAU_SERVICE"],
     "weight": 18, "avg_time_ms": 18000, "avg_bytes": 800_000_000, "avg_credits": 0.55},

    {"fn": lambda rng: gen_raw_payments_scan(rng, rng.choice(DATES), rng.choice(STATUSES)),
     "users": ["alex.kumar@company.com", "jordan.lee@company.com", "taylor.smith@company.com", "sarah.chen@company.com", "mike.johnson@company.com"],
     "weight": 12, "avg_time_ms": 25000, "avg_bytes": 1_500_000_000, "avg_credits": 1.20},

    {"fn": lambda rng: gen_event_funnel(rng, rng.choice(DATES), rng.choice(PLATFORMS)),
     "users": ["sarah.chen@company.com", "priya.patel@company.com", "emma.davis@company.com", "noah.martinez@company.com", "LOOKER_SERVICE", "TABLEAU_SERVICE"],
     "weight": 16, "avg_time_ms": 6000, "avg_bytes": 180_000_000, "avg_credits": 0.12},

    {"fn": lambda rng: gen_customer_lookup(rng, rng.randint(1, 500000)),
     "users": list(USERS.keys()),
     "weight": 15, "avg_time_ms": 8000, "avg_bytes": 950_000_000, "avg_credits": 0.65},

    {"fn": lambda rng: gen_marketing_attribution(rng, rng.choice(DATES)),
     "users": ["sarah.chen@company.com", "mike.johnson@company.com", "rachel.thompson@company.com", "david.brown@company.com", "LOOKER_SERVICE"],
     "weight": 10, "avg_time_ms": 9500, "avg_bytes": 280_000_000, "avg_credits": 0.22},

    {"fn": lambda rng: gen_churn_risk(rng, rng.choice([30, 60, 90, 120]), rng.choice([100, 250, 500, 1000])),
     "users": ["emma.davis@company.com", "noah.martinez@company.com", "sarah.chen@company.com", "priya.patel@company.com"],
     "weight": 8, "avg_time_ms": 15000, "avg_bytes": 400_000_000, "avg_credits": 0.30},

    {"fn": lambda rng: gen_support_tickets(rng, rng.choice(DATES)),
     "users": ["rachel.thompson@company.com", "david.brown@company.com", "mike.johnson@company.com", "lisa.nguyen@company.com"],
     "weight": 7, "avg_time_ms": 3500, "avg_bytes": 45_000_000, "avg_credits": 0.04},

    {"fn": lambda rng: gen_exec_kpis(rng, rng.choice(DATES)),
     "users": ["ceo@company.com", "rachel.thompson@company.com", "david.brown@company.com", "LOOKER_SERVICE", "TABLEAU_SERVICE"],
     "weight": 12, "avg_time_ms": 5500, "avg_bytes": 120_000_000, "avg_credits": 0.10},

    {"fn": lambda rng: gen_ml_features(rng),
     "users": ["emma.davis@company.com", "noah.martinez@company.com"],
     "weight": 6, "avg_time_ms": 35000, "avg_bytes": 2_000_000_000, "avg_credits": 2.50},

    {"fn": lambda rng: gen_warehouse_costs(rng, rng.choice(DATES)),
     "users": ["alex.kumar@company.com", "jordan.lee@company.com", "taylor.smith@company.com", "rachel.thompson@company.com"],
     "weight": 5, "avg_time_ms": 2000, "avg_bytes": 15_000_000, "avg_credits": 0.02},

    {"fn": lambda rng: gen_inventory(rng, rng.choice(DATES)),
     "users": ["rachel.thompson@company.com", "david.brown@company.com", "james.wilson@company.com"],
     "weight": 5, "avg_time_ms": 7000, "avg_bytes": 200_000_000, "avg_credits": 0.15},

    {"fn": lambda rng: gen_supplier_spend(rng, rng.choice(DATES), rng.choice(DATES)),
     "users": ["rachel.thompson@company.com", "david.brown@company.com", "james.wilson@company.com"],
     "weight": 4, "avg_time_ms": 4000, "avg_bytes": 60_000_000, "avg_credits": 0.06},

    {"fn": lambda rng: gen_ab_test(rng, rng.choice(EXPERIMENTS), rng.choice(DATES)),
     "users": ["emma.davis@company.com", "noah.martinez@company.com", "sarah.chen@company.com", "priya.patel@company.com"],
     "weight": 7, "avg_time_ms": 4000, "avg_bytes": 100_000_000, "avg_credits": 0.09},

    {"fn": lambda rng: gen_hr_headcount(rng),
     "users": ["rachel.thompson@company.com", "david.brown@company.com", "ceo@company.com"],
     "weight": 3, "avg_time_ms": 1200, "avg_bytes": 8_000_000, "avg_credits": 0.01},

    {"fn": lambda rng: gen_table_metadata(rng),
     "users": ["alex.kumar@company.com", "jordan.lee@company.com", "taylor.smith@company.com"],
     "weight": 3, "avg_time_ms": 800, "avg_bytes": 3_000_000, "avg_credits": 0.005},
]


REPEATED_QUERIES = [
    {
        "sql": "SELECT r.region_name, DATE_TRUNC('day', o.order_date) AS day, SUM(o.total_amount) AS daily_revenue, COUNT(DISTINCT o.customer_id) AS unique_buyers, COUNT(*) AS order_count FROM analytics.sales.fact_orders o JOIN analytics.sales.dim_regions r ON o.region_id = r.region_id WHERE o.order_date >= DATEADD('day', -7, CURRENT_DATE()) AND o.order_status = 'completed' GROUP BY r.region_name, DATE_TRUNC('day', o.order_date) ORDER BY day DESC, daily_revenue DESC",
        "user": "LOOKER_SERVICE",
        "count": 85,
        "avg_time_ms": 4200,
        "avg_bytes": 82_000_000,
        "avg_credits": 0.07,
    },
    {
        "sql": "SELECT r.region_name, DATE_TRUNC('day', o.order_date) AS day, SUM(o.total_amount) AS daily_revenue, COUNT(DISTINCT o.customer_id) AS unique_buyers, COUNT(*) AS order_count FROM analytics.sales.fact_orders o JOIN analytics.sales.dim_regions r ON o.region_id = r.region_id WHERE o.order_date >= DATEADD('day', -7, CURRENT_DATE()) AND o.order_status = 'completed' GROUP BY r.region_name, DATE_TRUNC('day', o.order_date) ORDER BY day DESC, daily_revenue DESC",
        "user": "TABLEAU_SERVICE",
        "count": 70,
        "avg_time_ms": 4400,
        "avg_bytes": 84_000_000,
        "avg_credits": 0.07,
    },
    {
        "sql": "SELECT p.product_category, p.product_subcategory, DATE_TRUNC('month', o.order_date) AS month, SUM(oi.quantity) AS units_sold, SUM(oi.quantity * oi.unit_price) AS gross_revenue, SUM(oi.quantity * (oi.unit_price - p.cost_price)) AS gross_margin, COUNT(DISTINCT o.customer_id) AS unique_buyers FROM analytics.sales.fact_order_items oi JOIN analytics.sales.fact_orders o ON oi.order_id = o.order_id JOIN analytics.sales.dim_products p ON oi.product_id = p.product_id WHERE o.order_date >= DATEADD('day', -30, CURRENT_DATE()) GROUP BY p.product_category, p.product_subcategory, DATE_TRUNC('month', o.order_date) ORDER BY gross_revenue DESC",
        "user": "LOOKER_SERVICE",
        "count": 60,
        "avg_time_ms": 8200,
        "avg_bytes": 210_000_000,
        "avg_credits": 0.17,
    },
    {
        "sql": "SELECT DATE_TRUNC('week', o.order_date) AS week, COUNT(DISTINCT o.order_id) AS orders, COUNT(DISTINCT o.customer_id) AS active_customers, SUM(o.total_amount) AS revenue, SUM(o.total_amount) / NULLIF(COUNT(DISTINCT o.customer_id), 0) AS revenue_per_customer FROM analytics.sales.fact_orders o WHERE o.order_date >= DATEADD('day', -90, CURRENT_DATE()) AND o.order_status = 'completed' GROUP BY DATE_TRUNC('week', o.order_date) ORDER BY week DESC",
        "user": "LOOKER_SERVICE",
        "count": 50,
        "avg_time_ms": 5200,
        "avg_bytes": 115_000_000,
        "avg_credits": 0.09,
    },
    {
        "sql": "SELECT DATE_TRUNC('week', o.order_date) AS week, COUNT(DISTINCT o.order_id) AS orders, COUNT(DISTINCT o.customer_id) AS active_customers, SUM(o.total_amount) AS revenue, SUM(o.total_amount) / NULLIF(COUNT(DISTINCT o.customer_id), 0) AS revenue_per_customer FROM analytics.sales.fact_orders o WHERE o.order_date >= DATEADD('day', -90, CURRENT_DATE()) AND o.order_status = 'completed' GROUP BY DATE_TRUNC('week', o.order_date) ORDER BY week DESC",
        "user": "TABLEAU_SERVICE",
        "count": 45,
        "avg_time_ms": 5500,
        "avg_bytes": 118_000_000,
        "avg_credits": 0.10,
    },
    {
        "sql": "SELECT o.order_id, o.order_date, o.order_status, o.total_amount, c.customer_name, c.email, c.customer_segment, r.region_name, oi.product_id, oi.quantity, oi.unit_price, oi.discount_amount, p.product_name, p.product_category FROM analytics.sales.fact_orders o JOIN analytics.sales.dim_customers c ON o.customer_id = c.customer_id JOIN analytics.sales.dim_regions r ON o.region_id = r.region_id JOIN analytics.sales.fact_order_items oi ON o.order_id = oi.order_id JOIN analytics.sales.dim_products p ON oi.product_id = p.product_id WHERE o.order_date >= DATEADD('day', -7, CURRENT_DATE())",
        "user": "TABLEAU_SERVICE",
        "count": 55,
        "avg_time_ms": 17500,
        "avg_bytes": 780_000_000,
        "avg_credits": 0.52,
    },
    {
        "sql": "SELECT * FROM raw.stripe.payments WHERE created_at >= DATEADD('day', -1, CURRENT_DATE())",
        "user": "alex.kumar@company.com",
        "count": 30,
        "avg_time_ms": 28000,
        "avg_bytes": 1_600_000_000,
        "avg_credits": 1.35,
    },
    {
        "sql": "SELECT * FROM raw.stripe.payments WHERE created_at >= DATEADD('day', -1, CURRENT_DATE())",
        "user": "jordan.lee@company.com",
        "count": 20,
        "avg_time_ms": 26000,
        "avg_bytes": 1_550_000_000,
        "avg_credits": 1.25,
    },
    {
        "sql": "SELECT c.customer_id, c.customer_name, c.email, c.signup_date, c.customer_segment, COUNT(o.order_id) AS total_orders, SUM(o.total_amount) AS lifetime_value, AVG(o.total_amount) AS avg_order_value, MAX(o.order_date) AS last_order_date, DATEDIFF('day', MAX(o.order_date), CURRENT_DATE()) AS days_since_last_order FROM analytics.sales.dim_customers c LEFT JOIN analytics.sales.fact_orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id, c.customer_name, c.email, c.signup_date, c.customer_segment ORDER BY lifetime_value DESC LIMIT 1000",
        "user": "sarah.chen@company.com",
        "count": 25,
        "avg_time_ms": 11000,
        "avg_bytes": 340_000_000,
        "avg_credits": 0.23,
    },
    {
        "sql": "SELECT c.customer_id, c.customer_name, c.email, c.signup_date, c.customer_segment, COUNT(o.order_id) AS total_orders, SUM(o.total_amount) AS lifetime_value, AVG(o.total_amount) AS avg_order_value, MAX(o.order_date) AS last_order_date, DATEDIFF('day', MAX(o.order_date), CURRENT_DATE()) AS days_since_last_order FROM analytics.sales.dim_customers c LEFT JOIN analytics.sales.fact_orders o ON c.customer_id = o.customer_id GROUP BY c.customer_id, c.customer_name, c.email, c.signup_date, c.customer_segment ORDER BY lifetime_value DESC LIMIT 1000",
        "user": "mike.johnson@company.com",
        "count": 18,
        "avg_time_ms": 11500,
        "avg_bytes": 345_000_000,
        "avg_credits": 0.24,
    },
    {
        "sql": "SELECT event_date, event_type, platform, COUNT(*) AS event_count, COUNT(DISTINCT user_id) AS unique_users FROM analytics.product.fact_events WHERE event_date >= DATEADD('day', -7, CURRENT_DATE()) AND event_type IN ('page_view', 'add_to_cart', 'checkout_start', 'purchase') GROUP BY event_date, event_type, platform ORDER BY event_date DESC",
        "user": "LOOKER_SERVICE",
        "count": 40,
        "avg_time_ms": 5800,
        "avg_bytes": 175_000_000,
        "avg_credits": 0.11,
    },
    {
        "sql": "SELECT s.utm_source, s.utm_medium, s.utm_campaign, COUNT(DISTINCT s.session_id) AS sessions, COUNT(DISTINCT s.user_id) AS unique_visitors, SUM(CASE WHEN s.converted THEN 1 ELSE 0 END) AS conversions, SUM(CASE WHEN s.converted THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(DISTINCT s.user_id), 0) AS conversion_rate, SUM(o.total_amount) AS attributed_revenue FROM marketing.public.sessions s LEFT JOIN analytics.sales.fact_orders o ON s.user_id = o.customer_id AND o.order_date = s.session_date WHERE s.session_date >= DATEADD('day', -7, CURRENT_DATE()) GROUP BY s.utm_source, s.utm_medium, s.utm_campaign ORDER BY attributed_revenue DESC NULLS LAST",
        "user": "sarah.chen@company.com",
        "count": 15,
        "avg_time_ms": 9200,
        "avg_bytes": 270_000_000,
        "avg_credits": 0.21,
    },
    {
        "sql": "SELECT s.utm_source, s.utm_medium, s.utm_campaign, COUNT(DISTINCT s.session_id) AS sessions, COUNT(DISTINCT s.user_id) AS unique_visitors, SUM(CASE WHEN s.converted THEN 1 ELSE 0 END) AS conversions, SUM(CASE WHEN s.converted THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(DISTINCT s.user_id), 0) AS conversion_rate, SUM(o.total_amount) AS attributed_revenue FROM marketing.public.sessions s LEFT JOIN analytics.sales.fact_orders o ON s.user_id = o.customer_id AND o.order_date = s.session_date WHERE s.session_date >= DATEADD('day', -7, CURRENT_DATE()) GROUP BY s.utm_source, s.utm_medium, s.utm_campaign ORDER BY attributed_revenue DESC NULLS LAST",
        "user": "mike.johnson@company.com",
        "count": 12,
        "avg_time_ms": 9500,
        "avg_bytes": 275_000_000,
        "avg_credits": 0.22,
    },
]


def generate(n_adhoc=250, seed=42):
    rng = random.Random(seed)
    queries = []
    base_time = datetime(2026, 4, 8, 6, 0, 0)
    idx = 0

    for rq in REPEATED_QUERIES:
        user_name = rq["user"]
        role, warehouses = USERS[user_name]
        warehouse = warehouses[0]

        for _ in range(rq["count"]):
            time_var = rng.uniform(0.7, 1.4)
            bytes_var = rng.uniform(0.8, 1.3)

            queries.append(RawQuery(
                query_id=f"01b{idx:05x}-{rng.randint(1000,9999)}-{rng.randint(1000,9999)}-0000-00000000{rng.randint(1000,9999)}",
                query_text=rq["sql"],
                user_name=user_name,
                role_name=role,
                warehouse_name=warehouse,
                execution_time_ms=int(rq["avg_time_ms"] * time_var),
                bytes_scanned=int(rq["avg_bytes"] * bytes_var),
                credits_used=round(rq["avg_credits"] * time_var, 6),
                start_time=base_time + timedelta(
                    days=rng.randint(0, 6),
                    hours=rng.randint(0, 15),
                    minutes=rng.randint(0, 59),
                    seconds=rng.randint(0, 59),
                ),
                query_type="SELECT",
            ))
            idx += 1

    weighted = []
    for g in GENERATORS:
        weighted.extend([g] * g["weight"])

    for _ in range(n_adhoc):
        gen = rng.choice(weighted)
        user_name = rng.choice(gen["users"])
        role, warehouses = USERS[user_name]
        warehouse = rng.choice(warehouses)

        sql = gen["fn"](rng)

        time_var = rng.uniform(0.3, 3.0)
        bytes_var = rng.uniform(0.2, 4.0)

        queries.append(RawQuery(
            query_id=f"01b{idx:05x}-{rng.randint(1000,9999)}-{rng.randint(1000,9999)}-0000-00000000{rng.randint(1000,9999)}",
            query_text=sql,
            user_name=user_name,
            role_name=role,
            warehouse_name=warehouse,
            execution_time_ms=int(gen["avg_time_ms"] * time_var),
            bytes_scanned=int(gen["avg_bytes"] * bytes_var),
            credits_used=round(gen["avg_credits"] * time_var, 6),
            start_time=base_time + timedelta(
                days=rng.randint(0, 6),
                hours=rng.randint(0, 15),
                minutes=rng.randint(0, 59),
                seconds=rng.randint(0, 59),
            ),
            query_type="SELECT",
        ))
        idx += 1

    rng.shuffle(queries)
    return queries


if __name__ == "__main__":
    queries = generate(n_adhoc=250)
    total_repeated = sum(rq["count"] for rq in REPEATED_QUERIES)
    print(f"Generated {len(queries)} queries ({total_repeated} repeated dashboard/saved + 250 ad hoc)")

    out_dir = Path(__file__).parent
    raw_path = out_dir / "query_history.json"
    raw_data = [q.model_dump(mode="json") for q in queries]
    with open(raw_path, "w") as f:
        json.dump(raw_data, f, indent=2, default=str)
    print(f"  -> {raw_path}")

    print("Running pipeline...")
    config = SqlscoutConfig(days=7, top_n=25)
    result = aggregate(iter(queries), config)

    json_path = out_dir / "analysis_output.json"
    export_json(result, str(json_path))

    md_path = out_dir / "analysis_output.md"
    export_markdown_summary(result, str(md_path))

    print(f"  -> {json_path}")
    print(f"  -> {md_path}")
    print()
    print(f"{result.metadata.total_queries_processed} queries | {result.metadata.distinct_fingerprints} patterns | {len(result.clusters)} top clusters | {result.metadata.total_credits:.2f} credits")
