#!/usr/bin/env python3
"""
Framework Risk Signal — stateful governance defense layer.

Writes/reads/clears a short-lived JSON signal that records when a framework
self-check detects critical drift failures.  session_start reads this signal
and defensively upgrades behavior (e.g. forces L0 → L1 when task-level
detection is known-compromised).

Design constraints:
  1. Signal only upgrades defense — never changes rules or overrides policy.
  2. Signal decays automatically: 48-hour time-based expiry, plus CI-pass
     event-based clear (governance_drift_checker calls clear_risk_signal
     when all critical checks pass).
  3. Signal is always visible: session_start must show a prominent warning
     when the signal is active.

Signal file location:
    {framework_root}/artifacts/runtime/framework_risk_signal.json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

# ── Known components (limited enum) ─────────────────────────────────────────
# Only components whose failure has a concrete, tested behavioral override.
# Extending this set requires a corresponding entry in COMPONENT_OVERRIDES
# and a test that covers the new override path.

KNOWN_COMPONENTS: frozenset[str] = frozenset({
    "task_level_detection",
    "domain_contract_loading",
    "summary_first_gate",
    "rule_selection",
    "runtime_enforcement_entrypoint",
    "runtime_enforcement_quality_trend",
    "drift_baseline_integrity",
})

# ── Component → protective override mapping ──────────────────────────────────
# Each entry describes what session_start should do when that component is
# affected.  "min_task_level": "L1" prevents L0 cold-start, which is the
# highest-coverage single override: it ensures at minimum a full L1 context
# is built even if task detection would otherwise allow the cheaper L0 path.

COMPONENT_OVERRIDES: dict[str, dict] = {
    "task_level_detection":         {"min_task_level": "L1"},
    "domain_contract_loading":      {"min_task_level": "L1", "disable_summary_first": True},
    "summary_first_gate":           {"min_task_level": "L1", "disable_summary_first": True},
    "rule_selection":               {"min_task_level": "L1"},
    "runtime_enforcement_entrypoint": {"min_task_level": "L1"},
    "runtime_enforcement_quality_trend": {"min_task_level": "L1"},
    "drift_baseline_integrity":     {"min_task_level": "L1"},
}

_SIGNAL_RELPATH = Path("artifacts") / "runtime" / "framework_risk_signal.json"
_DEFAULT_MAX_AGE_HOURS = 48
_SIGNAL_VERSION = 1


def _signal_path(framework_root: Path) -> Path:
    return framework_root / _SIGNAL_RELPATH


# ── Write ────────────────────────────────────────────────────────────────────

def write_risk_signal(
    framework_root: Path,
    affected_components: list[str],
    severity: str,
    source: str,
) -> Path:
    """
    Write (or overwrite) the framework risk signal file.

    Only components in KNOWN_COMPONENTS are recorded; unknown names are silently
    filtered so a future check-name rename cannot accidentally corrupt the signal.

    Returns the path of the written signal file.
    """
    known_affected = [c for c in affected_components if c in KNOWN_COMPONENTS]
    signal: dict = {
        "version": _SIGNAL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "severity": severity,
        "affected_components": known_affected,
        "source": source,
        "repo_scope": "framework",
    }
    path = _signal_path(framework_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(signal, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ── Read ─────────────────────────────────────────────────────────────────────

def read_risk_signal(
    framework_root: Path,
    max_age_hours: int = _DEFAULT_MAX_AGE_HOURS,
) -> dict | None:
    """
    Read the framework risk signal, returning None if:
      - The file does not exist
      - The signal has expired (older than max_age_hours)
      - The file is malformed / unparseable
      - repo_scope is not "framework" (guards against cross-contamination)
      - version does not match _SIGNAL_VERSION

    An expired-but-present file is left on disk; the caller decides whether
    to clean it up.  clear_risk_signal() removes it explicitly.
    """
    path = _signal_path(framework_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # Scope guard: only consume signals written for the framework itself.
    if data.get("repo_scope") != "framework":
        return None

    # Version guard: ignore future incompatible formats.
    if data.get("version") != _SIGNAL_VERSION:
        return None

    # Expiry check.
    generated_at_str = data.get("generated_at", "")
    try:
        generated_at = datetime.fromisoformat(generated_at_str)
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - generated_at).total_seconds() / 3600
        if age_hours > max_age_hours:
            return None
    except ValueError:
        return None

    return data


# ── Clear ────────────────────────────────────────────────────────────────────

def clear_risk_signal(framework_root: Path) -> bool:
    """
    Delete the framework risk signal file.

    Returns True if a file was deleted, False if it did not exist.
    Called by governance_drift_checker when all critical checks pass (CI-pass
    event-based decay).
    """
    path = _signal_path(framework_root)
    if path.exists():
        try:
            path.unlink()
            return True
        except OSError:
            return False
    return False


def clear_risk_signal_for_source(framework_root: Path, source: str) -> bool:
    """
    Delete the framework risk signal only when it belongs to the given source.

    This lets a producer clear its own stale signal without erasing a newer
    signal from a different source while the framework still uses a single-file
    substrate.
    """
    path = _signal_path(framework_root)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if data.get("source") != source:
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


# ── Compute overrides ────────────────────────────────────────────────────────

def compute_overrides(signal: dict | None) -> dict:
    """
    Given an active risk signal (from read_risk_signal), compute the merged
    set of protective overrides that session_start should apply.

    Returns an empty dict when signal is None (no active risk → no overrides).

    Current override keys:
      "min_task_level": "L1"   — prevent L0 cold-start
    """
    if signal is None:
        return {}

    merged: dict = {}
    for component in signal.get("affected_components", []):
        component_override = COMPONENT_OVERRIDES.get(component, {})
        for key, value in component_override.items():
            if key == "min_task_level":
                # Conservative merge: take the highest-protection level.
                current = merged.get(key)
                if current is None or _level_rank(value) > _level_rank(current):
                    merged[key] = value
            elif key == "disable_summary_first":
                # Boolean OR — any component requiring this wins.
                merged[key] = merged.get(key, False) or value
            else:
                merged[key] = value
    return merged


def _level_rank(level: str) -> int:
    return {"L0": 0, "L1": 1, "L2": 2}.get(level, 0)
