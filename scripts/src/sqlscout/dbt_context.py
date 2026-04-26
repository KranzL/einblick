from __future__ import annotations

import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlscout.atomic_io import atomic_write_bytes

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
from sqlscout.models import AnalysisResult

def _default_context_path() -> Path:
    base = Path(tempfile.gettempdir())
    try:
        uid = os.getuid()
        return base / f"sqlscout-dbt-context-{uid}.json"
    except AttributeError:
        return base / "sqlscout-dbt-context.json"


DEFAULT_CONTEXT_PATH = _default_context_path()
MAX_PERF_FETCHES = 50
PERF_FETCH_WORKERS = 8
PERF_FETCH_TOTAL_TIMEOUT_SECONDS = 60.0

log = logging.getLogger("sqlscout.dbt_context")


@dataclass
class PatternDbtContext:
    fingerprint: str
    matched_model_unique_ids: list[str] = field(default_factory=list)
    matched_models: list[dict] = field(default_factory=list)


@dataclass
class DbtContextHandoff:
    generated_at: str
    environment_id: str
    total_models_seen: int
    matched_pattern_count: int
    patterns: dict[str, PatternDbtContext] = field(default_factory=dict)
    perf: dict[str, dict] = field(default_factory=dict)


def run_dbt_context_prestep(
    result: AnalysisResult,
    output_path: Optional[Path] = None,
) -> Optional[DbtContextHandoff]:
    if not result.clusters:
        log.info("dbt context skipped: no clusters in result; leaving any cached handoff in place")
        return None

    target_path = output_path or DEFAULT_CONTEXT_PATH
    _purge_stale_handoff(target_path)

    try:
        host, token, env_id = resolve_discovery_config()
    except DbtConfigError as e:
        log.warning("dbt context skipped: %s", e)
        return None

    try:
        client = DbtDiscoveryClient(host=host, token=token, environment_id=env_id)
    except DbtConfigError as e:
        log.warning("dbt context skipped: %s", e)
        return None

    try:
        models = client.get_all_models()
    except DbtAuthError as e:
        log.warning(
            "dbt Discovery API returned auth error (%s). "
            "Continuing without dbt context -- recommendations will be less targeted.",
            e,
        )
        return None
    except DbtDiscoveryError as e:
        log.warning("dbt Discovery API error: %s. Continuing without dbt context.", e)
        return None

    source_index = build_source_index(models)

    pattern_tables = {
        c.fingerprint: list(c.tables_referenced)
        for c in result.clusters
    }
    matches = match_patterns_to_models(pattern_tables, source_index)
    all_uids = {uid for uids in matches.values() for uid in uids}

    if len(all_uids) > MAX_PERF_FETCHES:
        import heapq
        log.warning(
            "matched %d models; capping perf fetches to %d to keep runtime sane",
            len(all_uids),
            MAX_PERF_FETCHES,
        )
        matched_unique_ids = heapq.nsmallest(MAX_PERF_FETCHES, all_uids)
    else:
        matched_unique_ids = sorted(all_uids)

    models_by_id = {m.unique_id: m for m in models}

    perf: dict[str, dict] = {}
    if matched_unique_ids:
        workers = min(PERF_FETCH_WORKERS, len(matched_unique_ids))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {
                ex.submit(client.get_model_performance, uid): uid
                for uid in matched_unique_ids
            }
            try:
                for fut in as_completed(futures, timeout=PERF_FETCH_TOTAL_TIMEOUT_SECONDS):
                    uid = futures[fut]
                    try:
                        perf[uid] = asdict(fut.result())
                    except DbtDiscoveryError as e:
                        log.warning("perf fetch failed for %s: %s", uid, e)
                    except Exception as e:
                        log.warning(
                            "perf fetch crashed for %s: %s", uid, type(e).__name__
                        )
            except TimeoutError:
                log.warning(
                    "dbt perf fetches exceeded %ds; using partial results (%d/%d)",
                    PERF_FETCH_TOTAL_TIMEOUT_SECONDS, len(perf), len(matched_unique_ids),
                )

    patterns: dict[str, PatternDbtContext] = {}
    for fingerprint, uids in matches.items():
        patterns[fingerprint] = PatternDbtContext(
            fingerprint=fingerprint,
            matched_model_unique_ids=uids,
            matched_models=[
                _model_summary_dict(models_by_id[uid])
                for uid in uids
                if uid in models_by_id
            ],
        )

    handoff = DbtContextHandoff(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        environment_id=env_id,
        total_models_seen=len(models),
        matched_pattern_count=len(patterns),
        patterns=patterns,
        perf=perf,
    )

    path = output_path or DEFAULT_CONTEXT_PATH
    _write_handoff(handoff, path)
    return handoff


def load_handoff(path: Optional[Path] = None) -> Optional[DbtContextHandoff]:
    p = path or DEFAULT_CONTEXT_PATH
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError:
        return None

    patterns_raw = raw.get("patterns", {})
    patterns = {
        fp: PatternDbtContext(**data) for fp, data in patterns_raw.items()
    }

    return DbtContextHandoff(
        generated_at=raw.get("generated_at", ""),
        environment_id=raw.get("environment_id", ""),
        total_models_seen=raw.get("total_models_seen", 0),
        matched_pattern_count=raw.get("matched_pattern_count", 0),
        patterns=patterns,
        perf=raw.get("perf", {}),
    )


def render_dbt_context_for_prompt(handoff: DbtContextHandoff) -> str:
    if not handoff.patterns:
        return (
            "dbt context: queried project inventory, no top patterns matched "
            "existing dbt models. All proposals should be new_model."
        )

    lines = [
        "## dbt Project Context (from Discovery API)",
        "",
        f"Total models in project: {handoff.total_models_seen}",
        f"Top patterns matched to existing models: {handoff.matched_pattern_count}",
        "",
        "For each matched pattern, the existing dbt model is listed below. Prefer "
        "`modify_existing` over `new_model` when a match exists, and prefer "
        "`access_pattern` when a mart model already serves the same data users "
        "are hitting directly.",
        "",
    ]

    for fingerprint, pctx in handoff.patterns.items():
        safe_fp = _sanitize_for_prompt(fingerprint)
        lines.append(f"### Pattern {safe_fp}")
        for model in pctx.matched_models:
            uid = _sanitize_for_prompt(model["unique_id"])
            name = _sanitize_for_prompt(model.get("name") or "")
            materialized = _sanitize_for_prompt(model.get("materialized") or "?")
            perf = handoff.perf.get(model["unique_id"], {})
            avg = perf.get("avg_execution_ms")
            runs = perf.get("total_runs", 0)
            status = _sanitize_for_prompt(perf.get("last_run_status") or "-")
            perf_str = (
                f"avg {avg:.0f}ms over {runs} runs, last run: {status}"
                if avg is not None
                else "no recent runs"
            )
            lines.append(
                f"- `{name}` ({materialized}) "
                f"-- `{uid}` -- {perf_str}"
            )
        lines.append("")

    return "\n".join(lines)


def _sanitize_for_prompt(value: str) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = value.replace("\r", " ").replace("\n", " ").replace("`", "'")
    return cleaned[:200]


def _model_summary_dict(m: DbtModelSummary) -> dict:
    return {
        "unique_id": m.unique_id,
        "name": m.name,
        "database": m.database,
        "schema": m.schema,
        "alias": m.alias,
        "materialized": m.materialized,
        "source_tables": m.source_tables,
        "query_usage_count": m.query_usage_count,
        "file_path": m.file_path,
    }


def _purge_stale_handoff(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        log.warning("could not remove stale dbt context handoff at %s: %s", path, e)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass


def _write_handoff(handoff: DbtContextHandoff, path: Path) -> None:
    payload = {
        "generated_at": handoff.generated_at,
        "environment_id": handoff.environment_id,
        "total_models_seen": handoff.total_models_seen,
        "matched_pattern_count": handoff.matched_pattern_count,
        "patterns": {
            fp: asdict(p) for fp, p in handoff.patterns.items()
        },
        "perf": handoff.perf,
    }
    body = json.dumps(payload, indent=2, default=str).encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, body)
    except OSError as e:
        log.warning("failed to write dbt context handoff to %s: %s", path, e)
