#!/usr/bin/env python3
"""
Repo-level adoption audit for Phase 3 promotion gate.

Goal:
- Detect parallel/legacy promotion paths outside canonical gate modules
- Provide a deterministic check that promotion logic stays centralized
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

_SCOPES = ("governance_tools", "scripts")
_WORKFLOW_SCOPE = ".github/workflows"
_DOC_SCOPE = "docs"

_ALLOW_CLOSURE_VERIFIED = {
    "governance_tools/phase2_aggregation_consumer.py",
    "governance_tools/phase3_promotion_gate.py",
    "governance_tools/phase3_gate_adoption_audit.py",
    "governance_tools/external_observation_adapter.py",
    "governance_tools/enumd_observe_only_probe.py",
    "scripts/phase2_aggregation_dry_run.py",
}

_ALLOW_PHASE3_ENTRY_ALLOWED = {
    "governance_tools/phase3_promotion_gate.py",
    "governance_tools/phase3_gate_adoption_audit.py",
    "governance_tools/external_observation_adapter.py",
    "governance_tools/enumd_observe_only_probe.py",
}

# Policy dict for files allowed to reference current_state/promote_eligible with phase3 terms.
# Each entry carries: reason, source_commit, admitted_date, review_required,
#   invalid_if.pattern (grep-enforced), invalid_if.semantic (human-audit only).
#
# Files in this dict are explicitly exempted from the parallel-decision scan.
# If a file exhibits any invalid_if.pattern, it is flagged as having grown
# beyond its sanctioned scope (early warning, not a hard block).
_ALLOW_PARALLEL_DECISION_SCAN: dict[str, dict] = {
    "governance_tools/phase3_promotion_gate.py": {
        "reason": "canonical phase3 promotion gate — defines the decision boundary",
        "review_required": False,
        "invalid_if": {"pattern": [], "semantic": []},
    },
    "governance_tools/phase3_gate_adoption_audit.py": {
        "reason": "adoption audit reads all decision patterns to verify gate centralization",
        "review_required": False,
        "invalid_if": {"pattern": [], "semantic": []},
    },
    "governance_tools/external_observation_adapter.py": {
        "reason": "external observation adapter — observe-only, no promotion decisions",
        "review_required": False,
        "invalid_if": {"pattern": [], "semantic": []},
    },
    "governance_tools/enumd_observe_only_probe.py": {
        "reason": "observe-only probe — no promotion decisions",
        "review_required": False,
        "invalid_if": {"pattern": [], "semantic": []},
    },
    "scripts/phase2_aggregation_dry_run.py": {
        "reason": "dry-run script — reads phase2 aggregation state, no real promotion decisions",
        "review_required": False,
        "invalid_if": {"pattern": [], "semantic": []},
    },
    "governance_tools/phase2_aggregation_consumer.py": {
        "reason": "uses current_state/promote_eligible as Phase 2 aggregation keys, not Phase 3 promotion logic",
        "source_commit": "551d433",
        "admitted_date": "2026-05-03",
        "review_required": True,
        "invalid_if": {
            "pattern": [
                "phase3_entry_allowed",
                "from governance_tools.phase3_promotion_gate import",
            ],
            "semantic": [
                "makes Phase 3 gate decisions directly without routing through phase3_promotion_gate.py",
                "imports phase3_promotion_gate for decision logic (not just metadata reference)",
            ],
        },
    },
}


def _iter_python_files(repo_root: Path) -> list[Path]:
    out: list[Path] = []
    for scope in _SCOPES:
        base = repo_root / scope
        if not base.exists():
            continue
        out.extend(sorted(base.rglob("*.py")))
    return out


def _iter_text_files(repo_root: Path, base: str, pattern: str) -> list[Path]:
    root = repo_root / base
    if not root.exists():
        return []
    return sorted(root.rglob(pattern))


def _read_text_fallback(path: Path) -> str:
    for enc in ("utf-8", "cp950", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    # Last resort: replace undecodable bytes.
    return path.read_text(encoding="utf-8", errors="replace")


def _check_stale_exceptions(max_days: int = 90) -> list[str]:
    """Return warning strings for allow-list entries overdue for re-review."""
    today = date.today()
    warnings: list[str] = []
    for file_path, meta in _ALLOW_PARALLEL_DECISION_SCAN.items():
        if not meta.get("review_required"):
            continue
        admitted_str = meta.get("admitted_date")
        if not admitted_str:
            warnings.append(f"review_required entry missing admitted_date: {file_path}")
            continue
        try:
            admitted = date.fromisoformat(admitted_str)
        except ValueError:
            continue
        age = (today - admitted).days
        if age > max_days:
            warnings.append(
                f"stale_exception:{file_path} admitted={admitted_str} age={age}d (max={max_days}d)"
            )
    return warnings


def audit_phase3_gate_adoption(repo_root: Path) -> dict[str, Any]:
    files = _iter_python_files(repo_root)
    workflow_files = _iter_text_files(repo_root, _WORKFLOW_SCOPE, "*.yml")
    doc_files = _iter_text_files(repo_root, _DOC_SCOPE, "*.md")
    violations: list[dict[str, str]] = []

    for fpath in files:
        rel = fpath.relative_to(repo_root).as_posix()
        text = fpath.read_text(encoding="utf-8")

        if "closure_verified" in text and rel not in _ALLOW_CLOSURE_VERIFIED:
            violations.append(
                {
                    "path": rel,
                    "rule": "closure_verified_outside_canonical_modules",
                    "detail": "closure_verified token found in non-allowlisted module",
                }
            )

        if "phase3_entry_allowed" in text and rel not in _ALLOW_PHASE3_ENTRY_ALLOWED:
            violations.append(
                {
                    "path": rel,
                    "rule": "phase3_entry_allowed_defined_outside_gate",
                    "detail": "phase3_entry_allowed should be produced only by phase3_promotion_gate.py",
                }
            )

        # Detect potential parallel phase3 decision logic.
        if rel not in _ALLOW_PARALLEL_DECISION_SCAN:
            has_core_keys = ("current_state" in text) and ("promote_eligible" in text)
            has_promotion_terms = ("phase3" in text.lower()) or ("promotion" in text.lower())
            if has_core_keys and has_promotion_terms:
                violations.append(
                    {
                        "path": rel,
                        "rule": "potential_parallel_phase3_decision_logic",
                        "detail": (
                            "module references current_state/promote_eligible with phase3/promotion "
                            "terms outside canonical gate"
                        ),
                    }
                )
        else:
            # File is in the allow-list — verify it hasn't grown beyond its sanctioned scope.
            entry_meta = _ALLOW_PARALLEL_DECISION_SCAN[rel]
            for pattern in entry_meta.get("invalid_if", {}).get("pattern", []):
                if pattern in text:
                    violations.append(
                        {
                            "path": rel,
                            "rule": "allowed_file_exhibits_forbidden_pattern",
                            "detail": (
                                f"allowed exception file matches invalid_if pattern: {pattern!r} — "
                                f"exception may have grown beyond its sanctioned scope"
                            ),
                        }
                    )

    # Workflow-level adoption proof:
    # if workflow references phase3 promotion authority terms, it must route via canonical gate module.
    for wf in workflow_files:
        rel = wf.relative_to(repo_root).as_posix()
        text = _read_text_fallback(wf)
        mentions_phase3_terms = any(
            token in text for token in ("phase3_entry_allowed", "promote_eligible", "closure_verified")
        )
        if mentions_phase3_terms and "phase3_promotion_gate.py" not in text:
            violations.append(
                {
                    "path": rel,
                    "rule": "workflow_phase3_terms_without_canonical_gate",
                    "detail": "workflow references phase3 promotion terms but does not route via phase3_promotion_gate.py",
                }
            )

    # Docs-level bypass check for explicit manual bypass instructions.
    _BYPASS_PATTERNS = (
        "skip phase3 gate",
        "bypass phase3 gate",
        "manual promote override",
        "direct promote without gate",
    )
    for doc in doc_files:
        rel = doc.relative_to(repo_root).as_posix()
        lower = _read_text_fallback(doc).lower()
        for pat in _BYPASS_PATTERNS:
            if pat in lower:
                violations.append(
                    {
                        "path": rel,
                        "rule": "doc_mentions_promotion_bypass",
                        "detail": f"documentation contains bypass phrase: {pat!r}",
                    }
                )

    stale_warnings = _check_stale_exceptions()
    return {
        "ok": len(violations) == 0,
        "checked_files": len(files),
        "checked_workflows": len(workflow_files),
        "checked_docs": len(doc_files),
        "violations": violations,
        "stale_warnings": stale_warnings,
        "policy_source": "phase3_gate_adoption_audit.v1",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Phase 3 promotion gate adoption consistency.")
    parser.add_argument("--project-root", default=".", help="Repository root")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    result = audit_phase3_gate_adoption(Path(args.project_root).resolve())
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("[phase3_gate_adoption_audit]")
        print(f"ok={result['ok']}")
        print(f"checked_files={result['checked_files']}")
        if result["violations"]:
            for v in result["violations"]:
                print(f"  [VIOLATION] {v['rule']} {v['path']}: {v['detail']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
