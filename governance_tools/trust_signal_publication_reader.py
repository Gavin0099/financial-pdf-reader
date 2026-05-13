#!/usr/bin/env python3
"""
Read a generated trust-signal publication manifest as a stable reviewer-facing summary.
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

DEFAULT_MANIFEST = Path("artifacts") / "trust-signals" / "PUBLICATION_MANIFEST.json"
DEFAULT_DOCS_STATUS_MANIFEST = Path("docs") / "status" / "generated" / "PUBLICATION_MANIFEST.json"


def default_manifest_path(project_root: Path) -> Path:
    return project_root / DEFAULT_MANIFEST


def default_docs_status_manifest_path(project_root: Path) -> Path:
    return project_root / DEFAULT_DOCS_STATUS_MANIFEST


def assess_publication_manifest(manifest_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "manifest_file": str(manifest_path),
        "exists": False,
        "errors": [],
    }
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result["errors"].append("manifest file not found")
        return result
    except (OSError, json.JSONDecodeError) as exc:
        result["errors"].append(f"failed to read manifest: {exc}")
        return result

    result.update(payload)
    result["exists"] = True
    result["manifest_file"] = str(manifest_path)
    result["ok"] = bool(payload.get("ok"))
    result["bundle_published"] = bool(payload.get("bundle_published", payload.get("bundle") is not None))
    result["status_pages_published"] = bool(
        payload.get("status_pages_published", payload.get("published") is not None)
    )
    result.setdefault("errors", [])
    return result


def format_human_result(result: dict[str, Any]) -> str:
    summary = build_summary_line(
        f"ok={result.get('ok')}",
        f"release={result.get('release_version')}",
        f"bundle={result.get('bundle_published')}",
        f"published={result.get('status_pages_published')}",
        (
            f"external_contracts={result.get('external_contract_policy_ok')}"
            if result.get("external_contract_repo_count") is not None
            else None
        ),
        f"contract={result.get('contract_path') or 'none'}",
    )
    lines = [
        summary,
        "[trust_signal_publication]",
        f"manifest_file={result.get('manifest_file')}",
        f"exists={result.get('exists')}",
        f"generated_at={result.get('generated_at')}",
        f"project_root={result.get('project_root')}",
        f"publication_root={result.get('publication_root')}",
        f"publication_readme={result.get('readme_md')}",
        f"release_version={result.get('release_version')}",
        f"contract_path={result.get('contract_path')}",
        f"external_contract_repo_count={result.get('external_contract_repo_count')}",
        f"external_contract_policy_ok={result.get('external_contract_policy_ok')}",
        f"external_contract_profile_counts={result.get('external_contract_profile_counts')}",
        f"strict_runtime={result.get('strict_runtime')}",
        f"bundle_published={result.get('bundle_published')}",
        f"status_pages_published={result.get('status_pages_published')}",
    ]
    errors = result.get("errors") or []
    if errors:
        lines.append("[errors]")
        lines.extend(errors)

    bundle = result.get("bundle")
    if isinstance(bundle, dict):
        lines.append("[bundle]")
        for key in (
            "latest_json",
            "latest_txt",
            "latest_md",
            "index_md",
            "manifest_json",
            "external_policy_latest_md",
            "external_policy_latest_json",
            "external_policy_history_md",
            "external_policy_history_json",
        ):
            value = bundle.get(key)
            if value:
                lines.append(f"{key}={value}")

    published = result.get("published")
    if isinstance(published, dict):
        lines.append("[published]")
        for key in (
            "latest_md",
            "latest_json",
            "readme_md",
            "index_md",
            "manifest_json",
            "external_policy_md",
            "external_policy_json",
        ):
            value = published.get(key)
            if value:
                lines.append(f"{key}={value}")

    policies = result.get("external_contract_policies")
    if isinstance(policies, list) and policies:
        lines.append("[external_contract_policies]")
        for entry in policies:
            repo_root = entry.get("repo_root")
            if not entry.get("ok"):
                lines.append(f"{repo_root} | ok=False | error={entry.get('error')}")
                continue
            hard_stop_rules = ",".join(entry.get("hard_stop_rules") or []) or "-"
            lines.append(
                " | ".join(
                    [
                        str(repo_root),
                        f"domain={entry.get('domain')}",
                        f"profile={entry.get('enforcement_profile')}",
                        f"validators={entry.get('validator_ready_count')}/{entry.get('validator_count')}",
                        f"hard_stop_rules={hard_stop_rules}",
                    ]
                )
            )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read a generated trust-signal publication manifest.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--file")
    parser.add_argument("--docs-status", action="store_true")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    parser.add_argument("--output")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if args.file:
        manifest_path = Path(args.file).resolve()
    elif args.docs_status:
        manifest_path = default_docs_status_manifest_path(project_root)
    else:
        manifest_path = default_manifest_path(project_root)
    result = assess_publication_manifest(manifest_path)
    if args.format == "json":
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        rendered = format_human_result(result)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")

    print(rendered)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
