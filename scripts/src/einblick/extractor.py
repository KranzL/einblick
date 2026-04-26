from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Generator, Optional

from einblick.models import RawQuery, EinblickConfig
from einblick.warehouse import estimate_compute_credits

_CHUNK_SIZE = 10_000

_SNOWFLAKE_NOISE_FILTER = """
  AND LENGTH(TRIM(QUERY_TEXT)) > 20
  AND TOTAL_ELAPSED_TIME >= {min_duration_ms}
  AND NOT STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'SELECT 1 ')
  AND UPPER(TRIM(QUERY_TEXT)) NOT IN ('SELECT 1', 'SELECT 1;', 'SELECT 1::INT', 'SELECT CURRENT_TIMESTAMP()', 'SELECT CURRENT_DATE()')
  AND NOT STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'SELECT CURRENT_VERSION')
  AND NOT STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'SELECT CURRENT_ACCOUNT')
  AND NOT STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'SELECT CURRENT_USER')
  AND NOT STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'SELECT CURRENT_DATABASE')
  AND NOT STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'SELECT CURRENT_SCHEMA')
  AND NOT STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'SELECT CURRENT_WAREHOUSE')
  AND NOT STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'SELECT CURRENT_ROLE')
  AND NOT STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'SELECT CURRENT_SESSION')
  AND NOT STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'SELECT SYSTEM$')
  AND NOT STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'CALL ')
  AND NOT STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'BEGIN')
  AND NOT STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'COMMIT')
  AND NOT STARTSWITH(UPPER(TRIM(QUERY_TEXT)), 'ROLLBACK')
"""

_SNOWFLAKE_SQL = """
SELECT
    QUERY_ID,
    QUERY_TEXT,
    USER_NAME,
    ROLE_NAME,
    WAREHOUSE_NAME,
    TOTAL_ELAPSED_TIME,
    BYTES_SCANNED,
    COALESCE(CREDITS_USED_CLOUD_SERVICES, 0),
    START_TIME,
    QUERY_TYPE,
    COALESCE(EXECUTION_TIME, 0),
    WAREHOUSE_SIZE
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE START_TIME >= DATEADD('hour', -%s, CURRENT_TIMESTAMP())
  AND QUERY_TYPE = 'SELECT'
  AND EXECUTION_STATUS = 'SUCCESS'
  {noise_filter}
  {user_filter}
  {role_filter}
ORDER BY START_TIME DESC
"""

_SNOWFLAKE_COUNT_SQL = """
SELECT COUNT(*)
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE START_TIME >= DATEADD('hour', -%s, CURRENT_TIMESTAMP())
  AND QUERY_TYPE = 'SELECT'
  AND EXECUTION_STATUS = 'SUCCESS'
  {noise_filter}
  {user_filter}
  {role_filter}
"""

_SNOWFLAKE_USERS_SQL = """
SELECT USER_NAME, COUNT(*) AS query_count
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE START_TIME >= DATEADD('hour', -%s, CURRENT_TIMESTAMP())
  AND QUERY_TYPE = 'SELECT'
  AND EXECUTION_STATUS = 'SUCCESS'
GROUP BY USER_NAME
ORDER BY query_count DESC
"""

_MOTHERDUCK_SELECT_LIKE_FILTER = """
  AND (
    starts_with(qt_upper, 'SELECT ')
    OR starts_with(qt_upper, 'SELECT(')
    OR starts_with(qt_upper, 'WITH ')
    OR starts_with(qt_upper, 'WITH(')
  )
"""

_MOTHERDUCK_NOISE_FILTER = """
  AND qt_len > 20
  AND total_elapsed_time >= INTERVAL '{min_duration_ms} milliseconds'
  AND qt_upper NOT IN ('SELECT 1', 'SELECT 1;', 'SELECT CURRENT_TIMESTAMP', 'SELECT CURRENT_DATE')
  AND NOT starts_with(qt_upper, 'SELECT 1 ')
  AND NOT starts_with(qt_upper, 'SELECT VERSION')
  AND NOT starts_with(qt_upper, 'SELECT CURRENT_USER')
  AND NOT starts_with(qt_upper, 'SELECT CURRENT_DATABASE')
  AND NOT starts_with(qt_upper, 'SELECT CURRENT_SCHEMA')
""" + _MOTHERDUCK_SELECT_LIKE_FILTER

_MOTHERDUCK_PRECOMPUTE_CTE = """
WITH q AS (
  SELECT *,
         upper(trim(query_text)) AS qt_upper,
         length(trim(query_text)) AS qt_len
  FROM MD_INFORMATION_SCHEMA.QUERY_HISTORY
  WHERE start_time >= now() - INTERVAL '{hours} hours'
    AND error_message IS NULL
)
"""

_MOTHERDUCK_SQL = _MOTHERDUCK_PRECOMPUTE_CTE + """
SELECT
    CAST(query_id AS VARCHAR) AS query_id,
    query_text,
    COALESCE(user_name, '') AS user_name,
    '' AS role_name,
    COALESCE(duckling_id, session_name, '') AS warehouse_name,
    CAST(EXTRACT(EPOCH FROM total_elapsed_time) * 1000 AS BIGINT) AS total_elapsed_ms,
    COALESCE(bytes_downloaded, 0) AS bytes_scanned,
    0.0 AS cloud_services_credits,
    start_time,
    'SELECT' AS query_type,
    CAST(EXTRACT(EPOCH FROM execution_time) * 1000 AS BIGINT) AS execution_time_ms,
    upper(COALESCE(instance_type, '')) AS warehouse_size
FROM q
WHERE 1=1
  {noise_filter}
  {user_filter}
ORDER BY start_time DESC
"""

_MOTHERDUCK_COUNT_SQL = _MOTHERDUCK_PRECOMPUTE_CTE + """
SELECT COUNT(*)
FROM q
WHERE 1=1
  {noise_filter}
  {user_filter}
"""

_MOTHERDUCK_USERS_SQL = _MOTHERDUCK_PRECOMPUTE_CTE + """
SELECT
    COALESCE(user_name, '') AS user_name,
    COUNT(*) AS query_count,
    NULL AS user_id
FROM q
WHERE 1=1
""" + _MOTHERDUCK_SELECT_LIKE_FILTER + """
GROUP BY user_name
ORDER BY query_count DESC
"""


_DATABRICKS_NOISE_FILTER = """
  AND length(trim(q.statement_text)) > 20
  AND q.total_duration_ms >= {min_duration_ms}
  AND upper(trim(q.statement_text)) NOT IN ('SELECT 1', 'SELECT 1;', 'SELECT CURRENT_TIMESTAMP()', 'SELECT CURRENT_DATE()')
  AND NOT startswith(upper(trim(q.statement_text)), 'SELECT 1 ')
  AND NOT startswith(upper(trim(q.statement_text)), 'SELECT CURRENT_VERSION')
  AND NOT startswith(upper(trim(q.statement_text)), 'SELECT CURRENT_USER')
  AND NOT startswith(upper(trim(q.statement_text)), 'SELECT CURRENT_DATABASE')
  AND NOT startswith(upper(trim(q.statement_text)), 'SELECT CURRENT_SCHEMA')
  AND NOT startswith(upper(trim(q.statement_text)), 'SELECT CURRENT_CATALOG')
  AND NOT startswith(upper(trim(q.statement_text)), 'CALL ')
  AND NOT startswith(upper(trim(q.statement_text)), 'BEGIN')
  AND NOT startswith(upper(trim(q.statement_text)), 'COMMIT')
  AND NOT startswith(upper(trim(q.statement_text)), 'ROLLBACK')
  AND NOT startswith(upper(trim(q.statement_text)), 'SHOW CATALOGS')
  AND NOT startswith(upper(trim(q.statement_text)), 'SHOW SCHEMAS')
  AND NOT startswith(upper(trim(q.statement_text)), 'SHOW TABLES')
  AND NOT startswith(upper(trim(q.statement_text)), 'SHOW DATABASES')
  AND NOT startswith(upper(trim(q.statement_text)), 'DESCRIBE ')
  AND NOT startswith(upper(trim(q.statement_text)), 'DESC ')
  {cache_filter}
"""

_DATABRICKS_SQL = """
SELECT
    q.statement_id,
    q.statement_text,
    COALESCE(q.executed_by, ''),
    'default',
    COALESCE(w.warehouse_name, q.compute.warehouse_id),
    q.total_duration_ms,
    COALESCE(q.read_bytes, 0),
    0.0,
    q.start_time,
    q.statement_type,
    COALESCE(q.execution_duration_ms, q.total_duration_ms),
    w.warehouse_size,
    COALESCE(q.executed_by_user_id, ''),
    COALESCE(q.from_result_cache, FALSE),
    COALESCE(q.client_driver, ''),
    COALESCE(q.read_files, 0),
    COALESCE(q.pruned_files, 0)
FROM system.query.history q
LEFT JOIN system.compute.warehouses w
    ON q.compute.warehouse_id = w.warehouse_id
WHERE q.start_time >= (current_timestamp() - INTERVAL {hours} HOURS)
  AND q.statement_type = 'SELECT'
  AND q.execution_status = 'FINISHED'
  {noise_filter}
  {user_filter}
ORDER BY q.start_time DESC
"""

_DATABRICKS_COUNT_SQL = """
SELECT COUNT(*)
FROM system.query.history q
WHERE q.start_time >= (current_timestamp() - INTERVAL {hours} HOURS)
  AND q.statement_type = 'SELECT'
  AND q.execution_status = 'FINISHED'
  {noise_filter}
  {user_filter}
"""

_DATABRICKS_BILLING_SQL = """
SELECT
    date_trunc('HOUR', u.usage_start_time) AS hour,
    u.usage_metadata.warehouse_id AS warehouse_id,
    SUM(u.usage_quantity) AS hour_dbus
FROM system.billing.usage u
WHERE u.usage_start_time >= (current_timestamp() - INTERVAL {hours} HOURS)
  AND u.usage_metadata.warehouse_id IS NOT NULL
GROUP BY 1, 2
"""

_DATABRICKS_HOURLY_QUERIES_SQL = """
SELECT
    date_trunc('HOUR', q.start_time) AS hour,
    q.compute.warehouse_id AS warehouse_id,
    SUM(q.total_duration_ms) AS total_ms
FROM system.query.history q
WHERE q.start_time >= (current_timestamp() - INTERVAL {hours} HOURS)
  AND q.statement_type = 'SELECT'
  AND q.execution_status = 'FINISHED'
GROUP BY 1, 2
"""


def fetch_hourly_proration_factors(conn: Any, config: EinblickConfig) -> dict:
    if config.platform != "databricks":
        return {}
    hours = effective_hours(config)

    billing_sql = _DATABRICKS_BILLING_SQL.format(hours=hours)
    queries_sql = _DATABRICKS_HOURLY_QUERIES_SQL.format(hours=hours)

    cursor = conn.cursor()
    try:
        cursor.execute(billing_sql)
        billing_rows = cursor.fetchall()
        cursor.execute(queries_sql)
        query_rows = cursor.fetchall()
    finally:
        cursor.close()

    billing = {(str(r[0]), r[1]): float(r[2] or 0) for r in billing_rows}
    totals = {(str(r[0]), r[1]): float(r[2] or 0) for r in query_rows}

    factors = {}
    for key, hour_dbus in billing.items():
        total_ms = totals.get(key, 0)
        if total_ms > 0 and hour_dbus > 0:
            factors[key] = hour_dbus / total_ms
    return factors


_DATABRICKS_USERS_SQL = """
SELECT q.executed_by, COUNT(*) AS query_count, ANY_VALUE(q.executed_by_user_id) AS user_id
FROM system.query.history q
WHERE q.start_time >= (current_timestamp() - INTERVAL {hours} HOURS)
  AND q.statement_type = 'SELECT'
  AND q.execution_status = 'FINISHED'
GROUP BY q.executed_by
ORDER BY query_count DESC
"""

_SNOWFLAKE_USERS_SQL_WITH_ID = """
SELECT USER_NAME, COUNT(*) AS query_count, CAST(NULL AS VARCHAR) AS user_id
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE START_TIME >= DATEADD('hour', -%s, CURRENT_TIMESTAMP())
  AND QUERY_TYPE = 'SELECT'
  AND EXECUTION_STATUS = 'SUCCESS'
GROUP BY USER_NAME
ORDER BY query_count DESC
"""

_SKIP_PATTERNS = frozenset([
    "SHOW", "DESCRIBE", "DESC", "LIST", "ALTER",
    "GRANT", "REVOKE", "PUT", "GET", "REMOVE",
    "SET", "USE", "EXPLAIN",
    "CALL", "BEGIN", "COMMIT", "ROLLBACK",
])


def effective_hours(config: EinblickConfig) -> int:
    if config.hours is not None:
        return config.hours
    return config.days * 24


def _snowflake_noise_filter(config: EinblickConfig) -> str:
    if config.include_trivial:
        return ""
    return _SNOWFLAKE_NOISE_FILTER.format(min_duration_ms=config.min_duration_ms)


def _databricks_noise_filter(config: EinblickConfig) -> str:
    if config.include_trivial:
        return ""
    cache_filter = "AND COALESCE(q.from_result_cache, FALSE) = FALSE" if config.exclude_cache_hits else ""
    return _DATABRICKS_NOISE_FILTER.format(
        min_duration_ms=config.min_duration_ms,
        cache_filter=cache_filter,
    )


def count_queries(conn: Any, config: EinblickConfig) -> int:
    hours = effective_hours(config)

    if config.platform == "snowflake":
        params: list = [hours]
        user_filter = ""
        if config.exclude_users:
            placeholders = ", ".join(["%s"] * len(config.exclude_users))
            user_filter = f"AND USER_NAME NOT IN ({placeholders})"
            params.extend(config.exclude_users)
        role_filter = ""
        if config.exclude_roles:
            placeholders = ", ".join(["%s"] * len(config.exclude_roles))
            role_filter = f"AND ROLE_NAME NOT IN ({placeholders})"
            params.extend(config.exclude_roles)
        sql = _SNOWFLAKE_COUNT_SQL.format(
            noise_filter=_snowflake_noise_filter(config),
            user_filter=user_filter,
            role_filter=role_filter,
        )

        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            return int(cursor.fetchone()[0])
        finally:
            cursor.close()

    elif config.platform == "databricks":
        user_filter = ""
        params: dict = {}
        if config.exclude_users:
            placeholders = ", ".join([":u" + str(i) for i in range(len(config.exclude_users))])
            user_filter = f"AND executed_by NOT IN ({placeholders})"
            for i, user in enumerate(config.exclude_users):
                params[f"u{i}"] = user
        sql = _DATABRICKS_COUNT_SQL.format(
            hours=hours,
            noise_filter=_databricks_noise_filter(config),
            user_filter=user_filter,
        )

        cursor = conn.cursor()
        try:
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            return int(cursor.fetchone()[0])
        finally:
            cursor.close()

    elif config.platform == "motherduck":
        user_filter, params = _motherduck_user_filter(config.exclude_users)
        sql = _MOTHERDUCK_COUNT_SQL.format(
            hours=hours,
            noise_filter=_motherduck_noise_filter(config),
            user_filter=user_filter,
        )
        return int(conn.execute(sql, params).fetchone()[0])

    return 0


def _motherduck_user_filter(exclude_users: list[str]) -> tuple[str, list[str]]:
    if not exclude_users:
        return "", []
    placeholders = ", ".join("?" * len(exclude_users))
    return f"AND USER_NAME NOT IN ({placeholders})", list(exclude_users)


def _motherduck_noise_filter(config: EinblickConfig) -> str:
    if config.include_trivial:
        return ""
    return _MOTHERDUCK_NOISE_FILTER.format(min_duration_ms=config.min_duration_ms)


def list_users(conn: Any, config: EinblickConfig) -> list[dict]:
    hours = effective_hours(config)

    if config.platform == "snowflake":
        sql = _SNOWFLAKE_USERS_SQL_WITH_ID
        cursor = conn.cursor()
        try:
            cursor.execute(sql, [hours])
            rows = cursor.fetchall()
        finally:
            cursor.close()

    elif config.platform == "databricks":
        sql = _DATABRICKS_USERS_SQL.format(hours=hours)
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
        finally:
            cursor.close()
    elif config.platform == "motherduck":
        sql = _MOTHERDUCK_USERS_SQL.format(hours=hours)
        rows = conn.execute(sql).fetchall()
    else:
        return []

    return [
        {
            "user_name": row[0] or "",
            "query_count": int(row[1] or 0),
            "user_id": row[2] if len(row) > 2 else None,
            "likely_service_account": _is_likely_service_account(
                row[0] or "",
                patterns=config.service_user_patterns,
                service_roles=config.service_user_roles,
                user_id=row[2] if len(row) > 2 else None,
                platform=config.platform,
            ),
        }
        for row in rows
    ]


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


_DEFAULT_SERVICE_NAME_PATTERNS = [
    "FIVETRAN_*", "DBT_*", "LOOKER_*", "TABLEAU_*", "HEX_*",
    "HIGHTOUCH_*", "CENSUS_*", "MODE_*", "AIRBYTE_*", "MELTANO_*",
    "AIRFLOW_*", "DAGSTER_*", "PREFECT_*", "STITCH_*", "RIVERY_*",
    "MATILLION_*", "SEGMENT_*", "RUDDERSTACK_*", "OMNI_*",
    "*_SVC", "*_BOT", "*_SERVICE", "*_SERVICEACCOUNT",
    "*_INTEGRATION", "*_AUTOMATION", "*_PIPELINE", "*_ETL",
    "*_LOADER", "*_SYNC", "SVC_*", "BOT_*",
]


_PLATFORM_BUILTIN_SERVICE_USERS = {
    "snowflake": {
        "SYSTEM",
        "SNOWFLAKE",
        "WORKSHEETS_APP_USER",
        "STREAMLIT_APP_USER",
        "SNOWPIPE",
    },
    "motherduck": set(),
    "databricks": set(),
}


def _is_likely_service_account(
    user_name: str,
    patterns: Optional[list[str]] = None,
    role_name: Optional[str] = None,
    service_roles: Optional[list[str]] = None,
    user_id: Optional[str] = None,
    platform: Optional[str] = None,
) -> bool:
    if not user_name:
        return True

    if user_id and _UUID_RE.match(user_id):
        return True

    if service_roles and role_name:
        if role_name.upper() in {r.upper() for r in service_roles}:
            return True

    import fnmatch
    upper = user_name.upper()

    if platform and upper in _PLATFORM_BUILTIN_SERVICE_USERS.get(platform, set()):
        return True

    if patterns:
        for p in patterns:
            if fnmatch.fnmatch(user_name, p) or fnmatch.fnmatch(upper, p.upper()):
                return True

    for p in _DEFAULT_SERVICE_NAME_PATTERNS:
        if fnmatch.fnmatch(upper, p):
            return True

    if platform in ("snowflake", "motherduck"):
        return False

    return "@" not in user_name


def extract_queries(
    conn: Any,
    config: EinblickConfig,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Generator[RawQuery, None, None]:
    proration: dict = {}
    if config.accurate_cost and config.platform == "databricks":
        try:
            proration = fetch_hourly_proration_factors(conn, config)
        except Exception:
            proration = {}

    if config.platform == "snowflake":
        yield from _extract_snowflake(conn, config, progress_callback, proration)
    elif config.platform == "databricks":
        yield from _extract_databricks(conn, config, progress_callback, proration)
    elif config.platform == "motherduck":
        yield from _extract_motherduck(conn, config, progress_callback)


def _extract_motherduck(
    conn: Any,
    config: EinblickConfig,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Generator[RawQuery, None, None]:
    hours = effective_hours(config)
    user_filter, params = _motherduck_user_filter(config.exclude_users)
    sql = _MOTHERDUCK_SQL.format(
        hours=hours,
        noise_filter=_motherduck_noise_filter(config),
        user_filter=user_filter,
    )
    cursor = conn.execute(sql, params)
    yield from _stream_rows(cursor, "motherduck", progress_callback)


def _extract_snowflake(
    conn: Any,
    config: EinblickConfig,
    progress_callback: Optional[Callable[[int], None]] = None,
    proration: Optional[dict] = None,
) -> Generator[RawQuery, None, None]:
    hours = effective_hours(config)
    params: list = [hours]

    user_filter = ""
    if config.exclude_users:
        placeholders = ", ".join(["%s"] * len(config.exclude_users))
        user_filter = f"AND USER_NAME NOT IN ({placeholders})"
        params.extend(config.exclude_users)

    role_filter = ""
    if config.exclude_roles:
        placeholders = ", ".join(["%s"] * len(config.exclude_roles))
        role_filter = f"AND ROLE_NAME NOT IN ({placeholders})"
        params.extend(config.exclude_roles)

    sql = _SNOWFLAKE_SQL.format(
        noise_filter=_snowflake_noise_filter(config),
        user_filter=user_filter,
        role_filter=role_filter,
    )

    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        yield from _stream_rows(cursor, "snowflake", progress_callback, proration)
    finally:
        cursor.close()


def _extract_databricks(
    conn: Any,
    config: EinblickConfig,
    progress_callback: Optional[Callable[[int], None]] = None,
    proration: Optional[dict] = None,
) -> Generator[RawQuery, None, None]:
    hours = effective_hours(config)

    user_filter = ""
    if config.exclude_users:
        placeholders = ", ".join([":u" + str(i) for i in range(len(config.exclude_users))])
        user_filter = f"AND executed_by NOT IN ({placeholders})"

    sql = _DATABRICKS_SQL.format(
        hours=hours,
        noise_filter=_databricks_noise_filter(config),
        user_filter=user_filter,
    )

    params = {}
    for i, user in enumerate(config.exclude_users):
        params[f"u{i}"] = user

    cursor = conn.cursor()
    try:
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        yield from _stream_rows(cursor, "databricks", progress_callback, proration)
    finally:
        cursor.close()


def _iter_rows(cursor: Any) -> Generator[tuple, None, None]:
    while True:
        rows = cursor.fetchmany(_CHUNK_SIZE)
        if not rows:
            break
        yield from rows


def _stream_rows(
    cursor: Any,
    platform: str = "snowflake",
    progress_callback: Optional[Callable[[int], None]] = None,
    proration: Optional[dict] = None,
) -> Generator[RawQuery, None, None]:
    total = 0
    since_progress = 0
    progress_interval = 1000
    proration = proration or {}

    last_floor_key = None
    last_hour_bucket = None
    for row in _iter_rows(cursor):
        query_text = row[1] or ""
        first_word = query_text.strip().split()[0].upper() if query_text.strip() else ""
        if first_word in _SKIP_PATTERNS:
            continue

        warehouse_name = str(row[4]) if row[4] else None
        total_elapsed_ms = int(row[5] or 0)
        cloud_services_credits = float(row[7] or 0)
        execution_time_ms = int(row[10] or 0) if len(row) > 10 else total_elapsed_ms
        warehouse_size = row[11] if len(row) > 11 else None
        start_time = row[8] if row[8] else datetime.now()

        if proration and platform == "databricks":
            floor_key = (start_time.year, start_time.month, start_time.day, start_time.hour)
            if floor_key != last_floor_key:
                last_floor_key = floor_key
                last_hour_bucket = start_time.replace(minute=0, second=0, microsecond=0).isoformat()
            compute_cost = proration.get((last_hour_bucket, warehouse_name), 0) * total_elapsed_ms
            if compute_cost <= 0:
                compute_cost = estimate_compute_credits(
                    execution_time_ms=execution_time_ms,
                    warehouse_size=warehouse_size,
                    warehouse_name=warehouse_name,
                    platform=platform,
                )
        else:
            compute_cost = estimate_compute_credits(
                execution_time_ms=execution_time_ms,
                warehouse_size=warehouse_size,
                warehouse_name=warehouse_name,
                platform=platform,
            )
        total_credits = cloud_services_credits + compute_cost

        yield RawQuery(
            query_id=str(row[0]),
            query_text=query_text,
            user_name=row[2] or "",
            role_name=row[3] or "",
            warehouse_name=warehouse_name,
            execution_time_ms=total_elapsed_ms,
            bytes_scanned=int(row[6] or 0),
            credits_used=total_credits,
            start_time=start_time,
            query_type=row[9] or "SELECT",
        )
        total += 1
        since_progress += 1

        if progress_callback and since_progress >= progress_interval:
            progress_callback(total)
            since_progress = 0

    if progress_callback and since_progress > 0:
        progress_callback(total)
