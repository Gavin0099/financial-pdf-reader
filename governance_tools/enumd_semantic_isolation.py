#!/usr/bin/env python3
"""
Semantic isolation layer for Enumd runtime artifacts.

Supports three probe modes:
  candidate       — runtime session candidates (policy.decision, repo_readiness_level, …)
  closeout        — session closeout artifacts (closeout_status, narrative fields)
  memory-candidate — memory promotion candidates (risk, oversight, status)

Batch conclusions (candidate mode):
  observe_only_safe                    — no authority-like fields detected
  observe_only_with_inducement_risk    — occasional authority-like fields
  observe_only_with_semantic_collision — systematic high-collision fields (>= 50% of batch)

Narrative risk delta (closeout mode):
  amplified   — closeout adds narrative that wraps candidate decision-shaped signals
  maintained  — closeout has authority-like fields but no narrative amplification
  reduced     — closeout is null/empty; decision-shaped signals not narrativized
  neutral     — closeout has no authority-like fields and no candidate to compare
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
ARTIFACT_TYPE = "enumd-semantic-isolation-probe"

# Non-equivalence registry: Enumd field path → semantic annotation.
# Key format: dot-notation path into the candidate JSON (e.g. "policy.decision").
_NON_EQUIVALENCE_REGISTRY: dict[str, dict[str, Any]] = {
    "policy.decision": {
        "family": "promotion_like",
        "actual_scope": "session_memory_promotion",
        "misread_scope": "repo_integration_decision",
        "decision_shaped": True,
        "reinterpretation_required": True,
        "non_equivalence": "policy.decision != framework verdict.decision",
        "collision_risk": "high",
    },
    "checks.repo_readiness_level": {
        "family": "numeric_threshold",
        "actual_scope": "closeout_completeness_proxy",
        "misread_scope": "integration_readiness_gate",
        "decision_shaped": True,
        "reinterpretation_required": True,
        "non_equivalence": "repo_readiness_level != readiness_gate",
        "collision_risk": "medium",
    },
    "checks.closeout_schema_validity": {
        "family": "binary_verdict",
        "actual_scope": "artifact_file_presence_and_structure",
        "misread_scope": "governance_validity",
        "decision_shaped": True,
        "reinterpretation_required": True,
        "non_equivalence": "closeout_schema_validity != governance_validity",
        "collision_risk": "medium",
    },
    "checks.closeout_content_sufficiency": {
        "family": "binary_verdict",
        "actual_scope": "artifact_file_content_completeness",
        "misread_scope": "governance_content_sufficiency",
        "decision_shaped": True,
        "reinterpretation_required": True,
        "non_equivalence": "closeout_content_sufficiency != governance_content_sufficiency",
        "collision_risk": "low",
    },
    "checks.repo_closeout_activation_state": {
        "family": "state_machine",
        "actual_scope": "session_activation_lifecycle",
        "misread_scope": "integration_activation_status",
        "decision_shaped": True,
        "reinterpretation_required": True,
        "non_equivalence": "repo_closeout_activation_state != integration_activation_status",
        "collision_risk": "low",
    },
}

_HIGH_COLLISION_FIELDS = {k for k, v in _NON_EQUIVALENCE_REGISTRY.items() if v["collision_risk"] == "high"}

# Closeout-specific registry.  Closeout schema is much narrower:
# most narrative fields (task_intent, work_summary, etc.) are null in all observed samples,
# so only the status field carries any authority-like representation.
_CLOSEOUT_NON_EQUIVALENCE_REGISTRY: dict[str, dict[str, Any]] = {
    "closeout_status": {
        "family": "binary_verdict",
        "actual_scope": "session_closeout_file_presence",
        "misread_scope": "governance_session_status",
        "decision_shaped": True,
        "reinterpretation_required": True,
        "non_equivalence": "closeout_status != governance session status",
        "collision_risk": "low",
    },
}

# Memory-candidate registry.  These artifacts use a different schema (no policy.decision).
# risk/oversight/status are documentation metadata, not decision signals.
_MEMORY_CANDIDATE_NON_EQUIVALENCE_REGISTRY: dict[str, dict[str, Any]] = {
    "risk": {
        "family": "categorical_risk_label",
        "actual_scope": "session_risk_documentation",
        "misread_scope": "integration_risk_gate",
        "decision_shaped": False,
        "reinterpretation_required": False,
        "non_equivalence": "risk field is documentation metadata, not a gate",
        "collision_risk": "low",
    },
    "oversight": {
        "family": "oversight_label",
        "actual_scope": "session_oversight_documentation",
        "misread_scope": "governance_oversight_requirement",
        "decision_shaped": False,
        "reinterpretation_required": False,
        "non_equivalence": "oversight field is documentation metadata, not a requirement signal",
        "collision_risk": "low",
    },
    "status": {
        "family": "workflow_state",
        "actual_scope": "memory_promotion_workflow_state",
        "misread_scope": "governance_artifact_status",
        "decision_shaped": False,
        "reinterpretation_required": False,
        "non_equivalence": "status=candidate is a workflow position, not a governance verdict",
        "collision_risk": "low",
    },
}


def _get_nested(data: dict, dotpath: str) -> tuple[bool, Any]:
    """Return (exists, value) for a dot-notation path."""
    parts = dotpath.split(".")
    cur: Any = data
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _classify_ingestion_valid(candidate: dict) -> bool:
    """A candidate is ingestion-valid only if it has no missing_fields and boundary passes."""
    checks = candidate.get("checks") or {}
    missing = checks.get("closeout_per_layer_results", {}).get("missing_fields", [])
    errors = candidate.get("errors") or []
    return len(missing) == 0 and len(errors) == 0


def _classify_boundary_status(candidate: dict) -> str:
    """Pass unless explicit boundary_fail signal."""
    errors = candidate.get("errors") or []
    for e in errors:
        if isinstance(e, dict) and "boundary_fail" in str(e).lower():
            return "fail"
        if isinstance(e, str) and "boundary_fail" in e.lower():
            return "fail"
    return "pass"


@dataclass
class AuthorityLikeField:
    field: str
    family: str
    actual_scope: str
    misread_scope: str
    reinterpretation_required: bool
    collision_risk: str
    observed_value: Any
    non_equivalence: str

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "family": self.family,
            "actual_scope": self.actual_scope,
            "misread_scope": self.misread_scope,
            "reinterpretation_required": self.reinterpretation_required,
            "collision_risk": self.collision_risk,
            "observed_value": self.observed_value,
            "non_equivalence": self.non_equivalence,
        }


@dataclass
class SampleProbeResult:
    sample_id: str
    source_path: str
    ingestion_valid: bool
    boundary_status: str
    runtime_eligible_result: str
    inducement_risk: str
    misread_risk: str
    authority_like_fields: list[AuthorityLikeField] = field(default_factory=list)
    semantic_isolation_applied: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "sample_id": self.sample_id,
            "source_path": self.source_path,
            "ingestion_valid": self.ingestion_valid,
            "boundary_status": self.boundary_status,
            "runtime_eligible_result": self.runtime_eligible_result,
            "inducement_risk": self.inducement_risk,
            "misread_risk": self.misread_risk,
            "authority_like_fields": [f.to_dict() for f in self.authority_like_fields],
            "semantic_isolation_applied": self.semantic_isolation_applied,
            "notes": self.notes,
        }


def analyze_candidate(candidate: dict, source_path: str) -> SampleProbeResult:
    """Analyze one Enumd candidate file and return a probe result."""
    session_id = candidate.get("session_id", Path(source_path).stem)
    ingestion_valid = _classify_ingestion_valid(candidate)
    boundary_status = _classify_boundary_status(candidate)

    authority_fields: list[AuthorityLikeField] = []
    for dotpath, spec in _NON_EQUIVALENCE_REGISTRY.items():
        exists, value = _get_nested(candidate, dotpath)
        if not exists or value is None:
            continue
        authority_fields.append(AuthorityLikeField(
            field=dotpath,
            family=spec["family"],
            actual_scope=spec["actual_scope"],
            misread_scope=spec["misread_scope"],
            reinterpretation_required=spec["reinterpretation_required"],
            collision_risk=spec["collision_risk"],
            observed_value=value,
            non_equivalence=spec["non_equivalence"],
        ))

    high_risk = any(f.collision_risk == "high" for f in authority_fields)
    any_risk = len(authority_fields) > 0
    inducement_risk = "high" if high_risk else ("medium" if any_risk else "low")
    misread_risk = "high" if high_risk else ("medium" if any_risk else "low")

    notes_parts = []
    if boundary_status == "pass" and not ingestion_valid:
        notes_parts.append("boundary pass despite ingestion failure")
    if any_risk:
        notes_parts.append(f"{len(authority_fields)} authority-like field(s) detected; semantic isolation applied")

    return SampleProbeResult(
        sample_id=session_id,
        source_path=source_path,
        ingestion_valid=ingestion_valid,
        boundary_status=boundary_status,
        runtime_eligible_result="observe_only",
        inducement_risk=inducement_risk,
        misread_risk=misread_risk,
        authority_like_fields=authority_fields,
        semantic_isolation_applied=any_risk,
        notes="; ".join(notes_parts),
    )


def _classify_batch_conclusion(samples: list[SampleProbeResult]) -> str:
    """
    observe_only_with_semantic_collision  — systematic authority-like fields (high-collision
                                            family present in >= 50% of samples)
    observe_only_with_inducement_risk     — occasional authority-like fields
    observe_only_safe                     — no authority-like fields detected
    """
    if not samples:
        return "observe_only_safe"

    high_collision_hits = sum(
        1 for s in samples
        if any(f.field in _HIGH_COLLISION_FIELDS for f in s.authority_like_fields)
    )
    ratio = high_collision_hits / len(samples)
    if ratio >= 0.5:
        return "observe_only_with_semantic_collision"

    any_hit = sum(1 for s in samples if s.authority_like_fields)
    if any_hit > 0:
        return "observe_only_with_inducement_risk"

    return "observe_only_safe"


def run_probe(
    candidates_dir: Path,
    registry_path: Path | None = None,
) -> dict:
    """Read all candidate JSON files in candidates_dir and return a probe report."""
    files = sorted(candidates_dir.glob("*.json"))
    samples: list[SampleProbeResult] = []

    for fp in files:
        try:
            candidate = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as exc:
            samples.append(SampleProbeResult(
                sample_id=fp.stem,
                source_path=str(fp),
                ingestion_valid=False,
                boundary_status="error",
                runtime_eligible_result="error",
                inducement_risk="unknown",
                misread_risk="unknown",
                notes=f"parse error: {exc}",
            ))
            continue
        samples.append(analyze_candidate(candidate, str(fp)))

    batch_conclusion = _classify_batch_conclusion(samples)
    systematic_collision_fields = sorted({
        f.field
        for s in samples
        for f in s.authority_like_fields
        if f.field in _HIGH_COLLISION_FIELDS
    }) if batch_conclusion == "observe_only_with_semantic_collision" else []

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(candidates_dir),
        "registry_path": str(registry_path) if registry_path else "built-in",
        "n": len(samples),
        "batch_conclusion": batch_conclusion,
        "systematic_collision_fields": systematic_collision_fields,
        "boundary_fail_count": sum(1 for s in samples if s.boundary_status == "fail"),
        "ingestion_valid_count": sum(1 for s in samples if s.ingestion_valid),
        "semantic_isolation_applied_count": sum(1 for s in samples if s.semantic_isolation_applied),
        "samples": [s.to_dict() for s in samples],
    }


def _has_narrative_content(closeout: dict) -> bool:
    """True if the closeout contains any non-null narrative field."""
    narrative_fields = ("task_intent", "work_summary")
    for f in narrative_fields:
        if closeout.get(f) is not None:
            return True
    evidence = closeout.get("evidence_summary") or {}
    if evidence.get("tools_used") or evidence.get("artifacts_referenced"):
        return True
    if closeout.get("open_risks"):
        return True
    return False


def _classify_narrative_risk_delta(
    closeout: dict,
    candidate_result: SampleProbeResult | None,
) -> str:
    """
    amplified  — closeout has narrative content that wraps candidate decision-shaped signals
    maintained — closeout has authority-like fields but no narrative content
    reduced    — closeout is fully null/empty; no narrativization of candidate signals
    neutral    — closeout has no authority-like fields and no candidate to compare
    """
    has_narrative = _has_narrative_content(closeout)
    has_candidate_collision = (
        candidate_result is not None
        and any(f.collision_risk in ("high", "medium") for f in candidate_result.authority_like_fields)
    )

    if has_narrative and has_candidate_collision:
        return "amplified"
    if not has_narrative and has_candidate_collision:
        return "reduced"
    if has_narrative and not has_candidate_collision:
        return "maintained"
    return "neutral"


@dataclass
class CloseoutProbeResult:
    session_id: str
    source_path: str
    closeout_status: str
    has_narrative_content: bool
    authority_like_fields: list[AuthorityLikeField]
    narrative_risk_delta: str
    candidate_inducement_risk: str
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "source_path": self.source_path,
            "closeout_status": self.closeout_status,
            "has_narrative_content": self.has_narrative_content,
            "authority_like_fields": [f.to_dict() for f in self.authority_like_fields],
            "narrative_risk_delta": self.narrative_risk_delta,
            "candidate_inducement_risk": self.candidate_inducement_risk,
            "notes": self.notes,
        }


def analyze_closeout(
    closeout: dict,
    source_path: str,
    candidate_result: SampleProbeResult | None = None,
) -> CloseoutProbeResult:
    """Analyze one Enumd closeout file and return a probe result."""
    session_id = closeout.get("session_id", Path(source_path).stem)
    closeout_status = closeout.get("closeout_status", "unknown")
    has_narrative = _has_narrative_content(closeout)

    authority_fields: list[AuthorityLikeField] = []
    for dotpath, spec in _CLOSEOUT_NON_EQUIVALENCE_REGISTRY.items():
        exists, value = _get_nested(closeout, dotpath)
        if not exists or value is None:
            continue
        authority_fields.append(AuthorityLikeField(
            field=dotpath,
            family=spec["family"],
            actual_scope=spec["actual_scope"],
            misread_scope=spec["misread_scope"],
            reinterpretation_required=spec["reinterpretation_required"],
            collision_risk=spec["collision_risk"],
            observed_value=value,
            non_equivalence=spec["non_equivalence"],
        ))

    delta = _classify_narrative_risk_delta(closeout, candidate_result)
    candidate_risk = candidate_result.inducement_risk if candidate_result else "unknown"

    notes_parts = []
    if not has_narrative:
        notes_parts.append("null narrative content — no amplification of candidate signals")
    if delta == "reduced":
        notes_parts.append("risk reduced relative to candidate layer")

    return CloseoutProbeResult(
        session_id=session_id,
        source_path=source_path,
        closeout_status=closeout_status,
        has_narrative_content=has_narrative,
        authority_like_fields=authority_fields,
        narrative_risk_delta=delta,
        candidate_inducement_risk=candidate_risk,
        notes="; ".join(notes_parts),
    )


def run_closeout_probe(
    closeouts_dir: Path,
    candidates_dir: Path | None = None,
) -> dict:
    """
    Read all closeout JSON files and return a probe report.
    If candidates_dir is provided, cross-reference by session_id to compute risk delta.
    """
    # Build candidate index keyed by session_id
    candidate_index: dict[str, SampleProbeResult] = {}
    if candidates_dir and candidates_dir.exists():
        for fp in sorted(candidates_dir.glob("*.json")):
            try:
                candidate = json.loads(fp.read_text(encoding="utf-8"))
                result = analyze_candidate(candidate, str(fp))
                candidate_index[result.sample_id] = result
            except Exception:
                pass

    files = sorted(closeouts_dir.glob("*.json"))
    results: list[CloseoutProbeResult] = []

    for fp in files:
        try:
            closeout = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as exc:
            results.append(CloseoutProbeResult(
                session_id=fp.stem,
                source_path=str(fp),
                closeout_status="error",
                has_narrative_content=False,
                authority_like_fields=[],
                narrative_risk_delta="neutral",
                candidate_inducement_risk="unknown",
                notes=f"parse error: {exc}",
            ))
            continue

        session_id = closeout.get("session_id", fp.stem)
        candidate_result = candidate_index.get(session_id)
        results.append(analyze_closeout(closeout, str(fp), candidate_result))

    delta_dist: dict[str, int] = {}
    for r in results:
        delta_dist[r.narrative_risk_delta] = delta_dist.get(r.narrative_risk_delta, 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "enumd-closeout-probe",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(closeouts_dir),
        "candidates_dir": str(candidates_dir) if candidates_dir else None,
        "n": len(results),
        "with_narrative_content": sum(1 for r in results if r.has_narrative_content),
        "narrative_risk_delta_distribution": delta_dist,
        "batch_conclusion": _closeout_batch_conclusion(results),
        "samples": [r.to_dict() for r in results],
    }


def _closeout_batch_conclusion(results: list[CloseoutProbeResult]) -> str:
    if not results:
        return "observe_only_safe"
    if any(r.narrative_risk_delta == "amplified" for r in results):
        return "observe_only_with_semantic_collision"
    if any(r.has_narrative_content for r in results):
        return "observe_only_with_inducement_risk"
    return "observe_only_safe"


@dataclass
class MemoryCandidateResult:
    sample_id: str
    source_path: str
    memory_mode: str
    policy_decision_present: bool
    authority_like_fields: list[AuthorityLikeField]
    risk_profile: str
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "sample_id": self.sample_id,
            "source_path": self.source_path,
            "memory_mode": self.memory_mode,
            "policy_decision_present": self.policy_decision_present,
            "authority_like_fields": [f.to_dict() for f in self.authority_like_fields],
            "risk_profile": self.risk_profile,
            "notes": self.notes,
        }


def analyze_memory_candidate(candidate: dict, source_path: str) -> MemoryCandidateResult:
    """Analyze one Enumd memory candidate (different schema from runtime candidates)."""
    sample_id = Path(source_path).stem
    # Extract memory_mode from source_text if present
    source_text = candidate.get("source_text", "")
    memory_mode = "unknown"
    for line in source_text.splitlines():
        if line.strip().startswith("MEMORY_MODE"):
            memory_mode = line.split("=", 1)[-1].strip()
            break

    # policy.decision is NOT present in memory candidates — this is the key finding
    exists, _ = _get_nested(candidate, "policy.decision")
    policy_decision_present = exists

    authority_fields: list[AuthorityLikeField] = []
    for dotpath, spec in _MEMORY_CANDIDATE_NON_EQUIVALENCE_REGISTRY.items():
        exists, value = _get_nested(candidate, dotpath)
        if not exists or value is None:
            continue
        authority_fields.append(AuthorityLikeField(
            field=dotpath,
            family=spec["family"],
            actual_scope=spec["actual_scope"],
            misread_scope=spec["misread_scope"],
            reinterpretation_required=spec["reinterpretation_required"],
            collision_risk=spec["collision_risk"],
            observed_value=value,
            non_equivalence=spec["non_equivalence"],
        ))

    # Risk profile: low if no policy.decision and only documentation metadata fields
    high_collision = any(f.collision_risk == "high" for f in authority_fields)
    risk_profile = "high" if (high_collision or policy_decision_present) else "low"

    notes_parts = []
    if not policy_decision_present:
        notes_parts.append("policy.decision absent — memory_mode=candidate does not trigger DO_NOT_PROMOTE")
    if risk_profile == "low":
        notes_parts.append("risk profile: low — only documentation metadata fields present")

    return MemoryCandidateResult(
        sample_id=sample_id,
        source_path=source_path,
        memory_mode=memory_mode,
        policy_decision_present=policy_decision_present,
        authority_like_fields=authority_fields,
        risk_profile=risk_profile,
        notes="; ".join(notes_parts),
    )


def run_memory_candidate_probe(candidates_dir: Path) -> dict:
    """Read all memory candidate JSON files and return a spot-check report."""
    files = sorted(candidates_dir.glob("*.json"))
    results: list[MemoryCandidateResult] = []

    for fp in files:
        try:
            candidate = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as exc:
            results.append(MemoryCandidateResult(
                sample_id=fp.stem,
                source_path=str(fp),
                memory_mode="error",
                policy_decision_present=False,
                authority_like_fields=[],
                risk_profile="unknown",
                notes=f"parse error: {exc}",
            ))
            continue
        results.append(analyze_memory_candidate(candidate, str(fp)))

    policy_absent_count = sum(1 for r in results if not r.policy_decision_present)

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "enumd-memory-candidate-probe",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(candidates_dir),
        "n": len(results),
        "policy_decision_absent_count": policy_absent_count,
        "low_risk_count": sum(1 for r in results if r.risk_profile == "low"),
        "key_finding": (
            "policy.decision absent in all memory candidates — memory_mode=candidate "
            "does not trigger DO_NOT_PROMOTE; risk profile reduced vs stateless runtime candidates"
        ) if policy_absent_count == len(results) and len(results) > 0 else "mixed",
        "samples": [r.to_dict() for r in results],
    }


def format_human(report: dict) -> str:
    atype = report.get("artifact_type", "enumd-semantic-isolation-probe")

    if atype == "enumd-closeout-probe":
        lines = [
            "[enumd_closeout_probe]",
            f"source_dir={report['source_dir']}",
            f"n={report['n']}",
            f"batch_conclusion={report['batch_conclusion']}",
            f"with_narrative_content={report['with_narrative_content']}",
            f"narrative_risk_delta_distribution={report['narrative_risk_delta_distribution']}",
        ]
        return "\n".join(lines)

    if atype == "enumd-memory-candidate-probe":
        lines = [
            "[enumd_memory_candidate_probe]",
            f"source_dir={report['source_dir']}",
            f"n={report['n']}",
            f"policy_decision_absent_count={report['policy_decision_absent_count']}",
            f"low_risk_count={report['low_risk_count']}",
            f"key_finding={report['key_finding']}",
        ]
        return "\n".join(lines)

    # default: candidate probe
    lines = [
        "[enumd_semantic_isolation_probe]",
        f"source_dir={report['source_dir']}",
        f"n={report['n']}",
        f"batch_conclusion={report['batch_conclusion']}",
        f"boundary_fail_count={report['boundary_fail_count']}",
        f"ingestion_valid_count={report['ingestion_valid_count']}",
        f"semantic_isolation_applied_count={report['semantic_isolation_applied_count']}",
    ]
    if report.get("systematic_collision_fields"):
        lines.append(f"systematic_collision_fields={','.join(report['systematic_collision_fields'])}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run semantic isolation probe on Enumd runtime artifacts."
    )
    parser.add_argument(
        "--mode",
        choices=["candidate", "closeout", "memory-candidate"],
        default="candidate",
        help="Probe mode: candidate (default), closeout, or memory-candidate",
    )
    parser.add_argument("--candidates-dir", help="Directory containing Enumd candidate JSON files")
    parser.add_argument("--closeouts-dir", help="Directory containing Enumd closeout JSON files (closeout mode)")
    parser.add_argument("--registry", help="Path to external non_equivalence_registry.json (optional)")
    parser.add_argument("--output", help="Output path for probe report JSON")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    registry_path = Path(args.registry).resolve() if args.registry else None

    if args.mode == "candidate":
        if not args.candidates_dir:
            parser.error("--candidates-dir is required for candidate mode")
        report = run_probe(Path(args.candidates_dir).resolve(), registry_path)

    elif args.mode == "closeout":
        if not args.closeouts_dir:
            parser.error("--closeouts-dir is required for closeout mode")
        candidates_dir = Path(args.candidates_dir).resolve() if args.candidates_dir else None
        report = run_closeout_probe(Path(args.closeouts_dir).resolve(), candidates_dir)

    else:  # memory-candidate
        if not args.candidates_dir:
            parser.error("--candidates-dir is required for memory-candidate mode")
        report = run_memory_candidate_probe(Path(args.candidates_dir).resolve())

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_human(report))
        if args.output:
            print(f"output={args.output}")


if __name__ == "__main__":
    main()
