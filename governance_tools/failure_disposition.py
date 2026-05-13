#!/usr/bin/env python3
"""
Failure disposition classifier.

Classifies test failures by KIND (what type of failure this is) and
ACTION (what must happen before the agent can continue), distinct from
failure_test_validator.py which checks test *coverage*.

This module answers:  "I see a failing test — what do I do with it?"
failure_test_validator answers: "Do I have tests covering failure paths?"

Decision boundary semantics
---------------------------
- ignore_for_verdict    : failure does not block release verdict; log only
- test_fix_only         : test assertion is wrong; production code is correct
- production_fix_required : production code is wrong; agent must fix before
                            continuing
- escalate              : agent cannot self-classify or self-resolve; human
                          reviewer required before any action
- quarantine            : failure is temporarily excluded from verdict with
                          a registered justification and expiry; tracked

Unknown handling (conservative by design)
------------------------------------------
- Unknown failures default to `escalate`, never `ignore_for_verdict`
- Unknown failures appearing ≥ UNKNOWN_ESCALATION_THRESHOLD times trigger
  a taxonomy_expansion_candidate signal
- Reviewer confirmation is required to add a new FailureKind to the registry
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────

UNKNOWN_ESCALATION_THRESHOLD = 3  # consecutive unknowns before expansion signal

# ── Enumerations (as frozen string sets for lightweight portability) ──────────

FAILURE_KINDS = frozenset({
    "stale_assertion",      # test asserts old behaviour; production is correct
    "platform_mock",        # test uses platform-specific mock that breaks on CI
    "integration_drift",    # integration test is decoupled from current prod path
    "external_exclusion",   # depends on infra/external repo; intentionally excluded
    "unknown",              # cannot be classified with available signals
})

ACTION_POLICIES = frozenset({
    "ignore_for_verdict",
    "test_fix_only",
    "production_fix_required",
    "escalate",
    "quarantine",
})

CONFIDENCE_LEVELS = frozenset({
    "high",        # strong pattern match, reviewer can trust without re-reading
    "tentative",   # pattern match but ambiguous; reviewer should spot-check
    "unknown",     # no pattern matched or conflicting signals
})

# ── Default action per FailureKind ────────────────────────────────────────────
# Conservative defaults: when in doubt, escalate rather than ignore.

_KIND_DEFAULT_ACTION: dict[str, str] = {
    "stale_assertion":    "test_fix_only",
    "platform_mock":      "test_fix_only",
    "integration_drift":  "production_fix_required",
    "external_exclusion": "quarantine",
    "unknown":            "escalate",          # must NOT be ignore_for_verdict
}

# ── Classification patterns ───────────────────────────────────────────────────
# Each entry: (kind, confidence, [signal_patterns])
# Evaluated in order; first match wins.

_CLASSIFICATION_RULES: list[tuple[str, str, list[str]]] = [
    # external_exclusion — framework-known CI-exclusion paths
    ("external_exclusion", "high", [
        r"trust_signal",
        r"reviewer_handoff",
        r"governance_auditor",
        r"publication_reader",
        r"release_.*pipeline",
        r"failure_mode_test_matrix",
        r"governance_decision_model_v\d",
    ]),
    # stale_assertion — test name or message says "folder", "-folder", or old flag
    ("stale_assertion", "high", [
        r"folder_flag",
        r"includes_log_flag",
        r"includes_source_path",
        r"stale",
        r"old[_\- ]?assertion",
        r"deprecated[_\- ]?flag",
    ]),
    # platform_mock — mock of os.name / posix / PosixPath on Windows
    ("platform_mock", "high", [
        r"posix",
        r"posi[xX]path",
        r"macos.*exe.*detection",
        r"darwin.*exe",
        r"bundle.*binary",
        r"platform[_\- ]?mock",
        r"unsupportedoperation",
    ]),
    # integration_drift — integration test, mock call count is 0 when expected ≥1
    ("integration_drift", "high", [
        r"dfu[_\- ]?mode",
        r"dfu[_\- ]?sequence",
        r"run_dfu",
        r"integration.*drift",
        r"called.*0.*expected.*1",
        r"assert.*called.*once",
    ]),
    # stale_assertion tentative — loose signals
    ("stale_assertion", "tentative", [
        r"assert.*flag",
        r"assert.*arg",
        r"expected.*command",
    ]),
    # integration_drift tentative
    ("integration_drift", "tentative", [
        r"called_once",
        r"not_called",
        r"mock.*never",
    ]),
]


# ── Core data model ───────────────────────────────────────────────────────────

@dataclass
class DispositionResult:
    test_id: str
    kind: str                          # FailureKind
    action: str                        # ActionPolicy
    confidence: str                    # high | tentative | unknown
    matched_signals: list[str] = field(default_factory=list)
    reviewer_note: Optional[str] = None
    taxonomy_expansion_candidate: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BatchDispositionResult:
    total: int
    by_kind: dict[str, int]
    by_action: dict[str, int]
    by_confidence: dict[str, int]
    verdict_blocked: bool              # True if any failure requires production_fix or escalate
    unknown_count: int
    unknown_threshold: int             # threshold value that triggered taxonomy_expansion_signal
    taxonomy_expansion_signal: bool    # unknown_count >= unknown_threshold
    results: list[dict]

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ── Classification logic ──────────────────────────────────────────────────────

def classify_failure(test_id: str, *, extra_signals: Optional[list[str]] = None) -> DispositionResult:
    """
    Classify a single failing test by its identifier and optional extra signals
    (e.g. error message fragments, traceback keywords).

    Returns a DispositionResult with kind, action, confidence, and reviewer note.
    Unknown failures always map to action=escalate.
    """
    signals = [test_id.lower()]
    if extra_signals:
        signals.extend(s.lower() for s in extra_signals)
    combined = " ".join(signals)

    for kind, confidence, patterns in _CLASSIFICATION_RULES:
        matched = [p for p in patterns if re.search(p, combined, re.IGNORECASE)]
        if matched:
            action = _KIND_DEFAULT_ACTION[kind]
            note = _reviewer_note(kind, action, confidence)
            return DispositionResult(
                test_id=test_id,
                kind=kind,
                action=action,
                confidence=confidence,
                matched_signals=matched,
                reviewer_note=note,
            )

    # No pattern matched → unknown, conservative escalate
    return DispositionResult(
        test_id=test_id,
        kind="unknown",
        action="escalate",
        confidence="unknown",
        matched_signals=[],
        reviewer_note=(
            "No classification pattern matched. "
            "Agent must not self-resolve. Reviewer confirmation required."
        ),
    )


def classify_batch(
    test_ids: list[str],
    *,
    extra_signals_map: Optional[dict[str, list[str]]] = None,
) -> BatchDispositionResult:
    """
    Classify a list of failing test IDs.
    Emits taxonomy_expansion_signal when unknown count >= threshold.
    """
    extra_signals_map = extra_signals_map or {}
    results = []
    by_kind: dict[str, int] = {k: 0 for k in FAILURE_KINDS}
    by_action: dict[str, int] = {a: 0 for a in ACTION_POLICIES}
    by_confidence: dict[str, int] = {"high": 0, "tentative": 0, "unknown": 0}

    for tid in test_ids:
        r = classify_failure(tid, extra_signals=extra_signals_map.get(tid))
        results.append(r)
        by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
        by_action[r.action] = by_action.get(r.action, 0) + 1
        by_confidence[r.confidence] = by_confidence.get(r.confidence, 0) + 1
        if r.kind == "unknown":
            r.taxonomy_expansion_candidate = True

    unknown_count = by_kind.get("unknown", 0)
    verdict_blocked = (
        by_action.get("production_fix_required", 0) > 0
        or by_action.get("escalate", 0) > 0
    )

    return BatchDispositionResult(
        total=len(results),
        by_kind=by_kind,
        by_action=by_action,
        by_confidence=by_confidence,
        verdict_blocked=verdict_blocked,
        unknown_count=unknown_count,
        unknown_threshold=UNKNOWN_ESCALATION_THRESHOLD,
        taxonomy_expansion_signal=unknown_count >= UNKNOWN_ESCALATION_THRESHOLD,
        results=[r.to_dict() for r in results],
    )


# ── Reviewer note helpers ─────────────────────────────────────────────────────

def _reviewer_note(kind: str, action: str, confidence: str) -> str:
    notes = {
        "stale_assertion": (
            "Test assertion reflects removed/changed behaviour. "
            "Verify production code is intentionally changed, then update test."
        ),
        "platform_mock": (
            "Test uses platform-specific mock (e.g. os.name patching) that "
            "fails on the current OS. Update mock strategy to avoid PosixPath "
            "instantiation on Windows."
        ),
        "integration_drift": (
            "Integration test mock setup is decoupled from current production "
            "call path. Trace the actual entry point and re-anchor the mock."
        ),
        "external_exclusion": (
            "This test depends on external infrastructure or a separate repo. "
            "Exclusion is expected; verify the quarantine registry entry is "
            "current and has a valid expiry."
        ),
    }
    base = notes.get(kind, "")
    if confidence == "tentative":
        base += " [tentative classification — reviewer spot-check recommended]"
    return base


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify failing tests by disposition kind and action policy."
    )
    parser.add_argument(
        "--failures", nargs="+", metavar="TEST_ID",
        help="Space-separated failing test IDs",
    )
    parser.add_argument(
        "--file", metavar="PATH",
        help="JSON file: list of test IDs, or {test_id: [signals]} map",
    )
    parser.add_argument(
        "--format", choices=["human", "json"], default="human",
    )
    args = parser.parse_args()

    if not args.failures and not args.file:
        parser.error("Provide --failures or --file")

    test_ids: list[str] = []
    extra_signals_map: dict[str, list[str]] = {}

    if args.file:
        raw = json.loads(Path(args.file).read_text(encoding="utf-8"))
        if isinstance(raw, list):
            test_ids = [str(x) for x in raw]
        elif isinstance(raw, dict):
            for tid, sigs in raw.items():
                test_ids.append(tid)
                if isinstance(sigs, list):
                    extra_signals_map[tid] = [str(s) for s in sigs]
    if args.failures:
        test_ids.extend(args.failures)

    result = classify_batch(test_ids, extra_signals_map=extra_signals_map)

    if args.format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"[failure_disposition]")
        print(f"total={result.total}")
        print(f"verdict_blocked={result.verdict_blocked}")
        print(f"taxonomy_expansion_signal={result.taxonomy_expansion_signal}")
        print(f"unknown_count={result.unknown_count}")
        print()
        for r in result.results:
            print(
                f"  {r['test_id']}\n"
                f"    kind={r['kind']}  action={r['action']}  confidence={r['confidence']}"
            )
            if r.get("reviewer_note"):
                print(f"    note: {r['reviewer_note']}")

    sys.exit(1 if result.verdict_blocked else 0)


if __name__ == "__main__":
    main()
