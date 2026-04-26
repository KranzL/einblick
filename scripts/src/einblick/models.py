from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

Platform = Literal["snowflake", "databricks", "motherduck"]


class EinblickConfig(BaseModel):
    platform: Platform = "snowflake"
    days: int = 7
    hours: Optional[int] = None
    top_n: int = 100
    exclude_users: list[str] = Field(default_factory=list)
    exclude_roles: list[str] = Field(default_factory=list)
    service_user_patterns: list[str] = Field(default_factory=list)
    service_user_roles: list[str] = Field(default_factory=list)
    min_duration_ms: int = 100
    include_trivial: bool = False
    exclude_cache_hits: bool = False
    accurate_cost: bool = False
    snowflake_connection: str = "connections"
    snowflake_account: Optional[str] = None
    snowflake_user: Optional[str] = None
    snowflake_password: Optional[str] = None
    snowflake_database: Optional[str] = None
    snowflake_warehouse: Optional[str] = None
    snowflake_role: Optional[str] = None
    snowflake_host: Optional[str] = None
    databricks_host: Optional[str] = None
    databricks_token: Optional[str] = None
    databricks_http_path: Optional[str] = None
    databricks_catalog: Optional[str] = None
    motherduck_token: Optional[str] = None
    motherduck_database: Optional[str] = None
    slack_webhook_url: Optional[str] = None
    slack_mode: Literal["off", "digest", "alert"] = "off"
    llm_provider: str = "anthropic"
    llm_model: Optional[str] = None
    llm_base_url: Optional[str] = None
    output_format: str = "json"
    keep_db: bool = False
    context_ingestion: Optional[str] = None
    context_freshness: Optional[str] = None
    context_transform: Optional[str] = None
    context_spend: Optional[str] = None
    context_service_pattern: Optional[str] = None
    analysis_depth: Literal["quick", "standard", "deep"] = "standard"
    dbt_aware: bool = False


DEPTH_PRESETS = {
    "quick": {"top_n": 25, "min_duration_ms": 500},
    "standard": {"top_n": 100, "min_duration_ms": 100},
    "deep": {"top_n": 250, "min_duration_ms": 50},
}


def resolve_preset(
    depth: str,
    top_n: Optional[int] = None,
    min_duration_ms: Optional[int] = None,
) -> tuple[int, int]:
    preset = DEPTH_PRESETS[depth]
    return (
        top_n if top_n is not None else preset["top_n"],
        min_duration_ms if min_duration_ms is not None else preset["min_duration_ms"],
    )


class RawQuery(BaseModel):
    query_id: str
    query_text: str
    user_name: str
    role_name: str
    warehouse_name: Optional[str] = None
    execution_time_ms: int
    bytes_scanned: int
    credits_used: float
    start_time: datetime
    query_type: str


class FingerprintedQuery(BaseModel):
    query_id: str
    fingerprint: str
    normalized_sql: str
    user_name: str
    role_name: str
    warehouse_name: Optional[str] = None
    execution_time_ms: int
    bytes_scanned: int
    credits_used: float
    start_time: datetime
    tables_referenced: list[str] = Field(default_factory=list)


class QueryCluster(BaseModel):
    fingerprint: str
    canonical_sql: str
    execution_count: int
    distinct_users: list[str]
    distinct_roles: list[str]
    warehouses: list[str]
    total_credits: float
    avg_execution_time_ms: float
    total_bytes_scanned: int
    tables_referenced: list[str]
    first_seen: datetime
    last_seen: datetime
    impact_score: float = 0.0


class UserStats(BaseModel):
    user_name: str
    total_queries: int
    total_credits: float
    total_bytes_scanned: int
    avg_execution_time_ms: float
    max_execution_time_ms: int
    distinct_patterns: int
    primary_role: str
    primary_warehouse: str
    likely_service_account: bool = False


class WarehouseStats(BaseModel):
    warehouse_name: str
    total_queries: int
    total_credits: float
    total_bytes_scanned: int
    avg_execution_time_ms: float
    distinct_users: int
    avg_query_cost: float


class SlowestPattern(BaseModel):
    fingerprint: str
    canonical_sql: str
    avg_execution_time_ms: float
    max_execution_time_ms: int
    execution_count: int
    total_credits: float
    tables_referenced: list[str]
    distinct_users: list[str]


class Offenders(BaseModel):
    top_users_by_cost: list[UserStats] = Field(default_factory=list)
    top_users_by_runtime: list[UserStats] = Field(default_factory=list)
    top_warehouses: list[WarehouseStats] = Field(default_factory=list)
    slowest_patterns: list[SlowestPattern] = Field(default_factory=list)
    most_scanned_patterns: list[SlowestPattern] = Field(default_factory=list)


class ExtractionMetadata(BaseModel):
    platform: Platform = "snowflake"
    time_window_days: int
    time_window_hours: Optional[int] = None
    total_queries_processed: int
    distinct_fingerprints: int
    extraction_timestamp: datetime
    excluded_users: list[str] = Field(default_factory=list)
    excluded_roles: list[str] = Field(default_factory=list)
    total_credits: float = 0.0
    total_bytes_scanned: int = 0
    dbt_aware: bool = False
    analysis_depth: str = "standard"


class AnalysisResult(BaseModel):
    clusters: list[QueryCluster]
    offenders: Offenders = Field(default_factory=Offenders)
    metadata: ExtractionMetadata
