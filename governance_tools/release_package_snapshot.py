#!/usr/bin/env python3
"""
Generate a persistent release-package snapshot bundle from release_package_summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.release_package_summary import (
    assess_release_package,
    format_human_result,
    format_markdown_result,
)


def build_release_package_snapshot(*, project_root: Path, version: str) -> dict[str, Any]:
    package = assess_release_package(project_root, version=version)
    return {
        "ok": package["ok"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project_root),
        "version": version,
        "package": package,
    }


def _history_stem(snapshot: dict[str, Any]) -> str:
    dt = datetime.fromisoformat(snapshot["generated_at"].replace("Z", "+00:00"))
    return dt.strftime("%Y%m%d_%H%M%S")


def resolve_bundle_dir(
    *,
    project_root: Path,
    version: str,
    write_bundle: str | None = None,
    publish_docs_release: bool = False,
) -> Path | None:
    if write_bundle:
        return Path(write_bundle).resolve()
    if publish_docs_release:
        return (project_root / "docs" / "releases" / "generated" / version).resolve()
    return None


def format_index(history_dir: Path) -> str:
    json_files = sorted(history_dir.glob("*.json"))
    lines = ["[release_package_snapshot_index]", f"history_dir={history_dir}", f"reports={len(json_files)}"]
    if json_files:
        lines.append("[reports]")
        for path in reversed(json_files):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                lines.append(f"{path.name} | unreadable")
                continue
            package = payload.get("package") or {}
            lines.append(
                " | ".join(
                    [
                        path.name,
                        f"ok={payload.get('ok')}",
                        f"version={payload.get('version')}",
                        f"release_docs={package.get('existing_release_docs')}/{package.get('release_doc_count')}",
                        f"status_docs={package.get('existing_status_docs')}/{package.get('status_doc_count')}",
                        f"generated_at={payload.get('generated_at')}",
                    ]
                )
            )
    return "\n".join(lines)


def write_snapshot_bundle(snapshot: dict[str, Any], bundle_dir: Path) -> dict[str, str]:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    history_dir = bundle_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    stem = _history_stem(snapshot)
    latest_json = bundle_dir / "latest.json"
    latest_txt = bundle_dir / "latest.txt"
    latest_md = bundle_dir / "latest.md"
    history_json = history_dir / f"{stem}.json"
    history_txt = history_dir / f"{stem}.txt"
    history_md = history_dir / f"{stem}.md"
    index_md = bundle_dir / "INDEX.md"
    manifest_json = bundle_dir / "MANIFEST.json"
    publication_manifest_json = bundle_dir / "PUBLICATION_MANIFEST.json"
    publication_index_md = bundle_dir / "PUBLICATION_INDEX.md"
    readme_md = bundle_dir / "README.md"

    package = snapshot["package"]
    json_text = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    human_text = format_human_result(package) + "\n"
    markdown_text = format_markdown_result(package) + "\n"

    latest_json.write_text(json_text, encoding="utf-8")
    latest_txt.write_text(human_text, encoding="utf-8")
    latest_md.write_text(markdown_text, encoding="utf-8")
    history_json.write_text(json_text, encoding="utf-8")
    history_txt.write_text(human_text, encoding="utf-8")
    history_md.write_text(markdown_text, encoding="utf-8")
    index_md.write_text(format_index(history_dir) + "\n", encoding="utf-8")
    manifest_json.write_text(
        json.dumps(
            {
                "generated_at": snapshot["generated_at"],
                "project_root": snapshot["project_root"],
                "version": snapshot["version"],
                "ok": snapshot["ok"],
                "release_doc_count": package["release_doc_count"],
                "status_doc_count": package["status_doc_count"],
                "existing_release_docs": package["existing_release_docs"],
                "existing_status_docs": package["existing_status_docs"],
                "latest": {
                    "json": str(latest_json),
                    "text": str(latest_txt),
                    "markdown": str(latest_md),
                },
                "history": {
                    "json": str(history_json),
                    "text": str(history_txt),
                    "markdown": str(history_md),
                },
                "index": str(index_md),
                "readme": str(readme_md),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    publication_payload = {
        "ok": snapshot["ok"],
        "generated_at": snapshot["generated_at"],
        "project_root": snapshot["project_root"],
        "publication_root": str(bundle_dir),
        "publication_scope": "bundle",
        "version": snapshot["version"],
        "release_doc_count": package["release_doc_count"],
        "status_doc_count": package["status_doc_count"],
        "existing_release_docs": package["existing_release_docs"],
        "existing_status_docs": package["existing_status_docs"],
        "latest_json": str(latest_json),
        "latest_txt": str(latest_txt),
        "latest_md": str(latest_md),
        "history_json": str(history_json),
        "history_txt": str(history_txt),
        "history_md": str(history_md),
        "index_md": str(index_md),
        "manifest_json": str(manifest_json),
        "readme_md": str(readme_md),
    }
    publication_manifest_json.write_text(
        json.dumps(publication_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    publication_index_md.write_text(
        "\n".join(
            [
                "# Release Package Publication Index",
                "",
                f"- Publication scope: `bundle`",
                f"- Version: `{snapshot['version']}`",
                f"- Generated at: `{snapshot['generated_at']}`",
                f"- OK: `{snapshot['ok']}`",
                "",
                "## Paths",
                "",
                f"- Latest JSON: `{latest_json}`",
                f"- Latest Text: `{latest_txt}`",
                f"- Latest Markdown: `{latest_md}`",
                f"- History JSON: `{history_json}`",
                f"- History Text: `{history_txt}`",
                f"- History Markdown: `{history_md}`",
                f"- Bundle Index: `{index_md}`",
                f"- Bundle Manifest: `{manifest_json}`",
                f"- Bundle README: `{readme_md}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    readme_md.write_text(
        "\n".join(
            [
                "# Generated Release Package",
                "",
                "This directory contains generated release-package snapshots.",
                "",
                f"- Generated at: `{snapshot['generated_at']}`",
                f"- Release version: `{snapshot['version']}`",
                f"- Summary: `ok={snapshot['ok']} | release_docs={package['existing_release_docs']}/{package['release_doc_count']} | status_docs={package['existing_status_docs']}/{package['status_doc_count']}`",
                "",
                "## Entry Points",
                "",
                "- [Latest Markdown Summary](latest.md)",
                "- [Latest Human Summary](latest.txt)",
                "- [Latest JSON Snapshot](latest.json)",
                "- [History Index](INDEX.md)",
                "- `MANIFEST.json`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "latest_json": str(latest_json),
        "latest_txt": str(latest_txt),
        "latest_md": str(latest_md),
        "history_json": str(history_json),
        "history_txt": str(history_txt),
        "history_md": str(history_md),
        "index_md": str(index_md),
        "manifest_json": str(manifest_json),
        "publication_manifest_json": str(publication_manifest_json),
        "publication_index_md": str(publication_index_md),
        "readme_md": str(readme_md),
    }


def write_release_root_index(root_dir: Path, *, version: str, bundle_paths: dict[str, str]) -> dict[str, str]:
    root_dir.mkdir(parents=True, exist_ok=True)
    readme_md = root_dir / "README.md"
    latest_json = root_dir / "latest.json"
    latest_md = root_dir / "latest.md"
    publication_manifest_json = root_dir / "PUBLICATION_MANIFEST.json"
    publication_index_md = root_dir / "PUBLICATION_INDEX.md"

    manifest_path = Path(bundle_paths["manifest_json"])
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    relative_version_dir = Path(version).as_posix()

    latest_payload = {
        "version": version,
        "generated_at": manifest_payload.get("generated_at"),
        "ok": manifest_payload.get("ok"),
        "manifest_json": f"{relative_version_dir}/MANIFEST.json",
        "readme_md": f"{relative_version_dir}/README.md",
        "latest_md": f"{relative_version_dir}/latest.md",
        "latest_json": f"{relative_version_dir}/latest.json",
    }
    latest_json.write_text(json.dumps(latest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest_md.write_text(
        "\n".join(
            [
                "# Latest Generated Release Package",
                "",
                f"- Version: `{version}`",
                f"- Generated at: `{manifest_payload.get('generated_at')}`",
                f"- OK: `{manifest_payload.get('ok')}`",
                "",
                "## Entry Points",
                "",
                f"- [Version README]({relative_version_dir}/README.md)",
                f"- [Version Latest Markdown]({relative_version_dir}/latest.md)",
                f"- [Version Manifest]({relative_version_dir}/MANIFEST.json)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    readme_md.write_text(
        "\n".join(
            [
                "# Generated Release Packages",
                "",
                "This directory contains repo-local generated release-package snapshots.",
                "",
                f"- Latest version: `{version}`",
                f"- Latest summary: `ok={manifest_payload.get('ok')} | release_docs={manifest_payload.get('existing_release_docs')}/{manifest_payload.get('release_doc_count')} | status_docs={manifest_payload.get('existing_status_docs')}/{manifest_payload.get('status_doc_count')}`",
                "",
                "## Latest Entry Points",
                "",
                "- [Latest Overview](latest.md)",
                "- [Latest JSON Pointer](latest.json)",
                f"- [Version README]({relative_version_dir}/README.md)",
                f"- [Version Latest Markdown]({relative_version_dir}/latest.md)",
                f"- [Version Manifest]({relative_version_dir}/MANIFEST.json)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    publication_payload = {
        "ok": manifest_payload.get("ok"),
        "generated_at": manifest_payload.get("generated_at"),
        "project_root": manifest_payload.get("project_root"),
        "publication_root": str(root_dir),
        "publication_scope": "docs-release-root",
        "version": version,
        "release_doc_count": manifest_payload.get("release_doc_count"),
        "status_doc_count": manifest_payload.get("status_doc_count"),
        "existing_release_docs": manifest_payload.get("existing_release_docs"),
        "existing_status_docs": manifest_payload.get("existing_status_docs"),
        "latest_json": str(latest_json),
        "latest_md": str(latest_md),
        "readme_md": str(readme_md),
        "version_manifest_json": f"{relative_version_dir}/MANIFEST.json",
        "version_readme_md": f"{relative_version_dir}/README.md",
        "version_latest_md": f"{relative_version_dir}/latest.md",
    }
    publication_manifest_json.write_text(
        json.dumps(publication_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    publication_index_md.write_text(
        "\n".join(
            [
                "# Generated Release Publication Index",
                "",
                f"- Publication scope: `docs-release-root`",
                f"- Latest version: `{version}`",
                f"- Generated at: `{manifest_payload.get('generated_at')}`",
                f"- OK: `{manifest_payload.get('ok')}`",
                "",
                "## Paths",
                "",
                f"- Root README: `{readme_md.name}`",
                f"- Latest JSON Pointer: `{latest_json.name}`",
                f"- Latest Markdown Pointer: `{latest_md.name}`",
                f"- Version README: `{relative_version_dir}/README.md`",
                f"- Version Manifest: `{relative_version_dir}/MANIFEST.json`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "generated_root_readme_md": str(readme_md),
        "generated_root_latest_json": str(latest_json),
        "generated_root_latest_md": str(latest_md),
        "generated_root_publication_manifest_json": str(publication_manifest_json),
        "generated_root_publication_index_md": str(publication_index_md),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a release-package snapshot bundle.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--version", required=True)
    parser.add_argument("--format", choices=("human", "json", "markdown"), default="human")
    parser.add_argument("--output")
    parser.add_argument("--write-bundle")
    parser.add_argument("--publish-docs-release", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    snapshot = build_release_package_snapshot(project_root=project_root, version=args.version)
    package = snapshot["package"]

    if args.format == "json":
        rendered = json.dumps(snapshot, ensure_ascii=False, indent=2)
    elif args.format == "markdown":
        rendered = format_markdown_result(package)
    else:
        rendered = format_human_result(package)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")

    print(rendered)

    bundle_dir = resolve_bundle_dir(
        project_root=project_root,
        version=args.version,
        write_bundle=args.write_bundle,
        publish_docs_release=args.publish_docs_release,
    )
    if bundle_dir is not None:
        paths = write_snapshot_bundle(snapshot, bundle_dir)
        if args.publish_docs_release:
            paths.update(write_release_root_index(bundle_dir.parent, version=args.version, bundle_paths=paths))
        if args.format == "human":
            print("")
            print("[release_package_snapshot]")
            for key, value in paths.items():
                print(f"{key}={value}")

    return 0 if snapshot["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
