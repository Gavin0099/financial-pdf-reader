#!/usr/bin/env python3
"""
Phase 2 aggregation consumer (minimal deterministic implementation).

Purpose:
- Normalize legacy alias: none_observed -> not_observed_in_window
- Apply canonical aggregation precedence deterministically
- Emit a single canonical current_state
- Provide a strict promote guardrail
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from governance_tools.authority_rollout_policy import resolve_authority_rollout_policy
from governance_tools.escalation_authority_writer import assess_authority_directory

MISUSE_EVIDENCE_STATUSES = frozenset({
    "observed",
    "not_observed_in_window",
    "not_tested",
})

LEGACY_STATUS_ALIASES = {
    "none_observed": "not_observed_in_window",
}

CANONICAL_CURRENT_STATES = frozenset({
    "insufficient_observation",
    "risk_observed",
    "risk_persists",
    "risk_not_reobserved_yet",
    "insufficient_closure_evidence",
    "closure_verified",
})

APPROVED_CLOSURE_REVIEWER_ROLES = frozenset({
    "human_reviewer",
    "risk_owner",
})


@dataclass(frozen=True)
class WindowSpec:
    runs: int
    sessions: int
    min_runs: int = 3
    min_sessions: int = 2

    @property
    def adequate(self) -> bool:
        return self.runs >= self.min_runs and self.sessions >= self.min_sessions


def normalize_misuse_evidence_status(raw_status: str) -> str:
    """Normalize legacy alias to canonical status and validate value."""
    status = LEGACY_STATUS_ALIASES.get(raw_status, raw_status)
    if status not in MISUSE_EVIDENCE_STATUSES:
        raise ValueError(f"invalid misuse_evidence_status: {raw_status!r}")
    return status


def _validate_closure_approval(
    closure_approval: dict[str, Any] | None,
    *,
    historical_observed: bool,
    closure_review_approved: bool,
) -> dict[str, Any]:
    """
    Validate closure approval trust boundary.

    Rules:
    - approval is only meaningful on closure path (historical_observed=True)
    - approved=True requires reviewer metadata + evidence refs
    - legacy bool-only approval is rejected when True (must provide metadata)
    """
    if closure_approval is None:
        if closure_review_approved:
            raise ValueError(
                "closure_review_approved=True requires closure_approval metadata "
                "(reviewer_id/reviewer_role/review_note/evidence_refs)"
            )
        return {"approved": False}

    if not isinstance(closure_approval, dict):
        raise ValueError("closure_approval must be a dict when provided")

    approved = closure_approval.get("approved")
    if not isinstance(approved, bool):
        raise ValueError("closure_approval.approved must be bool")

    if approved and not historical_observed:
        raise ValueError(
            "closure approval is only valid on closure path (historical_observed=True)"
        )

    if not approved:
        return {"approved": False}

    reviewer_id = closure_approval.get("reviewer_id")
    reviewer_role = closure_approval.get("reviewer_role")
    review_note = closure_approval.get("review_note")
    evidence_refs = closure_approval.get("evidence_refs")

    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        raise ValueError("closure_approval.reviewer_id is required when approved=true")
    if reviewer_role not in APPROVED_CLOSURE_REVIEWER_ROLES:
        raise ValueError(
            "closure_approval.reviewer_role must be one of "
            f"{sorted(APPROVED_CLOSURE_REVIEWER_ROLES)} when approved=true"
        )
    if not isinstance(review_note, str) or not review_note.strip():
        raise ValueError("closure_approval.review_note is required when approved=true")
    if not isinstance(evidence_refs, list) or not evidence_refs or not all(
        isinstance(x, str) and x.strip() for x in evidence_refs
    ):
        raise ValueError(
            "closure_approval.evidence_refs must be a non-empty list[str] when approved=true"
        )

    return {
        "approved": True,
        "reviewer_id": reviewer_id.strip(),
        "reviewer_role": reviewer_role,
        "review_note": review_note.strip(),
        "evidence_refs": [x.strip() for x in evidence_refs],
    }


def aggregate_phase2_state(
    *,
    sample_statuses: list[str],
    window: WindowSpec,
    historical_observed: bool,
    remediation_introduced: bool = False,
    covers_original_misuse_path: bool = False,
    closure_review_approved: bool = False,
    closure_approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Deterministic aggregation based on canonical precedence.

    Returns:
      {
        "current_state": <canonical enum>,
        "historical_observed": bool,
        "closure_condition_met": bool,
        "normalized_statuses": [...],
        "promote_eligible": bool,
      }
    """
    if not sample_statuses:
        sample_statuses = ["not_tested"]

    normalized_closure_approval = _validate_closure_approval(
        closure_approval,
        historical_observed=historical_observed,
        closure_review_approved=closure_review_approved,
    )
    closure_approved = normalized_closure_approval["approved"]

    normalized = [normalize_misuse_evidence_status(s) for s in sample_statuses]

    has_observed_in_window = any(s == "observed" for s in normalized)
    has_tested_evidence = any(s != "not_tested" for s in normalized)
    all_not_tested = all(s == "not_tested" for s in normalized)

    closure_condition_met = (
        historical_observed
        and remediation_introduced
        and covers_original_misuse_path
        and window.adequate
        and (not has_observed_in_window)
        and has_tested_evidence
        and closure_approved
    )

    if has_observed_in_window:
        current_state = "risk_observed"
    elif all_not_tested:
        current_state = "insufficient_observation"
    elif historical_observed:
        if not remediation_introduced:
            current_state = "risk_persists"
        elif closure_condition_met:
            current_state = "closure_verified"
        elif (not window.adequate) or (not covers_original_misuse_path) or (not has_tested_evidence):
            current_state = "insufficient_closure_evidence"
        else:
            current_state = "risk_not_reobserved_yet"
    else:
        # Conservative default: no historical observed does not auto-promote.
        current_state = "insufficient_observation"

    if current_state not in CANONICAL_CURRENT_STATES:
        raise ValueError(f"internal error: non-canonical current_state {current_state!r}")

    return {
        "current_state": current_state,
        "historical_observed": historical_observed,
        "closure_condition_met": closure_condition_met,
        "closure_approval": normalized_closure_approval,
        "normalized_statuses": normalized,
        "promote_eligible": current_state == "closure_verified",
    }


def build_phase2_gate(
    aggregation_result: dict[str, Any],
    authority_assessment: dict[str, Any],
) -> dict[str, Any]:
    """
    Produce a canonical gate payload by joining Phase 2 aggregation result
    with escalation authority assessment.

    This is the ONLY place where misuse evidence eligibility and escalation
    authority are combined.  The promotion gate MUST consume this output and
    MUST NOT read authority_assessment directly.

    authority_assessment: output of assess_authority_directory() — keys used:
        ok, release_blocked, release_block_reasons, source.

    Fail-closed defaults: missing keys treated as authority_ok=False,
    release_blocked=True.  An empty or None dict denies promotion.
    """
    authority_ok = bool(authority_assessment.get("ok", False))
    authority_release_blocked = bool(authority_assessment.get("release_blocked", True))

    misuse_promote_eligible = bool(aggregation_result.get("promote_eligible", False))
    gate_promote_eligible = (
        misuse_promote_eligible and authority_ok and not authority_release_blocked
    )

    gate_block_reasons: list[str] = []
    if not misuse_promote_eligible:
        current_state = aggregation_result.get("current_state", "unknown")
        gate_block_reasons.append(f"aggregation_not_promote_eligible:{current_state}")
    if not authority_ok or authority_release_blocked:
        for reason in authority_assessment.get("release_block_reasons") or []:
            if reason not in gate_block_reasons:
                gate_block_reasons.append(reason)
        if not authority_ok and not any(
            r.startswith("aggregation_not_promote_eligible") or "authority" in r
            for r in gate_block_reasons
        ):
            gate_block_reasons.append("authority_assessment_not_ok")

    authority_summary = {
        "ok": authority_ok,
        "release_blocked": authority_release_blocked,
        "source": authority_assessment.get("source"),
        "decision_source": authority_assessment.get("decision_source"),
        "register_required_mode": bool(authority_assessment.get("register_required_mode", False)),
        "register_present": bool(authority_assessment.get("register_present", False)),
        "lifecycle_effective_by_escalation": dict(
            authority_assessment.get("lifecycle_effective_by_escalation") or {}
        ),
        "precedence_applied": "lifecycle_effective_by_escalation" in authority_assessment,
        "release_block_reasons": list(
            authority_assessment.get("release_block_reasons") or []
        ),
        # trust_root_evidence_level: advisory only, never affects gate_promote_eligible.
        # Enables promotion gate to surface evidence chain completeness without gating on it.
        "trust_root_evidence_level": authority_assessment.get("trust_root_evidence_level"),
    }

    return {
        "aggregation_result": {
            "current_state": aggregation_result.get("current_state"),
            "promote_eligible": gate_promote_eligible,
        },
        # v2 canonical shape for precedence-aware consumers.
        "authority_summary": authority_summary,
        # Backward compatibility for existing consumers/tests.
        "authority_assessment_summary": authority_summary,
        "gate_promote_eligible": gate_promote_eligible,
        "gate_block_reasons": gate_block_reasons,
        "gate_version": "phase2_gate.v1",
    }


def build_phase2_gate_with_policy(
    *,
    project_root: Path,
    aggregation_result: dict[str, Any],
    authority_require_register: bool | None = None,
    authority_policy_file: Path | None = None,
) -> dict[str, Any]:
    """
    Canonical runtime entry for phase2 gate with single rollout policy resolver.

    This avoids per-caller flag drift by forcing authority assessment to resolve
    strict-mode policy through one source before building the gate payload.
    """
    policy = resolve_authority_rollout_policy(
        project_root=project_root,
        require_register_override=authority_require_register,
        policy_file=authority_policy_file,
    )
    authority_assessment = assess_authority_directory(
        project_root,
        require_register=policy.require_register,
        require_log=policy.require_log,
    )
    return build_phase2_gate(aggregation_result, authority_assessment)
