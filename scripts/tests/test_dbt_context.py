from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sqlscout.dbt_context import (
    DbtContextHandoff,
    PatternDbtContext,
    load_handoff,
    render_dbt_context_for_prompt,
    run_dbt_context_prestep,
)
from sqlscout.dbt_discovery import (
    DbtAuthError,
    DbtConfigError,
    DbtDiscoveryError,
    DbtModelSummary,
    DbtPerformanceStats,
)
from sqlscout.models import (
    AnalysisResult,
    ExtractionMetadata,
    Offenders,
    QueryCluster,
)


def _make_result(patterns: list[tuple[str, list[str]]]) -> AnalysisResult:
    from datetime import datetime
    now = datetime.now()
    clusters = [
        QueryCluster(
            fingerprint=fp,
            canonical_sql="select 1",
            execution_count=10,
            distinct_users=[],
            distinct_roles=[],
            warehouses=[],
            total_credits=1.0,
            avg_execution_time_ms=100.0,
            total_bytes_scanned=0,
            tables_referenced=tables,
            first_seen=now,
            last_seen=now,
        )
        for fp, tables in patterns
    ]
    return AnalysisResult(
        clusters=clusters,
        offenders=Offenders(),
        metadata=ExtractionMetadata(
            platform="snowflake",
            time_window_days=7,
            total_queries_processed=100,
            distinct_fingerprints=len(clusters),
            extraction_timestamp=now,
        ),
    )


class TestPreStepGracefulFailures:
    def test_returns_none_when_no_clusters(self, monkeypatch):
        monkeypatch.setenv("DBT_TOKEN", "x")
        monkeypatch.setenv("DBT_PROD_ENV_ID", "12345")
        result = _make_result([])
        assert run_dbt_context_prestep(result) is None

    def test_returns_none_when_env_id_not_integer(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DBT_TOKEN", "x")
        monkeypatch.setenv("DBT_PROD_ENV_ID", "not-a-number")
        result = _make_result([("fp1", ["RAW.ORDERS"])])
        assert run_dbt_context_prestep(result, output_path=tmp_path / "h.json") is None

    def test_returns_none_when_config_missing(self, monkeypatch):
        monkeypatch.delenv("DBT_TOKEN", raising=False)
        monkeypatch.delenv("DBT_PROD_ENV_ID", raising=False)
        result = _make_result([("fp1", ["RAW.ORDERS"])])
        assert run_dbt_context_prestep(result) is None

    def test_returns_none_on_auth_error(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DBT_TOKEN", "x")
        monkeypatch.setenv("DBT_PROD_ENV_ID", "1")
        mock_client = MagicMock()
        mock_client.get_all_models.side_effect = DbtAuthError("401")
        with patch("sqlscout.dbt_context.DbtDiscoveryClient", return_value=mock_client):
            assert run_dbt_context_prestep(_make_result([("fp1", ["X"])]), output_path=tmp_path / "h.json") is None

    def test_returns_none_on_generic_error(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DBT_TOKEN", "x")
        monkeypatch.setenv("DBT_PROD_ENV_ID", "1")
        mock_client = MagicMock()
        mock_client.get_all_models.side_effect = DbtDiscoveryError("network")
        with patch("sqlscout.dbt_context.DbtDiscoveryClient", return_value=mock_client):
            assert run_dbt_context_prestep(_make_result([("fp1", ["X"])]), output_path=tmp_path / "h.json") is None


class TestPreStepSuccess:
    def test_writes_handoff_and_returns_it(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DBT_TOKEN", "x")
        monkeypatch.setenv("DBT_PROD_ENV_ID", "12345")

        models = [
            DbtModelSummary(
                unique_id="model.x.stg_orders",
                name="stg_orders",
                database="DB",
                schema="STG",
                alias=None,
                materialized="view",
                source_tables=["RAW.ORDERS"],
            ),
        ]
        perf_stats = DbtPerformanceStats(
            unique_id="model.x.stg_orders",
            avg_execution_ms=47000.0,
            max_execution_ms=60000,
            total_runs=20,
            last_run_status="success",
        )
        mock_client = MagicMock()
        mock_client.get_all_models.return_value = models
        mock_client.get_model_performance.return_value = perf_stats

        result = _make_result([("fp_abc", ["RAW.ORDERS"]), ("fp_unmatched", ["OTHER.TABLE"])])
        out_path = tmp_path / "context.json"
        with patch("sqlscout.dbt_context.DbtDiscoveryClient", return_value=mock_client):
            handoff = run_dbt_context_prestep(result, output_path=out_path)

        assert handoff is not None
        assert handoff.environment_id == "12345"
        assert handoff.total_models_seen == 1
        assert handoff.matched_pattern_count == 1
        assert "fp_abc" in handoff.patterns
        assert "fp_unmatched" not in handoff.patterns
        assert handoff.patterns["fp_abc"].matched_model_unique_ids == ["model.x.stg_orders"]
        assert handoff.perf["model.x.stg_orders"]["avg_execution_ms"] == 47000.0

        data = json.loads(out_path.read_text())
        assert data["matched_pattern_count"] == 1

    def test_load_handoff_roundtrips(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DBT_TOKEN", "x")
        monkeypatch.setenv("DBT_PROD_ENV_ID", "12345")

        mock_client = MagicMock()
        mock_client.get_all_models.return_value = [
            DbtModelSummary(
                unique_id="model.x.a", name="a", database="DB",
                schema="S", alias=None, materialized="view",
                source_tables=["RAW.ORDERS"],
            ),
        ]
        mock_client.get_model_performance.return_value = DbtPerformanceStats(
            unique_id="model.x.a",
        )
        result = _make_result([("fp1", ["RAW.ORDERS"])])
        out = tmp_path / "h.json"
        with patch("sqlscout.dbt_context.DbtDiscoveryClient", return_value=mock_client):
            run_dbt_context_prestep(result, output_path=out)

        loaded = load_handoff(out)
        assert loaded is not None
        assert "fp1" in loaded.patterns

    def test_load_handoff_returns_none_for_missing_file(self, tmp_path):
        assert load_handoff(tmp_path / "missing.json") is None

    def test_load_handoff_returns_none_for_malformed_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        assert load_handoff(p) is None

    def test_perf_fetch_capped_to_max(self, monkeypatch, tmp_path):
        from sqlscout.dbt_context import MAX_PERF_FETCHES

        monkeypatch.setenv("DBT_TOKEN", "x")
        monkeypatch.setenv("DBT_PROD_ENV_ID", "12345")

        models = [
            DbtModelSummary(
                unique_id=f"model.x.m{i}",
                name=f"m{i}",
                database="DB",
                schema="S",
                alias=None,
                materialized="view",
                source_tables=[f"RAW.S.T{i}"],
            )
            for i in range(MAX_PERF_FETCHES + 10)
        ]
        mock_client = MagicMock()
        mock_client.get_all_models.return_value = models
        mock_client.get_model_performance.return_value = DbtPerformanceStats(unique_id="x")

        patterns = [(f"fp{i}", [f"RAW.S.T{i}"]) for i in range(MAX_PERF_FETCHES + 10)]
        result = _make_result(patterns)
        with patch("sqlscout.dbt_context.DbtDiscoveryClient", return_value=mock_client):
            handoff = run_dbt_context_prestep(result, output_path=tmp_path / "h.json")

        assert handoff is not None
        assert mock_client.get_model_performance.call_count == MAX_PERF_FETCHES

    def test_write_handoff_failure_does_not_crash(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DBT_TOKEN", "x")
        monkeypatch.setenv("DBT_PROD_ENV_ID", "12345")
        mock_client = MagicMock()
        mock_client.get_all_models.return_value = []
        mock_client.get_model_performance.return_value = DbtPerformanceStats(unique_id="x")
        out_path = tmp_path / "h.json"

        original_open = __import__("os").open

        def _fake_open(path, *args, **kwargs):
            if "h.json" in str(path):
                raise OSError("disk full")
            return original_open(path, *args, **kwargs)

        with patch("sqlscout.dbt_context.DbtDiscoveryClient", return_value=mock_client):
            with patch("sqlscout.dbt_context.os.open", side_effect=_fake_open):
                handoff = run_dbt_context_prestep(_make_result([("fp", ["X"])]), output_path=out_path)

        assert handoff is not None
        assert not out_path.exists()


class TestRenderForPrompt:
    def test_empty_patterns_produces_no_match_line(self):
        h = DbtContextHandoff(
            generated_at="t",
            environment_id="1",
            total_models_seen=50,
            matched_pattern_count=0,
            patterns={},
            perf={},
        )
        out = render_dbt_context_for_prompt(h)
        assert "no top patterns matched" in out
        assert "new_model" in out

    def test_matched_patterns_rendered(self):
        h = DbtContextHandoff(
            generated_at="t",
            environment_id="1",
            total_models_seen=50,
            matched_pattern_count=1,
            patterns={
                "fp_abc": PatternDbtContext(
                    fingerprint="fp_abc",
                    matched_model_unique_ids=["model.x.fct_revenue"],
                    matched_models=[{
                        "unique_id": "model.x.fct_revenue",
                        "name": "fct_revenue",
                        "materialized": "view",
                    }],
                ),
            },
            perf={
                "model.x.fct_revenue": {
                    "avg_execution_ms": 47000,
                    "total_runs": 20,
                    "last_run_status": "success",
                },
            },
        )
        out = render_dbt_context_for_prompt(h)
        assert "fp_abc" in out
        assert "fct_revenue" in out
        assert "view" in out
        assert "47000" in out
        assert "modify_existing" in out
        assert "access_pattern" in out
