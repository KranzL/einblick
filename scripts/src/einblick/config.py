from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from einblick.models import EinblickConfig

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

_SNOWSQL_CONFIG_PATH = Path.home() / ".snowsql" / "config"
_SNOWFLAKE_CLI_CONFIG_PATHS = [
    Path.home() / ".snowflake" / "config.toml",
    Path.home() / "Library" / "Application Support" / "snowflake" / "config.toml",
    Path.home() / ".config" / "snowflake" / "config.toml",
]
_DATABRICKS_CONFIG_PATH = Path.home() / ".databrickscfg"
_USER_CONFIG_PATH = Path.home() / ".einblick.yml"
_PROJECT_CONFIG_NAME = ".einblick.yml"

_ENV_MAP = {
    "SNOWFLAKE_ACCOUNT": "snowflake_account",
    "SNOWFLAKE_USER": "snowflake_user",
    "SNOWFLAKE_PASSWORD": "snowflake_password",
    "SNOWFLAKE_DATABASE": "snowflake_database",
    "SNOWFLAKE_WAREHOUSE": "snowflake_warehouse",
    "SNOWFLAKE_ROLE": "snowflake_role",
    "SNOWFLAKE_HOST": "snowflake_host",
    "DATABRICKS_HOST": "databricks_host",
    "DATABRICKS_TOKEN": "databricks_token",
    "DATABRICKS_HTTP_PATH": "databricks_http_path",
    "DATABRICKS_CATALOG": "databricks_catalog",
}

_SNOWFLAKE_KEY_MAP = {
    "accountname": "account",
    "account": "account",
    "username": "user",
    "user": "user",
    "password": "password",
    "dbname": "database",
    "database": "database",
    "schemaname": "schema",
    "schema": "schema",
    "warehousename": "warehouse",
    "warehouse": "warehouse",
    "rolename": "role",
    "role": "role",
    "host": "host",
    "hostname": "host",
}


def load_config(
    cli_overrides: dict[str, Any] | None = None,
    config_path: str | None = None,
) -> EinblickConfig:
    merged: dict[str, Any] = {}

    user_config = _load_yaml(_USER_CONFIG_PATH)
    merged.update(user_config)

    project_path = Path(config_path) if config_path else Path.cwd() / _PROJECT_CONFIG_NAME
    project_config = _load_yaml(project_path)
    merged.update(project_config)

    for env_var, config_key in _ENV_MAP.items():
        val = os.environ.get(env_var)
        if val:
            merged[config_key] = val

    if cli_overrides:
        merged.update({k: v for k, v in cli_overrides.items() if v is not None})

    return EinblickConfig(**merged)


def load_snowflake_credentials(config: EinblickConfig) -> dict[str, str]:
    creds: dict[str, str] = {}

    toml_creds = _load_snowflake_toml(config.snowflake_connection)
    creds.update(toml_creds)

    if not creds and _SNOWSQL_CONFIG_PATH.exists():
        parser = configparser.ConfigParser()
        parser.read(_SNOWSQL_CONFIG_PATH)

        section = config.snowflake_connection
        if not parser.has_section(section):
            section = "connections"

        if parser.has_section(section):
            for snowsql_key, cred_key in _SNOWFLAKE_KEY_MAP.items():
                if parser.has_option(section, snowsql_key):
                    creds[cred_key] = parser.get(section, snowsql_key)

    if config.snowflake_account:
        creds["account"] = config.snowflake_account
    if config.snowflake_user:
        creds["user"] = config.snowflake_user
    if config.snowflake_password:
        creds["password"] = config.snowflake_password
    if config.snowflake_database:
        creds["database"] = config.snowflake_database
    if config.snowflake_warehouse:
        creds["warehouse"] = config.snowflake_warehouse
    if config.snowflake_role:
        creds["role"] = config.snowflake_role
    if config.snowflake_host:
        creds["host"] = config.snowflake_host

    return creds


def _load_snowflake_toml(connection_name: str) -> dict[str, str]:
    if tomllib is None:
        return {}

    for path in _SNOWFLAKE_CLI_CONFIG_PATHS:
        if not path.exists():
            continue

        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            continue

        connections = data.get("connections", {})
        if not isinstance(connections, dict):
            return {}

        target = None
        if connection_name in connections:
            target = connections[connection_name]
        else:
            default_name = data.get("default_connection_name")
            if default_name and default_name in connections:
                target = connections[default_name]
            elif connections:
                first_key = next(iter(connections))
                target = connections[first_key]

        if not target or not isinstance(target, dict):
            return {}

        creds: dict[str, str] = {}
        for key, value in target.items():
            mapped = _SNOWFLAKE_KEY_MAP.get(key.lower())
            if mapped and value is not None:
                creds[mapped] = str(value)
        return creds

    return {}


def load_motherduck_credentials(config: EinblickConfig) -> dict[str, str]:
    creds: dict[str, str] = {}

    for env_name in ("motherduck_token", "MOTHERDUCK_TOKEN"):
        value = os.environ.get(env_name)
        if value:
            creds["token"] = value
            break

    if config.motherduck_token:
        creds["token"] = config.motherduck_token
    if config.motherduck_database:
        creds["database"] = config.motherduck_database

    return creds


def load_databricks_credentials(config: EinblickConfig) -> dict[str, str]:
    creds: dict[str, str] = {}

    if _DATABRICKS_CONFIG_PATH.exists():
        parser = configparser.ConfigParser()
        parser.read(_DATABRICKS_CONFIG_PATH)

        defaults = parser.defaults()
        if defaults:
            if "host" in defaults:
                creds["host"] = defaults["host"]
            if "token" in defaults:
                creds["token"] = defaults["token"]
            if "http_path" in defaults:
                creds["http_path"] = defaults["http_path"]

    if config.databricks_host:
        creds["host"] = config.databricks_host
    if config.databricks_token:
        creds["token"] = config.databricks_token
    if config.databricks_http_path:
        creds["http_path"] = config.databricks_http_path

    return creds


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}
