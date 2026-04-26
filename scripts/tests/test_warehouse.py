from einblick.warehouse import (
    credits_per_hour,
    estimate_compute_credits,
    infer_size_from_name,
    normalize_warehouse_size,
)


class TestNormalizeSize:
    def test_snowflake_style(self):
        assert normalize_warehouse_size("X-Small") == "X-SMALL"
        assert normalize_warehouse_size("2X-Large") == "2X-LARGE"
        assert normalize_warehouse_size("MEDIUM") == "MEDIUM"

    def test_underscore_style(self):
        assert normalize_warehouse_size("X_SMALL") == "X-SMALL"
        assert normalize_warehouse_size("2X_LARGE") == "2X-LARGE"

    def test_abbreviations(self):
        assert normalize_warehouse_size("XS") == "X-SMALL"
        assert normalize_warehouse_size("XL") == "X-LARGE"
        assert normalize_warehouse_size("2XL") == "2X-LARGE"

    def test_none_and_empty(self):
        assert normalize_warehouse_size(None) is None
        assert normalize_warehouse_size("") is None
        assert normalize_warehouse_size("totally-unknown-size") is None

    def test_motherduck_ducklings_recognized(self):
        for name in ("PULSE", "STANDARD", "JUMBO", "MEGA", "GIGA"):
            assert normalize_warehouse_size(name) == name


class TestInferFromName:
    def test_suffix_size_tokens(self):
        assert infer_size_from_name("WH_ETL_L") == "LARGE"
        assert infer_size_from_name("WH_ANALYTICS_XL") == "X-LARGE"
        assert infer_size_from_name("WH_DS_2XL") == "2X-LARGE"
        assert infer_size_from_name("WH_REPORTING_M") == "MEDIUM"
        assert infer_size_from_name("WH_DEV_XS") == "X-SMALL"

    def test_mid_name_size_tokens(self):
        assert infer_size_from_name("XSM_DASHBOARD_WH") == "X-SMALL"
        assert infer_size_from_name("SM_BI_WAREHOUSE") == "SMALL"

    def test_no_size_token_returns_none(self):
        assert infer_size_from_name("MY_WAREHOUSE") is None
        assert infer_size_from_name("ANALYTICS") is None

    def test_prefers_trailing_token_over_leading(self):
        assert infer_size_from_name("MEDIUM_WH_XL") == "X-LARGE"

    def test_case_insensitive(self):
        assert infer_size_from_name("wh_etl_xl") == "X-LARGE"
        assert infer_size_from_name("MY-WH-L") == "LARGE"

    def test_empty(self):
        assert infer_size_from_name(None) is None
        assert infer_size_from_name("") is None


class TestCreditsPerHour:
    def test_standard_sizes(self):
        assert credits_per_hour("X-SMALL") == 1
        assert credits_per_hour("SMALL") == 2
        assert credits_per_hour("MEDIUM") == 4
        assert credits_per_hour("LARGE") == 8
        assert credits_per_hour("X-LARGE") == 16
        assert credits_per_hour("2X-LARGE") == 32
        assert credits_per_hour("6X-LARGE") == 512

    def test_databricks_sizes(self):
        assert credits_per_hour("2X-SMALL", platform="databricks") == 6
        assert credits_per_hour("X-SMALL", platform="databricks") == 12
        assert credits_per_hour("SMALL", platform="databricks") == 12
        assert credits_per_hour("MEDIUM", platform="databricks") == 24
        assert credits_per_hour("LARGE", platform="databricks") == 48
        assert credits_per_hour("X-LARGE", platform="databricks") == 96
        assert credits_per_hour("2X-LARGE", platform="databricks") == 192
        assert credits_per_hour("5X-LARGE", platform="databricks") == 480

    def test_platform_differences(self):
        assert credits_per_hour("LARGE", platform="snowflake") == 8
        assert credits_per_hour("LARGE", platform="databricks") == 48

    def test_unknown_returns_zero(self):
        assert credits_per_hour(None) == 0
        assert credits_per_hour("WEIRD") == 0
        assert credits_per_hour("WEIRD", platform="databricks") == 0

    def test_databricks_underscore_size_normalization(self):
        from einblick.warehouse import normalize_warehouse_size
        assert normalize_warehouse_size("X_SMALL") == "X-SMALL"
        assert normalize_warehouse_size("2X_LARGE") == "2X-LARGE"
        assert normalize_warehouse_size("2X_SMALL") == "2X-SMALL"


class TestEstimateComputeCredits:
    def test_large_warehouse_one_hour(self):
        credits = estimate_compute_credits(3_600_000, "LARGE", "WH_ETL_L")
        assert credits == 8.0

    def test_xsmall_one_minute(self):
        credits = estimate_compute_credits(60_000, "X-SMALL", "WH_XS")
        assert abs(credits - (1.0 / 60.0)) < 0.001

    def test_falls_back_to_name(self):
        credits = estimate_compute_credits(3_600_000, None, "WH_ETL_L")
        assert credits == 8.0

    def test_uses_size_column_over_name(self):
        credits = estimate_compute_credits(3_600_000, "2X-Large", "WH_SMALL_TYPO")
        assert credits == 32.0

    def test_zero_when_no_size_anywhere(self):
        credits = estimate_compute_credits(3_600_000, None, "UNKNOWN_WAREHOUSE")
        assert credits == 0.0

    def test_zero_when_no_execution_time(self):
        credits = estimate_compute_credits(0, "LARGE", "WH_L")
        assert credits == 0.0
