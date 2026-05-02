from __future__ import annotations

from pathlib import Path
from typing import Any

from einblick.dbt_context import (
    DEFAULT_CONTEXT_PATH,
    load_handoff,
    render_dbt_context_for_prompt,
)
from einblick.dbt_proposals import (
    EMIT_DBT_PROPOSALS_TOOL,
    Proposal,
    parse_proposals,
    render_proposals_section,
)
from einblick.models import AnalysisResult, EinblickConfig

_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-5",
}

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent.parent
_REFERENCES_DIR = _REPO_ROOT / "skills" / "einblick-analysis" / "references"


def generate_report(result: AnalysisResult, config: EinblickConfig) -> str:
    system_prompt = _load_prompt("system-prompt.md")
    analysis_template = _load_prompt("analysis-prompt.md")

    cluster_data = _format_clusters(result)
    offender_data = _format_offenders(result)
    dbt_context_block = _maybe_build_dbt_context(result, config)

    safe_cluster = cluster_data.replace("{{", "{ {").replace("}}", "} }")
    safe_offender = offender_data.replace("{{", "{ {").replace("}}", "} }")
    safe_dbt_context = dbt_context_block.replace("{{", "{ {").replace("}}", "} }")

    from einblick.aggregator import _format_time_window
    analysis_prompt = analysis_template.replace("{{TIME_WINDOW}}", _format_time_window(result.metadata))
    analysis_prompt = analysis_prompt.replace("{{TOTAL_QUERIES}}", f"{result.metadata.total_queries_processed:,}")
    analysis_prompt = analysis_prompt.replace("{{DISTINCT_PATTERNS}}", f"{result.metadata.distinct_fingerprints:,}")
    analysis_prompt = analysis_prompt.replace("{{TOP_N}}", str(len(result.clusters)))
    analysis_prompt = analysis_prompt.replace("{{CLUSTER_DATA}}", safe_cluster)
    analysis_prompt = analysis_prompt.replace("{{OFFENDER_DATA}}", safe_offender)
    analysis_prompt = analysis_prompt.replace("{{USER_CONTEXT}}", _build_user_context(config))
    analysis_prompt = analysis_prompt.replace("{{PLATFORM}}", config.platform.title())
    analysis_prompt = analysis_prompt.replace("{{ANALYSIS_DEPTH}}", _build_depth_directive(config.analysis_depth))
    analysis_prompt = analysis_prompt.replace("{{DBT_CONTEXT}}", safe_dbt_context)

    model = config.llm_model or _DEFAULT_MODELS.get(config.llm_provider, "claude-sonnet-4-6")

    if config.llm_provider == "anthropic":
        prose, proposals = _call_anthropic(
            system_prompt, analysis_prompt, model, config.llm_base_url
        )
    elif config.llm_provider == "openai":
        prose, proposals = _call_openai(
            system_prompt, analysis_prompt, model, config.llm_base_url
        )
    else:
        raise ValueError(f"Unknown LLM provider: {config.llm_provider}")

    if not prose.strip() and proposals:
        prose = _build_data_only_header(result, config)
    elif not prose.strip() and not proposals:
        prose = _build_empty_response_header(result, config)

    proposals_md = render_proposals_section(proposals)
    if proposals_md:
        return prose.rstrip() + "\n\n" + proposals_md
    return prose


def _run_summary_lines(result: AnalysisResult) -> str:
    from einblick.aggregator import _format_time_window
    md = result.metadata
    return (
        f"## Run Summary\n\n"
        f"- Platform: {md.platform.title()}\n"
        f"- Time window: {_format_time_window(md)}\n"
        f"- Queries processed: {md.total_queries_processed:,}\n"
        f"- Distinct patterns: {md.distinct_fingerprints:,}\n"
        f"- Total estimated compute cost: {md.total_credits:.4f}\n"
        f"- Analysis depth: {md.analysis_depth}\n"
    )


def _build_empty_response_header(result: AnalysisResult, config: EinblickConfig) -> str:
    md = result.metadata
    return (
        f"# Einblick Analysis ({md.platform.title()})\n\n"
        f"> LLM returned an empty response (no prose, no tool call). Re-run; "
        f"this usually clears.\n\n"
        + _run_summary_lines(result)
    )


def _build_data_only_header(result: AnalysisResult, config: EinblickConfig) -> str:
    md = result.metadata
    return (
        f"# Einblick Analysis ({md.platform.title()})\n\n"
        f"<!-- LLM emitted proposals via tool_use but no prose. Common on "
        f"OpenAI-compatible providers; switch to gpt-5 or claude-sonnet-4-6 for "
        f"the full prose report. -->\n\n"
        + _run_summary_lines(result)
        + f"- dbt-aware: {md.dbt_aware}\n"
    )


_DEPTH_DIRECTIVES = {
    "quick": (
        "Keep this fast. Skip the Query Rewrites section entirely. "
        "Limit Top Recommendations to the 3-5 highest-impact patterns. "
        "Skip Patterns Skipped. Aim for a report under 300 lines."
    ),
    "standard": (
        "Produce the full standard report. Top 10 query rewrites in the Query Rewrites section. "
        "Cover every section in the Output Format and call emit_dbt_proposals once at the end."
    ),
    "deep": (
        "Exhaustive analysis. Top 25 query rewrites in the Query Rewrites section. "
        "Call out long-tail patterns that individually look small but aggregate meaningfully. "
        "Include a 'Second-Order Patterns' subsection identifying patterns whose optimization "
        "would help other patterns that depend on the same tables."
    ),
}


def _build_depth_directive(depth: str) -> str:
    return _DEPTH_DIRECTIVES.get(depth, _DEPTH_DIRECTIVES["standard"])


def _maybe_build_dbt_context(result: AnalysisResult, config: EinblickConfig) -> str:
    if not config.dbt_aware:
        return (
            "dbt context: not requested (run without --dbt-aware). "
            "Only emit `new_model` proposals -- `modify_existing` and `access_pattern` "
            "require knowing which models already exist."
        )
    handoff = load_handoff(DEFAULT_CONTEXT_PATH)
    if handoff is None:
        return (
            "dbt context: requested but could not be fetched (misconfigured auth "
            "or network error; see logs). Continuing without dbt context -- emit "
            "only `new_model` proposals."
        )
    return render_dbt_context_for_prompt(handoff)


def _build_user_context(config: EinblickConfig) -> str:
    lines = [f"Platform: {config.platform.title()}."]
    if config.context_ingestion:
        lines.append(f"Ingestion: {config.context_ingestion}.")
    if config.context_freshness:
        lines.append(f"Freshness requirement: {config.context_freshness}.")
    if config.context_transform:
        lines.append(f"Transformation layer: {config.context_transform}.")
    if config.context_spend:
        lines.append(f"Daily spend: {config.context_spend}.")
    if len(lines) == 1:
        lines.append("CLI mode (no interactive context provided -- keep recommendations platform-agnostic).")
    return " ".join(lines)


def _resolve_api_key(provider: str) -> str | None:
    import os
    scoped = f"EINBLICK_{provider.upper()}_API_KEY"
    generic = f"{provider.upper()}_API_KEY"
    return os.environ.get(scoped) or os.environ.get(generic)


def _call_anthropic(
    system_prompt: str, user_prompt: str, model: str, base_url: str | None = None
) -> tuple[str, list[Proposal]]:
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "anthropic package not installed. Run: pip install einblick[llm]"
        )

    api_key = _resolve_api_key("anthropic")
    kwargs: dict[str, Any] = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    client = anthropic.Anthropic(**kwargs)
    response = client.messages.create(
        model=model,
        max_tokens=32768,
        system=system_prompt,
        tools=[EMIT_DBT_PROPOSALS_TOOL],
        messages=[{"role": "user", "content": user_prompt}],
    )
    return _extract_anthropic_content(response)


def _extract_anthropic_content(response: Any) -> tuple[str, list[Proposal]]:
    text_parts: list[str] = []
    proposals: list[Proposal] = []
    tool_call_count = 0
    for block in response.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(block.text)
        elif btype == "tool_use" and block.name == "emit_dbt_proposals":
            tool_call_count += 1
            try:
                proposals.extend(parse_proposals(block.input))
            except Exception as e:
                text_parts.append(
                    f"\n\n<!-- einblick: emit_dbt_proposals tool call failed validation: {e} -->\n"
                )
    if tool_call_count > 1:
        text_parts.append(
            f"\n\n<!-- einblick: LLM called emit_dbt_proposals {tool_call_count} times; "
            f"proposals were merged into a single list. -->\n"
        )
    return "\n".join(text_parts), proposals


def _call_openai(
    system_prompt: str, user_prompt: str, model: str, base_url: str | None = None
) -> tuple[str, list[Proposal]]:
    try:
        import openai
    except ImportError:
        raise ImportError(
            "openai package not installed. Run: pip install einblick[llm]"
        )

    api_key = _resolve_api_key("openai")
    kwargs: dict[str, Any] = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    client = openai.OpenAI(**kwargs)

    openai_tool = {
        "type": "function",
        "function": {
            "name": EMIT_DBT_PROPOSALS_TOOL["name"],
            "description": EMIT_DBT_PROPOSALS_TOOL["description"],
            "parameters": EMIT_DBT_PROPOSALS_TOOL["input_schema"],
        },
    }

    response = client.chat.completions.create(
        model=model,
        tools=[openai_tool],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return _extract_openai_content(response)


def _extract_openai_content(response: Any) -> tuple[str, list[Proposal]]:
    message = response.choices[0].message
    text = message.content or ""
    proposals: list[Proposal] = []
    emit_call_count = 0
    if getattr(message, "tool_calls", None):
        import json
        for call in message.tool_calls:
            fn = getattr(call, "function", None)
            if fn and fn.name == "emit_dbt_proposals":
                emit_call_count += 1
                try:
                    proposals.extend(parse_proposals(json.loads(fn.arguments)))
                except Exception as e:
                    text += f"\n\n<!-- einblick: emit_dbt_proposals tool call failed validation: {e} -->\n"
    if emit_call_count > 1:
        text += (
            f"\n\n<!-- einblick: LLM called emit_dbt_proposals {emit_call_count} times; "
            f"proposals were merged into a single list. -->\n"
        )
    return text, proposals


def _load_prompt(filename: str) -> str:
    import os
    env_dir = os.environ.get("EINBLICK_PROMPTS_DIR")
    if env_dir:
        env_path = Path(env_dir) / filename
        if env_path.exists():
            return env_path.read_text()

    path = _REFERENCES_DIR / filename
    if path.exists():
        return path.read_text()

    plugin_root_env = Path(__file__).resolve().parent
    for _ in range(6):
        candidate = plugin_root_env / "skills" / "einblick-analysis" / "references" / filename
        if candidate.exists():
            return candidate.read_text()
        plugin_root_env = plugin_root_env.parent

    raise FileNotFoundError(
        f"Could not find {filename}. Expected at {_REFERENCES_DIR} or "
        f"$EINBLICK_PROMPTS_DIR. If installed as a plugin, ensure the skills/ "
        f"directory is present."
    )


_CANONICAL_SQL_CAP = 8000
_LIST_FIELD_CAP = 10


def _format_clusters(result: AnalysisResult) -> str:
    lines = []
    for i, c in enumerate(result.clusters, 1):
        sql = c.canonical_sql
        if len(sql) > _CANONICAL_SQL_CAP:
            sql = sql[:_CANONICAL_SQL_CAP] + "\n-- ...truncated for prompt budget"
        roles = ", ".join(c.distinct_roles[:_LIST_FIELD_CAP])
        if len(c.distinct_roles) > _LIST_FIELD_CAP:
            roles += f" (+{len(c.distinct_roles) - _LIST_FIELD_CAP} more)"
        warehouses = ", ".join(c.warehouses[:_LIST_FIELD_CAP])
        if len(c.warehouses) > _LIST_FIELD_CAP:
            warehouses += f" (+{len(c.warehouses) - _LIST_FIELD_CAP} more)"
        lines.extend([
            f"### Pattern {i} | Fingerprint: {c.fingerprint}",
            f"- Executions: {c.execution_count:,}",
            f"- Users ({len(c.distinct_users)}): {', '.join(c.distinct_users[:_LIST_FIELD_CAP])}",
            f"- Roles ({len(c.distinct_roles)}): {roles}",
            f"- Warehouses ({len(c.warehouses)}): {warehouses}",
            f"- Est. compute cost: {c.total_credits:.4f}",
            f"- Avg execution time: {c.avg_execution_time_ms:.0f}ms",
            f"- Bytes scanned: {c.total_bytes_scanned:,}",
            f"- Tables: {', '.join(c.tables_referenced)}",
            f"- Active: {c.first_seen} to {c.last_seen}",
            f"- Impact score: {c.impact_score:.4f}",
            f"",
            f"```sql",
            sql,
            f"```",
            f"",
        ])
    return "\n".join(lines)


def _format_offenders(result: AnalysisResult) -> str:
    off = result.offenders
    has_any_data = any([
        off.top_users_by_cost,
        off.top_users_by_runtime,
        off.top_warehouses,
        off.slowest_patterns,
        off.most_scanned_patterns,
    ])
    if not has_any_data:
        return "No offender data available."

    lines = []
    lines.append("### IMPORTANT: Cost numbers are ESTIMATES, not actual credits.")
    lines.append("The `compute-cost-est` values below are computed as `execution_time × warehouse_size_credits_per_hour + cloud_services_overhead`. Because Snowflake bills per warehouse (not per query) and many queries share a warehouse concurrently, summed estimates will OVER-COUNT actual billed credits. Rankings are reliable; absolute totals are upper-bound approximations. Snowflake's per-query attribution view (`QUERY_ATTRIBUTION_HISTORY`) exists but updates infrequently and omits many queries, so we can't use it for exact numbers. When writing the report, explicitly call this out in the executive summary and cost-analysis sections. Use phrasing like 'estimated compute cost' or 'compute-cost score' -- avoid stating numbers as definitive Snowflake credits.")
    lines.append("")

    if off.top_users_by_cost:
        human_users = [u for u in off.top_users_by_cost if not u.likely_service_account]
        service_users = [u for u in off.top_users_by_cost if u.likely_service_account]

        lines.append("### Users tagged [service] are automated accounts (BI tools, ETL, dbt) detected by lack of '@' in username.")
        lines.append("Service accounts running a lot of queries is expected and does not by itself indicate a problem. Focus optimization on the *patterns* they run (dashboards, scheduled jobs), not the users. Service-account offenders that stand out should motivate materialization of the SQL they repeat.")
        lines.append("Human users (tagged [human]) are ad hoc analysts -- their cost reflects queries humans wrote and can change.")
        lines.append("")

        if human_users:
            lines.append("### Top HUMAN Users by Cost")
            for u in human_users[:10]:
                lines.append(
                    f"- **[human] {u.user_name}**: {u.total_queries:,} queries, {u.total_credits:.4f} compute-cost-est, "
                    f"avg {u.avg_execution_time_ms:.0f}ms, max {u.max_execution_time_ms:,}ms, "
                    f"{u.distinct_patterns} patterns, role={u.primary_role}, warehouse={u.primary_warehouse}"
                )
            lines.append("")

        if service_users:
            lines.append("### Top SERVICE ACCOUNTS by Cost")
            for u in service_users[:10]:
                lines.append(
                    f"- **[service] {u.user_name}**: {u.total_queries:,} queries, {u.total_credits:.4f} compute-cost-est, "
                    f"avg {u.avg_execution_time_ms:.0f}ms, max {u.max_execution_time_ms:,}ms, "
                    f"{u.distinct_patterns} patterns, role={u.primary_role}, warehouse={u.primary_warehouse}"
                )
            lines.append("")

    if off.top_users_by_runtime:
        lines.append("### Top Users by Total Runtime")
        for u in off.top_users_by_runtime[:10]:
            tag = "[service]" if u.likely_service_account else "[human]"
            lines.append(
                f"- **{tag} {u.user_name}**: {u.total_queries:,} queries, avg {u.avg_execution_time_ms:.0f}ms, "
                f"max {u.max_execution_time_ms:,}ms, {u.total_credits:.4f} compute-cost-est"
            )
        lines.append("")

    if off.top_warehouses:
        lines.append("### Top Warehouses by Cost")
        for w in off.top_warehouses:
            lines.append(
                f"- **{w.warehouse_name}**: {w.total_queries:,} queries, {w.total_credits:.4f} compute-cost-est, "
                f"avg {w.avg_execution_time_ms:.0f}ms, {w.distinct_users} users, "
                f"avg cost/query={w.avg_query_cost:.6f}"
            )
        lines.append("")

    if off.slowest_patterns:
        lines.append("### Slowest Query Patterns (by avg runtime, min 3 executions)")
        for p in off.slowest_patterns[:10]:
            lines.extend([
                f"- **{p.fingerprint}**: avg {p.avg_execution_time_ms:,.0f}ms, "
                f"max {p.max_execution_time_ms:,}ms, {p.execution_count:,} executions, "
                f"{p.total_credits:.4f} compute-cost-est",
                f"  Tables: {', '.join(p.tables_referenced)}",
                f"  ```sql",
                f"  {p.canonical_sql[:200]}",
                f"  ```",
            ])
        lines.append("")

    if off.most_scanned_patterns:
        lines.append("### Most Data Scanned (by total bytes, min 3 executions)")
        for p in off.most_scanned_patterns[:10]:
            lines.extend([
                f"- **{p.fingerprint}**: {p.execution_count:,} executions, "
                f"{p.total_credits:.4f} compute-cost-est, avg {p.avg_execution_time_ms:,.0f}ms",
                f"  Tables: {', '.join(p.tables_referenced)}",
                f"  ```sql",
                f"  {p.canonical_sql[:200]}",
                f"  ```",
            ])
        lines.append("")

    return "\n".join(lines) if lines else "No offender data available."
