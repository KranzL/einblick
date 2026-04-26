# dbt Integration

How sqlscout hands off its recommendations to a user's dbt project.

## What this is for

Right now sqlscout produces a markdown report with recommendations. Users read it, decide what to do, write dbt models by hand, open a PR. That last mile is manual and is where most of the value leaks out -- the recommendation is only as good as the follow-through.

This document is the plan for closing that loop by integrating with the dbt MCP server, so sqlscout's output can become actual dbt model files, validated and opened as a PR, without leaving Claude Code.

## Scope: dbt Platform (Cloud) only

Automated file creation is Platform-only. Reasons:

- Platform's Discovery API gives us a structured, uniform view of every model in the user's project: SQL, schema, lineage, materialization, performance history. That's what makes targeted recommendations possible.
- dbt Core projects vary too much at the file layout level -- naming conventions, folder structure, macro usage, ref/source style. Without Discovery API, we'd be reverse-engineering each project from examples.
- Platform users are also the group paying for dbt Cloud, which correlates with the kind of workload sqlscout is most useful on (bigger warehouses, more model volume).

Core users still get sqlscout's full report. The `## Proposed dbt Changes` section lands as copy-paste-ready SQL and YAML blocks they can drop into their project manually. They just don't get one-button creation.

## The three recommendation types

`sqlscout analyze` emits a structured `## Proposed dbt Changes` section. Every proposal fits one of three shapes:

### 1. `new_model`

```json
{
  "type": "new_model",
  "name": "stg_orders",
  "layer": "staging",
  "materialization": "view",
  "source_tables": ["RAW.ORDERS"],
  "proposed_sql": "...",
  "proposed_tests": [
    {"column": "order_id", "tests": ["unique", "not_null"]}
  ],
  "rationale": "...",
  "metrics_addressed": ["fingerprint_abc123"]
}
```

### 2. `modify_existing`

```json
{
  "type": "modify_existing",
  "target_model": "mart.fct_revenue",
  "change": "materialization",
  "from": "view",
  "to": "incremental",
  "incremental_strategy": "merge",
  "unique_key": "order_id",
  "rationale": "Pattern abc123 is a full scan of fct_revenue costing $240/week; incremental with merge saves ~80%"
}
```

### 3. `access_pattern`

```json
{
  "type": "access_pattern",
  "issue": "Users querying RAW.ORDERS directly",
  "redirect_to": "mart.fct_orders",
  "patterns_affected": ["fingerprint_abc", "fingerprint_def"],
  "suggested_fix": "Add a dbt exposure flagging the raw access; longer term, restrict raw schema access"
}
```

Access patterns surface in the report but never auto-apply changes -- governance is political and not something sqlscout should touch unilaterally.

**access_pattern requires `--dbt-aware`.** Detecting that a pattern "bypasses" a mart requires knowing which marts exist. Without dbt context the LLM has no way to identify these. When dbt context is off, this recommendation type is never emitted.

### Schema versioning

Every JSON block includes `"sqlscout_schema_version": "1"` so downstream parsers can detect and handle drift.

## Phases

### Phase 0: Structured output in `analyze`

Prereq for everything else. Useful on its own -- the report is more actionable even without dbt-mcp integration.

**Emission mechanism: Anthropic tool_use, not string parsing of prose.**

Free-form markdown output from the LLM is unreliable to parse -- JSON blocks can come back malformed, reordered, with stray commentary. We use Anthropic's `tool_use` / OpenAI's tool-calling API instead. Define a typed tool schema for `emit_dbt_proposals(proposals: list[Proposal])`. The LLM calls it once, we receive structured objects, and we then render them into the markdown report ourselves.

Result: the `## Proposed dbt Changes` section is always valid because sqlscout wrote it from typed data, not the LLM's prose. No try/catch around malformed JSON anywhere downstream.

**Scope:**
- Define the tool schema for each of the three recommendation types in `scripts/src/sqlscout/reporter.py`
- Update `skills/sqlscout-analysis/references/analysis-prompt.md` to instruct the LLM to call `emit_dbt_proposals` (tells it the tool exists, describes the fields, and says "always call this tool exactly once with your recommendations")
- Add a handler that accepts the tool call, validates via pydantic, renders into the markdown report
- Tests: mock LLM that returns a `tool_use` block with known proposals, verify the rendered markdown contains them all with correct shape

### Phase 1: Performance-aware pre-step

This is where the dbt integration earns its keep. Before the LLM writes recommendations, cross-reference sqlscout's patterns against the user's actual dbt models via the Discovery API.

**Pre-step flow (bulk fetch, not per-pattern):**

```
1. Call get_all_sources ONCE -> {unique_id -> (database, schema, identifier)}.
2. Call get_all_models ONCE with the source map joined in -> the full
   inventory including each model's source_tables (resolved FQNs),
   database, schema, alias, materialization (extracted from config),
   filePath, uniqueId.
3. Build a multi-suffix in-memory index: each source_table and each
   model FQN is registered under every suffix (3 -> 2 -> 1 part) so
   queries that say `ORDERS` match a source `RAW.PUB.ORDERS`.
4. For each sqlscout pattern, look up its source_tables; pick the most
   qualified suffix that has a hit.
5. For matched models (capped at 50 -- MAX_PERF_FETCHES), call
   get_model_performance per model. This is the one unavoidable
   per-model call.
6. Write to a uid-scoped temp file (e.g. /tmp/sqlscout-dbt-context-<uid>.json)
   atomically (tmpfile + rename) so concurrent runs don't corrupt each
   other and shared CI runners don't leak data between users.
```

Three round-trips at minimum (sources, models, perf-per-model) plus pagination. For a typical 500-model project with ~20 matches, expect ~25 round-trips total. The 300-call per-pattern naive implementation is ruled out by design.

That lookup is injected into the LLM's prompt via the same `tool_use` channel from Phase 0. The `emit_dbt_proposals` schema gains an `existing_model_context` field that the LLM fills per proposal when relevant.

**Triggering:**

Opt-in at both entry points:
- **CLI:** `sqlscout analyze --dbt-aware` (new flag)
- **Slash command:** AskUserQuestion at the start asking "Use dbt context from your project?" -- default yes if dbt-mcp is detected in the session, no otherwise.

Either path sets the same internal config flag, which gates the pre-step. Default off when neither flag nor question says yes, so users without dbt-mcp don't pay for capability they don't have.

**Scope:**
- New CLI flag `--dbt-aware` in `extract` and `analyze`
- Slash command: new AskUserQuestion in Step 2 alongside the existing context questions
- New module `scripts/src/sqlscout/dbt_discovery.py` -- small GraphQL client for dbt's Discovery API (`metadata.cloud.getdbt.com/graphql`). ~100 lines, uses `requests`. Both the CLI and interactive paths call through this module -- single implementation, one auth path, one place to fix bugs. dbt-mcp is only strictly needed for Phase 2's workflow tools (parse/compile/run/test).
- Writes `/tmp/sqlscout-dbt-context.json` as the handoff file for Phase 2B

**Handoff file schema (`/tmp/sqlscout-dbt-context-<uid>.json`):**

```json
{
  "generated_at": "2026-04-24T14:30:00Z",
  "environment_id": "12345",
  "total_models_seen": 487,
  "matched_pattern_count": 3,
  "patterns": {
    "fp_abc123": {
      "fingerprint": "fp_abc123",
      "matched_model_unique_ids": ["model.analytics.fct_revenue"],
      "matched_models": [{
        "unique_id": "model.analytics.fct_revenue",
        "name": "fct_revenue",
        "database": "ANALYTICS",
        "schema": "MART",
        "alias": null,
        "materialized": "view",
        "source_tables": ["RAW.PUB.ORDERS"],
        "file_path": "models/marts/fct_revenue.sql"
      }]
    }
  },
  "perf": {
    "model.analytics.fct_revenue": {
      "unique_id": "model.analytics.fct_revenue",
      "avg_execution_ms": 47000,
      "max_execution_ms": 72000,
      "total_runs": 20,
      "last_run_status": "success"
    }
  }
}
```

`avg_execution_ms`, `max_execution_ms`, `total_runs`, and `last_run_status` are derived from dbt Discovery's `modelHistoricalRuns` (last 20 runs by default). p95 and 7-day windowed counts are not currently captured -- if Phase 2B's PR-body before/after needs them, that's a follow-up.

### Phase 2: Slash command Step 8 -- three workflows

After the report is written, Step 8 kicks in if dbt-mcp is detected and there are proposals to act on. AskUserQuestion lets the user pick which proposals to apply.

For each picked proposal, run one of:

#### 2A. `new_model` workflow

```
1. dbt::get_all_models + Glob existing model files
   -> infer project conventions (layer folders, naming)
2. dbt::get_model_details on upstream sources
   -> confirm columns / types
3. Write tool -> create models/<layer>/<name>.sql
4. dbt::parse
   -> fails fast on syntax or bad ref()
5. dbt::compile --select <name>
   -> validates SQL compiles against the warehouse schema
6. Resolve the dbt target (see "Target resolution" below)
   AskUserQuestion: "Run dbt against target `<resolved_target>`?
                    This materializes to the warehouse."
7. dbt::run --select <name> --target <resolved_target>
   -> on failure: leave the SQL file in place, do NOT open a PR,
      print the dbt error output, exit the workflow with guidance
      for the user to fix target config / warehouse access
8. dbt::generate_model_yaml --model-names <name>
   -> post-run introspection gives us the column list
   -> requires dbt-codegen in user's packages.yml; if missing,
      print the add-to-packages.yml snippet and stop
9. Write tool -> create a per-model YAML file at
   `models/<layer>/<name>.yml` containing the generated columns merged
   with proposed_tests. No editing of existing schema.yml files --
   we always add a new file alongside the .sql.
10. dbt::test --select <name>
11. Bash: git commit + git push + gh pr create
    (branch name, PR body spec, push-failure fallback below)
```

#### 2B. `modify_existing` workflow (hybrid template + LLM)

```
1. dbt::get_model_details -> returns source file path
2. Read the file
3. Decide: does this change match a template?

   Templates (deterministic edits):
   - view -> incremental           (adds config block with materialized, strategy, unique_key)
   - add clustering key            (appends cluster_by to config)
   - add unique_key                (adds unique_key to existing config)
   - change schema                 (swaps schema in config)
   - view -> table                 (swaps materialized)

   If a template matches:
     Use string-substitution helpers from scripts/src/sqlscout/dbt_edit_templates.py
     (to be written) to patch the file deterministically.

   Otherwise:
     Fall back to Edit tool with LLM-written changes. This covers anything
     we didn't anticipate, at the cost of occasional syntax errors we'll
     catch in step 4.

4. dbt::parse
5. dbt::compile --select <name>
6. Resolve target, AskUserQuestion: "Run dbt against `<resolved_target>`?"
7. dbt::run --select <name> --target <resolved_target>
   -> failure handling same as 2A step 7
8. dbt::test --select <name>
9. dbt::get_model_performance (post-run capture)
   -> read "before" from /tmp/sqlscout-dbt-context.json (written in Phase 1)
   -> this call provides "after"
   -> include both in the PR body
10. Bash: git commit + push + gh pr create
```

**Target resolution (applies to both 2A and 2B step 6):**

Target names vary per project (`dev`, `dev_personal`, `local`, etc.) and live in `profiles.yml`, not `dbt_project.yml`. Resolution order:

1. Check `~/.sqlscout.yml` for `dbt_target:` -- persisted from a prior run
2. Else: on first invocation, call `dbt::list --output json` (or read `profiles.yml` directly) to enumerate available targets for the active profile. Show them via AskUserQuestion: "Which dbt target should sqlscout use for dev runs?"
3. Persist the choice to `~/.sqlscout.yml` so subsequent runs skip the question

Never assume `dev`.

#### 2C. `access_pattern` findings

Not a workflow -- handled entirely in Phase 0 via the `emit_dbt_proposals` tool schema. The LLM emits access_pattern blocks into the report's `## Proposed dbt Changes` section with plain-English fix guidance. Step 8 never picks them up. They do NOT get appended to PR bodies for unrelated changes (doing so would confuse reviewers -- the PR changes one thing, the note talks about another).

If a run produces only access_pattern findings, Step 8 doesn't fire at all -- the report is the deliverable.

Because Phase 2C reduces to "the LLM emitted some JSON," it does not need its own implementation PR. It ships for free with Phase 0.

#### Cross-cutting specs for Phase 2 workflows

**Branch naming.** `sqlscout/<slug>-<YYYYMMDD>` where `<slug>` is a short kebab-case summary (e.g., `revenue-incremental`). If two runs land on the same day for the same slug, append `-<HHMMSS>`.

**PR body template.**

```markdown
Applied by sqlscout from report `sqlscout_results_<platform>_<timestamp>.md`.

## Changes in this PR

### 1. <recommendation_type>: <name or target>
- Rationale: <rationale from proposal>
- Fingerprints addressed: <list of sqlscout pattern IDs>
- Before: <perf_before metrics if modify_existing>
- After: <perf_after metrics if modify_existing>

### 2. ... (additional proposals in the same run)

## Context

- dbt target used: `<resolved_target>`
- sqlscout analysis depth: `<quick|standard|deep>`
- Full report: <path to sqlscout_results_latest.md>
```

Claude composes the body from the structured proposal data and the before/after context file. No LLM prose here -- template is deterministic.

**Push failure fallback.** If `git push origin <branch>` fails (branch protection, no remote write, network), sqlscout:

1. Stops before calling `gh pr create`
2. Prints: "Local branch `<branch>` has your changes committed. Push failed: `<error>`. Fix the issue and run `git push origin <branch> && gh pr create ...` (see the rendered command below)."
3. Prints the exact `gh pr create --title ... --body ...` command the user can run once they resolve the push problem.

The branch and commits are never lost -- worst case, the user finishes the push manually.

**Misconfigured dbt-mcp / Discovery API fallback.** If Phase 1's `get_all_models` (or any Discovery call) returns 401/403 or network error:

1. Log the specific error (which env var is likely wrong)
2. Fall back to the non-dbt-aware path for that run
3. Print a warning: "dbt Discovery returned `<status>`; check `DBT_TOKEN` / `DBT_PROD_ENV_ID` / `DBT_HOST`. Continuing without dbt context -- recommendations will be less targeted."
4. Continue to analyze + report. Step 8 does not offer `modify_existing` or `access_pattern` proposals for that run (they both require dbt context).

Graceful degradation. A misconfigured dbt-mcp never blocks the core sqlscout value.

### Phase 3: Docs

Rides with each phase rather than being its own step. Each PR updates the relevant docs inline:

- Phase 0 PR: brief README note about the new "Proposed dbt Changes" section in reports
- Phase 1 PR: README "Automate with dbt Cloud" section (config stanza, what you get vs Core, `--dbt-aware` flag)
- Phase 2A/2B PR: README subsection on the model-creation flow, target resolution, and the dbt-codegen requirement

No standalone docs phase.

### Phase 4 (later, optional): Headless CLI

`sqlscout create-models --from-report report.md --dbt-project-dir ~/mydbt`

For Airflow / CI to act on sqlscout recommendations without a human at the keyboard. This is a larger piece of work than it looks -- it needs to re-implement Phase 2A/2B's orchestration (file writes, dbt parse/compile/run/test, git, gh) in Python rather than via Claude-in-the-session. Specifically:

- Read the structured proposals from the report file
- Call sqlscout's own Discovery client + dbt CLI subprocess for validation
- Apply templates / invoke an LLM for novel modify_existing edits
- Do git + gh shell-outs

Estimate: 1-2 weeks of focused work. Defer until a real user asks.

## Safeguards

- **Resolved dev target is always used.** Every `dbt run` through the flow hits the target sqlscout has resolved and persisted in `~/.sqlscout.yml` (see "Target resolution" in Phase 2 for how it's picked). Production materializations go through the user's normal CI, not sqlscout.
- **AskUserQuestion before any warehouse write.** The flow always stops and confirms before `dbt run`, showing the target and the list of models.
- **Every change goes through a PR.** No direct commits to main. The `gh pr create` step is always last.
- **Auto-open the PR.** That's the default (user confirmed). If `gh` isn't authenticated, fall back to "stop at pushed branch" and tell the user to open the PR themselves.
- **Access pattern recommendations never auto-apply.** Only surfaced in the report.

## PR authorship and branch conventions

sqlscout itself doesn't have a GitHub identity. Whatever account `git` and `gh` are authenticated as on the machine running Claude Code is who shows up on the PR. Claude is just orchestrating `git commit` and `gh pr create` -- it's not an author. No `Co-Authored-By: Claude` trailers will be added.

### Interactive path (you, in Claude Code)

- **Commit author**: your local `git config user.name` + `user.email`.
- **PR opened by**: whatever account `gh auth status` shows.
- **Branch name**: `sqlscout/<short-description>` (e.g., `sqlscout/revenue-incremental-plus-stg-customer-events`). Stable prefix makes filtering in the GitHub UI / CODEOWNERS rules easy.

No extra setup. You run the slash command, the PR lands under your name, same as if you'd opened it yourself.

### Automated path (cron, Airflow, CI): requires a service user

If you want sqlscout running on a schedule and opening PRs without a human at the keyboard, **you need a dedicated GitHub service user**. Don't reuse a personal account -- PRs authored by you while you're asleep will be confusing, and if you ever leave the team, the automation dies with your account.

What "dedicated service user" means:

1. **Create a GitHub user account** just for automation. Conventions: `sqlscout-bot`, `<your-org>-bot`, or whatever your org uses.
2. **Give it write access** to the dbt repo (push branches, open PRs). Not admin -- write is enough.
3. **Generate a personal access token** (classic or fine-grained) for that account with `repo` scope. This becomes `GH_TOKEN` in the Airflow/cron environment.
4. **Configure git identity** on the runner so commits are attributed to the bot:
   ```bash
   git config user.name "sqlscout-bot"
   git config user.email "sqlscout-bot@your-org.com"
   ```
5. **Create a dbt Cloud user for the bot too** and grab its `DBT_USER_ID`. The service token authenticates API calls; the user ID identifies the caller for audit trails. If you reuse a human's `DBT_USER_ID` the audit log looks like that human triggered automated runs, which is misleading.
6. **Set the PR opener identity** via `GH_TOKEN`:
   ```python
   BashOperator(
       task_id="sqlscout_weekly",
       bash_command="sqlscout analyze ... && git push && gh pr create ...",
       env={
           "GH_TOKEN": "{{ var.value.sqlscout_bot_github_token }}",
           "GIT_AUTHOR_NAME": "sqlscout-bot",
           "GIT_AUTHOR_EMAIL": "sqlscout-bot@your-org.com",
           "GIT_COMMITTER_NAME": "sqlscout-bot",
           "GIT_COMMITTER_EMAIL": "sqlscout-bot@your-org.com",
           "DBT_USER_ID": "{{ var.value.sqlscout_bot_dbt_user_id }}",
           "DBT_PROJECT_DIR": "{{ task_instance.xcom_pull(task_ids='checkout_dbt_repo') }}",
           # ... plus SQLSCOUT_ANTHROPIC_API_KEY, SNOWFLAKE_*, DBT_TOKEN, DBT_HOST, DBT_PROD_ENV_ID
       },
   )
   ```
   **`DBT_PROJECT_DIR` is dynamic for Airflow.** The path is set by the task that checks out the dbt repo, not hardcoded. Adjust per your pipeline.
7. **Tell the team** the bot exists. PRs from `sqlscout-bot` should be treated as automation -- reviewed and merged like any other, but nobody should expect the bot to respond to review comments or iterate.

**Why this matters:** PRs from a real human imply that human thought about the change. PRs from a clearly-named bot account signal "automation; review the diff, not the author." That's the right expectation to set.

**Branch protection on the target repo** should allow the bot to push branches but still require review before merge. Standard stuff -- same rules any other CI user follows.

### Why no `Co-Authored-By: Claude` trailers

Claude didn't write the code -- sqlscout did, and the LLM was a means to that end. Adding Claude as a co-author on every commit creates noise, confuses git blame, and doesn't reflect who actually owns the change. The interactive user (or the bot account, for automation) is the author. Full stop.

## Install reference

**User config** -- goes in Claude Code's `.mcp.json`:

```json
{
  "mcpServers": {
    "dbt": {
      "command": "uvx",
      "args": ["dbt-mcp"],
      "env": {
        "DBT_HOST": "cloud.getdbt.com",
        "DBT_TOKEN": "<service-token>",
        "DBT_PROD_ENV_ID": "12345",
        "DBT_DEV_ENV_ID": "12346",
        "DBT_USER_ID": "7890",
        "DBT_PROJECT_DIR": "/abs/path/to/dbt_project",
        "DBT_PATH": "/abs/path/to/dbt"
      }
    }
  }
}
```

**Service token scope recommendation:**
- Discovery API: read
- Admin API: read (for job history context), no write
- dbt run permission: dev environment only; no production

**Required dbt package:** `dbt-labs/dbt-codegen` must be in the user's `packages.yml`. The `generate_model_yaml` tool used in workflow step 2A.8 wraps dbt-codegen's `generate_model_yaml` macro. Without it, model-creation runs will fail at step 8 with a cryptic error.

Users add to `packages.yml`:

```yaml
packages:
  - package: dbt-labs/dbt-codegen
    version: [">=0.12.0"]
```

Then run `dbt deps`. The slash command detects missing dbt-codegen in step 8 and prints this snippet before stopping, so users get an actionable error on the first failed run.

## Decisions locked in from Q&A

| Decision | Choice |
|---|---|
| Edit strategy for `modify_existing` | Hybrid: templates for common changes (view->incremental, add clustering, etc.), LLM for novel cases |
| When to query Discovery API | Opt-in. `--dbt-aware` flag on the CLI; AskUserQuestion in the slash command at the start |
| Access pattern recommendations | Surface in report only. Never in PR bodies. No auto-DDL, no governance changes |
| PR creation | Auto-open via `gh pr create` at the end of Step 8 |
| Structured output mechanism | Anthropic `tool_use` -- LLM calls `emit_dbt_proposals`, sqlscout renders the markdown from the typed data |
| Discovery API client location | Single GraphQL client in `scripts/src/sqlscout/dbt_discovery.py`, used by both CLI and interactive paths |
| schema.yml strategy for new models | Per-model `<name>.yml` file -- never edit existing schema.yml |
| Branch naming | `sqlscout/<slug>-<YYYYMMDD>` with `HHMMSS` fallback for same-day dupes |
| Misconfigured dbt-mcp fallback | Fall back to non-dbt-aware run + warning; never hard-fail the whole run |
| dbt target resolution | Ask on first run, persist to `~/.sqlscout.yml`; never assume `dev` |

## Open decisions deferred

- Which specific changes get templates in 2B. Start with the five listed (view->incremental, add clustering, add unique_key, change schema, view->table); expand as we see real patterns.
- Where to store a "proposal -> PR" mapping so run-over-run diff can mark recommendations as implemented. Likely a line appended to `~/.sqlscout/history/<platform>/<timestamp>.applied.json` after a successful PR. Defer to the run-over-run diff PR.
- Whether `--dbt-aware` should persist in `~/.sqlscout.yml` so users don't have to pass it every run. Lean yes; implement when we wire the flag.

## Implementation order

1. **Phase 0** -- structured output via `tool_use`. `access_pattern` emission ships here too (Phase 2C has no separate work).
2. **Phase 1** -- performance-aware pre-step + `--dbt-aware` flag + Discovery GraphQL client.
3. **Phase 2A** -- new model workflow in the slash command.
4. **Phase 2B** -- modify existing, with the template set.
5. **Phase 4** -- headless CLI. Deferred until a user asks.

Docs ride with each phase -- no standalone docs PR.

Each phase is its own PR.
