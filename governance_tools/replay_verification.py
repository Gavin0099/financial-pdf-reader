#!/usr/bin/env python3
"""
replay_verification.py — E6 re-runnable decision-path evidence tool.

Replays every case in the failure disposition corpus against the live
classifier and evaluates two independent match layers:

  Layer 1 — Classification correctness
      Does the classifier produce the expected kind / action / confidence?

  Layer 2 — Gate-effect correctness
      Does the classifier output produce the expected gate-blocking outcome?
      (expected_gate_blocking field in corpus, evaluated against gate policy)

Evidence is written to:
  artifacts/runtime/replay-evidence/latest.json   (machine-readable)
  stdout                                            (human-readable summary)

Usage:
  python governance_tools/replay_verification.py
  python governance_tools/replay_verification.py --format json
  python governance_tools/replay_verification.py --out path/to/result.json
  python governance_tools/replay_verification.py --corpus tests/fixtures/failure_disposition_corpus.json

Exit codes:
  0 — all corpus cases match (both layers)
  1 — one or more mismatches detected
  2 — corpus could not be loaded
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Path bootstrap ────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CORPUS = _REPO_ROOT / "tests" / "fixtures" / "failure_disposition_corpus.json"
_DEFAULT_ARTIFACT_DIR = _REPO_ROOT / "artifacts" / "runtime" / "replay-evidence"

# Add repo root to sys.path so governance_tools imports work when run directly.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from governance_tools.failure_disposition import classify_failure  # noqa: E402
from governance_tools.gate_policy import load_policy              # noqa: E402

# ── Data types ────────────────────────────────────────────────────────────────


@dataclass
class CaseResult:
    case_id: str
    test_id: str

    # Layer 1 — classification
    expected_kind: str
    actual_kind: str
    kind_match: bool

    expected_action: str
    actual_action: str
    action_match: bool

    expected_confidence: str
    actual_confidence: str
    confidence_match: bool

    expected_note_fragment: str
    actual_note: str
    note_match: bool

    classification_match: bool      # all four fields above agree

    # Layer 2 — gate effect
    expected_gate_blocking: bool    # ground truth from corpus
    actual_gate_blocking: bool      # derived: actual_action in policy.blocking_actions
    gate_effect_match: bool

    # Source provenance from corpus
    source: str
    added_by: str
    added_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReplayEvidence:
    """Top-level evidence artifact produced by replay_verification.py."""

    # Corpus metadata
    corpus_path: str
    corpus_schema_version: str
    corpus_version: str
    corpus_case_count: int
    corpus_provenance: dict

    # Policy provenance
    policy_source: str
    policy_path: str
    blocking_actions: list[str]

    # Per-case results
    cases: list[CaseResult]

    # Summary
    classification_match_count: int
    classification_match_rate: str   # "N/M"
    gate_effect_match_count: int
    gate_effect_match_rate: str      # "N/M"
    mismatch_cases: list[dict]       # {case_id, layer, expected, actual}
    unknown_count: int
    taxonomy_expansion_signal: bool

    # Evidence scope statement (precise — must not overclaim)
    evidence_scope: str

    # Timestamp
    generated_at: str

    # Overall pass/fail
    all_match: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ── Corpus loading ────────────────────────────────────────────────────────────


def _load_corpus(corpus_path: Path) -> tuple[list[dict], str, str, dict]:
    """Return (cases, schema_version, corpus_version, provenance) from corpus file."""
    raw = json.loads(corpus_path.read_text(encoding="utf-8"))

    # The first element may be a metadata object (contains _schema key).
    # All subsequent elements (or all elements without _schema) are cases.
    if not raw:
        return [], "unknown", "unknown", {}

    first = raw[0]
    schema_version = first.get("_schema", "failure_disposition_corpus_v1")
    corpus_version = first.get("_corpus_version", "unknown")
    provenance = first.get("_ground_truth_provenance", {})

    cases = [e for e in raw if not any(k.startswith("_") for k in e)]
    return cases, schema_version, corpus_version, provenance


# ── Per-case evaluation ───────────────────────────────────────────────────────


def _evaluate_case(case: dict, blocking_actions: list[str]) -> CaseResult:
    test_id = case["case_id"]  # used as display key
    test_id_for_classifier = case["test_id"]
    extra = case.get("extra_signals", [])

    result = classify_failure(test_id_for_classifier, extra_signals=extra)

    # Layer 1
    exp_kind = case["expected_kind"]
    exp_action = case["expected_action"]
    exp_conf = case["expected_confidence"]
    exp_note = case.get("expected_reviewer_note_contains", "")

    kind_match = result.kind == exp_kind
    action_match = result.action == exp_action
    confidence_match = result.confidence == exp_conf
    note_match = exp_note.lower() in (result.reviewer_note or "").lower() if exp_note else True
    classification_match = kind_match and action_match and confidence_match and note_match

    # Layer 2
    exp_gate = case.get("expected_gate_blocking", exp_action in blocking_actions)
    actual_gate = result.action in blocking_actions
    gate_effect_match = exp_gate == actual_gate

    return CaseResult(
        case_id=case["case_id"],
        test_id=test_id_for_classifier,
        expected_kind=exp_kind,
        actual_kind=result.kind,
        kind_match=kind_match,
        expected_action=exp_action,
        actual_action=result.action,
        action_match=action_match,
        expected_confidence=exp_conf,
        actual_confidence=result.confidence,
        confidence_match=confidence_match,
        expected_note_fragment=exp_note,
        actual_note=result.reviewer_note or "",
        note_match=note_match,
        classification_match=classification_match,
        expected_gate_blocking=exp_gate,
        actual_gate_blocking=actual_gate,
        gate_effect_match=gate_effect_match,
        source=case.get("source", ""),
        added_by=case.get("added_by", ""),
        added_at=case.get("added_at", ""),
    )


# ── Replay runner ─────────────────────────────────────────────────────────────


def run_replay(
    corpus_path: Path | None = None,
    policy_path: Path | None = None,
) -> ReplayEvidence:
    """Run full replay and return structured evidence."""
    corpus_path = corpus_path or _DEFAULT_CORPUS

    cases_raw, schema_version, corpus_version, provenance = _load_corpus(corpus_path)

    policy = load_policy(path=policy_path) if policy_path else load_policy()
    blocking_actions = policy.blocking_actions

    case_results: list[CaseResult] = []
    for c in cases_raw:
        case_results.append(_evaluate_case(c, blocking_actions))

    total = len(case_results)
    classification_matched = sum(1 for r in case_results if r.classification_match)
    gate_matched = sum(1 for r in case_results if r.gate_effect_match)
    unknown_count = sum(1 for r in case_results if r.actual_kind == "unknown")

    # Collect mismatch detail
    mismatches: list[dict] = []
    for r in case_results:
        if not r.classification_match:
            mismatches.append({
                "case_id": r.case_id,
                "layer": "classification",
                "expected": {
                    "kind": r.expected_kind,
                    "action": r.expected_action,
                    "confidence": r.expected_confidence,
                    "note_fragment": r.expected_note_fragment,
                },
                "actual": {
                    "kind": r.actual_kind,
                    "action": r.actual_action,
                    "confidence": r.actual_confidence,
                    "note": r.actual_note,
                },
            })
        if not r.gate_effect_match:
            mismatches.append({
                "case_id": r.case_id,
                "layer": "gate_effect",
                "expected": {"gate_blocking": r.expected_gate_blocking},
                "actual": {"gate_blocking": r.actual_gate_blocking, "action": r.actual_action},
            })

    all_match = total > 0 and classification_matched == total and gate_matched == total

    evidence_scope = (
        f"For current seed corpus ({total} cases, schema {schema_version}, "
        f"version {corpus_version}), classifier output matches human analysis "
        f"on classification ({classification_matched}/{total}) and gate-effect "
        f"({gate_matched}/{total}) layers. "
        "Scope is limited to seed corpus only — does not assert correctness beyond labelled cases."
    )

    return ReplayEvidence(
        corpus_path=str(corpus_path),
        corpus_schema_version=schema_version,
        corpus_version=corpus_version,
        corpus_case_count=total,
        corpus_provenance=provenance,
        policy_source=policy.policy_source,
        policy_path=policy.policy_path,
        blocking_actions=blocking_actions,
        cases=case_results,
        classification_match_count=classification_matched,
        classification_match_rate=f"{classification_matched}/{total}",
        gate_effect_match_count=gate_matched,
        gate_effect_match_rate=f"{gate_matched}/{total}",
        mismatch_cases=mismatches,
        unknown_count=unknown_count,
        taxonomy_expansion_signal=unknown_count >= 3,
        evidence_scope=evidence_scope,
        generated_at=datetime.now(timezone.utc).isoformat(),
        all_match=all_match,
    )


# ── Output formatters ─────────────────────────────────────────────────────────


def _format_human(ev: ReplayEvidence) -> str:
    lines: list[str] = []
    w = lines.append

    w("=" * 70)
    w("  Failure Disposition Replay Verification")
    w("=" * 70)
    w(f"  Corpus          : {ev.corpus_path}")
    w(f"  Schema version  : {ev.corpus_schema_version}")
    w(f"  Corpus version  : {ev.corpus_version}")
    w(f"  Cases           : {ev.corpus_case_count}")
    w(f"  Policy source   : {ev.policy_source}  ({ev.policy_path or 'builtin'})")
    w(f"  Blocking actions: {', '.join(ev.blocking_actions)}")
    w("")
    if ev.corpus_provenance:
        w("  Ground truth provenance:")
        for k, v in ev.corpus_provenance.items():
            w(f"    {k}: {v}")
    w("")
    w("-" * 70)
    w("  Per-case results")
    w("-" * 70)
    for r in ev.cases:
        c_icon = "OK" if r.classification_match else "!!"
        g_icon = "OK" if r.gate_effect_match else "!!"
        w(f"  [{c_icon}] [{g_icon}]  {r.case_id}")
        if not r.classification_match:
            w(f"           classification MISMATCH:")
            if not r.kind_match:
                w(f"             kind:   expected={r.expected_kind!r}  actual={r.actual_kind!r}")
            if not r.action_match:
                w(f"             action: expected={r.expected_action!r}  actual={r.actual_action!r}")
            if not r.confidence_match:
                w(f"             conf:   expected={r.expected_confidence!r}  actual={r.actual_confidence!r}")
            if not r.note_match:
                w(f"             note fragment not found in reviewer_note")
        if not r.gate_effect_match:
            w(f"           gate_effect MISMATCH:")
            w(f"             expected_gate_blocking={r.expected_gate_blocking}  actual={r.actual_gate_blocking}")

    w("")
    w("-" * 70)
    w("  Summary")
    w("-" * 70)
    w(f"  Classification match rate : {ev.classification_match_rate}")
    w(f"  Gate-effect match rate    : {ev.gate_effect_match_rate}")
    w(f"  Unknown classifications   : {ev.unknown_count}")
    if ev.taxonomy_expansion_signal:
        w("  [WARN] taxonomy_expansion_signal: unknown_count >= 3 — review taxonomy coverage")
    if ev.mismatch_cases:
        w(f"  [FAIL] {len(ev.mismatch_cases)} mismatch(es) detected")
    w("")
    w("  Evidence scope:")
    w(f"  {ev.evidence_scope}")
    w("")
    w("  Result: " + ("PASS — all corpus cases match" if ev.all_match else "FAIL — mismatch(es) detected"))
    w("=" * 70)

    return "\n".join(lines)


# ── Artifact writer ───────────────────────────────────────────────────────────


def _write_artifact(ev: ReplayEvidence, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(ev.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )


# ── CLI ───────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Replay failure disposition corpus against live classifier."
    )
    p.add_argument(
        "--corpus",
        type=Path,
        default=None,
        help=f"Path to corpus JSON (default: {_DEFAULT_CORPUS})",
    )
    p.add_argument(
        "--policy",
        type=Path,
        default=None,
        help="Path to gate_policy.yaml (default: framework discovery order)",
    )
    p.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Write machine-readable JSON artifact to this path. "
            f"Default when format=human: {_DEFAULT_ARTIFACT_DIR}/latest.json"
        ),
    )
    p.add_argument(
        "--no-artifact",
        action="store_true",
        help="Skip writing the JSON artifact to disk (stdout only).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        ev = run_replay(corpus_path=args.corpus, policy_path=args.policy)
    except FileNotFoundError as exc:
        print(f"[replay_verification] ERROR: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"[replay_verification] ERROR: corpus JSON parse error — {exc}", file=sys.stderr)
        return 2

    # Output
    if args.format == "json":
        print(json.dumps(ev.to_dict(), indent=2, default=str))
    else:
        print(_format_human(ev))

    # Artifact
    if not args.no_artifact:
        artifact_path = args.out or (_DEFAULT_ARTIFACT_DIR / "latest.json")
        _write_artifact(ev, artifact_path)
        if args.format == "human":
            print(f"\n  Artifact written: {artifact_path}")

    return 0 if ev.all_match else 1


if __name__ == "__main__":
    sys.exit(main())
