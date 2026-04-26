from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from sqlscout.config import load_motherduck_credentials
from sqlscout.extractor import _is_likely_service_account
from sqlscout.models import SqlscoutConfig
from sqlscout.warehouse import credits_per_hour, estimate_compute_credits, normalize_warehouse_size


class TestMotherDuckCredentials:
    def test_lowercase_env_var_picked_up(self, monkeypatch):
        monkeypatch.setenv("motherduck_token", "tok-123")
        creds = load_motherduck_credentials(SqlscoutConfig())
        assert creds["token"] == "tok-123"

    def test_uppercase_env_var_works_too(self, monkeypatch):
        monkeypatch.delenv("motherduck_token", raising=False)
        monkeypatch.setenv("MOTHERDUCK_TOKEN", "tok-456")
        creds = load_motherduck_credentials(SqlscoutConfig())
        assert creds["token"] == "tok-456"

    def test_config_field_overrides_env(self, monkeypatch):
        monkeypatch.setenv("motherduck_token", "from-env")
        config = SqlscoutConfig(motherduck_token="from-config")
        creds = load_motherduck_credentials(config)
        assert creds["token"] == "from-config"

    def test_database_field_propagates(self, monkeypatch):
        monkeypatch.setenv("motherduck_token", "tok")
        config = SqlscoutConfig(motherduck_database="my_db")
        creds = load_motherduck_credentials(config)
        assert creds["database"] == "my_db"

    def test_no_token_returns_empty(self, monkeypatch):
        monkeypatch.delenv("motherduck_token", raising=False)
        monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
        creds = load_motherduck_credentials(SqlscoutConfig())
        assert "token" not in creds


class TestMotherDuckCost:
    @pytest.mark.parametrize("instance,rate", [
        ("PULSE", 0.60),
        ("STANDARD", 2.40),
        ("JUMBO", 4.80),
        ("MEGA", 12.00),
        ("GIGA", 36.00),
    ])
    def test_each_duckling_has_a_rate(self, instance, rate):
        assert credits_per_hour(instance, platform="motherduck") == rate

    def test_unknown_duckling_costs_zero(self):
        assert credits_per_hour("UNKNOWN_DUCKLING", platform="motherduck") == 0.0

    def test_estimate_for_one_hour_pulse(self):
        cost = estimate_compute_credits(
            execution_time_ms=3_600_000,
            warehouse_size="PULSE",
            warehouse_name="md-pulse-instance",
            platform="motherduck",
        )
        assert abs(cost - 0.60) < 1e-9

    def test_estimate_for_zero_time_is_zero(self):
        cost = estimate_compute_credits(
            execution_time_ms=0,
            warehouse_size="PULSE",
            warehouse_name="x",
            platform="motherduck",
        )
        assert cost == 0.0

    def test_normalize_keeps_duckling_name(self):
        assert normalize_warehouse_size("pulse") == "PULSE"
        assert normalize_warehouse_size("Standard") == "STANDARD"


class TestMotherDuckPlatformDispatch:
    def test_unknown_platform_raises_in_connector(self):
        from sqlscout.connector import PlatformAccessError, connect
        config = SqlscoutConfig.model_construct(platform="bigquery")
        with pytest.raises(PlatformAccessError, match="Unknown platform"):
            with connect(config):
                pass

    def test_motherduck_routes_through_connector(self, monkeypatch):
        from sqlscout.connector import connect

        monkeypatch.setenv("motherduck_token", "fake-token")
        config = SqlscoutConfig(platform="motherduck")

        fake_duckdb = MagicMock()
        fake_conn = MagicMock()
        fake_duckdb.connect.return_value = fake_conn

        with patch.dict("sys.modules", {"duckdb": fake_duckdb}):
            with connect(config) as conn:
                assert conn is fake_conn

        fake_duckdb.connect.assert_called_once()
        call_args = fake_duckdb.connect.call_args
        assert call_args[0][0] == "md:"
        assert call_args[1]["config"]["motherduck_token"] == "fake-token"

    def test_motherduck_with_database_appends_to_uri(self, monkeypatch):
        from sqlscout.connector import connect

        monkeypatch.setenv("motherduck_token", "fake-token")
        config = SqlscoutConfig(platform="motherduck", motherduck_database="analytics")

        fake_duckdb = MagicMock()
        fake_conn = MagicMock()
        fake_duckdb.connect.return_value = fake_conn

        with patch.dict("sys.modules", {"duckdb": fake_duckdb}):
            with connect(config):
                pass

        assert fake_duckdb.connect.call_args[0][0] == "md:analytics"

    def test_no_token_raises_helpful_error(self, monkeypatch):
        from sqlscout.connector import PlatformAccessError, connect

        monkeypatch.delenv("motherduck_token", raising=False)
        monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
        config = SqlscoutConfig(platform="motherduck")

        with pytest.raises(PlatformAccessError, match="MotherDuck token"):
            with connect(config):
                pass


class TestServiceAccountDetectionOnMotherDuck:
    def test_motherduck_uses_pattern_list_not_at_heuristic(self):
        assert not _is_likely_service_account("luke", platform="motherduck")
        assert not _is_likely_service_account("jane.smith", platform="motherduck")

    def test_motherduck_still_catches_known_service_patterns(self):
        assert _is_likely_service_account("FIVETRAN_USER", platform="motherduck")
        assert _is_likely_service_account("dbt_cloud_runner_svc", platform="motherduck")


class TestPlatformBuiltinServiceUsers:
    def test_snowflake_system_is_service(self):
        assert _is_likely_service_account("SYSTEM", platform="snowflake")
        assert _is_likely_service_account("system", platform="snowflake")

    def test_snowflake_snowpipe_is_service(self):
        assert _is_likely_service_account("SNOWPIPE", platform="snowflake")

    def test_snowflake_worksheets_app_user_is_service(self):
        assert _is_likely_service_account("WORKSHEETS_APP_USER", platform="snowflake")

    def test_snowflake_streamlit_app_user_is_service(self):
        assert _is_likely_service_account("STREAMLIT_APP_USER", platform="snowflake")

    def test_snowflake_real_user_still_human(self):
        assert not _is_likely_service_account("LUKEKRANZ", platform="snowflake")
        assert not _is_likely_service_account("alice@company.com", platform="snowflake")

    def test_motherduck_does_not_treat_system_as_builtin(self):
        assert not _is_likely_service_account("SYSTEM", platform="motherduck")


class TestMotherDuckValidateAccess:
    def test_permission_error_wraps_with_business_plan_hint(self):
        from sqlscout.connector import PlatformAccessError, _validate_motherduck

        conn = MagicMock()
        conn.execute.side_effect = Exception("permission denied")
        with pytest.raises(PlatformAccessError, match="Business plan"):
            _validate_motherduck(conn)

    def test_unrelated_error_propagates_unchanged(self):
        from sqlscout.connector import _validate_motherduck

        conn = MagicMock()
        conn.execute.side_effect = ValueError("network blip")
        with pytest.raises(ValueError, match="network blip"):
            _validate_motherduck(conn)

    def test_validate_passes_when_query_succeeds(self):
        from sqlscout.connector import _validate_motherduck

        conn = MagicMock()
        result = MagicMock()
        result.fetchone.return_value = (1,)
        conn.execute.return_value = result
        _validate_motherduck(conn)
        conn.execute.assert_called_once()


class TestMotherDuckExtractIteration:
    def test_extract_motherduck_streams_rows_through_cursor(self):
        from sqlscout.extractor import _extract_motherduck

        rows = [
            ("q1", "SELECT * FROM analytics.events", "luke", "", "duckling-1",
             1500, 4096, 0.0, datetime(2026, 4, 25), "SELECT", 1500, "STANDARD"),
            ("q2", "SELECT count(*) FROM analytics.users", "luke", "", "duckling-1",
             200, 1024, 0.0, datetime(2026, 4, 25), "SELECT", 200, "STANDARD"),
        ]
        cursor = MagicMock()
        cursor.fetchmany.side_effect = [rows, []]
        conn = MagicMock()
        conn.execute.return_value = cursor

        config = SqlscoutConfig(platform="motherduck", days=1)
        extracted = list(_extract_motherduck(conn, config))
        assert len(extracted) == 2
        assert extracted[0].query_id == "q1"
        assert extracted[0].user_name == "luke"
        assert extracted[0].bytes_scanned == 4096
        assert extracted[0].execution_time_ms == 1500
        assert extracted[0].warehouse_name == "duckling-1"
        assert extracted[0].credits_used > 0
        assert extracted[1].query_id == "q2"
        assert extracted[1].bytes_scanned == 1024


class TestMotherDuckDialect:
    def test_aggregator_uses_duckdb_dialect_for_motherduck(self):
        from sqlscout.fingerprinter import fingerprint_query

        snowflake_fp = fingerprint_query("SELECT 1::INT", dialect="snowflake")
        duckdb_fp = fingerprint_query("SELECT 1::INT", dialect="duckdb")
        assert snowflake_fp[0] == duckdb_fp[0]

        snowflake_struct = fingerprint_query("SELECT {'a': 1}", dialect="snowflake")
        duckdb_struct = fingerprint_query("SELECT {'a': 1}", dialect="duckdb")
        assert duckdb_struct[0] is not None
        assert snowflake_struct[0] is not None
