from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Any, Generator

from sqlscout.config import (
    load_databricks_credentials,
    load_motherduck_credentials,
    load_snowflake_credentials,
)
from sqlscout.models import SqlscoutConfig


class PlatformAccessError(Exception):
    pass


_HEADLESS_ENV_SIGNALS = (
    "CI",
    "CRON",
    "AIRFLOW_HOME",
    "KUBERNETES_SERVICE_HOST",
    "LAMBDA_TASK_ROOT",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "BUILDKITE",
    "JENKINS_URL",
)


def _is_non_interactive() -> bool:
    for var in _HEADLESS_ENV_SIGNALS:
        if os.environ.get(var):
            return True
    if os.path.exists("/.dockerenv"):
        return True
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        return True
    return False


@contextmanager
def connect(config: SqlscoutConfig) -> Generator[Any, None, None]:
    if config.platform == "snowflake":
        yield from _connect_snowflake(config)
    elif config.platform == "databricks":
        yield from _connect_databricks(config)
    elif config.platform == "motherduck":
        yield from _connect_motherduck(config)
    else:
        raise PlatformAccessError(f"Unknown platform: {config.platform}")


def _connect_snowflake(config: SqlscoutConfig) -> Generator[Any, None, None]:
    import snowflake.connector

    creds = load_snowflake_credentials(config)

    required = ["account", "user"]
    missing = [k for k in required if k not in creds]
    if missing:
        raise PlatformAccessError(
            f"Missing Snowflake credentials: {', '.join(missing)}. "
            "Set them in ~/.snowsql/config, environment variables "
            "(SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER), or .sqlscout.yml"
        )

    connect_kwargs = {k: v for k, v in creds.items() if v}

    if "password" not in connect_kwargs:
        if _is_non_interactive():
            raise PlatformAccessError(
                "No Snowflake password found and no TTY/DISPLAY available for browser SSO. "
                "Browser SSO (externalbrowser) cannot launch in containers, cron, or other "
                "non-interactive environments. Set SNOWFLAKE_PASSWORD, configure key-pair "
                "auth in ~/.snowflake/config.toml, or run with --connection pointing at a "
                "section that uses key-pair or PAT auth."
            )
        connect_kwargs["authenticator"] = "externalbrowser"

    conn = snowflake.connector.connect(**connect_kwargs)
    try:
        yield conn
    finally:
        conn.close()


def _connect_databricks(config: SqlscoutConfig) -> Generator[Any, None, None]:
    try:
        from databricks import sql as databricks_sql
    except ImportError:
        raise ImportError(
            "databricks-sql-connector not installed. Run: pip install sqlscout[databricks]"
        )

    creds = load_databricks_credentials(config)

    required = ["host", "http_path"]
    missing = [k for k in required if k not in creds]
    if missing:
        raise PlatformAccessError(
            f"Missing Databricks credentials: {', '.join(missing)}. "
            "Set them in ~/.databrickscfg, environment variables "
            "(DATABRICKS_HOST, DATABRICKS_HTTP_PATH, DATABRICKS_TOKEN), or .sqlscout.yml"
        )

    connect_kwargs = {
        "server_hostname": creds["host"],
        "http_path": creds["http_path"],
    }
    if "token" in creds:
        connect_kwargs["access_token"] = creds["token"]

    conn = databricks_sql.connect(**connect_kwargs)
    try:
        yield conn
    finally:
        conn.close()


def _connect_motherduck(config: SqlscoutConfig) -> Generator[Any, None, None]:
    try:
        import duckdb
    except ImportError:
        raise ImportError(
            "duckdb not installed. It's in sqlscout's main dependencies, "
            "but you may have a broken install. Run: pip install duckdb"
        )

    creds = load_motherduck_credentials(config)
    if "token" not in creds:
        raise PlatformAccessError(
            "Missing MotherDuck token. Set MOTHERDUCK_TOKEN (or motherduck_token) "
            "env var, or motherduck_token in .sqlscout.yml. Generate one at "
            "app.motherduck.com under Organization Settings -> Create token. "
            "QUERY_HISTORY needs an organization-admin token."
        )

    database = creds.get("database", "")
    uri = f"md:{database}" if database else "md:"
    conn = duckdb.connect(uri, config={"motherduck_token": creds["token"]})
    try:
        yield conn
    finally:
        conn.close()


def validate_access(conn: Any, platform: str) -> None:
    if platform == "snowflake":
        _validate_snowflake(conn)
    elif platform == "databricks":
        _validate_databricks(conn)
    elif platform == "motherduck":
        _validate_motherduck(conn)


def _validate_snowflake(conn: Any) -> None:
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY LIMIT 1"
        )
    except Exception as e:
        error_msg = str(e)
        if "access" in error_msg.lower() or "privilege" in error_msg.lower():
            raise PlatformAccessError(
                "Cannot access SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY. "
                "Your role needs the IMPORTED PRIVILEGES grant on the SNOWFLAKE database. "
                "An ACCOUNTADMIN can run: "
                "GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE <your_role>;"
            ) from e
        raise
    finally:
        cursor.close()


def _validate_databricks(conn: Any) -> None:
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM system.query.history LIMIT 1"
        )
    except Exception as e:
        error_msg = str(e)
        if "access" in error_msg.lower() or "permission" in error_msg.lower():
            raise PlatformAccessError(
                "Cannot access system.query.history. "
                "Your account needs access to the system catalog. "
                "Ensure Unity Catalog is enabled and you have the "
                "necessary permissions on system.query.history."
            ) from e
        raise
    finally:
        cursor.close()


def _validate_motherduck(conn: Any) -> None:
    try:
        conn.execute("SELECT 1 FROM MD_INFORMATION_SCHEMA.QUERY_HISTORY LIMIT 1").fetchone()
    except Exception as e:
        error_msg = str(e)
        lower = error_msg.lower()
        if "permission" in lower or "denied" in lower or "not found" in lower or "does not exist" in lower:
            raise PlatformAccessError(
                "Cannot access MD_INFORMATION_SCHEMA.QUERY_HISTORY. "
                "This view requires the Business plan and an organization-admin token. "
                "Lite/Pro tokens cannot read it. "
                "Create an admin token at app.motherduck.com -> Organization Settings -> Create token."
            ) from e
        raise
