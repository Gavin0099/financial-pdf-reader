#!/usr/bin/env python3
"""
A/B baseline pre-run validator.

Purpose:
- Classify Group A baseline readiness before running A/B smoke.
- Emit machine-readable JSON and reviewer-readable human summary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


INVALID_PATHS = (
    "GOVERNANCE_ENTRY.md",
    "runtime_hooks",
    "governance_tools",
)

INVALID_KEYWORDS = (
    "authority register",
    "closeout contract",
)

DEGRADED_KEYWORDS = (
    "governance-complete",
    "governance complete",
    "release-ready",
    "release ready",
    "authority",
    "reviewer",
    "verdict",
)

DIRECTIONAL_HINT_KEYWORDS = (
    "contract",
    "governance",
    "authority",
    "reviewer",
    "evidence",
)


def _scan_file(path: Path, keywords: tuple[str, ...]) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
    except Exception:
        return []
    hits: list[str] = []
    for kw in keywords:
        if kw in text:
            hits.append(kw)
    return hits


def validate_ab_baseline(project_root: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []

    # Layer 1: baseline_invalid
    for rel in INVALID_PATHS:
        p = project_root / rel
        if p.exists():
            findings.append(
                {
                    "code": "governance_surface_present",
                    "path": rel,
                    "severity": "invalid",
                    "evidence": "path exists in ungoverned baseline",
                }
            )

    for rel in ("README.md", "PLAN.md"):
        hits = _scan_file(project_root / rel, INVALID_KEYWORDS)
        for kw in hits:
            findings.append(
                {
                    "code": "invalid_authority_contract_reference",
                    "path": rel,
                    "severity": "invalid",
                    "evidence": f"contains '{kw}'",
                }
            )

    # Layer 2: baseline_degraded
    degraded_paths = (
        "README.md",
        "PLAN.md",
        "artifacts",
    )
    for rel in degraded_paths:
        p = project_root / rel
        if p.is_dir() and rel == "artifacts":
            # directory-name heuristic for reviewer/verdict/authority residue
            for child in p.rglob("*"):
                c = str(child.relative_to(project_root)).replace("\\", "/").lower()
                if any(token in c for token in ("reviewer", "verdict", "authority")):
                    findings.append(
                        {
                            "code": "semantic_prior_from_artifact_naming",
                            "path": c,
                            "severity": "degraded",
                            "evidence": "residual reviewer/verdict/authority artifact naming",
                        }
                    )
                    break
        else:
            hits = _scan_file(p, DEGRADED_KEYWORDS)
            if hits:
                findings.append(
                    {
                        "code": "semantic_prior_from_retained_doc_language",
                        "path": rel,
                        "severity": "degraded",
                        "evidence": "contains release-ready / authority wording",
                    }
                )

    # Layer 3: baseline_directional_only
    root_name = project_root.name.lower()
    if any(token in root_name for token in DIRECTIONAL_HINT_KEYWORDS):
        findings.append(
            {
                "code": "semantic_prior_from_repo_naming",
                "path": project_root.name,
                "severity": "directional_only",
                "evidence": "repo naming implies governance semantics",
            }
        )

    # Catch wrapped baselines like ".../<repo>/workspace/group-a"
    # where the immediate root is neutral but parent names carry governance semantics.
    parent_name_chain = [
        p.name
        for p in (project_root.parent, project_root.parent.parent, project_root.parent.parent.parent)
        if p is not None
    ]
    for name in parent_name_chain:
        name_l = name.lower()
        if any(token in name_l for token in DIRECTIONAL_HINT_KEYWORDS):
            findings.append(
                {
                    "code": "semantic_prior_from_parent_repo_naming",
                    "path": name,
                    "severity": "directional_only",
                    "evidence": "parent repo naming implies governance semantics",
                }
            )
            break

    examples_dir = project_root / "examples"
    if examples_dir.exists():
        if len([d for d in examples_dir.iterdir() if d.is_dir()]) > 0:
            findings.append(
                {
                    "code": "semantic_prior_from_example_structure",
                    "path": "examples/",
                    "severity": "directional_only",
                    "evidence": "retained example layout can imply governance usage patterns",
                }
            )
        for child in examples_dir.iterdir():
            name = child.name.lower()
            if any(token in name for token in DIRECTIONAL_HINT_KEYWORDS):
                findings.append(
                    {
                        "code": "semantic_prior_from_example_naming",
                        "path": f"examples/{child.name}",
                        "severity": "directional_only",
                        "evidence": "example naming implies governance semantics",
                    }
                )
                break

    # classification reducer
    severities = {f["severity"] for f in findings}
    if "invalid" in severities:
        classification = "baseline_invalid"
    elif "degraded" in severities:
        classification = "baseline_degraded"
    elif "directional_only" in severities:
        classification = "baseline_directional_only"
    else:
        classification = "clean"

    if classification == "baseline_invalid":
        comparison_allowed = False
        conclusion_strength = "do_not_compare"
        ok = False
    elif classification == "baseline_degraded":
        comparison_allowed = True
        conclusion_strength = "compare_with_caution"
        ok = False
    elif classification == "baseline_directional_only":
        comparison_allowed = True
        conclusion_strength = "directional_observation_only"
        ok = False
    else:
        comparison_allowed = True
        conclusion_strength = "comparative_smoke_result_allowed"
        ok = True

    return {
        "ok": ok,
        "baseline_classification": classification,
        "findings": findings,
        "comparison_allowed": comparison_allowed,
        "conclusion_strength": conclusion_strength,
        "claim_boundary": "Baseline validation establishes absence of known detectable governance surfaces, not proof of absolute governance absence.",
    }


def format_human(result: dict[str, Any]) -> str:
    lines = [
        "[ab_baseline_validator]",
        f"ok={result['ok']}",
        f"baseline_classification={result['baseline_classification']}",
        f"comparison_allowed={result['comparison_allowed']}",
        f"conclusion_strength={result['conclusion_strength']}",
        f"claim_boundary={result['claim_boundary']}",
    ]
    for f in result.get("findings", []):
        lines.append(
            f"- {f['severity']} {f['code']} path={f['path']} evidence={f['evidence']}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate A/B Group A baseline sanitization.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    result = validate_ab_baseline(Path(args.project_root).resolve())
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human(result))
    return 0 if result["comparison_allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
