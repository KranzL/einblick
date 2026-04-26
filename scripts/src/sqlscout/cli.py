from __future__ import annotations

import os
import shlex
import sys

import click
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from sqlscout.aggregator import aggregate, export_json, export_markdown_summary
from sqlscout.config import load_config
from sqlscout.connector import connect, validate_access, PlatformAccessError
from sqlscout.extractor import count_queries, effective_hours, extract_queries, list_users
from sqlscout.history import DEFAULT_KEEP, list_runs, resolve_history_dir, store_run
from sqlscout.redact import format_error as _format_error

console = Console()


def _save_to_history(
    platform: str,
    result,
    rerun_command: str,
    history_dir,
    keep: int,
    full_report_md: str | None = None,
) -> None:
    import json
    import tempfile

    try:
        json_blob = json.dumps(result.model_dump(mode="json"), indent=2, default=str)
    except Exception as e:
        console.print(
            f"[yellow]Warning:[/yellow] could not serialize history JSON: {_format_error(e)}. "
            f"Run continues; history not saved."
        )
        return

    md_blob: str | None
    if full_report_md is not None:
        md_blob = full_report_md
    else:
        md_blob = None
        tmp_path = None
        try:
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
            tmp.close()
            tmp_path = tmp.name
            export_markdown_summary(result, tmp_path, rerun_command=rerun_command)
            with open(tmp_path) as f:
                md_blob = f.read()
        except Exception:
            md_blob = None
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    try:
        path = store_run(
            platform=platform,
            json_content=json_blob,
            md_content=md_blob,
            override_dir=history_dir,
            keep=keep,
        )
        console.print(f"[dim]Saved to history: {path}[/dim]")
    except Exception as e:
        console.print(
            f"[yellow]Warning:[/yellow] could not write history: {_format_error(e)}. "
            f"Run continues; report on stdout/--output is still valid."
        )


def _run_dbt_aware_prestep(result) -> None:
    from sqlscout.dbt_context import DEFAULT_CONTEXT_PATH, run_dbt_context_prestep

    console.print("[dim]Cross-referencing patterns against dbt project...[/dim]")
    handoff = run_dbt_context_prestep(result)
    if handoff is None:
        console.print(
            "[yellow]Warning:[/yellow] dbt Discovery API not reachable. "
            "Continuing without dbt context."
        )
        return
    console.print(
        f"[dim]Matched {handoff.matched_pattern_count} of {len(result.clusters)} "
        f"patterns to existing dbt models. Context saved to {DEFAULT_CONTEXT_PATH}[/dim]"
    )


_SENSITIVE_FLAGS = ("--slack-webhook", "--llm-base-url")


def _user_set(ctx: click.Context, param_name: str) -> bool:
    try:
        source = ctx.get_parameter_source(param_name)
    except Exception:
        return True
    return source not in (
        click.core.ParameterSource.DEFAULT,
        click.core.ParameterSource.DEFAULT_MAP,
    )


def _gated_overrides(ctx: click.Context, mapping: dict[str, tuple[str, object]]) -> dict:
    out: dict = {}
    for param_name, (override_key, value) in mapping.items():
        if _user_set(ctx, param_name):
            out[override_key] = value
    return out


from sqlscout.aggregator import format_window as _format_window_hours


def _scrub_sensitive_flags(argv: list[str]) -> list[str]:
    out: list[str] = []
    skip_next_value = False
    for tok in argv:
        if skip_next_value:
            skip_next_value = False
            continue
        if tok in _SENSITIVE_FLAGS:
            skip_next_value = True
            continue
        if any(tok.startswith(f"{flag}=") for flag in _SENSITIVE_FLAGS):
            continue
        out.append(tok)
    return out


def _rerun_command(resolved_excludes: list[str] | None = None) -> str:
    argv = sys.argv[1:]
    if resolved_excludes is not None:
        argv = _substitute_auto_exclude(argv, resolved_excludes)
    argv = _scrub_sensitive_flags(argv)
    return " ".join(["sqlscout"] + [shlex.quote(a) for a in argv])


def _substitute_auto_exclude(argv: list[str], resolved: list[str]) -> list[str]:
    out: list[str] = []
    skip_next_value = False
    saw_value_for_exclude = False
    existing = list(resolved)
    for i, tok in enumerate(argv):
        if skip_next_value:
            skip_next_value = False
            continue
        if tok == "--auto-exclude-service-users":
            continue
        if tok == "--exclude-users":
            next_tok = argv[i + 1] if i + 1 < len(argv) else None
            if next_tok is not None and not next_tok.startswith("--"):
                saw_value_for_exclude = True
                merged = ",".join(sorted(set(
                    [x.strip() for x in next_tok.split(",") if x.strip()]
                    + existing
                )))
                out.append(tok)
                out.append(merged)
                skip_next_value = True
            continue
        if tok.startswith("--exclude-users="):
            saw_value_for_exclude = True
            prefix, _, val = tok.partition("=")
            merged = ",".join(sorted(set(
                [x.strip() for x in val.split(",") if x.strip()]
                + existing
            )))
            out.append(f"{prefix}={merged}")
            continue
        out.append(tok)
    if not saw_value_for_exclude and existing:
        out.extend(["--exclude-users", ",".join(sorted(set(existing)))])
    return out


def _require_llm_api_key(provider: str) -> None:
    scoped = f"SQLSCOUT_{provider.upper()}_API_KEY"
    generic = f"{provider.upper()}_API_KEY"
    other = "openai" if provider == "anthropic" else "anthropic"

    if os.environ.get(scoped):
        return
    if os.environ.get(generic):
        console.print(
            f"[yellow]Warning:[/yellow] using {generic}; prefer {scoped} to avoid "
            f"collisions with Claude Code."
        )
        return
    console.print(
        f"[red]Missing {scoped}.[/red] Set it, run --provider {other}, "
        f"or use /sqlscout inside Claude Code (no key needed)."
    )
    sys.exit(1)


_GROUP_HELP = """\
Find repeated query patterns in Snowflake, Databricks, or MotherDuck and
recommend what to materialize, cluster, or denormalize.

\b
Two ways to run this:
  /sqlscout              -- inside Claude Code / Codex; no API key needed.
  sqlscout analyze       -- cron / Airflow / CI; needs an LLM API key.
"""


@click.group(help=_GROUP_HELP)
def main():
    pass


def _find_sample_data():
    from pathlib import Path
    env_override = os.environ.get("SQLSCOUT_SAMPLE_DATA_DIR")
    candidates = []
    if env_override:
        candidates.append(Path(env_override) / "generate.py")
    candidates.extend([
        Path(__file__).resolve().parent.parent.parent.parent / "sample_data" / "generate.py",
        Path.cwd() / "sample_data" / "generate.py",
    ])
    for c in candidates:
        if c.exists():
            return c.parent
    return None


def _run_analyze_sample(config, output):
    sample_dir = _find_sample_data()
    if not sample_dir:
        console.print("[red]Error:[/red] Cannot find sample_data/generate.py")
        sys.exit(1)

    import importlib.util
    spec = importlib.util.spec_from_file_location("generate", sample_dir / "generate.py")
    gen_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen_module)

    console.print("Using sample dataset (775 generated queries) -- still calls the LLM")
    if config.dbt_aware:
        console.print(
            "[yellow]Note:[/yellow] --dbt-aware is ignored in --sample mode "
            "(would make outbound HTTP to dbt Cloud)."
        )
        config = config.model_copy(update={"dbt_aware": False})
    queries = gen_module.generate()
    result = aggregate(iter(queries), config)
    console.print(
        f"Processed {result.metadata.total_queries_processed:,} queries "
        f"into {len(result.clusters)} clusters"
    )

    console.print("Generating report via LLM...")
    from sqlscout.reporter import generate_report
    report = generate_report(result, config)

    if output:
        with open(output, "w") as f:
            f.write(report)
        console.print(f"Report written to {output}")
    else:
        click.echo(report)

    if config.slack_webhook_url:
        console.print(
            "[dim]Slack post skipped in --sample mode "
            "(diff would compare against unrelated real runs).[/dim]"
        )


def _maybe_post_to_slack(config, result, output, history_dir_override):
    if not config.slack_webhook_url or config.slack_mode == "off":
        return

    from sqlscout.slack import compute_diff_against_previous, post_report, should_post

    diff = compute_diff_against_previous(result, history_dir_override=history_dir_override)
    if not should_post(config.slack_mode, diff):
        if config.slack_mode == "alert":
            if diff is None:
                console.print(
                    "[dim]Slack alert mode: no prior run on disk to diff against; "
                    "next run will compare. Re-run with --slack-mode digest if you want "
                    "the first run posted unconditionally.[/dim]"
                )
            else:
                console.print(
                    "[dim]Slack: nothing interesting changed vs last run, skipping post.[/dim]"
                )
        return

    console.print("[dim]Posting Slack digest...[/dim]")
    ok = post_report(
        webhook_url=config.slack_webhook_url,
        result=result,
        report_path=str(output) if output else None,
        diff=diff,
    )
    if ok:
        console.print("[dim]Slack post sent.[/dim]")
    else:
        console.print(
            "[yellow]Slack post failed.[/yellow] Common causes: webhook URL typo, "
            "Slack workspace removed the incoming-webhook integration, or transient "
            "network failure. The full report is on stdout/--output and saved to history."
        )


def _run_sample(config, output, fmt):
    sample_dir = _find_sample_data()
    if not sample_dir:
        console.print("[red]Error:[/red] Cannot find sample_data/generate.py")
        sys.exit(1)

    import importlib.util
    spec = importlib.util.spec_from_file_location("generate", sample_dir / "generate.py")
    gen_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen_module)

    console.print("Using sample dataset (775 generated queries)")
    queries = gen_module.generate()
    result = aggregate(iter(queries), config)

    console.print(
        f"Processed {result.metadata.total_queries_processed:,} queries "
        f"into {len(result.clusters)} clusters"
    )

    rerun = _rerun_command()

    if output:
        if fmt == "json":
            export_json(result, output)
        else:
            export_markdown_summary(result, output, rerun_command=rerun)
        console.print(f"Output written to {output}")
    else:
        if fmt == "json":
            click.echo(result.model_dump_json(indent=2))
        else:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
            tmp.close()
            export_markdown_summary(result, tmp.name, rerun_command=rerun)
            with open(tmp.name) as f:
                click.echo(f.read())
            os.unlink(tmp.name)


@main.command(help="""Pull query history, fingerprint, cluster patterns. No
LLM call. Writes JSON or a markdown summary. This is what /sqlscout runs
under the hood; for a full LLM-written report use `sqlscout analyze`.""")
@click.option("--platform", type=click.Choice(["snowflake", "databricks", "motherduck"]), default="snowflake")
@click.option("--days", type=click.Choice(["1", "7", "14", "30"]), default="7")
@click.option("--hours", type=int, default=None, help="Time window in hours. Overrides --days when set. Use 1 or 6 for quick previews.")
@click.option("--output", "-o", type=click.Path(), default=None)
@click.option("--format", "fmt", type=click.Choice(["json", "markdown"]), default="json")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--connection", default=None, help="Snowflake-only: name of a section in ~/.snowsql/config (or ~/.snowflake/config.toml). Ignored for --platform databricks / motherduck.")
@click.option("--exclude-users", default=None)
@click.option("--exclude-roles", default=None)
@click.option("--auto-exclude-service-users", is_flag=True, default=False, help="Auto-exclude usernames matching your service-user patterns (falls back to no-'@' heuristic).")
@click.option("--service-user-pattern", multiple=True, help="Glob pattern identifying service users (e.g., 'FIVETRAN_*', '*_SVC'). Can be specified multiple times.")
@click.option("--service-user-role", multiple=True, help="Role name that means 'service account' (e.g., SERVICE_ROLE). Can be specified multiple times.")
@click.option("--min-duration-ms", type=int, default=None, help="Skip queries shorter than this many ms. Defaults to the value for --analysis-depth (500 quick / 100 standard / 50 deep).")
@click.option("--include-trivial", is_flag=True, default=False, help="Include all queries (disables SELECT 1, CALL SYSTEM$, CURRENT_VERSION etc. filters).")
@click.option("--exclude-cache-hits", is_flag=True, default=False, help="[Databricks] Exclude queries served entirely from result cache.")
@click.option("--accurate-cost", is_flag=True, default=False, help="[Databricks] Join system.billing.usage for actual hourly-prorated DBU costs (slower, more accurate).")
@click.option("--top-n", type=int, default=None, help="How many query pattern clusters to analyze. Defaults to the value for --analysis-depth (25 quick / 100 standard / 250 deep).")
@click.option("--analysis-depth", type=click.Choice(["quick", "standard", "deep"]), default="standard", help="How deep to look: 'quick' (top 25, fast), 'standard' (top 100, default), 'deep' (top 250, long tail).")
@click.option("--dbt-aware", is_flag=True, default=False, help="Cross-reference patterns against your dbt project via the Discovery API. Requires DBT_HOST / DBT_TOKEN / DBT_PROD_ENV_ID. Falls back gracefully on auth or network errors.")
@click.option("--keep-db", is_flag=True, default=False)
@click.option("--sample", is_flag=True, default=False, help="Use built-in sample data instead of connecting to a live platform")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show additional progress details.")
@click.option("--no-history", is_flag=True, default=False, help="Skip saving this run to ~/.sqlscout/history/. History is on by default so run-over-run diffs work.")
@click.option("--history-dir", type=click.Path(), default=None, help="Override history location (default: ~/.sqlscout/history/, or $SQLSCOUT_HISTORY_DIR).")
@click.option("--keep-history", type=int, default=DEFAULT_KEEP, help=f"How many past runs to keep per platform. Default: {DEFAULT_KEEP}. Use 0 for unlimited.")
@click.pass_context
def extract(ctx, platform, days, hours, output, fmt, config_path, connection, exclude_users, exclude_roles, auto_exclude_service_users, service_user_pattern, service_user_role, min_duration_ms, include_trivial, exclude_cache_hits, accurate_cost, top_n, analysis_depth, dbt_aware, keep_db, sample, verbose, no_history, history_dir, keep_history):
    from sqlscout.models import resolve_preset
    resolved_top_n, resolved_min_duration = resolve_preset(analysis_depth, top_n, min_duration_ms)

    overrides = _gated_overrides(ctx, {
        "platform": ("platform", platform),
        "days": ("days", int(days)),
        "fmt": ("output_format", fmt),
        "keep_db": ("keep_db", keep_db),
        "include_trivial": ("include_trivial", include_trivial),
        "exclude_cache_hits": ("exclude_cache_hits", exclude_cache_hits),
        "accurate_cost": ("accurate_cost", accurate_cost),
        "analysis_depth": ("analysis_depth", analysis_depth),
        "dbt_aware": ("dbt_aware", dbt_aware),
    })
    if top_n is not None or _user_set(ctx, "analysis_depth"):
        overrides["top_n"] = resolved_top_n
    if min_duration_ms is not None or _user_set(ctx, "analysis_depth"):
        overrides["min_duration_ms"] = resolved_min_duration
    if hours is not None:
        overrides["hours"] = hours
    if connection:
        if platform != "snowflake":
            console.print(
                f"[yellow]Warning:[/yellow] --connection is Snowflake-only and is "
                f"ignored on --platform {platform}."
            )
        else:
            overrides["snowflake_connection"] = connection
    if exclude_users:
        overrides["exclude_users"] = [u.strip() for u in exclude_users.split(",")]
    if exclude_roles:
        overrides["exclude_roles"] = [r.strip() for r in exclude_roles.split(",")]
    if service_user_pattern:
        overrides["service_user_patterns"] = list(service_user_pattern)
    if service_user_role:
        overrides["service_user_roles"] = list(service_user_role)

    config = load_config(cli_overrides=overrides, config_path=config_path)

    if sample:
        _run_sample(config, output, fmt)
        return

    try:
        with connect(config) as conn:
            console.print(f"Connected to {platform.title()}")
            window_hours = effective_hours(config)
            window_label = _format_window_hours(window_hours)
            console.print(f"Time window: [cyan]{window_label}[/cyan]")

            validate_access(conn, config.platform)

            if auto_exclude_service_users:
                if verbose:
                    console.print("Identifying service accounts...")
                users = list_users(conn, config)
                service_users = [u["user_name"] for u in users if u["likely_service_account"]]
                if service_users:
                    existing = set(config.exclude_users)
                    new_excludes = [u for u in service_users if u not in existing]
                    config = config.model_copy(update={"exclude_users": list(existing | set(service_users))})
                    console.print(
                        f"Auto-excluding [yellow]{len(new_excludes)}[/yellow] likely service account(s): "
                        f"{', '.join(new_excludes[:5])}{'...' if len(new_excludes) > 5 else ''}"
                    )

            expected = count_queries(conn, config)
            if expected == 0:
                console.print("[yellow]No queries matched the filters. Nothing to extract.[/yellow]")
                return
            console.print(f"Expected queries: [green]{expected:,}[/green]")
            if expected > 500_000:
                console.print(
                    "[yellow]Heads up:[/yellow] this is a lot. Consider a shorter window "
                    "(e.g., `--hours 6`) or more aggressive user/role exclusions."
                )

            fetched_count = {"n": 0}
            processed_count = {"n": 0}

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=40),
                MofNCompleteColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
                refresh_per_second=8,
            ) as progress:
                extract_task = progress.add_task(
                    f"Fetched from {platform.title()}",
                    total=expected,
                )
                agg_task = progress.add_task(
                    "Processed locally (fingerprint + index)",
                    total=expected,
                )

                def on_extract_progress(count: int):
                    fetched_count["n"] = count
                    lag = max(0, count - processed_count["n"])
                    progress.update(
                        extract_task,
                        completed=min(count, expected),
                        description=(
                            f"Fetched from {platform.title()} (lag +{lag:,})"
                            if lag else f"Fetched from {platform.title()}"
                        ),
                    )

                def on_agg_progress(phase: str, count: int):
                    processed_count["n"] = count
                    progress.update(
                        agg_task,
                        completed=min(count, expected),
                        description=f"Processed locally ({phase})",
                    )

                queries = extract_queries(conn, config, progress_callback=on_extract_progress)
                result = aggregate(queries, config, progress_callback=on_agg_progress)

                progress.update(extract_task, completed=expected, total=expected,
                                description="Fetch complete")
                progress.update(agg_task, completed=expected, total=expected,
                                description="Processing complete")

            console.print(
                f"Processed {result.metadata.total_queries_processed:,} queries "
                f"into {len(result.clusters)} clusters"
            )

            if config.dbt_aware:
                _run_dbt_aware_prestep(result)

            rerun = _rerun_command(resolved_excludes=list(config.exclude_users))

            if not no_history:
                _save_to_history(platform, result, rerun, history_dir, keep_history)

            if output:
                if fmt == "json":
                    export_json(result, output)
                else:
                    export_markdown_summary(result, output, rerun_command=rerun)
                console.print(f"Output written to {output}")
            else:
                if fmt == "json":
                    click.echo(result.model_dump_json(indent=2))
                else:
                    import tempfile
                    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
                    tmp.close()
                    export_markdown_summary(result, tmp.name, rerun_command=rerun)
                    with open(tmp.name) as f:
                        click.echo(f.read())
                    os.unlink(tmp.name)

    except PlatformAccessError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {_format_error(e)}")
        sys.exit(1)


@main.command(help="""Extract query history, cluster patterns, and ask an LLM
to write the report. For cron / Airflow / CI. Needs SQLSCOUT_ANTHROPIC_API_KEY
or SQLSCOUT_OPENAI_API_KEY (the SQLSCOUT_-prefixed forms avoid colliding with
Claude Code). For interactive use, run /sqlscout instead.""")
@click.option("--platform", type=click.Choice(["snowflake", "databricks", "motherduck"]), default="snowflake")
@click.option("--days", type=click.Choice(["1", "7", "14", "30"]), default="7")
@click.option("--hours", type=int, default=None, help="Time window in hours. Overrides --days when set. Use 1 or 6 for quick previews.")
@click.option("--output", "-o", type=click.Path(), default=None)
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--connection", default=None, help="Snowflake-only: name of a section in ~/.snowsql/config (or ~/.snowflake/config.toml). Ignored for --platform databricks / motherduck.")
@click.option("--exclude-users", default=None)
@click.option("--exclude-roles", default=None)
@click.option("--auto-exclude-service-users", is_flag=True, default=False, help="Auto-exclude usernames matching your service-user patterns (falls back to no-'@' heuristic).")
@click.option("--service-user-pattern", multiple=True, help="Glob pattern identifying service users (e.g., 'FIVETRAN_*', '*_SVC'). Can be specified multiple times.")
@click.option("--service-user-role", multiple=True, help="Role name that means 'service account'. Can be specified multiple times.")
@click.option("--min-duration-ms", type=int, default=None, help="Skip queries shorter than this many ms. Defaults to the value for --analysis-depth (500 quick / 100 standard / 50 deep).")
@click.option("--include-trivial", is_flag=True, default=False, help="Include all queries (disables SELECT 1, CALL SYSTEM$, CURRENT_VERSION etc. filters).")
@click.option("--exclude-cache-hits", is_flag=True, default=False, help="[Databricks] Exclude queries served entirely from result cache.")
@click.option("--accurate-cost", is_flag=True, default=False, help="[Databricks] Join system.billing.usage for actual hourly-prorated DBU costs (slower, more accurate).")
@click.option("--top-n", type=int, default=None, help="How many query pattern clusters to analyze. Defaults to the value for --analysis-depth.")
@click.option("--analysis-depth", type=click.Choice(["quick", "standard", "deep"]), default="standard", help="How deep to look: 'quick' (top 25, short report, no rewrites), 'standard' (top 100, default), 'deep' (top 250, long tail, exhaustive rewrites).")
@click.option("--dbt-aware", is_flag=True, default=False, help="Cross-reference patterns against your dbt project via the Discovery API. Requires DBT_HOST / DBT_TOKEN / DBT_PROD_ENV_ID. Falls back gracefully on auth or network errors.")
@click.option("--provider", type=click.Choice(["anthropic", "openai"]), default="anthropic")
@click.option("--model", default=None)
@click.option("--llm-base-url", default=None, help="Override the LLM API base URL. Useful for OpenAI-compatible endpoints (e.g., Venice.ai: https://api.venice.ai/api/v1) or Anthropic-compatible proxies. Use with --provider matching the protocol.")
@click.option("--slack-webhook", default=None, envvar="SQLSCOUT_SLACK_WEBHOOK_URL", help="Slack incoming webhook URL. Sends a Block Kit summary after the report is written. Also reads $SQLSCOUT_SLACK_WEBHOOK_URL.")
@click.option("--slack-mode", type=click.Choice(["off", "digest", "alert"]), default="digest", help="When to post: 'digest' always posts, 'alert' only when something interesting changed vs last run (>=20% cost delta, >=3 new patterns, or any disappeared), 'off' never posts. Ignored if --slack-webhook is unset.")
@click.option("--context-ingestion", default=None, help="Ingestion pattern (e.g., 'Managed connectors (Fivetran)'). Shapes LLM recommendations.")
@click.option("--context-freshness", default=None, help="Freshness requirement (e.g., 'Daily', 'Real-time').")
@click.option("--context-transform", default=None, help="Transformation layer (e.g., 'dbt', 'Platform-native', 'None').")
@click.option("--context-spend", default=None, help="Daily spend bracket (e.g., 'Under $100', '$1,000-$10,000').")
@click.option("--sample", is_flag=True, default=False, help="Use built-in sample data instead of connecting to Snowflake/Databricks. Useful for smoke-testing the LLM pipeline end-to-end. Still calls the LLM API.")
@click.option("--keep-db", is_flag=True, default=False)
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show additional progress details.")
@click.option("--no-history", is_flag=True, default=False, help="Skip saving this run to ~/.sqlscout/history/.")
@click.option("--history-dir", type=click.Path(), default=None, help="Override history location (default: ~/.sqlscout/history/, or $SQLSCOUT_HISTORY_DIR).")
@click.option("--keep-history", type=int, default=DEFAULT_KEEP, help=f"How many past runs to keep per platform. Default: {DEFAULT_KEEP}. Use 0 for unlimited.")
@click.pass_context
def analyze(ctx, platform, days, hours, output, config_path, connection, exclude_users, exclude_roles, auto_exclude_service_users, service_user_pattern, service_user_role, min_duration_ms, include_trivial, exclude_cache_hits, accurate_cost, top_n, analysis_depth, dbt_aware, provider, model, llm_base_url, slack_webhook, slack_mode, context_ingestion, context_freshness, context_transform, context_spend, sample, keep_db, verbose, no_history, history_dir, keep_history):
    _require_llm_api_key(provider)

    from sqlscout.models import resolve_preset
    resolved_top_n, resolved_min_duration = resolve_preset(analysis_depth, top_n, min_duration_ms)

    overrides = _gated_overrides(ctx, {
        "platform": ("platform", platform),
        "days": ("days", int(days)),
        "analysis_depth": ("analysis_depth", analysis_depth),
        "include_trivial": ("include_trivial", include_trivial),
        "exclude_cache_hits": ("exclude_cache_hits", exclude_cache_hits),
        "accurate_cost": ("accurate_cost", accurate_cost),
        "provider": ("llm_provider", provider),
        "keep_db": ("keep_db", keep_db),
        "dbt_aware": ("dbt_aware", dbt_aware),
        "slack_mode": ("slack_mode", slack_mode),
    })
    if top_n is not None or _user_set(ctx, "analysis_depth"):
        overrides["top_n"] = resolved_top_n
    if min_duration_ms is not None or _user_set(ctx, "analysis_depth"):
        overrides["min_duration_ms"] = resolved_min_duration
    if hours is not None:
        overrides["hours"] = hours
    if model:
        overrides["llm_model"] = model
    if llm_base_url:
        overrides["llm_base_url"] = llm_base_url
    if slack_webhook:
        overrides["slack_webhook_url"] = slack_webhook
    if connection:
        if platform != "snowflake":
            console.print(
                f"[yellow]Warning:[/yellow] --connection is Snowflake-only and is "
                f"ignored on --platform {platform}."
            )
        else:
            overrides["snowflake_connection"] = connection
    if exclude_users:
        overrides["exclude_users"] = [u.strip() for u in exclude_users.split(",")]
    if exclude_roles:
        overrides["exclude_roles"] = [r.strip() for r in exclude_roles.split(",")]
    if service_user_pattern:
        overrides["service_user_patterns"] = list(service_user_pattern)
    if service_user_role:
        overrides["service_user_roles"] = list(service_user_role)
    if context_ingestion:
        overrides["context_ingestion"] = context_ingestion
    if context_freshness:
        overrides["context_freshness"] = context_freshness
    if context_transform:
        overrides["context_transform"] = context_transform
    if context_spend:
        overrides["context_spend"] = context_spend

    config = load_config(cli_overrides=overrides, config_path=config_path)

    if sample:
        _run_analyze_sample(config, output)
        return

    try:
        with connect(config) as conn:
            console.print(f"Connected to {platform.title()}")
            validate_access(conn, config.platform)

            if auto_exclude_service_users:
                if verbose:
                    console.print("Identifying service accounts...")
                users_list = list_users(conn, config)
                service_users = [u["user_name"] for u in users_list if u["likely_service_account"]]
                if service_users:
                    existing = set(config.exclude_users)
                    new_excludes = [u for u in service_users if u not in existing]
                    config = config.model_copy(update={"exclude_users": list(existing | set(service_users))})
                    console.print(
                        f"Auto-excluding [yellow]{len(new_excludes)}[/yellow] likely service account(s): "
                        f"{', '.join(new_excludes[:5])}{'...' if len(new_excludes) > 5 else ''}"
                    )

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Extracting and processing...", total=None)
                queries = extract_queries(conn, config)
                result = aggregate(queries, config)
                progress.update(task, completed=1, total=1)

            console.print(
                f"Processed {result.metadata.total_queries_processed:,} queries "
                f"into {len(result.clusters)} clusters"
            )

            if config.dbt_aware:
                _run_dbt_aware_prestep(result)
            console.print("Generating report via LLM...")

            from sqlscout.reporter import generate_report
            report = generate_report(result, config)

            if not no_history:
                _save_to_history(
                    platform, result,
                    _rerun_command(resolved_excludes=list(config.exclude_users)),
                    history_dir, keep_history,
                    full_report_md=report,
                )

            if output:
                with open(output, "w") as f:
                    f.write(report)
                console.print(f"Report written to {output}")
            else:
                click.echo(report)

            _maybe_post_to_slack(config, result, output, history_dir)

    except PlatformAccessError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {_format_error(e)}")
        sys.exit(1)


@main.command()
@click.option("--platform", type=click.Choice(["snowflake", "databricks", "motherduck"]), default="snowflake")
@click.option("--connection", default=None, help="Snowflake-only: name of a section in ~/.snowsql/config (or ~/.snowflake/config.toml). Ignored for --platform databricks / motherduck.")
def setup(platform, connection):
    overrides = {"platform": platform}
    if connection:
        if platform != "snowflake":
            console.print(
                f"[yellow]Warning:[/yellow] --connection is Snowflake-only and is "
                f"ignored on --platform {platform}."
            )
        else:
            overrides["snowflake_connection"] = connection

    config = load_config(cli_overrides=overrides)

    console.print(f"Testing {platform.title()} connection...")
    try:
        with connect(config) as conn:
            console.print("[green]Connected successfully[/green]")
            validate_access(conn, config.platform)
            console.print("[green]Query history access verified[/green]")

            if platform == "snowflake":
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY "
                    "WHERE START_TIME >= DATEADD('day', -1, CURRENT_TIMESTAMP())"
                )
                count = cursor.fetchone()[0]
                cursor.close()
            elif platform == "databricks":
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM system.query.history "
                    "WHERE start_time >= (current_timestamp() - INTERVAL 24 HOURS)"
                )
                count = cursor.fetchone()[0]
                cursor.close()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM MD_INFORMATION_SCHEMA.QUERY_HISTORY "
                    "WHERE start_time >= now() - INTERVAL '24' HOUR"
                ).fetchone()
                count = row[0] if row else 0
            console.print(f"Queries in last 24h: {count:,}")
            console.print("[green]Setup complete. Ready to use.[/green]")

    except PlatformAccessError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Connection failed:[/red] {_format_error(e)}")
        sys.exit(1)


@main.group(help="Inspect past sqlscout runs stored under ~/.sqlscout/history/ (or $SQLSCOUT_HISTORY_DIR).")
def history():
    pass


@history.command("list", help="List past runs for a platform, newest first.")
@click.option("--platform", type=click.Choice(["snowflake", "databricks", "motherduck"]), default="snowflake")
@click.option("--history-dir", type=click.Path(), default=None)
def history_list(platform, history_dir):
    runs = list_runs(platform, override_dir=history_dir)
    if not runs:
        hdir = resolve_history_dir(platform, history_dir)
        console.print(f"No runs found at {hdir}")
        return
    console.print(f"Past runs for [cyan]{platform}[/cyan]:")
    for r in runs:
        size_kb = r.stat().st_size // 1024
        md = r.with_suffix(".md")
        md_suffix = f" (+ {md.name})" if md.exists() else ""
        console.print(f"  {r.name}  {size_kb:>6}KB{md_suffix}")


@history.command("path", help="Print the history directory for a platform.")
@click.option("--platform", type=click.Choice(["snowflake", "databricks", "motherduck"]), default="snowflake")
@click.option("--history-dir", type=click.Path(), default=None)
def history_path(platform, history_dir):
    click.echo(resolve_history_dir(platform, history_dir))


@main.command()
@click.option("--platform", type=click.Choice(["snowflake", "databricks", "motherduck"]), default="snowflake")
@click.option("--days", type=click.Choice(["1", "7", "14", "30"]), default="7")
@click.option("--hours", type=int, default=None, help="Time window in hours. Overrides --days when set.")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--connection", default=None, help="Snowflake-only: name of a section in ~/.snowsql/config (or ~/.snowflake/config.toml). Ignored for --platform databricks / motherduck.")
@click.option("--exclude-users", default=None)
@click.option("--exclude-roles", default=None)
@click.option("--min-duration-ms", type=int, default=100, help="Skip queries shorter than this many ms.")
@click.option("--include-trivial", is_flag=True, default=False, help="Include trivial queries (SELECT 1, CALL, etc.).")
@click.pass_context
def count(ctx, platform, days, hours, config_path, connection, exclude_users, exclude_roles, min_duration_ms, include_trivial):
    overrides = _gated_overrides(ctx, {
        "platform": ("platform", platform),
        "days": ("days", int(days)),
        "min_duration_ms": ("min_duration_ms", min_duration_ms),
        "include_trivial": ("include_trivial", include_trivial),
    })
    if hours is not None:
        overrides["hours"] = hours
    if connection:
        if platform != "snowflake":
            console.print(
                f"[yellow]Warning:[/yellow] --connection is Snowflake-only and is "
                f"ignored on --platform {platform}."
            )
        else:
            overrides["snowflake_connection"] = connection
    if exclude_users:
        overrides["exclude_users"] = [u.strip() for u in exclude_users.split(",")]
    if exclude_roles:
        overrides["exclude_roles"] = [r.strip() for r in exclude_roles.split(",")]

    config = load_config(cli_overrides=overrides, config_path=config_path)

    try:
        with connect(config) as conn:
            validate_access(conn, config.platform)
            window_hours = effective_hours(config)
            total = count_queries(conn, config)
            window_label = _format_window_hours(window_hours)
            console.print(f"[cyan]{total:,}[/cyan] SELECT queries in the last {window_label}")
    except Exception as e:
        console.print(f"[red]Error:[/red] {_format_error(e)}")
        sys.exit(1)


@main.command()
@click.option("--platform", type=click.Choice(["snowflake", "databricks", "motherduck"]), default="snowflake")
@click.option("--days", type=click.Choice(["1", "7", "14", "30"]), default="7")
@click.option("--hours", type=int, default=None, help="Time window in hours. Overrides --days when set.")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--connection", default=None, help="Snowflake-only: name of a section in ~/.snowsql/config (or ~/.snowflake/config.toml). Ignored for --platform databricks / motherduck.")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.option("--service-only", is_flag=True, default=False, help="Only show likely service accounts.")
@click.option("--service-user-pattern", multiple=True, help="Glob pattern identifying service users (e.g., 'FIVETRAN_*'). Can be specified multiple times.")
@click.option("--service-user-role", multiple=True, help="Role name that means 'service account'. Can be specified multiple times.")
@click.pass_context
def users(ctx, platform, days, hours, config_path, connection, fmt, service_only, service_user_pattern, service_user_role):
    overrides = _gated_overrides(ctx, {
        "platform": ("platform", platform),
        "days": ("days", int(days)),
    })
    if hours is not None:
        overrides["hours"] = hours
    if connection:
        if platform != "snowflake":
            console.print(
                f"[yellow]Warning:[/yellow] --connection is Snowflake-only and is "
                f"ignored on --platform {platform}."
            )
        else:
            overrides["snowflake_connection"] = connection
    if service_user_pattern:
        overrides["service_user_patterns"] = list(service_user_pattern)
    if service_user_role:
        overrides["service_user_roles"] = list(service_user_role)

    config = load_config(cli_overrides=overrides, config_path=config_path)

    try:
        with connect(config) as conn:
            validate_access(conn, config.platform)
            entries = list_users(conn, config)

            if service_only:
                entries = [e for e in entries if e["likely_service_account"]]

            if fmt == "json":
                import json
                click.echo(json.dumps(entries, indent=2))
                return

            console.print(f"Found [cyan]{len(entries)}[/cyan] distinct users.")
            console.print()
            for e in entries:
                tag = "[yellow]service?[/yellow]" if e["likely_service_account"] else "[green]human[/green]"
                console.print(f"  {tag}  {e['user_name']:40s}  {e['query_count']:>8,} queries")
    except Exception as e:
        console.print(f"[red]Error:[/red] {_format_error(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
