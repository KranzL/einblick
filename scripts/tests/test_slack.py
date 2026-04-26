from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from sqlscout.models import (
    AnalysisResult,
    ExtractionMetadata,
    Offenders,
    QueryCluster,
)
from sqlscout.slack import (
    ALERT_COST_DELTA_PCT,
    ALERT_NEW_PATTERN_COUNT,
    RunDiff,
    _build_blocks,
    compute_diff_against_previous,
    post_report,
    should_post,
)


def _result(total_credits: float = 0.0, fingerprints: list[str] = None) -> AnalysisResult:
    fingerprints = fingerprints or ["fp_a", "fp_b", "fp_c"]
    now = datetime.now()
    clusters = [
        QueryCluster(
            fingerprint=fp,
            canonical_sql="select 1",
            execution_count=10,
            distinct_users=[],
            distinct_roles=[],
            warehouses=[],
            total_credits=1.0,
            avg_execution_time_ms=100.0,
            total_bytes_scanned=0,
            tables_referenced=[],
            first_seen=now,
            last_seen=now,
        )
        for fp in fingerprints
    ]
    return AnalysisResult(
        clusters=clusters,
        offenders=Offenders(),
        metadata=ExtractionMetadata(
            platform="snowflake",
            time_window_days=7,
            total_queries_processed=100,
            distinct_fingerprints=len(clusters),
            extraction_timestamp=now,
            total_credits=total_credits,
        ),
    )


class TestRunDiff:
    def test_interesting_when_cost_jumps(self):
        diff = RunDiff(total_credits_before=10.0, total_credits_after=15.0, cost_delta_pct=50.0)
        assert diff.is_interesting

    def test_interesting_when_cost_drops(self):
        diff = RunDiff(total_credits_before=15.0, total_credits_after=10.0, cost_delta_pct=-33.3)
        assert diff.is_interesting

    def test_interesting_when_many_new_patterns(self):
        diff = RunDiff(new_fingerprints=["a", "b", "c"])
        assert diff.is_interesting

    def test_interesting_when_pattern_disappears(self):
        diff = RunDiff(gone_fingerprints=["a"])
        assert diff.is_interesting

    def test_not_interesting_when_below_thresholds(self):
        diff = RunDiff(
            new_fingerprints=["a"],
            cost_delta_pct=5.0,
            total_credits_before=100.0,
            total_credits_after=105.0,
        )
        assert not diff.is_interesting

    def test_alert_thresholds_match_constants(self):
        assert ALERT_NEW_PATTERN_COUNT == 3
        assert ALERT_COST_DELTA_PCT == 20.0


class TestShouldPost:
    def test_off_never_posts(self):
        assert not should_post("off", None)
        assert not should_post("off", RunDiff(new_fingerprints=["a", "b", "c"]))

    def test_digest_always_posts(self):
        assert should_post("digest", None)
        assert should_post("digest", RunDiff())

    def test_alert_skips_when_not_interesting(self):
        assert not should_post("alert", RunDiff())

    def test_alert_skips_when_no_diff(self):
        assert not should_post("alert", None)

    def test_alert_posts_when_interesting(self):
        assert should_post("alert", RunDiff(gone_fingerprints=["a"]))


class TestComputeDiff:
    def test_returns_none_when_only_one_run(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SQLSCOUT_HISTORY_DIR", str(tmp_path))
        result = _result()
        assert compute_diff_against_previous(result) is None

    def test_diffs_against_prior_run(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SQLSCOUT_HISTORY_DIR", str(tmp_path))
        snowflake_dir = tmp_path / "snowflake"
        snowflake_dir.mkdir(parents=True)

        prior_data = {
            "clusters": [
                {"fingerprint": "fp_a"},
                {"fingerprint": "fp_old"},
            ],
            "metadata": {"total_credits": 10.0},
        }
        (snowflake_dir / "20260424_100000.json").write_text(json.dumps(prior_data))
        (snowflake_dir / "20260425_100000.json").write_text("{}")

        result = _result(total_credits=15.0, fingerprints=["fp_a", "fp_new1", "fp_new2"])
        diff = compute_diff_against_previous(result)
        assert diff is not None
        assert sorted(diff.new_fingerprints) == ["fp_new1", "fp_new2"]
        assert diff.gone_fingerprints == ["fp_old"]
        assert diff.total_credits_before == 10.0
        assert diff.total_credits_after == 15.0
        assert abs(diff.cost_delta_pct - 50.0) < 1e-6

    def test_handles_zero_prior_cost(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SQLSCOUT_HISTORY_DIR", str(tmp_path))
        snowflake_dir = tmp_path / "snowflake"
        snowflake_dir.mkdir(parents=True)
        (snowflake_dir / "20260424_100000.json").write_text(json.dumps({
            "clusters": [], "metadata": {"total_credits": 0.0}
        }))
        (snowflake_dir / "20260425_100000.json").write_text("{}")

        diff = compute_diff_against_previous(_result(total_credits=5.0))
        assert diff is not None
        assert diff.cost_delta_pct == 0.0

    def test_returns_none_on_corrupt_prior(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SQLSCOUT_HISTORY_DIR", str(tmp_path))
        snowflake_dir = tmp_path / "snowflake"
        snowflake_dir.mkdir(parents=True)
        (snowflake_dir / "20260424_100000.json").write_text("{not json")
        (snowflake_dir / "20260425_100000.json").write_text("{}")

        assert compute_diff_against_previous(_result()) is None


class TestPostReport:
    def test_posts_blocks_payload(self):
        with patch("requests.post") as mock_post:
            resp = MagicMock(status_code=200)
            mock_post.return_value = resp
            ok = post_report("https://hooks.slack.com/services/x/y/z", _result())
        assert ok is True
        url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        assert url == "https://hooks.slack.com/services/x/y/z"
        assert "blocks" in kwargs["json"]
        assert kwargs["json"]["blocks"][0]["type"] == "header"

    def test_returns_false_on_4xx(self):
        with patch("requests.post") as mock_post:
            resp = MagicMock(status_code=403, text="forbidden")
            mock_post.return_value = resp
            ok = post_report("https://x", _result())
        assert ok is False

    def test_returns_false_on_network_error(self):
        import requests as _requests
        with patch("requests.post", side_effect=_requests.exceptions.ConnectionError("boom")):
            ok = post_report("https://x", _result())
        assert ok is False


class TestBuildBlocks:
    def test_blocks_include_stats_grid_and_top_patterns(self):
        blocks = _build_blocks(_result(total_credits=12.34), report_path="/tmp/r.md", diff=None)
        text = json.dumps(blocks)
        assert "Snowflake" in text
        assert "12.34" in text
        assert "fp_a" in text
        assert "/tmp/r.md" in text

    def test_blocks_include_diff_block_when_provided(self):
        diff = RunDiff(
            new_fingerprints=["x"],
            gone_fingerprints=["y"],
            total_credits_before=10.0,
            total_credits_after=12.0,
            cost_delta_pct=20.0,
        )
        blocks = _build_blocks(_result(), report_path=None, diff=diff)
        text = json.dumps(blocks)
        assert "Compared to last run" in text
        assert "10.00 -> 12.00" in text
