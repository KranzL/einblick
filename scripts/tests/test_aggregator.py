from datetime import datetime

from einblick.aggregator import aggregate, export_json, export_markdown_summary
from einblick.models import RawQuery, EinblickConfig


def _make_query(query_text="SELECT * FROM orders WHERE id = 1", user="ALICE", credits=0.001, **kwargs):
    defaults = dict(
        query_id="q1",
        query_text=query_text,
        user_name=user,
        role_name="ANALYST",
        warehouse_name="COMPUTE_WH",
        execution_time_ms=100,
        bytes_scanned=1000,
        credits_used=credits,
        start_time=datetime(2026, 4, 15, 10, 0, 0),
        query_type="SELECT",
    )
    defaults.update(kwargs)
    return RawQuery(**defaults)


def _gen(queries):
    yield from queries


class TestAggregateEmpty:
    def test_empty_input(self):
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen([]), config)
        assert result.metadata.total_queries_processed == 0
        assert len(result.clusters) == 0


class TestAggregateClustering:
    def test_same_pattern_groups_together(self):
        queries = [
            _make_query("SELECT * FROM orders WHERE id = 1", user="ALICE", query_id="q1"),
            _make_query("SELECT * FROM orders WHERE id = 2", user="BOB", query_id="q2"),
            _make_query("SELECT * FROM orders WHERE id = 3", user="ALICE", query_id="q3"),
        ]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        assert len(result.clusters) == 1
        assert result.clusters[0].execution_count == 3

    def test_different_patterns_separate(self):
        queries = [
            _make_query("SELECT * FROM orders WHERE id = 1", query_id="q1"),
            _make_query("SELECT * FROM customers WHERE name = 'alice'", query_id="q2"),
        ]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        assert len(result.clusters) == 2

    def test_distinct_users_tracked(self):
        queries = [
            _make_query(user="ALICE", query_id="q1"),
            _make_query(user="BOB", query_id="q2"),
            _make_query(user="ALICE", query_id="q3"),
        ]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        assert len(result.clusters) == 1
        assert sorted(result.clusters[0].distinct_users) == ["ALICE", "BOB"]


class TestAggregateRanking:
    def test_top_n_limits_output(self):
        queries = [
            _make_query(f"SELECT * FROM table_{i} WHERE id = 1", query_id=f"q{i}")
            for i in range(20)
        ]
        config = EinblickConfig(days=1, top_n=5)
        result = aggregate(_gen(queries), config)
        assert len(result.clusters) == 5

    def test_impact_score_ranking(self):
        queries = [
            _make_query("SELECT * FROM cheap", credits=0.001, query_id="q1"),
            _make_query("SELECT * FROM expensive", credits=10.0, query_id="q2"),
        ]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        assert result.clusters[0].total_credits > result.clusters[1].total_credits


class TestOffenders:
    def test_user_cost_ranking(self):
        queries = [
            _make_query(user="EXPENSIVE_USER", credits=5.0, query_id="q1"),
            _make_query(user="EXPENSIVE_USER", credits=5.0, query_id="q2"),
            _make_query(user="EXPENSIVE_USER", credits=5.0, query_id="q3"),
            _make_query(user="CHEAP_USER", credits=0.001, query_id="q4"),
            _make_query(user="CHEAP_USER", credits=0.001, query_id="q5"),
            _make_query(user="CHEAP_USER", credits=0.001, query_id="q6"),
        ]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        assert len(result.offenders.top_users_by_cost) == 2
        assert result.offenders.top_users_by_cost[0].user_name == "EXPENSIVE_USER"
        assert result.offenders.top_users_by_cost[0].total_credits > 10

    def test_warehouse_stats(self):
        queries = [
            _make_query(warehouse_name="BIG_WH", credits=1.0, query_id="q1"),
            _make_query(warehouse_name="BIG_WH", credits=1.0, query_id="q2"),
            _make_query(warehouse_name="SMALL_WH", credits=0.01, query_id="q3"),
        ]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        assert len(result.offenders.top_warehouses) == 2
        assert result.offenders.top_warehouses[0].warehouse_name == "BIG_WH"

    def test_slowest_patterns_min_executions(self):
        queries = [
            _make_query("SELECT * FROM slow_table", execution_time_ms=50000, query_id="q1"),
            _make_query("SELECT * FROM slow_table", execution_time_ms=60000, query_id="q2"),
        ]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        assert len(result.offenders.slowest_patterns) == 0

    def test_slowest_patterns_with_enough_executions(self):
        queries = [
            _make_query("SELECT * FROM slow_table", execution_time_ms=50000, query_id="q1"),
            _make_query("SELECT * FROM slow_table", execution_time_ms=60000, query_id="q2"),
            _make_query("SELECT * FROM slow_table", execution_time_ms=70000, query_id="q3"),
        ]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        assert len(result.offenders.slowest_patterns) == 1
        assert result.offenders.slowest_patterns[0].avg_execution_time_ms == 60000

    def test_metadata_totals(self):
        queries = [
            _make_query(credits=1.5, bytes_scanned=1000, query_id="q1"),
            _make_query(credits=2.5, bytes_scanned=2000, query_id="q2"),
        ]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        assert result.metadata.total_credits == 4.0
        assert result.metadata.total_bytes_scanned == 3000

    def test_offenders_in_json_export(self, tmp_path):
        queries = [
            _make_query(user="USER_A", credits=5.0, query_id="q1"),
            _make_query(user="USER_A", credits=5.0, query_id="q2"),
            _make_query(user="USER_A", credits=5.0, query_id="q3"),
        ]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        path = str(tmp_path / "out.json")
        export_json(result, path)
        import json
        with open(path) as f:
            data = json.load(f)
        assert "offenders" in data
        assert len(data["offenders"]["top_users_by_cost"]) > 0

    def test_offenders_in_markdown_export(self, tmp_path):
        queries = [
            _make_query(user="HEAVY_USER", credits=10.0, query_id="q1"),
            _make_query(user="HEAVY_USER", credits=10.0, query_id="q2"),
            _make_query(user="HEAVY_USER", credits=10.0, query_id="q3"),
        ]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        path = str(tmp_path / "out.md")
        export_markdown_summary(result, path)
        with open(path) as f:
            content = f.read()
        assert "Biggest Offenders" in content
        assert "HEAVY_USER" in content


class TestServiceAccountTagging:
    def test_email_user_tagged_as_human(self):
        queries = [
            _make_query(user="alice@company.com", credits=1.0, query_id=f"q{i}")
            for i in range(5)
        ]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        alice = next((u for u in result.offenders.top_users_by_cost if u.user_name == "alice@company.com"), None)
        assert alice is not None
        assert alice.likely_service_account is False

    def test_no_email_user_tagged_as_service(self):
        queries = [
            _make_query(user="FIVETRAN_PROD", credits=5.0, query_id=f"q{i}")
            for i in range(5)
        ]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        svc = next((u for u in result.offenders.top_users_by_cost if u.user_name == "FIVETRAN_PROD"), None)
        assert svc is not None
        assert svc.likely_service_account is True

    def test_markdown_export_separates_service_and_human(self, tmp_path):
        queries = [
            _make_query(user="alice@company.com", credits=5.0, query_id="q1"),
            _make_query(user="bob@company.com", credits=5.0, query_id="q2"),
            _make_query(user="FIVETRAN_PROD", credits=20.0, query_id="q3"),
            _make_query(user="DBT_CLOUD", credits=15.0, query_id="q4"),
        ]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        path = str(tmp_path / "out.md")
        export_markdown_summary(result, path)
        with open(path) as f:
            content = f.read()
        assert "Human Users by" in content
        assert "Service Accounts by" in content
        assert "FIVETRAN_PROD" in content
        assert "alice@company.com" in content


class TestDatabricksPlatform:
    def test_databricks_platform_metadata(self):
        queries = [_make_query(query_id="q1")]
        config = EinblickConfig(platform="databricks", days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        assert result.metadata.platform == "databricks"

    def test_databricks_markdown_uses_estimate_label(self, tmp_path):
        queries = [_make_query(query_id="q1")]
        config = EinblickConfig(platform="databricks", days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        path = str(tmp_path / "out.md")
        export_markdown_summary(result, path)
        with open(path) as f:
            content = f.read()
        assert "Databricks" in content
        assert "Est. Compute Cost" in content
        assert "estimate" in content.lower()

    def test_markdown_has_methodology_disclaimer(self, tmp_path):
        queries = [_make_query(query_id="q1")]
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen(queries), config)
        path = str(tmp_path / "out.md")
        export_markdown_summary(result, path)
        with open(path) as f:
            content = f.read()
        assert "Methodology" in content
        assert "estimated" in content.lower()
        assert "per warehouse" in content.lower() or "warehouse-second" in content.lower()
        assert "QUERY_ATTRIBUTION_HISTORY" in content


class TestExport:
    def test_json_export(self, tmp_path):
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen([_make_query()]), config)
        path = str(tmp_path / "out.json")
        export_json(result, path)
        import json
        with open(path) as f:
            data = json.load(f)
        assert "clusters" in data
        assert "metadata" in data

    def test_markdown_export(self, tmp_path):
        config = EinblickConfig(days=1, top_n=10)
        result = aggregate(_gen([_make_query()]), config)
        path = str(tmp_path / "out.md")
        export_markdown_summary(result, path)
        with open(path) as f:
            content = f.read()
        assert "Einblick Analysis" in content
        assert "Pattern 1" in content
