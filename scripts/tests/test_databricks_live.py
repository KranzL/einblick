"""Live Databricks integration tests. SKIPPED unless explicit env vars are set.

These tests connect to a real Databricks SQL warehouse and run the actual
queries einblick uses against `system.query.history`. They exist because pure
unit tests with mocked cursors only verify substring presence in rendered SQL --
they cannot catch column-name typos, dialect quirks, or schema mismatches that
only surface at runtime.

Two real bugs slipped past unit tests and were caught only when einblick was
pointed at a live Databricks workspace:
1. `date_sub(current_timestamp(), INTERVAL X HOUR)` is not valid Databricks SQL
   (date_sub takes integer days, not interval).
2. `q.compute_resource_id` does not exist in `system.query.history`; the
   warehouse id is nested under `q.compute.warehouse_id`.

To run:
    EINBLICK_LIVE_DATABRICKS=1 \
    DATABRICKS_HOST=dbc-xxxx.cloud.databricks.com \
    DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/abc123 \
    DATABRICKS_TOKEN=dapi... \
        pytest scripts/tests/test_databricks_live.py -v

Default behavior with no env vars: every test is skipped.
"""

from __future__ import annotations

import os

import pytest

LIVE = (
    os.environ.get("EINBLICK_LIVE_DATABRICKS") == "1"
    and os.environ.get("DATABRICKS_HOST")
    and os.environ.get("DATABRICKS_HTTP_PATH")
    and os.environ.get("DATABRICKS_TOKEN")
)


pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="Live Databricks tests opt-in: set EINBLICK_LIVE_DATABRICKS=1 plus DATABRICKS_HOST/HTTP_PATH/TOKEN",
)


def _config(**overrides):
    from einblick.config import load_config
    return load_config(cli_overrides={"platform": "databricks", "days": 1, **overrides})


def test_validate_access_succeeds():
    from einblick.connector import connect, validate_access

    config = _config()
    with connect(config) as conn:
        validate_access(conn, "databricks")


def test_count_queries_runs_without_sql_error():
    from einblick.connector import connect
    from einblick.extractor import count_queries

    config = _config(hours=1)
    with connect(config) as conn:
        n = count_queries(conn, config)
    assert isinstance(n, int)
    assert n >= 0


def test_extract_queries_returns_well_formed_rows():
    from einblick.connector import connect
    from einblick.extractor import extract_queries

    config = _config(hours=24)
    with connect(config) as conn:
        rows = list(extract_queries(conn, config))

    for r in rows[:5]:
        assert r.query_id
        assert r.query_text is not None
        assert r.execution_time_ms >= 0


def test_list_users_includes_executor_metadata():
    from einblick.connector import connect
    from einblick.extractor import list_users

    config = _config(hours=24)
    with connect(config) as conn:
        users = list_users(conn, config)

    assert isinstance(users, list)
    if users:
        u = users[0]
        assert "user_name" in u
        assert "query_count" in u
        assert "likely_service_account" in u


def test_full_pipeline_through_aggregate():
    """End-to-end: extract -> aggregate. Catches column-rename bugs that only
    fire when the result actually flows through the cluster pipeline."""
    from einblick.aggregator import aggregate
    from einblick.connector import connect
    from einblick.extractor import extract_queries

    config = _config(hours=24)
    with connect(config) as conn:
        queries = extract_queries(conn, config)
        result = aggregate(queries, config)

    assert result.metadata.platform == "databricks"
    assert result.metadata.total_queries_processed >= 0
