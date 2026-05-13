#!/usr/bin/env python3
"""
Phase C Slice 1 runtime helper: lifecycle transition authority checks.

Scope:
- enforce illegal transition rejection (including active -> resolved_confirmed)
- enforce no auto-write for resolved_confirmed
- define release-unblock boundary (only resolved_confirmed may unblock)
"""

from __future__ import annotations

from typing import Any


LIFECYCLE_STATES = {
    "created",
    "active",
    "superseded",
    "resolved_provisional",
    "resolved_confirmed",
    "invalidated",
    "archived",
}

ALLOWED_TRANSITIONS = {
    ("created", "active"),
    ("active", "superseded"),
    ("active", "resolved_provisional"),
    ("resolved_provisional", "resolved_confirmed"),
    ("active", "invalidated"),
    ("superseded", "archived"),
    ("resolved_provisional", "archived"),
    ("resolved_confirmed", "archived"),
    ("invalidated", "archived"),
}


def state_can_unblock_release(state: str) -> bool:
    return state == "resolved_confirmed"


def validate_lifecycle_transition(
    *,
    from_state: str,
    to_state: str,
    actor: str,
    auto: bool,
) -> dict[str, Any]:
    errors: list[str] = []

    if from_state not in LIFECYCLE_STATES:
        errors.append("from_state_invalid")
    if to_state not in LIFECYCLE_STATES:
        errors.append("to_state_invalid")

    if errors:
        return {
            "ok": False,
            "errors": errors,
            "release_unblock_allowed": False,
        }

    if (from_state, to_state) not in ALLOWED_TRANSITIONS:
        errors.append("transition_not_allowed")

    # Phase C Slice 1 hard boundary: no direct active -> resolved_confirmed
    if from_state == "active" and to_state == "resolved_confirmed":
        errors.append("active_to_resolved_confirmed_forbidden")

    # Phase C Slice 1 hard boundary: auto write to resolved_confirmed is forbidden.
    if to_state == "resolved_confirmed" and auto:
        errors.append("resolved_confirmed_auto_write_forbidden")

    # Phase C Slice 1 hard boundary: author_provisional cannot confirm resolution.
    if to_state == "resolved_confirmed" and actor == "author_provisional":
        errors.append("author_provisional_cannot_confirm_resolution")

    # Optional policy tightening: resolved_confirmed requires reviewer actor.
    if to_state == "resolved_confirmed" and actor not in {"reviewer_confirmed", "reviewer"}:
        errors.append("resolved_confirmed_requires_reviewer_confirmation")

    ok = len(errors) == 0
    return {
        "ok": ok,
        "errors": errors,
        "release_unblock_allowed": ok and state_can_unblock_release(to_state),
    }
