from __future__ import annotations

import re
from typing import Literal, Optional


Platform = Literal["snowflake", "databricks", "motherduck"]


_SNOWFLAKE_SIZE_CREDITS_PER_HOUR = {
    "X-SMALL": 1,
    "SMALL": 2,
    "MEDIUM": 4,
    "LARGE": 8,
    "X-LARGE": 16,
    "2X-LARGE": 32,
    "3X-LARGE": 64,
    "4X-LARGE": 128,
    "5X-LARGE": 256,
    "6X-LARGE": 512,
}

_DATABRICKS_SIZE_DBUS_PER_HOUR = {
    "2X-SMALL": 6,
    "X-SMALL": 12,
    "SMALL": 12,
    "MEDIUM": 24,
    "LARGE": 48,
    "X-LARGE": 96,
    "2X-LARGE": 192,
    "3X-LARGE": 288,
    "4X-LARGE": 384,
    "5X-LARGE": 480,
}

_MOTHERDUCK_INSTANCE_RATES_USD_PER_HOUR = {
    "PULSE": 0.60,
    "STANDARD": 2.40,
    "JUMBO": 4.80,
    "MEGA": 12.00,
    "GIGA": 36.00,
}

_NAME_TOKEN_TO_SIZE = {
    "6XLARGE": "6X-LARGE", "6XL": "6X-LARGE",
    "5XLARGE": "5X-LARGE", "5XL": "5X-LARGE",
    "4XLARGE": "4X-LARGE", "4XL": "4X-LARGE",
    "3XLARGE": "3X-LARGE", "3XL": "3X-LARGE",
    "2XLARGE": "2X-LARGE", "2XL": "2X-LARGE",
    "2XSMALL": "2X-SMALL", "2XS": "2X-SMALL",
    "XLARGE": "X-LARGE", "XL": "X-LARGE",
    "LARGE": "LARGE", "LG": "LARGE", "L": "LARGE",
    "MEDIUM": "MEDIUM", "MED": "MEDIUM", "MD": "MEDIUM", "M": "MEDIUM",
    "SMALL": "SMALL", "SM": "SMALL", "S": "SMALL",
    "XSMALL": "X-SMALL", "XSM": "X-SMALL", "XS": "X-SMALL",
}


def normalize_warehouse_size(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    upper = raw.strip().upper().replace("_", "-").replace(" ", "-")
    if upper in _SNOWFLAKE_SIZE_CREDITS_PER_HOUR or upper in _DATABRICKS_SIZE_DBUS_PER_HOUR:
        return upper
    if upper in _MOTHERDUCK_INSTANCE_RATES_USD_PER_HOUR:
        return upper
    collapsed = upper.replace("-", "")
    return _NAME_TOKEN_TO_SIZE.get(collapsed)


def infer_size_from_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    tokens = re.split(r"[_\-\s]+", name.upper())
    for token in reversed(tokens):
        if token in _NAME_TOKEN_TO_SIZE:
            return _NAME_TOKEN_TO_SIZE[token]
    return None


def credits_per_hour(size: Optional[str], platform: Platform = "snowflake") -> float:
    if not size:
        return 0.0
    if platform == "motherduck":
        table = _MOTHERDUCK_INSTANCE_RATES_USD_PER_HOUR
    elif platform == "databricks":
        table = _DATABRICKS_SIZE_DBUS_PER_HOUR
    else:
        table = _SNOWFLAKE_SIZE_CREDITS_PER_HOUR
    return float(table.get(size, 0))


def estimate_compute_credits(
    execution_time_ms: int,
    warehouse_size: Optional[str],
    warehouse_name: Optional[str],
    platform: Platform = "snowflake",
) -> float:
    if execution_time_ms <= 0:
        return 0.0

    size = normalize_warehouse_size(warehouse_size) or infer_size_from_name(warehouse_name)
    if not size:
        return 0.0

    hours = execution_time_ms / 1000.0 / 3600.0
    return hours * credits_per_hour(size, platform)
