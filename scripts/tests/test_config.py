from unittest.mock import patch

from einblick.config import load_config, load_snowflake_credentials, _load_snowflake_toml
from einblick.models import EinblickConfig


class TestConfigDefaults:
    def test_default_values(self):
        config = load_config()
        assert config.days == 7
        assert config.top_n == 100
        assert config.exclude_users == []
        assert config.exclude_roles == []
        assert config.llm_provider == "anthropic"
        assert config.output_format == "json"
        assert config.platform == "snowflake"

    def test_cli_overrides(self):
        config = load_config(cli_overrides={"days": 30, "top_n": 50})
        assert config.days == 30
        assert config.top_n == 50

    def test_none_values_ignored(self):
        config = load_config(cli_overrides={"days": 14, "top_n": None})
        assert config.days == 14
        assert config.top_n == 100

    def test_platform_override(self):
        config = load_config(cli_overrides={"platform": "databricks"})
        assert config.platform == "databricks"


class TestConfigEnvironment:
    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "myaccount")
        monkeypatch.setenv("SNOWFLAKE_USER", "myuser")
        config = load_config()
        assert config.snowflake_account == "myaccount"
        assert config.snowflake_user == "myuser"

    def test_cli_overrides_env(self, monkeypatch):
        monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "env_account")
        config = load_config(cli_overrides={"snowflake_account": "cli_account"})
        assert config.snowflake_account == "cli_account"

    def test_databricks_env_vars(self, monkeypatch):
        monkeypatch.setenv("DATABRICKS_HOST", "myhost.databricks.com")
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        config = load_config()
        assert config.databricks_host == "myhost.databricks.com"
        assert config.databricks_token == "dapi123"


class TestConfigFile:
    def test_yaml_config_loading(self, tmp_path):
        config_file = tmp_path / ".einblick.yml"
        config_file.write_text("days: 14\nexclude_users:\n  - FIVETRAN\n  - DBT_CLOUD\n")
        config = load_config(config_path=str(config_file))
        assert config.days == 14
        assert config.exclude_users == ["FIVETRAN", "DBT_CLOUD"]

    def test_cli_overrides_file(self, tmp_path):
        config_file = tmp_path / ".einblick.yml"
        config_file.write_text("days: 14\ntop_n: 200\n")
        config = load_config(
            cli_overrides={"days": 30},
            config_path=str(config_file),
        )
        assert config.days == 30
        assert config.top_n == 200

    def test_platform_in_config_file(self, tmp_path):
        config_file = tmp_path / ".einblick.yml"
        config_file.write_text("platform: databricks\ndays: 7\n")
        config = load_config(config_path=str(config_file))
        assert config.platform == "databricks"


class TestSnowflakeHost:
    def test_host_from_env_var(self, monkeypatch):
        monkeypatch.setenv("SNOWFLAKE_HOST", "myorg.privatelink.snowflakecomputing.com")
        config = load_config()
        assert config.snowflake_host == "myorg.privatelink.snowflakecomputing.com"

    def test_host_included_in_credentials(self):
        config = EinblickConfig(
            snowflake_account="acct",
            snowflake_user="user",
            snowflake_host="myorg.privatelink.snowflakecomputing.com",
        )
        with patch("einblick.config._SNOWSQL_CONFIG_PATH") as mock_ini, \
             patch("einblick.config._load_snowflake_toml", return_value={}):
            mock_ini.exists.return_value = False
            creds = load_snowflake_credentials(config)
        assert creds["host"] == "myorg.privatelink.snowflakecomputing.com"


class TestSnowflakeTomlConfig:
    def test_toml_named_connection(self, tmp_path, monkeypatch):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(
            'default_connection_name = "work"\n\n'
            '[connections.work]\n'
            'account = "myorg-myaccount"\n'
            'user = "alice"\n'
            'password = "secret"\n'
            'host = "myorg.privatelink.snowflakecomputing.com"\n'
            'warehouse = "COMPUTE_WH"\n'
        )
        monkeypatch.setattr(
            "einblick.config._SNOWFLAKE_CLI_CONFIG_PATHS", [toml_path]
        )
        creds = _load_snowflake_toml("work")
        assert creds["account"] == "myorg-myaccount"
        assert creds["user"] == "alice"
        assert creds["password"] == "secret"
        assert creds["host"] == "myorg.privatelink.snowflakecomputing.com"
        assert creds["warehouse"] == "COMPUTE_WH"

    def test_toml_falls_back_to_default_connection_name(self, tmp_path, monkeypatch):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(
            'default_connection_name = "prod"\n\n'
            '[connections.prod]\n'
            'account = "prod-account"\n'
            'user = "prod-user"\n'
        )
        monkeypatch.setattr(
            "einblick.config._SNOWFLAKE_CLI_CONFIG_PATHS", [toml_path]
        )
        creds = _load_snowflake_toml("nonexistent")
        assert creds["account"] == "prod-account"

    def test_toml_returns_empty_when_no_file(self, monkeypatch):
        monkeypatch.setattr(
            "einblick.config._SNOWFLAKE_CLI_CONFIG_PATHS", []
        )
        creds = _load_snowflake_toml("work")
        assert creds == {}

    def test_toml_host_mapped_correctly(self, tmp_path, monkeypatch):
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(
            '[connections.connections]\n'
            'account = "acct"\n'
            'user = "user"\n'
            'host = "priv.snowflakecomputing.com"\n'
        )
        monkeypatch.setattr(
            "einblick.config._SNOWFLAKE_CLI_CONFIG_PATHS", [toml_path]
        )
        config = EinblickConfig(snowflake_connection="connections")
        creds = load_snowflake_credentials(config)
        assert creds.get("host") == "priv.snowflakecomputing.com"


