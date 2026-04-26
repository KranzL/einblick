from datetime import datetime
from unittest.mock import MagicMock

from sqlscout.extractor import (
    _extract_snowflake,
    _extract_databricks,
    _is_likely_service_account,
    _stream_rows,
    effective_hours,
)
from sqlscout.models import SqlscoutConfig


def _mock_cursor(rows, chunk_size=None):
    cursor = MagicMock()
    remaining = list(rows)

    def fetchmany(size):
        nonlocal remaining
        batch = remaining[:size]
        remaining = remaining[size:]
        return batch

    cursor.fetchmany = fetchmany
    return cursor


def _make_row(
    query_id="q1",
    query_text="SELECT * FROM orders WHERE id = 1",
    user="ALICE",
    role="ANALYST",
    warehouse="WH_SMALL",
    elapsed=500,
    scanned=10000,
    credits=0.01,
    start=None,
    qtype="SELECT",
    execution_time_ms=500,
    warehouse_size="SMALL",
):
    return (
        query_id, query_text, user, role, warehouse,
        elapsed, scanned, credits,
        start or datetime(2026, 4, 15, 10, 0, 0), qtype,
        execution_time_ms, warehouse_size,
    )


class TestStreamRows:
    def test_basic_streaming(self):
        rows = [_make_row(query_id=f"q{i}") for i in range(5)]
        cursor = _mock_cursor(rows)
        results = list(_stream_rows(cursor))
        assert len(results) == 5
        assert results[0].query_id == "q0"

    def test_skips_describe_queries(self):
        rows = [
            _make_row(query_text="DESCRIBE TABLE orders"),
            _make_row(query_text="SELECT * FROM orders"),
            _make_row(query_text="SHOW TABLES"),
        ]
        cursor = _mock_cursor(rows)
        results = list(_stream_rows(cursor))
        assert len(results) == 1
        assert "SELECT" in results[0].query_text

    def test_skips_show_set_use_explain(self):
        rows = [
            _make_row(query_text="SET timezone = 'UTC'"),
            _make_row(query_text="USE DATABASE analytics"),
            _make_row(query_text="EXPLAIN SELECT 1"),
        ]
        cursor = _mock_cursor(rows)
        results = list(_stream_rows(cursor))
        assert len(results) == 0

    def test_skips_call_and_transaction_queries(self):
        rows = [
            _make_row(query_text="CALL SYSTEM$TASK_STATUS('my_task')"),
            _make_row(query_text="BEGIN TRANSACTION"),
            _make_row(query_text="COMMIT"),
            _make_row(query_text="ROLLBACK"),
            _make_row(query_text="SELECT * FROM orders"),
        ]
        cursor = _mock_cursor(rows)
        results = list(_stream_rows(cursor))
        assert len(results) == 1
        assert "orders" in results[0].query_text

    def test_handles_empty_query_text(self):
        rows = [_make_row(query_text="")]
        cursor = _mock_cursor(rows)
        results = list(_stream_rows(cursor))
        assert len(results) == 1
        assert results[0].query_text == ""

    def test_handles_none_fields(self):
        rows = [(
            "q1", "SELECT 1", "USER", "ROLE", None,
            None, None, None, datetime(2026, 1, 1), "SELECT",
            None, None,
        )]
        cursor = _mock_cursor(rows)
        results = list(_stream_rows(cursor))
        assert len(results) == 1
        assert results[0].warehouse_name is None
        assert results[0].execution_time_ms == 0
        assert results[0].bytes_scanned == 0
        assert results[0].credits_used == 0.0

    def test_full_shape_row_uses_warehouse_size_for_cost(self):
        rows = [_make_row(execution_time_ms=3_600_000, warehouse_size="SMALL")]
        cursor = _mock_cursor(rows)
        results = list(_stream_rows(cursor, "snowflake"))
        assert len(results) == 1
        assert results[0].credits_used > 0

    def test_legacy_10_tuple_falls_back_to_total_elapsed(self):
        rows = [(
            "q1", "SELECT * FROM orders", "ALICE", "ANALYST", "WH_SMALL",
            1500, 4096, 0.0, datetime(2026, 4, 15), "SELECT",
        )]
        cursor = _mock_cursor(rows)
        results = list(_stream_rows(cursor, "snowflake"))
        assert len(results) == 1
        assert results[0].execution_time_ms == 1500

    def test_progress_callback_called(self):
        rows = [_make_row(query_id=f"q{i}") for i in range(3)]
        cursor = _mock_cursor(rows)
        counts = []
        list(_stream_rows(cursor, progress_callback=lambda c: counts.append(c)))
        assert len(counts) > 0
        assert counts[-1] == 3


class TestNoiseFilter:
    def test_snowflake_noise_filter_in_sql_by_default(self):
        config = SqlscoutConfig(days=1)
        conn = MagicMock()
        cursor = _mock_cursor([])
        conn.cursor.return_value = cursor

        list(_extract_snowflake(conn, config))
        sql = cursor.execute.call_args[0][0]
        assert "STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'CALL ')" in sql
        assert "STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'SELECT SYSTEM$')" in sql
        assert "SELECT CURRENT_VERSION" in sql
        assert "TOTAL_ELAPSED_TIME >= 100" in sql
        assert "LENGTH(TRIM(QUERY_TEXT)) > 20" in sql

    def test_include_trivial_disables_noise_filter(self):
        config = SqlscoutConfig(days=1, include_trivial=True)
        conn = MagicMock()
        cursor = _mock_cursor([])
        conn.cursor.return_value = cursor

        list(_extract_snowflake(conn, config))
        sql = cursor.execute.call_args[0][0]
        assert "CALL" not in sql
        assert "SYSTEM$" not in sql

    def test_custom_min_duration(self):
        config = SqlscoutConfig(days=1, min_duration_ms=500)
        conn = MagicMock()
        cursor = _mock_cursor([])
        conn.cursor.return_value = cursor

        list(_extract_snowflake(conn, config))
        sql = cursor.execute.call_args[0][0]
        assert "TOTAL_ELAPSED_TIME >= 500" in sql

    def test_databricks_noise_filter(self):
        config = SqlscoutConfig(platform="databricks", days=1)
        conn = MagicMock()
        cursor = _mock_cursor([])
        conn.cursor.return_value = cursor

        list(_extract_databricks(conn, config))
        sql = cursor.execute.call_args[0][0]
        assert "startswith(upper(trim(q.statement_text)), 'CALL ')" in sql
        assert "q.total_duration_ms >= 100" in sql
        assert "SHOW CATALOGS" in sql


class TestSnowflakeExtraction:
    def test_builds_correct_sql_with_excludes(self):
        config = SqlscoutConfig(
            days=7,
            exclude_users=["FIVETRAN", "DBT_CLOUD"],
            exclude_roles=["SYSADMIN"],
        )
        conn = MagicMock()
        cursor = _mock_cursor([])
        conn.cursor.return_value = cursor

        list(_extract_snowflake(conn, config))

        call_args = cursor.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "QUERY_TYPE = 'SELECT'" in sql
        assert "CREATE_TABLE_AS_SELECT" not in sql
        assert "DATEADD('hour'" in sql
        assert "USER_NAME NOT IN" in sql
        assert "ROLE_NAME NOT IN" in sql
        assert params[0] == 7 * 24
        assert "FIVETRAN" in params
        assert "DBT_CLOUD" in params
        assert "SYSADMIN" in params

    def test_hours_overrides_days(self):
        config = SqlscoutConfig(days=7, hours=6)
        conn = MagicMock()
        cursor = _mock_cursor([])
        conn.cursor.return_value = cursor

        list(_extract_snowflake(conn, config))
        params = cursor.execute.call_args[0][1]
        assert params[0] == 6

    def test_no_excludes_no_user_or_role_filter(self):
        config = SqlscoutConfig(days=1)
        conn = MagicMock()
        cursor = _mock_cursor([])
        conn.cursor.return_value = cursor

        list(_extract_snowflake(conn, config))

        sql = cursor.execute.call_args[0][0]
        assert "USER_NAME NOT IN" not in sql
        assert "ROLE_NAME NOT IN" not in sql


class TestDatabricksExtraction:
    def test_builds_correct_sql(self):
        config = SqlscoutConfig(platform="databricks", days=14)
        conn = MagicMock()
        cursor = _mock_cursor([])
        conn.cursor.return_value = cursor

        list(_extract_databricks(conn, config))

        sql = cursor.execute.call_args[0][0]
        assert "system.query.history q" in sql
        assert "system.compute.warehouses w" in sql
        assert "LEFT JOIN system.compute.warehouses" in sql
        assert f"INTERVAL {14 * 24} HOUR" in sql
        assert "q.statement_type = 'SELECT'" in sql
        assert "CREATE_TABLE_AS_SELECT" not in sql
        assert "w.warehouse_size" in sql
        assert "q.execution_duration_ms" in sql
        assert "q.from_result_cache" in sql
        assert "q.client_driver" in sql
        assert "q.executed_by_user_id" in sql

    def test_databricks_sql_parses_in_databricks_dialect(self):
        import sqlglot

        config = SqlscoutConfig(platform="databricks", days=7)
        conn = MagicMock()
        cursor = _mock_cursor([])
        conn.cursor.return_value = cursor

        list(_extract_databricks(conn, config))
        sql = cursor.execute.call_args[0][0]
        sqlglot.parse_one(sql, dialect="databricks")

    def test_databricks_sql_uses_struct_warehouse_id_not_compute_resource_id(self):
        config = SqlscoutConfig(platform="databricks", days=7)
        conn = MagicMock()
        cursor = _mock_cursor([])
        conn.cursor.return_value = cursor

        list(_extract_databricks(conn, config))
        sql = cursor.execute.call_args[0][0]
        assert "q.compute.warehouse_id" in sql
        assert "q.compute_resource_id" not in sql

    def test_databricks_sql_uses_interval_subtraction_not_date_sub_with_interval(self):
        config = SqlscoutConfig(platform="databricks", days=7)
        conn = MagicMock()
        cursor = _mock_cursor([])
        conn.cursor.return_value = cursor

        list(_extract_databricks(conn, config))
        sql = cursor.execute.call_args[0][0]
        assert "date_sub(current_timestamp(), INTERVAL" not in sql
        assert "current_timestamp() - INTERVAL" in sql

    def test_excludes_use_parameterized_queries(self):
        config = SqlscoutConfig(
            platform="databricks", days=7,
            exclude_users=["svc_fivetran@company.com"],
        )
        conn = MagicMock()
        cursor = _mock_cursor([])
        conn.cursor.return_value = cursor

        list(_extract_databricks(conn, config))

        call_args = cursor.execute.call_args
        sql = call_args[0][0]
        assert ":u0" in sql
        assert "svc_fivetran@company.com" not in sql

    def test_exclude_cache_hits_filter(self):
        config = SqlscoutConfig(platform="databricks", days=1, exclude_cache_hits=True)
        conn = MagicMock()
        cursor = _mock_cursor([])
        conn.cursor.return_value = cursor

        list(_extract_databricks(conn, config))
        sql = cursor.execute.call_args[0][0]
        assert "from_result_cache" in sql
        assert "= FALSE" in sql

    def test_cache_hits_not_excluded_by_default(self):
        config = SqlscoutConfig(platform="databricks", days=1)
        conn = MagicMock()
        cursor = _mock_cursor([])
        conn.cursor.return_value = cursor

        list(_extract_databricks(conn, config))
        sql = cursor.execute.call_args[0][0]
        assert "COALESCE(q.from_result_cache, FALSE) = FALSE" not in sql


class TestServicePrincipalDetection:
    def test_uuid_detected_as_service(self):
        assert _is_likely_service_account(
            "some.display.name@databricks.com",
            user_id="abcd1234-5678-90ef-1234-567890abcdef",
        ) is True

    def test_non_uuid_user_id_not_service(self):
        assert _is_likely_service_account(
            "alice@company.com",
            user_id="12345",
        ) is False

    def test_uuid_wins_over_email_heuristic(self):
        assert _is_likely_service_account(
            "service-principal@databricks.com",
            user_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        ) is True


class TestEffectiveHours:
    def test_default_days_to_hours(self):
        config = SqlscoutConfig(days=7)
        assert effective_hours(config) == 7 * 24

    def test_hours_overrides(self):
        config = SqlscoutConfig(days=7, hours=1)
        assert effective_hours(config) == 1

    def test_hours_of_zero_falls_back(self):
        config = SqlscoutConfig(days=30, hours=None)
        assert effective_hours(config) == 30 * 24


class TestServiceAccountDetection:
    def test_email_user_is_not_service(self):
        assert _is_likely_service_account("alice@company.com") is False
        assert _is_likely_service_account("bob.smith@company.io") is False

    def test_no_email_is_service(self):
        assert _is_likely_service_account("FIVETRAN_PROD") is True
        assert _is_likely_service_account("DBT_CLOUD") is True
        assert _is_likely_service_account("LOOKER_USER") is True

    def test_empty_name_is_service(self):
        assert _is_likely_service_account("") is True

    def test_prefix_pattern_matches(self):
        patterns = ["FIVETRAN_*", "DBT_*"]
        assert _is_likely_service_account("FIVETRAN_PROD", patterns=patterns) is True
        assert _is_likely_service_account("DBT_CLOUD", patterns=patterns) is True
        assert _is_likely_service_account("alice@company.com", patterns=patterns) is False

    def test_suffix_pattern_matches(self):
        patterns = ["*_SVC", "*_BOT"]
        assert _is_likely_service_account("airflow_svc", patterns=patterns) is True
        assert _is_likely_service_account("slack_bot", patterns=patterns) is True

    def test_pattern_case_insensitive(self):
        patterns = ["fivetran_*"]
        assert _is_likely_service_account("FIVETRAN_PROD", patterns=patterns) is True

    def test_service_role_matches(self):
        assert _is_likely_service_account(
            "alice@company.com",
            role_name="SERVICE_ROLE",
            service_roles=["SERVICE_ROLE", "INTEGRATION_ROLE"],
        ) is True

    def test_email_user_without_matching_pattern_is_human(self):
        patterns = ["FIVETRAN_*"]
        assert _is_likely_service_account("alice@company.com", patterns=patterns) is False
