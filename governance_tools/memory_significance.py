#!/usr/bin/env python3
"""
Memory significance v0.2 helpers.

Scope (v0.2 rollout):
- closeout -> candidate generation -> significance classifier -> advisory report
- advisory only; never blocks runtime gate decisions
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


L3_EVENT_TYPES = {
    "architecture_contract_change",
    "enforcement_semantic_change",
    "external_behavior_change",
    "reviewer_override",
    "incident_root_cause",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_significance(task_intent: str, checks: dict[str, Any]) -> tuple[str, str, str]:
    """
    Return (significance_level, event_type, why_significant).

    Heuristic classifier for v0.2. Conservative by default.
    """
    text = (task_intent or "").lower()

    if "reviewer override" in text or "override" in text:
        return ("L3", "reviewer_override", "task intent indicates reviewer override flow")
    if "incident" in text or "postmortem" in text or "root cause" in text:
        return ("L3", "incident_root_cause", "task intent indicates incident/root-cause workflow")
    if "contract" in text or "governance rule" in text or "enforcement" in text:
        return ("L3", "enforcement_semantic_change", "task intent indicates enforcement/contract semantics update")
    if "architecture" in text:
        return ("L3", "architecture_contract_change", "task intent indicates architecture contract update")
    if "external" in text or "release" in text or "client-facing" in text:
        return ("L3", "external_behavior_change", "task intent indicates external behavior semantics")

    # Non-L3 default path.
    if checks.get("closeout_status") == "valid":
        return ("L2", "other", "valid closeout with no L3 semantic trigger detected")
    return ("L1", "other", "no high-significance trigger detected")


def build_candidate(
    *,
    repo_root: Path,
    session_id: str,
    commit_hash: str,
    task_intent: str,
    checks: dict[str, Any],
) -> dict[str, Any]:
    level, event_type, why = classify_significance(task_intent, checks)
    suggested_target = (
        "memory/03_decisions.md" if level == "L3"
        else "memory/01_active_task.md" if level == "L2"
        else ""
    )
    evidence_links = [
        f"artifacts/runtime/verdicts/{session_id}.json",
        f"artifacts/runtime/traces/{session_id}.json",
    ]

    candidate = {
        "schema_version": "0.2",
        "candidate_id": f"msc-{session_id}",
        "repo": str(repo_root),
        "session_id": session_id,
        "run_id": "",
        "commit_hash": commit_hash,
        "generated_at_utc": _utc_now(),
        "significance_level": level,
        "event_type": event_type,
        "why_significant": why,
        "evidence_links": evidence_links,
        "suggested_memory_target": suggested_target,
        "promotion_state": "candidate",
        "authority_flags": {
            "canonical_review_required": False,
            "canonical_conflict_detected": False,
        },
        "validation": {
            "l3_enum_valid": (event_type in L3_EVENT_TYPES) if level == "L3" else True,
            "evidence_linkage_complete": True,
        },
        "notes": "",
    }
    return candidate


def build_advisory(candidate: dict[str, Any]) -> dict[str, Any]:
    advisories: list[dict[str, Any]] = []
    level = candidate.get("significance_level")
    event_type = candidate.get("event_type", "")
    target = candidate.get("suggested_memory_target", "")
    validation = candidate.get("validation") or {}

    if level == "L3" and event_type not in L3_EVENT_TYPES:
        advisories.append(
            {
                "code": "invalid_l3_event_type",
                "severity": "warning",
                "message": "L3 event_type must use closed enum; custom strings are forbidden.",
            }
        )

    if level == "L3" and not target:
        advisories.append(
            {
                "code": "missing_l3_memory_linkage",
                "severity": "warning",
                "message": "L3 candidate has no suggested memory target.",
            }
        )

    return {
        "schema_version": "0.2",
        "candidate_id": candidate.get("candidate_id"),
        "session_id": candidate.get("session_id"),
        "generated_at_utc": _utc_now(),
        "advisories": advisories,
        "advisory_only": True,
        "validation": validation,
    }


def write_candidate_and_advisory(
    *,
    repo_root: Path,
    session_id: str,
    commit_hash: str,
    task_intent: str,
    checks: dict[str, Any],
) -> dict[str, str]:
    candidate = build_candidate(
        repo_root=repo_root,
        session_id=session_id,
        commit_hash=commit_hash,
        task_intent=task_intent,
        checks=checks,
    )
    advisory = build_advisory(candidate)

    candidate_dir = repo_root / "artifacts" / "runtime" / "memory-candidates"
    advisory_dir = repo_root / "artifacts" / "runtime" / "advisory"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    advisory_dir.mkdir(parents=True, exist_ok=True)

    candidate_path = candidate_dir / f"{session_id}.json"
    advisory_path = advisory_dir / f"memory-significance-{session_id}.json"
    candidate_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    advisory_path.write_text(json.dumps(advisory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "candidate_path": str(candidate_path),
        "advisory_path": str(advisory_path),
    }

