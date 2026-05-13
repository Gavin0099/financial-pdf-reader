#!/usr/bin/env python3
"""
Enumd real-data observe-only probe (advisory-only, non-gating).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integrations.enumd.enumd_adapter import adapt_enumd_report
from integrations.enumd.ingestor import validate_report

_FORBIDDEN_AUTHORITY_FIELDS: frozenset[str] = frozenset(
    {
        "verdict",
        "gate_verdict",
        "current_state",
        "closure_verified",
        "promote_eligible",
        "phase3_entry_allowed",
        "closure_review_approved",
    }
)

_DEFAULT_FIXTURES: tuple[str, ...] = (
    "valid_wave5.json",
    "looks_safe_not_tested.json",
    "ambiguous_status.json",
    "missing_fields.json",
    "forbidden_authority_fields.json",
)


def _runtime_eligible_from_report(report: dict[str, Any]) -> bool:
    return bool(report.get("semantic_boundary", {}).get("represents_agent_behavior", True))


def _severity_rank(level: str) -> int:
    if level == "high":
        return 3
    if level == "medium":
        return 2
    return 1


def _max_risk(a: str, b: str) -> str:
    return a if _severity_rank(a) >= _severity_rank(b) else b


def _read_node_signals_consumed(report: dict[str, Any]) -> tuple[bool, list[str]]:
    notes: list[str] = []
    raw = report.get("nodeSignals_consumed", False)
    if isinstance(raw, bool):
        return raw, notes
    notes.append("node_signals_consumed_malformed_treated_as_false")
    return False, notes


def _read_instrumentation_version(raw: Any) -> dict[str, int] | None:
    if not isinstance(raw, dict):
        return None
    major = raw.get("major")
    minor = raw.get("minor")
    if isinstance(major, int) and isinstance(minor, int):
        return {"major": major, "minor": minor}
    return None


def _assess_instrumentation_version_change(report: dict[str, Any]) -> dict[str, Any]:
    current = _read_instrumentation_version(report.get("instrumentation_version"))
    baseline = _read_instrumentation_version(report.get("instrumentation_version_baseline"))

    major_changed = False
    minor_changed = False
    if current and baseline:
        major_changed = current["major"] != baseline["major"]
        minor_changed = current["minor"] != baseline["minor"]

    return {
        "current": current,
        "baseline": baseline,
        "major_changed": major_changed,
        "minor_changed": minor_changed,
        "advisory_only": True,
    }


def probe_report(report: dict[str, Any], sample_id: str) -> dict[str, Any]:
    notes: list[str] = []
    validation_errors = validate_report(report)
    envelope = adapt_enumd_report(report)

    ingestion_valid = envelope.get("ingest_status") == "accepted"
    if not ingestion_valid:
        notes.append("adapter_ingest_status_not_accepted")

    runtime_eligible = _runtime_eligible_from_report(report)
    runtime_eligible_result = {
        "eligible": runtime_eligible,
        "expected": False,
        "pass": runtime_eligible is False,
    }
    if runtime_eligible:
        notes.append("runtime_eligible_true_for_external_observation")

    boundary_reasons: list[str] = []
    for err in validation_errors:
        msg = str(err)
        if "semantic_boundary" in msg or "represents_agent_behavior" in msg:
            boundary_reasons.append(msg)
    if runtime_eligible:
        boundary_reasons.append("is_runtime_eligible_true")
    boundary_status = "pass" if not boundary_reasons else "fail"

    forbidden_seen = sorted(k for k in _FORBIDDEN_AUTHORITY_FIELDS if k in report)
    advisory_signals = envelope.get("advisory_signals") or []
    advisories = report.get("advisories") or []
    node_signals_consumed, consumed_notes = _read_node_signals_consumed(report)
    notes.extend(consumed_notes)
    instrumentation_change = _assess_instrumentation_version_change(report)
    instrumentation_major_changed = bool(instrumentation_change["major_changed"])
    instrumentation_minor_changed = bool(instrumentation_change["minor_changed"])
    reevaluation_required = node_signals_consumed or instrumentation_major_changed
    advisory_signal_present = bool(
        advisories
        or advisory_signals
        or node_signals_consumed
        or instrumentation_major_changed
        or instrumentation_minor_changed
    )
    semantic_shift_candidate_reasons: list[str] = []
    if instrumentation_major_changed:
        semantic_shift_candidate_reasons.append("instrumentation_major_change")
    semantic_shift_candidate = bool(semantic_shift_candidate_reasons)
    event_metadata = {
        "event_name": report.get("event_name") if isinstance(report.get("event_name"), str) else None,
        "event_channel": report.get("event_channel") if isinstance(report.get("event_channel"), str) else None,
        "run_type": report.get("run_type") if isinstance(report.get("run_type"), str) else None,
        "observation_type": report.get("observation_type") if isinstance(report.get("observation_type"), str) else None,
        "semantic_scope": report.get("semantic_scope") if isinstance(report.get("semantic_scope"), str) else None,
    }
    source = envelope.get("source") if isinstance(envelope.get("source"), dict) else {}
    observation = envelope.get("observation") if isinstance(envelope.get("observation"), dict) else {}
    source_provenance = {
        "run_id": report.get("run_id") if isinstance(report.get("run_id"), str) else None,
        "source_id": source.get("source_id") if isinstance(source.get("source_id"), str) else None,
        "source_type": source.get("source_type") if isinstance(source.get("source_type"), str) else None,
        "evidence_refs": observation.get("evidence_refs") if isinstance(observation.get("evidence_refs"), list) else [],
    }

    semantic_inducement_risk = "low"
    consumer_misread_risk = "low"
    if advisories or advisory_signals:
        semantic_inducement_risk = "medium"
        consumer_misread_risk = "medium"
        notes.append("advisory_signal_present")
    if forbidden_seen:
        semantic_inducement_risk = "high"
        consumer_misread_risk = "high"
        notes.append("forbidden_authority_fields_present")
    if node_signals_consumed:
        semantic_inducement_risk = _max_risk(semantic_inducement_risk, "medium")
        consumer_misread_risk = _max_risk(consumer_misread_risk, "medium")
        notes.append("node_signals_consumed_requires_semantic_reevaluation")
    if instrumentation_major_changed:
        semantic_inducement_risk = _max_risk(semantic_inducement_risk, "medium")
        consumer_misread_risk = _max_risk(consumer_misread_risk, "medium")
        notes.append("instrumentation_major_change_advisory")
    elif instrumentation_minor_changed:
        notes.append("instrumentation_minor_change_no_gate_escalation")
    if boundary_status == "fail":
        semantic_inducement_risk = _max_risk(semantic_inducement_risk, "high")
        consumer_misread_risk = _max_risk(consumer_misread_risk, "high")

    if boundary_status == "fail":
        sample_conclusion = "boundary_fail_do_not_progress"
    elif semantic_inducement_risk != "low" or consumer_misread_risk != "low":
        sample_conclusion = "observe_only_with_inducement_risk"
    else:
        sample_conclusion = "safe_for_observe_only"

    return {
        "sample_id": sample_id,
        "ingestion_valid": ingestion_valid,
        "boundary_status": boundary_status,
        "runtime_eligible_result": runtime_eligible_result,
        "semantic_inducement_risk": semantic_inducement_risk,
        "consumer_misread_risk": consumer_misread_risk,
        "notes": notes,
        "validation_error_count": len(validation_errors),
        "validation_errors": validation_errors,
        "forbidden_authority_fields_seen": forbidden_seen,
        "advisory_signal_present": advisory_signal_present,
        "event_metadata": event_metadata,
        "source_provenance": source_provenance,
        "nodeSignals_consumed": node_signals_consumed,
        "reevaluation_required": reevaluation_required,
        "semantic_shift_candidate": semantic_shift_candidate,
        "semantic_shift_candidate_reasons": semantic_shift_candidate_reasons,
        "instrumentation_version_change": instrumentation_change,
        "sample_conclusion": sample_conclusion,
    }


def _default_sample_paths(sample_dir: Path) -> list[Path]:
    return [sample_dir / name for name in _DEFAULT_FIXTURES]


def run_probe(sample_paths: list[Path]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in sample_paths:
        sample_id = path.stem
        if not path.is_file():
            records.append(
                {
                    "sample_id": sample_id,
                    "ingestion_valid": False,
                    "boundary_status": "fail",
                    "runtime_eligible_result": {"eligible": True, "expected": False, "pass": False},
                    "semantic_inducement_risk": "high",
                    "consumer_misread_risk": "high",
                    "notes": ["sample_file_missing"],
                    "validation_error_count": 1,
                    "validation_errors": [f"sample_not_found:{path}"],
                    "forbidden_authority_fields_seen": [],
                    "advisory_signal_present": False,
                    "event_metadata": {
                        "event_name": None,
                        "event_channel": None,
                        "run_type": None,
                        "observation_type": None,
                        "semantic_scope": None,
                    },
                    "source_provenance": {
                        "run_id": None,
                        "source_id": None,
                        "source_type": None,
                        "evidence_refs": [],
                    },
                    "nodeSignals_consumed": False,
                    "reevaluation_required": False,
                    "semantic_shift_candidate": False,
                    "semantic_shift_candidate_reasons": [],
                    "instrumentation_version_change": {
                        "current": None,
                        "baseline": None,
                        "major_changed": False,
                        "minor_changed": False,
                        "advisory_only": True,
                    },
                    "sample_conclusion": "boundary_fail_do_not_progress",
                }
            )
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            records.append(
                {
                    "sample_id": sample_id,
                    "ingestion_valid": False,
                    "boundary_status": "fail",
                    "runtime_eligible_result": {"eligible": True, "expected": False, "pass": False},
                    "semantic_inducement_risk": "high",
                    "consumer_misread_risk": "high",
                    "notes": ["sample_unreadable"],
                    "validation_error_count": 1,
                    "validation_errors": [f"sample_unreadable:{exc}"],
                    "forbidden_authority_fields_seen": [],
                    "advisory_signal_present": False,
                    "event_metadata": {
                        "event_name": None,
                        "event_channel": None,
                        "run_type": None,
                        "observation_type": None,
                        "semantic_scope": None,
                    },
                    "source_provenance": {
                        "run_id": None,
                        "source_id": None,
                        "source_type": None,
                        "evidence_refs": [],
                    },
                    "nodeSignals_consumed": False,
                    "reevaluation_required": False,
                    "semantic_shift_candidate": False,
                    "semantic_shift_candidate_reasons": [],
                    "instrumentation_version_change": {
                        "current": None,
                        "baseline": None,
                        "major_changed": False,
                        "minor_changed": False,
                        "advisory_only": True,
                    },
                    "sample_conclusion": "boundary_fail_do_not_progress",
                }
            )
            continue
        if not isinstance(report, dict):
            report = {}
        records.append(probe_report(report, sample_id=sample_id))

    if any(r["sample_conclusion"] == "boundary_fail_do_not_progress" for r in records):
        batch_conclusion = "boundary_fail_do_not_progress"
    elif any(r["sample_conclusion"] == "observe_only_with_inducement_risk" for r in records):
        batch_conclusion = "observe_only_with_inducement_risk"
    else:
        batch_conclusion = "safe_for_observe_only"

    review_required_sample_ids = [
        str(r.get("sample_id"))
        for r in records
        if bool(r.get("reevaluation_required"))
    ]

    return {
        "advisory_only": True,
        "probe_kind": "enumd_real_data_observe_only",
        "sample_count": len(records),
        "batch_conclusion": batch_conclusion,
        "review_required_sample_count": len(review_required_sample_ids),
        "review_required_sample_ids": review_required_sample_ids,
        "review_required_advisory_only": True,
        "samples": records,
        "caveat": (
            "Probe pass means containment under observe-only scope; "
            "it does not imply integration-ready value justification."
        ),
    }


def format_human(result: dict[str, Any]) -> str:
    lines = [
        "[enumd_observe_only_probe]",
        f"advisory_only={result.get('advisory_only')}",
        f"sample_count={result.get('sample_count')}",
        f"batch_conclusion={result.get('batch_conclusion')}",
        f"review_required_sample_count={result.get('review_required_sample_count')}",
        "review_required_advisory_only=True",
        f"caveat={result.get('caveat')}",
        "[samples]",
    ]
    for sample in result.get("samples", []):
        lines.append(
            " | ".join(
                [
                    str(sample.get("sample_id")),
                    f"ingestion_valid={sample.get('ingestion_valid')}",
                    f"boundary_status={sample.get('boundary_status')}",
                    f"runtime_pass={(sample.get('runtime_eligible_result') or {}).get('pass')}",
                    f"advisory_signal_present={sample.get('advisory_signal_present')}",
                    f"reevaluation_required={sample.get('reevaluation_required')}",
                    f"semantic_shift_candidate={sample.get('semantic_shift_candidate')}",
                    f"semantic_inducement_risk={sample.get('semantic_inducement_risk')}",
                    f"consumer_misread_risk={sample.get('consumer_misread_risk')}",
                    f"sample_conclusion={sample.get('sample_conclusion')}",
                ]
            )
        )
    ids = result.get("review_required_sample_ids") or []
    if ids:
        lines.append("[review_required_samples]")
        for sample_id in ids:
            lines.append(f"- {sample_id}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Enumd observe-only probe on sample reports.")
    parser.add_argument("--sample", action="append", default=[], help="Enumd report JSON path (repeatable)")
    parser.add_argument("--sample-dir", default="tests/fixtures/enumd")
    parser.add_argument("--use-default-sample-set", action="store_true")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    sample_paths = [Path(p) for p in args.sample]
    if not sample_paths:
        sample_dir = Path(args.sample_dir)
        sample_paths = _default_sample_paths(sample_dir)

    result = run_probe(sample_paths)
    rendered = (
        json.dumps(result, ensure_ascii=False, indent=2)
        if args.format == "json"
        else format_human(result)
    )
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
