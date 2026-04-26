"""Live MotherDuck integration tests. SKIPPED unless explicit env vars are set.

Same purpose as test_databricks_live.py: catch column-name typos, dialect
quirks, and schema mismatches that only surface against the real
`MD_INFORMATION_SCHEMA.QUERY_HISTORY` table.

Two real bugs slipped past unit tests and were caught only against a real
MotherDuck account:
1. `WHERE QUERY_TYPE = 'SELECT'` filtered everything out -- MotherDuck's
   query_type column is always 'QUERY'. Fixed by removing that filter and
   adding a positive SELECT/WITH prefix check in the noise filter.
2. The setup command's else branch ran Databricks SQL on MotherDuck. Fixed
   by adding a third platform branch.

To run:
    EINBLICK_LIVE_MOTHERDUCK=1 \
    MOTHERDUCK_TOKEN=eyJ... \
        pytest scripts/tests/test_motherduck_live.py -v

Default behavior with no env vars: every test is skipped.
"""

from __future__ import annotations

import os

import pytest

LIVE = (
    os.environ.get("EINBLICK_LIVE_MOTHERDUCK") == "1"
    and os.environ.get("MOTHERDUCK_TOKEN")
)


pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="Live MotherDuck tests opt-in: set EINBLICK_LIVE_MOTHERDUCK=1 plus MOTHERDUCK_TOKEN",
)


def _config(**overrides):
    from einblick.config import load_config
    return load_config(cli_overrides={
        "platform": "motherduck",
        "days": 1,
        "min_duration_ms": 1,
        **overrides,
    })


def test_validate_access_succeeds():
    from einblick.connector import connect, validate_access

    config = _config()
    with connect(config) as conn:
        validate_access(conn, "motherduck")


def test_count_queries_runs_without_sql_error():
    from einblick.connector import connect
    from einblick.extractor import count_queries

    config = _config(hours=24)
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
    from einblick.aggregator import aggregate
    from einblick.connector import connect
    from einblick.extractor import extract_queries

    config = _config(hours=24)
    with connect(config) as conn:
        queries = extract_queries(conn, config)
        result = aggregate(queries, config)

    assert result.metadata.platform == "motherduck"
    assert result.metadata.total_queries_processed >= 0
