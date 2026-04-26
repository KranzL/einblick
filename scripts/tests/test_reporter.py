import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from einblick.reporter import generate_report, _format_clusters, _format_offenders, _load_prompt
from einblick.models import (
    AnalysisResult, ExtractionMetadata, QueryCluster, Offenders,
    UserStats, WarehouseStats, SlowestPattern, EinblickConfig,
)


def _make_result(n_clusters=2):
    clusters = []
    for i in range(n_clusters):
        clusters.append(QueryCluster(
            fingerprint=f"fp{i:032x}",
            canonical_sql=f"SELECT * FROM table_{i} WHERE ID = '?'",
            execution_count=100 - i * 10,
            distinct_users=["ALICE", "BOB"],
            distinct_roles=["ANALYST"],
            warehouses=["WH_SMALL"],
            total_credits=5.0 - i,
            avg_execution_time_ms=200.0 + i * 50,
            total_bytes_scanned=1000000,
            tables_referenced=[f"TABLE_{i}"],
            first_seen=datetime(2026, 4, 10),
            last_seen=datetime(2026, 4, 15),
            impact_score=500.0 - i * 50,
        ))

    offenders = Offenders(
        top_users_by_cost=[
            UserStats(
                user_name="ALICE", total_queries=50, total_credits=10.0,
                total_bytes_scanned=5000000, avg_execution_time_ms=300.0,
                max_execution_time_ms=5000, distinct_patterns=5,
                primary_role="ANALYST", primary_warehouse="WH_SMALL",
            )
        ],
    )

    metadata = ExtractionMetadata(
        time_window_days=7,
        total_queries_processed=200,
        distinct_fingerprints=20,
        extraction_timestamp=datetime(2026, 4, 15, 12, 0, 0),
        total_credits=50.0,
        total_bytes_scanned=10000000,
    )

    return AnalysisResult(clusters=clusters, offenders=offenders, metadata=metadata)


class TestFormatClusters:
    def test_formats_all_clusters(self):
        result = _make_result(3)
        output = _format_clusters(result)
        assert "Pattern 1" in output
        assert "Pattern 2" in output
        assert "Pattern 3" in output
        assert "fp" in output
        assert "```sql" in output

    def test_empty_clusters(self):
        result = _make_result(0)
        output = _format_clusters(result)
        assert output == ""


class TestFormatOffenders:
    def test_formats_user_stats(self):
        result = _make_result()
        output = _format_offenders(result)
        assert "ALICE" in output
        assert "SERVICE ACCOUNTS" in output or "HUMAN Users" in output
        assert "[service]" in output or "[human]" in output

    def test_empty_offenders(self):
        result = _make_result()
        result.offenders = Offenders()
        output = _format_offenders(result)
        assert output == "No offender data available."


class TestTemplateInjectionSafety:
    def test_cluster_data_with_template_vars_escaped(self):
        result = _make_result(1)
        result.clusters[0].canonical_sql = "SELECT '{{TIME_WINDOW}}' FROM t"
        output = _format_clusters(result)
        assert "{{TIME_WINDOW}}" in output


class TestLoadPrompt:
    def test_loads_system_prompt(self):
        content = _load_prompt("system-prompt.md")
        assert "data platform architect" in content.lower() or "data modeling" in content.lower()

    def test_loads_analysis_prompt(self):
        content = _load_prompt("analysis-prompt.md")
        assert "{{CLUSTER_DATA}}" in content

    def test_missing_prompt_raises(self):
        with pytest.raises(FileNotFoundError):
            _load_prompt("nonexistent-file.md")


class TestGenerateReport:
    @patch("einblick.reporter._call_anthropic")
    def test_calls_anthropic_by_default(self, mock_call):
        mock_call.return_value = ("# Report\nSome recommendations", [])
        config = EinblickConfig(llm_provider="anthropic")
        result = _make_result()

        report = generate_report(result, config)

        mock_call.assert_called_once()
        assert report == "# Report\nSome recommendations"
        system_prompt = mock_call.call_args[0][0]
        user_prompt = mock_call.call_args[0][1]
        assert "data" in system_prompt.lower()
        assert "200" in user_prompt

    @patch("einblick.reporter._call_anthropic")
    def test_dbt_aware_off_emits_skip_message_into_prompt(self, mock_call):
        mock_call.return_value = ("# Report", [])
        config = EinblickConfig(llm_provider="anthropic", dbt_aware=False)
        generate_report(_make_result(), config)
        user_prompt = mock_call.call_args[0][1]
        assert "not requested" in user_prompt
        assert "Only emit `new_model`" in user_prompt

    @patch("einblick.reporter.load_handoff")
    @patch("einblick.reporter._call_anthropic")
    def test_dbt_aware_on_renders_cached_handoff_into_prompt(self, mock_call, mock_load):
        from einblick.dbt_context import DbtContextHandoff, PatternDbtContext
        mock_load.return_value = DbtContextHandoff(
            generated_at="t",
            environment_id="1",
            total_models_seen=42,
            matched_pattern_count=1,
            patterns={
                "fp_xyz": PatternDbtContext(
                    fingerprint="fp_xyz",
                    matched_model_unique_ids=["model.x.fct_revenue"],
                    matched_models=[{
                        "unique_id": "model.x.fct_revenue",
                        "name": "fct_revenue",
                        "materialized": "view",
                    }],
                ),
            },
            perf={"model.x.fct_revenue": {
                "avg_execution_ms": 47000, "total_runs": 20, "last_run_status": "success"
            }},
        )
        mock_call.return_value = ("# Report", [])
        config = EinblickConfig(llm_provider="anthropic", dbt_aware=True)
        generate_report(_make_result(), config)
        user_prompt = mock_call.call_args[0][1]
        assert "fct_revenue" in user_prompt
        assert "Pattern fp_xyz" in user_prompt
        assert "view" in user_prompt
        mock_load.assert_called_once()

    @patch("einblick.reporter.load_handoff")
    @patch("einblick.reporter._call_anthropic")
    def test_dbt_aware_on_with_no_cached_handoff_emits_fallback_message(self, mock_call, mock_load):
        mock_load.return_value = None
        mock_call.return_value = ("# Report", [])
        config = EinblickConfig(llm_provider="anthropic", dbt_aware=True)
        generate_report(_make_result(), config)
        user_prompt = mock_call.call_args[0][1]
        assert "could not be fetched" in user_prompt

    @patch("einblick.reporter._call_openai")
    def test_calls_openai_when_specified(self, mock_call):
        mock_call.return_value = ("# Report", [])
        config = EinblickConfig(llm_provider="openai")
        result = _make_result()

        report = generate_report(result, config)
        mock_call.assert_called_once()

    def test_raises_on_unknown_provider(self):
        config = EinblickConfig.model_construct(llm_provider="gemini")
        result = _make_result()
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            generate_report(result, config)
