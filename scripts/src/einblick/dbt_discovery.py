from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from einblick.redact import redact_secrets as _redact

DEFAULT_HOST = "cloud.getdbt.com"
PARTNER_HEADER = "einblick"
MAX_PAGES = 100


class DbtDiscoveryError(Exception):
    pass


class DbtAuthError(DbtDiscoveryError):
    pass


class DbtConfigError(DbtDiscoveryError):
    pass


@dataclass
class DbtModelSummary:
    unique_id: str
    name: str
    database: Optional[str]
    schema: Optional[str]
    alias: Optional[str]
    materialized: Optional[str]
    source_tables: list[str] = field(default_factory=list)
    query_usage_count: Optional[int] = None
    file_path: Optional[str] = None

    @property
    def fully_qualified_name(self) -> Optional[str]:
        if not (self.database and self.schema and (self.alias or self.name)):
            return None
        return f"{self.database}.{self.schema}.{self.alias or self.name}".upper()


@dataclass
class _SourceFqn:
    database: Optional[str]
    schema: Optional[str]
    identifier: str

    @property
    def fqn(self) -> Optional[str]:
        if not (self.database and self.schema and self.identifier):
            return None
        return f"{self.database}.{self.schema}.{self.identifier}".upper()


@dataclass
class DbtPerformanceStats:
    unique_id: str
    avg_execution_ms: Optional[float] = None
    max_execution_ms: Optional[int] = None
    total_runs: int = 0
    last_run_status: Optional[str] = None


def resolve_discovery_config() -> tuple[str, str, str]:
    host = os.environ.get("DBT_HOST", DEFAULT_HOST)
    token = os.environ.get("DBT_TOKEN", "").strip()
    env_id = os.environ.get("DBT_PROD_ENV_ID", "").strip()

    missing = [k for k, v in (("DBT_TOKEN", token), ("DBT_PROD_ENV_ID", env_id)) if not v]
    if missing:
        raise DbtConfigError(
            f"Missing required env vars for dbt Discovery API: {', '.join(missing)}. "
            f"Set them or drop --dbt-aware."
        )
    return host, token, env_id


class DbtDiscoveryClient:

    def __init__(
        self,
        host: str,
        token: str,
        environment_id: str,
        timeout: float = 30.0,
    ):
        self.url = f"https://metadata.{host}/graphql"
        self.token = token
        try:
            self._environment_id_int = int(str(environment_id).strip())
        except (TypeError, ValueError):
            raise DbtConfigError(
                f"DBT_PROD_ENV_ID must be an integer, got: {environment_id!r}"
            )
        self.environment_id = str(environment_id)
        self.timeout = timeout

    def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "x-dbt-partner-source": PARTNER_HEADER,
        }
        payload = {"query": query, "variables": variables}

        try:
            response = requests.post(
                self.url, headers=headers, json=payload, timeout=self.timeout
            )
        except requests.exceptions.RequestException as e:
            raise DbtDiscoveryError(f"Network error calling dbt Discovery: {e}")

        if response.status_code in (401, 403):
            raise DbtAuthError(
                f"dbt Discovery returned {response.status_code}. "
                f"Check DBT_TOKEN and DBT_PROD_ENV_ID."
            )
        if response.status_code >= 400:
            raise DbtDiscoveryError(
                f"dbt Discovery returned {response.status_code}: {_redact(response.text)[:500]}"
            )

        try:
            body = response.json()
        except ValueError as e:
            raise DbtDiscoveryError(
                f"dbt Discovery returned non-JSON response: {type(e).__name__}"
            )
        if not isinstance(body, dict):
            raise DbtDiscoveryError(
                f"dbt Discovery returned unexpected payload type: {type(body).__name__}"
            )
        errors = body.get("errors")
        if errors:
            if isinstance(errors, list) and errors:
                first = errors[0] if isinstance(errors[0], dict) else {}
                msg = first.get("message", "unknown GraphQL error")
            else:
                msg = "unknown GraphQL error"
            raise DbtDiscoveryError(f"GraphQL error: {msg}")

        return body.get("data") or {}

    def get_all_sources(self, page_size: int = 500) -> dict[str, _SourceFqn]:
        query = """
        query GetAllSources($envId: BigInt!, $first: Int!, $after: String) {
          environment(id: $envId) {
            applied {
              sources(first: $first, after: $after) {
                pageInfo { hasNextPage, endCursor }
                edges {
                  node {
                    uniqueId
                    name
                    identifier
                    database
                    schema
                  }
                }
              }
            }
          }
        }
        """
        out: dict[str, _SourceFqn] = {}
        for data in self._paginate(
            query,
            extra_vars={},
            page_path=["environment", "applied", "sources"],
            page_size=page_size,
        ):
            edges = _safe_path(data, ["environment", "applied", "sources", "edges"]) or []
            for edge in edges:
                node = edge.get("node") or {}
                uid = node.get("uniqueId")
                if not uid:
                    continue
                out[uid] = _SourceFqn(
                    database=node.get("database"),
                    schema=node.get("schema"),
                    identifier=node.get("identifier") or node.get("name") or "",
                )
        return out

    def get_all_models(self, page_size: int = 500) -> list[DbtModelSummary]:
        sources_by_id = self.get_all_sources()

        query = """
        query GetAllModels($envId: BigInt!, $first: Int!, $after: String) {
          environment(id: $envId) {
            applied {
              models(first: $first, after: $after) {
                pageInfo { hasNextPage, endCursor }
                edges {
                  node {
                    uniqueId
                    name
                    database
                    schema
                    alias
                    filePath
                    config
                    parents {
                      ... on SourceAppliedStateNestedNode {
                        resourceType
                        uniqueId
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        models: list[DbtModelSummary] = []
        for data in self._paginate(
            query,
            extra_vars={},
            page_path=["environment", "applied", "models"],
            page_size=page_size,
        ):
            edges = _safe_path(data, ["environment", "applied", "models", "edges"]) or []
            for edge in edges:
                node = edge.get("node") or {}
                models.append(_node_to_model(node, sources_by_id))
        return models

    def _paginate(
        self,
        query: str,
        extra_vars: dict[str, Any],
        page_path: list[str],
        page_size: int,
    ):
        after: Optional[str] = None
        previous_after: Optional[str] = None
        for page_num in range(MAX_PAGES):
            variables = {
                "envId": self._environment_id_int,
                "first": page_size,
                "after": after,
                **extra_vars,
            }
            data = self._post(query, variables)
            yield data
            page_info = _safe_path(data, [*page_path, "pageInfo"]) or {}
            if not page_info.get("hasNextPage"):
                return
            after = page_info.get("endCursor")
            if not after or after == previous_after:
                return
            previous_after = after
        import logging
        logging.getLogger("einblick.dbt_discovery").warning(
            "pagination cap (%d pages) hit; truncating results", MAX_PAGES
        )

    def get_model_performance(self, unique_id: str, last_n: int = 20) -> DbtPerformanceStats:
        query = """
        query GetModelPerformance($envId: BigInt!, $uniqueId: String!, $lastN: Int!) {
          environment(id: $envId) {
            applied {
              modelHistoricalRuns(uniqueId: $uniqueId, lastRunCount: $lastN) {
                runId
                status
                executionTime
              }
            }
          }
        }
        """
        data = self._post(
            query,
            {
                "envId": self._environment_id_int,
                "uniqueId": unique_id,
                "lastN": last_n,
            },
        )
        runs = _safe_path(data, ["environment", "applied", "modelHistoricalRuns"]) or []
        exec_times = [r.get("executionTime") for r in runs if r.get("executionTime") is not None]
        last_status = runs[0].get("status") if runs else None

        if exec_times:
            avg = sum(exec_times) / len(exec_times) * 1000.0
            mx = int(max(exec_times) * 1000.0)
        else:
            avg = None
            mx = None

        return DbtPerformanceStats(
            unique_id=unique_id,
            avg_execution_ms=avg,
            max_execution_ms=mx,
            total_runs=len(runs),
            last_run_status=last_status,
        )


def build_source_index(models: list[DbtModelSummary]) -> dict[str, list[str]]:
    raw: dict[str, set[str]] = {}
    for m in models:
        candidates: list[str] = []
        candidates.extend(m.source_tables)
        fqn = m.fully_qualified_name
        if fqn:
            candidates.append(fqn)

        keys_seen: set[str] = set()
        for full in candidates:
            parts = full.upper().split(".")
            for i in range(len(parts)):
                key = ".".join(parts[i:])
                if key in keys_seen:
                    continue
                keys_seen.add(key)
                raw.setdefault(key, set()).add(m.unique_id)
    return {key: sorted(ids) for key, ids in raw.items()}


def match_patterns_to_models(
    pattern_tables: dict[str, list[str]],
    source_index: dict[str, list[str]],
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for fingerprint, tables in pattern_tables.items():
        candidates: set[str] = set()
        for t in tables:
            parts = t.upper().split(".")
            for i in range(len(parts)):
                key = ".".join(parts[i:])
                hits = source_index.get(key)
                if hits:
                    candidates.update(hits)
                    break
        if candidates:
            out[fingerprint] = sorted(candidates)
    return out


def _node_to_model(
    node: dict[str, Any],
    sources_by_id: Optional[dict[str, _SourceFqn]] = None,
) -> DbtModelSummary:
    sources_by_id = sources_by_id or {}
    source_tables: list[str] = []
    for parent in node.get("parents", []) or []:
        if parent.get("resourceType") != "source":
            continue
        uid = parent.get("uniqueId")
        src = sources_by_id.get(uid) if uid else None
        if src and src.fqn:
            source_tables.append(src.fqn)

    config = node.get("config") or {}
    materialized = None
    if isinstance(config, dict):
        materialized = config.get("materialized")

    return DbtModelSummary(
        unique_id=node.get("uniqueId") or "",
        name=node.get("name") or "",
        database=node.get("database"),
        schema=node.get("schema"),
        alias=node.get("alias"),
        materialized=materialized,
        source_tables=source_tables,
        query_usage_count=None,
        file_path=node.get("filePath"),
    )


def _safe_path(data: dict[str, Any], keys: list[str]) -> Any:
    node: Any = data
    for k in keys:
        if node is None:
            return None
        node = node.get(k) if isinstance(node, dict) else None
    return node
