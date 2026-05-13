#!/usr/bin/env python3
"""
Aggregate the current release-facing package into one reviewer-friendly summary.
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
from governance_tools.release_readiness import assess_release_readiness


def _document(name: str, path: Path, *, required: bool = True) -> dict[str, Any]:
    return {
        "name": name,
        "path": str(path),
        "exists": path.is_file(),
        "required": required,
    }


def assess_release_package(project_root: Path, *, version: str) -> dict[str, Any]:
    readiness = assess_release_readiness(project_root, version=version)

    release_docs = [
        _document("release_note", project_root / "docs" / "releases" / f"{version}.md"),
        _document("github_release_draft", project_root / "docs" / "releases" / f"{version}-github-release.md"),
        _document("publish_checklist", project_root / "docs" / "releases" / f"{version}-publish-checklist.md"),
        _document("alpha_checklist", project_root / "docs" / "releases" / "alpha-checklist.md"),
        _document("changelog", project_root / "CHANGELOG.md"),
    ]
    status_docs = [
        _document("status_index", project_root / "docs" / "status" / "README.md"),
        _document("trust_signal_dashboard", project_root / "docs" / "status" / "trust-signal-dashboard.md"),
        _document("runtime_status", project_root / "docs" / "status" / "runtime-governance-status.md"),
        _document("domain_enforcement_matrix", project_root / "docs" / "status" / "domain-enforcement-matrix.md"),
        _document("generated_status_root", project_root / "docs" / "status" / "generated" / "README.md", required=False),
    ]
    commands = [
        {
            "name": "release_readiness",
            "command": f"python governance_tools/release_readiness.py --version {version} --format human",
        },
        {
            "name": "release_surface_overview",
            "command": f"python governance_tools/release_surface_overview.py --version {version} --format human",
        },
        {
            "name": "trust_signal_overview",
            "command": "python governance_tools/trust_signal_overview.py --project-root . --plan PLAN.md "
            f"--release-version {version} --contract examples/usb-hub-contract/contract.yaml --format human",
        },
        {
            "name": "trust_signal_snapshot_docs_status",
            "command": "python governance_tools/trust_signal_snapshot.py --project-root . --plan PLAN.md "
            f"--release-version {version} --contract examples/usb-hub-contract/contract.yaml --publish-docs-status --format human",
        },
        {
            "name": "trust_signal_publication_reader_docs_status",
            "command": "python governance_tools/trust_signal_publication_reader.py --project-root . --docs-status --format human",
        },
        {
            "name": "phase_gates",
            "command": "bash scripts/verify_phase_gates.sh",
        },
    ]

    return {
        "ok": readiness["ok"],
        "project_root": str(project_root),
        "version": version,
        "readiness": readiness,
        "release_docs": release_docs,
        "status_docs": status_docs,
        "commands": commands,
        "release_doc_count": len(release_docs),
        "status_doc_count": len(status_docs),
        "existing_release_docs": sum(1 for item in release_docs if item["exists"]),
        "existing_status_docs": sum(1 for item in status_docs if item["exists"]),
    }


def format_human_result(result: dict[str, Any]) -> str:
    summary_line = build_summary_line(
        f"ok={result['ok']}",
        f"version={result['version']}",
        f"release_docs={result['existing_release_docs']}/{result['release_doc_count']}",
        f"status_docs={result['existing_status_docs']}/{result['status_doc_count']}",
        f"readiness_checks={len(result['readiness']['checks'])}",
    )
    lines = [
        summary_line,
        "[release_package_summary]",
        f"project_root={result['project_root']}",
        f"version={result['version']}",
        f"ok={result['ok']}",
    ]

    lines.append("[release_docs]")
    for item in result["release_docs"]:
        lines.append(f"{item['name']} | exists={item['exists']} | path={item['path']}")

    lines.append("[status_docs]")
    for item in result["status_docs"]:
        lines.append(
            f"{item['name']} | exists={item['exists']} | required={item['required']} | path={item['path']}"
        )

    lines.append("[commands]")
    for item in result["commands"]:
        lines.append(f"{item['name']}={item['command']}")

    if result["readiness"]["warnings"]:
        lines.append("[readiness_warnings]")
        for item in result["readiness"]["warnings"]:
            lines.append(str(item))

    if result["readiness"]["errors"]:
        lines.append("[readiness_errors]")
        for item in result["readiness"]["errors"]:
            lines.append(str(item))

    return "\n".join(lines)


def format_markdown_result(result: dict[str, Any]) -> str:
    summary_line = build_summary_line(
        f"ok={result['ok']}",
        f"version={result['version']}",
        f"release_docs={result['existing_release_docs']}/{result['release_doc_count']}",
        f"status_docs={result['existing_status_docs']}/{result['status_doc_count']}",
        f"readiness_checks={len(result['readiness']['checks'])}",
    )
    lines = [
        "# Release Package Summary",
        "",
        f"- Summary: `{summary_line}`",
        f"- Project root: `{result['project_root']}`",
        f"- Release version: `{result['version']}`",
        "",
        "## Release Docs",
        "",
        "| Name | Exists | Path |",
        "| --- | --- | --- |",
    ]
    for item in result["release_docs"]:
        lines.append(f"| `{item['name']}` | `{item['exists']}` | `{item['path']}` |")

    lines.extend(
        [
            "",
            "## Status Docs",
            "",
            "| Name | Exists | Required | Path |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in result["status_docs"]:
        lines.append(
            f"| `{item['name']}` | `{item['exists']}` | `{item['required']}` | `{item['path']}` |"
        )

    lines.extend(
        [
            "",
            "## Suggested Commands",
            "",
        ]
    )
    for item in result["commands"]:
        lines.append(f"- `{item['command']}`")

    if result["readiness"]["warnings"]:
        lines.extend(["", "## Readiness Warnings", ""])
        for item in result["readiness"]["warnings"]:
            lines.append(f"- {item}")

    if result["readiness"]["errors"]:
        lines.extend(["", "## Readiness Errors", ""])
        for item in result["readiness"]["errors"]:
            lines.append(f"- {item}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize the current release-facing package.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--version", required=True)
    parser.add_argument("--format", choices=("human", "json", "markdown"), default="human")
    parser.add_argument("--output")
    args = parser.parse_args()

    result = assess_release_package(Path(args.project_root).resolve(), version=args.version)
    if args.format == "json":
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
    elif args.format == "markdown":
        rendered = format_markdown_result(result)
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
