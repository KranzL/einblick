---
name: sqlscout-analysis
description: >
  Activate when the user asks to analyze Snowflake, Databricks, or MotherDuck queries, optimize data models,
  find expensive queries, recommend materialized views, analyze query patterns,
  reduce query costs, or mentions sqlscout.
version: 0.1.0
---

# SqlScout Analysis

Analyze query history patterns from Snowflake, Databricks, or MotherDuck and generate data modeling recommendations.

## Pipeline

```bash
${CLAUDE_PLUGIN_ROOT}/.venv/bin/sqlscout extract --platform <snowflake|databricks|motherduck> --days <N> --format json --output "/tmp/sqlscout-results-$(id -u).json"
```

Then read `/tmp/sqlscout-results-$(id -u).json` (resolve `$(id -u)` to a numeric value via `Bash` first, then pass the literal path to `Read`). The uid suffix avoids cross-user collisions on shared boxes.

## Context Gathering

Before analyzing results, use AskUserQuestion to understand the user's environment:
1. Which platform? (Snowflake, Databricks, or MotherDuck)
2. Where does source data come from? (ETL, dbt, streaming, manual)
3. What data freshness is required? (real-time, hourly, daily, weekly)
4. Is there an existing transformation layer? (dbt, Tasks/Workflows, Airflow, none)

## Analysis Framework

Evaluate each query pattern cluster against these criteria. Apply platform-specific recommendations:

### Both Platforms
1. **Materialization candidates**: High execution count aggregations
2. **Denormalization candidates**: Repeated multi-table joins
3. **Cost hotspots**: High total credits/DBUs
4. **Access patterns**: Who queries what, governance concerns
5. **Biggest offenders**: Users burning the most cost, slowest patterns, heaviest scanners

### Snowflake-Specific
- **Clustering keys**: ALTER TABLE CLUSTER BY on filtered columns (tables >1GB)
- **Dynamic Tables**: Automatic lag-based refresh for SQL transformations
- **Streams + Tasks**: CDC for incremental processing
- **Transient tables**: Skip Fail-Safe on staging tables
- **Search Optimization Service**: Point lookups on large tables

### Databricks-Specific
- **OPTIMIZE + ZORDER**: Compact small files and co-locate data by filter columns
- **Liquid clustering**: Automatic incremental clustering (replaces ZORDER)
- **Delta Live Tables**: Declarative pipelines with dependency tracking
- **Materialized views**: Auto-refreshing pre-computed results
- **Photon**: Queries that would benefit from Photon-accelerated compute
- **Caching**: Delta caching and result caching patterns

## Structured Proposed dbt Changes

Every report ends with a `## Proposed dbt Changes` section. It's not free-form prose -- the LLM calls a typed tool named `emit_dbt_proposals` which sqlscout validates and renders. Three recommendation shapes:

- `new_model` -- brand-new dbt model with proposed SQL, tests, source tables, layer, and materialization
- `modify_existing` -- a config change to an existing dbt model (e.g. `materialized: view` -> `incremental`, add clustering key, add unique_key)
- `access_pattern` -- users querying raw tables that a curated mart already covers (surface only; sqlscout never auto-applies governance changes)

Each proposal carries `metrics_addressed` (sqlscout pattern fingerprints it absorbs) and `sqlscout_schema_version` for forward compatibility.

Claude Code users with `dbt-mcp` installed can act on these proposals directly: create the model files, validate with `dbt parse` / `compile` / `run` / `test`, and open a PR -- all without leaving the conversation. See `docs/dbt-integration.md` in the sqlscout repo for the full flow. This lands phase-by-phase.

**Ships in this release:** `--dbt-aware` (or the "Use dbt project context?" question in the interactive flow) queries the dbt Discovery API to cross-reference each pattern's source tables against actual models in the user's dbt project. The cross-reference is injected into the LLM prompt so recommendations can differentiate new_model / modify_existing / access_pattern from real data, not guesses. Requires `DBT_HOST` / `DBT_TOKEN` / `DBT_PROD_ENV_ID`. Misconfigured auth or network errors fall back to the non-dbt-aware path gracefully -- the run never hard-fails.

## Reference Files

- `references/system-prompt.md` - Data modeling expertise for both platforms
- `references/analysis-prompt.md` - Template for structured analysis (instructs the LLM to call `emit_dbt_proposals`)
