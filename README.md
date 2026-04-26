# Einblick

Point it at Snowflake, Databricks, or MotherDuck. It pulls your query history, clusters the patterns that keep showing up, and tells you what to materialize, cluster, or denormalize.

I built this because my team kept running the same twenty joins in slightly different shapes, and I wanted to see them all laid out with cost attached.

## Two ways to use it

The setup is genuinely different for each, so pick the one that matches you.

### You're in Claude Code or Codex right now

Install the plugin and run `/einblick`. Claude reads the data and writes the report inside your conversation. **No LLM API key from you** -- the agent you're already talking to does that work.

```
/plugin marketplace add KranzL/einblick
/plugin install einblick@einblick
/einblick --platform snowflake --days 7
```

First run sets up a Python venv on its own. You only need warehouse credentials.

### You want it on a schedule

Airflow, cron, GitHub Actions. The CLI calls Claude or OpenAI directly and writes a finished markdown report to disk, no agent needed. **You provide the API key.**

```bash
git clone https://github.com/KranzL/einblick
bash einblick/hooks/scripts/install.sh

# No warehouse handy yet? Try the bundled sample dataset first --
# 775 generated queries, no creds, full pipeline including the LLM call:
einblick/.venv/bin/einblick analyze --sample \
  --provider anthropic --output sample-report.md

# Real run:
export EINBLICK_ANTHROPIC_API_KEY=sk-ant-...
export SNOWFLAKE_ACCOUNT=...
export SNOWFLAKE_USER=...
export SNOWFLAKE_PASSWORD=...

einblick/.venv/bin/einblick analyze \
  --platform snowflake \
  --days 7 \
  --output report.md
```

> Use `EINBLICK_ANTHROPIC_API_KEY`, **not** the bare `ANTHROPIC_API_KEY`. The unprefixed one is read by Claude Code itself, so putting it in your shell profile will hijack Claude Code and break its auth. The `EINBLICK_`-prefixed name is einblick-only. The bare name still works as a fallback for one-off invocations (Airflow tasks, etc.) but you'll get a warning telling you to switch.

For non-Anthropic providers (Venice.ai, Together, local Ollama), point `--llm-base-url` at the compatible endpoint:

```bash
export EINBLICK_OPENAI_API_KEY=your-venice-key

einblick analyze --provider openai \
  --llm-base-url https://api.venice.ai/api/v1 \
  --model llama-3.3-70b \
  --platform snowflake --days 7 --output report.md
```

Tool-calling support varies. Some providers don't fully implement OpenAI's tool API, so the structured `## Proposed dbt Changes` block may be empty even though the prose report renders fine. The run won't fail.

In Airflow, set the env on the task itself so secrets don't sit in your shell:

```python
BashOperator(
    task_id="einblick_weekly",
    bash_command="einblick analyze --platform snowflake --days 7 --output /tmp/report.md",
    env={
        "EINBLICK_ANTHROPIC_API_KEY": "{{ var.value.anthropic_key }}",
        "SNOWFLAKE_ACCOUNT": "{{ var.value.snowflake_account }}",
        "SNOWFLAKE_USER": "{{ var.value.snowflake_user }}",
        "SNOWFLAKE_PASSWORD": "{{ var.value.snowflake_password }}",
    },
)
```

## Run as a Docker container (Airflow / cron / CI)

For scheduled runs, the cleanest deployment is the prebuilt container at `ghcr.io/kranzl/einblick:latest`. Pinned Python, pinned deps, no virtualenv to babysit on shared infrastructure.

```bash
docker run --rm \
  -e EINBLICK_ANTHROPIC_API_KEY=sk-ant-... \
  -e SNOWFLAKE_ACCOUNT=... \
  -e SNOWFLAKE_USER=... \
  -e SNOWFLAKE_PASSWORD=... \
  -e EINBLICK_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/... \
  -v $(pwd)/reports:/workspace/reports \
  ghcr.io/kranzl/einblick:latest \
  analyze --platform snowflake --days 7 --slack-mode alert --output /workspace/reports/r.md
```

Or use the included `docker-compose.yml` -- drop your secrets in a `.env` file next to it and `docker compose up` does the rest.

In Airflow, the `KubernetesPodOperator` or `DockerOperator` is one block:

```python
KubernetesPodOperator(
    task_id="einblick_weekly",
    image="ghcr.io/kranzl/einblick:latest",
    arguments=[
        "analyze", "--platform", "snowflake", "--days", "7",
        "--slack-mode", "alert",
        "--output", "/workspace/reports/einblick.md",
    ],
    env_vars={
        "EINBLICK_ANTHROPIC_API_KEY": Variable.get("anthropic_key"),
        "SNOWFLAKE_ACCOUNT": Variable.get("snowflake_account"),
        "SNOWFLAKE_USER": Variable.get("snowflake_user"),
        "SNOWFLAKE_PASSWORD": Variable.get("snowflake_password"),
        "EINBLICK_SLACK_WEBHOOK_URL": Variable.get("einblick_slack_webhook"),
    },
    volume_mounts=[VolumeMount("reports", "/workspace/reports", read_only=False)],
)
```

The image runs as a non-root user (`einblick`), has all three platforms baked in, and ships at ~250MB. No tag = `latest`; pin to a version (`ghcr.io/kranzl/einblick:0.2.0`) for reproducible cron runs.

The interactive Claude Code path stays as-is -- the slash command runs the local venv directly, no container involved.

## Slack delivery

Add `--slack-webhook` (or `EINBLICK_SLACK_WEBHOOK_URL` env var) and einblick posts a Block Kit summary to Slack after the report is written. **No Slack app needed -- you create the webhook yourself in your own workspace.** It's a 90-second setup:

1. Visit `https://<your-workspace>.slack.com/apps/manage` and pick **Incoming Webhooks** -> **Add to Slack**
2. Pick the channel (`#data-eng`, `#alerts`, whatever)
3. Slack hands you a URL like `https://hooks.slack.com/services/T0XXX/B0YYY/ABC123def456`
4. Set it as `EINBLICK_SLACK_WEBHOOK_URL` and you're done

```bash
export EINBLICK_SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T0X/B0Y/abc123"

einblick analyze --platform snowflake --days 7 --slack-mode alert --output /tmp/r.md
```

Two modes:

- `--slack-mode digest` (default when `--slack-webhook` is set) -- always posts. Good for a weekly Monday-morning summary.
- `--slack-mode alert` -- only posts when something interesting changed vs the last run: cost moved >=20%, three or more new patterns appeared, or any pattern disappeared (someone fixed it). Quiet weeks stay quiet.

The Slack post includes the platform, time window, distinct-pattern count, total estimated cost, the top 3 patterns by impact, and a diff against the previous run if one exists. The full markdown report path is referenced as a footer so you can pull the details from your shared volume / S3.

## Pipe the report wherever

If Slack isn't your channel of choice, just pipe `/tmp/r.md` to wherever your pipeline already posts -- email, S3, GitHub Issue, etc. The markdown report is the same regardless of where it lands.

## Hook up dbt for sharper recommendations

If you use dbt Cloud, einblick can cross-reference each query pattern against your actual dbt project. Instead of "this query is expensive, materialize it," you get "this query is hitting `mart.fct_revenue` directly, which is currently a view that runs in 47s on average -- switch it to incremental." Concrete instead of generic, and tied to a real model file you can change.

There are two ways to wire dbt up. Pick whichever matches your setup -- you can do both.

### Path 1: data-only (works in interactive AND scheduled mode)

Set three env vars, pass `--dbt-aware`. einblick calls dbt Cloud's Discovery API directly to grab the model list, lineage, and per-model perf numbers. If auth fails or dbt Cloud is down, the run still finishes -- you just don't get the dbt context.

```bash
export DBT_HOST=cloud.getdbt.com
export DBT_TOKEN=dbts_...                # service token from dbt Cloud
export DBT_PROD_ENV_ID=12345             # the prod env you want to read

einblick analyze --platform snowflake --days 7 --dbt-aware --output report.md
```

**Where to find each value:**

- `DBT_TOKEN` -- dbt Cloud → Account settings → Service tokens → New. Give it "Metadata only" + "Job admin" scope. Stash the token somewhere safe, you only see it once.
- `DBT_PROD_ENV_ID` -- dbt Cloud → Deploy → Environments → click your prod environment. The number in the URL is the env ID.
- `DBT_HOST` -- `cloud.getdbt.com` for the US region. EU is `emea.dbt.com`. Check the domain on your dbt Cloud login page if unsure.

This works for both `/einblick` (interactive) and `einblick analyze` (cron). The slash command will ask if you want to use dbt context; the CLI uses it whenever you pass `--dbt-aware`.

### Path 2: full integration via dbt-mcp (Claude Code only)

Beyond just reading dbt's data, you can let the agent actually create the proposed models -- write the `.sql` and `schema.yml`, run `dbt parse / compile / run / test`, and open a PR. This requires dbt's official MCP server alongside einblick's plugin.

Install [dbt-mcp](https://github.com/dbt-labs/dbt-mcp) by adding to your `.mcp.json`:

```json
{
  "mcpServers": {
    "dbt": {
      "command": "uvx",
      "args": ["dbt-mcp"],
      "env": {
        "DBT_HOST": "cloud.getdbt.com",
        "DBT_TOKEN": "dbts_...",
        "DBT_PROD_ENV_ID": "12345",
        "DBT_DEV_ENV_ID": "12346",
        "DBT_USER_ID": "7890",
        "DBT_PROJECT_DIR": "/abs/path/to/your/dbt_project",
        "DBT_PATH": "/abs/path/to/dbt"
      }
    }
  }
}
```

Two more values you'll need:

- `DBT_DEV_ENV_ID` -- the env einblick will materialize against during validation. **Use a dev environment, not prod.** Same place as the prod env ID, just click the dev one.
- `DBT_USER_ID` -- your user ID in dbt Cloud. Account settings → Users → click your row → the number in the URL.
- `DBT_PROJECT_DIR` -- the absolute path on your machine to your dbt project (the directory with `dbt_project.yml`).
- `DBT_PATH` -- absolute path to your `dbt` binary. `which dbt` will tell you.

You also need the `dbt-codegen` package in your project's `packages.yml`. einblick uses it to generate `schema.yml` for new models:

```yaml
packages:
  - package: dbt-labs/dbt-codegen
    version: [">=0.12.0"]
```

Run `dbt deps` after adding. One-time setup.

**What happens when it's all wired up.** When you run `/einblick` and pick "yes" on the dbt context question, the slash command does the analysis as usual. After the report is written, it offers to actually apply the proposed changes:

1. Asks which proposed models you want to create
2. Asks which dbt target to test against (asks once, persists to `~/.einblick.yml`)
3. For each picked model: writes the `.sql`, runs `dbt parse → compile → run → test`
4. Generates `schema.yml` from the materialized model and writes it as a per-model file
5. Opens a PR in your dbt repo via `gh pr create`

If anything fails partway (parse error, dbt run fails, dbt-codegen missing), the `.sql` gets rolled back and the workflow stops cleanly. Nothing half-applied sitting in your project.

### Running this on a cron / Airflow with auto-PRs

If you want einblick to open dbt PRs at 3am unattended, set up a **dedicated GitHub service account** so the PRs are clearly automation:

1. Create a GitHub user like `einblick-bot`
2. Give it write access to your dbt repo
3. Generate a personal access token with `repo` scope -- this becomes `GH_TOKEN` in your task env
4. Set `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` to the bot's identity in your task env

Don't reuse your personal GitHub account. PRs from a real human imply that human reviewed the change. PRs from `einblick-bot` signal "automation, review the diff not the author."

## What you need to run einblick at all

- Python 3.10+
- One of:
  - **Snowflake**: a role with `IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE` (so you can query `ACCOUNT_USAGE.QUERY_HISTORY`)
  - **Databricks**: Unity Catalog and access to `system.query.history`
  - **MotherDuck**: a Business plan + an organization-admin token (Lite/Pro plans don't expose `MD_INFORMATION_SCHEMA.QUERY_HISTORY`)

The dbt parts above are optional -- einblick works fine without them.

### MotherDuck specifics

```bash
export MOTHERDUCK_TOKEN=your_admin_token   # Org Settings -> Create token
einblick setup --platform motherduck
einblick extract --platform motherduck --hours 24 --output /tmp/md.md --format markdown
```

Cost is estimated from `INSTANCE_TYPE` × `EXECUTION_TIME` using the published Duckling rates ($0.60/hr Pulse → $36/hr Giga). Pulse's billing is per-CU-second under the hood, so estimates skew slightly high there -- treat them as ranking, not billing.

## Warehouse credentials

Snowflake reads in this order, first hit wins:

1. `~/.snowflake/config.toml`
2. `~/.snowsql/config`
3. `SNOWFLAKE_ACCOUNT` / `SNOWFLAKE_USER` / `SNOWFLAKE_PASSWORD` env vars

If there's no password set anywhere, browser SSO kicks in. `SNOWFLAKE_HOST` is only needed for PrivateLink.

Databricks reads `~/.databrickscfg`, or you can set `DATABRICKS_HOST` / `DATABRICKS_TOKEN` / `DATABRICKS_HTTP_PATH`.

## Optional: project defaults

Don't want to type the same flags every time? Drop a `~/.einblick.yml` (your defaults) or `.einblick.yml` in a repo (project defaults). CLI flags win over both.

```yaml
platform: snowflake
days: 7
analysis_depth: standard       # quick | standard | deep
exclude_users: [FIVETRAN_USER, DBT_CLOUD, LOOKER_SERVICE]
service_user_patterns: ["FIVETRAN_*", "DBT_*"]
min_duration_ms: 100
```

## Try it without a warehouse

```bash
einblick extract --sample --format markdown --output /tmp/out.md
```

Ships with 775 realistic Snowflake queries so you can see the output shape before pointing it at prod. `einblick analyze --sample` runs the same data through the full LLM pipeline -- handy for verifying your API key works and your model handles tool-calling correctly.

If you want to read the report without running anything, [`sample_data/analysis_output.md`](./sample_data/analysis_output.md) is a pre-rendered example (Claude Opus against the bundled 775-query dataset) showing the shape of a real run -- biggest offenders, top recommendations with DDL, query rewrites, cost analysis, and structured dbt proposals.

## Subcommands

```bash
einblick extract  --platform snowflake --days 7 --output results.json
einblick analyze  --platform snowflake --days 7 --output report.md
einblick setup    --platform snowflake                # test your connection
einblick users    --platform snowflake --hours 24     # list users, flag service accounts
einblick history  list --platform snowflake           # past runs
```

`einblick --help` or `einblick <subcommand> --help` for the full flag list. Common ones below.

## Common flags

| Flag | What it does |
| ---- | ------------ |
| `--platform` | `snowflake`, `databricks`, or `motherduck` |
| `--days` | `1`, `7`, `14`, or `30` |
| `--hours` | Sub-day window. Overrides `--days`. |
| `--analysis-depth` | `quick` (top 25, fast), `standard` (top 100, default), `deep` (top 250, exhaustive) |
| `--dbt-aware` | Cross-reference patterns against dbt Cloud's Discovery API |
| `--exclude-users` | Comma-separated. |
| `--auto-exclude-service-users` | Auto-detect Fivetran/dbt/etc. and exclude them |
| `--service-user-pattern` | Repeatable glob (e.g., `FIVETRAN_*`) |
| `--no-history` | Skip saving this run to `~/.einblick/history/` |
| `--sample` | Use built-in 775-query dataset instead of a real warehouse |
| `--llm-base-url` | OpenAI-compatible endpoint override (Venice.ai, Together, etc.) |
| `--slack-webhook` | Slack incoming webhook URL. Posts a Block Kit summary after the run. |
| `--slack-mode` | `digest` (always post), `alert` (only when something changed vs last run), `off` |

## What gets saved

Every run drops the JSON result and markdown report into `~/.einblick/history/<platform>/<timestamp>.{json,md}`. Default retention is the last 12 runs per platform; tune with `--keep-history N` (or `0` for unlimited).

`einblick history list --platform snowflake` shows past runs newest-first. This sets up run-over-run diff later: "compared to last week, three new patterns appeared, pattern X got 40% cheaper."

For Airflow on ephemeral containers, point `EINBLICK_HISTORY_DIR=/mnt/shared-volume` so history survives between runs. Opt out per-run with `--no-history`.

## How it works under the hood

1. Stream query history from your warehouse in 10K-row chunks
2. Parse each statement with sqlglot, normalize literals and aliases, hash to a fingerprint
3. Write fingerprints into DuckDB and group by hash
4. Rank clusters by `execution_count × total_credits`
5. Hand the top patterns to an LLM with a platform-specific system prompt

## What you get back

- Top users, warehouses, and patterns burning the most credits
- Materialization, clustering, and denormalization recommendations with DDL
- Patterns it deliberately skipped, and why
- A `## Proposed dbt Changes` section with structured proposals (`new_model`, `modify_existing`, `access_pattern`) -- copy-paste ready, or hand off to the dbt-mcp integration above for automated creation

## Develop

```bash
cd scripts
pip install -e ".[all]"
pytest
```

## Release notes

### v0.1.0 (2026-04-26)

First public alpha. Tag your expectations accordingly: it works, but it's the first release.

**What you get**

- Three platforms: Snowflake (`ACCOUNT_USAGE.QUERY_HISTORY`), Databricks (`system.query.history`), and MotherDuck (`MD_INFORMATION_SCHEMA.QUERY_HISTORY`).
- Two entry points: the `/einblick` slash command for interactive Claude Code / Codex sessions (no API key needed) and the `einblick analyze` CLI for cron / Airflow / GitHub Actions (Anthropic, OpenAI, or any OpenAI-compatible endpoint via `--llm-base-url`).
- `--sample` mode: 775 generated queries, runs the full pipeline including the LLM call, no warehouse needed. Useful for evaluating the report quality before connecting a real account.
- Two dbt integration paths:
  - **Smarter recommendations (`--dbt-aware`)**: einblick calls the dbt Cloud Discovery API (GraphQL) directly so the LLM prestep can cross-reference each query pattern against the actual models in your dbt project. Recommendations distinguish `new_model`, `modify_existing`, and `access_pattern` from real project state instead of guesses. Needs `DBT_HOST` / `DBT_TOKEN` / `DBT_PROD_ENV_ID`. Works in both `/einblick` and `einblick analyze`.
  - **Apply the recommendations for me**: in `/einblick` only, if you have `dbt-labs/dbt-mcp` loaded in your Claude Code / Codex session, the agent will pick proposals from the report, create the `.sql` model files in your dbt project, run `dbt parse / compile / run / test`, generate the schema YAML, and open a PR — all from inside the conversation. We don't ship dbt-mcp; install it separately.
- Slack incoming-webhook delivery (`--slack-mode digest|alert|off`) with run-over-run diff detection — alerts only fire when something interesting changed.
- Service-account auto-exclusion (`--auto-exclude-service-users`) recognizes Fivetran, dbt, Looker, Tableau, Hex, Hightouch, Census, Mode, Airbyte, Meltano, Airflow, Dagster, Prefect, Stitch, Rivery, Matillion, Segment, RudderStack, plus Snowflake's `SYSTEM` / `SNOWPIPE` / `WORKSHEETS_APP_USER` / `STREAMLIT_APP_USER`, plus glob patterns `*_SVC` / `SVC_*` / `*_BOT` / etc.
- Docker image (`ghcr.io/kranzl/einblick:latest`) for scheduled runs. Mount `./reports` and `./history` as volumes for persistence.
- History is kept under `~/.einblick/history/` (atomic writes, mode `0o600`, `0o700` directory) so run-over-run diffs work without you setting anything up.

Tested end-to-end against live Snowflake, Databricks, and MotherDuck accounts. 341 unit tests plus opt-in live integration tests for each platform.

## License

MIT
