#!/usr/bin/env python3
"""
E1-B Phase 2: Real Rule Mutation Runner.

Tests code-level bypass by applying targeted mutations to governance tool SOURCE CODE
inside isolated git worktrees — no production code is ever modified.

Phase 1 proved: hostile DATA cannot fool the governance tools.
Phase 2 proves: removing a governance CHECK from source code is detectable as a gap.

Each scenario:
  1. Creates an isolated git worktree on a throwaway branch
  2. Applies one minimal mutation (old_str → new_str) to the target source file
  3. Runs the mutated tool against a fixture that would trigger the removed check
  4. Reports VULNERABLE if mutation survives (gap documented), PROTECTED if cross-check kills it
  5. Cleans up worktree in try/finally (always runs, even on error)

Safety contract:
  - Production source code is NEVER modified
  - Worktrees are created in <project_root>/.tmp_mut_<id>/ and always removed
  - Mutations are minimal (one targeted string replacement per scenario)
  - VULNERABLE is a documented gap, not a proof that enforcement is broken
    (Phase 1 covers the data-level protection layer; Phase 2 audits code-level surface)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Mutation record
# ---------------------------------------------------------------------------

@dataclass
class CodeMutation:
    """A single code-level mutation: replace old_str with new_str in target_file."""
    target_file: str       # relative to project root
    old_str: str           # exact string to replace (must be unique in file)
    new_str: str           # replacement string


# ---------------------------------------------------------------------------
# Scenario definition
# ---------------------------------------------------------------------------

@dataclass
class MutationScenario2:
    id: str
    description: str
    mutation: CodeMutation
    expected_violation: str        # violation code that SHOULD appear but WON'T after mutation
    violation_field: str           # "violations" | "errors" | "stderr"
    test_fn: Callable[[Path, Path], dict[str, Any]]  # (worktree, fixture_dir) -> raw_result
    catalog_ref: str = ""          # cross-reference to e1-mutation-catalog.md


# ---------------------------------------------------------------------------
# Fixture helpers  (reused from Phase 1 pattern)
# ---------------------------------------------------------------------------

def _setup_plan_passed_no_closeout(fixture_dir: Path) -> None:
    """Minimal PLAN.md with phase_d=passed but no closeout artifact present."""
    (fixture_dir / "PLAN.md").write_text(
        "# PLAN.md\n- [x] Phase D : Closeout\n",
        encoding="utf-8",
    )
    # Ensure closeout artifact is absent
    closeout = fixture_dir / "artifacts" / "governance" / "phase-d-reviewer-closeout.json"
    if closeout.exists():
        closeout.unlink()


def _setup_multiroot(fixture_dir: Path) -> None:
    """Create both app/ and src/app/ to trigger multi-root detection."""
    (fixture_dir / "app").mkdir(exist_ok=True)
    (fixture_dir / "src" / "app").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Scenario test functions
# ---------------------------------------------------------------------------

def _test_closeout_bypass(worktree: Path, fixture_dir: Path) -> dict[str, Any]:
    """Run mutated state_reconciliation_validator against phase_d=passed + no closeout."""
    _setup_plan_passed_no_closeout(fixture_dir)
    result = subprocess.run(
        [
            sys.executable,
            str(worktree / "governance_tools" / "state_reconciliation_validator.py"),
            "--project-root", str(fixture_dir),
            "--format", "json",
        ],
        capture_output=True,
        text=True,
    )
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"parse_error": result.stdout[:300], "stderr": result.stderr}
    return {
        "violations": output.get("violations", []),
        "ok": output.get("ok"),
        "exit_code": result.returncode,
    }


def _test_confirmation_bypass(worktree: Path, _fixture_dir: Path) -> dict[str, Any]:
    """
    Call mutated lifecycle_transition_writer.validate_lifecycle_transition
    with actor='operator' (non-reviewer) requesting resolved_confirmed.
    Library has no CLI, so we use a subprocess -c driver pointing at worktree.
    """
    driver = (
        "import sys; "
        f"sys.path.insert(0, r'{worktree}'); "
        "from governance_tools.lifecycle_transition_writer import validate_lifecycle_transition; "
        "import json; "
        "result = validate_lifecycle_transition("
        "from_state='resolved_provisional', "
        "to_state='resolved_confirmed', "
        "actor='operator', "
        "auto=False"
        "); "
        "print(json.dumps(result))"
    )
    result = subprocess.run(
        [sys.executable, "-c", driver],
        capture_output=True,
        text=True,
    )
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"parse_error": result.stdout[:300], "stderr": result.stderr}
    return {
        "errors": output.get("errors", []),
        "ok": output.get("ok"),
        "exit_code": result.returncode,
    }


def _test_multiroot_bypass(worktree: Path, fixture_dir: Path) -> dict[str, Any]:
    """Run mutated feature_surface_snapshot against a dir with dual app roots."""
    _setup_multiroot(fixture_dir)
    result = subprocess.run(
        [
            sys.executable,
            str(worktree / "governance_tools" / "feature_surface_snapshot.py"),
            "--project-root", str(fixture_dir),
        ],
        capture_output=True,
        text=True,
    )
    return {
        "stderr": result.stderr,
        "stdout_len": len(result.stdout),
        "exit_code": result.returncode,
    }


def _setup_active_escalation_artifact(fixture_dir: Path) -> None:
    """
    Place a minimal authority artifact with authority_lifecycle_state='active' in the
    standard authority_dir.  The artifact intentionally has a wrong fingerprint so it
    fails the trust check — but assess_authority_artifact still reads the raw payload
    field authority_lifecycle_state (line 451), which is all we need to trigger the
    lifecycle_effective_by_escalation precedence loop.
    """
    authority_dir = (
        fixture_dir
        / "artifacts"
        / "runtime"
        / "e1b-phase-b-escalation"
        / "authority"
    )
    authority_dir.mkdir(parents=True, exist_ok=True)
    artifact = {
        "artifact_type": "e1b_phase_b_escalation_authority",
        "artifact_schema": "e1b.phase_b.escalation_authority.v1",
        "authority_provenance": {
            "writer_id": "governance_tools.escalation_authority_writer",
            "writer_version": "1.0",
            "written_at": "2026-05-12T00:00:00+00:00",
            "provenance_linkage_version": "v1",
            "authority_valid": True,
            "source_inputs_hash": "mutation-test-only",
            "normalized_payload_hash": "WRONG_HASH_FOR_MUTATION_TEST",
            "payload_fingerprint": "WRONG_FINGERPRINT_FOR_MUTATION_TEST",
        },
        "payload": {
            "escalation_id": "test-active-precedence-esc",
            "authority_lifecycle_state": "active",
            "mitigation_validation_state": "validated",
            "governance_track_state": "closed",
            "release_blocked": False,
            "release_block_reasons": [],
        },
    }
    (authority_dir / "test-active-precedence-esc.json").write_text(
        json.dumps(artifact), encoding="utf-8"
    )


def _test_precedence_bypass(worktree: Path, fixture_dir: Path) -> dict[str, Any]:
    """
    Run mutated escalation_authority_writer (assess mode) against a fixture that
    contains an authority artifact with lifecycle_state='active'.
    The unmodified code appends authority_precedence_active_blocks_release.
    After the mutation that block is gone → VULNERABLE.
    """
    _setup_active_escalation_artifact(fixture_dir)
    result = subprocess.run(
        [
            sys.executable,
            str(worktree / "governance_tools" / "escalation_authority_writer.py"),
            "--project-root", str(fixture_dir),
            "--mode", "assess",
            "--format", "json",
        ],
        capture_output=True,
        text=True,
    )
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"parse_error": result.stdout[:300], "stderr": result.stderr}
    return {
        "release_block_reasons": output.get("release_block_reasons", []),
        "lifecycle_effective_by_escalation": output.get("lifecycle_effective_by_escalation", {}),
        "ok": output.get("ok"),
        "release_blocked": output.get("release_blocked"),
        "exit_code": result.returncode,
    }


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

SCENARIOS: list[MutationScenario2] = [
    MutationScenario2(
        id="closeout_bypass",
        description=(
            "Remove closeout gate from state_reconciliation_validator. "
            "Phase D can be marked passed without a reviewer closeout artifact."
        ),
        mutation=CodeMutation(
            target_file="governance_tools/state_reconciliation_validator.py",
            old_str=(
                "    # Closeout gate: completed without reviewer artifact → violation (regardless of phase_c).\n"
                "    if plan_phase_d == \"passed\" and not closeout_ok:\n"
                "        violations.append(\"phase_d_completed_without_reviewer_closeout_artifact\")\n"
                "    if state_phase_d == \"passed\" and not closeout_ok:\n"
                "        violations.append(\"phase_d_completed_without_reviewer_closeout_artifact\")"
            ),
            new_str="    # [MUTATION E1-B-P2-01: closeout gate removed]",
        ),
        expected_violation="phase_d_completed_without_reviewer_closeout_artifact",
        violation_field="violations",
        test_fn=_test_closeout_bypass,
        catalog_ref="e1-mutation-catalog.md §1 Closeout Bypass",
    ),
    MutationScenario2(
        id="confirmation_bypass",
        description=(
            "Remove reviewer-confirmation requirement from lifecycle_transition_writer. "
            "Any actor can confirm resolution to resolved_confirmed."
        ),
        mutation=CodeMutation(
            target_file="governance_tools/lifecycle_transition_writer.py",
            old_str=(
                "    # Optional policy tightening: resolved_confirmed requires reviewer actor.\n"
                "    if to_state == \"resolved_confirmed\" and actor not in {\"reviewer_confirmed\", \"reviewer\"}:\n"
                "        errors.append(\"resolved_confirmed_requires_reviewer_confirmation\")"
            ),
            new_str="    # [MUTATION E1-B-P2-02: reviewer confirmation requirement removed]",
        ),
        expected_violation="resolved_confirmed_requires_reviewer_confirmation",
        violation_field="errors",
        test_fn=_test_confirmation_bypass,
        catalog_ref="e1-mutation-catalog.md §1 Confirmation Bypass",
    ),
    MutationScenario2(
        id="snapshot_multiroot_bypass",
        description=(
            "Suppress multi-root warning in feature_surface_snapshot. "
            "Ambiguous app route root goes silently undetected."
        ),
        mutation=CodeMutation(
            target_file="governance_tools/feature_surface_snapshot.py",
            old_str=(
                "    if len(app_roots) > 1:\n"
                "        print(\"warning: multiple app route roots detected\", file=sys.stderr)"
            ),
            new_str="    # [MUTATION E1-B-P2-03: multi-root warning suppressed]",
        ),
        expected_violation="warning: multiple app route roots detected",
        violation_field="stderr",
        test_fn=_test_multiroot_bypass,
        catalog_ref="e1-mutation-catalog.md §1 Snapshot Multi-Root",
    ),
    MutationScenario2(
        id="precedence_bypass",
        description=(
            "Remove active-lifecycle precedence block from escalation_authority_writer. "
            "An authority artifact with lifecycle_state='active' no longer blocks release."
        ),
        mutation=CodeMutation(
            target_file="governance_tools/escalation_authority_writer.py",
            old_str=(
                "        elif lifecycle_state == \"active\":\n"
                "            blocked = True\n"
                "            precedence_violation = True\n"
                "            _append_unique_reason(reasons, \"authority_precedence_active_blocks_release\")"
            ),
            new_str="        # [MUTATION E1-B-P2-04: active precedence block removed]",
        ),
        expected_violation="authority_precedence_active_blocks_release",
        violation_field="release_block_reasons",
        test_fn=_test_precedence_bypass,
        catalog_ref="e1-mutation-catalog.md §1 Precedence Bypass",
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class MutationProofRunnerPhase2:
    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()

    def _apply_mutation(self, worktree: Path, mutation: CodeMutation) -> tuple[bool, str]:
        """Apply string replacement to target file in worktree. Returns (ok, error_msg)."""
        target = worktree / mutation.target_file
        if not target.exists():
            return False, f"target file not found in worktree: {mutation.target_file}"
        source = target.read_text(encoding="utf-8")
        if mutation.old_str not in source:
            return False, f"mutation anchor not found in {mutation.target_file} — source may have changed"
        if source.count(mutation.old_str) > 1:
            return False, f"mutation anchor is not unique in {mutation.target_file} — too risky to apply"
        mutated = source.replace(mutation.old_str, mutation.new_str, 1)
        target.write_text(mutated, encoding="utf-8")
        return True, ""

    def _check_mutation_survived(
        self,
        raw_result: dict[str, Any],
        expected_violation: str,
        violation_field: str,
    ) -> bool:
        """Return True if mutation survived (expected violation is absent)."""
        if violation_field == "stderr":
            return expected_violation not in raw_result.get("stderr", "")
        values = raw_result.get(violation_field, [])
        return expected_violation not in values

    def run_scenario(self, scenario: MutationScenario2) -> dict[str, Any]:
        worktree_path = self.project_root / f".tmp_mut_{scenario.id}"
        branch_name = f"mutation-test-{scenario.id}"

        # Guard: remove stale worktree if it exists from a previous interrupted run
        if worktree_path.exists():
            try:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(worktree_path)],
                    cwd=str(self.project_root), capture_output=True,
                )
            except Exception:
                shutil.rmtree(worktree_path, ignore_errors=True)

        # Create worktree
        wt_create = subprocess.run(
            ["git", "worktree", "add", str(worktree_path), "-b", branch_name],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
        )
        if wt_create.returncode != 0:
            return {
                "scenario": scenario.id,
                "status": "ERROR",
                "error": f"git worktree add failed: {wt_create.stderr.strip()}",
            }

        try:
            # Apply mutation
            mut_ok, mut_err = self._apply_mutation(worktree_path, scenario.mutation)
            if not mut_ok:
                return {
                    "scenario": scenario.id,
                    "status": "ERROR",
                    "error": f"mutation apply failed: {mut_err}",
                }

            # Run test in temp fixture dir
            with tempfile.TemporaryDirectory() as fixture_dir:
                raw_result = scenario.test_fn(worktree_path, Path(fixture_dir))

            # Check if mutation survived
            survived = self._check_mutation_survived(
                raw_result, scenario.expected_violation, scenario.violation_field
            )

            return {
                "scenario": scenario.id,
                "description": scenario.description,
                "catalog_ref": scenario.catalog_ref,
                "status": "VULNERABLE" if survived else "PROTECTED",
                "mutation_survived": survived,
                "expected_violation": scenario.expected_violation,
                "violation_field": scenario.violation_field,
                "raw_result": raw_result,
            }

        except Exception as exc:
            return {
                "scenario": scenario.id,
                "status": "ERROR",
                "error": str(exc),
            }

        finally:
            # Always clean up worktree and branch
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=str(self.project_root),
                capture_output=True,
            )
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=str(self.project_root),
                capture_output=True,
            )

    def run_all(self) -> list[dict[str, Any]]:
        return [self.run_scenario(s) for s in SCENARIOS]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="E1-B Phase 2: Real Rule Mutation Proof Runner."
    )
    parser.add_argument("--project-root", default=".", help="Repository root (default: cwd)")
    parser.add_argument("--out", help="Write JSON report to this path instead of stdout")
    parser.add_argument(
        "--scenario", help="Run a single scenario by ID (omit to run all)"
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    runner = MutationProofRunnerPhase2(project_root)

    if args.scenario:
        matches = [s for s in SCENARIOS if s.id == args.scenario]
        if not matches:
            print(f"ERROR: unknown scenario id '{args.scenario}'", file=sys.stderr)
            print(f"Available: {[s.id for s in SCENARIOS]}", file=sys.stderr)
            return 2
        results = [runner.run_scenario(matches[0])]
    else:
        results = runner.run_all()

    report = {
        "timestamp": _utc_now(),
        "runner_version": "1.0",
        "phase": "E1-B Phase 2: Real Rule Mutation",
        "project_root": str(project_root),
        "results": results,
        "summary": {
            "total": len(results),
            "vulnerable": sum(1 for r in results if r.get("status") == "VULNERABLE"),
            "protected": sum(1 for r in results if r.get("status") == "PROTECTED"),
            "error": sum(1 for r in results if r.get("status") == "ERROR"),
        },
        "interpretation": (
            "VULNERABLE = mutation survived; governance gap documented. "
            "PROTECTED = cross-check prevented bypass. "
            "Phase 2 audits code-level bypass surface; "
            "it does not replace Phase 1 data-level protection evidence."
        ),
    }

    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Report written to {args.out}", file=sys.stderr)
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))

    # Exit 1 if any scenario is VULNERABLE or ERROR (signals governance gaps exist)
    if report["summary"]["vulnerable"] > 0 or report["summary"]["error"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
