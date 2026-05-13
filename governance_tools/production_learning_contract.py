#!/usr/bin/env python3
"""
Phase E / E3 - Production Learning Contract (advisory-only).

This tool aggregates:
- Spec ambiguity signals
- Weak-agent governance hardening signals

Output is a reviewer-visible artifact for learning and follow-up actions.
It does NOT change gate decisions.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validators.governance_hardening_guard import (
    validate_authority_reference,
    validate_governance_closeout_payload,
    detect_forbidden_inference,
)
from validators.spec_ambiguity_validator import evaluate_spec_ambiguity


DEFAULT_OUTPUT = "artifacts/governance/production-learning/latest.json"


def build_production_learning_contract(
    *,
    project_root: Path,
    spec_text: str,
    analysis_text: str,
    authority_source_identified: bool,
    claimed_authority_file: str,
    closeout_payload: dict[str, Any],
    reviewer_action: str = "manual_clarification_pending",
) -> dict[str, Any]:
    ambiguity = evaluate_spec_ambiguity(spec_text, title="production_learning_input_spec")
    inference_guard = detect_forbidden_inference(
        analysis_text,
        authority_source_identified=authority_source_identified,
    )
    authority_ref = validate_authority_reference(
        project_root=project_root,
        claimed_authority_file=claimed_authority_file,
        claimed_overrides_from="runtime_governance_outputs",
    )
    closeout_shape = validate_governance_closeout_payload(closeout_payload)

    advisory_findings: list[str] = []
    if not ambiguity["ok"]:
        advisory_findings.append("spec_ambiguity_requires_clarification")
    if inference_guard["blocked"]:
        advisory_findings.append("forbidden_inference_detected")
    if not authority_ref["ok"]:
        advisory_findings.append("authority_reference_invalid")
    if not closeout_shape["ok"]:
        advisory_findings.append("closeout_payload_shape_invalid")

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "advisory_only": True,
        "governance_complete_claim_allowed": False,
        "reviewer_action_required": len(advisory_findings) > 0,
        "reviewer_action": reviewer_action,
        "advisory_findings": advisory_findings,
        "signals": {
            "spec_ambiguity": ambiguity,
            "forbidden_inference_guard": inference_guard,
            "authority_reference": authority_ref,
            "closeout_payload_shape": closeout_shape,
        },
        "contract_boundary": {
            "allowed_use": [
                "reviewer clarification queue",
                "learning evidence accumulation",
                "governance hardening backlog input",
            ],
            "forbidden_use": [
                "release gate override",
                "promotion approval proof",
                "governance completion claim from this artifact alone",
            ],
        },
    }


def write_contract_artifact(contract: dict[str, Any], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def format_human(contract: dict[str, Any], artifact_path: Path) -> str:
    lines = [
        "[production_learning_contract]",
        f"artifact={artifact_path}",
        f"advisory_only={contract.get('advisory_only')}",
        f"reviewer_action_required={contract.get('reviewer_action_required')}",
        f"reviewer_action={contract.get('reviewer_action')}",
        f"findings={contract.get('advisory_findings', [])}",
    ]
    return "\n".join(lines)


def _load_closeout_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {
            "authority_source_verified": False,
            "runtime_path_executed": False,
            "pre_task_gate_observed": False,
            "post_task_advisory_visible": False,
            "reviewer_surface_present": False,
            "closeout_artifact_generated": False,
            "validation_dataset_updated": False,
            "governance_status": "manual_review_required",
        }
    return json.loads(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build production learning contract artifact (advisory-only).")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--spec-text", default="")
    parser.add_argument("--spec-path")
    parser.add_argument("--analysis-text", default="")
    parser.add_argument("--authority-source-identified", action="store_true")
    parser.add_argument("--claimed-authority-file", default="GOVERNANCE_ENTRY.md")
    parser.add_argument("--closeout-payload-json")
    parser.add_argument("--reviewer-action", default="manual_clarification_pending")
    parser.add_argument("--out", default=DEFAULT_OUTPUT)
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if args.spec_path:
        spec_text = Path(args.spec_path).read_text(encoding="utf-8")
    else:
        spec_text = args.spec_text

    closeout_payload = _load_closeout_payload(args.closeout_payload_json)

    contract = build_production_learning_contract(
        project_root=project_root,
        spec_text=spec_text,
        analysis_text=args.analysis_text,
        authority_source_identified=args.authority_source_identified,
        claimed_authority_file=args.claimed_authority_file,
        closeout_payload=closeout_payload,
        reviewer_action=args.reviewer_action,
    )
    artifact = write_contract_artifact(contract, Path(args.out))

    if args.format == "json":
        print(json.dumps(contract, ensure_ascii=False, indent=2))
    else:
        print(format_human(contract, artifact))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
