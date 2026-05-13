#!/usr/bin/env python3
"""
Read a release-package MANIFEST.json as a reviewer-first summary.
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


def default_manifest_path(project_root: Path, *, version: str) -> Path:
    return project_root / "artifacts" / "release-package" / version / "MANIFEST.json"


def default_docs_release_manifest_path(project_root: Path, *, version: str) -> Path:
    return project_root / "docs" / "releases" / "generated" / version / "MANIFEST.json"


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
        "exists": True,
        "manifest_file": str(manifest_path),
        "generated_at": payload.get("generated_at"),
        "project_root": payload.get("project_root"),
        "version": payload.get("version"),
        "release_doc_count": payload.get("release_doc_count"),
        "status_doc_count": payload.get("status_doc_count"),
        "existing_release_docs": payload.get("existing_release_docs"),
        "existing_status_docs": payload.get("existing_status_docs"),
        "latest_json": (payload.get("latest") or {}).get("json"),
        "latest_txt": (payload.get("latest") or {}).get("text"),
        "latest_md": (payload.get("latest") or {}).get("markdown"),
        "history_json": (payload.get("history") or {}).get("json"),
        "history_txt": (payload.get("history") or {}).get("text"),
        "history_md": (payload.get("history") or {}).get("markdown"),
        "index_md": payload.get("index"),
        "readme_md": payload.get("readme"),
    }


def format_human_result(result: dict[str, Any]) -> str:
    summary_line = build_summary_line(
        f"ok={result['ok']}",
        f"version={result.get('version')}",
        f"release_docs={result.get('existing_release_docs')}/{result.get('release_doc_count')}",
        f"status_docs={result.get('existing_status_docs')}/{result.get('status_doc_count')}",
    )
    lines = [
        summary_line,
        "[release_package_reader]",
        f"manifest_file={result['manifest_file']}",
        f"exists={result['exists']}",
        f"version={result.get('version')}",
        f"generated_at={result.get('generated_at')}",
    ]

    if result.get("error"):
        lines.append(f"error={result['error']}")
        return "\n".join(lines)

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
    parser = argparse.ArgumentParser(description="Read a release-package manifest.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--version", required=True)
    parser.add_argument("--file")
    parser.add_argument("--docs-release", action="store_true")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if args.file:
        manifest_path = Path(args.file).resolve()
    elif args.docs_release:
        manifest_path = default_docs_release_manifest_path(project_root, version=args.version)
    else:
        manifest_path = default_manifest_path(project_root, version=args.version)

    result = assess_manifest(manifest_path)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human_result(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
