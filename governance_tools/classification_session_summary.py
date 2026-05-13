#!/usr/bin/env python3
"""
Read session summary artifacts and report governance classification distribution.

Collects ``decision_context`` fields from all ``artifacts/runtime/summaries/*.json``
files and produces reason-frequency and class-distribution statistics.

Use this tool to verify that ``conservative_downgrade`` is not anomalously
high-frequency and that ``classification_anomaly_upgrade`` never appears in
normal operation.

See docs/classification-transition-semantics.md for the controlled reason taxonomy.
See docs/classification-reaction-policy.md for how classification changes affect
downstream surfaces.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.human_summary import build_summary_line

# Controlled reclassification_reason taxonomy (mirrors classification-transition-semantics.md)
_KNOWN_REASONS = frozenset(
    {
        "context_degraded",
        "instruction_load_failed",
        "tool_gate_missing",
        "conservative_downgrade",
        "classification_anomaly_upgrade",
    }
)

_KNOWN_CLASSES = frozenset({"instruction_capable", "instruction_limited", "wrapper_only"})

# Threshold above which conservative_downgrade_rate triggers a classifier review flag.
# Not a hard invariant — this is a drift indicator. If the rate climbs above this threshold
# it suggests classification logic has an unhandled edge case, not that the system is broken.
# See docs/classification-reaction-policy.md for policy_flags semantics.
_CONSERVATIVE_DOWNGRADE_REVIEW_THRESHOLD = 0.10  # 10% of sessions


def build_classification_session_summary(project_root: Path) -> dict[str, Any]:
    """
    Scan ``artifacts/runtime/summaries/`` under *project_root* and return
    aggregate classification statistics across all recorded sessions.

    Returns a dict with:
    - session_count: total summaries read
    - classification_changed_count: sessions where class changed
    - downgrade_count: legitimate downgrades (excludes anomaly_upgrade)
    - anomaly_count: sessions with classification_anomaly_upgrade
    - reason_distribution: {reason_value: count, ...}
    - effective_class_distribution: {class_value: count, ...}
    - conservative_downgrade_rate: float | None (None if no sessions)
    - unknown_reasons: [reason_value, ...] values not in controlled taxonomy
    - policy_flags: {
        "anomaly_alert": bool,        — any anomaly_count > 0 (hard invariant: should be 0)
        "classifier_review": bool,    — conservative_downgrade_rate > threshold (drift signal)
        "taxonomy_breach": bool,      — any unknown_reasons present (schema drift)
      }
    - policy_ok: bool — True iff no policy_flags are raised
    """
    summaries_dir = project_root / "artifacts" / "runtime" / "summaries"

    sessions: list[dict[str, Any]] = []
    unreadable: list[str] = []

    if summaries_dir.exists():
        for path in sorted(summaries_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                dc = payload.get("decision_context") or {}
                sessions.append(
                    {
                        "session_id": payload.get("session_id"),
                        "closed_at": payload.get("closed_at"),
                        "effective_agent_class": dc.get("effective_agent_class"),
                        "initial_agent_class": dc.get("initial_agent_class"),
                        "classification_changed": dc.get("classification_changed"),
                        "reclassification_reason": dc.get("reclassification_reason"),
                    }
                )
            except Exception:
                unreadable.append(str(path))

    total = len(sessions)

    # Reason distribution
    reason_counts: dict[str, int] = {}
    for s in sessions:
        reason = s.get("reclassification_reason")
        if reason is not None:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    # Effective class distribution
    class_counts: dict[str, int] = {}
    for s in sessions:
        cls = s.get("effective_agent_class") or "unknown"
        class_counts[cls] = class_counts.get(cls, 0) + 1

    changed_count = sum(1 for s in sessions if s.get("classification_changed") is True)
    downgrade_count = sum(
        1
        for s in sessions
        if s.get("classification_changed") is True
        and s.get("reclassification_reason") not in (None, "classification_anomaly_upgrade")
    )
    anomaly_count = reason_counts.get("classification_anomaly_upgrade", 0)

    conservative_downgrade_rate = (
        round(reason_counts.get("conservative_downgrade", 0) / total, 3) if total > 0 else None
    )

    unknown_reasons = sorted(r for r in reason_counts if r not in _KNOWN_REASONS)

    # Policy flags: minimum judgment rules for governance health.
    # anomaly_alert is a hard invariant — any nonzero count needs investigation.
    # classifier_review is a drift signal — high rate implies classification logic gaps.
    # taxonomy_breach is a schema contract signal — unknown reasons indicate spec drift.
    policy_flags = {
        "anomaly_alert": anomaly_count > 0,
        "classifier_review": (
            conservative_downgrade_rate is not None
            and conservative_downgrade_rate > _CONSERVATIVE_DOWNGRADE_REVIEW_THRESHOLD
        ),
        "taxonomy_breach": len(unknown_reasons) > 0,
    }
    policy_ok = not any(policy_flags.values())

    return {
        "ok": True,
        "policy_ok": policy_ok,
        "project_root": str(project_root),
        "summaries_dir": str(summaries_dir),
        "session_count": total,
        "classification_changed_count": changed_count,
        "downgrade_count": downgrade_count,
        "anomaly_count": anomaly_count,
        "reason_distribution": reason_counts,
        "effective_class_distribution": class_counts,
        "conservative_downgrade_rate": conservative_downgrade_rate,
        "unknown_reasons": unknown_reasons,
        "policy_flags": policy_flags,
        "unreadable_files": unreadable,
    }


def format_human_result(result: dict[str, Any]) -> str:
    reason_dist = result.get("reason_distribution") or {}
    class_dist = result.get("effective_class_distribution") or {}
    total = result["session_count"]
    conservative_rate = result.get("conservative_downgrade_rate")
    policy_flags = result.get("policy_flags") or {}
    policy_ok = result.get("policy_ok", True)

    summary_line = build_summary_line(
        f"ok={result['ok']}",
        f"policy_ok={policy_ok}",
        f"sessions={total}",
        f"downgrades={result['downgrade_count']}",
        f"anomalies={result['anomaly_count']}",
        f"conservative_rate={conservative_rate}" if conservative_rate is not None else None,
    )

    lines = [
        "[classification_session_summary]",
        summary_line,
        f"project_root={result['project_root']}",
        f"summaries_dir={result['summaries_dir']}",
        f"session_count={total}",
        f"classification_changed_count={result['classification_changed_count']}",
        f"downgrade_count={result['downgrade_count']}",
        f"anomaly_count={result['anomaly_count']}",
        f"conservative_downgrade_rate={conservative_rate}",
    ]

    # Policy flags: show even when all False so reviewers can confirm health state
    lines.append("[policy_flags]")
    lines.append(f"  anomaly_alert={policy_flags.get('anomaly_alert', False)}"
                 "  # hard invariant: any anomaly_count > 0 needs investigation")
    lines.append(f"  classifier_review={policy_flags.get('classifier_review', False)}"
                 f"  # drift signal: conservative_downgrade_rate > {_CONSERVATIVE_DOWNGRADE_REVIEW_THRESHOLD}")
    lines.append(f"  taxonomy_breach={policy_flags.get('taxonomy_breach', False)}"
                 "  # schema drift: unknown reason values detected")

    if reason_dist:
        lines.append("[reason_distribution]")
        for reason, count in sorted(reason_dist.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {reason}={count}")
    else:
        lines.append("[reason_distribution] (none)")

    if class_dist:
        lines.append("[effective_class_distribution]")
        for cls, count in sorted(class_dist.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {cls}={count}")
    else:
        lines.append("[effective_class_distribution] (none)")

    if result.get("unknown_reasons"):
        lines.append(f"unknown_reasons={','.join(result['unknown_reasons'])}")

    if result.get("unreadable_files"):
        for path in result["unreadable_files"]:
            lines.append(f"unreadable={path}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report governance classification distribution across session artifacts."
    )
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    result = build_classification_session_summary(Path(args.project_root).resolve())

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human_result(result))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
