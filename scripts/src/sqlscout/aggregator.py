from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Generator, Optional

import duckdb

from sqlscout.extractor import _is_likely_service_account
from sqlscout.fingerprinter import fingerprint_query
from sqlscout.log import get_logger

_log = get_logger("aggregator")

from sqlscout.models import (
    AnalysisResult,
    ExtractionMetadata,
    Offenders,
    QueryCluster,
    RawQuery,
    SlowestPattern,
    SqlscoutConfig,
    UserStats,
    WarehouseStats,
)

_BATCH_SIZE = 10_000

_CREATE_TABLE_SQL = """
CREATE TABLE raw_queries (
    query_id VARCHAR,
    fingerprint VARCHAR,
    normalized_sql VARCHAR,
    user_name VARCHAR,
    role_name VARCHAR,
    warehouse_name VARCHAR,
    execution_time_ms BIGINT,
    bytes_scanned BIGINT,
    credits_used DOUBLE,
    start_time TIMESTAMP,
    tables_referenced VARCHAR
)
"""

_INSERT_SQL = """
INSERT INTO raw_queries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_CLUSTER_SQL = """
SELECT
    fingerprint,
    ANY_VALUE(normalized_sql) AS canonical_sql,
    COUNT(*) AS execution_count,
    list_slice(LIST(DISTINCT user_name), 1, 50) AS distinct_users,
    list_slice(LIST(DISTINCT role_name), 1, 50) AS distinct_roles,
    list_slice(LIST(DISTINCT warehouse_name) FILTER (WHERE warehouse_name IS NOT NULL), 1, 50) AS warehouses,
    SUM(credits_used) AS total_credits,
    AVG(execution_time_ms) AS avg_execution_time_ms,
    SUM(bytes_scanned) AS total_bytes_scanned,
    ANY_VALUE(tables_referenced) AS tables_referenced,
    MIN(start_time) AS first_seen,
    MAX(start_time) AS last_seen,
    COUNT(*) * SUM(credits_used) AS impact_score
FROM raw_queries
GROUP BY fingerprint
ORDER BY impact_score DESC
LIMIT ?
"""

_USERS_BY_COST_SQL = """
SELECT
    user_name,
    COUNT(*) AS total_queries,
    SUM(credits_used) AS total_credits,
    SUM(bytes_scanned) AS total_bytes_scanned,
    AVG(execution_time_ms) AS avg_execution_time_ms,
    MAX(execution_time_ms) AS max_execution_time_ms,
    COUNT(DISTINCT fingerprint) AS distinct_patterns,
    MODE(role_name) AS primary_role,
    MODE(warehouse_name) AS primary_warehouse
FROM raw_queries
GROUP BY user_name
ORDER BY total_credits DESC
LIMIT 15
"""

_USERS_BY_RUNTIME_SQL = """
SELECT
    user_name,
    COUNT(*) AS total_queries,
    SUM(credits_used) AS total_credits,
    SUM(bytes_scanned) AS total_bytes_scanned,
    AVG(execution_time_ms) AS avg_execution_time_ms,
    MAX(execution_time_ms) AS max_execution_time_ms,
    COUNT(DISTINCT fingerprint) AS distinct_patterns,
    MODE(role_name) AS primary_role,
    MODE(warehouse_name) AS primary_warehouse
FROM raw_queries
GROUP BY user_name
ORDER BY SUM(execution_time_ms) DESC
LIMIT 15
"""

_WAREHOUSES_SQL = """
SELECT
    warehouse_name,
    COUNT(*) AS total_queries,
    SUM(credits_used) AS total_credits,
    SUM(bytes_scanned) AS total_bytes_scanned,
    AVG(execution_time_ms) AS avg_execution_time_ms,
    COUNT(DISTINCT user_name) AS distinct_users,
    SUM(credits_used) / NULLIF(COUNT(*), 0) AS avg_query_cost
FROM raw_queries
WHERE warehouse_name IS NOT NULL
GROUP BY warehouse_name
ORDER BY total_credits DESC
LIMIT 10
"""

_SLOWEST_PATTERNS_SQL = """
SELECT
    fingerprint,
    ANY_VALUE(normalized_sql) AS canonical_sql,
    AVG(execution_time_ms) AS avg_execution_time_ms,
    MAX(execution_time_ms) AS max_execution_time_ms,
    COUNT(*) AS execution_count,
    SUM(credits_used) AS total_credits,
    ANY_VALUE(tables_referenced) AS tables_referenced,
    LIST(DISTINCT user_name) AS distinct_users
FROM raw_queries
GROUP BY fingerprint
HAVING COUNT(*) >= 3
ORDER BY avg_execution_time_ms DESC
LIMIT 15
"""

_MOST_SCANNED_SQL = """
SELECT
    fingerprint,
    ANY_VALUE(normalized_sql) AS canonical_sql,
    AVG(execution_time_ms) AS avg_execution_time_ms,
    MAX(execution_time_ms) AS max_execution_time_ms,
    COUNT(*) AS execution_count,
    SUM(credits_used) AS total_credits,
    ANY_VALUE(tables_referenced) AS tables_referenced,
    LIST(DISTINCT user_name) AS distinct_users
FROM raw_queries
GROUP BY fingerprint
HAVING COUNT(*) >= 3
ORDER BY SUM(bytes_scanned) DESC
LIMIT 15
"""


def aggregate(
    queries: Generator[RawQuery, None, None],
    config: SqlscoutConfig,
    progress_callback: Optional[Callable[[str, int], None]] = None,
) -> AnalysisResult:
    dialect = {"databricks": "databricks", "motherduck": "duckdb"}.get(config.platform, "snowflake")
    db_path = None if not config.keep_db else str(Path.cwd() / "sqlscout_working.duckdb")

    if db_path is None:
        db_path = os.path.join(tempfile.mkdtemp(), "sqlscout.duckdb")

    db = duckdb.connect(db_path)
    try:
        db.execute(_CREATE_TABLE_SQL)

        total_ingested = _ingest(db, queries, dialect, progress_callback)
        _log.info("Ingested %d queries into DuckDB", total_ingested)

        if progress_callback:
            progress_callback("clustering", 0)

        distinct_count = db.execute(
            "SELECT COUNT(DISTINCT fingerprint) FROM raw_queries"
        ).fetchone()[0]

        rows = db.execute(_CLUSTER_SQL, [config.top_n]).fetchall()

        clusters = []
        for row in rows:
            tables_str = row[9] or "[]"
            try:
                tables = json.loads(tables_str)
            except (json.JSONDecodeError, TypeError):
                tables = []

            clusters.append(QueryCluster(
                fingerprint=row[0],
                canonical_sql=row[1],
                execution_count=row[2],
                distinct_users=row[3] or [],
                distinct_roles=row[4] or [],
                warehouses=row[5] or [],
                total_credits=round(row[6] or 0, 6),
                avg_execution_time_ms=round(row[7] or 0, 2),
                total_bytes_scanned=row[8] or 0,
                tables_referenced=tables,
                first_seen=row[10],
                last_seen=row[11],
                impact_score=round(row[12] or 0, 4),
            ))

        if progress_callback:
            progress_callback("computing offenders", 0)

        offenders = _compute_offenders(db, config)

        totals = db.execute(
            "SELECT COALESCE(SUM(credits_used), 0), COALESCE(SUM(bytes_scanned), 0) FROM raw_queries"
        ).fetchone()

        metadata = ExtractionMetadata(
            platform=config.platform,
            time_window_days=config.days,
            time_window_hours=config.hours,
            total_queries_processed=total_ingested,
            distinct_fingerprints=distinct_count,
            extraction_timestamp=datetime.now(),
            excluded_users=config.exclude_users,
            excluded_roles=config.exclude_roles,
            total_credits=round(totals[0], 6),
            total_bytes_scanned=totals[1],
            dbt_aware=config.dbt_aware,
            analysis_depth=config.analysis_depth,
        )

        return AnalysisResult(clusters=clusters, offenders=offenders, metadata=metadata)
    finally:
        db.close()
        if not config.keep_db:
            Path(db_path).unlink(missing_ok=True)


_WORKER_DIALECT = "snowflake"


def _init_worker(dialect: str) -> None:
    global _WORKER_DIALECT
    _WORKER_DIALECT = dialect


def _fingerprint_worker(query_text: str):
    return fingerprint_query(query_text, dialect=_WORKER_DIALECT)


def _ingest(
    db: duckdb.DuckDBPyConnection,
    queries: Generator[RawQuery, None, None],
    dialect: str,
    progress_callback: Optional[Callable[[str, int], None]] = None,
) -> int:
    import multiprocessing

    worker_count = max(1, min(multiprocessing.cpu_count() - 1, 8))
    if worker_count == 1:
        return _ingest_serial(db, queries, dialect, progress_callback)

    total = 0
    pending: list[RawQuery] = []

    def _flush(chunk: list[RawQuery], pool) -> int:
        if not chunk:
            return 0
        texts = [q.query_text for q in chunk]
        results = pool.map(_fingerprint_worker, texts, chunksize=256)
        rows = []
        for q, (fp, normalized, tables) in zip(chunk, results):
            rows.append((
                q.query_id, fp, normalized,
                q.user_name, q.role_name, q.warehouse_name,
                q.execution_time_ms, q.bytes_scanned, q.credits_used,
                q.start_time, json.dumps(tables),
            ))
        db.executemany(_INSERT_SQL, rows)
        return len(rows)

    pulled = 0
    progress_interval = 500
    with multiprocessing.Pool(
        processes=worker_count,
        initializer=_init_worker,
        initargs=(dialect,),
    ) as pool:
        for query in queries:
            pending.append(query)
            pulled += 1
            if progress_callback and pulled % progress_interval == 0:
                progress_callback("ingesting", pulled)
            if len(pending) >= _BATCH_SIZE:
                total += _flush(pending, pool)
                pending = []

        if pending:
            total += _flush(pending, pool)
        if progress_callback:
            progress_callback("ingesting", total)

    return total


def _ingest_serial(
    db: duckdb.DuckDBPyConnection,
    queries: Generator[RawQuery, None, None],
    dialect: str,
    progress_callback: Optional[Callable[[str, int], None]] = None,
) -> int:
    batch: list[tuple] = []
    total = 0
    progress_interval = 500

    for query in queries:
        fp, normalized, tables = fingerprint_query(query.query_text, dialect=dialect)

        batch.append((
            query.query_id,
            fp,
            normalized,
            query.user_name,
            query.role_name,
            query.warehouse_name,
            query.execution_time_ms,
            query.bytes_scanned,
            query.credits_used,
            query.start_time,
            json.dumps(tables),
        ))
        total += 1
        if progress_callback and total % progress_interval == 0:
            progress_callback("ingesting", total)

        if len(batch) >= _BATCH_SIZE:
            db.executemany(_INSERT_SQL, batch)
            batch.clear()

    if batch:
        db.executemany(_INSERT_SQL, batch)

    if progress_callback:
        progress_callback("ingesting", total)

    return total


def _compute_offenders(db: duckdb.DuckDBPyConnection, config: SqlscoutConfig) -> Offenders:

    def _parse_user_rows(rows) -> list[UserStats]:
        return [
            UserStats(
                user_name=r[0],
                total_queries=r[1],
                total_credits=round(r[2] or 0, 6),
                total_bytes_scanned=r[3] or 0,
                avg_execution_time_ms=round(r[4] or 0, 2),
                max_execution_time_ms=r[5] or 0,
                distinct_patterns=r[6],
                primary_role=r[7] or "",
                primary_warehouse=r[8] or "",
                likely_service_account=_is_likely_service_account(
                    r[0] or "",
                    patterns=config.service_user_patterns,
                    role_name=r[7] or "",
                    service_roles=config.service_user_roles,
                    platform=config.platform,
                ),
            )
            for r in rows
        ]

    def _parse_pattern_rows(rows) -> list[SlowestPattern]:
        results = []
        for r in rows:
            tables_str = r[6] or "[]"
            try:
                tables = json.loads(tables_str)
            except (json.JSONDecodeError, TypeError):
                tables = []
            results.append(SlowestPattern(
                fingerprint=r[0],
                canonical_sql=r[1],
                avg_execution_time_ms=round(r[2] or 0, 2),
                max_execution_time_ms=r[3] or 0,
                execution_count=r[4],
                total_credits=round(r[5] or 0, 6),
                tables_referenced=tables,
                distinct_users=r[7] or [],
            ))
        return results

    users_by_cost = _parse_user_rows(db.execute(_USERS_BY_COST_SQL).fetchall())
    users_by_runtime = _parse_user_rows(db.execute(_USERS_BY_RUNTIME_SQL).fetchall())

    wh_rows = db.execute(_WAREHOUSES_SQL).fetchall()
    warehouses = [
        WarehouseStats(
            warehouse_name=r[0],
            total_queries=r[1],
            total_credits=round(r[2] or 0, 6),
            total_bytes_scanned=r[3] or 0,
            avg_execution_time_ms=round(r[4] or 0, 2),
            distinct_users=r[5],
            avg_query_cost=round(r[6] or 0, 8),
        )
        for r in wh_rows
    ]

    slowest = _parse_pattern_rows(db.execute(_SLOWEST_PATTERNS_SQL).fetchall())
    most_scanned = _parse_pattern_rows(db.execute(_MOST_SCANNED_SQL).fetchall())

    return Offenders(
        top_users_by_cost=users_by_cost,
        top_users_by_runtime=users_by_runtime,
        top_warehouses=warehouses,
        slowest_patterns=slowest,
        most_scanned_patterns=most_scanned,
    )


def export_json(result: AnalysisResult, path: str) -> None:
    data = result.model_dump(mode="json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def format_window(hours: float) -> str:
    if hours < 24:
        n = int(hours) if hours == int(hours) else None
        return f"{n} hour{'s' if n != 1 else ''}" if n is not None else f"{hours:.1f} hours"
    days = hours / 24
    n = int(days) if days == int(days) else None
    return f"{n} day{'s' if n != 1 else ''}" if n is not None else f"{days:.1f} days"


def _format_time_window(metadata) -> str:
    if metadata.time_window_hours is not None:
        return format_window(metadata.time_window_hours)
    return format_window(metadata.time_window_days * 24)


def export_markdown_summary(
    result: AnalysisResult,
    path: str,
    rerun_command: str | None = None,
    context: dict[str, str] | None = None,
) -> None:
    platform_label = result.metadata.platform.title()
    cost_label = "Est. Compute Cost"

    lines = [
        f"# SqlScout Analysis ({platform_label})",
        f"",
        f"- Platform: {platform_label}",
        f"- Time window: {_format_time_window(result.metadata)}",
        f"- Total queries processed: {result.metadata.total_queries_processed:,}",
        f"- Distinct patterns: {result.metadata.distinct_fingerprints:,}",
        f"- Total {cost_label}: {result.metadata.total_credits:.4f}",
        f"- Total bytes scanned: {result.metadata.total_bytes_scanned:,}",
        f"- Top patterns shown: {len(result.clusters)}",
        f"- Extracted: {result.metadata.extraction_timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
    ]

    if rerun_command:
        lines.extend([
            f"## Re-run this analysis",
            f"",
            f"Skip the questions next time -- this is the exact command that produced this report:",
            f"",
            f"```bash",
            f"{rerun_command}",
            f"```",
            f"",
        ])
        if context:
            lines.append("Context used for this run (feeds the analysis prompt, not the CLI):")
            lines.append("")
            for key, value in context.items():
                lines.append(f"- **{key}**: {value}")
            lines.append("")

    lines.extend([
        f"## Methodology: About the Compute Cost Estimate",
        f"",
        f"**This report shows an _estimated_ compute cost per query, not actual billed credits.** Treat the numbers as a ranking score, not a billing reconciliation.",
        f"",
        f"**How we compute it**: `(query execution time in hours) × (warehouse credits-per-hour based on size)`. Warehouse size comes from Snowflake's `WAREHOUSE_SIZE` column when present, otherwise inferred from the warehouse name (e.g., `WH_ETL_L` -> LARGE). Cloud-services overhead is added on top.",
        f"",
        f"**Why this is an approximation (and always will be)**: Snowflake bills per *warehouse*, not per query. When eight queries run concurrently on the same warehouse during a given second, Snowflake bills one warehouse-second -- not eight. Our estimate attributes the full warehouse runtime to each query independently, so summed estimates will over-count actual credits, sometimes substantially on busy warehouses. Snowflake does publish per-query attribution in `QUERY_ATTRIBUTION_HISTORY`, but that view updates infrequently, omits many queries, and isn't available on all accounts.",
        f"",
        f"**What this means for the report**: Rankings (which patterns are the most expensive relative to each other) are reliable. Absolute totals are *upper-bound approximations*. A query pattern showing `15.0 Est. Compute Cost` is more expensive than one showing `2.0`; whether the first cost you literally 15 Snowflake credits on your bill is a separate question.",
        f"",
    ])

    if result.metadata.excluded_users:
        lines.append(f"- Excluded users: {', '.join(result.metadata.excluded_users)}")
    if result.metadata.excluded_roles:
        lines.append(f"- Excluded roles: {', '.join(result.metadata.excluded_roles)}")
    lines.append("")

    off = result.offenders

    def _user_type_tag(u):
        return "service" if u.likely_service_account else "human"

    human_users_by_cost = [u for u in off.top_users_by_cost if not u.likely_service_account]
    service_users_by_cost = [u for u in off.top_users_by_cost if u.likely_service_account]

    if human_users_by_cost:
        lines.extend([f"## Biggest Offenders: Human Users by {cost_label}", ""])
        lines.append("These are humans writing ad hoc queries. Optimizations here change user behavior and dashboard SQL.")
        lines.append("")
        lines.append(f"| User | Queries | {cost_label} | Avg Runtime | Max Runtime | Patterns | Primary Role | Primary Warehouse |")
        lines.append("|------|---------|---------|-------------|-------------|----------|--------------|-------------------|")
        for u in human_users_by_cost:
            lines.append(
                f"| {u.user_name} | {u.total_queries:,} | {u.total_credits:.4f} | "
                f"{u.avg_execution_time_ms:.0f}ms | {u.max_execution_time_ms:,}ms | "
                f"{u.distinct_patterns} | {u.primary_role} | {u.primary_warehouse} |"
            )
        lines.append("")

    if service_users_by_cost:
        lines.extend([f"## Biggest Offenders: Service Accounts by {cost_label}", ""])
        lines.append("These are automated users (BI tools, ETL, dbt, etc. -- detected by lack of `@` in username). Their high cost is often expected; focus optimization on the *patterns* they run (dashboards, scheduled refreshes), not the users themselves.")
        lines.append("")
        lines.append(f"| User | Queries | {cost_label} | Avg Runtime | Max Runtime | Patterns | Primary Role | Primary Warehouse |")
        lines.append("|------|---------|---------|-------------|-------------|----------|--------------|-------------------|")
        for u in service_users_by_cost:
            lines.append(
                f"| {u.user_name} | {u.total_queries:,} | {u.total_credits:.4f} | "
                f"{u.avg_execution_time_ms:.0f}ms | {u.max_execution_time_ms:,}ms | "
                f"{u.distinct_patterns} | {u.primary_role} | {u.primary_warehouse} |"
            )
        lines.append("")

    if off.top_users_by_runtime:
        lines.extend(["## Biggest Offenders: Users by Total Runtime", ""])
        lines.append(f"| Type | User | Queries | {cost_label} | Avg Runtime | Max Runtime | Primary Warehouse |")
        lines.append("|------|------|---------|---------|-------------|-------------|-------------------|")
        for u in off.top_users_by_runtime:
            lines.append(
                f"| {_user_type_tag(u)} | {u.user_name} | {u.total_queries:,} | {u.total_credits:.4f} | "
                f"{u.avg_execution_time_ms:.0f}ms | {u.max_execution_time_ms:,}ms | {u.primary_warehouse} |"
            )
        lines.append("")

    if off.top_warehouses:
        wh_label = "Warehouses" if result.metadata.platform == "snowflake" else "SQL Warehouses"
        lines.extend([f"## Biggest Offenders: {wh_label}", ""])
        lines.append(f"| Warehouse | Queries | {cost_label} | Avg Runtime | Users | Avg Cost/Query |")
        lines.append("|-----------|---------|---------|-------------|-------|----------------|")
        for w in off.top_warehouses:
            lines.append(
                f"| {w.warehouse_name} | {w.total_queries:,} | {w.total_credits:.4f} | "
                f"{w.avg_execution_time_ms:.0f}ms | {w.distinct_users} | {w.avg_query_cost:.6f} |"
            )
        lines.append("")

    if off.slowest_patterns:
        lines.extend(["## Biggest Offenders: Slowest Query Patterns", ""])
        for i, p in enumerate(off.slowest_patterns, 1):
            lines.extend([
                f"### Slow Pattern {i} ({p.fingerprint})",
                f"- Avg runtime: {p.avg_execution_time_ms:,.0f}ms | Max: {p.max_execution_time_ms:,}ms",
                f"- Executions: {p.execution_count:,} | {cost_label}: {p.total_credits:.4f}",
                f"- Users: {', '.join(p.distinct_users[:5])}",
                f"- Tables: {', '.join(p.tables_referenced)}",
                f"```sql",
                p.canonical_sql,
                f"```",
                f"",
            ])

    if off.most_scanned_patterns:
        lines.extend(["## Biggest Offenders: Most Data Scanned", ""])
        for i, p in enumerate(off.most_scanned_patterns, 1):
            lines.extend([
                f"### Heavy Scan {i} ({p.fingerprint})",
                f"- Avg runtime: {p.avg_execution_time_ms:,.0f}ms",
                f"- Executions: {p.execution_count:,} | {cost_label}: {p.total_credits:.4f}",
                f"- Users: {', '.join(p.distinct_users[:5])}",
                f"- Tables: {', '.join(p.tables_referenced)}",
                f"```sql",
                p.canonical_sql,
                f"```",
                f"",
            ])

    lines.extend(["---", "", "## Top Query Patterns by Impact", ""])

    for i, cluster in enumerate(result.clusters, 1):
        lines.extend([
            f"### Pattern {i} (fingerprint: {cluster.fingerprint})",
            f"",
            f"- Executions: {cluster.execution_count:,}",
            f"- Users: {', '.join(cluster.distinct_users)}",
            f"- Roles: {', '.join(cluster.distinct_roles)}",
            f"- Warehouses: {', '.join(cluster.warehouses)}",
            f"- Total {cost_label}: {cluster.total_credits:.4f}",
            f"- Avg execution time: {cluster.avg_execution_time_ms:.0f}ms",
            f"- Total bytes scanned: {cluster.total_bytes_scanned:,}",
            f"- Tables: {', '.join(cluster.tables_referenced)}",
            f"- First seen: {cluster.first_seen}",
            f"- Last seen: {cluster.last_seen}",
            f"- Impact score: {cluster.impact_score:.4f}",
            f"",
            f"```sql",
            cluster.canonical_sql,
            f"```",
            f"",
        ])

    with open(path, "w") as f:
        f.write("\n".join(lines))
