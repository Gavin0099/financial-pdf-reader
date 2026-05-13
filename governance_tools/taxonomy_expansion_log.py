"""
taxonomy_expansion_log.py — Remediation trace substrate for taxonomy_expansion_signal.

When `taxonomy_expansion_signal=True` fires in a session, the session_end_hook
writes one entry here with review_status="pending".  Operators update the entry
fields manually (or via a future write-back tool) to leave a closure trace.

Authority:
  - This log is advisory-only.  Its contents do not affect gate decisions.
  - A "pending" entry does NOT block anything — it is a visibility record.
  - The log exists so that repeated unreviewed signals accumulate visibly
    instead of silently disappearing each session.
  - write failure -> warning only; session gate must not be affected.
  - This substrate is NOT a strong authority. It is a traceability aid.
    Do not make gate decisions based on log contents.

Storage: <project_root>/governance/taxonomy_expansion_log.ndjson
  One JSON object per line.  Transitions rewrite the file in-place
  (governance data is small; rewrite is safe and avoids tombstone complexity).

Entry schema:
  session_id:       str   — matches session_end_hook session_id
  timestamp_utc:    str   — ISO 8601 UTC
  unknown_count:    int   — unknown failures in the session that triggered signal
  unknown_threshold: int  — threshold value that classified the count as expansion signal
  review_status:    str   — "pending" | "reviewed" | "updated" | "dismissed"
                            default = "pending" on write
  review_note:      str | None  — free-form operator annotation
  review_evidence:  str | None  — path or URL to supporting evidence
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_LOG_RELPATH = Path("governance") / "taxonomy_expansion_log.ndjson"

REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_REVIEWED = "reviewed"
REVIEW_STATUS_UPDATED = "updated"
REVIEW_STATUS_DISMISSED = "dismissed"

VALID_REVIEW_STATUSES = frozenset({
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_REVIEWED,
    REVIEW_STATUS_UPDATED,
    REVIEW_STATUS_DISMISSED,
})


def _log_path(project_root: Path) -> Path:
    return project_root / _LOG_RELPATH


def append_pending_entry(
    project_root: Path,
    session_id: str,
    unknown_count: int,
    unknown_threshold: int,
) -> dict:
    """
    Append one 'pending' remediation trace entry to the log file.

    Returns the dict that was written (so callers can include it in result output).
    The log directory is created if absent.  Raises on write error (caller decides
    how to handle — session_end_hook wraps in try/except to stay non-blocking).
    """
    entry = {
        "session_id": session_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "unknown_count": unknown_count,
        "unknown_threshold": unknown_threshold,
        "review_status": REVIEW_STATUS_PENDING,
        "review_note": None,
        "review_evidence": None,
    }
    log_file = _log_path(project_root)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_log(project_root: Path) -> list[dict]:
    """
    Read all entries from the log.  Returns an empty list if the file does not
    exist or is empty.  Malformed lines are skipped silently.
    """
    log_file = _log_path(project_root)
    if not log_file.exists():
        return []
    entries = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def list_pending(project_root: Path) -> list[dict]:
    """Return only entries where review_status == 'pending'."""
    return [e for e in read_log(project_root) if e.get("review_status") == REVIEW_STATUS_PENDING]


def update_entry_status(
    project_root: Path,
    session_id: str,
    new_status: str,
    *,
    review_note: str | None = None,
    review_evidence: str | None = None,
) -> dict | None:
    """
    Transition the review_status of the entry matching session_id.

    Returns the updated entry dict on success.
    Returns None if no entry with that session_id is found (not an error).
    Raises ValueError if new_status is not a recognised review status, or if
    the close path evidence expectation is not met (see below).

    Close-path evidence expectations (F4.6):
      reviewed  — at least review_note OR review_evidence must be non-empty
      updated   — review_evidence must be non-empty (path/ref of updated taxonomy)
      dismissed — review_note must be non-empty (reason for dismissal)

    The expectation is evaluated against the *resultant* entry state after
    applying the supplied values, so passing a note on an entry that already
    has evidence also satisfies the 'reviewed' requirement.

    Implementation: read-modify-rewrite.  The log file is small governance data;
    full rewrite avoids tombstone complexity and keeps read_log() simple.

    Authority note: this function modifies the traceability substrate only.
    It has no effect on gate decisions — the log is advisory, not authority.
    """
    if new_status not in VALID_REVIEW_STATUSES:
        raise ValueError(
            f"Invalid review_status {new_status!r}. "
            f"Must be one of: {sorted(VALID_REVIEW_STATUSES)}"
        )

    entries = read_log(project_root)
    updated_entry: dict | None = None

    for entry in entries:
        if entry.get("session_id") == session_id:
            entry["review_status"] = new_status
            if review_note is not None:
                entry["review_note"] = review_note
            if review_evidence is not None:
                entry["review_evidence"] = review_evidence
            updated_entry = entry
            break  # session_id is treated as unique; update first match only

    if updated_entry is None:
        return None

    # F4.6: close-path evidence expectation — checked AFTER applying new values,
    # BEFORE writing.  If the requirement is not met, raise without modifying the file.
    _check_close_path_evidence(updated_entry)

    # Rewrite the file atomically enough for governance data (not high-volume).
    log_file = _log_path(project_root)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return updated_entry


def _check_close_path_evidence(entry: dict) -> None:
    """
    Enforce minimum evidence expectations for close-path transitions.

    Raises ValueError describing what is missing.
    Only fires for reviewed, updated, and dismissed statuses.
    pending has no evidence requirement (it is the initial state, not a close).
    """
    status = entry.get("review_status")
    note = entry.get("review_note") or ""
    evidence = entry.get("review_evidence") or ""

    if status == REVIEW_STATUS_DISMISSED:
        if not note.strip():
            raise ValueError(
                "dismissed requires review_note — "
                "provide a reason so the dismissal is traceable "
                "(e.g. 'confirmed test infrastructure issue, not a taxonomy gap')"
            )
    elif status == REVIEW_STATUS_UPDATED:
        if not evidence.strip():
            raise ValueError(
                "updated requires review_evidence — "
                "provide the path or reference of the updated taxonomy/corpus "
                "(e.g. 'governance/data/failure_disposition_corpus.json')"
            )
    elif status == REVIEW_STATUS_REVIEWED:
        if not note.strip() and not evidence.strip():
            raise ValueError(
                "reviewed requires at least review_note or review_evidence — "
                "provide one to make the review traceable"
            )
