#!/usr/bin/env python3
"""
Phase D reviewer closeout artifact writer and assessor.

The closeout artifact is the authority gate between 'resumable' and 'completed'
for Phase D.  It must exist and carry trusted writer identity before any system
is permitted to mark Phase D as completed.

Design:
- Absent artifact → fail-closed (ok=False).  This is unconditional — unlike
  escalation register which falls back to ok=True when absent.
  Phase D completed without a reviewer closeout artifact is a governance violation.
- Untrusted writer → fail-closed.
- Minimum required conditions not present → fail-closed (F10/F11).
- state_generator cannot derive 'completed' without this artifact passing
  assess_phase_d_closeout().

Failure semantics (FS-1 / FS-2 from PHASE_D_CLOSE_AUTHORITY.md):
  assess_phase_d_closeout() returns machine-readable failure entries with
  failure_class ('blocked' | 'void' | 'presumptively_void') and remediation
  ('procedural_fix' | 'new_authority_event_required' | 'exception_authority_required').
  'blocked' = structural/procedural, remediable by re-issuance.
  'void' = authority act invalid; new authority event required.

Canonical path (relative to project root):
  artifacts/governance/phase-d-reviewer-closeout.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CLOSEOUT_WRITER_ID = "governance_tools.phase_d_closeout_writer"
CLOSEOUT_WRITER_VERSION = "1.0"
CLOSEOUT_SCHEMA = "governance.phase_d.closeout.v1"

CANONICAL_CLOSEOUT_RELPATH = Path("artifacts") / "governance" / "phase-d-reviewer-closeout.json"

# F10/F11: minimum confirmed_conditions coverage required for ok=True.
# Each entry must appear (as an exact string) in confirmed_conditions.
REQUIRED_CONDITIONS: frozenset[str] = frozenset({
    "reviewer_independent_of_author",
    "phase_c_surface_gap_resolved",
    "validator_output_reviewed",
    "fail_closed_semantics_accepted",
    "no_unresolved_blocking_conditions",
})

# VRB-3 exception override path is not yet implemented in this runtime.
# Contract acknowledges the path exists; runtime explicitly marks it unsupported.
EXCEPTION_OVERRIDE_SUPPORTED: bool = False
_EXCEPTION_OVERRIDE_NOTE: str = (
    "VRB-3 exception authority artifact path is not implemented in this runtime. "
    "Validator failures cannot be overridden. "
    "See PHASE_D_CLOSE_AUTHORITY.md § VRB-3 for the contractual path."
)

# failure_code prefix → (failure_class, remediation)
# Codes with colon-suffixed detail (e.g. 'prefix:detail') resolve via prefix.
_FAILURE_SEMANTICS: dict[str, tuple[str, str]] = {
    "phase_d_closeout_artifact_absent":           ("blocked", "procedural_fix"),
    "phase_d_closeout_artifact_unreadable":        ("blocked", "procedural_fix"),
    "phase_d_closeout_writer_untrusted":           ("blocked", "procedural_fix"),
    "phase_d_closeout_reviewer_id_missing":        ("blocked", "procedural_fix"),
    "phase_d_closeout_confirmed_conditions_empty": ("blocked", "procedural_fix"),
    "phase_d_closeout_confirmed_at_missing":       ("blocked", "procedural_fix"),
    "phase_d_closeout_verdict_not_completed":      ("blocked", "procedural_fix"),
    "phase_d_closeout_required_condition_missing": ("blocked", "procedural_fix"),
    # Future void failures — not yet runtime-detectable:
    # "phase_d_closeout_artifact_modified":   ("void", "new_authority_event_required"),
    # "phase_d_closeout_self_review":         ("void", "new_authority_event_required"),
    # "phase_d_closeout_retroactive_signing": ("presumptively_void", "new_authority_event_required"),
}

# RI-2 (proxy review) and RI-4 (wrong scope) cannot be machine-verified.
# Listed so reviewers and auditors know these are reviewer-attested only.
RUNTIME_UNVERIFIABLE_CONDITIONS: list[dict[str, str]] = [
    {
        "failure_code": "phase_d_closeout_proxy_review",
        "failure_class": "void",
        "detectability": "runtime-unverifiable",
        "attestation": "reviewer-attested",
        "audit_note": (
            "RI-2: reviewer must independently evaluate completion conditions. "
            "Runtime cannot verify independence of judgment. "
            "Mitigated by: 'reviewer_independent_of_author' in confirmed_conditions."
        ),
    },
    {
        "failure_code": "phase_d_closeout_wrong_scope",
        "failure_class": "void",
        "detectability": "runtime-unverifiable",
        "attestation": "reviewer-attested",
        "audit_note": (
            "RI-4: reviewer must explicitly accept Phase D closeout scope, "
            "not just approve implementation code. "
            "Mitigated by: 'phase_d_closeout_scope_accepted' in confirmed_conditions."
        ),
    },
]


def _make_failure(code: str) -> dict[str, str]:
    """Build a structured failure entry from a failure code string.

    Codes may carry a colon-suffix detail (e.g. 'prefix:detail'); the prefix
    is used for semantic lookup while the full code is preserved in output.
    """
    lookup = code.split(":")[0]
    sem = _FAILURE_SEMANTICS.get(lookup)
    if sem is None:
        return {"failure_code": code, "failure_class": "blocked", "remediation": "procedural_fix"}
    return {"failure_code": code, "failure_class": sem[0], "remediation": sem[1]}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_phase_d_closeout(
    path: Path,
    reviewer_id: str,
    confirmed_conditions: list[str],
    *,
    confirmed_at: str | None = None,
    written_at: str | None = None,
) -> dict[str, Any]:
    """
    Write the Phase D reviewer closeout artifact.

    reviewer_id: identity of the reviewer explicitly confirming Phase D completion.
    confirmed_conditions: non-empty list of conditions the reviewer is confirming.
      Caller is responsible for meaningful content — see REQUIRED_CONDITIONS for
      the minimum coverage that assess_phase_d_closeout() will enforce.

    Returns the artifact dict that was written.
    """
    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        raise ValueError("reviewer_id must be a non-empty string")
    if not isinstance(confirmed_conditions, list) or not confirmed_conditions:
        raise ValueError("confirmed_conditions must be a non-empty list")

    artifact = {
        "closeout_schema": CLOSEOUT_SCHEMA,
        "writer_id": CLOSEOUT_WRITER_ID,
        "writer_version": CLOSEOUT_WRITER_VERSION,
        "written_at": written_at or _utc_now(),
        "phase_completed": "D",
        "verdict": "completed",
        "reviewer_id": reviewer_id.strip(),
        "confirmed_at": confirmed_at or _utc_now(),
        "confirmed_conditions": list(confirmed_conditions),
        "reviewer_confirmation": "explicit",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return artifact


def assess_phase_d_closeout(path: Path) -> dict[str, Any]:
    """
    Read and validate the Phase D reviewer closeout artifact.

    Returns:
      {
        "available": bool,
        "ok": bool,
        "review_confirmed": bool,
        "trusted_writer": bool,
        "reviewer_id": str | None,
        "confirmed_conditions": list[str],
        "missing_required_conditions": list[str],   # F10/F11
        "verdict": str | None,
        "confirmed_at": str | None,
        "release_block_reasons": list[str],          # backwards-compat flat list
        "failures": list[dict],                      # structured: failure_code/class/remediation
        "exception_override_supported": bool,        # always False in this runtime
        "exception_override_note": str,
        "runtime_unverifiable_conditions": list[dict],
      }

    Fail-closed semantics (stricter than escalation register):
      Absent artifact → ok=False, available=False.
      Callers MUST NOT treat absent as "not required" — absence means the
      closeout gate has not been satisfied.
    """
    if not path.is_file():
        code = "phase_d_closeout_artifact_absent"
        return {
            "available": False,
            "ok": False,
            "review_confirmed": False,
            "trusted_writer": False,
            "reviewer_id": None,
            "confirmed_conditions": [],
            "missing_required_conditions": sorted(REQUIRED_CONDITIONS),
            "release_block_reasons": [code],
            "failures": [_make_failure(code)],
            "exception_override_supported": EXCEPTION_OVERRIDE_SUPPORTED,
            "exception_override_note": _EXCEPTION_OVERRIDE_NOTE,
            "runtime_unverifiable_conditions": RUNTIME_UNVERIFIABLE_CONDITIONS,
        }

    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        code = f"phase_d_closeout_artifact_unreadable:{exc}"
        return {
            "available": True,
            "ok": False,
            "review_confirmed": False,
            "trusted_writer": False,
            "reviewer_id": None,
            "confirmed_conditions": [],
            "missing_required_conditions": sorted(REQUIRED_CONDITIONS),
            "release_block_reasons": [code],
            "failures": [_make_failure(code)],
            "exception_override_supported": EXCEPTION_OVERRIDE_SUPPORTED,
            "exception_override_note": _EXCEPTION_OVERRIDE_NOTE,
            "runtime_unverifiable_conditions": RUNTIME_UNVERIFIABLE_CONDITIONS,
        }

    trusted_writer = (
        artifact.get("writer_id") == CLOSEOUT_WRITER_ID
        and artifact.get("writer_version") == CLOSEOUT_WRITER_VERSION
        and artifact.get("closeout_schema") == CLOSEOUT_SCHEMA
        and artifact.get("phase_completed") == "D"
        and artifact.get("reviewer_confirmation") == "explicit"
    )
    reviewer_id = artifact.get("reviewer_id")
    reviewer_id_valid = isinstance(reviewer_id, str) and bool(reviewer_id.strip())
    confirmed_conditions = list(artifact.get("confirmed_conditions") or [])
    conditions_present = len(confirmed_conditions) > 0
    confirmed_at = artifact.get("confirmed_at")
    confirmed_at_valid = isinstance(confirmed_at, str) and bool(confirmed_at.strip())
    verdict_valid = artifact.get("verdict") == "completed"

    # F10/F11: check minimum required condition coverage.
    # Only evaluated when conditions are non-empty (F9 covers empty-list case).
    missing_conditions: list[str] = []
    if conditions_present:
        missing_conditions = sorted(REQUIRED_CONDITIONS - set(confirmed_conditions))

    ok = (
        trusted_writer
        and reviewer_id_valid
        and conditions_present
        and confirmed_at_valid
        and verdict_valid
        and not missing_conditions
    )

    reasons: list[str] = []
    if not trusted_writer:
        reasons.append("phase_d_closeout_writer_untrusted")
    if not reviewer_id_valid:
        reasons.append("phase_d_closeout_reviewer_id_missing")
    if not conditions_present:
        reasons.append("phase_d_closeout_confirmed_conditions_empty")
    if not confirmed_at_valid:
        reasons.append("phase_d_closeout_confirmed_at_missing")
    if not verdict_valid:
        reasons.append("phase_d_closeout_verdict_not_completed")
    for cond in missing_conditions:
        reasons.append(f"phase_d_closeout_required_condition_missing:{cond}")

    failures = [_make_failure(r) for r in reasons]

    return {
        "available": True,
        "ok": ok,
        "review_confirmed": ok,
        "trusted_writer": trusted_writer,
        "reviewer_id": reviewer_id if reviewer_id_valid else None,
        "confirmed_conditions": confirmed_conditions,
        "missing_required_conditions": missing_conditions,
        "verdict": artifact.get("verdict"),
        "confirmed_at": confirmed_at if confirmed_at_valid else None,
        "release_block_reasons": reasons,
        "failures": failures,
        "exception_override_supported": EXCEPTION_OVERRIDE_SUPPORTED,
        "exception_override_note": _EXCEPTION_OVERRIDE_NOTE,
        "runtime_unverifiable_conditions": RUNTIME_UNVERIFIABLE_CONDITIONS,
    }
