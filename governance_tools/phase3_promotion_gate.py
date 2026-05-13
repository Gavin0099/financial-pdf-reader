#!/usr/bin/env python3
"""
Phase 2 -> Phase 3 promotion gate (integration proof).

Decision authority boundary:
- ONLY reads aggregation_result.current_state and aggregation_result.promote_eligible
- NEVER reads raw sample-level fields (e.g. misuse_evidence_status, confidence_level)
- NEVER reads reviewer free text as decision input
"""

from __future__ import annotations

from typing import Any

from governance_tools.phase2_aggregation_consumer import CANONICAL_CURRENT_STATES


def evaluate_phase3_promotion_entry(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Evaluate Phase 3 entry eligibility from canonical aggregation output.

    Required input shape:
      {
        "aggregation_result": {
          "current_state": <canonical enum>,
          "promote_eligible": <bool>
        },
        ...
      }
    """
    aggregation_result = payload.get("aggregation_result")
    if not isinstance(aggregation_result, dict):
        raise ValueError("missing aggregation_result object")

    current_state = aggregation_result.get("current_state")
    promote_eligible = aggregation_result.get("promote_eligible")

    if current_state not in CANONICAL_CURRENT_STATES:
        raise ValueError(f"invalid canonical current_state: {current_state!r}")
    if not isinstance(promote_eligible, bool):
        raise ValueError("aggregation_result.promote_eligible must be bool")

    allowed = current_state == "closure_verified" and promote_eligible is True

    # Surface gate_block_reasons and authority_ok when payload came from
    # build_phase2_gate().  Audit fields only — allow/deny is still solely
    # based on aggregation_result.promote_eligible (which already encodes
    # authority when the payload was built via build_phase2_gate).
    gate_block_reasons = list(payload.get("gate_block_reasons") or [])
    authority_summary = payload.get("authority_summary")
    if authority_summary is None:
        authority_summary = payload.get("authority_assessment_summary")

    decision_basis: dict[str, Any] = {
        "current_state": current_state,
        "promote_eligible": promote_eligible,
    }
    if gate_block_reasons:
        decision_basis["gate_block_reasons"] = gate_block_reasons
    if authority_summary is not None:
        decision_basis["authority_ok"] = bool(authority_summary.get("ok"))
        # trust_root_evidence_level: advisory signal only.
        # Visible to reviewer; does NOT affect phase3_entry_allowed.
        trust_level = authority_summary.get("trust_root_evidence_level")
        if trust_level is not None:
            decision_basis["trust_root_evidence_level"] = trust_level

    return {
        "phase3_entry_allowed": allowed,
        "phase3_runtime_enforcement": "not_enabled",
        "warnings": ["phase3_not_enabled"],
        "decision_basis": decision_basis,
        "policy_source": "phase3_promotion_gate.v1",
        "notes": (
            "Denied: requires current_state=closure_verified AND promote_eligible=true"
            if not allowed else
            "Allowed by canonical aggregation decision core."
        ),
    }

