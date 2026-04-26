from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from einblick.dbt_proposals import NewModelProposal
from einblick.dbt_context import DbtContextHandoff, PatternDbtContext
from einblick.history import resolve_history_dir
from einblick.models import (
    AnalysisResult,
    ExtractionMetadata,
    Offenders,
    QueryCluster,
    EinblickConfig,
)


def _sample_data_dir() -> Path:
    here = Path(__file__).resolve().parent.parent.parent
    return here / "sample_data"


def _generate_sample_queries():
    import importlib.util
    spec = importlib.util.spec_from_file_location("generate", _sample_data_dir() / "generate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.generate()


@pytest.fixture
def mock_llm():
    sample_proposal = NewModelProposal(
        type="new_model",
        name="orders",
        layer="staging",
        materialization="view",
        source_tables=["RAW.ORDERS"],
        proposed_sql="select * from {{ source('raw', 'orders') }}",
        rationale="mocked",
    )
    with patch("einblick.reporter._call_anthropic") as mock_call:
        mock_call.return_value = ("# Mocked Report\n\nExecutive summary.", [sample_proposal])
        yield mock_call


@pytest.fixture
def mock_no_dbt_context():
    with patch("einblick.reporter.load_handoff") as mock_load:
        mock_load.return_value = None
        yield mock_load


@pytest.fixture
def mock_dbt_context_with_match():
    handoff = DbtContextHandoff(
        generated_at="t",
        environment_id="12345",
        total_models_seen=42,
        matched_pattern_count=1,
        patterns={
            "fp_test": PatternDbtContext(
                fingerprint="fp_test",
                matched_model_unique_ids=["model.x.fct_revenue"],
                matched_models=[{
                    "unique_id": "model.x.fct_revenue",
                    "name": "fct_revenue",
                    "materialized": "view",
                }],
            ),
        },
        perf={"model.x.fct_revenue": {
            "avg_execution_ms": 47000,
            "total_runs": 20,
            "last_run_status": "success",
        }},
    )
    with patch("einblick.reporter.load_handoff") as mock_load:
        mock_load.return_value = handoff
        yield mock_load


def _run_aggregate(config: EinblickConfig) -> AnalysisResult:
    from einblick.aggregator import aggregate
    queries = _generate_sample_queries()
    return aggregate(iter(queries), config)


class TestNoDbtScenarios:
    def test_baseline_extract_no_dbt(self, mock_llm, mock_no_dbt_context):
        from einblick.reporter import generate_report
        config = EinblickConfig(llm_provider="anthropic", dbt_aware=False)
        result = _run_aggregate(config)
        report = generate_report(result, config)
        assert "Mocked Report" in report
        assert "Proposed dbt Changes" in report
        prompt = mock_llm.call_args[0][1]
        assert "not requested" in prompt
        mock_no_dbt_context.assert_not_called()

    def test_no_service_user_exclusions(self, mock_llm, mock_no_dbt_context):
        from einblick.reporter import generate_report
        config = EinblickConfig(
            llm_provider="anthropic",
            exclude_users=[],
            service_user_patterns=[],
        )
        result = _run_aggregate(config)
        generate_report(result, config)
        offender_section = mock_llm.call_args[0][1]
        assert "alex.kumar@company.com" in offender_section or "[human]" in offender_section


class TestDbtAwareScenarios:
    def test_dbt_aware_no_creds_falls_back(self, mock_llm, mock_no_dbt_context):
        from einblick.reporter import generate_report
        config = EinblickConfig(llm_provider="anthropic", dbt_aware=True)
        result = _run_aggregate(config)
        report = generate_report(result, config)
        prompt = mock_llm.call_args[0][1]
        assert "could not be fetched" in prompt
        mock_no_dbt_context.assert_called_once()

    def test_dbt_aware_with_match_renders_into_prompt(
        self, mock_llm, mock_dbt_context_with_match
    ):
        from einblick.reporter import generate_report
        config = EinblickConfig(llm_provider="anthropic", dbt_aware=True)
        result = _run_aggregate(config)
        generate_report(result, config)
        prompt = mock_llm.call_args[0][1]
        assert "fct_revenue" in prompt
        assert "47000" in prompt
        assert "modify_existing" in prompt


class TestAnalysisDepthScenarios:
    @pytest.mark.parametrize("depth,expected_top_n", [
        ("quick", 25),
        ("standard", 100),
        ("deep", 250),
    ])
    def test_depth_caps_top_n(self, depth, expected_top_n, mock_llm, mock_no_dbt_context):
        from einblick.reporter import generate_report
        from einblick.models import DEPTH_PRESETS
        config = EinblickConfig(
            llm_provider="anthropic",
            analysis_depth=depth,
            top_n=DEPTH_PRESETS[depth]["top_n"],
        )
        result = _run_aggregate(config)
        generate_report(result, config)
        prompt = mock_llm.call_args[0][1]
        assert depth in prompt.lower() or _depth_directive_marker(depth) in prompt

    def test_quick_depth_skips_query_rewrites(self, mock_llm, mock_no_dbt_context):
        from einblick.reporter import generate_report
        config = EinblickConfig(llm_provider="anthropic", analysis_depth="quick")
        result = _run_aggregate(config)
        generate_report(result, config)
        prompt = mock_llm.call_args[0][1]
        assert "Skip the Query Rewrites section" in prompt

    def test_deep_depth_requests_second_order_patterns(self, mock_llm, mock_no_dbt_context):
        from einblick.reporter import generate_report
        config = EinblickConfig(llm_provider="anthropic", analysis_depth="deep")
        result = _run_aggregate(config)
        generate_report(result, config)
        prompt = mock_llm.call_args[0][1]
        assert "Second-Order Patterns" in prompt


def _depth_directive_marker(depth: str) -> str:
    return {
        "quick": "Skip the Query Rewrites section",
        "standard": "Cover every section",
        "deep": "Exhaustive analysis",
    }[depth]


class TestTimeWindowScenarios:
    @pytest.mark.parametrize("days", [1, 7, 14, 30])
    def test_time_window_passes_through(self, days, mock_llm, mock_no_dbt_context):
        from einblick.reporter import generate_report
        config = EinblickConfig(llm_provider="anthropic", days=days)
        result = _run_aggregate(config)
        generate_report(result, config)
        prompt = mock_llm.call_args[0][1]
        unit = "day" if days == 1 else "days"
        assert f"past {days} {unit}" in prompt


class TestTimeWindowHoursScenarios:
    @pytest.mark.parametrize("hours,expected", [
        (1, "past 1 hour"),
        (6, "past 6 hours"),
        (12, "past 12 hours"),
    ])
    def test_hours_window_propagates_to_prompt(self, hours, expected, mock_llm, mock_no_dbt_context):
        from einblick.reporter import generate_report
        config = EinblickConfig(llm_provider="anthropic", hours=hours)
        result = _run_aggregate(config)
        generate_report(result, config)
        prompt = mock_llm.call_args[0][1]
        assert expected in prompt


class TestPlatformScenarios:
    @pytest.mark.parametrize("platform", ["snowflake", "databricks", "motherduck"])
    def test_platform_propagates_into_prompt(self, platform, mock_llm, mock_no_dbt_context):
        from einblick.reporter import generate_report
        config = EinblickConfig(llm_provider="anthropic", platform=platform)
        result = _run_aggregate(config)
        generate_report(result, config)
        prompt = mock_llm.call_args[0][1]
        assert platform.title() in prompt


class TestServiceUserScenarios:
    def test_service_users_in_excluded_list_propagate_to_metadata(
        self, mock_llm, mock_no_dbt_context
    ):
        from einblick.reporter import generate_report
        config = EinblickConfig(
            llm_provider="anthropic",
            exclude_users=["FIVETRAN_USER", "DBT_CLOUD"],
        )
        result = _run_aggregate(config)
        generate_report(result, config)
        assert "FIVETRAN_USER" in result.metadata.excluded_users
        assert "DBT_CLOUD" in result.metadata.excluded_users

    def test_service_user_patterns_in_config_persist(self):
        config = EinblickConfig(
            service_user_patterns=["FIVETRAN_*", "DBT_*", "*_BOT"],
        )
        assert "FIVETRAN_*" in config.service_user_patterns


class TestHistoryIntegration:
    def test_run_metadata_records_dbt_aware_flag(self, mock_llm, mock_no_dbt_context):
        from einblick.reporter import generate_report
        config = EinblickConfig(llm_provider="anthropic", dbt_aware=True)
        result = _run_aggregate(config)
        generate_report(result, config)
        assert result.metadata.dbt_aware is True

    def test_run_metadata_records_analysis_depth(self, mock_llm, mock_no_dbt_context):
        from einblick.reporter import generate_report
        config = EinblickConfig(llm_provider="anthropic", analysis_depth="deep")
        result = _run_aggregate(config)
        generate_report(result, config)
        assert result.metadata.analysis_depth == "deep"


class TestProposalsSchema:
    def test_report_includes_proposed_dbt_changes_section(
        self, mock_llm, mock_no_dbt_context
    ):
        from einblick.reporter import generate_report
        config = EinblickConfig(llm_provider="anthropic")
        result = _run_aggregate(config)
        report = generate_report(result, config)
        assert "## Proposed dbt Changes" in report
        assert "new_model" in report

    def test_empty_proposals_list_omits_section(self, mock_no_dbt_context):
        from einblick.reporter import generate_report
        with patch("einblick.reporter._call_anthropic") as mock_call:
            mock_call.return_value = ("# Just prose, no proposals.", [])
            config = EinblickConfig(llm_provider="anthropic")
            result = _run_aggregate(config)
            report = generate_report(result, config)
        assert "Proposed dbt Changes" not in report


class TestLLMBaseUrl:
    def test_base_url_passed_to_openai_client(self):
        from einblick.reporter import _call_openai
        with patch("openai.OpenAI") as mock_client:
            instance = mock_client.return_value
            instance.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="x", tool_calls=None))]
            )
            _call_openai(
                "system", "user", "gpt-4o", base_url="https://api.venice.ai/api/v1"
            )
            call_kwargs = mock_client.call_args.kwargs
            assert call_kwargs.get("base_url") == "https://api.venice.ai/api/v1"

    def test_no_base_url_omits_kwarg(self):
        from einblick.reporter import _call_openai
        with patch("openai.OpenAI") as mock_client:
            instance = mock_client.return_value
            instance.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="x", tool_calls=None))]
            )
            _call_openai("system", "user", "gpt-4o")
            call_kwargs = mock_client.call_args.kwargs
            assert "base_url" not in call_kwargs

    def test_base_url_passed_to_anthropic_client(self):
        from einblick.reporter import _call_anthropic
        with patch("anthropic.Anthropic") as mock_client:
            instance = mock_client.return_value
            instance.messages.create.return_value = MagicMock(content=[])
            _call_anthropic(
                "system", "user", "claude-sonnet-4", base_url="https://anthropic.proxy.example/v1"
            )
            call_kwargs = mock_client.call_args.kwargs
            assert call_kwargs.get("base_url") == "https://anthropic.proxy.example/v1"

    def test_no_base_url_omits_kwarg_anthropic(self):
        from einblick.reporter import _call_anthropic
        with patch("anthropic.Anthropic") as mock_client:
            instance = mock_client.return_value
            instance.messages.create.return_value = MagicMock(content=[])
            _call_anthropic("system", "user", "claude-sonnet-4")
            call_kwargs = mock_client.call_args.kwargs
            assert "base_url" not in call_kwargs
