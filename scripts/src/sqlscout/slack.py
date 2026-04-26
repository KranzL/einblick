from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from sqlscout.history import list_runs, resolve_history_dir
from sqlscout.models import AnalysisResult

DEFAULT_TIMEOUT_SECONDS = 10.0
ALERT_COST_DELTA_PCT = 20.0
ALERT_NEW_PATTERN_COUNT = 3

log = logging.getLogger("sqlscout.slack")


@dataclass
class RunDiff:
    new_fingerprints: list[str] = field(default_factory=list)
    gone_fingerprints: list[str] = field(default_factory=list)
    total_credits_before: float = 0.0
    total_credits_after: float = 0.0
    cost_delta_pct: float = 0.0
    prior_run_path: Optional[str] = None

    @property
    def is_interesting(self) -> bool:
        if len(self.new_fingerprints) >= ALERT_NEW_PATTERN_COUNT:
            return True
        if len(self.gone_fingerprints) >= 1:
            return True
        if abs(self.cost_delta_pct) >= ALERT_COST_DELTA_PCT:
            return True
        return False


def compute_diff_against_previous(
    current: AnalysisResult,
    history_dir_override: Optional[str] = None,
) -> Optional[RunDiff]:
    runs = list_runs(current.metadata.platform, override_dir=history_dir_override)
    runs = [r for r in runs if r.suffix == ".json"]
    if len(runs) < 2:
        return None

    prior_path = runs[1]
    try:
        prior_data = json.loads(prior_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.warning("could not read prior run for Slack diff: %s", e)
        return None

    prior_clusters = prior_data.get("clusters") or []
    prior_meta = prior_data.get("metadata") or {}

    current_fps = {c.fingerprint for c in current.clusters}
    prior_fps = {c.get("fingerprint") for c in prior_clusters if c.get("fingerprint")}

    before = float(prior_meta.get("total_credits") or 0.0)
    after = float(current.metadata.total_credits or 0.0)
    delta_pct = ((after - before) / before * 100.0) if before > 0 else 0.0

    return RunDiff(
        new_fingerprints=list(current_fps - prior_fps),
        gone_fingerprints=list(prior_fps - current_fps),
        total_credits_before=before,
        total_credits_after=after,
        cost_delta_pct=delta_pct,
        prior_run_path=str(prior_path),
    )


def should_post(mode: str, diff: Optional[RunDiff]) -> bool:
    if mode == "off":
        return False
    if mode == "digest":
        return True
    if mode == "alert":
        return diff is not None and diff.is_interesting
    return False


_EXPECTED_SLACK_PREFIX = "https://hooks.slack.com/services/"


def post_report(
    webhook_url: str,
    result: AnalysisResult,
    report_path: Optional[str] = None,
    diff: Optional[RunDiff] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    if not webhook_url.startswith(_EXPECTED_SLACK_PREFIX):
        log.warning(
            "Slack webhook URL does not look like a Slack incoming webhook "
            "(expected prefix %s). Posting anyway, but if delivery fails check the URL.",
            _EXPECTED_SLACK_PREFIX,
        )

    blocks = _build_blocks(result, report_path, diff)
    host = urlparse(webhook_url).hostname or "unknown"
    try:
        resp = requests.post(webhook_url, json={"blocks": blocks}, timeout=timeout)
    except requests.RequestException as e:
        log.warning("Slack POST failed (host=%s): %s", host, type(e).__name__)
        return False
    if resp.status_code >= 400:
        log.warning("Slack returned %d (host=%s)", resp.status_code, host)
        return False
    return True


def _build_blocks(
    result: AnalysisResult,
    report_path: Optional[str],
    diff: Optional[RunDiff],
) -> list[dict]:
    from sqlscout.aggregator import _format_time_window
    md = result.metadata

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "SqlScout report"}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Platform:*\n{md.platform.title()}"},
                {"type": "mrkdwn", "text": f"*Window:*\n{_format_time_window(md)}"},
                {"type": "mrkdwn", "text": f"*Patterns:*\n{md.distinct_fingerprints:,}"},
                {"type": "mrkdwn", "text": f"*Est. cost:*\n{md.total_credits:.2f}"},
            ],
        },
    ]

    if diff is not None:
        blocks.append({"type": "divider"})
        blocks.append(_diff_block(diff))

    if result.clusters:
        blocks.append({"type": "divider"})
        blocks.append(_top_patterns_block(result.clusters[:3]))

    if report_path:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Full report: `{report_path}`"}],
        })

    return blocks


def _diff_block(diff: RunDiff) -> dict:
    arrow = "up" if diff.cost_delta_pct > 0 else "down" if diff.cost_delta_pct < 0 else "flat"
    cost_line = (
        f"*Cost:* {diff.total_credits_before:.2f} -> {diff.total_credits_after:.2f} "
        f"({arrow} {abs(diff.cost_delta_pct):.1f}%)"
    )
    new_line = f"*New patterns:* {len(diff.new_fingerprints)}"
    gone_line = f"*Disappeared:* {len(diff.gone_fingerprints)}"
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "*Compared to last run:*\n" + "\n".join([cost_line, new_line, gone_line]),
        },
    }


def _top_patterns_block(clusters) -> dict:
    lines = []
    for c in clusters:
        lines.append(
            f"`{c.fingerprint[:8]}` - {c.execution_count:,} runs, "
            f"{c.total_credits:.2f} cost, {c.avg_execution_time_ms:.0f}ms avg"
        )
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "*Top patterns:*\n" + "\n".join(lines)},
    }
