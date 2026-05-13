#!/usr/bin/env python3
"""
Authority writer and validator for E1b Phase-B escalation authority artifacts.

Design intent:
- Authority semantics are not enough; write-path and read-path must both enforce.
- Only artifacts emitted by this writer are considered authority-valid.
- Consumers fail closed when provenance is untrusted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.escalation_log_writer import assess_escalation_register, read_log_entry_hashes
from governance_tools.lifecycle_transition_writer import validate_lifecycle_transition


WRITER_ID = "governance_tools.escalation_authority_writer"
WRITER_VERSION = "1.0"
ARTIFACT_SCHEMA = "e1b.phase_b.escalation_authority.v1"

ALLOWED_MITIGATION_STATES = {
    "pending_human_validation",
    "pending_independent_validation",
    "author_provisional",
    "validated",
    "waived_by_policy",
}
ALLOWED_GOVERNANCE_TRACK_STATES = {
    "pending_validation",
    "pending_independent_validation",
    "closure_eligible",
    "closed",
    "governance_incomplete",
}
ALLOWED_ROUTE_STATUS = {
    "assigned",
    "in_progress",
    "overdue",
    "completed",
    "not_applicable",
}
ALLOWED_COVERAGE_ERAS = {
    "CURRENT",
    "TRANSITION",
    "PRE-SKIP-TYPE-ERA",
}
ALLOWED_AUTHORITY_LIFECYCLE_STATES = {
    "created",
    "active",
    "superseded",
    "resolved_provisional",
    "resolved_confirmed",
    "invalidated",
    "archived",
}
LIFECYCLE_PRECEDENCE = {
    "invalidated": 0,
    "active": 1,
    "resolved_confirmed": 2,
    "resolved_provisional": 3,
    "superseded": 4,
    "archived": 5,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_authority_dir(project_root: Path) -> Path:
    return project_root / "artifacts" / "runtime" / "e1b-phase-b-escalation" / "authority"


def default_authority_artifact_path(project_root: Path, escalation_id: str) -> Path:
    return default_authority_dir(project_root) / f"{escalation_id}.json"


def _canonical_for_fingerprint(payload: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "escalation_id",
        "mitigation_validation_state",
        "governance_track_state",
        "forced_owner",
        "forced_escalation_target",
        "forced_route_due_date",
        "forced_route_status",
        "protected_claim_used",
        "coverage_era",
        "coverage_caveat",
        "contamination_status",
        "release_claims_resolved",
        "release_blocked",
        "release_block_reasons",
        "authority_lifecycle_state",
        "lifecycle_transition",
    ]
    return {key: payload.get(key) for key in keys}


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = _canonical_for_fingerprint(payload)
    wire = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    seed = f"{WRITER_ID}|{WRITER_VERSION}|{ARTIFACT_SCHEMA}|{wire}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _hash_json(payload: dict[str, Any]) -> str:
    wire = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()


def _validate_required_str(payload: dict[str, Any], key: str, errors: list[str]) -> None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{key} is required and must be a non-empty string")


def _append_release_block(payload: dict[str, Any], reason: str) -> None:
    reasons = payload.setdefault("release_block_reasons", [])
    if reason not in reasons:
        reasons.append(reason)
    payload["release_blocked"] = True


def _append_unique_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)

def _pick_precedence_state(states: list[str]) -> str | None:
    ranked = [
        state for state in states
        if state in LIFECYCLE_PRECEDENCE
    ]
    if not ranked:
        return None
    return sorted(ranked, key=lambda s: LIFECYCLE_PRECEDENCE[s])[0]


def validate_prewrite_payload(payload: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    errors: list[str] = []
    normalized = dict(payload)
    normalized.setdefault("release_blocked", False)
    normalized.setdefault("release_block_reasons", [])

    _validate_required_str(normalized, "escalation_id", errors)

    mitigation_state = normalized.get("mitigation_validation_state")
    if mitigation_state not in ALLOWED_MITIGATION_STATES:
        errors.append("mitigation_validation_state is invalid")

    governance_track = normalized.get("governance_track_state")
    if governance_track not in ALLOWED_GOVERNANCE_TRACK_STATES:
        errors.append("governance_track_state is invalid")

    route_status = normalized.get("forced_route_status", "not_applicable")
    if route_status not in ALLOWED_ROUTE_STATUS:
        errors.append("forced_route_status is invalid")

    if mitigation_state == "author_provisional":
        _validate_required_str(normalized, "forced_owner", errors)
        _validate_required_str(normalized, "forced_escalation_target", errors)
        _validate_required_str(normalized, "forced_route_due_date", errors)
        if route_status == "not_applicable":
            errors.append("forced_route_status must not be not_applicable when mitigation_validation_state=author_provisional")

    if route_status == "overdue":
        _append_release_block(normalized, "forced_route_overdue")

    if normalized.get("release_claims_resolved") and route_status == "overdue":
        errors.append("release_claims_resolved cannot be true when forced_route_status=overdue")

    if normalized.get("protected_claim_used"):
        coverage_era = normalized.get("coverage_era")
        caveat = normalized.get("coverage_caveat")
        if coverage_era not in ALLOWED_COVERAGE_ERAS:
            errors.append("coverage_era is required and must be valid when protected_claim_used=true")
        if coverage_era != "CURRENT" and caveat != "not_supported_under_current_coverage":
            errors.append("coverage_caveat must be not_supported_under_current_coverage when coverage_era is not CURRENT")
        if coverage_era != "CURRENT" and not errors:
            _append_release_block(normalized, "protected_claim_invalid_under_current_coverage")

    contamination_status = normalized.get("contamination_status")
    if contamination_status == "unresolved":
        _append_release_block(normalized, "contamination_unresolved")

    escalation_closed = bool(normalized.get("escalation_closed", False))
    if escalation_closed and governance_track in {"pending_validation", "pending_independent_validation", "governance_incomplete"}:
        errors.append("escalation_closed=true is inconsistent with current governance_track_state")

    lifecycle_state = normalized.get("authority_lifecycle_state")
    if lifecycle_state is not None and lifecycle_state not in ALLOWED_AUTHORITY_LIFECYCLE_STATES:
        errors.append("authority_lifecycle_state is invalid")

    if lifecycle_state in {"resolved_provisional", "resolved_confirmed"}:
        transition = normalized.get("lifecycle_transition")
        if not isinstance(transition, dict):
            errors.append("lifecycle_transition is required for resolved_* lifecycle states")
        else:
            from_state = transition.get("from_state")
            actor = transition.get("actor")
            auto = bool(transition.get("auto", False))
            if not isinstance(from_state, str) or not from_state.strip():
                errors.append("lifecycle_transition.from_state is required")
            if not isinstance(actor, str) or not actor.strip():
                errors.append("lifecycle_transition.actor is required")
            if not errors:
                transition_result = validate_lifecycle_transition(
                    from_state=from_state,
                    to_state=lifecycle_state,
                    actor=actor,
                    auto=auto,
                )
                if not transition_result["ok"]:
                    errors.append("lifecycle_transition_guard_failed:" + ",".join(transition_result["errors"]))

            if lifecycle_state == "resolved_confirmed":
                reviewer_confirmation = transition.get("reviewer_confirmation")
                if not isinstance(reviewer_confirmation, dict):
                    errors.append("resolved_confirmed requires lifecycle_transition.reviewer_confirmation")
                else:
                    reviewer_id = reviewer_confirmation.get("reviewer_id")
                    confirmed_at = reviewer_confirmation.get("confirmed_at")
                    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
                        errors.append("lifecycle_transition.reviewer_confirmation.reviewer_id is required")
                    if not isinstance(confirmed_at, str) or not confirmed_at.strip():
                        errors.append("lifecycle_transition.reviewer_confirmation.confirmed_at is required")

    if lifecycle_state == "active":
        _append_release_block(normalized, "authority_state_active")
    if lifecycle_state == "invalidated":
        _append_release_block(normalized, "authority_state_invalidated")

    return len(errors) == 0, errors, normalized


def build_authority_artifact(
    payload: dict[str, Any],
    *,
    written_at: str | None = None,
    log_entry_hash: str | None = None,
) -> dict[str, Any]:
    """
    Build a validated authority artifact.

    log_entry_hash: optional _entry_hash from the escalation log entry that
    triggered this authority record. When supplied, the artifact carries a
    log_reference that allows authority↔log binding validation. Callers should
    obtain this from append_escalation_log_entry() return value["_entry_hash"].
    """
    ok, errors, normalized = validate_prewrite_payload(payload)
    normalized_payload_hash = _hash_json(_canonical_for_fingerprint(normalized))
    source_inputs_hash = _hash_json(payload)
    artifact = {
        "artifact_type": "e1b_phase_b_escalation_authority",
        "artifact_schema": ARTIFACT_SCHEMA,
        "authority_provenance": {
            "writer_id": WRITER_ID,
            "writer_version": WRITER_VERSION,
            "written_at": written_at or _utc_now(),
            "provenance_linkage_version": "v1",
            "authority_valid": ok,
            "authority_errors": errors,
            "source_inputs_hash": source_inputs_hash,
            "normalized_payload_hash": normalized_payload_hash,
        },
        "payload": normalized,
    }
    artifact["authority_provenance"]["payload_fingerprint"] = _fingerprint(normalized)
    if log_entry_hash is not None:
        artifact["log_reference"] = {
            "entry_hash": log_entry_hash,
            "escalation_id": normalized.get("escalation_id"),
            "binding_version": "v1",
        }
    return artifact


def write_authority_artifact(project_root: Path, payload: dict[str, Any], *, out_file: Path | None = None) -> dict[str, Any]:
    escalation_id = payload.get("escalation_id", "unknown-escalation")
    canonical_target = default_authority_artifact_path(project_root, escalation_id).resolve()
    target = out_file.resolve() if out_file else canonical_target

    if target != canonical_target:
        return {
            "ok": False,
            "artifact_file": str(target),
            "escalation_id": escalation_id,
            "error": "authority_write_path_violation",
            "release_blocked": True,
            "release_block_reasons": ["authority_write_path_violation"],
            "authority_errors": ["authority artifact writes must use canonical writer path"],
        }

    if target.is_file():
        existing = assess_authority_artifact(target)
        if not existing.get("authority_valid", False):
            return {
                "ok": False,
                "artifact_file": str(target),
                "escalation_id": escalation_id,
                "error": "authority_write_existing_untrusted_artifact",
                "release_blocked": True,
                "release_block_reasons": ["existing_untrusted_authority_artifact"],
                "authority_errors": ["existing authority artifact is untrusted and cannot be overwritten silently"],
            }

    artifact = build_authority_artifact(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": bool(artifact["authority_provenance"]["authority_valid"]),
        "artifact_file": str(target),
        "escalation_id": escalation_id,
        "release_blocked": bool(artifact["payload"].get("release_blocked")),
        "release_block_reasons": artifact["payload"].get("release_block_reasons") or [],
        "authority_errors": artifact["authority_provenance"]["authority_errors"],
    }


def assess_authority_artifact(path: Path, *, known_log_hashes: set[str] | None = None) -> dict[str, Any]:
    if not path.is_file():
        return {
            "ok": False,
            "exists": False,
            "authority_valid": False,
            "manifest_file": str(path),
            "error": "authority_artifact_missing",
            "release_blocked": True,
            "release_block_reasons": ["untrusted_escalation_provenance"],
        }
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "exists": True,
            "authority_valid": False,
            "manifest_file": str(path),
            "error": f"authority_artifact_unreadable:{exc}",
            "release_blocked": True,
            "release_block_reasons": ["untrusted_escalation_provenance"],
        }

    provenance = artifact.get("authority_provenance") or {}
    payload = artifact.get("payload") or {}

    ok, errors, normalized = validate_prewrite_payload(payload)
    expected_fingerprint = _fingerprint(normalized)
    actual_fingerprint = provenance.get("payload_fingerprint")
    expected_normalized_hash = _hash_json(_canonical_for_fingerprint(normalized))
    actual_normalized_hash = provenance.get("normalized_payload_hash")

    linkage_fields_ok = all(
        isinstance(provenance.get(field), str) and bool(str(provenance.get(field)).strip())
        for field in ("written_at", "payload_fingerprint", "source_inputs_hash", "normalized_payload_hash")
    )

    trusted_writer = (
        provenance.get("writer_id") == WRITER_ID
        and provenance.get("writer_version") == WRITER_VERSION
        and artifact.get("artifact_schema") == ARTIFACT_SCHEMA
        and provenance.get("provenance_linkage_version") == "v1"
    )
    fingerprint_valid = isinstance(actual_fingerprint, str) and actual_fingerprint == expected_fingerprint
    normalized_hash_valid = isinstance(actual_normalized_hash, str) and actual_normalized_hash == expected_normalized_hash

    authority_valid = bool(
        ok
        and trusted_writer
        and linkage_fields_ok
        and fingerprint_valid
        and normalized_hash_valid
        and provenance.get("authority_valid") is True
    )
    release_blocked = bool(payload.get("release_blocked")) or (not authority_valid)
    release_block_reasons = list(payload.get("release_block_reasons") or [])
    if not authority_valid:
        _append_unique_reason(release_block_reasons, "untrusted_escalation_provenance")
        if not trusted_writer:
            _append_unique_reason(release_block_reasons, "untrusted_writer_identity")
        if not linkage_fields_ok:
            _append_unique_reason(release_block_reasons, "missing_or_invalid_provenance_linkage")
        if not fingerprint_valid:
            _append_unique_reason(release_block_reasons, "payload_fingerprint_mismatch")
        if not normalized_hash_valid:
            _append_unique_reason(release_block_reasons, "normalized_payload_hash_mismatch")
        if not ok:
            _append_unique_reason(release_block_reasons, "payload_prewrite_validation_failed")

    # Log binding check (advisory only — does not affect authority_valid or release_blocked).
    # Verifies that the artifact's log_reference.entry_hash appears in the known log hashes,
    # forming the evidence chain: authority_file → log_entry.
    log_binding_ok: bool | None = None
    log_binding_advisory: str | None = None
    log_ref = artifact.get("log_reference")
    has_log_ref = isinstance(log_ref, dict) and bool(log_ref.get("entry_hash"))

    if known_log_hashes is not None:
        if not isinstance(log_ref, dict):
            log_binding_ok = None
            log_binding_advisory = "no_log_reference_in_artifact"
        else:
            entry_hash = log_ref.get("entry_hash")
            if not isinstance(entry_hash, str) or not entry_hash:
                log_binding_ok = False
                log_binding_advisory = "log_reference_missing_entry_hash"
            elif entry_hash in known_log_hashes:
                log_binding_ok = True
            else:
                log_binding_ok = False
                log_binding_advisory = "log_entry_not_found"

    # trust_root_evidence_level: reviewer-visible signal distinguishing
    # ok=True with no evidence chain from ok=True with verified chain.
    # none             — no log_reference in artifact
    # log_unbound      — log_reference present but not verified (no hashes supplied)
    # log_bound        — log_reference verified against log (hash matched)
    # log_binding_failed — log_reference present but hash not found in log
    if known_log_hashes is None:
        trust_root_evidence_level = "log_unbound" if has_log_ref else "none"
    elif log_binding_ok is True:
        trust_root_evidence_level = "log_bound"
    elif log_binding_ok is False:
        trust_root_evidence_level = "log_binding_failed"
    else:
        trust_root_evidence_level = "none"

    return {
        "ok": authority_valid,
        "exists": True,
        "authority_valid": authority_valid,
        "manifest_file": str(path),
        "error": None if authority_valid else "authority_validation_failed",
        "trusted_writer": trusted_writer,
        "linkage_fields_ok": linkage_fields_ok,
        "fingerprint_valid": fingerprint_valid,
        "normalized_hash_valid": normalized_hash_valid,
        "validation_errors": errors,
        "escalation_id": payload.get("escalation_id"),
        "authority_lifecycle_state": payload.get("authority_lifecycle_state"),
        "written_at": provenance.get("written_at"),
        "release_blocked": release_blocked,
        "release_block_reasons": release_block_reasons,
        "log_binding_ok": log_binding_ok,
        "log_binding_advisory": log_binding_advisory,
        "trust_root_evidence_level": trust_root_evidence_level,
    }


def assess_authority_directory(
    project_root: Path,
    *,
    require_register: bool = False,
    require_log: bool = False,
) -> dict[str, Any]:
    authority_dir = default_authority_dir(project_root)

    escalation_log = authority_dir.parent / "phase-b-escalation-log.jsonl"
    register_path = authority_dir.parent / "phase-b-escalation-register.json"

    # Log Production Gap guard (advisory mode): when caller declares log is required,
    # missing or empty log is recorded as a degraded signal — not a release blocker.
    # Fail-closed enforcement is deferred until log contract + authority↔log binding
    # are validated in production. See: feedback_require_log_semantic_risk.md
    log_advisory_reason: str | None = None
    if require_log:
        if not escalation_log.is_file():
            log_advisory_reason = "escalation_log_missing"
        elif escalation_log.stat().st_size == 0:
            log_advisory_reason = "escalation_log_empty"

    # Primary signal: escalation log existence with content.
    escalation_active_from_log = escalation_log.is_file() and escalation_log.stat().st_size > 0

    # Independent signal: companion register (survives log deletion).
    # If the register says active cases exist but the log is absent or empty,
    # we still treat escalation as active — the register is the cross-verification source.
    register_result = assess_escalation_register(register_path)
    escalation_active_from_register = (
        register_result["available"]
        and register_result["ok"]
        and register_result["escalation_active"]
    )
    register_has_problem = register_result["available"] and not register_result["ok"]
    register_missing_under_requirement = require_register and not register_result["available"]
    register_present = bool(register_result["available"])
    decision_source = "strict_register_enforcement" if require_register else "compatibility_mode"

    escalation_active = escalation_active_from_log or escalation_active_from_register

    if not authority_dir.is_dir():
        if register_missing_under_requirement:
            return {
                "available": False,
                "ok": False,
                "source": "register_required_missing",
                "decision_source": decision_source,
                "register_required_mode": require_register,
                "register_present": register_present,
                "authority_dir": str(authority_dir),
                "artifacts_read": 0,
                "release_blocked": True,
                "release_block_reasons": ["mandatory_register_missing"],
                "records": [],
            }
        if escalation_active:
            return {
                "available": False,
                "ok": False,
                "source": "escalation_expected_missing",
                "decision_source": decision_source,
                "register_required_mode": require_register,
                "register_present": register_present,
                "authority_dir": str(authority_dir),
                "artifacts_read": 0,
                "release_blocked": True,
                "release_block_reasons": ["escalation_active_but_no_authority_artifacts"],
                "records": [],
            }
        if register_has_problem:
            return {
                "available": False,
                "ok": False,
                "source": "register_integrity_failed",
                "decision_source": decision_source,
                "register_required_mode": require_register,
                "register_present": register_present,
                "authority_dir": str(authority_dir),
                "artifacts_read": 0,
                "release_blocked": True,
                "release_block_reasons": list(register_result.get("release_block_reasons") or []),
                "records": [],
            }
        return {
            "available": False,
            "ok": True,
            "source": "no_escalation_expected",
            "decision_source": decision_source,
            "register_required_mode": require_register,
            "register_present": register_present,
            "authority_dir": str(authority_dir),
            "artifacts_read": 0,
            "release_blocked": False,
            "release_block_reasons": [],
            "log_advisory_reason": log_advisory_reason,
            "records": [],
        }

    files = sorted(authority_dir.glob("*.json"))
    log_hashes = read_log_entry_hashes(escalation_log)
    records = [assess_authority_artifact(path, known_log_hashes=log_hashes) for path in files]
    all_ok = all(item["ok"] for item in records)
    blocked = any(item.get("release_blocked") for item in records) or (len(records) > 0 and not all_ok)
    reasons: list[str] = []
    for item in records:
        for reason in item.get("release_block_reasons") or []:
            if reason not in reasons:
                reasons.append(reason)

    lifecycle_effective_by_escalation: dict[str, str] = {}
    for item in records:
        escalation_id = item.get("escalation_id")
        lifecycle_state = item.get("authority_lifecycle_state")
        if not isinstance(escalation_id, str) or not escalation_id.strip():
            continue
        if not isinstance(lifecycle_state, str) or lifecycle_state not in LIFECYCLE_PRECEDENCE:
            continue
        existing = lifecycle_effective_by_escalation.get(escalation_id)
        lifecycle_effective_by_escalation[escalation_id] = _pick_precedence_state(
            [existing, lifecycle_state] if existing else [lifecycle_state]
        ) or lifecycle_state

    precedence_violation = False
    for escalation_id, lifecycle_state in lifecycle_effective_by_escalation.items():
        if lifecycle_state == "invalidated":
            blocked = True
            precedence_violation = True
            _append_unique_reason(reasons, "authority_precedence_invalidated_blocks_release")
        elif lifecycle_state == "active":
            blocked = True
            precedence_violation = True
            _append_unique_reason(reasons, "authority_precedence_active_blocks_release")

    register_active_ids = set(register_result.get("active_escalation_ids") or [])
    for escalation_id in register_active_ids:
        effective_state = lifecycle_effective_by_escalation.get(escalation_id)
        if effective_state == "resolved_confirmed":
            blocked = True
            precedence_violation = True
            _append_unique_reason(reasons, f"authority_precedence_active_register_overrides_resolved_confirmed:{escalation_id}")

    # Propagate register integrity problems even when authority dir exists.
    if register_missing_under_requirement:
        blocked = True
        _append_unique_reason(reasons, "mandatory_register_missing")
    if register_has_problem:
        blocked = True
        for r in register_result.get("release_block_reasons") or []:
            if r not in reasons:
                reasons.append(r)

    # Summarise log binding state across all artifacts (advisory).
    bound_count = sum(1 for r in records if r.get("log_binding_ok") is True)
    unbound_count = sum(1 for r in records if r.get("log_binding_ok") is False)
    no_ref_count = sum(1 for r in records if r.get("log_binding_ok") is None)
    log_binding_summary = {
        "bound": bound_count,
        "unbound": unbound_count,
        "no_reference": no_ref_count,
        "advisory_only": True,
    }

    # Aggregate trust_root_evidence_level: worst-case across all artifact records.
    # Precedence (worst → best): log_binding_failed > none > log_unbound > log_bound
    _LEVEL_RANK = {"log_binding_failed": 0, "none": 1, "log_unbound": 2, "log_bound": 3}
    artifact_levels = [r.get("trust_root_evidence_level", "none") for r in records]
    if not artifact_levels:
        dir_trust_level = "none"
    else:
        dir_trust_level = min(artifact_levels, key=lambda lvl: _LEVEL_RANK.get(lvl, 1))

    return {
        "available": len(files) > 0,
        "ok": (
            all_ok
            and not register_has_problem
            and not precedence_violation
            and not register_missing_under_requirement
        ),
        "source": "authority-writer-monopoly",
        "decision_source": decision_source,
        "register_required_mode": require_register,
        "register_present": register_present,
        "authority_dir": str(authority_dir),
        "artifacts_read": len(files),
        "release_blocked": blocked,
        "release_block_reasons": reasons,
        "log_advisory_reason": log_advisory_reason,
        "log_binding_summary": log_binding_summary,
        "trust_root_evidence_level": dir_trust_level,
        "lifecycle_effective_by_escalation": lifecycle_effective_by_escalation,
        "records": records,
    }


def _format_human(result: dict[str, Any]) -> str:
    lines = [
        "[escalation_authority]",
        f"ok={result.get('ok')}",
        f"available={result.get('available')}",
        f"source={result.get('source')}",
        f"artifacts_read={result.get('artifacts_read')}",
        f"release_blocked={result.get('release_blocked')}",
    ]
    reasons = result.get("release_block_reasons") or []
    if reasons:
        lines.append(f"release_block_reasons={','.join(reasons)}")
    if result.get("trust_root_evidence_level") is not None:
        lines.append(f"trust_root_evidence_level={result.get('trust_root_evidence_level')}")
    if result.get("log_advisory_reason") is not None:
        lines.append(f"log_advisory_reason={result.get('log_advisory_reason')}")
    for item in result.get("records") or []:
        lines.append(
            f"record[{item.get('escalation_id')}]="
            f"ok:{item.get('ok')},trusted_writer:{item.get('trusted_writer')},"
            f"fingerprint_valid:{item.get('fingerprint_valid')},"
            f"trust_root_evidence_level:{item.get('trust_root_evidence_level')}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write or assess escalation authority artifacts.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--mode", choices=("assess", "write"), default="assess")
    parser.add_argument("--input")
    parser.add_argument("--out")
    parser.add_argument("--require-register", action="store_true")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if args.mode == "write":
        if not args.input:
            raise SystemExit("--input JSON file is required in write mode")
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = write_authority_artifact(
            project_root,
            payload,
            out_file=Path(args.out).resolve() if args.out else None,
        )
    else:
        result = assess_authority_directory(
            project_root,
            require_register=bool(args.require_register),
        )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_format_human(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
