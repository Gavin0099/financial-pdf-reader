"""
Lightweight assumption-check extraction for prompt/workflow observability.

This module is advisory-only. It never blocks execution.
"""

from __future__ import annotations

import re


_ASSUMPTION_MARKERS = (
    "assumption",
    "assumptions",
    "premise",
    "premises",
    "key premise",
    "前提",
    "假設",
)

_ALTERNATIVE_MARKERS = (
    "alternative_causes",
    "alternative causes",
    "alternative root cause",
    "alternative root causes",
    "alternative explanation",
    "alternative explanations",
    "替代 root cause",
    "替代原因",
    "其他可能原因",
)

_EVIDENCE_MARKERS = (
    "evidence",
    "supporting evidence",
    "證據",
    "依據",
)

_REFRAME_MARKERS = (
    "reframe",
    "validation step",
    "validate first",
    "改寫任務",
    "驗證步驟",
    "先驗證",
)

_ACTION_DECISION_RE = re.compile(
    r'"?action_decision"?\s*[:=]\s*"?(proceed|need_more_info|reframe)"?',
    re.IGNORECASE,
)

_ALTERNATIVE_LINE_RE = re.compile(
    r"(alternative|root cause|替代|其他可能原因)",
    re.IGNORECASE,
)

_MODIFICATION_MARKERS = (
    "implement",
    "implemented",
    "modify",
    "modified",
    "update",
    "updated",
    "patch",
    "patched",
    "delete",
    "deleted",
    "remove",
    "removed",
    "refactor",
    "fix",
    "fixed",
    "新增",
    "修改",
    "刪除",
    "重構",
    "修正",
)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def _count_alternative_lines(text: str) -> int:
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _ALTERNATIVE_LINE_RE.search(stripped):
            count += 1
    return count


def evaluate_assumption_check(text: str, *, require_action_decision: bool) -> dict:
    action_match = _ACTION_DECISION_RE.search(text or "")
    action_decision = action_match.group(1).lower() if action_match else None

    assumptions_present = _contains_any(text, _ASSUMPTION_MARKERS)
    alternatives_present = _contains_any(text, _ALTERNATIVE_MARKERS)
    alternatives_count = _count_alternative_lines(text)
    evidence_present = _contains_any(text, _EVIDENCE_MARKERS)
    reframe_present = _contains_any(text, _REFRAME_MARKERS)

    missing: list[str] = []
    if not assumptions_present:
        missing.append("assumptions")
    if not alternatives_present:
        missing.append("alternative_root_causes")
    if not evidence_present:
        missing.append("evidence")
    if not reframe_present:
        missing.append("reframe_or_validation_step")
    if require_action_decision and action_decision is None:
        missing.append("action_decision")

    return {
        "present": assumptions_present or alternatives_present or evidence_present or reframe_present or action_decision is not None,
        "assumptions_present": assumptions_present,
        "alternatives_present": alternatives_present,
        "alternatives_count": alternatives_count,
        "evidence_present": evidence_present,
        "reframe_present": reframe_present,
        "action_decision": action_decision,
        "complete": len(missing) == 0,
        "missing": missing,
    }


def has_modification_intent(text: str) -> bool:
    return _contains_any(text or "", _MODIFICATION_MARKERS)
