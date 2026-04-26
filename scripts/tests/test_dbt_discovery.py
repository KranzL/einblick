from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sqlscout.dbt_discovery import (
    DbtAuthError,
    DbtConfigError,
    DbtDiscoveryClient,
    DbtDiscoveryError,
    DbtModelSummary,
    build_source_index,
    match_patterns_to_models,
    resolve_discovery_config,
)


class TestResolveDiscoveryConfig:
    def test_reads_env_vars(self, monkeypatch):
        monkeypatch.setenv("DBT_HOST", "cloud.getdbt.com")
        monkeypatch.setenv("DBT_TOKEN", "abc")
        monkeypatch.setenv("DBT_PROD_ENV_ID", "12345")
        host, token, env_id = resolve_discovery_config()
        assert host == "cloud.getdbt.com"
        assert token == "abc"
        assert env_id == "12345"

    def test_default_host_when_unset(self, monkeypatch):
        monkeypatch.delenv("DBT_HOST", raising=False)
        monkeypatch.setenv("DBT_TOKEN", "abc")
        monkeypatch.setenv("DBT_PROD_ENV_ID", "12345")
        host, _, _ = resolve_discovery_config()
        assert host == "cloud.getdbt.com"

    def test_raises_when_token_missing(self, monkeypatch):
        monkeypatch.delenv("DBT_TOKEN", raising=False)
        monkeypatch.setenv("DBT_PROD_ENV_ID", "12345")
        with pytest.raises(DbtConfigError, match="DBT_TOKEN"):
            resolve_discovery_config()

    def test_raises_when_env_id_missing(self, monkeypatch):
        monkeypatch.setenv("DBT_TOKEN", "abc")
        monkeypatch.delenv("DBT_PROD_ENV_ID", raising=False)
        with pytest.raises(DbtConfigError, match="DBT_PROD_ENV_ID"):
            resolve_discovery_config()


class TestClientInit:
    def test_rejects_non_integer_env_id(self):
        with pytest.raises(DbtConfigError, match="must be an integer"):
            DbtDiscoveryClient("cloud.getdbt.com", "tok", "abc-not-a-number")

    def test_accepts_int_or_int_string(self):
        c1 = DbtDiscoveryClient("cloud.getdbt.com", "tok", "12345")
        c2 = DbtDiscoveryClient("cloud.getdbt.com", "tok", 12345)
        assert c1._environment_id_int == 12345
        assert c2._environment_id_int == 12345


class TestDbtDiscoveryClient:
    def _mock_response(self, data=None, errors=None, status_code=200, text=""):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text
        body = {}
        if data is not None:
            body["data"] = data
        if errors is not None:
            body["errors"] = errors
        resp.json.return_value = body
        return resp

    def test_auth_error_on_401(self, monkeypatch):
        client = DbtDiscoveryClient("cloud.getdbt.com", "bad", "1")
        mock_post = MagicMock(return_value=self._mock_response(status_code=401, text="Unauthorized"))
        with patch("requests.post", mock_post):
            with pytest.raises(DbtAuthError):
                client._post("query { x }", {})

    def test_auth_error_on_403(self):
        client = DbtDiscoveryClient("cloud.getdbt.com", "bad", "1")
        mock_post = MagicMock(return_value=self._mock_response(status_code=403, text="Forbidden"))
        with patch("requests.post", mock_post):
            with pytest.raises(DbtAuthError):
                client._post("query { x }", {})

    def test_generic_error_on_500(self):
        client = DbtDiscoveryClient("cloud.getdbt.com", "ok", "1")
        mock_post = MagicMock(return_value=self._mock_response(status_code=500, text="server down"))
        with patch("requests.post", mock_post):
            with pytest.raises(DbtDiscoveryError, match="500"):
                client._post("query { x }", {})

    def test_graphql_error_in_body(self):
        client = DbtDiscoveryClient("cloud.getdbt.com", "ok", "1")
        mock_post = MagicMock(return_value=self._mock_response(errors=[{"message": "bad syntax"}]))
        with patch("requests.post", mock_post):
            with pytest.raises(DbtDiscoveryError, match="bad syntax"):
                client._post("query { x }", {})

    def test_non_json_response_body_raises_discovery_error(self):
        client = DbtDiscoveryClient("cloud.getdbt.com", "ok", "1")
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "<html>proxy interstitial</html>"
        resp.json.side_effect = ValueError("not json")
        with patch("requests.post", MagicMock(return_value=resp)):
            with pytest.raises(DbtDiscoveryError, match="non-JSON"):
                client._post("query { x }", {})

    def test_list_response_body_raises_discovery_error(self):
        client = DbtDiscoveryClient("cloud.getdbt.com", "ok", "1")
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "[]"
        resp.json.return_value = []
        with patch("requests.post", MagicMock(return_value=resp)):
            with pytest.raises(DbtDiscoveryError, match="unexpected payload"):
                client._post("query { x }", {})

    def test_empty_errors_list_does_not_index_error(self):
        client = DbtDiscoveryClient("cloud.getdbt.com", "ok", "1")
        resp = MagicMock()
        resp.status_code = 200
        resp.text = ""
        resp.json.return_value = {"data": {"x": 1}, "errors": []}
        with patch("requests.post", MagicMock(return_value=resp)):
            data = client._post("query { x }", {})
        assert data == {"x": 1}

    def test_redacts_bearer_token_in_error_text(self):
        client = DbtDiscoveryClient("cloud.getdbt.com", "ok", "1")
        leaky_text = "echoed: Authorization: Bearer dbt_abc.xyz.123"
        mock_post = MagicMock(return_value=self._mock_response(status_code=500, text=leaky_text))
        with patch("requests.post", mock_post):
            with pytest.raises(DbtDiscoveryError) as exc_info:
                client._post("query { x }", {})
        assert "dbt_abc.xyz.123" not in str(exc_info.value)
        assert "[redacted]" in str(exc_info.value)

    def test_request_pins_url_headers_and_partner(self):
        client = DbtDiscoveryClient("cloud.getdbt.com", "tok-abc", "42")
        mock_post = MagicMock(return_value=self._mock_response(data={"ok": True}))
        with patch("requests.post", mock_post):
            client._post("query GetX { x }", {"foo": "bar"})

        assert mock_post.call_count == 1
        args, kwargs = mock_post.call_args
        assert args[0] == "https://metadata.cloud.getdbt.com/graphql"
        headers = kwargs["headers"]
        assert headers["Authorization"] == "Bearer tok-abc"
        assert headers["Content-Type"] == "application/json"
        assert headers["x-dbt-partner-source"] == "sqlscout"
        body = kwargs["json"]
        assert body["query"] == "query GetX { x }"
        assert body["variables"] == {"foo": "bar"}

    def test_get_all_models_parses_and_handles_pagination(self):
        client = DbtDiscoveryClient("cloud.getdbt.com", "ok", "1")
        sources_response = self._mock_response(data={
            "environment": {"applied": {"sources": {
                "edges": [
                    {"node": {
                        "uniqueId": "source.x.raw.events",
                        "name": "events",
                        "identifier": "events",
                        "database": "RAW",
                        "schema": "PUB",
                    }},
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }}}
        })
        page1 = self._mock_response(data={
            "environment": {"applied": {"models": {
                "edges": [
                    {"node": {
                        "uniqueId": "model.x.a",
                        "name": "a",
                        "database": "DB",
                        "schema": "SCH",
                        "alias": None,
                        "filePath": "models/a.sql",
                        "config": {"materialized": "view"},
                        "parents": [
                            {"resourceType": "source",
                             "uniqueId": "source.x.raw.events"},
                        ],
                    }}
                ],
                "pageInfo": {"hasNextPage": True, "endCursor": "cur1"},
            }}}
        })
        page2 = self._mock_response(data={
            "environment": {"applied": {"models": {
                "edges": [
                    {"node": {
                        "uniqueId": "model.x.b",
                        "name": "b",
                        "database": "DB",
                        "schema": "SCH",
                        "alias": "b_view",
                        "filePath": "models/b.sql",
                        "config": {"materialized": "table"},
                        "parents": [],
                    }}
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }}}
        })
        mock_post = MagicMock(side_effect=[sources_response, page1, page2])
        with patch("requests.post", mock_post):
            models = client.get_all_models()
        assert len(models) == 2
        assert models[0].name == "a"
        assert models[0].source_tables == ["RAW.PUB.EVENTS"]
        assert models[0].materialized == "view"
        assert models[1].alias == "b_view"
        assert models[1].materialized == "table"
        assert models[1].source_tables == []
        assert mock_post.call_count == 3

    def test_get_model_performance(self):
        client = DbtDiscoveryClient("cloud.getdbt.com", "ok", "1")
        mock_post = MagicMock(return_value=self._mock_response(data={
            "environment": {"applied": {"modelHistoricalRuns": [
                {"runId": "r1", "status": "success", "executionTime": 47.0},
                {"runId": "r2", "status": "success", "executionTime": 53.0},
                {"runId": "r3", "status": "error", "executionTime": 60.0},
            ]}}
        }))
        with patch("requests.post", mock_post):
            stats = client.get_model_performance("model.x.a")
        assert stats.total_runs == 3
        assert stats.last_run_status == "success"
        assert abs(stats.avg_execution_ms - 53_333.333) < 1.0
        assert stats.max_execution_ms == 60_000


class TestSourceIndex:
    def test_builds_by_every_suffix(self):
        models = [
            DbtModelSummary(
                unique_id="model.x.stg_orders",
                name="stg_orders",
                database="DB",
                schema="STG",
                alias=None,
                materialized="view",
                source_tables=["RAW.PUB.ORDERS"],
            ),
        ]
        idx = build_source_index(models)
        assert "RAW.PUB.ORDERS" in idx
        assert "PUB.ORDERS" in idx
        assert "ORDERS" in idx
        assert "DB.STG.STG_ORDERS" in idx
        assert "STG.STG_ORDERS" in idx
        assert "STG_ORDERS" in idx

    def test_index_dedupes_within_a_model(self):
        models = [
            DbtModelSummary(
                unique_id="model.x.a",
                name="a",
                database="DB",
                schema="S",
                alias=None,
                materialized="view",
                source_tables=["RAW.A.X", "RAW.A.X"],
            ),
        ]
        idx = build_source_index(models)
        assert idx["RAW.A.X"] == ["model.x.a"]

    def test_match_picks_most_qualified_match_first(self):
        models = [
            DbtModelSummary(
                unique_id="model.x.stg_orders",
                name="stg_orders",
                database="DB",
                schema="STG",
                alias=None,
                materialized="view",
                source_tables=["RAW.PUB.ORDERS"],
            ),
            DbtModelSummary(
                unique_id="model.x.other_orders",
                name="other_orders",
                database="DB",
                schema="OTHER",
                alias=None,
                materialized="view",
                source_tables=["WAREHOUSE.OTHER.ORDERS"],
            ),
        ]
        idx = build_source_index(models)
        out = match_patterns_to_models(
            {"fp_full": ["RAW.PUB.ORDERS"], "fp_bare": ["ORDERS"]},
            idx,
        )
        assert out["fp_full"] == ["model.x.stg_orders"]
        assert set(out["fp_bare"]) == {"model.x.stg_orders", "model.x.other_orders"}

    def test_match_two_part_qualifier(self):
        models = [
            DbtModelSummary(
                unique_id="model.x.stg_orders",
                name="stg_orders",
                database="DB",
                schema="STG",
                alias=None,
                materialized="view",
                source_tables=["RAW.PUB.ORDERS"],
            ),
        ]
        idx = build_source_index(models)
        out = match_patterns_to_models({"fp": ["pub.orders"]}, idx)
        assert out["fp"] == ["model.x.stg_orders"]

    def test_match_no_match_returns_empty_for_pattern(self):
        idx = {"RAW.PUB.ORDERS": ["model.x.a"]}
        out = match_patterns_to_models({"fp": ["UNKNOWN.TABLE"]}, idx)
        assert "fp" not in out

    def test_empty_sources(self):
        idx = build_source_index([])
        assert idx == {}
        out = match_patterns_to_models({"fp": ["X"]}, idx)
        assert out == {}

    def test_ref_only_model_still_indexed_by_fqn(self):
        models = [
            DbtModelSummary(
                unique_id="model.x.fct_revenue",
                name="fct_revenue",
                database="DB",
                schema="MART",
                alias=None,
                materialized="view",
                source_tables=[],
            ),
        ]
        idx = build_source_index(models)
        assert "DB.MART.FCT_REVENUE" in idx
        assert "FCT_REVENUE" in idx
        out = match_patterns_to_models({"fp": ["mart.fct_revenue"]}, idx)
        assert out["fp"] == ["model.x.fct_revenue"]
