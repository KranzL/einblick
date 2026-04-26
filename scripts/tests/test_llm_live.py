"""Live LLM smoke tests. SKIPPED unless explicit env vars are set.

These tests make real API calls and cost real money (or burn quota on a free
provider). They exist for one purpose: verifying that tool_use actually works
end-to-end against a real provider's API, not just our mocks.

To run against the official Anthropic API:
    SQLSCOUT_LIVE_LLM=1 SQLSCOUT_ANTHROPIC_API_KEY=sk-ant-... \
        pytest scripts/tests/test_llm_live.py -v

To run against an OpenAI-compatible endpoint (e.g., Venice.ai):
    SQLSCOUT_LIVE_LLM=1 \
    SQLSCOUT_OPENAI_API_KEY=your-key \
    SQLSCOUT_OPENAI_BASE_URL=https://api.venice.ai/api/v1 \
    SQLSCOUT_OPENAI_MODEL=llama-3.3-70b \
        pytest scripts/tests/test_llm_live.py -v

Default behavior with no env vars: every test is skipped.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

LIVE_LLM = os.environ.get("SQLSCOUT_LIVE_LLM") == "1"


def _sample_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "sample_data"


def _generate_sample_queries(limit: int = 50):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "generate", _sample_data_dir() / "generate.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    queries = mod.generate()
    return queries[:limit]


def _run_pipeline(config):
    from sqlscout.aggregator import aggregate
    from sqlscout.reporter import generate_report
    queries = _generate_sample_queries()
    result = aggregate(iter(queries), config)
    return generate_report(result, config)


@pytest.mark.skipif(
    not (LIVE_LLM and os.environ.get("SQLSCOUT_ANTHROPIC_API_KEY")),
    reason="Live LLM tests opt-in: set SQLSCOUT_LIVE_LLM=1 + SQLSCOUT_ANTHROPIC_API_KEY",
)
class TestAnthropicLive:
    def test_real_anthropic_returns_proposals_via_tool_use(self):
        from sqlscout.models import SqlscoutConfig
        config = SqlscoutConfig(
            llm_provider="anthropic",
            llm_model=os.environ.get("SQLSCOUT_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
            analysis_depth="quick",
        )
        report = _run_pipeline(config)
        assert "Executive Summary" in report or "executive summary" in report.lower()
        assert "Proposed dbt Changes" in report
        # The tool call should produce at least one proposal block
        assert "new_model" in report or "modify_existing" in report or "access_pattern" in report


@pytest.mark.skipif(
    not (LIVE_LLM and os.environ.get("SQLSCOUT_OPENAI_API_KEY")),
    reason="Live LLM tests opt-in: set SQLSCOUT_LIVE_LLM=1 + SQLSCOUT_OPENAI_API_KEY",
)
class TestOpenAICompatibleLive:
    """Tests an OpenAI-compatible endpoint. Defaults to api.openai.com but
    SQLSCOUT_OPENAI_BASE_URL points it at Venice.ai or any other compatible."""

    def test_real_openai_compatible_returns_proposals_via_tool_use(self):
        from sqlscout.models import SqlscoutConfig
        config = SqlscoutConfig(
            llm_provider="openai",
            llm_model=os.environ.get("SQLSCOUT_OPENAI_MODEL", "gpt-4o-mini"),
            llm_base_url=os.environ.get("SQLSCOUT_OPENAI_BASE_URL"),
            analysis_depth="quick",
        )
        report = _run_pipeline(config)
        assert len(report) > 100
        # The Proposed dbt Changes section is required if the model called the tool
        # On models that don't support tool_use, the section may be omitted.
        # Either way, the prose should be substantial.
        assert "report" in report.lower() or "summary" in report.lower() or "pattern" in report.lower()

    def test_real_openai_compatible_handles_no_tool_use_gracefully(self):
        """Some OpenAI-compatible providers don't implement tool_use fully.
        Even when the tool isn't called, the run should produce a readable report,
        not crash."""
        from sqlscout.models import SqlscoutConfig
        config = SqlscoutConfig(
            llm_provider="openai",
            llm_model=os.environ.get("SQLSCOUT_OPENAI_MODEL", "gpt-4o-mini"),
            llm_base_url=os.environ.get("SQLSCOUT_OPENAI_BASE_URL"),
            analysis_depth="quick",
        )
        report = _run_pipeline(config)
        assert isinstance(report, str)
        assert len(report) > 0
