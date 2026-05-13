#!/usr/bin/env python3
"""
Run a minimal framework quickstart smoke so onboarding docs map to a real command.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.contract_context import contract_label, extract_contract_context
from governance_tools.domain_governance_metadata import domain_risk_tier
from runtime_hooks.core.pre_task_check import run_pre_task_check
from runtime_hooks.core.session_start import build_session_start_context


def run_quickstart_smoke(
    *,
    project_root: Path,
    plan_path: Path,
    contract_file: Path | None = None,
    task_text: str = "Quickstart governance smoke",
) -> dict[str, Any]:
    session_rules = "common"

    pre_task = run_pre_task_check(
        project_root=project_root,
        rules="common",
        risk="low",
        oversight="review-required",
        memory_mode="candidate",
        task_text=task_text,
    )

    session_start = build_session_start_context(
        project_root=project_root,
        plan_path=plan_path,
        rules=session_rules,
        risk="medium" if contract_file else "low",
        oversight="review-required",
        memory_mode="candidate",
        task_text=task_text,
        contract_file=contract_file,
        task_level="L1",
    )

    contract_context = extract_contract_context(session_start)
    return {
        "ok": pre_task["ok"] and session_start["ok"],
        "project_root": str(project_root),
        "plan_path": str(plan_path),
        "contract_path": str(contract_file.resolve()) if contract_file else None,
        "contract_mode": "explicit" if contract_file else "repo-default",
        "contract_context": contract_context,
        "pre_task_ok": pre_task["ok"],
        "session_start_ok": session_start["ok"],
        "pre_task": pre_task,
        "session_start": session_start,
    }


def format_human_result(result: dict[str, Any]) -> str:
    contract_context = result.get("contract_context") or {}
    label = contract_label(contract_context)
    risk_tier = contract_context.get("risk_tier") or domain_risk_tier(contract_context.get("domain"))

    lines = [
        "[quickstart_smoke]",
        f"ok={result['ok']}",
        (
            "summary="
            + " | ".join(
                part
                for part in (
                    f"ok={result['ok']}",
                    f"pre_task_ok={result['pre_task_ok']}",
                    f"session_start_ok={result['session_start_ok']}",
                    (
                        f"contract={label}/{risk_tier}"
                        if label and risk_tier and risk_tier != "unknown"
                        else (f"contract={label}" if label else None)
                    ),
                )
                if part
            )
        ),
        f"project_root={result['project_root']}",
        f"plan_path={result['plan_path']}",
        f"contract_path={result.get('contract_path')}",
        f"contract_mode={result.get('contract_mode')}",
        f"pre_task_ok={result['pre_task_ok']}",
        f"session_start_ok={result['session_start_ok']}",
    ]

    if result.get("contract_mode") == "repo-default" and result.get("contract_path") is None:
        lines.append("contract_note=no explicit --contract provided; using repo-local governance defaults")

    if result["pre_task"].get("suggested_rules_preview"):
        lines.append(
            "pre_task_suggested_rules_preview="
            + ",".join(result["pre_task"]["suggested_rules_preview"])
        )

    if result["session_start"].get("suggested_rules_preview"):
        lines.append(
            "session_start_suggested_rules_preview="
            + ",".join(result["session_start"]["suggested_rules_preview"])
        )

    if label:
        lines.append(f"contract={label}")
    if risk_tier:
        lines.append(f"contract_risk_tier={risk_tier}")

    pre_warnings = result["pre_task"].get("warnings") or []
    session_warnings = result["session_start"].get("pre_task_check", {}).get("warnings", []) or []
    if pre_warnings:
        lines.append(f"pre_task_warnings={len(pre_warnings)}")
    if session_warnings:
        lines.append(f"session_start_warnings={len(session_warnings)}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the documented framework quickstart as a smoke check.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--plan", default="PLAN.md")
    parser.add_argument("--contract")
    parser.add_argument("--task-text", default="Quickstart governance smoke")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    result = run_quickstart_smoke(
        project_root=Path(args.project_root).resolve(),
        plan_path=Path(args.plan),
        contract_file=Path(args.contract).resolve() if args.contract else None,
        task_text=args.task_text,
    )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human_result(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
