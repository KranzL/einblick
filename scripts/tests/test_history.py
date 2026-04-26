from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from sqlscout.history import (
    DEFAULT_HISTORY_DIR,
    _atomic_write,
    latest_run,
    list_runs,
    previous_run,
    resolve_history_dir,
    store_run,
)


class TestResolveHistoryDir:
    def test_default_path_is_under_home(self):
        path = resolve_history_dir("snowflake")
        assert str(DEFAULT_HISTORY_DIR) in str(path)
        assert path.name == "snowflake"

    def test_explicit_override_wins(self, tmp_path):
        path = resolve_history_dir("databricks", override=str(tmp_path))
        assert path == tmp_path / "databricks"

    def test_env_var_respected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SQLSCOUT_HISTORY_DIR", str(tmp_path))
        path = resolve_history_dir("snowflake")
        assert path == tmp_path / "snowflake"

    def test_explicit_override_beats_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SQLSCOUT_HISTORY_DIR", "/should/not/win")
        path = resolve_history_dir("snowflake", override=str(tmp_path))
        assert path == tmp_path / "snowflake"


class TestStoreAndList:
    def test_store_writes_json_and_md(self, tmp_path):
        p = store_run(
            "snowflake",
            json_content='{"ok": 1}',
            md_content="# report",
            override_dir=str(tmp_path),
        )
        assert p.exists()
        assert p.read_text() == '{"ok": 1}'
        md = p.with_suffix(".md")
        assert md.exists()
        assert md.read_text() == "# report"

    def test_store_without_md(self, tmp_path):
        p = store_run(
            "snowflake",
            json_content='{"ok": 1}',
            override_dir=str(tmp_path),
        )
        assert p.exists()
        assert not p.with_suffix(".md").exists()

    def test_list_newest_first(self, tmp_path):
        for ts in ["20260101_000000", "20260102_000000", "20260103_000000"]:
            store_run(
                "snowflake",
                json_content="{}",
                override_dir=str(tmp_path),
                timestamp=datetime.strptime(ts, "%Y%m%d_%H%M%S"),
            )
        runs = list_runs("snowflake", override_dir=str(tmp_path))
        assert [r.stem for r in runs] == ["20260103_000000", "20260102_000000", "20260101_000000"]

    def test_latest_and_previous(self, tmp_path):
        for ts in ["20260101_000000", "20260102_000000"]:
            store_run(
                "snowflake",
                json_content="{}",
                override_dir=str(tmp_path),
                timestamp=datetime.strptime(ts, "%Y%m%d_%H%M%S"),
            )
        newest = latest_run("snowflake", override_dir=str(tmp_path))
        assert newest.stem == "20260102_000000"
        prev = previous_run("snowflake", override_dir=str(tmp_path), before=newest)
        assert prev.stem == "20260101_000000"

    def test_retention_prunes_oldest(self, tmp_path):
        base = datetime(2026, 1, 1)
        for i in range(5):
            store_run(
                "snowflake",
                json_content="{}",
                md_content="m",
                override_dir=str(tmp_path),
                keep=3,
                timestamp=base + timedelta(days=i),
            )
        runs = list_runs("snowflake", override_dir=str(tmp_path))
        assert len(runs) == 3
        assert runs[0].stem == "20260105_000000"
        assert runs[-1].stem == "20260103_000000"
        for r in runs:
            assert r.with_suffix(".md").exists()

    def test_keep_zero_disables_pruning(self, tmp_path):
        base = datetime(2026, 1, 1)
        for i in range(5):
            store_run(
                "snowflake",
                json_content="{}",
                override_dir=str(tmp_path),
                keep=0,
                timestamp=base + timedelta(days=i),
            )
        assert len(list_runs("snowflake", override_dir=str(tmp_path))) == 5

    def test_empty_dir_returns_empty_list(self, tmp_path):
        assert list_runs("snowflake", override_dir=str(tmp_path)) == []
        assert latest_run("snowflake", override_dir=str(tmp_path)) is None


class TestAtomicWrite:
    def test_writes_full_content(self, tmp_path):
        path = tmp_path / "x.json"
        _atomic_write(path, b'{"a": 1, "b": 2}')
        assert path.read_bytes() == b'{"a": 1, "b": 2}'

    def test_mode_is_0o600(self, tmp_path):
        import os
        path = tmp_path / "x.json"
        _atomic_write(path, b"data")
        st = os.stat(path)
        assert (st.st_mode & 0o777) == 0o600

    def test_failure_during_write_cleans_up_tmp(self, tmp_path, monkeypatch):
        import os
        path = tmp_path / "x.json"
        original_write = os.write

        def _fail_after_first_call(fd, data):
            raise OSError("simulated disk full")

        monkeypatch.setattr(os, "write", _fail_after_first_call)
        with pytest.raises(OSError, match="disk full"):
            _atomic_write(path, b"some payload")

        assert not path.exists()
        tmp = path.with_suffix(path.suffix + ".tmp")
        assert not tmp.exists()

    def test_handles_partial_writes(self, tmp_path, monkeypatch):
        import os
        path = tmp_path / "x.json"
        body = b"abcdefghijklmnopqrstuvwxyz" * 4
        original_write = os.write
        call_count = {"n": 0}

        def _short_write(fd, data):
            call_count["n"] += 1
            chunk = bytes(data[:5])
            return original_write(fd, chunk)

        monkeypatch.setattr(os, "write", _short_write)
        _atomic_write(path, body)

        assert path.read_bytes() == body
        assert call_count["n"] >= len(body) // 5

    def test_replace_is_atomic_no_partial_visible(self, tmp_path):
        path = tmp_path / "x.json"
        _atomic_write(path, b"first")
        _atomic_write(path, b"second")
        assert path.read_bytes() == b"second"
        tmp = path.with_suffix(path.suffix + ".tmp")
        assert not tmp.exists()
