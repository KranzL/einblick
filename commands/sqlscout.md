---
description: Analyze Snowflake, Databricks, or MotherDuck query history and recommend data modeling improvements
argument-hint: "[--sample] [--platform snowflake|databricks|motherduck] [--days 7] [--hours 1] [--top-n 100] [--exclude-users USER1,USER2]"
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - AskUserQuestion
---

# SqlScout: Query History Analysis

Analyze query history from Snowflake, Databricks, or MotherDuck to find repeated patterns, identify biggest offenders, and recommend data modeling improvements.

## Fast path: inline flags provided

If the user passed `--platform` AND at least one of (`--days`, `--hours`) in their arguments, they already know what they want -- skip the question flow. Use the provided flags, skip to Step 3 with the user's exact arguments, and continue to Step 4.

Use the interactive flow only for first-run or when the user hasn't provided enough flags.

## Check for --sample mode

If the user passed `--sample` in their arguments, skip Steps 1-2 and jump directly to Step 3 using this command:

```bash
${CLAUDE_PLUGIN_ROOT}/.venv/bin/sqlscout extract --sample --format json --output "/tmp/sqlscout-results-$(id -u).json"
```

All sqlscout temp files are uid-scoped (`-$(id -u)`) so concurrent users on shared boxes do not collide and other users on the same host cannot read them.

POSIX-only convention: every `/tmp/sqlscout-*-$(id -u).json` reference in this file assumes a Linux/macOS shell where `id -u` returns a numeric user id. On native Windows shells this won't work; use Git Bash, WSL, or substitute `$(whoami)` for `$(id -u)` and adjust paths accordingly. macOS users should also note that `tempfile.gettempdir()` resolves to `${TMPDIR:-/tmp}` (typically `/var/folders/...`); the cleanup glob in Step 9 covers both.

This uses a built-in dataset of 775 realistic Snowflake queries. No credentials needed. For user context in sample mode, use these defaults:
- Platform: Snowflake
- Ingestion: Managed connectors (Fivetran)
- Freshness: Daily
- Transform: dbt
- Daily spend: $1,000-$10,000/day

Then continue from Step 4.

## Step 1: Verify Setup

Check if SqlScout is installed:

```bash
test -f "${CLAUDE_PLUGIN_ROOT}/.venv/bin/sqlscout" && echo "READY" || echo "SETUP_NEEDED"
```

If SETUP_NEEDED, run the installer yourself (do not ask the user to run pip/python commands -- just do it):

```bash
bash "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/install.sh"
```

It creates a local venv under the plugin and installs Snowflake, Databricks, and LLM extras. Takes about 30 seconds.

After the install finishes, the user will still need credentials for a real run. For sample mode (`--sample`), no credentials are needed and you can skip to Step 3.

## Step 2: Gather Context

BEFORE running extraction, use AskUserQuestion to understand the user's environment. Ask these questions in a single AskUserQuestion call:

**Question 1 - "Which platform are you analyzing?"**
Header: "Platform"
Options:
- "Snowflake" - Query SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
- "Databricks" - Query system.query.history via Unity Catalog
- "MotherDuck" - Query MD_INFORMATION_SCHEMA.QUERY_HISTORY (Business plan, org admin only)

**Question 2 - "How does data get into your warehouse?"**
Header: "Ingestion"
Options:
- "Managed connectors (Fivetran, Airbyte, Meltano)" - Data lands in raw/staging schemas via managed EL tools
- "Streaming (Snowpipe, Kafka, Auto Loader)" - Near-real-time data ingestion from event streams or cloud storage
- "Database replication (CDC, log-based)" - Change data capture from operational databases
- "File loads (COPY INTO, external stages)" - Batch file-based loading from cloud storage or local files

**Question 3 - "What is your primary data freshness requirement?"**
Header: "Freshness"
Options:
- "Real-time / minutes" - At least some dashboards or apps need data within minutes of source change
- "Hourly" - Hourly refresh cycles are acceptable for most consumers
- "Daily" - Overnight batch processing, morning-ready data is the norm
- "Weekly or less" - Reporting cadence is weekly or ad hoc

**Question 4 - "Do you have an existing transformation layer?"**
Header: "Transform"
Options:
- "dbt (dbt Cloud or dbt Core)" - Models, tests, and docs managed in dbt
- "Platform-native scheduling (Tasks / Workflows)" - Native Snowflake Tasks or Databricks Workflows
- "External orchestrator (Airflow, Dagster, Prefect)" - Pipeline orchestration outside the platform
- "No formal layer" - Analysts write ad hoc queries directly against source tables

After those 4 questions, ask two more in a second AskUserQuestion call:

**Question 5 - "What is your approximate daily spend on this platform?"**
Header: "Daily Spend"
Options:
- "Under $100/day" - Small workload, every credit matters
- "$100-$1,000/day" - Mid-size, focus on the biggest wins
- "$1,000-$10,000/day" - Large workload, many optimization opportunities
- "Over $10,000/day" - Enterprise scale, even small percentage savings are significant

This answer calibrates the priority thresholds in the report. At $20K/day, a pattern costing 10 credits/day is noise. At $50/day, it's 20% of the budget.

**Question 6 - "How deep should the analysis go?"**
Header: "Depth"
Options:
- "Quick scan (top 25 patterns, short report)" - Use `--analysis-depth quick`. Best for a first look or recurring weekly summary.
- "Standard (top 100, full report with rewrites)" - Use `--analysis-depth standard`. The default. Covers everything meaningful.
- "Deep scan (top 250, long-tail patterns, exhaustive rewrites)" - Use `--analysis-depth deep`. Slower LLM, denser report. Reserve for quarterly reviews.

Save the answer as `--analysis-depth quick|standard|deep` to pass to Step 3.

**Question 7 - "Use dbt project context for this run?"** (only ask if dbt-mcp is available in the session OR if the user has set `DBT_HOST`/`DBT_TOKEN`/`DBT_PROD_ENV_ID` in their env)
Header: "dbt Context"
Options:
- "Yes -- cross-reference against my dbt project" - Use `--dbt-aware`. sqlscout queries the dbt Discovery API to find existing models that cover the same tables as each pattern, so recommendations can differentiate new_model vs modify_existing vs access_pattern. Requires DBT_HOST / DBT_TOKEN / DBT_PROD_ENV_ID env vars. Falls back gracefully if those are missing or return an error.
- "No -- analyze patterns without project context" - Skip the Discovery cross-reference. All proposals will be `new_model` since we can't know what already exists.

If the user doesn't have dbt-mcp and doesn't have the Discovery env vars set, skip this question entirely and proceed without `--dbt-aware`.

Save the answer to pass `--dbt-aware` (or omit) to Step 3.

Format all answers as a bullet list and hold them for injection into the analysis in Step 5. These answers determine whether to recommend dbt models vs raw CTAS, Dynamic Tables vs Delta Live Tables, views vs materialized tables, and how aggressively to prioritize optimizations.

## Step 2.5: Detect Service Accounts (MANDATORY -- DO NOT SKIP)

**This step is required for every run unless the user already passed `--exclude-users` or `--service-user-pattern` with explicit values.** Service-account patterns vary by company -- what looks like a service user in one org is a normal human in another. We need the user to tell us their convention.

First, run a quick sample of distinct users to show what's in their data:

```bash
${CLAUDE_PLUGIN_ROOT}/.venv/bin/sqlscout users --platform <platform> --hours 24 --format json
```

Look at the output. Notice any patterns: is it email-style (`alice@company.com`)? All caps (`FIVETRAN_PROD`)? Prefix-based (`svc_airflow`)? Suffix-based (`tableau_bot`)?

Then use AskUserQuestion to ask the user how to identify service accounts at their company:

**Question: "How are service accounts (automated users like ETL, BI tools, dbt) named in your organization?"**
Header: "Service Pattern"
Options:
- "Humans have `@`, service accounts don't (most common default)" - Uses no-`@` heuristic only
- "Service accounts have specific prefixes (e.g., FIVETRAN_*, DBT_*, SVC_*)" - Claude will ask which prefixes
- "Service accounts have specific suffixes (e.g., *_SVC, *_BOT, *_SERVICE)" - Claude will ask which suffixes
- "Service accounts use specific roles (e.g., SERVICE_ROLE, INTEGRATION_ROLE)" - Claude will ask which roles

Based on the answer, follow up with a specific question to gather the patterns. If they pick prefixes, show a multi-select of detected prefix patterns from the user list. If roles, do the same for roles.

Example follow-up for prefixes:
**"Which prefixes identify service users?"** (multiSelect=true)
Options derived from the actual user list (e.g., `FIVETRAN_*`, `DBT_*`, `LOOKER_*`, `AIRFLOW_*`).

Pass the patterns to Step 3 via `--service-user-pattern 'FIVETRAN_*' --service-user-pattern 'DBT_*'` (each pattern as its own flag). Or pass roles via `--service-user-role SERVICE_ROLE`.

If the user picks the default `@` option, just proceed without patterns -- the pipeline uses the `@` heuristic as a fallback.

Use `--hours 24` here to make this step fast regardless of the main analysis window.

```bash
${CLAUDE_PLUGIN_ROOT}/.venv/bin/sqlscout users --platform <platform> --hours 24 --service-only --format json
```

Parse the JSON. Then use AskUserQuestion to ask the user which service accounts to exclude:

**Question: "We detected {N} likely service accounts. Should we exclude them from the analysis?"**
Header: "Service Accts"
Options:
- "Exclude all of them (recommended)" - cleanest analysis, focuses on human queries only
- "Exclude most, keep ETL users I care about" - Claude will ask a follow-up about specific users
- "Include everything" - analyze all queries including automated jobs
- "Show me the list first" - Claude will display the names and query counts before deciding

If the list is short (<5) just show it inline and use a binary include/exclude question. If the user picks "Exclude most", follow up with a multi-select question listing the detected service accounts.

Pass the final exclude list to Step 3 via `--exclude-users` (comma separated).

## Step 3: Extract and Process

Run the extraction pipeline. Use the platform from Step 2 and the service-account exclusions from Step 2.5:

```bash
${CLAUDE_PLUGIN_ROOT}/.venv/bin/sqlscout extract --platform <platform> $ARGUMENTS --exclude-users "USER1,USER2" --format json --output "/tmp/sqlscout-results-$(id -u).json"
```

The CLI will print:
- An expected query count before extraction starts
- A live progress bar showing `{extracted} / ~{expected} queries`

If the expected count is very large (>500K), suggest a shorter window to the user: `--hours 6` or `--hours 1` for a quick preview.

If extraction fails:
- Snowflake "Cannot access SNOWFLAKE.ACCOUNT_USAGE" -> GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE <role>
- Databricks "Cannot access system.query.history" -> Unity Catalog must be enabled, user needs system catalog access
- Connection errors -> check ~/.snowsql/config, ~/.snowflake/config.toml, or ~/.databrickscfg
- Timeout -> try a shorter time window (`--hours 6` or `--hours 1`)

## Step 4: Load Results

Read the output file at `/tmp/sqlscout-results-$(id -u).json`. Resolve `$(id -u)` first via `Bash` (e.g. `id -u`) and substitute the literal numeric value into the file path you pass to the `Read` tool.

If `/tmp/sqlscout-dbt-context-$UID.json` exists (or `/tmp/sqlscout-dbt-context.json` on systems where `getuid()` is unavailable), also read it. This is the dbt cross-reference handoff. Each pattern fingerprint may have a list of `matched_models` — model names, materialization, and recent performance stats. **Use this to ground the recommendations in Step 5/6:** if a pattern matches an existing model, prefer `modify_existing` over `new_model`. If a mart-layer model already exists for raw access, propose `access_pattern`.

After loading, ask follow-up questions if the data reveals:
- Multiple schemas/databases (ask which are source vs. analytics)
- Suspected service accounts that weren't excluded

## Step 5: Analyze

Read the analysis expertise from `${CLAUDE_PLUGIN_ROOT}/skills/sqlscout-analysis/references/system-prompt.md`.

Using that expertise AND the user context from Step 2, analyze each query pattern cluster. Tailor recommendations to the platform:

**Snowflake-specific**: clustering keys, materialized views, Dynamic Tables, transient tables, Streams + Tasks, Search Optimization Service
**Databricks-specific**: Delta table optimization (OPTIMIZE, ZORDER), liquid clustering, materialized views, Delta Live Tables, Auto Loader, photon acceleration, caching

For every cluster, evaluate:
1. Is this a materialization candidate?
2. Is this a denormalization candidate?
3. Could tables benefit from clustering/ZORDER?
4. Should this use incremental processing (Stream+Task / DLT)?
5. What is the cost impact?
6. Who is running these queries? (biggest offenders)

## Step 6: Generate Report

Produce a structured report with these sections:

1. **Executive Summary** (2-3 sentences, lead with highest-impact finding; note that cost numbers are estimates)
2. **Methodology Note** (short section: "Cost figures in this report are ESTIMATES based on execution time × warehouse size. Actual Snowflake billing is per warehouse-second, not per query, so when queries share a warehouse the summed estimates over-count actual credits. Use these as a RANKING score, not a billing reconciliation. Snowflake's per-query attribution view exists but is incomplete and doesn't include all queries.")
3. **Biggest Offenders** (users by estimated cost, longest-running queries, heaviest scanners, warehouse inefficiencies)
4. **Top Recommendations** (each with DDL, **original + rewritten query**, impact estimate, refresh strategy, priority, implementation risk). For every recommendation, attempt a query rewrite applying the patterns from the system prompt (predicate pushdown, SELECT * elimination, ROW_NUMBER->QUALIFY, NOT IN->NOT EXISTS, APPROX_COUNT_DISTINCT, etc.). If a query is already near-optimal, say so explicitly.
5. **Query Rewrites** (consolidated section: top 5-10 rewrites from above, each as fingerprint + original SQL + optimized SQL + one-line summary, so users can copy rewrites into dbt/BI tools without reading the full report)
6. **Patterns Skipped** (patterns not worth optimizing, with reasoning)
7. **Cost Analysis** (total estimated compute cost, top consumers, estimated savings -- use phrasing like "estimated" or "approximate")
8. **Access Patterns** (who queries what, role distribution, governance)
9. **Implementation Checklist** (ordered steps, permissions, dependencies, validation)
10. **Proposed dbt Changes** (structured section, described below) -- always include. Every sqlscout report ends with this section so downstream tooling and humans have a consistent shape.

**Important**: When writing the report, use language like "estimated compute cost", "approximate cost ranking", or "compute-cost score" rather than definitive credit numbers. Be honest about the limitation -- users need to understand what they're looking at.

### Proposed dbt Changes section format

After Implementation Checklist, emit a `## Proposed dbt Changes` section. For each item in Top Recommendations that maps to a dbt change, render one of three typed blocks:

**new_model** (a brand-new dbt model):

```markdown
### N. `new_model`: <layer>/<name>

- **Materialization:** `<view|table|incremental|ephemeral>`
- **Source tables:** `<RAW.SCHEMA.TABLE>`, ...
- **Rationale:** <one-sentence why>
- **Fingerprints addressed:** fp1, fp2, ...

**Proposed SQL:**

` ` `sql
select ...
` ` `

**Proposed tests:**

- `column_name`: unique, not_null
```

**modify_existing** (only include if you know the model exists in the user's project -- requires dbt context; otherwise skip):

```markdown
### N. `modify_existing`: <target_model>

- **Change:** `materialization` / `add_clustering` / `add_unique_key` / `change_schema` / `other`
- **From -> To:** `<from>` -> `<to>`
- **Incremental strategy:** `merge` (if applicable)
- **Unique key:** `order_id` (if applicable)
- **Rationale:** <one-sentence why>
- **Fingerprints addressed:** fp1, fp2, ...
```

**access_pattern** (only include if you know a mart model covers the accessed data):

```markdown
### N. `access_pattern`: <one-sentence issue>

- **Should query instead:** `<mart.model_name>`
- **Patterns affected:** fp1, fp2, ...
- **Suggested fix:** <fix description>

> Surface-only recommendation -- sqlscout will not auto-apply governance changes.
```

If there are no concrete dbt changes worth proposing, the Proposed dbt Changes section should still exist but say: "No structured dbt proposals from this run -- recommendations above are copy-paste guidance only."

Numbering is sequential across all three types (1, 2, 3 ...), not restarted per type.

Schema version: the full sqlscout CLI output tags each proposal with `sqlscout_schema_version: "1"` in its JSON form. The interactive markdown rendering doesn't need to surface that field to the user.

### Also write the structured proposals as JSON for Step 8

After writing the markdown report, use the Write tool to also save a JSON sidecar at `/tmp/sqlscout-proposals-$(id -u).json`. This is what Step 8 reads. Resolve `$(id -u)` via `Bash` once and substitute the numeric value when calling Write. Format:

```json
{
  "sqlscout_schema_version": "1",
  "report_path": "<absolute path to the saved .md>",
  "dbt_target": "<resolved dbt target name, if known>",
  "proposals": [
    {
      "type": "new_model",
      "name": "stg_orders",
      "layer": "staging",
      "materialization": "view",
      "source_tables": ["RAW.PUB.ORDERS"],
      "proposed_sql": "select ...",
      "proposed_tests": [{"column": "order_id", "tests": ["unique", "not_null"]}],
      "rationale": "...",
      "metrics_addressed": ["fp_abc123"]
    }
  ]
}
```

Include only the proposals you actually rendered in the markdown. Use the same field names the schema uses. Step 8 reads this file -- if it's missing or malformed, Step 8 stops with a clear error.

## Step 7: Save Report

Always save the complete report to a uniquely-named file so historical runs are preserved (this enables `--diff` against previous runs later).

**Filename format**: `sqlscout_results_<platform>_<YYYYMMDD>_<HHMMSS>.md` in the user's current working directory.

- `<platform>` is `snowflake` or `databricks` (lowercase)
- Timestamp is current local time at report generation

To get the current timestamp, run: `date +%Y%m%d_%H%M%S`

Example: `sqlscout_results_snowflake_20260419_143022.md`

**The first section of the report MUST be a "Re-run this analysis" block** so the user can copy-paste it to rerun this exact analysis on demand, a cron job, or an Airflow task. Format (fill in the exact values used):

```markdown
## Re-run this analysis

### Interactive (Claude Code)

    /sqlscout --platform <platform> --days <N> --exclude-users "USER1,USER2" --service-user-pattern 'PATTERN_*' [--dbt-aware]

### Programmatic (CLI, full LLM report)

Requires an LLM API key. Use the SQLSCOUT-prefixed variable so it doesn't collide with Claude Code (which also reads ANTHROPIC_API_KEY):

    export SQLSCOUT_ANTHROPIC_API_KEY=sk-ant-...   # or SQLSCOUT_OPENAI_API_KEY=sk-...

If you used --dbt-aware in this run, also export the dbt env vars in your cron environment:

    export DBT_HOST=cloud.getdbt.com
    export DBT_TOKEN=dbts_...
    export DBT_PROD_ENV_ID=12345

    sqlscout analyze \
      --platform <platform> \
      --days <N> \
      --analysis-depth <quick|standard|deep> \
      [--dbt-aware] \
      --exclude-users "USER1,USER2" \
      --service-user-pattern 'PATTERN_*' \
      --context-ingestion "<answer>" \
      --context-freshness "<answer>" \
      --context-transform "<answer>" \
      --context-spend "<answer>" \
      --output report.md

Include `--dbt-aware` only if it was used in the original run. If included, the DBT_* env vars must be set or the run silently degrades (warning logged, no dbt context applied).

For Airflow / cron: pipe `report.md` to Slack, S3, or wherever via a shell task.

### Extract only (no LLM, raw clusters)

    sqlscout extract --platform <platform> --days <N> --exclude-users "USER1,USER2" [--dbt-aware] --format markdown --output report.md
```

Use the exact flag values the user answered in Steps 2, 2.5, and 3 -- quote strings with commas or spaces. This section must appear before the Executive Summary.

**Critical: never write `--auto-exclude-service-users` in this block.** The whole point of persisting this command is that it's reproducible on a cron without running the users-list step first. Write out the resolved usernames explicitly as `--exclude-users "USER1,USER2,..."`. If the list is long, include it all -- a 30-user exclude list is still better than a runtime detection step that adds 20 seconds to every cron run and can drift if new service accounts appear.

Use the Write tool to save the full report contents (the same text you displayed in the conversation). Do not overwrite existing `sqlscout_results_*.md` files -- each run gets its own timestamped output.

Also update (or create) `sqlscout_results_latest.md` as a symlink/duplicate pointing to the most recent report, so users always have a stable filename to reference. Since we can't create symlinks with the Write tool, just write the same content to both filenames.

After writing, confirm to the user with both filenames: "Report saved to `sqlscout_results_<platform>_<timestamp>.md` (also copied to `sqlscout_results_latest.md`). The top of the file has the exact command for re-running this analysis from the CLI, an Airflow task, or cron."

## Step 8: Offer to create dbt models (only if dbt-mcp is loaded in this session)

**When to run this step:**
- `dbt::get_all_models` is in the session's available tool list (i.e., the user has dbt-mcp installed and configured against dbt Cloud), AND
- The report's "Proposed dbt Changes" section contains at least one `new_model` or `modify_existing` proposal (access_pattern-only runs skip Step 8 entirely).

If dbt-mcp is not loaded, skip this step. Step 9 (Cleanup) still runs.

### 8.1 Load structured proposals from the JSON sidecar

Read `/tmp/sqlscout-proposals-$(id -u).json` (written by Step 6). If it's missing or malformed: print the error, skip Step 8, proceed to Step 9. Do not parse the markdown.

Filter to actionable proposals (`new_model` and `modify_existing`). Skip `access_pattern` -- those stay surface-only.

If there are zero actionable proposals, skip the rest of Step 8 and proceed to Step 9.

### 8.2 First, ask the apply mode

AskUserQuestion (single-select):

**Question: "Apply dbt changes from this report?"**
Header: "Apply Mode"
Options:
- "Apply all the actionable proposals" -- proceed to 8.3 with all proposals selected
- "Pick a subset" -- proceed to 8.2b
- "None -- I'll do it manually" -- skip to Step 9

### 8.2b If the user picked "subset"

Second AskUserQuestion (multi-select):

**Question: "Which proposals?"**
Header: "Pick"
Options: one per actionable proposal, labeled like `new_model: staging/stg_orders` or `modify_existing: mart.fct_revenue (view -> incremental)`.

If the user picks zero, skip to Step 9.

### 8.3 Resolve the dbt project directory

Step 8 must operate inside the user's dbt project, not the current working directory.

1. Check `$DBT_PROJECT_DIR` env var. If set, use it.
2. Else read `~/.sqlscout.yml` for `dbt_project_dir:`.
3. Else AskUserQuestion: "Where is your dbt project? (absolute path)"
4. Verify the path exists and contains `dbt_project.yml`. If not, AskUserQuestion again with a hint.
5. Persist via the Write tool: add `dbt_project_dir: <path>` to `~/.sqlscout.yml`.

Use Bash to `cd "$DBT_PROJECT_DIR"` once at the start of Step 8.4 -- all subsequent git, file, and dbt commands run from there.

### 8.4 Resolve the dbt target (once per session)

Before running any `dbt::run`:

1. Check `~/.sqlscout.yml` for `dbt_target:`. If present, use it.
2. Otherwise, read `~/.dbt/profiles.yml` via the Read tool to enumerate targets for the active profile (the project's `dbt_project.yml` names the profile via `profile:`).
3. AskUserQuestion: "Which dbt target should sqlscout use for dev runs?" with one option per detected target.
4. Persist via the Write tool: add `dbt_target: <name>` to `~/.sqlscout.yml`.

Never assume a target is called `dev`.

### 8.5 For each picked `new_model` proposal

Execute this workflow end-to-end before starting the next proposal:

```
1. dbt::get_all_models (cached from Phase 1 if available) + Glob models/<layer>/*.sql
   to infer project conventions (folder layout, naming, config style)
2. dbt::get_model_details on each upstream source in source_tables
   to confirm column names / types before writing the proposed SQL
3. Write tool -> create models/<layer>/<name>.sql with the proposal's
   proposed_sql, adapted to match the project's ref/source style
4. dbt::parse
   -> if this errors, read the output, fix the file, re-try once;
      give up after one retry. On final failure, ROLL BACK: rm the
      .sql file you wrote in step 3 and stop this proposal.
5. dbt::compile --select <name>
   -> same retry policy. On final failure, roll back the .sql file.
6. AskUserQuestion: "Run dbt against target `<resolved>`? This materializes
   to the warehouse." Only ask if not already answered for this session.
7. dbt::run --select <name> --target <resolved>
   -> on failure: ROLL BACK the .sql file you wrote in step 3 (`rm <path>`)
      and do NOT proceed to yml/tests or PR. Print the dbt error.
      Note: a partial materialization MAY exist in the warehouse if dbt::run
      committed CTAS before failing on a post-step. Warn the user with the
      resolved FQN (database.schema.<name>) so they can clean up if needed.
      Continue to the next picked proposal if any.
8. dbt::generate_model_yaml --model-names <name>
   -> requires dbt-labs/dbt-codegen in the user's packages.yml. If it
      errors about codegen, print the add-to-packages.yml snippet AND
      ROLL BACK the .sql + the materialized table (`drop table <fqn>`
      via dbt::execute_sql or warn the user). Stop the proposal.
9. Write tool -> create models/<layer>/<name>.yml (a per-model schema
   file, NOT edits to an existing schema.yml). Merge the generate_model_yaml
   output with the proposed_tests from the proposal.
10. dbt::test --select <name>
11. Capture: { name, layer, file_path, perf_after (from dbt::get_model_performance) }
    for the PR body.
```

### 8.6 For each picked `modify_existing` proposal

The proposal's `target_model` is layer-qualified (e.g. `mart.fct_revenue`). For the dbt CLI `--select`, use only the model name part (e.g. `fct_revenue`). Parse it as `[layer].[name]` and pass `<name>` to `--select`.

CRITICAL: this workflow MODIFIES an existing tracked file. Rollback MUST use `git checkout -- <path>` to restore the original contents -- never `rm`. Do NOT proceed to 8.7 (commit + PR) for any proposal whose verification (parse / compile / run / test) failed; only commit modifications that fully verified.

```
1. dbt::get_model_details on target_model -> returns the source file path (record this as <path>)
2. Read tool -> read the existing .sql file at <path>
3. Decide: does this change match one of these templates?
     - view -> incremental (add config block with materialized, strategy,
       unique_key)
     - add clustering key (append cluster_by to config)
     - add unique_key (add unique_key to existing config)
     - change schema (swap schema in config)
     - view -> table (swap materialized)
   If a template matches: use string-substitution in the config() block
   deterministically. Otherwise: use Edit tool with LLM-written changes.
4. dbt::parse
   -> on error: ROLL BACK with `git checkout -- <path>` and stop this proposal.
5. dbt::compile --select <name>
   -> on error: ROLL BACK with `git checkout -- <path>` and stop this proposal.
6. If target not yet resolved this session: 8.3
7. dbt::run --select <name> --target <resolved>
   -> on failure: ROLL BACK with `git checkout -- <path>`. Print the dbt error.
      Note: a partial materialization MAY exist in the warehouse if dbt::run
      committed CTAS before failing on a post-step. Warn the user with the
      resolved FQN (database.schema.<name>) so they can clean up if needed.
      Do NOT proceed to 8.7 for this proposal. Continue to next proposal.
8. dbt::test --select <name>
   -> on failure: ROLL BACK with `git checkout -- <path>`. Tests caught a
      regression. Do NOT proceed to 8.7 for this proposal.
9. Capture: perf_before (from Phase 1's /tmp/sqlscout-dbt-context.json),
   perf_after (dbt::get_model_performance), target_model, change description
   for the PR body.
```

### 8.7 Branch + commit + PR

After all picked proposals are processed (and at least one succeeded -- if all rolled back, skip to Step 9). Only commit work for proposals whose 8.5/8.6 verification fully passed -- rolled-back files are already restored via `git checkout`, so they will not appear in `git status`.

Before substituting any field into a shell command, verify it matches `[A-Za-z0-9_-]{1,50}`. Refuse to proceed if a proposal's `name` or `target_model` would generate an unsafe slug. Compute the `BRANCH` from sanitized fields only.

```bash
cd "$DBT_PROJECT_DIR"   # must be inside the dbt project, not the cwd /sqlscout was invoked from
BRANCH="sqlscout/$(short-slug)-$(date +%Y%m%d)"
git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH"
git add models/
git commit -F /tmp/sqlscout-commit-message-$$.txt
git push -u origin "$BRANCH"
```

Write the commit message to a temp file via the Write tool first (never inline a Pydantic field into `-m`). Use `--body-file` for `gh pr create` for the same reason.

If `git commit` fails (pre-commit hook, signing config issue):
1. Do NOT call `git push` or `gh pr create`.
2. Tell the user the changes are staged locally, surface the hook output, and let them resolve.

If `git push` fails (branch protection, network, etc.):
1. Do NOT call `gh pr create`.
2. Print the diagnostic, tell the user the branch is ready locally, and paste the exact `gh pr create ...` command they can run after fixing the push.

If `gh` is not installed (`which gh` returns nothing):
1. Skip `gh pr create`.
2. Tell the user the branch is pushed and give them the URL pattern to open the PR manually.

On successful push, run `gh pr create` with this body template (filled from captured data in 8.5/8.6):

```markdown
Applied by sqlscout from report `sqlscout_results_<platform>_<timestamp>.md`.

## Changes in this PR

### 1. <type>: <name or target>
- Rationale: <rationale from proposal>
- Fingerprints addressed: <sqlscout fingerprints>
- Before: <perf_before if modify_existing>
- After: <perf_after>

### 2. ... (additional proposals)

## Context

- dbt target used: `<resolved_target>`
- sqlscout analysis depth: `<quick|standard|deep>`
- Full report: `<sqlscout_results_latest.md>`
```

No LLM prose in the PR body -- it's assembled from structured data.

### 8.8 Branch-naming rules

Short slug comes from the proposal names joined with `-plus-`, hyphen-kebab, max 50 chars. Examples:
- One proposal: `sqlscout/revenue-incremental-20260424`
- Two proposals: `sqlscout/revenue-incremental-plus-stg-customer-events-20260424`
- Many: truncate to the two highest-impact proposals and append `-plus-<N>-more-20260424`

If the same branch already exists (same slug, same day), append `-<HHMMSS>`.

### 8.9 Never do these things in Step 8

- Never run `dbt::run` without resolving the target via 8.4.
- Never edit an existing `schema.yml`. Always write per-model `<name>.yml` files for new models.
- Never append `access_pattern` findings to the PR body. They live in the report only.
- Never skip the dbt-codegen detection in 8.5 step 8. Users will be confused by cryptic errors without the add-to-packages.yml hint.
- Never commit to `main`. Always open a PR.
- Never run git commands from outside `$DBT_PROJECT_DIR`. Always `cd` first.

## Step 9: Cleanup

```bash
TMP="${TMPDIR:-/tmp}"
TMP="${TMP%/}"
rm -f "$TMP/sqlscout-results-$(id -u).json"
rm -f "$TMP/sqlscout-proposals-$(id -u).json"
rm -f "$TMP"/sqlscout-dbt-context-*.json
rm -f "$TMP"/sqlscout-dbt-context.json
rm -f "$TMP"/sqlscout-commit-message-*.txt
```

`${TMPDIR:-/tmp}` covers macOS (where Python's `tempfile.gettempdir()` resolves to a per-user `/var/folders/.../T` path) AND Linux (where it falls back to `/tmp`).
