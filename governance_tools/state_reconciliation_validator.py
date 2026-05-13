#!/usr/bin/env python3
"""State reconciliation validator for governance phase status vs runtime capability."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.phase_d_closeout_writer import assess_phase_d_closeout
from governance_tools.state_generator import parse_gate_status


def _extract_phase_d_from_state_yaml(state_text: str) -> str | None:
    m = re.search(r"^\s*PhaseD:\s*([A-Za-z_]+)\s*$", state_text, re.MULTILINE)
    return m.group(1) if m else None


def _release_surface_precedence_ready(release_surface_text: str) -> bool:
    required_markers = (
        "precedence_applied",
        "lifecycle_effective_by_escalation",
    )
    return all(marker in release_surface_text for marker in required_markers)

def _promotion_path_precedence_ready(
    phase2_text: str,
    phase3_text: str,
) -> bool:
    phase2_markers = (
        "authority_summary",
        "lifecycle_effective_by_escalation",
        "precedence_applied",
    )
    phase3_markers = (
        'payload.get("authority_summary")',
    )
    return all(m in phase2_text for m in phase2_markers) and all(
        m in phase3_text for m in phase3_markers
    )


def _readside_enforcement_threshold_sufficient(authority_writer_text: str) -> bool:
    markers = (
        "lifecycle_effective_by_escalation",
        "authority_precedence_active_blocks_release",
        "authority_precedence_active_register_overrides_resolved_confirmed",
    )
    return all(marker in authority_writer_text for marker in markers)


def validate_state_reconciliation(
    *,
    plan_path: Path,
    state_path: Path,
    release_surface_path: Path,
    phase2_gate_path: Path,
    phase3_gate_path: Path,
    authority_writer_path: Path,
    closeout_path: Path,
) -> dict[str, Any]:
    plan_text = plan_path.read_text(encoding="utf-8")
    state_text = state_path.read_text(encoding="utf-8") if state_path.exists() else ""
    release_surface_text = (
        release_surface_path.read_text(encoding="utf-8")
        if release_surface_path.exists()
        else ""
    )
    phase2_text = (
        phase2_gate_path.read_text(encoding="utf-8")
        if phase2_gate_path.exists()
        else ""
    )
    phase3_text = (
        phase3_gate_path.read_text(encoding="utf-8")
        if phase3_gate_path.exists()
        else ""
    )
    authority_writer_text = (
        authority_writer_path.read_text(encoding="utf-8")
        if authority_writer_path.exists()
        else ""
    )

    plan_gate_status = parse_gate_status(plan_text)
    plan_phase_d = plan_gate_status.get("PhaseD")
    state_phase_d = _extract_phase_d_from_state_yaml(state_text)
    release_surface_ready = _release_surface_precedence_ready(release_surface_text)
    promotion_path_ready = _promotion_path_precedence_ready(phase2_text, phase3_text)
    readside_threshold_ok = _readside_enforcement_threshold_sufficient(authority_writer_text)
    phase_c_surface_gap_resolved = (
        release_surface_ready and promotion_path_ready and readside_threshold_ok
    )
    closeout_result = assess_phase_d_closeout(closeout_path)
    closeout_ok = closeout_result["ok"]

    violations: list[str] = []
    if plan_phase_d == "passed" and not phase_c_surface_gap_resolved:
        violations.append(
            "plan_marks_phase_d_completed_while_phase_c_release_surface_precedence_pending"
        )
    if state_phase_d == "passed" and not phase_c_surface_gap_resolved:
        violations.append(
            "state_marks_phase_d_completed_while_phase_c_release_surface_precedence_pending"
        )
    # Closeout gate: completed without reviewer artifact → violation (regardless of phase_c).
    if plan_phase_d == "passed" and not closeout_ok:
        violations.append("phase_d_completed_without_reviewer_closeout_artifact")
    if state_phase_d == "passed" and not closeout_ok:
        violations.append("phase_d_completed_without_reviewer_closeout_artifact")
    if plan_phase_d in {"pending", "in_progress"} and phase_c_surface_gap_resolved:
        violations.append(
            "plan_phase_d_still_blocked_while_original_block_reason_resolved"
        )
    if state_phase_d in {"pending", "in_progress"} and phase_c_surface_gap_resolved:
        violations.append(
            "state_phase_d_still_blocked_while_original_block_reason_resolved"
        )
    if plan_phase_d == "resumable" and not phase_c_surface_gap_resolved:
        violations.append(
            "plan_phase_d_marked_resumable_but_block_reason_still_active"
        )
    if state_phase_d == "resumable" and not phase_c_surface_gap_resolved:
        violations.append(
            "state_phase_d_marked_resumable_but_block_reason_still_active"
        )

    if phase_c_surface_gap_resolved and closeout_ok:
        recommended_phase_d_status = "completed"
    elif phase_c_surface_gap_resolved:
        recommended_phase_d_status = "resumable"
    else:
        recommended_phase_d_status = "pending"

    return {
        "ok": len(violations) == 0,
        "plan_phase_d_status": plan_phase_d,
        "state_phase_d_status": state_phase_d,
        "release_surface_precedence_ready": release_surface_ready,
        "promotion_path_precedence_ready": promotion_path_ready,
        "readside_threshold_sufficient": readside_threshold_ok,
        "phase_c_surface_gap_resolved": phase_c_surface_gap_resolved,
        "closeout_available": closeout_result["available"],
        "closeout_ok": closeout_ok,
        "closeout_reviewer_id": closeout_result.get("reviewer_id"),
        "recommended_phase_d_status": recommended_phase_d_status,
        "violations": violations,
    }


def _format_human(result: dict[str, Any]) -> str:
    lines = [
        "[state_reconciliation]",
        f"ok={result['ok']}",
        f"plan_phase_d_status={result.get('plan_phase_d_status')}",
        f"state_phase_d_status={result.get('state_phase_d_status')}",
        f"release_surface_precedence_ready={result.get('release_surface_precedence_ready')}",
        f"promotion_path_precedence_ready={result.get('promotion_path_precedence_ready')}",
        f"readside_threshold_sufficient={result.get('readside_threshold_sufficient')}",
        f"phase_c_surface_gap_resolved={result.get('phase_c_surface_gap_resolved')}",
        f"closeout_available={result.get('closeout_available')}",
        f"closeout_ok={result.get('closeout_ok')}",
        f"closeout_reviewer_id={result.get('closeout_reviewer_id')}",
        f"recommended_phase_d_status={result.get('recommended_phase_d_status')}",
    ]
    violations = result.get("violations") or []
    if violations:
        lines.append("violations=" + ",".join(violations))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate governance state reconciliation for Phase D closeout drift."
    )
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--plan")
    parser.add_argument("--state")
    parser.add_argument("--release-surface")
    parser.add_argument("--phase2-gate")
    parser.add_argument("--phase3-gate")
    parser.add_argument("--authority-writer")
    parser.add_argument("--closeout")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    plan_path = Path(args.plan) if args.plan else root / "PLAN.md"
    state_path = Path(args.state) if args.state else root / ".governance-state.yaml"
    release_surface_path = Path(args.release_surface) if args.release_surface else root / "governance_tools" / "release_surface_overview.py"
    phase2_gate_path = Path(args.phase2_gate) if args.phase2_gate else root / "governance_tools" / "phase2_aggregation_consumer.py"
    phase3_gate_path = Path(args.phase3_gate) if args.phase3_gate else root / "governance_tools" / "phase3_promotion_gate.py"
    authority_writer_path = Path(args.authority_writer) if args.authority_writer else root / "governance_tools" / "escalation_authority_writer.py"
    closeout_path = Path(args.closeout) if args.closeout else root / "artifacts" / "governance" / "phase-d-reviewer-closeout.json"

    result = validate_state_reconciliation(
        plan_path=plan_path,
        state_path=state_path,
        release_surface_path=release_surface_path,
        phase2_gate_path=phase2_gate_path,
        phase3_gate_path=phase3_gate_path,
        authority_writer_path=authority_writer_path,
        closeout_path=closeout_path,
    )
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_format_human(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
