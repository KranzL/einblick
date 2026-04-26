from unittest.mock import MagicMock

import click
import pytest

from sqlscout.cli import (
    _format_error,
    _scrub_sensitive_flags,
    _substitute_auto_exclude,
    _user_set,
)


class TestSubstituteAutoExclude:
    def test_strips_auto_flag_and_appends_resolved_list(self):
        argv = ["extract", "--platform", "snowflake", "--auto-exclude-service-users"]
        out = _substitute_auto_exclude(argv, ["FIVETRAN_USER", "DBT_CLOUD"])
        assert "--auto-exclude-service-users" not in out
        assert "--exclude-users" in out
        idx = out.index("--exclude-users")
        assert set(out[idx + 1].split(",")) == {"DBT_CLOUD", "FIVETRAN_USER"}

    def test_merges_into_existing_exclude_users(self):
        argv = [
            "extract", "--platform", "snowflake",
            "--exclude-users", "ALICE,BOB",
            "--auto-exclude-service-users",
        ]
        out = _substitute_auto_exclude(argv, ["FIVETRAN_USER"])
        idx = out.index("--exclude-users")
        merged = out[idx + 1]
        assert set(merged.split(",")) == {"ALICE", "BOB", "FIVETRAN_USER"}
        assert "--auto-exclude-service-users" not in out

    def test_handles_equals_form(self):
        argv = ["extract", "--exclude-users=ALICE", "--auto-exclude-service-users"]
        out = _substitute_auto_exclude(argv, ["FIVETRAN_USER"])
        merged = next(t for t in out if t.startswith("--exclude-users="))
        _, _, values = merged.partition("=")
        assert set(values.split(",")) == {"ALICE", "FIVETRAN_USER"}

    def test_no_auto_flag_but_excludes_still_merged(self):
        argv = ["extract", "--exclude-users", "ALICE"]
        out = _substitute_auto_exclude(argv, ["FIVETRAN_USER"])
        idx = out.index("--exclude-users")
        assert set(out[idx + 1].split(",")) == {"ALICE", "FIVETRAN_USER"}

    def test_no_existing_flag_appends_one(self):
        argv = ["extract", "--platform", "snowflake"]
        out = _substitute_auto_exclude(argv, ["SVC_USER"])
        assert out[-2] == "--exclude-users"
        assert out[-1] == "SVC_USER"

    def test_empty_resolved_list_is_noop_on_auto_flag(self):
        argv = ["extract", "--auto-exclude-service-users"]
        out = _substitute_auto_exclude(argv, [])
        assert out == ["extract"]

    def test_deduplicates(self):
        argv = ["extract", "--exclude-users", "FIVETRAN_USER,ALICE"]
        out = _substitute_auto_exclude(argv, ["FIVETRAN_USER", "DBT_CLOUD"])
        idx = out.index("--exclude-users")
        assert set(out[idx + 1].split(",")) == {"ALICE", "DBT_CLOUD", "FIVETRAN_USER"}

    def test_does_not_swallow_following_flag_as_value(self):
        argv = ["extract", "--exclude-users", "--platform", "snowflake"]
        out = _substitute_auto_exclude(argv, ["SVC1"])
        assert "--platform" in out
        assert out.index("--platform") < out.index("snowflake")
        idx = out.index("--exclude-users")
        assert set(out[idx + 1].split(",")) == {"SVC1"}

    def test_handles_exclude_users_at_end_with_no_value(self):
        argv = ["extract", "--platform", "snowflake", "--exclude-users"]
        out = _substitute_auto_exclude(argv, ["SVC1", "SVC2"])
        idx = out.index("--exclude-users")
        assert set(out[idx + 1].split(",")) == {"SVC1", "SVC2"}


class TestScrubSensitiveFlags:
    def test_removes_slack_webhook_space_form(self):
        argv = [
            "analyze",
            "--platform", "snowflake",
            "--slack-webhook", "https://hooks.slack.com/services/T0X/B0Y/SECRET",
            "--days", "7",
        ]
        out = _scrub_sensitive_flags(argv)
        assert "--slack-webhook" not in out
        assert not any("hooks.slack.com" in t for t in out)
        assert out == ["analyze", "--platform", "snowflake", "--days", "7"]

    def test_removes_slack_webhook_equals_form(self):
        argv = [
            "analyze",
            "--slack-webhook=https://hooks.slack.com/services/T0X/B0Y/SECRET",
            "--days", "7",
        ]
        out = _scrub_sensitive_flags(argv)
        assert not any("--slack-webhook" in t for t in out)
        assert not any("hooks.slack.com" in t for t in out)

    def test_removes_llm_base_url_space_form(self):
        argv = [
            "analyze",
            "--llm-base-url", "https://api.venice.ai/api/v1",
            "--platform", "snowflake",
        ]
        out = _scrub_sensitive_flags(argv)
        assert "--llm-base-url" not in out
        assert not any("venice.ai" in t for t in out)

    def test_removes_llm_base_url_equals_form(self):
        argv = ["analyze", "--llm-base-url=https://api.venice.ai/api/v1"]
        out = _scrub_sensitive_flags(argv)
        assert not any("--llm-base-url" in t for t in out)
        assert not any("venice.ai" in t for t in out)

    def test_keeps_unrelated_flags(self):
        argv = ["analyze", "--platform", "snowflake", "--days", "7"]
        out = _scrub_sensitive_flags(argv)
        assert out == argv

    def test_strips_both_at_once(self):
        argv = [
            "analyze",
            "--platform", "snowflake",
            "--slack-webhook", "https://hooks.slack.com/services/T0X/B0Y/SECRET",
            "--llm-base-url", "https://api.venice.ai/api/v1",
            "--days", "7",
        ]
        out = _scrub_sensitive_flags(argv)
        assert out == ["analyze", "--platform", "snowflake", "--days", "7"]


class TestFormatError:
    def test_includes_exception_class_name(self):
        out = _format_error(ValueError("bad input"))
        assert out.startswith("ValueError: ")
        assert "bad input" in out

    def test_truncates_long_messages(self):
        msg = "x" * 500
        out = _format_error(ValueError(msg))
        assert len(out) <= 220

    def test_redacts_password(self):
        out = _format_error(RuntimeError("connect failed: password=hunter2 user=alice"))
        assert "hunter2" not in out
        assert "[redacted]" in out
        assert "user=alice" in out

    def test_redacts_motherduck_token_assignment(self):
        out = _format_error(RuntimeError("motherduck_token=eyJabcdef.ghijkl.mnopqr"))
        assert "eyJabcdef.ghijkl.mnopqr" not in out

    def test_redacts_motherduck_token_dict_form(self):
        out = _format_error(RuntimeError("config: {'motherduck_token': 'eyJlongtokenvalue'}"))
        assert "eyJlongtokenvalue" not in out
        assert "[redacted]" in out

    def test_redacts_authorization_header(self):
        out = _format_error(RuntimeError("Authorization: Bearer dapi.abc.xyz123"))
        assert "dapi.abc.xyz123" not in out
        assert "[redacted]" in out

    def test_redacts_bearer_token_anywhere(self):
        out = _format_error(RuntimeError("auth header was 'Bearer sk-ant-secret123'"))
        assert "sk-ant-secret123" not in out

    def test_redacts_url_embedded_credentials(self):
        out = _format_error(RuntimeError("connect to https://user:dapi-secret@host.databricks.com"))
        assert "dapi-secret" not in out
        assert "@host.databricks.com" in out

    def test_redacts_slack_webhook_path(self):
        out = _format_error(RuntimeError("POST https://hooks.slack.com/services/T0X/B0Y/SECRETXYZ failed"))
        assert "T0X/B0Y/SECRETXYZ" not in out
        assert "hooks.slack.com" in out

    def test_redacts_api_key(self):
        out = _format_error(RuntimeError("api_key: sk-ant-abcdef"))
        assert "sk-ant-abcdef" not in out

    def test_does_not_redact_innocent_strings(self):
        out = _format_error(RuntimeError("query failed: user=alice role=ANALYST"))
        assert "user=alice" in out
        assert "role=ANALYST" in out


class TestUserSet:
    def _ctx_with_source(self, source):
        ctx = MagicMock(spec=click.Context)
        ctx.get_parameter_source.return_value = source
        return ctx

    def test_default_source_returns_false(self):
        ctx = self._ctx_with_source(click.core.ParameterSource.DEFAULT)
        assert _user_set(ctx, "platform") is False

    def test_default_map_source_returns_false(self):
        ctx = self._ctx_with_source(click.core.ParameterSource.DEFAULT_MAP)
        assert _user_set(ctx, "platform") is False

    def test_commandline_source_returns_true(self):
        ctx = self._ctx_with_source(click.core.ParameterSource.COMMANDLINE)
        assert _user_set(ctx, "platform") is True

    def test_environment_source_returns_true(self):
        ctx = self._ctx_with_source(click.core.ParameterSource.ENVIRONMENT)
        assert _user_set(ctx, "platform") is True

    def test_unknown_param_returns_true_safely(self):
        ctx = MagicMock(spec=click.Context)
        ctx.get_parameter_source.side_effect = Exception("not found")
        assert _user_set(ctx, "missing_param") is True
