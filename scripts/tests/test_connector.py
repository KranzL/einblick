import pytest
from unittest.mock import patch, MagicMock

from sqlscout.connector import connect, validate_access, PlatformAccessError
from sqlscout.models import SqlscoutConfig


class TestConnectSnowflake:
    @patch("sqlscout.connector.load_snowflake_credentials")
    @patch("snowflake.connector.connect")
    def test_connects_with_password(self, mock_sf_connect, mock_creds):
        mock_creds.return_value = {"account": "myaccount", "user": "myuser", "password": "mypass"}
        mock_conn = MagicMock()
        mock_sf_connect.return_value = mock_conn
        config = SqlscoutConfig(platform="snowflake")

        with connect(config) as conn:
            assert conn is mock_conn

        mock_sf_connect.assert_called_once()
        call_kwargs = mock_sf_connect.call_args[1]
        assert call_kwargs["account"] == "myaccount"
        assert "authenticator" not in call_kwargs

    @patch("sqlscout.connector.load_snowflake_credentials")
    @patch("snowflake.connector.connect")
    @patch("sqlscout.connector._is_non_interactive", return_value=False)
    def test_uses_externalbrowser_without_password_in_tty(self, mock_tty, mock_sf_connect, mock_creds):
        mock_creds.return_value = {"account": "myaccount", "user": "myuser"}
        mock_sf_connect.return_value = MagicMock()
        config = SqlscoutConfig(platform="snowflake")

        with connect(config) as conn:
            pass

        call_kwargs = mock_sf_connect.call_args[1]
        assert call_kwargs["authenticator"] == "externalbrowser"

    @patch("sqlscout.connector.load_snowflake_credentials")
    @patch("snowflake.connector.connect")
    @patch("sqlscout.connector._is_non_interactive", return_value=True)
    def test_refuses_browser_sso_in_non_interactive_env(self, mock_tty, mock_sf_connect, mock_creds):
        mock_creds.return_value = {"account": "myaccount", "user": "myuser"}
        config = SqlscoutConfig(platform="snowflake")

        with pytest.raises(PlatformAccessError, match="non-interactive"):
            with connect(config):
                pass
        mock_sf_connect.assert_not_called()

    @patch("sqlscout.connector.load_snowflake_credentials")
    def test_raises_on_missing_credentials(self, mock_creds):
        mock_creds.return_value = {"user": "myuser"}
        config = SqlscoutConfig(platform="snowflake")

        with pytest.raises(PlatformAccessError, match="Missing Snowflake credentials"):
            with connect(config):
                pass

    @patch("sqlscout.connector.load_snowflake_credentials")
    @patch("snowflake.connector.connect")
    def test_closes_connection_on_exit(self, mock_sf_connect, mock_creds):
        mock_creds.return_value = {"account": "a", "user": "u", "password": "p"}
        mock_conn = MagicMock()
        mock_sf_connect.return_value = mock_conn
        config = SqlscoutConfig(platform="snowflake")

        with connect(config):
            pass

        mock_conn.close.assert_called_once()


class TestConnectDatabricks:
    @patch("sqlscout.connector.load_databricks_credentials")
    @patch.dict("sys.modules", {"databricks": MagicMock(), "databricks.sql": MagicMock()})
    def test_raises_on_missing_credentials(self, mock_creds):
        mock_creds.return_value = {"host": "myhost.databricks.com"}
        config = SqlscoutConfig(platform="databricks")

        with pytest.raises(PlatformAccessError, match="Missing Databricks credentials"):
            with connect(config):
                pass

    def test_raises_on_unknown_platform(self):
        config = SqlscoutConfig.model_construct(platform="bigquery")

        with pytest.raises(PlatformAccessError, match="Unknown platform"):
            with connect(config):
                pass


class TestValidateAccess:
    def test_snowflake_access_denied(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.execute.side_effect = Exception("access denied for table QUERY_HISTORY")

        with pytest.raises(PlatformAccessError, match="IMPORTED PRIVILEGES"):
            validate_access(conn, "snowflake")

    def test_snowflake_success(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        validate_access(conn, "snowflake")
        cursor.execute.assert_called_once()

    def test_databricks_permission_denied(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.execute.side_effect = Exception("permission denied for system.query.history")

        with pytest.raises(PlatformAccessError, match="Unity Catalog"):
            validate_access(conn, "databricks")
