#!/usr/bin/env python3
"""
Read a reviewer-handoff MANIFEST.json as a reviewer-first summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.human_summary import build_summary_line


def default_manifest_path(project_root: Path, *, release_version: str) -> Path:
    return project_root / "artifacts" / "reviewer-handoff" / release_version / "MANIFEST.json"


def assess_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.is_file():
        return {
            "ok": False,
            "exists": False,
            "manifest_file": str(manifest_path),
            "error": "manifest_not_found",
        }

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "exists": True,
            "manifest_file": str(manifest_path),
            "error": f"manifest_unreadable: {exc}",
        }

    return {
        "ok": bool(payload.get("ok", False)),
        "upstream_ok": bool(payload.get("upstream_ok", payload.get("ok", False))),
        "handoff_clean_identity": payload.get("handoff_clean_identity"),
        "exists": True,
        "manifest_file": str(manifest_path),
        "generated_at": payload.get("generated_at"),
        "project_root": payload.get("project_root"),
        "plan_path": payload.get("plan_path"),
        "release_version": payload.get("release_version"),
        "contract_path": payload.get("contract_path"),
        "external_contract_repos": payload.get("external_contract_repos") or [],
        "external_contract_repo_count": payload.get("external_contract_repo_count"),
        "strict_runtime": payload.get("strict_runtime"),
        "trust_ok": payload.get("trust_ok"),
        "release_ok": payload.get("release_ok"),
        "lint_status": payload.get("lint_status"),
        "lint_violation_count": payload.get("lint_violation_count"),
        "lint_highest_severity": payload.get("lint_highest_severity"),
        "lint_violations": payload.get("lint_violations") or [],
        "lint_policy": payload.get("lint_policy") or {},
        "override_decision_reason": payload.get("override_decision_reason"),
        "latest_json": (payload.get("latest") or {}).get("json"),
        "latest_txt": (payload.get("latest") or {}).get("text"),
        "latest_md": (payload.get("latest") or {}).get("markdown"),
        "history_json": (payload.get("history") or {}).get("json"),
        "history_txt": (payload.get("history") or {}).get("text"),
        "history_md": (payload.get("history") or {}).get("markdown"),
        "index_md": payload.get("index"),
        "readme_md": payload.get("readme"),
    }


def _severity_rank(level: str) -> int:
    if level == "high":
        return 3
    if level == "medium":
        return 2
    if level == "low":
        return 1
    return 0


def format_human_result(result: dict[str, Any]) -> str:
    summary_line = build_summary_line(
        f"ok={result['ok']}",
        f"upstream_ok={result.get('upstream_ok')}",
        f"trust={result.get('trust_ok')}",
        f"release={result.get('release_ok')}",
        f"lint={result.get('lint_status')}",
        f"release_version={result.get('release_version')}",
        f"contract={result.get('contract_path') or 'none'}",
    )
    lines = [
        summary_line,
        "[reviewer_handoff_reader]",
        f"manifest_file={result['manifest_file']}",
        f"exists={result['exists']}",
        f"release_version={result.get('release_version')}",
        f"generated_at={result.get('generated_at')}",
        f"plan_path={result.get('plan_path')}",
        f"contract_path={result.get('contract_path')}",
        f"external_contract_repo_count={result.get('external_contract_repo_count')}",
        f"strict_runtime={result.get('strict_runtime')}",
        f"trust_ok={result.get('trust_ok')}",
        f"release_ok={result.get('release_ok')}",
        f"handoff_clean_identity={result.get('handoff_clean_identity')}",
        f"lint_status={result.get('lint_status')}",
        f"lint_violation_count={result.get('lint_violation_count')}",
        f"lint_highest_severity={result.get('lint_highest_severity')}",
    ]
    lint_policy = result.get("lint_policy") or {}
    sorted_violations = sorted(
        result.get("lint_violations") or [],
        key=lambda item: (
            -_severity_rank(str(item.get("severity", "low"))),
            str(item.get("claim_type", "")),
            str(item.get("excerpt", "")),
        ),
    )
    top_excerpt = sorted_violations[0].get("excerpt") if sorted_violations else None
    lines.extend(
        [
            "[policy_not_clean]",
            f"lint_status={result.get('lint_status')}",
            f"override_reason_code={lint_policy.get('override_reason_code')}",
            f"override_decision_reason={result.get('override_decision_reason') or lint_policy.get('override_decision_reason')}",
            f"override_blocked_by_non_overridable={lint_policy.get('override_blocked_by_non_overridable')}",
            "non_overridable_claim_types="
            + ",".join(lint_policy.get("non_overridable_claim_types") or []),
            f"top_violation_excerpt={top_excerpt}",
        ]
    )
    lines.extend(
        [
            f"lint_fail_on_non_clean={lint_policy.get('fail_on_non_clean')}",
            f"lint_allow_non_clean={lint_policy.get('allow_non_clean')}",
            f"lint_override_active={lint_policy.get('override_active')}",
            f"lint_override_source={lint_policy.get('override_source')}",
        ]
    )

    if result.get("error"):
        lines.append(f"error={result['error']}")
        return "\n".join(lines)

    lines.extend(
        [
            "[lint_violations]",
        ]
    )
    for v in sorted_violations:
        lines.append(
            f"{v.get('severity')}|{v.get('claim_type')}|{v.get('excerpt')}"
        )
    lines.extend(
        [
            "[latest]",
            f"json={result.get('latest_json')}",
            f"text={result.get('latest_txt')}",
            f"markdown={result.get('latest_md')}",
            "[history]",
            f"json={result.get('history_json')}",
            f"text={result.get('history_txt')}",
            f"markdown={result.get('history_md')}",
            "[paths]",
            f"index_md={result.get('index_md')}",
            f"readme_md={result.get('readme_md')}",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read a reviewer-handoff manifest.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--file")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if args.file:
        manifest_path = Path(args.file).resolve()
    else:
        manifest_path = default_manifest_path(project_root, release_version=args.release_version)

    result = assess_manifest(manifest_path)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human_result(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
