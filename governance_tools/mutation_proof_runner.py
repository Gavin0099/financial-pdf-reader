#!/usr/bin/env python3
"""
Mutation Proof Runner - Phase 1: Safe Fixture Probe.

Design Intent:
- Automated verification of Negative Fixtures (data-level hostile inputs).
- Execute against the REAL governance tools in an isolated environment.
- Verify EXACT violation codes as defined in e1-mutation-catalog.md.
- NO source code modification or PYTHONPATH mocking allowed for proof claims.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MutationScenario:
    id: str
    description: str
    target_tool: str  # Command or tool script to run
    expected_code: str
    setup_fn: Any  # Function to prepare the negative fixture


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# --- Fixture Setup Functions ---

def setup_forged_artifact(work_dir: Path) -> None:
    """Create an authority artifact with a mismatched fingerprint."""
    auth_dir = work_dir / "artifacts" / "runtime" / "e1b-phase-b-escalation" / "authority"
    auth_dir.mkdir(parents=True, exist_ok=True)
    
    # Minimal schema-valid but fingerprint-invalid artifact
    artifact = {
        "artifact_type": "e1b_phase_b_escalation_authority",
        "artifact_schema": "e1b.phase_b.escalation_authority.v1",
        "authority_provenance": {
            "writer_id": "governance_tools.escalation_authority_writer",
            "writer_version": "1.0",
            "written_at": _utc_now(),
            "provenance_linkage_version": "v1",
            "authority_valid": True,
            "source_inputs_hash": "dummy",
            "normalized_payload_hash": "dummy",
            "payload_fingerprint": "WRONG_FINGERPRINT_FOR_PROOF"
        },
        "payload": {
            "escalation_id": "mutation-test-esc",
            "mitigation_validation_state": "validated",
            "governance_track_state": "closed",
            "authority_lifecycle_state": "resolved_confirmed"
        }
    }
    (auth_dir / "mutation-test-esc.json").write_text(json.dumps(artifact), encoding="utf-8")


def setup_missing_authority_dir(work_dir: Path) -> None:
    """Active log present but authority directory missing."""
    # Create active escalation log
    log_file = work_dir / "artifacts" / "runtime" / "e1b-phase-b-escalation" / "phase-b-escalation-log.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text('{"event": "escalation_started"}\n', encoding="utf-8")
    
    # Ensure authority dir does NOT exist
    auth_dir = work_dir / "artifacts" / "runtime" / "e1b-phase-b-escalation" / "authority"
    if auth_dir.exists():
        shutil.rmtree(auth_dir)


def setup_plan_passed_missing_closeout(work_dir: Path) -> None:
    """PLAN.md shows [x] Phase D but closeout artifact is missing."""
    plan_content = """
# PLAN.md
- [x] Phase D : Closeout
"""
    (work_dir / "PLAN.md").write_text(plan_content, encoding="utf-8")
    
    # Ensure closeout artifact is missing
    closeout_file = work_dir / "artifacts" / "governance" / "phase-d-reviewer-closeout.json"
    if closeout_file.exists():
        closeout_file.unlink()


# --- Registry ---

SCENARIOS = [
    MutationScenario(
        id="forged_authority_artifact",
        description="Verify fingerprint mismatch detection in authority artifacts.",
        target_tool="governance_tools/escalation_authority_writer.py",
        expected_code="payload_fingerprint_mismatch",
        setup_fn=setup_forged_artifact
    ),
    MutationScenario(
        id="escalation_active_but_no_authority_artifacts",
        description="Verify fail-closed behavior when authority artifacts are missing during active escalation.",
        target_tool="governance_tools/escalation_authority_writer.py",
        expected_code="escalation_active_but_no_authority_artifacts",
        setup_fn=setup_missing_authority_dir
    ),
    MutationScenario(
        id="phase_d_completed_without_reviewer_closeout_artifact",
        description="Verify state reconciliation fails when Phase D is marked passed without a closeout artifact.",
        target_tool="governance_tools/state_reconciliation_validator.py",
        expected_code="phase_d_completed_without_reviewer_closeout_artifact",
        setup_fn=setup_plan_passed_missing_closeout
    )
]


class MutationProofRunner:
    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()

    def run_scenario(self, scenario: MutationScenario) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            
            # 1. Setup Fixture
            scenario.setup_fn(work_dir)
            
            # 2. Prepare Command
            # We run the tool script using the REAL project's code but against the TEMP work_dir
            tool_script = self.project_root / scenario.target_tool
            cmd = [
                sys.executable,
                str(tool_script),
                "--project-root", str(work_dir),
                "--format", "json"
            ]
            
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=str(self.project_root)
                )
                
                # 3. Parse and Verify
                try:
                    output = json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {
                        "scenario": scenario.id,
                        "status": "ERROR",
                        "error": f"Failed to parse tool output: {result.stdout[:200]}",
                        "stderr": result.stderr
                    }
                
                # Check for the expected violation code in release_block_reasons or error fields
                reasons = output.get("release_block_reasons", [])
                violations = output.get("violations", [])
                actual_error = output.get("error")
                
                all_signals = set(reasons) | set(violations)
                if actual_error:
                    all_signals.add(actual_error)
                
                match = scenario.expected_code in all_signals
                
                return {
                    "scenario": scenario.id,
                    "description": scenario.description,
                    "status": "PROTECTED" if match else "VULNERABLE",
                    "expected_code": scenario.expected_code,
                    "actual_signals": list(all_signals),
                    "exit_code": result.returncode,
                    "match": match
                }
                
            except Exception as exc:
                return {
                    "scenario": scenario.id,
                    "status": "ERROR",
                    "error": str(exc)
                }

    def run_all(self) -> list[dict[str, Any]]:
        results = []
        for scenario in SCENARIOS:
            results.append(self.run_scenario(scenario))
        return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Governance Mutation Proof (Phase 1).")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--out", help="Path to write the proof report JSON.")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    runner = MutationProofRunner(project_root)
    results = runner.run_all()
    
    report = {
        "timestamp": _utc_now(),
        "runner_version": "1.0",
        "phase": "E1-B Phase 1: Safe Fixture Probe",
        "results": results,
        "summary": {
            "total": len(results),
            "protected": sum(1 for r in results if r.get("status") == "PROTECTED"),
            "vulnerable": sum(1 for r in results if r.get("status") == "VULNERABLE"),
            "error": sum(1 for r in results if r.get("status") == "ERROR")
        }
    }

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    else:
        print(json.dumps(report, indent=2))

    # Exit with 1 if any scenario is VULNERABLE or ERROR
    if report["summary"]["vulnerable"] > 0 or report["summary"]["error"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
