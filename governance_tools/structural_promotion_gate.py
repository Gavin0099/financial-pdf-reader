#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.memory_authority_guard import run_guard

_CLAIM_BOUNDARY = re.compile(r"^\s*-\s*claim_boundary:\s*`?([^`]+?)`?\s*$", re.IGNORECASE | re.MULTILINE)
_TEST_EXEC_DEGRADED = re.compile(
    r"^\s*-\s*test_execution_degraded_reason:\s*`?([^`]+?)`?\s*$", re.IGNORECASE | re.MULTILINE
)
_SECTION_H2 = re.compile(r"^##\s+", re.MULTILINE)
_PROMOTION_STATUS = re.compile(r"<!--\s*promotion_status:\s*(\w+)\s*-->", re.IGNORECASE)
_PROMOTED_BY = re.compile(r"<!--\s*promoted_by:\s*.+?-->", re.IGNORECASE)
_PROMOTED_AT = re.compile(r"<!--\s*promoted_at:\s*.+?-->", re.IGNORECASE)
_SOURCE_ANCHOR = re.compile(r"<!--\s*source_anchor:\s*.+?-->", re.IGNORECASE)


def _read_closeout(closeout_path: Path) -> tuple[str, str]:
    if not closeout_path.exists():
        return "", ""
    text = closeout_path.read_text(encoding="utf-8")
    claim = ""
    degraded = ""
    m1 = _CLAIM_BOUNDARY.search(text)
    if m1:
        claim = m1.group(1).strip()
    m2 = _TEST_EXEC_DEGRADED.search(text)
    if m2:
        degraded = m2.group(1).strip()
    return claim, degraded


def _has_required_authoritative_markers(memory_root: Path) -> bool:
    p = memory_root / "00_long_term.md"
    if not p.exists():
        return False
    text = p.read_text(encoding="utf-8")
    sections = _SECTION_H2.split(text)
    for section in sections:
        if not section.strip():
            continue
        status = _PROMOTION_STATUS.search(section)
        if not status or status.group(1).strip().lower() != "authoritative":
            continue
        if not (_PROMOTED_BY.search(section) and _PROMOTED_AT.search(section) and _SOURCE_ANCHOR.search(section)):
            return False
    return True


def evaluate_gate(memory_root: Path, project_root: Path, closeout_path: Path) -> dict[str, Any]:
    guard = run_guard(memory_root, project_root, skip_git=True)
    structural = guard.get("authority_coverage_rate", {}).get("structural", {})
    structural_rate = structural.get("rate")
    claim_boundary, degraded_reason = _read_closeout(closeout_path)

    blocked_reasons: list[str] = []
    if structural_rate in (None, 0, 0.0):
        blocked_reasons.append("missing_structural_promotions")
    if claim_boundary and claim_boundary != "runtime_verified":
        blocked_reasons.append("claim_boundary_not_runtime_verified")
    if degraded_reason:
        blocked_reasons.append("test_execution_degraded")
    if not _has_required_authoritative_markers(memory_root):
        blocked_reasons.append("missing_required_promotion_markers")

    promotion_allowed = len(blocked_reasons) == 0
    failure_class = ""
    if "test_execution_degraded" in blocked_reasons or "claim_boundary_not_runtime_verified" in blocked_reasons:
        failure_class = "runtime_unverifiable"
    elif blocked_reasons:
        failure_class = "authority_unqualified"

    return {
        "ok": promotion_allowed,
        "promotion_allowed": promotion_allowed,
        "failure_class": failure_class,
        "blocked_reasons": blocked_reasons,
        "claim_boundary": claim_boundary or "unknown",
        "test_execution_degraded_reason": degraded_reason or "",
        "structural_authority_rate": structural_rate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Structural Promotion Gate v0.1")
    parser.add_argument("--memory-root", default="memory")
    parser.add_argument("--project-root", default=".")
    parser.add_argument(
        "--closeout",
        default="governance/STRUCTURAL_PROMOTION_COVERAGE_CLOSEOUT_2026-04-30.md",
    )
    args = parser.parse_args()

    result = evaluate_gate(Path(args.memory_root), Path(args.project_root), Path(args.closeout))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["promotion_allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
