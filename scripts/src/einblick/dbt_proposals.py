from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, StringConstraints

SCHEMA_VERSION = "1"

_IDENT_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{0,99}$"
_QUALIFIED_IDENT_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*){0,2}$"
_KEY_LIST_PATTERN = r"^\s*[A-Za-z][A-Za-z0-9_]*(\s*,\s*[A-Za-z][A-Za-z0-9_]*)*\s*$"
_SOURCE_TABLE_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,199}$"
_FINGERPRINT_PATTERN = r"^[A-Za-z0-9_]{1,32}$"
_SHORT_VALUE_PATTERN = r"^[A-Za-z0-9_+\- ]{1,80}$"
_TEST_LABEL_PATTERN = r"^[^\n\r\x00`]{1,200}$"

Identifier = Annotated[str, StringConstraints(pattern=_IDENT_PATTERN)]
SourceTable = Annotated[str, StringConstraints(pattern=_SOURCE_TABLE_PATTERN)]
Fingerprint = Annotated[str, StringConstraints(pattern=_FINGERPRINT_PATTERN)]
TestLabel = Annotated[str, StringConstraints(pattern=_TEST_LABEL_PATTERN)]


class ProposedTest(BaseModel):
    column: Identifier
    tests: list[TestLabel] = Field(description="dbt test names, e.g. 'unique', 'not_null', 'accepted_values: [a, b]'")


class NewModelProposal(BaseModel):
    type: Literal["new_model"]
    einblick_schema_version: Literal["1"] = SCHEMA_VERSION
    name: Identifier = Field(
        description="Model name without layer prefix, e.g. 'orders' for stg_orders",
    )
    layer: Literal["staging", "intermediate", "mart"]
    materialization: Literal["view", "table", "incremental", "ephemeral"]
    source_tables: list[SourceTable] = Field(description="Fully-qualified source tables this model reads from")
    proposed_sql: str = Field(description="Ready-to-save dbt model SQL using ref() / source()")
    proposed_tests: list[ProposedTest] = Field(default_factory=list)
    rationale: str
    metrics_addressed: list[Fingerprint] = Field(
        default_factory=list,
        description="einblick pattern fingerprints this model would absorb",
    )


class ModifyExistingProposal(BaseModel):
    type: Literal["modify_existing"]
    einblick_schema_version: Literal["1"] = SCHEMA_VERSION
    target_model: str = Field(
        pattern=_QUALIFIED_IDENT_PATTERN,
        description="Existing dbt model to change, e.g. 'mart.fct_revenue'",
    )
    change: Literal["materialization", "add_clustering", "add_unique_key", "change_schema", "other"]
    from_value: Optional[str] = Field(default=None, alias="from", pattern=_SHORT_VALUE_PATTERN)
    to_value: Optional[str] = Field(default=None, alias="to", pattern=_SHORT_VALUE_PATTERN)
    incremental_strategy: Optional[Literal["merge", "append", "delete+insert", "insert_overwrite"]] = None
    unique_key: Optional[str] = Field(default=None, pattern=_KEY_LIST_PATTERN)
    cluster_by: Optional[list[Identifier]] = None
    rationale: str
    metrics_addressed: list[Fingerprint] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class AccessPatternProposal(BaseModel):
    type: Literal["access_pattern"]
    einblick_schema_version: Literal["1"] = SCHEMA_VERSION
    issue: str = Field(description="One-sentence description of the problematic access pattern")
    redirect_to: Optional[str] = Field(
        default=None,
        pattern=_QUALIFIED_IDENT_PATTERN,
        description="Existing model that users should query instead, if one exists",
    )
    patterns_affected: list[Fingerprint] = Field(description="einblick pattern fingerprints")
    suggested_fix: str


Proposal = Annotated[
    Union[NewModelProposal, ModifyExistingProposal, AccessPatternProposal],
    Field(discriminator="type"),
]


EMIT_DBT_PROPOSALS_TOOL = {
    "name": "emit_dbt_proposals",
    "description": (
        "Emit structured dbt model proposals extracted from your analysis. "
        "Call this exactly once at the end of your response, after you have written "
        "the prose sections. Convert your 'Top Recommendations' into one or more "
        "typed proposals. Use 'new_model' for brand-new models, 'modify_existing' for "
        "changes to models that already exist in the user's project, and 'access_pattern' "
        "for cases where users are querying raw tables that a curated model already covers. "
        "Only emit 'modify_existing' or 'access_pattern' if dbt context was provided -- "
        "without it you cannot know which models exist. Omit the tool call entirely if "
        "you have no concrete proposals."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "proposals": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {
                                "type": {"const": "new_model"},
                                "einblick_schema_version": {"const": "1"},
                                "name": {"type": "string"},
                                "layer": {"enum": ["staging", "intermediate", "mart"]},
                                "materialization": {"enum": ["view", "table", "incremental", "ephemeral"]},
                                "source_tables": {"type": "array", "items": {"type": "string"}},
                                "proposed_sql": {"type": "string"},
                                "proposed_tests": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "column": {"type": "string"},
                                            "tests": {"type": "array", "items": {"type": "string"}},
                                        },
                                        "required": ["column", "tests"],
                                    },
                                },
                                "rationale": {"type": "string"},
                                "metrics_addressed": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": [
                                "type", "name", "layer", "materialization",
                                "source_tables", "proposed_sql", "rationale",
                            ],
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"const": "modify_existing"},
                                "einblick_schema_version": {"const": "1"},
                                "target_model": {"type": "string"},
                                "change": {"enum": ["materialization", "add_clustering", "add_unique_key", "change_schema", "other"]},
                                "from": {"type": "string"},
                                "to": {"type": "string"},
                                "incremental_strategy": {"enum": ["merge", "append", "delete+insert", "insert_overwrite"]},
                                "unique_key": {"type": "string"},
                                "cluster_by": {"type": "array", "items": {"type": "string"}},
                                "rationale": {"type": "string"},
                                "metrics_addressed": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["type", "target_model", "change", "rationale"],
                        },
                        {
                            "type": "object",
                            "properties": {
                                "type": {"const": "access_pattern"},
                                "einblick_schema_version": {"const": "1"},
                                "issue": {"type": "string"},
                                "redirect_to": {"type": "string"},
                                "patterns_affected": {"type": "array", "items": {"type": "string"}},
                                "suggested_fix": {"type": "string"},
                            },
                            "required": ["type", "issue", "patterns_affected", "suggested_fix"],
                        },
                    ]
                },
            }
        },
        "required": ["proposals"],
    },
}


class ProposalsEnvelope(BaseModel):
    proposals: list[Proposal]


def parse_proposals(raw_input: dict) -> list[Proposal]:
    if isinstance(raw_input, str):
        import json
        raw_input = json.loads(raw_input)

    proposals = raw_input.get("proposals") if isinstance(raw_input, dict) else None
    if isinstance(proposals, str):
        import json
        raw_input = {**raw_input, "proposals": json.loads(proposals)}

    return ProposalsEnvelope.model_validate(raw_input).proposals


def render_proposals_section(proposals: list[Proposal]) -> str:
    if not proposals:
        return ""

    lines = ["## Proposed dbt Changes", ""]
    for i, p in enumerate(proposals, start=1):
        if isinstance(p, NewModelProposal):
            lines.extend(_render_new_model(i, p))
        elif isinstance(p, ModifyExistingProposal):
            lines.extend(_render_modify_existing(i, p))
        elif isinstance(p, AccessPatternProposal):
            lines.extend(_render_access_pattern(i, p))
    return "\n".join(lines)


def _render_new_model(i: int, p: NewModelProposal) -> list[str]:
    out = [
        f"### {i}. `new_model`: {p.layer}/{p.name}",
        "",
        f"- **Materialization:** `{p.materialization}`",
        f"- **Source tables:** {', '.join(f'`{t}`' for t in p.source_tables)}",
        f"- **Rationale:** {p.rationale}",
    ]
    if p.metrics_addressed:
        out.append(f"- **Fingerprints addressed:** {', '.join(p.metrics_addressed)}")
    out.extend([
        "",
        "**Proposed SQL:**",
        "",
        "```sql",
        p.proposed_sql.rstrip(),
        "```",
    ])
    if p.proposed_tests:
        out.extend(["", "**Proposed tests:**", ""])
        for t in p.proposed_tests:
            out.append(f"- `{t.column}`: {', '.join(t.tests)}")
    out.append("")
    return out


def _render_modify_existing(i: int, p: ModifyExistingProposal) -> list[str]:
    out = [
        f"### {i}. `modify_existing`: {p.target_model}",
        "",
        f"- **Change:** `{p.change}`",
    ]
    if p.from_value or p.to_value:
        out.append(f"- **From -> To:** `{p.from_value}` -> `{p.to_value}`")
    if p.incremental_strategy:
        out.append(f"- **Incremental strategy:** `{p.incremental_strategy}`")
    if p.unique_key:
        out.append(f"- **Unique key:** `{p.unique_key}`")
    if p.cluster_by:
        out.append(f"- **Cluster by:** {', '.join(f'`{c}`' for c in p.cluster_by)}")
    out.append(f"- **Rationale:** {p.rationale}")
    if p.metrics_addressed:
        out.append(f"- **Fingerprints addressed:** {', '.join(p.metrics_addressed)}")
    out.append("")
    return out


def _render_access_pattern(i: int, p: AccessPatternProposal) -> list[str]:
    out = [
        f"### {i}. `access_pattern`: {p.issue}",
        "",
    ]
    if p.redirect_to:
        out.append(f"- **Should query instead:** `{p.redirect_to}`")
    out.append(f"- **Patterns affected:** {', '.join(p.patterns_affected)}")
    out.append(f"- **Suggested fix:** {p.suggested_fix}")
    out.append("")
    out.append("> Surface-only recommendation -- einblick will not auto-apply governance changes.")
    out.append("")
    return out
