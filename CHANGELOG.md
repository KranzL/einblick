# Changelog

All notable changes to einblick are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-05-02

### Changed

- Default Anthropic model bumped from `claude-sonnet-4-20250514` to `claude-sonnet-4-6`.
- Default OpenAI model bumped from `gpt-4o` to `gpt-5`.

### Added

- GitHub Actions workflow (`.github/workflows/test.yml`) runs `pytest` on every push to `main` and every pull request on Python 3.12. Live warehouse and LLM tests stay skipped without credentials.

## [0.1.0] - 2026-04-26

First public alpha.

### Added

- Three warehouse platforms: Snowflake (`ACCOUNT_USAGE.QUERY_HISTORY`), Databricks (`system.query.history`), and MotherDuck (`MD_INFORMATION_SCHEMA.QUERY_HISTORY`).
- Two entry points: the `/einblick` slash command for interactive Claude Code / Codex sessions (no API key needed) and the `einblick analyze` CLI for cron / Airflow / GitHub Actions (Anthropic, OpenAI, or any OpenAI-compatible endpoint via `--llm-base-url`).
- `--sample` mode: 775 generated queries, runs the full pipeline including the LLM call, no warehouse needed.
- dbt integration -- smarter recommendations via `--dbt-aware` (calls the dbt Cloud Discovery API to cross-reference patterns against real models), and an apply-the-recommendations flow in `/einblick` when `dbt-labs/dbt-mcp` is loaded (creates model files, runs `dbt parse / compile / run / test`, opens a PR).
- Slack incoming-webhook delivery with `--slack-mode digest|alert|off`. Alert mode only fires when cost moves >=20%, three or more new patterns appear, or a pattern disappears versus the previous run.
- Service-account auto-exclusion (`--auto-exclude-service-users`) recognizes Fivetran, dbt, Looker, Tableau, Hex, Hightouch, Census, Mode, Airbyte, Meltano, Airflow, Dagster, Prefect, Stitch, Rivery, Matillion, Segment, RudderStack, Snowflake's `SYSTEM` / `SNOWPIPE` / `WORKSHEETS_APP_USER` / `STREAMLIT_APP_USER`, plus glob patterns like `*_SVC` / `SVC_*` / `*_BOT`.
- Structured `## Proposed dbt Changes` section emitted via a typed `emit_dbt_proposals` tool call. Three proposal shapes -- `new_model`, `modify_existing`, `access_pattern` -- validated through Pydantic with `einblick_schema_version` for forward compatibility.
- Docker image (`ghcr.io/kranzl/einblick:latest`) for scheduled runs.
- Run history under `~/.einblick/history/` with atomic writes, mode `0o600` for files and `0o700` for directories. Default retention is the last 12 runs per platform.
- 341 unit tests plus opt-in live integration tests for each platform.

[Unreleased]: https://github.com/KranzL/einblick/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/KranzL/einblick/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/KranzL/einblick/releases/tag/v0.1.0
