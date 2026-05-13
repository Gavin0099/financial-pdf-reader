#!/usr/bin/env python3
"""
Summarize reviewer linter calibration dataset coverage and sparsity hotspots.

This tool is observational only. It must not gate CI by itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.review_artifact_linter import lint_text

DEFAULT_DATASET = Path("tests/fixtures/reviewer_linter_calibration_dataset.json")
HIGH_RISK_FAMILIES = {"promotion", "confidence_laundering"}


def _load_dataset(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("dataset_must_be_list")
    return [item for item in payload if isinstance(item, dict)]


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    text = str(case.get("text", ""))
    expected_status = str(case.get("expected_status", "clean"))
    result = lint_text(text)
    claim_types = {str(v.get("claim_type")) for v in result.get("violations", [])}

    must_include = [str(x) for x in (case.get("must_include_claim_types") or [])]
    must_exclude = [str(x) for x in (case.get("must_exclude_claim_types") or [])]
    include_ok = all(x in claim_types for x in must_include)
    exclude_ok = all(x not in claim_types for x in must_exclude)
    status_ok = str(result.get("status")) == expected_status

    return {
        "id": str(case.get("id", "")),
        "semantic_family": str(case.get("semantic_family", "unknown")),
        "surface_type": str(case.get("surface_type", "unknown")),
        "ambiguity_tier": str(case.get("ambiguity_tier", "unknown")),
        "expected_status": expected_status,
        "observed_status": str(result.get("status")),
        "status_ok": status_ok,
        "include_ok": include_ok,
        "exclude_ok": exclude_ok,
        "case_ok": bool(status_ok and include_ok and exclude_ok),
    }


def build_calibration_summary(dataset: list[dict[str, Any]]) -> dict[str, Any]:
    cases = [_evaluate_case(case) for case in dataset]
    by_family: dict[str, dict[str, Any]] = {}
    for case in cases:
        family = case["semantic_family"]
        slot = by_family.setdefault(
            family,
            {
                "sample_count": 0,
                "surface_types": set(),
                "tiers": {},
                "status_mismatch_count": 0,
                "claim_constraint_mismatch_count": 0,
                "case_fail_count": 0,
            },
        )
        slot["sample_count"] += 1
        slot["surface_types"].add(case["surface_type"])
        slot["tiers"][case["ambiguity_tier"]] = slot["tiers"].get(case["ambiguity_tier"], 0) + 1
        if not case["status_ok"]:
            slot["status_mismatch_count"] += 1
        if not (case["include_ok"] and case["exclude_ok"]):
            slot["claim_constraint_mismatch_count"] += 1
        if not case["case_ok"]:
            slot["case_fail_count"] += 1

    families: dict[str, dict[str, Any]] = {}
    for family, slot in sorted(by_family.items()):
        families[family] = {
            "sample_count": slot["sample_count"],
            "surface_count": len(slot["surface_types"]),
            "surface_types": sorted(slot["surface_types"]),
            "tier_distribution": slot["tiers"],
            "status_mismatch_count": slot["status_mismatch_count"],
            "claim_constraint_mismatch_count": slot["claim_constraint_mismatch_count"],
            "case_fail_count": slot["case_fail_count"],
        }

    sparse_families = [
        family
        for family, info in families.items()
        if info["sample_count"] < 2 or info["surface_count"] < 2
    ]
    missing_high_risk_subtle = [
        family
        for family in sorted(HIGH_RISK_FAMILIES)
        if family in families and families[family]["tier_distribution"].get("tier_c_subtle", 0) == 0
    ]
    failing_families = [
        family for family, info in families.items() if info["case_fail_count"] > 0
    ]

    return {
        "advisory_only": True,
        "dataset_case_count": len(dataset),
        "evaluated_case_count": len(cases),
        "overall_case_fail_count": sum(1 for c in cases if not c["case_ok"]),
        "families": families,
        "hotspots": {
            "sparse_families": sparse_families,
            "high_risk_missing_subtle_coverage": missing_high_risk_subtle,
            "failing_families": failing_families,
        },
    }


def format_human_summary(summary: dict[str, Any]) -> str:
    lines = [
        "[reviewer_linter_calibration_summary]",
        f"advisory_only={summary.get('advisory_only')}",
        f"dataset_case_count={summary.get('dataset_case_count')}",
        f"overall_case_fail_count={summary.get('overall_case_fail_count')}",
        "[families]",
    ]
    families = summary.get("families") or {}
    for family in sorted(families):
        info = families[family]
        lines.append(
            " | ".join(
                [
                    family,
                    f"samples={info.get('sample_count')}",
                    f"surfaces={info.get('surface_count')}",
                    f"tiers={json.dumps(info.get('tier_distribution', {}), ensure_ascii=False, sort_keys=True)}",
                    f"fails={info.get('case_fail_count')}",
                ]
            )
        )
    hotspots = summary.get("hotspots") or {}
    lines.extend(
        [
            "[hotspots]",
            f"sparse_families={','.join(hotspots.get('sparse_families') or [])}",
            "high_risk_missing_subtle_coverage="
            + ",".join(hotspots.get("high_risk_missing_subtle_coverage") or []),
            f"failing_families={','.join(hotspots.get('failing_families') or [])}",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize reviewer linter calibration coverage.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--format", choices=("human", "json"), default="human")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    dataset = _load_dataset(Path(args.dataset))
    summary = build_calibration_summary(dataset)
    rendered = (
        json.dumps(summary, ensure_ascii=False, indent=2)
        if args.format == "json"
        else format_human_summary(summary)
    )
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
