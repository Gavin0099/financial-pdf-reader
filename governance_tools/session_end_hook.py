#!/usr/bin/env python3
"""
Session end hook — reads artifacts/session-closeout.txt and closes out the governance session.

Intended to be called by Claude Code stop hook or manually.
Always runs at session stop.

Four independent classification layers:

  presence            file exists and is readable
  schema_validity     all required fields present
  content_sufficiency fields contain specific, non-vague content with observable anchors
  evidence_consistency claimed files/tools cross-referenced against filesystem + execution artifacts

"Observable anchors" for content_sufficiency:
  - WORK_COMPLETED must contain a filename (word.ext) or known tool name — or NONE
  - CHECKS_RUN must name a specific check/command — or NONE

evidence_consistency is an inconsistency signal, not proof of execution.
It raises the cost of fake claims. It does not eliminate them.

Memory promotion tiers:
  working_state_update  content_sufficient — allows state tracking even when evidence is unchecked
  verified_state_update valid (all 4 layers) — full memory promotion

This prevents governance over-strictness from starving memory.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime_hooks.core.session_end import run_session_end
from runtime_hooks.core._canonical_closeout import write_candidate
from governance_tools.gate_policy import (
    load_policy,
    classify_artifact,
    evaluate_gate,
    ARTIFACT_STATE_ABSENT,
    ARTIFACT_STATE_OK,
    POLICY_SOURCE_REPO_LOCAL,
    POLICY_SOURCE_FRAMEWORK_DEFAULT,
    POLICY_SOURCE_BUILTIN_DEFAULT,
)
from governance_tools.taxonomy_expansion_log import append_pending_entry
from governance_tools.memory_significance import write_candidate_and_advisory


CLOSEOUT_FILE = "artifacts/session-closeout.txt"

# Standard path where test_result_ingestor writes the ingested test result.
# Gate decisions are delegated entirely to gate_policy.py — session_end_hook
# never hardcodes blocking logic.
_TEST_RESULT_ARTIFACT = "artifacts/runtime/test-results/latest.json"

REQUIRED_FIELDS = [
    "TASK_INTENT",
    "WORK_COMPLETED",
    "FILES_TOUCHED",
    "CHECKS_RUN",
    "OPEN_RISKS",
    "NOT_DONE",
    "RECOMMENDED_MEMORY_UPDATE",
]

_VAGUE_PHRASES = frozenset({
    "worked on things", "made improvements", "various changes", "misc",
    "updated files", "ran checks", "fixed stuff", "general updates",
    "some work", "various fixes",
})

_FILENAME_PATTERN = re.compile(r"\b\w[\w/-]*\.\w{1,6}\b")

_TOOL_ANCHORS = frozenset({
    "pytest", "python", "quickstart_smoke", "session_end_hook",
    "governance_drift_checker", "adopt_governance", "pre_task_check",
    "post_task_check", "session_start", "external_repo_readiness",
    "external_project_facts_intake", "npm", "cargo", "go", "make",
    "mypy", "ruff", "pylint", "flake8", "black",
})

# Maps tool names to directories/patterns that indicate the tool was run
_TOOL_ARTIFACT_SIGNALS: dict[str, list[str]] = {
    "pytest": [".pytest_cache", "test-results", ".tox"],
    "session_end_hook": ["artifacts/runtime/verdicts"],
    "quickstart_smoke": ["artifacts/runtime/verdicts", "scratch_quickstart_smoke"],
    "governance_drift_checker": [".governance-state.yaml", ".governance-audit"],
    "adopt_governance": [".governance/baseline.yaml"],
    "pre_task_check": ["artifacts/runtime/traces"],
    "post_task_check": ["artifacts/runtime/traces"],
}

# ── Layer result constants ────────────────────────────────────────────────────

PRESENT = "present"
MISSING = "missing"
SCHEMA_VALID = "valid"
SCHEMA_INVALID = "invalid"
CONTENT_SUFFICIENT = "sufficient"
CONTENT_INSUFFICIENT = "insufficient"
EVIDENCE_CONSISTENT = "consistent"
EVIDENCE_INCONSISTENT = "inconsistent"
EVIDENCE_UNCHECKED = "unchecked"

STATUS_VALID = "valid"
STATUS_MISSING = "closeout_missing"
STATUS_SCHEMA_INVALID = "schema_invalid"
STATUS_CONTENT_INSUFFICIENT = "content_insufficient"
STATUS_EVIDENCE_INCONSISTENT = "evidence_inconsistent"

# Memory promotion tiers
MEMORY_TIER_VERIFIED = "verified_state_update"   # all 4 layers pass
MEMORY_TIER_WORKING = "working_state_update"     # content_sufficient, evidence unchecked/failed
MEMORY_TIER_NONE = "no_update"                   # schema or content failed

_DEFAULT_RUNTIME_CONTRACT: dict[str, Any] = {
    "task": "session",
    "rules": ["common"],
    "risk": "low",
    "oversight": "auto",
    "memory_mode": "candidate",
}


# ── Layer 1: Presence ─────────────────────────────────────────────────────────

def _check_presence(path: Path) -> tuple[str, str]:
    if not path.exists():
        return MISSING, ""
    try:
        return PRESENT, path.read_text(encoding="utf-8").strip()
    except Exception:
        return MISSING, ""


# ── Layer 2: Schema validity ──────────────────────────────────────────────────

def _parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().upper()
            value = value.strip()
            if key in REQUIRED_FIELDS:
                fields[key] = value
    return fields


def _check_schema(fields: dict[str, str]) -> tuple[str, list[str]]:
    missing = [f for f in REQUIRED_FIELDS if not fields.get(f)]
    return (SCHEMA_INVALID, missing) if missing else (SCHEMA_VALID, [])


# ── Layer 3: Content sufficiency ──────────────────────────────────────────────

def _has_observable_anchor(value: str) -> bool:
    if _FILENAME_PATTERN.search(value):
        return True
    tokens = set(re.split(r"[\s,/\-]+", value.lower()))
    return bool(tokens & _TOOL_ANCHORS)


def _is_vague(value: str) -> bool:
    lower = value.lower().strip()
    return any(phrase in lower for phrase in _VAGUE_PHRASES)


def _check_content(fields: dict[str, str]) -> tuple[str, list[dict[str, str]]]:
    issues: list[dict[str, str]] = []

    def _assess(field: str, require_anchor: bool = True) -> None:
        value = fields.get(field, "").strip()
        if value.upper() in {"NONE", "NO_UPDATE"}:
            return
        if _is_vague(value):
            issues.append({
                "field": field,
                "type": "vague_phrase",
                "guidance": "Avoid generic phrases. State specific files, commands, or outcomes.",
            })
            return
        if require_anchor and not _has_observable_anchor(value):
            issues.append({
                "field": field,
                "type": "no_observable_anchor",
                "guidance": (
                    "Include at least one filename (e.g. foo.py) or tool name "
                    "(e.g. pytest, session_end_hook) to allow cross-referencing."
                ),
            })

    _assess("WORK_COMPLETED", require_anchor=True)
    _assess("CHECKS_RUN", require_anchor=True)
    _assess("TASK_INTENT", require_anchor=False)

    return (CONTENT_INSUFFICIENT, issues) if issues else (CONTENT_SUFFICIENT, [])


# ── Layer 4: Evidence consistency (cross-reference) ───────────────────────────

def _extract_tool_names(text: str) -> list[str]:
    """Extract known tool names mentioned in a field value."""
    tokens = set(re.split(r"[\s,/()\-]+", text.lower()))
    return [t for t in _TOOL_ANCHORS if t in tokens]


def _check_evidence(
    fields: dict[str, str], project_root: Path
) -> tuple[str, list[str], list[dict[str, Any]]]:
    """
    Cross-reference claimed files and tools against filesystem + artifacts.

    Returns (evidence_consistency, inconsistencies, cross_reference_results).

    cross_reference_results records what was checked and found, so
    failure_signals can map to root causes.
    """
    inconsistencies: list[str] = []
    cross_refs: list[dict[str, Any]] = []
    has_checkable = False

    # FILES_TOUCHED: each file must exist
    files_touched = fields.get("FILES_TOUCHED", "").strip()
    if files_touched and files_touched.upper() not in {"NONE", ""}:
        has_checkable = True
        claimed_files = [f.strip() for f in files_touched.split(",") if f.strip()]
        for claimed in claimed_files:
            exists = (project_root / claimed).exists() or Path(claimed).exists()
            cross_refs.append({
                "type": "file_existence",
                "claimed": claimed,
                "found": exists,
            })
            if not exists:
                inconsistencies.append(
                    f"FILES_TOUCHED: '{claimed}' not found on filesystem"
                )

    # CHECKS_RUN: extract tool names, check for corresponding artifacts
    checks_run = fields.get("CHECKS_RUN", "").strip()
    if checks_run and checks_run.upper() not in {"NONE", ""}:
        has_checkable = True
        found_tools = _extract_tool_names(checks_run)
        for tool in found_tools:
            signals = _TOOL_ARTIFACT_SIGNALS.get(tool, [])
            artifact_found = any(
                (project_root / sig).exists() for sig in signals
            )
            cross_refs.append({
                "type": "tool_artifact_signal",
                "tool": tool,
                "checked_paths": signals,
                "artifact_found": artifact_found,
            })
            if signals and not artifact_found:
                inconsistencies.append(
                    f"CHECKS_RUN: '{tool}' claimed but no corresponding artifact found "
                    f"(checked: {signals})"
                )

    if not has_checkable:
        return EVIDENCE_UNCHECKED, [], cross_refs

    return (
        (EVIDENCE_INCONSISTENT, inconsistencies, cross_refs)
        if inconsistencies
        else (EVIDENCE_CONSISTENT, [], cross_refs)
    )


# ── Failure signals ───────────────────────────────────────────────────────────

def _build_failure_signals(
    schema_validity: str,
    missing_fields: list[str],
    content_sufficiency: str,
    content_issues: list[dict[str, str]],
    evidence_consistency: str,
    inconsistencies: list[str],
) -> list[dict[str, Any]]:
    """
    Map per-layer failures to root-cause signals.

    This lets reviewers see WHY something failed, not just WHAT failed.
    Multiple layers can share the same root cause (e.g. no specific content
    causes both content and evidence failures).
    """
    signals: list[dict[str, Any]] = []

    if schema_validity == SCHEMA_INVALID:
        signals.append({
            "type": "missing_required_fields",
            "affects": ["schema_validity"],
            "detail": missing_fields,
            "guidance": "All 7 fields must be present. See docs/session-closeout-schema.md.",
        })

    for issue in content_issues:
        if issue["type"] == "vague_phrase":
            signals.append({
                "type": "vague_phrase_detected",
                "affects": ["content_sufficiency"],
                "field": issue["field"],
                "guidance": issue["guidance"],
            })
        elif issue["type"] == "no_observable_anchor":
            signals.append({
                "type": "no_observable_anchor",
                "affects": ["content_sufficiency", "evidence_consistency"],
                "field": issue["field"],
                "guidance": issue["guidance"],
            })

    for inc in inconsistencies:
        signals.append({
            "type": "cross_reference_failed",
            "affects": ["evidence_consistency"],
            "detail": inc,
            "guidance": "Verify the file exists or the tool was actually run.",
        })

    return signals


# ── Readiness level detection (metadata only, never decision input) ───────────

def detect_readiness_level(project_root: Path, framework_root: Path) -> dict[str, Any]:
    """
    Detect the structural readiness level of the consuming repo (0-3).

    Returns two independent dimensions:

      level (0-3)                 Structural capability — what governance
                                  infrastructure is in place. Determined by
                                  capability checklist, not session history.

      closeout_activation_state   Whether the cross-reference loop has been
        "active"                  observed in practice (verdict artifacts exist).
        "pending"                 Structural prerequisites met but no verdicts yet.
        "unknown"                 Structural level too low to activate.

    These two dimensions are SEPARATE. A repo can be structural Level 3 with
    activation=pending (all capability in place, no run yet). A repo can be
    activation=active at Level 1 (has run, but content governance incomplete).

    Prior verdict artifacts affect activation_state only. They do NOT affect level.
    Level is determined purely by structural capability checklist.

    IMPORTANT: This result is injected into verdict/trace artifacts as metadata.
    It is NEVER read back as decision input. A Level 0 repo can produce a valid
    closeout. A Level 3 repo can produce closeout_missing.

    See docs/closeout-readiness-spectrum.md for level definitions.
    """
    checks: dict[str, Any] = {}

    # ── Level 0: hook can run + artifacts writable ────────────────────────────
    artifacts_dir = project_root / "artifacts"
    l0 = {
        "hook_callable": True,  # always true if we got here
        "artifacts_writable": _can_write(artifacts_dir),
    }
    checks["level_0"] = l0
    if not all(l0.values()):
        return {
            "level": 0,
            "checklist": checks,
            "limiting_factor": "artifacts_not_writable",
            "suggested_next_step": "mkdir -p artifacts/runtime && chmod -R u+w artifacts/",
            "closeout_activation_state": "unknown",
            "activation_recency": None,
            "activation_gap": "structural_prerequisites_missing",
        }

    # ── Level 1: schema doc + AGENTS.base.md closeout obligation ─────────────
    schema_doc = (framework_root / "docs" / "session-closeout-schema.md").exists()
    agents_base = _agents_base_has_obligation(project_root)
    l1 = {
        "schema_doc_present": schema_doc,
        "agents_base_has_obligation": agents_base,
    }
    checks["level_1"] = l1
    if not all(l1.values()):
        limiting = _first_false(l1)
        next_step = (
            "python -m governance_tools.upgrade_closeout --repo <repo>"
            if limiting == "agents_base_has_obligation"
            else "Ensure docs/session-closeout-schema.md is present in the framework repo"
        )
        return {
            "level": 0,
            "checklist": checks,
            "limiting_factor": limiting,
            "suggested_next_step": next_step,
            "closeout_activation_state": "unknown",
            "activation_recency": None,
            "activation_gap": "structural_prerequisites_missing",
        }

    # ── Level 2: content governance aligned ──────────────────────────────────
    agents_has_anchors = _agents_base_has_anchor_guidance(project_root)
    l2 = {
        "agents_base_has_anchor_guidance": agents_has_anchors,
    }
    checks["level_2"] = l2
    if not all(l2.values()):
        activation = _detect_activation_state(project_root)
        return {
            "level": 1,
            "checklist": checks,
            "limiting_factor": _first_false(l2),
            "suggested_next_step": (
                "python -m governance_tools.upgrade_closeout --repo <repo>  "
                "(re-run to patch anchor guidance)"
            ),
            **activation,
        }

    # ── Level 3: cross-reference capability ──────────────────────────────────
    # Cross-reference (FILES_TOUCHED existence + CHECKS_RUN artifact signals)
    # is always active in the current framework code. Level 3 structural
    # capability is achieved whenever Level 2 is met.
    # Prior verdict artifacts are an ACTIVATION signal, not a structural one.
    l3 = {
        "tool_artifact_signals_configured": True,  # always true in current code
        "working_vs_verified_split_active": True,  # always true in current code
    }
    checks["level_3"] = l3

    activation = _detect_activation_state(project_root)
    return {
        "level": 3,
        "checklist": checks,
        "limiting_factor": None,
        "suggested_next_step": None,
        **activation,
    }


_ACTIVATION_RECENCY_DAYS = 30  # verdicts older than this are considered stale


def _detect_activation_state(project_root: Path) -> dict[str, Any]:
    """
    Compute closeout_activation_state independently of structural level.

    Values:
      observed  — at least one verdict artifact file exists in artifacts/runtime/verdicts/
      pending   — structural prerequisites met but no verdict artifacts yet

    IMPORTANT SEMANTIC NOTE:
      'observed' answers "has the stop hook ever written a verdict?" — not
      "is this repo currently reliable?" or "did recent sessions pass?".
      observed ≠ trustworthy. observed = hook was invoked at least once.

    activation_recency (only set when observed):
      recent  — most recent verdict FILE mtime is within _ACTIVATION_RECENCY_DAYS days
      stale   — verdict files exist but most recent mtime exceeds that threshold

    What recency does NOT check:
      - Whether the session produced closeout_status=valid
      - Whether memory was promoted
      - Whether the closeout content was sufficient

    recent is an operational heuristic (was the hook invoked recently?), not a
    health guarantee (is the governance working?).

    activation_state reduces the risk of completely unverified operation.
    It does not eliminate errors or adversarial behavior.
    """
    verdicts_dir = project_root / "artifacts" / "runtime" / "verdicts"
    if not verdicts_dir.exists():
        return {
            "closeout_activation_state": "pending",
            "activation_recency": None,
            "activation_gap": "no_prior_verdict_artifacts",
        }

    verdict_files = sorted(verdicts_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not verdict_files:
        return {
            "closeout_activation_state": "pending",
            "activation_recency": None,
            "activation_gap": "no_prior_verdict_artifacts",
        }

    # Most recent verdict file
    latest = verdict_files[-1]
    age_seconds = datetime.now(tz=timezone.utc).timestamp() - latest.stat().st_mtime
    age_days = age_seconds / 86400
    recency = "recent" if age_days <= _ACTIVATION_RECENCY_DAYS else "stale"

    return {
        "closeout_activation_state": "observed",
        "activation_recency": recency,
        "activation_gap": None,
    }


def _can_write(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        test = path / ".write_test"
        test.write_text("x")
        test.unlink()
        return True
    except Exception:
        return False


def _agents_base_has_obligation(project_root: Path) -> bool:
    for candidate in ["AGENTS.base.md", "AGENTS.md"]:
        f = project_root / candidate
        if f.exists():
            try:
                return "Session Closeout Obligation" in f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
    return False


def _agents_base_has_anchor_guidance(project_root: Path) -> bool:
    for candidate in ["AGENTS.base.md", "AGENTS.md"]:
        f = project_root / candidate
        if f.exists():
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                return "observable anchor" in text.lower() or "vague" in text.lower()
            except Exception:
                pass
    return False


def _first_false(d: dict[str, Any]) -> str:
    return next((k for k, v in d.items() if not v), "unknown")


# ── Memory promotion tier ─────────────────────────────────────────────────────

def _determine_memory_tier(
    closeout_status: str,
    content_sufficiency: str,
    evidence_consistency: str,
) -> str:
    """
    Two-tier memory promotion:

    verified_state_update  all four layers pass (closeout_status == valid)
    working_state_update   content is sufficient but evidence is unchecked or inconsistent
    no_update              schema or content failed — content cannot be trusted

    Rationale: governance over-strictness that blocks ALL memory updates when
    evidence_consistency fails causes "clean-death" — memory never updates,
    state tracking breaks. working_state_update allows session state tracking
    without claiming verified completeness.
    """
    if closeout_status == STATUS_VALID:
        return MEMORY_TIER_VERIFIED
    if content_sufficiency == CONTENT_SUFFICIENT:
        # content is meaningful even if evidence cross-ref failed or was unchecked
        return MEMORY_TIER_WORKING
    return MEMORY_TIER_NONE


def _split_csv_field(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw or raw.upper() in {"NONE", "NO_UPDATE"}:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _build_closeout_candidate_from_fields(fields: dict[str, str]) -> dict[str, Any]:
    return {
        "task_intent": fields.get("TASK_INTENT", "").strip(),
        "work_summary": fields.get("WORK_COMPLETED", "").strip(),
        "tools_used": _extract_tool_names(fields.get("CHECKS_RUN", "")),
        "artifacts_referenced": _split_csv_field(fields.get("FILES_TOUCHED", "")),
        "open_risks": _split_csv_field(fields.get("OPEN_RISKS", "")),
    }


# ── Classification aggregate ──────────────────────────────────────────────────

def classify_closeout(path: Path, project_root: Path) -> dict[str, Any]:
    presence, raw_text = _check_presence(path)

    if presence == MISSING:
        return {
            "presence": MISSING,
            "schema_validity": SCHEMA_INVALID,
            "content_sufficiency": CONTENT_INSUFFICIENT,
            "evidence_consistency": EVIDENCE_UNCHECKED,
            "closeout_status": STATUS_MISSING,
            "memory_tier": MEMORY_TIER_NONE,
            "per_layer_results": {
                "missing_fields": REQUIRED_FIELDS[:],
                "content_issues": [],
                "inconsistencies": [],
                "cross_reference_results": [],
            },
            "failure_signals": [{
                "type": "closeout_file_missing",
                "affects": ["presence", "schema_validity", "content_sufficiency"],
                "guidance": f"Write {CLOSEOUT_FILE} before session ends. See docs/session-closeout-schema.md.",
            }],
            "fields": {},
            "response_text": "",
        }

    fields = _parse_fields(raw_text)
    schema_validity, missing_fields = _check_schema(fields)
    content_sufficiency, content_issues = _check_content(fields)
    evidence_consistency, inconsistencies, cross_refs = _check_evidence(fields, project_root)

    # Worst-layer status
    if schema_validity == SCHEMA_INVALID:
        status = STATUS_SCHEMA_INVALID
    elif content_sufficiency == CONTENT_INSUFFICIENT:
        status = STATUS_CONTENT_INSUFFICIENT
    elif evidence_consistency == EVIDENCE_INCONSISTENT:
        status = STATUS_EVIDENCE_INCONSISTENT
    else:
        status = STATUS_VALID

    memory_tier = _determine_memory_tier(status, content_sufficiency, evidence_consistency)

    failure_signals = _build_failure_signals(
        schema_validity, missing_fields,
        content_sufficiency, content_issues,
        evidence_consistency, inconsistencies,
    )

    return {
        "presence": presence,
        "schema_validity": schema_validity,
        "content_sufficiency": content_sufficiency,
        "evidence_consistency": evidence_consistency,
        "closeout_status": status,
        "memory_tier": memory_tier,
        "per_layer_results": {
            "missing_fields": missing_fields,
            "content_issues": content_issues,
            "inconsistencies": inconsistencies,
            "cross_reference_results": cross_refs,
        },
        "failure_signals": failure_signals,
        "fields": fields,
        "response_text": raw_text,
    }


# ── Canonical path audit ──────────────────────────────────────────────────────

# Path of the canonical audit log relative to project_root.
# The log is append-only, repo-local, and NOT authoritative — it is an
# observability substrate only.  Authority of truth remains the single-session
# result dict produced by run_session_end_hook().
_CANONICAL_AUDIT_LOG_RELPATH = Path("artifacts") / "runtime" / "canonical-audit-log.jsonl"

# Maximum number of entries retained in the log before rotation.
# Oldest entries are removed when this limit is exceeded, so the log
# never grows without bound.  Set conservatively — observability, not audit.
_CANONICAL_AUDIT_LOG_MAX_ENTRIES = 500

# E1b Phase 1 — Passive Observation Layer.
# Minimum entropy ratio below which an observation window is considered
# degenerate (state sampling rather than event sampling).
# A degenerate window must never be used to trigger E1b enforcement.
_E1B_MIN_VALID_ENTROPY = 0.3

def _build_canonical_path_audit(
    artifact_result: Any,
    skip_test_result_check: bool = False,
) -> dict:
    """
    Audit whether the test-result artifact carries a canonical interpretation
    footprint — i.e. whether test_result_ingestor._apply_failure_disposition
    has been called.

    If ``skip_test_result_check=True`` and the artifact is absent, the absence
    is treated as a declared structural fact rather than an adoption gap.  No
    ``test_result_artifact_absent`` signal is emitted; ``audit_note`` records
    the declaration.  Use this for repos that structurally cannot produce test
    artifacts (e.g. C++ firmware, documentation-only repos).

    Two distinct signal codes:

      test_result_artifact_absent
          The artifact file does not exist at session boundary.  Canonical
          path *may* have run but left no persistent evidence.

      canonical_interpretation_missing
          Artifact exists (ok or stale) but the ``failure_disposition`` key is
          absent from the JSON — meaning the artifact was not produced by the
          canonical ingestor (or was produced by an older version that did not
          include the key).

    ``failure_disposition_key_present=True`` with ``failure_disposition=None``
    is NOT flagged.  That is a valid canonical output when no tests failed.

    This is an advisory surface only — signals are appended to warnings and
    never cause gate blocking.
    """
    from governance_tools.gate_policy import ARTIFACT_STATE_ABSENT

    state = getattr(artifact_result, "state", None)
    artifact_present = state != ARTIFACT_STATE_ABSENT

    # key_present distinguishes "canonical ingestor ran (key exists, value may
    # be null due to no failures)" from "non-canonical artifact (key absent)".
    failure_disposition_key_present: bool = getattr(
        artifact_result, "failure_disposition_key_present", False
    )
    failure_disposition_non_null: bool = artifact_result.failure_disposition is not None

    # For human display, "failure_disposition_present" means the key is in the
    # artifact JSON (value may legitimately be null when no tests failed).
    failure_disposition_present = artifact_present and failure_disposition_key_present

    signals: list[str] = []

    if not artifact_present:
        if skip_test_result_check:
            pass  # structural absence declared — not an adoption signal
        else:
            signals.append("test_result_artifact_absent")
    elif not failure_disposition_key_present:
        # Artifact exists but canonical ingestor key is missing.
        signals.append("canonical_interpretation_missing")
    # else: key present (null or dict) — canonical path footprint confirmed.

    if not artifact_present and skip_test_result_check:
        audit_note = "test result check skipped (structural absence declared)"
    elif not artifact_present:
        audit_note = "test result artifact absent at session boundary"
    elif failure_disposition_key_present and failure_disposition_non_null:
        audit_note = "canonical interpretation footprint present (with classified failures)"
    elif failure_disposition_key_present:
        audit_note = "canonical interpretation footprint present (no failures to classify)"
    else:
        audit_note = "artifact present but canonical interpretation footprint missing"

    return {
        "artifact_present": artifact_present,
        "failure_disposition_key_present": failure_disposition_key_present,
        "failure_disposition_present": failure_disposition_present,
        "signals": signals,
        "audit_note": audit_note,
        "skip_test_result_check": skip_test_result_check,
    }


_PLAN_CONTEXT_PROVENANCE_SIDECAR = Path("artifacts") / "runtime" / "plan-context-provenance.json"


def _read_plan_context_provenance(project_root: Path) -> dict | None:
    """
    Read the plan context provenance sidecar written by session_start or plan_summary.

    Returns None if not present (full PLAN.md presumed, no provenance is recorded).
    Returns dict with fidelity/origin/summary_kind if present.
    Non-blocking: any read failure returns None silently.
    """
    sidecar = project_root / _PLAN_CONTEXT_PROVENANCE_SIDECAR
    if not sidecar.exists():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        # Only return if fidelity key present (guards against corrupted sidecar)
        if isinstance(data, dict) and "fidelity" in data:
            return data
    except Exception:  # noqa: BLE001
        pass
    return None


def _append_canonical_audit_log(
    project_root: Path,
    session_id: str,
    artifact_state: str,
    canonical_path_audit: dict,
    gate_blocked: bool,
    policy_source: str,
    policy_path: str,
    fallback_used: bool,
    repo_policy_present: bool,
    skip_type: str | None = None,
    plan_context_provenance: dict | None = None,
    policy_load_error: str | None = None,
) -> None:
    """
    Append one entry to the canonical audit log for this session.

    Authority note
    --------------
    This log is an append-only observability substrate.
    It is NOT the authority of truth for any session outcome.
    Authority remains the single-session result dict produced by
    run_session_end_hook().  This log exists only to make multi-session
    canonical footprint patterns observable without requiring external tooling.

    Repo-local
    ----------
    Written to <project_root>/artifacts/runtime/canonical-audit-log.jsonl so
    that framework and consuming repos maintain separate histories.

    Failure handling
    ----------------
    Any write failure is silently swallowed — the canonical audit log must
    never block or degrade core session_end behaviour.  The caller should not
    assume the entry was persisted.

    Rotation
    --------
    When the log exceeds _CANONICAL_AUDIT_LOG_MAX_ENTRIES lines, the oldest
    entries are removed so the file does not grow without bound.  Partial
    writes during rotation are transactional via a temp-file swap.
    """
    log_path = project_root / _CANONICAL_AUDIT_LOG_RELPATH

    entry: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        # repo_name is an observability hint, not a canonical repo identifier.
        # project_root.resolve().name avoids any subprocess / git dependency.
        "repo_name": project_root.resolve().name,
        "artifact_state": artifact_state,
        "signals": canonical_path_audit.get("signals", []),
        "audit_note": canonical_path_audit.get("audit_note", ""),
        "gate_blocked": gate_blocked,
        "policy_provenance": {
            "policy_source": policy_source,
            "policy_path": policy_path,
            "fallback_used": fallback_used,
            "repo_policy_present": repo_policy_present,
            "skip_type": skip_type,
            **(({"policy_load_error": policy_load_error}) if policy_load_error is not None else {}),
        },
    }
    if plan_context_provenance is not None:
        entry["plan_context_provenance"] = plan_context_provenance

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing entries (tolerate empty or missing file).
        existing: list[str] = []
        if log_path.exists():
            try:
                existing = [
                    line for line in log_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except OSError:
                existing = []

        new_line = json.dumps(entry, separators=(",", ":"))
        all_lines = existing + [new_line]

        # Rotate: keep only the most recent _CANONICAL_AUDIT_LOG_MAX_ENTRIES.
        if len(all_lines) > _CANONICAL_AUDIT_LOG_MAX_ENTRIES:
            all_lines = all_lines[-_CANONICAL_AUDIT_LOG_MAX_ENTRIES:]

        # Atomic write via temp file + rename so partial writes cannot corrupt.
        tmp_path = log_path.with_suffix(".jsonl.tmp")
        tmp_path.write_text("\n".join(all_lines) + "\n", encoding="utf-8")
        tmp_path.replace(log_path)

    except Exception:  # noqa: BLE001  — intentionally broad; must not propagate
        pass  # Log append failure is silent — never blocks session_end.


def _compute_canonical_audit_trend(
    project_root: Path,
    window_size: int,
    signal_threshold_ratio: float,
) -> dict:
    """
    Compute a sliding-window advisory trend from the canonical audit log.

    Authority boundary
    ------------------
    This is ALWAYS advisory_only=True.  The result MUST NOT be connected to
    gate.blocked or any blocking mechanism.  It is a reviewer-facing adoption
    risk signal only.

    Semantics
    ---------
    Reads the most recent ``window_size`` entries from the canonical audit log,
    sorted by timestamp (not by file position — silent write failures may
    produce gaps).  Returns the fraction of those entries that carry at least
    one advisory signal.  If that fraction >= signal_threshold_ratio, emits
    adoption_risk=True.

    repo_name grouping
    ------------------
    Entries are filtered to those whose repo_name matches
    project_root.resolve().name.  This is best-effort identity — it does not
    handle same-name directories, nested checkouts, or forks.  The scope_note
    field in the output makes this limitation explicit.

    Failure handling
    ----------------
    Any read failure returns a minimal result with entries_available=0 and
    adoption_risk=False.  Trend computation must never block session_end.
    """
    log_path = project_root / _CANONICAL_AUDIT_LOG_RELPATH
    repo_name = project_root.resolve().name

    try:
        if not log_path.exists():
            raw_entries: list[dict] = []
        else:
            lines = [
                l for l in log_path.read_text(encoding="utf-8").splitlines()
                if l.strip()
            ]
            raw_entries = []
            for line in lines:
                try:
                    raw_entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # skip malformed lines; tolerate partial writes
    except Exception:  # noqa: BLE001
        return {
            "window_size": window_size,
            "entries_read": 0,
            "entries_available": 0,
            "entries_with_signals": 0,
            "signal_ratio": 0.0,
            "top_signals": {},
            "adoption_risk": False,
            "advisory_only": True,
            "scope_note": (
                "best-effort grouping by repo_name; not canonical repo identity; "
                "log read failed"
            ),
        }

    # Filter to this repo and sort by timestamp (newest last).
    repo_entries = [e for e in raw_entries if e.get("repo_name") == repo_name]
    try:
        repo_entries.sort(key=lambda e: e.get("timestamp", ""))
    except Exception:  # noqa: BLE001
        pass  # sorting failure is acceptable — use file order as fallback

    entries_available = len(repo_entries)

    # Window: most recent window_size entries.
    window = repo_entries[-window_size:] if len(repo_entries) > window_size else repo_entries
    entries_read = len(window)

    # Count entries with at least one advisory signal and tally signal codes.
    entries_with_signals = 0
    top_signals: dict[str, int] = {}
    for entry in window:
        sigs = entry.get("signals") or []
        if sigs:
            entries_with_signals += 1
            for s in sigs:
                top_signals[s] = top_signals.get(s, 0) + 1

    signal_ratio = entries_with_signals / entries_read if entries_read > 0 else 0.0
    adoption_risk = signal_ratio >= signal_threshold_ratio and entries_read > 0

    return {
        "window_size": window_size,
        "entries_read": entries_read,
        "entries_available": entries_available,
        "entries_with_signals": entries_with_signals,
        "signal_ratio": round(signal_ratio, 4),
        "top_signals": top_signals,
        "adoption_risk": adoption_risk,
        "advisory_only": True,
        "scope_note": (
            "best-effort grouping by repo_name; not canonical repo identity; "
            "does not account for renamed directories or forks"
        ),
    }


# ── E1b Phase 1: Passive Observation Layer ───────────────────────────────────

def _build_e1b_observation(
    project_root: Path,
    window_size: int,
) -> dict:
    """
    E1b Phase 1 — Passive Observation Layer.

    Reads the canonical audit log and computes entropy-based measurement
    quality metrics.  Returns an advisory-only observation dict.

    Purpose
    -------
    Determine whether the current log window contains enough state diversity
    (entropy) to be statistically meaningful for drift detection.
    This is a passive observer — it NEVER influences gate.blocked or ok.

    Entropy definition
    ------------------
    Uses artifact_state (absent / ok / stale / malformed) as the state proxy.
    entropy = distinct_states / entries_in_window.
    Full state_hash (content_hash + mtime) is not tracked here — that level
    of fidelity requires the G1-G4 fixture layer for synthetic scenarios.

    Degenerate dataset (is_degenerate=True):
      entropy < _E1B_MIN_VALID_ENTROPY (0.3)
      => all recent sessions saw the same artifact_state
      => the window cannot support E1b-style statistical interpretation

    DEPRECATION NOTE: is_degenerate uses the LEGACY entropy formula (distinct_states/n < 0.3).
    This formula generates false-positives for stable_ok repos (converged entropy is
    EXPECTED to be low). The authoritative v2 signal is lifecycle_class / is_degenerate_v2
    computed by scripts/analyze_e1b_distribution.py (requires fingerprint_diversity).
    is_degenerate here is kept for backward compatibility ONLY — do not use it as
    a primary governance signal.

    The output dict carries is_degenerate_deprecated=True to make this legacy status
    machine-readable.  Downstream consumers MUST NOT use is_degenerate as a Phase 2
    gate criterion — use is_degenerate_v2 from analyze_e1b_distribution.py instead.

    Authority boundary
    ------------------
    advisory_only=True is HARD-CODED.  This function must never be extended
    to contribute to gate.blocked without a separate, deliberate design decision
    recorded in PLAN.md.
    """
    log_path = project_root / _CANONICAL_AUDIT_LOG_RELPATH
    repo_name = project_root.resolve().name

    try:
        if not log_path.exists():
            raw_entries: list[dict] = []
        else:
            lines = [
                line for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            raw_entries = []
            for line in lines:
                try:
                    raw_entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:  # noqa: BLE001
        return {
            "raw_entries": 0,
            "valid_entries": 0,
            "distinct_states": 0,
            "entropy": 0.0,
            "signal_ratio": 0.0,
            # DEPRECATED: legacy entropy formula; always True here due to error path.
            # Do NOT use as gate criterion. See is_degenerate_v2 in analyze_e1b_distribution.py.
            "is_degenerate": True,
            "is_degenerate_deprecated": True,
            "is_degenerate_formula": "legacy_entropy",
            "observation_note": "observation unavailable due to internal error",
            "advisory_only": True,
            "internal_error": True,
        }

    # Filter to this repo and sort by timestamp.
    repo_entries = [e for e in raw_entries if e.get("repo_name") == repo_name]
    try:
        repo_entries.sort(key=lambda e: e.get("timestamp", ""))
    except Exception:  # noqa: BLE001
        pass

    window = repo_entries[-window_size:] if len(repo_entries) > window_size else repo_entries
    entries_in_window = len(window)

    if entries_in_window == 0:
        return {
            "raw_entries": 0,
            "valid_entries": 0,
            "distinct_states": 0,
            "entropy": 0.0,
            "signal_ratio": 0.0,
            # DEPRECATED: legacy entropy formula; always True for empty window.
            # Do NOT use as gate criterion. See is_degenerate_v2 in analyze_e1b_distribution.py.
            "is_degenerate": True,
            "is_degenerate_deprecated": True,
            "is_degenerate_formula": "legacy_entropy",
            "observation_note": "no entries in log for this repo",
            "advisory_only": True,
        }

    # Entropy using artifact_state as state proxy.
    state_values = [e.get("artifact_state", "unknown") for e in window]
    distinct_states = len(set(state_values))
    entropy = round(distinct_states / entries_in_window, 4)
    is_degenerate = entropy < _E1B_MIN_VALID_ENTROPY

    # Signal ratio: fraction of window entries that recorded at least one signal.
    entries_with_signals = sum(1 for e in window if e.get("signals"))
    signal_ratio = round(entries_with_signals / entries_in_window, 4)

    if is_degenerate:
        note = (
            f"degenerate window: all {entries_in_window} entries share "
            f"{distinct_states} distinct state(s) — entropy={entropy} < "
            f"threshold={_E1B_MIN_VALID_ENTROPY}; "
            "window cannot support E1b statistical interpretation"
        )
    else:
        note = (
            f"observation valid: entropy={entropy} >= threshold={_E1B_MIN_VALID_ENTROPY}; "
            f"distinct_states={distinct_states} over {entries_in_window} entries"
        )

    return {
        "raw_entries": entries_in_window,
        "valid_entries": entries_in_window,  # session_ids are unique; no dedup at this layer
        "distinct_states": distinct_states,
        "entropy": entropy,
        "signal_ratio": signal_ratio,
        # DEPRECATED: legacy entropy-based formula (distinct_states/n < 0.3).
        # Generates false-positives for stable_ok repos (converged window is expected low-entropy).
        # is_degenerate_deprecated=True marks this field as legacy so downstream
        # consumers can detect the deprecation machine-readably and switch to v2.
        # Authoritative v2: lifecycle_class / is_degenerate_v2 in analyze_e1b_distribution.py.
        "is_degenerate": is_degenerate,
        "is_degenerate_deprecated": True,
        "is_degenerate_formula": "legacy_entropy",
        "observation_note": note,
        "advisory_only": True,
    }


# ── Tier-aware closeout enforcement ──────────────────────────────────────────

def _evaluate_closeout_by_tier(
    closeout_status: str,
    hook_coverage_tier: str | None,
) -> dict[str, Any]:
    """
    Apply tier-aware closeout contract, returning a structured evaluation.

    Determines whether a missing closeout file blocks session ok.

    Tier matrix (applies when closeout_status == STATUS_MISSING):
      A or undeclared  — required / violation / fail
                          → ok=False, signal=closeout_file_missing
      B                — expected_but_optional / incomplete_observation / advisory
                          → ok unchanged, signal=closeout_missing_tier_b
      C                — not_expected / not_applicable / none
                          → ok unchanged, no signal

    undeclared additionally emits hook_coverage_tier_undeclared advisory signal.
    For non-missing closeout statuses the fields are still returned for
    artifact visibility, with classification="ok" and ok_effect="pass".
    """
    resolved_tier = hook_coverage_tier if hook_coverage_tier in ("A", "B", "C") else None
    tier_label = resolved_tier or "undeclared"

    # (expectation, classification, enforcement) per tier
    _TIER_CONTRACT: dict[str | None, tuple[str, str, str]] = {
        "A": ("required", "violation", "fail"),
        "B": ("expected_but_optional", "incomplete_observation", "advisory"),
        "C": ("not_expected", "not_applicable", "none"),
        None: ("required", "violation", "fail"),  # undeclared = conservative Tier A
    }

    expectation, classification, enforcement = _TIER_CONTRACT[resolved_tier]

    is_missing = closeout_status == STATUS_MISSING

    signals: list[str] = []
    if is_missing:
        if enforcement == "fail":
            signals.append("closeout_file_missing")
        elif enforcement == "advisory":
            signals.append("closeout_missing_tier_b")
        # enforcement == "none": no signal
        if resolved_tier is None:
            signals.append("hook_coverage_tier_undeclared")

    return {
        "hook_coverage_tier": tier_label,
        "expectation": expectation,
        "classification": classification if is_missing else "ok",
        "enforcement": enforcement,
        "ok_effect": "fail" if (is_missing and enforcement == "fail") else "pass",
        "signals": signals,
    }


# ── Runtime helpers ───────────────────────────────────────────────────────────

def _build_runtime_contract(fields: dict[str, str], memory_tier: str) -> dict[str, Any]:
    contract = dict(_DEFAULT_RUNTIME_CONTRACT)
    task_intent = fields.get("TASK_INTENT", "").strip()
    if task_intent:
        contract["task"] = task_intent
    # working_state updates use candidate mode — they go through normal promotion policy
    # but are tagged so reviewers know the confidence level
    if memory_tier == MEMORY_TIER_NONE:
        contract["memory_mode"] = "stateless"
    return contract


def _generate_session_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"session-{ts}-{uuid.uuid4().hex[:6]}"


def _build_canonical_usage_audit(
    canonical_path_audit: dict,
    canonical_audit_trend: dict,
) -> dict:
    """
    Synthesise E7 (single-session footprint) and E8b (multi-session trend) into
    a single reviewer-facing usage_status name.

    Interpretation layer — NOT a signal producer
    ---------------------------------------------
    This function introduces no new authority, no new signal sources, and no new
    policy parameters.  It names a combination of two pre-existing signals so
    reviewers do not have to cross-reference canonical_path_audit and
    canonical_audit_trend manually.

    Usage status 2x2 matrix
    -----------------------

        E7 footprint present / E8b adoption_risk=False  →  "observed"
        E7 footprint missing / E8b adoption_risk=False  →  "missing"
        E7 footprint present / E8b adoption_risk=True   →  "observed_with_trend_risk"
        E7 footprint missing / E8b adoption_risk=True   →  "trend_risk_context"

    canonical_key_present semantics
    --------------------------------
    True means: the artifact JSON contains the failure_disposition key that
    canonical ingestors write.  It does NOT assert that the ingestor was called —
    only that the artifact looks like ingestor output.  This distinction is
    intentional and must not be eroded.

    Failure handling
    ----------------
    Any exception returns a minimal result with usage_status="observed",
    advisory_only=True, and internal_error=True so that the fallback is never
    mistaken for a genuine observation.  Never blocks.
    """
    try:
        # --- E7 inputs ---
        cpa = canonical_path_audit or {}
        artifact_present: bool = bool(cpa.get("artifact_present", False))
        canonical_key_present: bool = bool(
            cpa.get("failure_disposition_key_present", False)
        )
        # footprint = artifact exists AND canonical ingestor marker key is present
        footprint_present = artifact_present and canonical_key_present
        e7_has_signals = bool(cpa.get("signals"))

        # --- E8b inputs ---
        cat = canonical_audit_trend or {}
        trend_adoption_risk: bool = bool(cat.get("adoption_risk", False))
        trend_signal_ratio: float = float(cat.get("signal_ratio", 0.0))

        # --- 2x2 synthesis ---
        if not e7_has_signals and not trend_adoption_risk:
            usage_status = "observed"
            usage_note = "canonical interpretation footprint present; no trend concern"
        elif e7_has_signals and not trend_adoption_risk:
            usage_status = "missing"
            audit_note = cpa.get("audit_note", "")
            usage_note = (
                "canonical footprint absent this session; "
                "no sustained trend pattern yet"
                + (f"; {audit_note}" if audit_note else "")
            )
        elif not e7_has_signals and trend_adoption_risk:
            usage_status = "observed_with_trend_risk"
            usage_note = (
                "canonical footprint present this session; "
                "trend signals repeated adoption gap in recent history (advisory)"
            )
        else:  # e7 signals AND trend risk
            usage_status = "trend_risk_context"
            usage_note = (
                "canonical footprint absent this session and trend signals repeated "
                "adoption gap; reviewer context warranted (advisory only \u2014 no gate effect)"
            )

        return {
            "artifact_present": artifact_present,
            "canonical_key_present": canonical_key_present,
            "trend_adoption_risk": trend_adoption_risk,
            "trend_signal_ratio": round(trend_signal_ratio, 4),
            "usage_status": usage_status,
            "usage_note": usage_note,
            "advisory_only": True,
            "basis": "E7+E8b synthesis",
        }

    except Exception:  # noqa: BLE001
        # Fallback: safe default, but NOT silent success — internal_error=True
        # signals that this result is a default, not a genuine observation.
        return {
            "artifact_present": False,
            "canonical_key_present": False,
            "trend_adoption_risk": False,
            "trend_signal_ratio": 0.0,
            "usage_status": "observed",
            "usage_note": "canonical usage audit unavailable due to internal error",
            "advisory_only": True,
            "basis": "E7+E8b synthesis",
            "internal_error": True,
        }


# ── Main hook logic ───────────────────────────────────────────────────────────

def run_session_end_hook(project_root: Path) -> dict[str, Any]:
    closeout_path = project_root / CLOSEOUT_FILE
    closeout_trigger_mode = "manual"
    clf = classify_closeout(closeout_path, project_root)

    closeout_status = clf["closeout_status"]
    memory_tier = clf["memory_tier"]
    fields = clf["fields"]

    session_id = _generate_session_id()
    runtime_contract = _build_runtime_contract(fields, memory_tier)

    # Detect readiness level as metadata — NEVER used as decision input.
    # Injected into checks so it appears in verdict/trace artifacts for
    # reviewer context and adoption debugging.
    framework_root = Path(__file__).resolve().parents[1]
    readiness = detect_readiness_level(project_root, framework_root)

    checks: dict[str, Any] = {
        "closeout_status": closeout_status,
        "closeout_file": str(closeout_path),
        "closeout_presence": clf["presence"],
        "closeout_schema_validity": clf["schema_validity"],
        "closeout_content_sufficiency": clf["content_sufficiency"],
        "closeout_evidence_consistency": clf["evidence_consistency"],
        "closeout_memory_tier": memory_tier,
        "closeout_per_layer_results": clf["per_layer_results"],
        "closeout_failure_signals": clf["failure_signals"],
        # Readiness metadata — context only, never decision input
        "repo_readiness_level": readiness["level"],
        "repo_readiness_limiting_factor": readiness["limiting_factor"],
        "repo_closeout_activation_state": readiness.get("closeout_activation_state", "unknown"),
        "repo_activation_recency": readiness.get("activation_recency"),
        "repo_activation_gap": readiness.get("activation_gap"),
    }

    # Pass response_text for working_state and verified tiers.
    # memory_mode=stateless blocks memory for MEMORY_TIER_NONE at the contract level.
    effective_response = (
        clf["response_text"]
        if memory_tier in {MEMORY_TIER_VERIFIED, MEMORY_TIER_WORKING}
        else ""
    )

    if clf["presence"] == PRESENT and clf["schema_validity"] == SCHEMA_VALID:
        # Bridge session-closeout input into canonical closeout pipeline so
        # session_end can build non-missing canonical artifacts for this session.
        write_candidate(
            session_id=session_id,
            project_root=project_root,
            candidate=_build_closeout_candidate_from_fields(fields),
        )

    result = run_session_end(
        project_root=project_root,
        session_id=session_id,
        runtime_contract=runtime_contract,
        checks=checks,
        response_text=effective_response,
        summary=fields.get("TASK_INTENT", ""),
    )

    # Gate evaluation — policy-driven, not hardcoded.
    # load_policy discovers: project_root/governance/gate_policy.yaml first,
    # then framework default, then builtin.  Provenance is always recorded.
    policy = load_policy(project_root=project_root)
    artifact_path = project_root / _TEST_RESULT_ARTIFACT
    artifact_result = classify_artifact(artifact_path, policy)
    gate = evaluate_gate(artifact_result, policy)

    failure_disposition_data = artifact_result.failure_disposition

    # Canonical path audit — runs after gate so gate.blocked is not affected.
    # Emits advisory signals when the session boundary lacks a canonical
    # interpretation footprint.  Advisory only; never contributes to gate.blocked.
    canonical_path_audit = _build_canonical_path_audit(
        artifact_result,
        skip_test_result_check=policy.skip_test_result_check,
    )

    # F1b: Tier-aware closeout enforcement.
    # Tier A / undeclared: closeout_missing → ok=False (existing behaviour, conservative).
    # Tier B: closeout_missing → advisory only; ok is not pulled down.
    # Tier C: closeout_missing → no enforcement; ok is not pulled down.
    closeout_eval = _evaluate_closeout_by_tier(closeout_status, policy.hook_coverage_tier)
    closeout_ok = closeout_status == STATUS_VALID or closeout_eval["ok_effect"] == "pass"

    base_ok = result["ok"] and closeout_ok and not gate.blocked
    gate_errors: list[str] = list(result["errors"]) + gate.errors
    gate_warnings: list[str] = list(result["warnings"]) + gate.warnings

    # Adoption gap signal: if no repo-local policy, warn so the gap is explicit.
    if not policy.repo_policy_present:
        gate_warnings.append(
            "[gate_policy] repo_local_policy_missing: "
            "no gate_policy.yaml found in project governance/ — "
            f"using {policy.policy_source} policy ({policy.policy_path or 'builtin'}); "
            "create governance/gate_policy.yaml to declare this repo's risk posture"
        )

    # Tier-aware closeout evaluation advisory signals.
    for sig in closeout_eval["signals"]:
        if sig == "hook_coverage_tier_undeclared":
            gate_warnings.append(
                "[closeout_evaluation:hook_coverage_tier_undeclared] "
                "hook_coverage_tier not declared in gate_policy.yaml — "
                "treating as Tier A (conservative); "
                "set hook_coverage_tier: A|B|C to make tier explicit"
            )
        elif closeout_eval["enforcement"] == "advisory":
            gate_warnings.append(
                f"[closeout_evaluation:{sig}] "
                f"tier={closeout_eval['hook_coverage_tier']} enforcement=advisory — "
                f"closeout file absent but not required for Tier B repos"
            )

    # Advisory signals from canonical path audit — appended after gate warnings
    # so they are visible but clearly distinguishable from gate decisions.
    for sig in canonical_path_audit["signals"]:
        gate_warnings.append(f"[canonical_path_audit] {sig}: {canonical_path_audit['audit_note']}")

    # Persist canonical audit entry — non-blocking, repo-local, observability only.
    # See _append_canonical_audit_log() for authority boundary documentation.
    _append_canonical_audit_log(
        project_root=project_root,
        session_id=session_id,
        artifact_state=artifact_result.state,
        canonical_path_audit=canonical_path_audit,
        gate_blocked=gate.blocked,
        policy_source=policy.policy_source,
        policy_path=policy.policy_path,
        fallback_used=policy.fallback_used,
        repo_policy_present=policy.repo_policy_present,
        skip_type=policy.skip_type,
        plan_context_provenance=_read_plan_context_provenance(project_root),
        policy_load_error=policy.policy_load_error,
    )

    # Compute multi-session trend — reads the log just written to, advisory only.
    # This MUST NOT contribute to gate.blocked.  Config comes from policy so
    # consuming repos can tune window_size and signal_threshold_ratio.
    canonical_audit_trend = _compute_canonical_audit_trend(
        project_root=project_root,
        window_size=policy.canonical_audit_trend_window_size,
        signal_threshold_ratio=policy.canonical_audit_trend_signal_threshold_ratio,
    )

    # Synthesise E7 + E8b into a single reviewer-facing usage_status — advisory only.
    # This is an interpretation layer, not a signal producer.  It never contributes
    # to gate.blocked.  See _build_canonical_usage_audit() for boundary documentation.
    canonical_usage_audit = _build_canonical_usage_audit(
        canonical_path_audit=canonical_path_audit,
        canonical_audit_trend=canonical_audit_trend,
    )

    # E1b Phase 1: Passive Observation Layer — advisory only, never blocks.
    # Computes entropy from the artifact_state distribution in the audit log.
    # is_degenerate=True means the window cannot support E1b statistical
    # interpretation (all entries share the same artifact_state).
    # This result MUST NOT be used to make gate decisions.
    e1b_observation = _build_e1b_observation(
        project_root=project_root,
        window_size=policy.canonical_audit_trend_window_size,
    )

    # F4: Taxonomy remediation trace.
    # When taxonomy_expansion_signal fires, append a 'pending' log entry so that
    # operator action (or inaction) becomes traceable across sessions.
    # Advisory-only — log write failures must not interrupt the session result.
    taxonomy_expansion_log_entry: dict | None = None
    if failure_disposition_data and failure_disposition_data.get("taxonomy_expansion_signal"):
        try:
            taxonomy_expansion_log_entry = append_pending_entry(
                project_root=project_root,
                session_id=session_id,
                unknown_count=failure_disposition_data.get("unknown_count", 0),
                unknown_threshold=failure_disposition_data.get("unknown_threshold", 0),
            )
        except Exception as exc:  # noqa: BLE001
            gate_warnings.append(
                f"[taxonomy_expansion_log] failed to write remediation trace entry: {exc}"
            )

    # F5: compute gate_verdict — a single human-readable verdict name that
    # distinguishes gate-blocking failures from non-gate ok=False cases so
    # operators (especially Tier B) can interpret the result at a glance.
    gate_verdict = _compute_gate_verdict(base_ok, gate.blocked, gate_warnings, gate_errors)

    memory_closeout = result.get("memory_closeout") or {}
    memory_closeout_decision = str(memory_closeout.get("decision", "")).strip().lower()
    memory_update_attempted = closeout_status != STATUS_MISSING
    memory_update_result = "updated" if result["promotion"] is not None else "skipped"
    if memory_update_result == "updated":
        memory_update_skipped_reason = None
    elif not memory_update_attempted:
        memory_update_skipped_reason = "missing_session_closeout_artifact"
    elif memory_closeout_decision in {"no_candidate", "skipped"}:
        memory_update_skipped_reason = "memory_closeout_no_candidate"
    elif memory_closeout_decision in {"blocked"}:
        memory_update_skipped_reason = "memory_closeout_blocked"
    elif memory_closeout_decision:
        memory_update_skipped_reason = f"memory_closeout_{memory_closeout_decision}"
    elif result["promotion"] is None:
        memory_update_skipped_reason = "promotion_not_performed"
    else:
        memory_update_skipped_reason = None

    memory_significance_artifacts: dict[str, str] | None = None
    try:
        # v0.2 rollout: candidate + significance classifier + advisory report.
        # Advisory only; never changes gate outcome.
        commit_hash = _resolve_head_commit(project_root)
        memory_significance_artifacts = write_candidate_and_advisory(
            repo_root=project_root,
            session_id=session_id,
            commit_hash=commit_hash,
            task_intent=fields.get("TASK_INTENT", ""),
            checks=checks,
        )
    except Exception as exc:  # noqa: BLE001
        gate_warnings.append(
            f"[memory_significance] advisory generation failed: {exc}"
        )

    return {
        "ok": base_ok,
        "session_id": session_id,
        "closeout_trigger_mode": closeout_trigger_mode,
        "closeout_status": closeout_status,
        "memory_tier": memory_tier,
        "memory_update_attempted": memory_update_attempted,
        "memory_update_result": memory_update_result,
        "memory_update_skipped_reason": memory_update_skipped_reason,
        "memory_significance": memory_significance_artifacts,
        "hook_coverage_tier": closeout_eval["hook_coverage_tier"],
        "closeout_evaluation": closeout_eval,
        "repo_readiness_level": readiness["level"],
        "repo_readiness_limiting_factor": readiness["limiting_factor"],
        "repo_closeout_activation_state": readiness.get("closeout_activation_state", "unknown"),
        "repo_activation_recency": readiness.get("activation_recency"),
        "repo_activation_gap": readiness.get("activation_gap"),
        "closeout_classification": {
            "presence": clf["presence"],
            "schema_validity": clf["schema_validity"],
            "content_sufficiency": clf["content_sufficiency"],
            "evidence_consistency": clf["evidence_consistency"],
        },
        "per_layer_results": clf["per_layer_results"],
        "failure_signals": clf["failure_signals"],
        "failure_disposition": failure_disposition_data,
        "gate_policy": {
            "fail_mode": policy.fail_mode,
            "artifact_state": artifact_result.state,
            "blocked": gate.blocked,
            # Provenance — reviewer-visible authority record
            "policy_source": policy.policy_source,
            "policy_path": policy.policy_path,
            "fallback_used": policy.fallback_used,
            "repo_policy_present": policy.repo_policy_present,
            "policy_load_error": policy.policy_load_error,
        },
        "closeout_file": str(closeout_path),
        "decision": result["decision"],
        "snapshot_created": result["snapshot"] is not None,
        "promoted": result["promotion"] is not None,
        "memory_closeout": result["memory_closeout"],
        "verdict_artifact": result["verdict_artifact"],
        "trace_artifact": result["trace_artifact"],
        "canonical_path_audit": canonical_path_audit,
        "canonical_audit_trend": canonical_audit_trend,
        "canonical_usage_audit": canonical_usage_audit,
        "e1b_observation": e1b_observation,
        "taxonomy_expansion_log_entry": taxonomy_expansion_log_entry,
        # gate_verdict is DERIVED from ok/gate_policy.blocked/warnings/errors.
        # It is a human-readable abstraction, not an authoritative gate signal.
        # Source of truth for automation: ok + gate_policy.blocked.
        "gate_verdict": gate_verdict,
        "warnings": gate_warnings,
        "errors": gate_errors,
    }


# ── Output formatting ─────────────────────────────────────────────────────────

# F5: gate verdict semantic tiers
GATE_VERDICT_BLOCKED = "BLOCKED"
GATE_VERDICT_NON_GATE_FAILURE = "NON-GATE-FAILURE"
GATE_VERDICT_OK_WITH_ADVISORIES = "OK+ADVISORIES"
GATE_VERDICT_OK = "OK"


def _compute_gate_verdict(
    ok: bool,
    gate_blocked: bool,
    warnings: list[str],
    errors: list[str],
) -> str:
    """
    Derive a single semantic verdict name from ok/blocked/warnings/errors.

    DERIVED — NOT AUTHORITATIVE.
    gate_verdict is a human-readable abstraction computed from the machine-
    level fields (ok, gate_policy.blocked, warnings, errors).  Those fields
    remain the source of truth.  Tooling and CI MUST NOT gate on gate_verdict
    alone; always check ok and gate_policy.blocked directly.

    Priority:
      BLOCKED            gate.blocked=True OR errors present
                         Production code or test infra must be fixed.
      NON-GATE-FAILURE   ok=False but gate is not blocked.
                         Structural/process issue (e.g. missing closeout).
                         Does NOT require a production code fix.
      OK+ADVISORIES      ok=True with advisory warnings present.
      OK                 ok=True, no warnings.
    """
    if gate_blocked or errors:
        return GATE_VERDICT_BLOCKED
    if not ok:
        return GATE_VERDICT_NON_GATE_FAILURE
    if warnings:
        return GATE_VERDICT_OK_WITH_ADVISORIES
    return GATE_VERDICT_OK


# F5b: semantic prefix dispatchers for warnings / errors
_ADVISORY_PREFIXES = (
    "[gate_policy:signal]",
    "[gate_policy:audit]",
    "[gate_policy]",
    "[closeout_evaluation:",
    "[canonical_path_audit]",
    "[canonical_audit_trend]",
    "[taxonomy_expansion_log]",
)

_BLOCKED_PREFIXES = (
    "[GATE:",
    "[gate_policy:strict]",
)


def _semantic_warning_label(w: str) -> str:
    if any(w.startswith(p) for p in _ADVISORY_PREFIXES):
        return "ADVISORY"
    return "WARNING"


def _semantic_error_label(e: str) -> str:
    if any(e.startswith(p) for p in _BLOCKED_PREFIXES):
        return "BLOCKED"
    return "ERROR"


def format_human_result(result: dict[str, Any]) -> str:
    ok = result["ok"]
    gate_blocked = (result.get("gate_policy") or {}).get("blocked", False)
    warnings = result.get("warnings", [])
    errors = result.get("errors", [])

    # F5a: gate_verdict — computed from result dict if present, else derived inline.
    gate_verdict = result.get("gate_verdict") or _compute_gate_verdict(
        ok, gate_blocked, warnings, errors
    )

    lines = [
        "[session_end_hook]",
        f"ok={ok}",
        f"gate_verdict={gate_verdict}",
    ]

    # F5a: reading guide for NON-GATE-FAILURE — the common Tier B confusion point.
    # ok=False caused by a non-gate issue means no production code fix is required.
    if gate_verdict == GATE_VERDICT_NON_GATE_FAILURE:
        lines.append(
            "  ok=False is caused by a non-gate issue (e.g. missing or incomplete closeout)."
        )
        lines.append(
            "  gate_policy.blocked=False — no production code fix is required."
        )
        lines.append(
            "  See closeout_evaluation below for what triggered the failure."
        )

    lines += [
        f"session_id={result['session_id']}",
        f"closeout_trigger_mode={result.get('closeout_trigger_mode', 'manual')}",
        f"closeout_status={result['closeout_status']}",
        f"memory_tier={result['memory_tier']}",
        f"memory_update_attempted={result.get('memory_update_attempted')}",
        f"memory_update_result={result.get('memory_update_result')}",
        f"repo_readiness_level={result['repo_readiness_level']}"
        + (f" (limited by: {result['repo_readiness_limiting_factor']})" if result['repo_readiness_limiting_factor'] else "")
        + f"  activation={result.get('repo_closeout_activation_state', 'unknown')}"
        + (f"/{result['repo_activation_recency']}" if result.get('repo_activation_recency') else "")
        + (f" (gap: {result['repo_activation_gap']})" if result.get('repo_activation_gap') else ""),
    ]
    if result.get("memory_update_skipped_reason"):
        lines.append(f"memory_update_skipped_reason={result['memory_update_skipped_reason']}")

    # Tier-aware closeout evaluation — displayed early so Tier B/C repos see
    # their advisory status before the per-layer detail.
    ce = result.get("closeout_evaluation") or {}
    if ce:
        lines.append(
            f"closeout_evaluation: "
            f"tier={ce.get('hook_coverage_tier')} "
            f"enforcement={ce.get('enforcement')} "
            f"ok_effect={ce.get('ok_effect')} "
            f"classification={ce.get('classification')}"
        )
        for sig in ce.get("signals", []):
            if ce.get("enforcement") == "advisory":
                lines.append(f"  [ADVISORY] {sig}")
            elif sig == "hook_coverage_tier_undeclared":
                lines.append(f"  [ADVISORY] {sig}")
            else:
                lines.append(f"  [ENFORCEMENT] {sig}")

    clf = result.get("closeout_classification") or {}
    if clf:
        lines.append(f"  presence={clf.get('presence')}")
        lines.append(f"  schema_validity={clf.get('schema_validity')}")
        lines.append(f"  content_sufficiency={clf.get('content_sufficiency')}")
        lines.append(f"  evidence_consistency={clf.get('evidence_consistency')}")

    per = result.get("per_layer_results") or {}
    if per.get("missing_fields"):
        lines.append(f"  missing_fields={per['missing_fields']}")
    for issue in per.get("content_issues", []):
        lines.append(f"  content_issue: {issue['field']} ({issue['type']})")
    for inc in per.get("inconsistencies", []):
        lines.append(f"  inconsistency: {inc}")
    for ref in per.get("cross_reference_results", []):
        if ref["type"] == "file_existence":
            status = "found" if ref["found"] else "NOT FOUND"
            lines.append(f"  file_check: {ref['claimed']} → {status}")
        elif ref["type"] == "tool_artifact_signal":
            status = "artifact found" if ref["artifact_found"] else "no artifact"
            lines.append(f"  tool_check: {ref['tool']} → {status}")

    for sig in result.get("failure_signals", []):
        lines.append(
            f"  signal[{sig['type']}] affects={sig['affects']}: {sig.get('guidance', '')}"
        )

    disp = result.get("failure_disposition") or {}
    if disp:
        lines.append(
            f"failure_disposition: verdict_blocked={disp.get('verdict_blocked')} "
            f"unknown={disp.get('unknown_count', 0)} total={disp.get('total', 0)}"
        )
        by_action = disp.get("by_action") or {}
        if by_action.get("production_fix_required", 0) > 0:
            lines.append(
                f"  [GATE] production_fix_required={by_action['production_fix_required']}: "
                f"agent must not continue without fixing production code"
            )
        if disp.get("taxonomy_expansion_signal"):
            lines.append(
                f"  [SIGNAL] taxonomy_expansion_signal: unknown_count={disp.get('unknown_count', 0)}"
            )

    gp = result.get("gate_policy") or {}
    if gp:
        lines.append(
            f"gate_policy: fail_mode={gp.get('fail_mode')} "
            f"artifact_state={gp.get('artifact_state')} "
            f"blocked={gp.get('blocked')}"
        )
        lines.append(
            f"  policy_source={gp.get('policy_source')} "
            f"fallback_used={gp.get('fallback_used')} "
            f"repo_policy_present={gp.get('repo_policy_present')}"
        )
        policy_path = gp.get('policy_path')
        if policy_path:
            lines.append(f"  policy_path={policy_path}")
        policy_load_error = gp.get('policy_load_error')
        if policy_load_error:
            lines.append(
                f"  [ADVISORY] gate_policy: YAML parse failed, using builtin_defaults"
            )
            lines.append(f"    parse_error={policy_load_error}")

    # Canonical path audit advisory — displayed after gate policy, before decision.
    cpa = result.get("canonical_path_audit") or {}
    if cpa:
        lines.append(
            f"canonical_path_audit: "
            f"artifact_present={cpa.get('artifact_present')} "
            f"failure_disposition_key_present={cpa.get('failure_disposition_key_present')} "
            f"failure_disposition_present={cpa.get('failure_disposition_present')}"
        )
        if cpa.get("signals"):
            for sig in cpa["signals"]:
                lines.append(f"  [ADVISORY] {sig}")
            lines.append(f"  note: {cpa.get('audit_note', '')}")
        elif cpa.get("skip_test_result_check") and not cpa.get("artifact_present"):
            lines.append("  [skipped] test_result_check: structural absence declared")
            lines.append(f"  note: {cpa.get('audit_note', '')}")

    cat = result.get("canonical_audit_trend") or {}
    if cat:
        lines.append(
            f"canonical_audit_trend: "
            f"entries_read={cat.get('entries_read', 0)}/{cat.get('window_size', '?')} "
            f"signal_ratio={cat.get('signal_ratio', 0.0):.0%} "
            f"adoption_risk={cat.get('adoption_risk')}"
        )
        if cat.get("adoption_risk"):
            top = cat.get("top_signals") or {}
            top_str = ", ".join(f"{k}={v}" for k, v in top.items()) if top else "none"
            lines.append(f"  [ADVISORY] adoption_risk: top_signals=[{top_str}]")
            lines.append(f"  scope: {cat.get('scope_note', '')}")

    cua = result.get("canonical_usage_audit") or {}
    if cua:
        status = cua.get("usage_status", "?")
        lines.append(
            f"canonical_usage_audit: "
            f"usage_status={status} "
            f"artifact={cua.get('artifact_present')} "
            f"canonical_key={cua.get('canonical_key_present')} "
            f"trend_risk={cua.get('trend_adoption_risk')}"
            + (" [internal_error]" if cua.get("internal_error") else "")
        )
        if status != "observed" or cua.get("internal_error"):
            lines.append(f"  [ADVISORY] canonical usage: {cua.get('usage_note', '')}")

    e1b = result.get("e1b_observation") or {}
    if e1b:
        lines.append(
            f"e1b_observation: "
            f"entropy={e1b.get('entropy', 0.0)} "
            f"distinct_states={e1b.get('distinct_states', 0)} "
            f"entries={e1b.get('raw_entries', 0)} "
            f"signal_ratio={e1b.get('signal_ratio', 0.0):.0%} "
            f"is_degenerate={e1b.get('is_degenerate')} [DEPRECATED:legacy_entropy]"
            + (" [internal_error]" if e1b.get("internal_error") else "")
        )
        if e1b.get("is_degenerate") or e1b.get("internal_error"):
            lines.append(f"  [ADVISORY] e1b: {e1b.get('observation_note', '')}")
            if e1b.get("is_degenerate") and not e1b.get("internal_error"):
                lines.append(
                    "  [DEPRECATED] is_degenerate uses legacy entropy formula \u2014 "
                    "DO NOT use as Phase 2 gate criterion; "
                    "for authoritative v2 signal run: "
                    "scripts/analyze_e1b_distribution.py (lifecycle_class / is_degenerate_v2)"
                )
    lines += [
        f"decision={result['decision']}",
        f"snapshot_created={result['snapshot_created']}",
        f"promoted={result['promoted']}",
    ]

    closeout = result.get("memory_closeout") or {}
    if closeout:
        lines.append(f"memory_closeout_decision={closeout.get('decision')}")
        lines.append(f"memory_closeout_reason={closeout.get('reason')}")

    # F5b: semantic labels for warnings and errors so operators can distinguish
    # advisory notices from hard failures without parsing warning string content.
    for w in warnings:
        lines.append(f"[{_semantic_warning_label(w)}] {w}")
    for e in errors:
        lines.append(f"[{_semantic_error_label(e)}] {e}")

    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Session end hook. Four-layer closeout classification with cross-reference, "
            "failure_signals, and two-tier memory promotion. Always runs."
        )
    )
    parser.add_argument("--project-root", default=".", help="Consuming repo root")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    try:
        result = run_session_end_hook(project_root=project_root)
    except RuntimeError as exc:
        # F2: policy loading integrity failure — repo-local yaml present but
        # PyYAML unavailable.  This is a hard stop; do not continue with a
        # silently substituted builtin default.
        print(f"[gate_policy] FATAL: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human_result(result))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
