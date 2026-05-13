#!/usr/bin/env python3
"""
Smoke-check the first-slice execution surface coverage model.

This does not alter runtime verdicts. It only reports whether the current repo
is missing hard/soft coverage requirements or contains dead surfaces.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.execution_surface_coverage import (
    build_execution_surface_coverage,
    coverage_has_signal,
)
from governance_tools.framework_versioning import repo_root_from_tooling


@dataclass
class ExecutionSurfaceCoverageSmokeResult:
    ok: bool
    repo_root: str
    repo_commit: str | None
    consumer: str
    signal_posture: str
    missing_hard_required: list[dict] = field(default_factory=list)
    missing_soft_required: list[dict] = field(default_factory=list)
    dead_never_observed: list[dict] = field(default_factory=list)
    dead_never_required: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def check_execution_surface_coverage(repo_root: Path | None = None) -> ExecutionSurfaceCoverageSmokeResult:
    root = (repo_root or repo_root_from_tooling()).resolve()
    payload = build_execution_surface_coverage(root)
    coverage = payload["coverage"]
    return ExecutionSurfaceCoverageSmokeResult(
        ok=not coverage_has_signal(payload),
        repo_root=str(root),
        repo_commit=payload.get("repo_commit"),
        consumer=payload["consumer"],
        signal_posture=payload["signal_posture"],
        missing_hard_required=coverage["missing_hard_required"],
        missing_soft_required=coverage["missing_soft_required"],
        dead_never_observed=coverage["dead_surfaces"]["never_observed"],
        dead_never_required=coverage["dead_surfaces"]["never_required"],
    )


def format_human(result: ExecutionSurfaceCoverageSmokeResult) -> str:
    lines = [
        "[execution_surface_coverage_smoke]",
        f"ok={result.ok}",
        f"repo_root={result.repo_root}",
        f"repo_commit={result.repo_commit}",
        f"consumer={result.consumer}",
        f"signal_posture={result.signal_posture}",
        f"missing_hard_required={len(result.missing_hard_required)}",
        f"missing_soft_required={len(result.missing_soft_required)}",
        f"dead_never_observed={len(result.dead_never_observed)}",
        f"dead_never_required={len(result.dead_never_required)}",
    ]
    if result.missing_hard_required:
        lines.append("[missing_hard_required]")
        for item in result.missing_hard_required:
            lines.append(f"  - {item['decision']}::{item['surface_name']}::{item['coverage_role']}")
    if result.missing_soft_required:
        lines.append("[missing_soft_required]")
        for item in result.missing_soft_required:
            lines.append(f"  - {item['decision']}::{item['surface_name']}::{item['coverage_role']}")
    if result.dead_never_observed:
        lines.append("[dead_never_observed]")
        for item in result.dead_never_observed:
            lines.append(f"  - {item['surface_name']}::{item['coverage_role']}::{item['requirement_level']}")
    if result.dead_never_required:
        lines.append("[dead_never_required]")
        for item in result.dead_never_required:
            lines.append(f"  - {item['surface_name']}::{item['coverage_role']}::{item['requirement_level']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-check execution surface coverage signals.")
    parser.add_argument("--repo-root", help="Framework repo root (default: auto-detect).")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else None
    result = check_execution_surface_coverage(repo_root)
    if args.format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_human(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
