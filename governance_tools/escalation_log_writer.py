#!/usr/bin/env python3
"""
Canonical log writer and escalation register for E1b Phase-B.

Two trust-hardening slices:

Slice 1 — Log writer identity:
  append_escalation_log_entry() embeds _writer_id in every entry.
  assess_log_writer_integrity() validates that entries carry a trusted identity.
  Entries without _writer_id are treated as legacy (not fail-closed).
  Entries with an untrusted _writer_id are treated as writer-untrusted.

Slice 2 — Companion escalation register (cross-verification source):
  write_escalation_register() writes a machine-readable JSON register that
  records active escalation IDs independently of the log file.
  assess_escalation_register() reads the register.

  The register is the independent signal for "escalation cases exist."
  If the register records active IDs but the log is absent, assess_authority_directory()
  can detect the governance gap without relying solely on the log file.

Design intent:
  These two components harden the Log Production Gap:
  - Writer identity makes silent tampering detectable.
  - The register provides a log-independent source that can survive log deletion.
  Together they move from "provided authority fail-closed" toward
  "authority-required detection fail-closed."
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOG_WRITER_ID = "governance_tools.escalation_log_writer"
LOG_WRITER_VERSION = "1.0"

REGISTER_WRITER_ID = "governance_tools.escalation_register_writer"
REGISTER_WRITER_VERSION = "1.0"
REGISTER_SCHEMA = "e1b.phase_b.escalation_register.v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Slice 1 — Log writer identity
# ---------------------------------------------------------------------------

def _compute_entry_hash(entry: dict[str, Any]) -> str:
    """
    Deterministic fingerprint for a log entry.

    Hashes the identity-stable fields: escalation_id, _writer_id, _written_at.
    This hash is embedded in both the log entry (_entry_hash) and in any
    authority artifact that references this entry (log_reference.entry_hash),
    forming the evidence chain: authority_file → log_entry.
    """
    canonical = {
        "escalation_id": entry.get("escalation_id"),
        "_writer_id": entry.get("_writer_id"),
        "_written_at": entry.get("_written_at"),
    }
    wire = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()


def append_escalation_log_entry(
    log_path: Path,
    entry: dict[str, Any],
    *,
    written_at: str | None = None,
) -> dict[str, Any]:
    """
    Append a single escalation log entry with embedded writer identity and entry hash.

    Injected fields (must not be set by caller):
      _writer_id, _writer_version, _written_at, _entry_hash

    Returns the normalized entry that was written.
    """
    normalized = dict(entry)
    if "_writer_id" in normalized or "_writer_version" in normalized:
        raise ValueError(
            "_writer_id and _writer_version must not be set by caller; "
            "they are injected by the canonical log writer"
        )
    normalized["_writer_id"] = LOG_WRITER_ID
    normalized["_writer_version"] = LOG_WRITER_VERSION
    normalized["_written_at"] = written_at or _utc_now()
    # _entry_hash computed after identity fields are set — enables authority↔log binding
    normalized["_entry_hash"] = _compute_entry_hash(normalized)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")) + "\n")

    return normalized


def read_log_entry_hashes(log_path: Path) -> set[str]:
    """Return the set of all _entry_hash values in the log. Used for authority binding checks."""
    if not log_path.is_file():
        return set()
    hashes: set[str] = set()
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                h = entry.get("_entry_hash")
                if isinstance(h, str) and h:
                    hashes.add(h)
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return hashes


def assess_log_writer_integrity(log_path: Path) -> dict[str, Any]:
    """
    Check that escalation log entries carry trusted writer identity.

    Returns:
      {
        "ok": bool,
        "exists": bool,
        "entry_count": int,
        "trusted_entry_count": int,   # _writer_id == LOG_WRITER_ID
        "legacy_entry_count": int,    # no _writer_id (pre-hardening entries)
        "untrusted_entry_count": int, # _writer_id present but not trusted
        "writer_integrity": "trusted" | "legacy_only" | "untrusted_present",
        "release_blocked": bool,
        "release_block_reasons": list[str],
      }

    Semantics:
      trusted:          all entries have trusted _writer_id
      legacy_only:      some/all entries have no _writer_id (ok=True, not fail-closed)
      untrusted_present: at least one entry has a non-trusted _writer_id (ok=False)
    """
    if not log_path.is_file():
        return {
            "ok": False,
            "exists": False,
            "entry_count": 0,
            "trusted_entry_count": 0,
            "legacy_entry_count": 0,
            "untrusted_entry_count": 0,
            "writer_integrity": "log_absent",
            "release_blocked": False,  # absence handled by assess_authority_directory
            "release_block_reasons": [],
        }

    trusted = 0
    legacy = 0
    untrusted = 0
    errors: list[str] = []

    try:
        lines = [l.strip() for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError as exc:
        return {
            "ok": False,
            "exists": True,
            "entry_count": 0,
            "trusted_entry_count": 0,
            "legacy_entry_count": 0,
            "untrusted_entry_count": 0,
            "writer_integrity": f"log_unreadable:{exc}",
            "release_blocked": True,
            "release_block_reasons": ["log_unreadable"],
        }

    for i, line in enumerate(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"line_{i+1}_invalid_json")
            untrusted += 1
            continue

        writer_id = entry.get("_writer_id")
        if writer_id is None:
            legacy += 1
        elif writer_id == LOG_WRITER_ID:
            trusted += 1
        else:
            untrusted += 1

    total = trusted + legacy + untrusted
    release_blocked = untrusted > 0 or bool(errors)
    reasons: list[str] = []
    if untrusted > 0:
        reasons.append("log_entries_with_untrusted_writer_id")
    reasons.extend(errors)

    if untrusted > 0:
        integrity = "untrusted_present"
    elif legacy > 0:
        integrity = "legacy_only"
    else:
        integrity = "trusted"

    return {
        "ok": not release_blocked,
        "exists": True,
        "entry_count": total,
        "trusted_entry_count": trusted,
        "legacy_entry_count": legacy,
        "untrusted_entry_count": untrusted,
        "writer_integrity": integrity,
        "release_blocked": release_blocked,
        "release_block_reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Slice 2 — Companion escalation register
# ---------------------------------------------------------------------------

def write_escalation_register(
    register_path: Path,
    active_escalation_ids: list[str],
    *,
    written_at: str | None = None,
) -> dict[str, Any]:
    """
    Write the machine-readable escalation register.

    The register is the independent source of truth for "active escalation cases
    exist."  It survives log deletion and can be used for cross-verification.

    active_escalation_ids: list of escalation IDs that are currently open.
      An empty list means no active cases (register still written for audit trail).
    """
    if not isinstance(active_escalation_ids, list):
        raise ValueError("active_escalation_ids must be a list")
    deduped = list(dict.fromkeys(active_escalation_ids))  # stable dedup

    register = {
        "register_schema": REGISTER_SCHEMA,
        "writer_id": REGISTER_WRITER_ID,
        "writer_version": REGISTER_WRITER_VERSION,
        "written_at": written_at or _utc_now(),
        "active_escalation_ids": deduped,
        "active_case_count": len(deduped),
    }

    register_path.parent.mkdir(parents=True, exist_ok=True)
    register_path.write_text(
        json.dumps(register, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return register


def assess_escalation_register(register_path: Path) -> dict[str, Any]:
    """
    Read and validate the escalation register.

    Returns:
      {
        "available": bool,
        "ok": bool,
        "trusted_writer": bool,
        "active_escalation_ids": list[str],
        "active_case_count": int,
        "escalation_active": bool,   # True if any active IDs listed
        "release_blocked": bool,
        "release_block_reasons": list[str],
      }

    Fail-closed: if register exists but writer_id is untrusted, ok=False.
    If register does not exist, available=False, ok=True (caller falls back to log).
    """
    if not register_path.is_file():
        return {
            "available": False,
            "ok": True,
            "trusted_writer": False,
            "active_escalation_ids": [],
            "active_case_count": 0,
            "escalation_active": False,
            "release_blocked": False,
            "release_block_reasons": [],
        }

    try:
        register = json.loads(register_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "available": True,
            "ok": False,
            "trusted_writer": False,
            "active_escalation_ids": [],
            "active_case_count": 0,
            "escalation_active": False,
            "release_blocked": True,
            "release_block_reasons": [f"register_unreadable:{exc}"],
        }

    trusted_writer = (
        register.get("writer_id") == REGISTER_WRITER_ID
        and register.get("writer_version") == REGISTER_WRITER_VERSION
        and register.get("register_schema") == REGISTER_SCHEMA
    )
    active_ids = list(register.get("active_escalation_ids") or [])
    escalation_active = len(active_ids) > 0

    reasons: list[str] = []
    if not trusted_writer:
        reasons.append("register_writer_untrusted")

    return {
        "available": True,
        "ok": trusted_writer,
        "trusted_writer": trusted_writer,
        "active_escalation_ids": active_ids,
        "active_case_count": len(active_ids),
        "escalation_active": escalation_active,
        "release_blocked": not trusted_writer,
        "release_block_reasons": reasons,
    }
