from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from einblick.dbt_proposals import (
    AccessPatternProposal,
    EMIT_DBT_PROPOSALS_TOOL,
    ModifyExistingProposal,
    NewModelProposal,
    parse_proposals,
    render_proposals_section,
)


class TestParseProposals:
    def test_parses_new_model(self):
        raw = {
            "proposals": [
                {
                    "type": "new_model",
                    "name": "orders",
                    "layer": "staging",
                    "materialization": "view",
                    "source_tables": ["RAW.ORDERS"],
                    "proposed_sql": "select * from {{ source('raw', 'orders') }}",
                    "proposed_tests": [
                        {"column": "order_id", "tests": ["unique", "not_null"]}
                    ],
                    "rationale": "Consolidates 3 raw-access patterns",
                    "metrics_addressed": ["abc", "def"],
                }
            ]
        }
        proposals = parse_proposals(raw)
        assert len(proposals) == 1
        p = proposals[0]
        assert isinstance(p, NewModelProposal)
        assert p.name == "orders"
        assert p.layer == "staging"
        assert p.source_tables == ["RAW.ORDERS"]
        assert p.proposed_tests[0].tests == ["unique", "not_null"]
        assert p.metrics_addressed == ["abc", "def"]

    def test_parses_modify_existing_with_from_to_aliases(self):
        raw = {
            "proposals": [
                {
                    "type": "modify_existing",
                    "target_model": "mart.fct_revenue",
                    "change": "materialization",
                    "from": "view",
                    "to": "incremental",
                    "incremental_strategy": "merge",
                    "unique_key": "order_id",
                    "rationale": "Full scan of view cost $240/week",
                }
            ]
        }
        proposals = parse_proposals(raw)
        p = proposals[0]
        assert isinstance(p, ModifyExistingProposal)
        assert p.target_model == "mart.fct_revenue"
        assert p.from_value == "view"
        assert p.to_value == "incremental"
        assert p.incremental_strategy == "merge"

    def test_parses_access_pattern(self):
        raw = {
            "proposals": [
                {
                    "type": "access_pattern",
                    "issue": "Users querying RAW.ORDERS directly",
                    "redirect_to": "mart.fct_orders",
                    "patterns_affected": ["fp1", "fp2"],
                    "suggested_fix": "Add a dbt exposure",
                }
            ]
        }
        proposals = parse_proposals(raw)
        p = proposals[0]
        assert isinstance(p, AccessPatternProposal)
        assert p.redirect_to == "mart.fct_orders"
        assert p.patterns_affected == ["fp1", "fp2"]

    def test_parses_mixed_list(self):
        raw = {
            "proposals": [
                {"type": "new_model", "name": "a", "layer": "staging", "materialization": "view",
                 "source_tables": ["X"], "proposed_sql": "select 1", "rationale": "r"},
                {"type": "modify_existing", "target_model": "b", "change": "materialization",
                 "rationale": "r"},
                {"type": "access_pattern", "issue": "x", "patterns_affected": ["fp"],
                 "suggested_fix": "f"},
            ]
        }
        proposals = parse_proposals(raw)
        assert [type(p).__name__ for p in proposals] == [
            "NewModelProposal", "ModifyExistingProposal", "AccessPatternProposal",
        ]

    def test_rejects_missing_required_fields(self):
        raw = {"proposals": [{"type": "new_model", "name": "a"}]}
        with pytest.raises(Exception):
            parse_proposals(raw)

    def test_rejects_unknown_type(self):
        raw = {"proposals": [{"type": "whatever", "foo": "bar"}]}
        with pytest.raises(Exception):
            parse_proposals(raw)

    def test_empty_list_is_valid(self):
        assert parse_proposals({"proposals": []}) == []

    def test_handles_proposals_as_json_string(self):
        raw = {
            "proposals": '[{"type": "new_model", "name": "orders", "layer": "staging", '
                         '"materialization": "view", "source_tables": ["X"], '
                         '"proposed_sql": "select 1", "rationale": "r"}]'
        }
        proposals = parse_proposals(raw)
        assert len(proposals) == 1
        assert proposals[0].name == "orders"

    def test_handles_entire_input_as_json_string(self):
        raw = '{"proposals": [{"type": "new_model", "name": "n", "layer": "mart", ' \
              '"materialization": "table", "source_tables": ["X"], ' \
              '"proposed_sql": "select 1", "rationale": "r"}]}'
        proposals = parse_proposals(raw)
        assert len(proposals) == 1

    def test_schema_version_defaults(self):
        raw = {"proposals": [{
            "type": "new_model", "name": "n", "layer": "mart",
            "materialization": "table", "source_tables": ["X"],
            "proposed_sql": "select 1", "rationale": "r",
        }]}
        p = parse_proposals(raw)[0]
        assert p.einblick_schema_version == "1"


class TestRenderProposalsSection:
    def test_empty_proposals_renders_empty_string(self):
        assert render_proposals_section([]) == ""

    def test_renders_new_model_with_all_fields(self):
        p = NewModelProposal(
            type="new_model",
            name="orders",
            layer="staging",
            materialization="view",
            source_tables=["RAW.ORDERS"],
            proposed_sql="select id from {{ source('raw', 'orders') }}",
            proposed_tests=[{"column": "id", "tests": ["unique"]}],
            rationale="Replaces 3 raw patterns",
            metrics_addressed=["fp1"],
        )
        out = render_proposals_section([p])
        assert "## Proposed dbt Changes" in out
        assert "`new_model`: staging/orders" in out
        assert "RAW.ORDERS" in out
        assert "Replaces 3 raw patterns" in out
        assert "fp1" in out
        assert "```sql" in out
        assert "select id from" in out

    def test_renders_modify_existing_with_templates(self):
        p = ModifyExistingProposal(
            type="modify_existing",
            target_model="mart.fct_revenue",
            change="materialization",
            **{"from": "view", "to": "incremental"},
            incremental_strategy="merge",
            unique_key="order_id",
            rationale="Saves 80%",
        )
        out = render_proposals_section([p])
        assert "mart.fct_revenue" in out
        assert "`view` -> `incremental`" in out
        assert "merge" in out
        assert "order_id" in out
        assert "Saves 80%" in out

    def test_renders_access_pattern_with_surface_only_note(self):
        p = AccessPatternProposal(
            type="access_pattern",
            issue="Users hit RAW.ORDERS directly",
            redirect_to="mart.fct_orders",
            patterns_affected=["fp1", "fp2"],
            suggested_fix="Deprecation exposure",
        )
        out = render_proposals_section([p])
        assert "Users hit RAW.ORDERS directly" in out
        assert "mart.fct_orders" in out
        assert "fp1, fp2" in out
        assert "einblick will not auto-apply governance changes" in out

    def test_numbers_proposals_sequentially(self):
        p1 = NewModelProposal(
            type="new_model", name="a", layer="staging",
            materialization="view", source_tables=["X"],
            proposed_sql="select 1", rationale="r1",
        )
        p2 = NewModelProposal(
            type="new_model", name="b", layer="mart",
            materialization="table", source_tables=["Y"],
            proposed_sql="select 2", rationale="r2",
        )
        out = render_proposals_section([p1, p2])
        assert "### 1. `new_model`: staging/a" in out
        assert "### 2. `new_model`: mart/b" in out


class TestToolSchema:
    def test_tool_name_is_stable(self):
        assert EMIT_DBT_PROPOSALS_TOOL["name"] == "emit_dbt_proposals"

    def test_tool_has_oneof_for_three_types(self):
        items_schema = EMIT_DBT_PROPOSALS_TOOL["input_schema"]["properties"]["proposals"]["items"]
        oneof = items_schema["oneOf"]
        assert len(oneof) == 3
        types = {branch["properties"]["type"]["const"] for branch in oneof}
        assert types == {"new_model", "modify_existing", "access_pattern"}


class TestReporterIntegration:
    def test_anthropic_extract_parses_tool_use(self):
        from einblick.reporter import _extract_anthropic_content

        text_block = SimpleNamespace(type="text", text="# Executive Summary\nWords.")
        tool_block = SimpleNamespace(
            type="tool_use",
            name="emit_dbt_proposals",
            input={
                "proposals": [
                    {"type": "new_model", "name": "orders", "layer": "staging",
                     "materialization": "view", "source_tables": ["RAW.ORDERS"],
                     "proposed_sql": "select 1", "rationale": "r"},
                ]
            },
        )
        response = SimpleNamespace(content=[text_block, tool_block])
        prose, proposals = _extract_anthropic_content(response)
        assert "Executive Summary" in prose
        assert len(proposals) == 1
        assert isinstance(proposals[0], NewModelProposal)

    def test_anthropic_extract_handles_no_tool_call(self):
        from einblick.reporter import _extract_anthropic_content

        text_block = SimpleNamespace(type="text", text="# Just Prose")
        response = SimpleNamespace(content=[text_block])
        prose, proposals = _extract_anthropic_content(response)
        assert prose == "# Just Prose"
        assert proposals == []

    def test_anthropic_extract_handles_malformed_tool_input(self):
        from einblick.reporter import _extract_anthropic_content

        text_block = SimpleNamespace(type="text", text="# Prose")
        bad_tool = SimpleNamespace(
            type="tool_use",
            name="emit_dbt_proposals",
            input={"proposals": [{"type": "new_model", "name": "x"}]},
        )
        response = SimpleNamespace(content=[text_block, bad_tool])
        prose, proposals = _extract_anthropic_content(response)
        assert proposals == []
        assert "tool call failed validation" in prose

    def test_openai_extract_parses_tool_calls(self):
        from einblick.reporter import _extract_openai_content

        import json
        tool_call = SimpleNamespace(
            function=SimpleNamespace(
                name="emit_dbt_proposals",
                arguments=json.dumps({
                    "proposals": [
                        {"type": "access_pattern", "issue": "x",
                         "patterns_affected": ["fp"], "suggested_fix": "f"},
                    ]
                }),
            )
        )
        message = SimpleNamespace(content="# Prose", tool_calls=[tool_call])
        response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        prose, proposals = _extract_openai_content(response)
        assert "Prose" in prose
        assert len(proposals) == 1
        assert isinstance(proposals[0], AccessPatternProposal)

    def test_openai_extract_handles_no_tool_calls(self):
        from einblick.reporter import _extract_openai_content

        message = SimpleNamespace(content="# Just Prose", tool_calls=None)
        response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        prose, proposals = _extract_openai_content(response)
        assert prose == "# Just Prose"
        assert proposals == []

    def test_anthropic_extract_merges_multiple_tool_calls(self):
        from einblick.reporter import _extract_anthropic_content

        text = SimpleNamespace(type="text", text="# Prose")
        tool_a = SimpleNamespace(
            type="tool_use", name="emit_dbt_proposals",
            input={"proposals": [
                {"type": "new_model", "name": "a", "layer": "staging",
                 "materialization": "view", "source_tables": ["X"],
                 "proposed_sql": "select 1", "rationale": "r"},
            ]},
        )
        tool_b = SimpleNamespace(
            type="tool_use", name="emit_dbt_proposals",
            input={"proposals": [
                {"type": "new_model", "name": "b", "layer": "mart",
                 "materialization": "table", "source_tables": ["Y"],
                 "proposed_sql": "select 2", "rationale": "r"},
            ]},
        )
        response = SimpleNamespace(content=[text, tool_a, tool_b])
        prose, proposals = _extract_anthropic_content(response)
        assert len(proposals) == 2
        assert {p.name for p in proposals} == {"a", "b"}
        assert "called emit_dbt_proposals 2 times" in prose

    def test_openai_extract_merges_multiple_tool_calls(self):
        from einblick.reporter import _extract_openai_content

        import json
        call_a = SimpleNamespace(function=SimpleNamespace(
            name="emit_dbt_proposals",
            arguments=json.dumps({"proposals": [
                {"type": "access_pattern", "issue": "a",
                 "patterns_affected": ["fp1"], "suggested_fix": "f"},
            ]}),
        ))
        call_b = SimpleNamespace(function=SimpleNamespace(
            name="emit_dbt_proposals",
            arguments=json.dumps({"proposals": [
                {"type": "access_pattern", "issue": "b",
                 "patterns_affected": ["fp2"], "suggested_fix": "f"},
            ]}),
        ))
        message = SimpleNamespace(content="# Prose", tool_calls=[call_a, call_b])
        response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        prose, proposals = _extract_openai_content(response)
        assert len(proposals) == 2
        assert "called emit_dbt_proposals 2 times" in prose

    def test_empty_prose_with_proposals_returns_empty_text(self):
        from einblick.reporter import _extract_openai_content

        import json
        tool_call = SimpleNamespace(function=SimpleNamespace(
            name="emit_dbt_proposals",
            arguments=json.dumps({"proposals": [
                {"type": "new_model", "name": "orders", "layer": "staging",
                 "materialization": "view", "source_tables": ["RAW.ORDERS"],
                 "proposed_sql": "select 1", "rationale": "r"},
            ]}),
        ))
        message = SimpleNamespace(content=None, tool_calls=[tool_call])
        response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        prose, proposals = _extract_openai_content(response)
        assert prose == ""
        assert len(proposals) == 1

    def test_empty_prose_synthesizes_header(self):
        from einblick.models import EinblickConfig
        from einblick.reporter import generate_report
        from tests.test_reporter import _make_result
        from unittest.mock import patch

        with patch("einblick.reporter._call_anthropic") as mock_call:
            mock_call.return_value = ("", [
                NewModelProposal(
                    type="new_model", name="x", layer="staging",
                    materialization="view", source_tables=["A"],
                    proposed_sql="select 1", rationale="r",
                ),
            ])
            config = EinblickConfig(llm_provider="anthropic")
            report = generate_report(_make_result(), config)

        assert "# Einblick Analysis" in report
        assert "## Run Summary" in report
        assert "Time window:" in report
        assert "Proposed dbt Changes" in report

    def test_empty_prose_with_no_proposals_stays_empty(self):
        from einblick.reporter import _extract_openai_content

        message = SimpleNamespace(content=None, tool_calls=None)
        response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        prose, proposals = _extract_openai_content(response)
        assert prose == ""
        assert proposals == []


class TestEndToEndReport:
    @patch("einblick.reporter._call_anthropic")
    def test_report_appends_proposals_section(self, mock_call):
        from einblick.models import EinblickConfig
        from einblick.reporter import generate_report
        from tests.test_reporter import _make_result

        mock_call.return_value = (
            "# Executive Summary\n\nSome analysis.",
            [NewModelProposal(
                type="new_model",
                name="orders",
                layer="staging",
                materialization="view",
                source_tables=["RAW.ORDERS"],
                proposed_sql="select 1",
                rationale="r",
            )],
        )
        config = EinblickConfig(llm_provider="anthropic")
        report = generate_report(_make_result(), config)
        assert "# Executive Summary" in report
        assert "## Proposed dbt Changes" in report
        assert "`new_model`: staging/orders" in report

    @patch("einblick.reporter._call_anthropic")
    def test_report_without_proposals_omits_section(self, mock_call):
        from einblick.models import EinblickConfig
        from einblick.reporter import generate_report
        from tests.test_reporter import _make_result

        mock_call.return_value = ("# Just Prose", [])
        config = EinblickConfig(llm_provider="anthropic")
        report = generate_report(_make_result(), config)
        assert report == "# Just Prose"
        assert "Proposed dbt Changes" not in report
