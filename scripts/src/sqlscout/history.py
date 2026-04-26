from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlscout.atomic_io import atomic_write_bytes

DEFAULT_HISTORY_DIR = Path.home() / ".sqlscout" / "history"
DEFAULT_KEEP = 12


def resolve_history_dir(platform: str, override: Optional[str] = None) -> Path:
    if override:
        base = Path(override).expanduser()
    else:
        env_override = os.environ.get("SQLSCOUT_HISTORY_DIR")
        base = Path(env_override).expanduser() if env_override else DEFAULT_HISTORY_DIR
    return base / platform


def store_run(
    platform: str,
    json_content: str,
    md_content: Optional[str] = None,
    override_dir: Optional[str] = None,
    keep: int = DEFAULT_KEEP,
    timestamp: Optional[datetime] = None,
) -> Path:
    hdir = resolve_history_dir(platform, override_dir)
    hdir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(hdir, 0o700)
    except OSError:
        pass
    ts = (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
    json_path = hdir / f"{ts}.json"
    _atomic_write(json_path, json_content.encode("utf-8"))
    if md_content:
        md_path = hdir / f"{ts}.md"
        _atomic_write(md_path, md_content.encode("utf-8"))
    _prune(hdir, keep)
    return json_path


def _atomic_write(path: Path, body: bytes) -> None:
    atomic_write_bytes(path, body)


def list_runs(platform: str, override_dir: Optional[str] = None) -> list[Path]:
    hdir = resolve_history_dir(platform, override_dir)
    if not hdir.exists():
        return []
    return sorted(hdir.glob("*.json"), reverse=True)


def latest_run(platform: str, override_dir: Optional[str] = None) -> Optional[Path]:
    runs = list_runs(platform, override_dir)
    return runs[0] if runs else None


def previous_run(
    platform: str,
    override_dir: Optional[str] = None,
    before: Optional[Path] = None,
) -> Optional[Path]:
    runs = list_runs(platform, override_dir)
    if before is not None:
        runs = [r for r in runs if r.name < before.name]
    return runs[0] if runs else None


def _prune(hdir: Path, keep: int) -> None:
    if keep <= 0:
        return
    import heapq
    keep_set = set(heapq.nlargest(keep, hdir.glob("*.json"), key=lambda p: p.name))
    for path in hdir.glob("*.json"):
        if path in keep_set:
            continue
        path.unlink(missing_ok=True)
        md = path.with_suffix(".md")
        if md.exists():
            md.unlink()
