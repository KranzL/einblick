import json
import random
from datetime import datetime, timedelta

from einblick.aggregator import aggregate, export_json, export_markdown_summary
from einblick.models import RawQuery, EinblickConfig

USERS = ["ALICE_ANALYST", "BOB_ENGINEER", "CAROL_DS", "DAVE_MANAGER", "EVE_INTERN",
         "FRANK_BI", "GRACE_ANALYST", "HANK_ENGINEER", "IVY_DS", "JACK_INTERN"]

ROLES = ["ANALYST", "DATA_ENGINEER", "DATA_SCIENTIST", "MANAGER", "READONLY"]

WAREHOUSES = ["WH_XSMALL", "WH_SMALL", "WH_MEDIUM", "WH_LARGE", "WH_XLARGE"]

QUERY_TEMPLATES = [
    {
        "sql": "SELECT customer_id, SUM(order_total) AS total_spend, COUNT(*) AS order_count FROM analytics.public.orders WHERE order_date >= '{date}' GROUP BY customer_id ORDER BY total_spend DESC LIMIT {limit}",
        "tables": ["analytics.public.orders"],
        "weight": 15,
        "avg_time_ms": 2500,
        "avg_bytes": 50000000,
        "avg_credits": 0.05,
    },
    {
        "sql": "SELECT o.order_id, o.order_date, c.customer_name, c.email, p.product_name, oi.quantity, oi.unit_price FROM analytics.public.orders o JOIN analytics.public.customers c ON o.customer_id = c.id JOIN analytics.public.order_items oi ON o.order_id = oi.order_id JOIN analytics.public.products p ON oi.product_id = p.id WHERE o.order_date >= '{date}' AND c.region = '{region}'",
        "tables": ["analytics.public.orders", "analytics.public.customers", "analytics.public.order_items", "analytics.public.products"],
        "weight": 12,
        "avg_time_ms": 8000,
        "avg_bytes": 200000000,
        "avg_credits": 0.15,
    },
    {
        "sql": "SELECT product_category, DATE_TRUNC('month', order_date) AS month, SUM(revenue) AS monthly_revenue, COUNT(DISTINCT customer_id) AS unique_customers FROM analytics.public.fact_sales WHERE order_date >= '{date}' GROUP BY product_category, DATE_TRUNC('month', order_date) ORDER BY month DESC, monthly_revenue DESC",
        "tables": ["analytics.public.fact_sales"],
        "weight": 10,
        "avg_time_ms": 5000,
        "avg_bytes": 150000000,
        "avg_credits": 0.12,
    },
    {
        "sql": "SELECT * FROM raw.stripe.payments WHERE created_at >= '{date}' AND status = '{status}'",
        "tables": ["raw.stripe.payments"],
        "weight": 8,
        "avg_time_ms": 12000,
        "avg_bytes": 500000000,
        "avg_credits": 0.35,
    },
    {
        "sql": "SELECT user_id, event_type, COUNT(*) AS event_count FROM analytics.public.user_events WHERE event_date = '{date}' AND event_type IN ('page_view', 'click', 'purchase') GROUP BY user_id, event_type",
        "tables": ["analytics.public.user_events"],
        "weight": 8,
        "avg_time_ms": 3000,
        "avg_bytes": 80000000,
        "avg_credits": 0.08,
    },
    {
        "sql": "SELECT d.department_name, COUNT(e.id) AS headcount, AVG(e.salary) AS avg_salary FROM hr.public.employees e JOIN hr.public.departments d ON e.department_id = d.id WHERE e.status = 'active' GROUP BY d.department_name",
        "tables": ["hr.public.employees", "hr.public.departments"],
        "weight": 5,
        "avg_time_ms": 800,
        "avg_bytes": 5000000,
        "avg_credits": 0.01,
    },
    {
        "sql": "SELECT warehouse_name, DATE_TRUNC('hour', start_time) AS hour, SUM(credits_used) AS hourly_credits FROM snowflake.account_usage.warehouse_metering_history WHERE start_time >= '{date}' GROUP BY warehouse_name, DATE_TRUNC('hour', start_time) ORDER BY hourly_credits DESC",
        "tables": ["snowflake.account_usage.warehouse_metering_history"],
        "weight": 4,
        "avg_time_ms": 1500,
        "avg_bytes": 10000000,
        "avg_credits": 0.02,
    },
    {
        "sql": "SELECT s.supplier_name, COUNT(po.id) AS po_count, SUM(po.total_amount) AS total_spent FROM procurement.public.purchase_orders po JOIN procurement.public.suppliers s ON po.supplier_id = s.id WHERE po.order_date BETWEEN '{date}' AND '{date2}' GROUP BY s.supplier_name ORDER BY total_spent DESC",
        "tables": ["procurement.public.purchase_orders", "procurement.public.suppliers"],
        "weight": 6,
        "avg_time_ms": 4000,
        "avg_bytes": 75000000,
        "avg_credits": 0.09,
    },
    {
        "sql": "SELECT region, product_line, SUM(quantity) AS units_sold, SUM(revenue) AS total_revenue, SUM(revenue) / NULLIF(SUM(quantity), 0) AS avg_price FROM analytics.public.fact_sales WHERE order_date >= '{date}' GROUP BY region, product_line",
        "tables": ["analytics.public.fact_sales"],
        "weight": 7,
        "avg_time_ms": 6000,
        "avg_bytes": 180000000,
        "avg_credits": 0.14,
    },
    {
        "sql": "SELECT c.customer_segment, c.region, COUNT(DISTINCT o.customer_id) AS active_customers, SUM(o.order_total) AS segment_revenue FROM analytics.public.orders o JOIN analytics.public.customers c ON o.customer_id = c.id WHERE o.order_date >= '{date}' GROUP BY c.customer_segment, c.region",
        "tables": ["analytics.public.orders", "analytics.public.customers"],
        "weight": 6,
        "avg_time_ms": 4500,
        "avg_bytes": 120000000,
        "avg_credits": 0.11,
    },
    {
        "sql": "SELECT DATE_TRUNC('day', created_at) AS day, status, COUNT(*) AS ticket_count, AVG(DATEDIFF('hour', created_at, resolved_at)) AS avg_resolution_hours FROM support.public.tickets WHERE created_at >= '{date}' GROUP BY DATE_TRUNC('day', created_at), status",
        "tables": ["support.public.tickets"],
        "weight": 4,
        "avg_time_ms": 2000,
        "avg_bytes": 30000000,
        "avg_credits": 0.03,
    },
    {
        "sql": "SELECT * FROM analytics.public.dim_customers WHERE customer_id = {customer_id}",
        "tables": ["analytics.public.dim_customers"],
        "weight": 5,
        "avg_time_ms": 15000,
        "avg_bytes": 800000000,
        "avg_credits": 0.50,
    },
    {
        "sql": "SELECT channel, utm_source, utm_medium, COUNT(*) AS sessions, COUNT(DISTINCT user_id) AS unique_users, SUM(CASE WHEN converted = TRUE THEN 1 ELSE 0 END) AS conversions FROM marketing.public.sessions WHERE session_date >= '{date}' GROUP BY channel, utm_source, utm_medium ORDER BY sessions DESC",
        "tables": ["marketing.public.sessions"],
        "weight": 5,
        "avg_time_ms": 3500,
        "avg_bytes": 90000000,
        "avg_credits": 0.07,
    },
    {
        "sql": "SELECT i.sku, i.product_name, i.current_stock, i.reorder_point, s.avg_daily_sales FROM inventory.public.stock_levels i JOIN (SELECT product_id, AVG(quantity) AS avg_daily_sales FROM analytics.public.fact_sales WHERE order_date >= '{date}' GROUP BY product_id) s ON i.product_id = s.product_id WHERE i.current_stock < i.reorder_point",
        "tables": ["inventory.public.stock_levels", "analytics.public.fact_sales"],
        "weight": 3,
        "avg_time_ms": 7000,
        "avg_bytes": 250000000,
        "avg_credits": 0.20,
    },
    {
        "sql": "SELECT table_catalog, table_schema, table_name, row_count, bytes FROM snowflake.account_usage.tables WHERE deleted IS NULL AND row_count > {min_rows} ORDER BY bytes DESC LIMIT {limit}",
        "tables": ["snowflake.account_usage.tables"],
        "weight": 2,
        "avg_time_ms": 500,
        "avg_bytes": 2000000,
        "avg_credits": 0.005,
    },
]

DATES = ["2026-04-01", "2026-04-05", "2026-04-07", "2026-04-10", "2026-04-12", "2026-04-14"]
REGIONS = ["US-EAST", "US-WEST", "EU", "APAC"]
STATUSES = ["succeeded", "pending", "failed", "refunded"]


def _generate_sample_queries(n=100, seed=42):
    rng = random.Random(seed)

    weighted_templates = []
    for t in QUERY_TEMPLATES:
        weighted_templates.extend([t] * t["weight"])

    queries = []
    base_time = datetime(2026, 4, 15, 8, 0, 0)

    for i in range(n):
        template = rng.choice(weighted_templates)
        user = rng.choice(USERS)
        role = rng.choice(ROLES)
        warehouse = rng.choice(WAREHOUSES)

        sql = template["sql"].format(
            date=rng.choice(DATES),
            date2=rng.choice(DATES),
            limit=rng.choice([10, 25, 50, 100, 500]),
            region=rng.choice(REGIONS),
            status=rng.choice(STATUSES),
            customer_id=rng.randint(1, 100000),
            min_rows=rng.choice([1000, 10000, 100000]),
        )

        time_variance = rng.uniform(0.5, 2.0)
        bytes_variance = rng.uniform(0.3, 3.0)

        queries.append(RawQuery(
            query_id=f"q{i:04d}",
            query_text=sql,
            user_name=user,
            role_name=role,
            warehouse_name=warehouse,
            execution_time_ms=int(template["avg_time_ms"] * time_variance),
            bytes_scanned=int(template["avg_bytes"] * bytes_variance),
            credits_used=round(template["avg_credits"] * time_variance, 6),
            start_time=base_time + timedelta(minutes=rng.randint(0, 10080)),
            query_type="SELECT",
        ))

    return queries


class TestE2ESample:
    def test_pipeline_produces_clusters(self):
        queries = _generate_sample_queries(100)
        config = EinblickConfig(days=7, top_n=20)
        result = aggregate(iter(queries), config)

        assert result.metadata.total_queries_processed == 100
        assert result.metadata.distinct_fingerprints > 0
        assert len(result.clusters) > 0
        assert len(result.clusters) <= 20

        for cluster in result.clusters:
            assert cluster.execution_count > 0
            assert len(cluster.distinct_users) > 0
            assert cluster.fingerprint is not None
            assert len(cluster.fingerprint) == 32

    def test_offenders_populated(self):
        queries = _generate_sample_queries(100)
        config = EinblickConfig(days=7, top_n=20)
        result = aggregate(iter(queries), config)

        assert len(result.offenders.top_users_by_cost) > 0
        assert len(result.offenders.top_warehouses) > 0

        top_user = result.offenders.top_users_by_cost[0]
        assert top_user.total_queries > 0
        assert top_user.total_credits > 0

    def test_similar_queries_cluster_together(self):
        queries = _generate_sample_queries(100)
        config = EinblickConfig(days=7, top_n=50)
        result = aggregate(iter(queries), config)

        assert result.metadata.distinct_fingerprints < 100

        top_cluster = result.clusters[0]
        assert top_cluster.execution_count > 1

    def test_json_export_valid(self, tmp_path):
        queries = _generate_sample_queries(100)
        config = EinblickConfig(days=7, top_n=15)
        result = aggregate(iter(queries), config)

        path = str(tmp_path / "sample_output.json")
        export_json(result, path)

        with open(path) as f:
            data = json.load(f)

        assert len(data["clusters"]) > 0
        assert data["metadata"]["total_queries_processed"] == 100
        assert "offenders" in data
        assert len(data["offenders"]["top_users_by_cost"]) > 0

        first_cluster = data["clusters"][0]
        assert "fingerprint" in first_cluster
        assert "canonical_sql" in first_cluster
        assert "execution_count" in first_cluster
        assert "impact_score" in first_cluster

    def test_markdown_export_readable(self, tmp_path):
        queries = _generate_sample_queries(100)
        config = EinblickConfig(days=7, top_n=15)
        result = aggregate(iter(queries), config)

        path = str(tmp_path / "sample_output.md")
        export_markdown_summary(result, path)

        with open(path) as f:
            content = f.read()

        assert "Einblick Analysis" in content
        assert "Biggest Offenders" in content
        assert "Top Query Patterns by Impact" in content
        assert "```sql" in content
        assert "Pattern 1" in content
        assert len(content) > 1000

    def test_impact_score_ordering(self):
        queries = _generate_sample_queries(100)
        config = EinblickConfig(days=7, top_n=20)
        result = aggregate(iter(queries), config)

        for i in range(len(result.clusters) - 1):
            assert result.clusters[i].impact_score >= result.clusters[i + 1].impact_score

    def test_metadata_totals_match(self):
        queries = _generate_sample_queries(100)
        config = EinblickConfig(days=7, top_n=50)
        result = aggregate(iter(queries), config)

        assert result.metadata.total_credits > 0
        assert result.metadata.total_bytes_scanned > 0
        assert result.metadata.total_queries_processed == 100

    def test_tables_extracted_from_clusters(self):
        queries = _generate_sample_queries(100)
        config = EinblickConfig(days=7, top_n=20)
        result = aggregate(iter(queries), config)

        clusters_with_tables = [c for c in result.clusters if len(c.tables_referenced) > 0]
        assert len(clusters_with_tables) > 0
