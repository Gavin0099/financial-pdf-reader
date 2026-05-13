#!/usr/bin/env python3
"""
Generate a persistent reviewer-handoff snapshot bundle from reviewer_handoff_summary.
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

from governance_tools.reviewer_handoff_summary import (
    assess_reviewer_handoff,
    format_human_result,
    format_markdown_result,
)


def _external_project_facts_summaries(snapshot: dict[str, Any]) -> list[str]:
    handoff = snapshot.get("handoff") or {}
    trust = handoff.get("trust_signal") or {}
    auditor = trust.get("auditor") or {}
    external_onboarding = auditor.get("external_onboarding") or {}
    summaries: list[str] = []
    for item in external_onboarding.get("top_issues") or []:
        summary = item.get("project_facts_summary")
        if summary:
            summaries.append(f"{item.get('repo_root')}: {summary}")
    return summaries


def build_reviewer_handoff_snapshot(
    *,
    project_root: Path,
    plan_path: Path,
    release_version: str,
    contract_file: Path | None = None,
    external_contract_repos: list[Path] | None = None,
    strict_runtime: bool = False,
    release_bundle_manifest: Path | None = None,
    release_publication_manifest: Path | None = None,
    fail_on_non_clean: bool = True,
    allow_non_clean: bool = False,
    lint_override_source: str | None = None,
    override_reason_code: str | None = None,
    override_reason_note: str | None = None,
) -> dict[str, Any]:
    handoff = assess_reviewer_handoff(
        project_root=project_root,
        plan_path=plan_path,
        release_version=release_version,
        contract_file=contract_file,
        external_contract_repos=external_contract_repos,
        strict_runtime=strict_runtime,
        release_bundle_manifest=release_bundle_manifest,
        release_publication_manifest=release_publication_manifest,
        fail_on_non_clean=fail_on_non_clean,
        allow_non_clean=allow_non_clean,
        lint_override_source=lint_override_source,
        override_reason_code=override_reason_code,
        override_reason_note=override_reason_note,
    )
    return {
        "ok": handoff["ok"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project_root),
        "plan_path": str(plan_path),
        "release_version": release_version,
        "contract_path": str(contract_file.resolve()) if contract_file else None,
        "external_contract_repos": [str(path.resolve()) for path in (external_contract_repos or [])],
        "strict_runtime": strict_runtime,
        "handoff": handoff,
    }


def _history_stem(snapshot: dict[str, Any]) -> str:
    dt = datetime.fromisoformat(snapshot["generated_at"].replace("Z", "+00:00"))
    return dt.strftime("%Y%m%d_%H%M%S")


def resolve_bundle_dir(
    *,
    project_root: Path,
    release_version: str,
    write_bundle: str | None = None,
) -> Path | None:
    if write_bundle:
        return Path(write_bundle).resolve()
    return project_root / "artifacts" / "reviewer-handoff" / release_version


def resolve_publication_paths(
    *,
    project_root: Path,
    release_version: str,
    write_bundle: str | None = None,
    publish_status_dir: str | None = None,
    publication_root: str | None = None,
    publish_docs_status: bool = False,
) -> tuple[Path | None, Path | None, Path | None]:
    if publish_docs_status:
        docs_root = (project_root / "docs" / "status" / "generated" / "reviewer-handoff").resolve()
        bundle_path = Path(write_bundle).resolve() if write_bundle else docs_root / "bundle"
        published_path = Path(publish_status_dir).resolve() if publish_status_dir else docs_root / "site"
        publication_path = Path(publication_root).resolve() if publication_root else docs_root
    else:
        bundle_path = resolve_bundle_dir(
            project_root=project_root,
            release_version=release_version,
            write_bundle=write_bundle,
        )
        published_path = Path(publish_status_dir).resolve() if publish_status_dir else None
        publication_path = Path(publication_root).resolve() if publication_root else None

        if publication_path is None:
            if bundle_path is not None:
                publication_path = bundle_path.parent
            elif published_path is not None:
                publication_path = published_path.parent

    return bundle_path, published_path, publication_path


def format_index(history_dir: Path) -> str:
    json_files = sorted(history_dir.glob("*.json"))
    lines = ["[reviewer_handoff_snapshot_index]", f"history_dir={history_dir}", f"reports={len(json_files)}"]
    if json_files:
        lines.append("[reports]")
        for path in reversed(json_files):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                lines.append(f"{path.name} | unreadable")
                continue
            handoff = payload.get("handoff") or {}
            trust = handoff.get("trust_signal") or {}
            release = handoff.get("release_surface") or {}
            lines.append(
                " | ".join(
                    [
                        path.name,
                        f"ok={payload.get('ok')}",
                        f"release_version={payload.get('release_version')}",
                        f"trust={trust.get('ok')}",
                        f"release={release.get('ok')}",
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

    handoff = snapshot["handoff"]
    trust = handoff.get("trust_signal") or {}
    release = handoff.get("release_surface") or {}
    lint = handoff.get("reviewer_lint") or {}
    lint_policy = handoff.get("reviewer_lint_policy") or {}
    override_decision_reason = lint_policy.get("override_decision_reason")
    json_text = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    human_text = format_human_result(handoff) + "\n"
    markdown_text = format_markdown_result(handoff) + "\n"

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
                "plan_path": snapshot["plan_path"],
                "release_version": snapshot["release_version"],
                "contract_path": snapshot.get("contract_path"),
                "external_contract_repos": snapshot.get("external_contract_repos") or [],
                "external_contract_repo_count": len(snapshot.get("external_contract_repos") or []),
                "external_onboarding_project_facts": _external_project_facts_summaries(snapshot),
                "strict_runtime": snapshot["strict_runtime"],
                "ok": snapshot["ok"],
                "upstream_ok": handoff.get("upstream_ok"),
                "handoff_clean_identity": handoff.get("handoff_clean_identity"),
                "trust_ok": trust.get("ok"),
                "release_ok": release.get("ok"),
                "lint_status": lint.get("status"),
                "lint_violation_count": lint.get("violation_count"),
                "lint_highest_severity": lint.get("highest_severity"),
                "lint_violations": lint.get("violations") or [],
                "lint_policy": lint_policy,
                "override_decision_reason": override_decision_reason,
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
    publication_manifest_json.write_text(
        json.dumps(
            {
                "ok": snapshot["ok"],
                "generated_at": snapshot["generated_at"],
                "project_root": snapshot["project_root"],
                "publication_root": str(bundle_dir),
                "publication_scope": "bundle",
                "plan_path": snapshot["plan_path"],
                "release_version": snapshot["release_version"],
                "contract_path": snapshot.get("contract_path"),
                "external_contract_repos": snapshot.get("external_contract_repos") or [],
                "external_contract_repo_count": len(snapshot.get("external_contract_repos") or []),
                "external_onboarding_project_facts": _external_project_facts_summaries(snapshot),
                "strict_runtime": snapshot["strict_runtime"],
                "trust_ok": trust.get("ok"),
                "release_ok": release.get("ok"),
                "handoff_clean_identity": handoff.get("handoff_clean_identity"),
                "lint_status": lint.get("status"),
                "lint_violation_count": lint.get("violation_count"),
                "lint_highest_severity": lint.get("highest_severity"),
                "lint_policy": lint_policy,
                "override_decision_reason": override_decision_reason,
                "latest_json": str(latest_json),
                "latest_txt": str(latest_txt),
                "latest_md": str(latest_md),
                "history_json": str(history_json),
                "history_txt": str(history_txt),
                "history_md": str(history_md),
                "index_md": str(index_md),
                "manifest_json": str(manifest_json),
                "readme_md": str(readme_md),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    publication_index_md.write_text(
        "\n".join(
            [
                "# Reviewer Handoff Publication Index",
                "",
                f"- Publication scope: `bundle`",
                f"- Release version: `{snapshot['release_version']}`",
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
                "# Reviewer Handoff Snapshot",
                "",
                "This directory contains generated reviewer-handoff snapshots.",
                "",
                f"- Generated at: `{snapshot['generated_at']}`",
                f"- Release version: `{snapshot['release_version']}`",
                f"- Summary: `ok={snapshot['ok']} | trust={trust.get('ok')} | release={release.get('ok')}`",
                "",
                "## Entry Points",
                "",
                "- [Latest Markdown Summary](latest.md)",
                "- [Latest Human Summary](latest.txt)",
                "- [Latest JSON Snapshot](latest.json)",
                "- [History Index](INDEX.md)",
                "- `MANIFEST.json`",
                "- `PUBLICATION_MANIFEST.json`",
            ]
            + (
                ["", "## External Fact States", ""]
                + [f"- `{item}`" for item in _external_project_facts_summaries(snapshot)]
                if _external_project_facts_summaries(snapshot)
                else []
            )
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


def format_published_status_page(snapshot: dict[str, Any]) -> str:
    handoff = snapshot["handoff"]
    lines = [
        "# Published Reviewer Handoff",
        "",
        "> This page is generated. Rebuild it with `governance_tools/reviewer_handoff_snapshot.py`.",
        "",
        f"- Generated at: `{snapshot['generated_at']}`",
        f"- Release version: `{snapshot['release_version']}`",
        f"- Project root: `{snapshot['project_root']}`",
        f"- Contract path: `{snapshot.get('contract_path')}`",
        f"- External contract repos: `{len(snapshot.get('external_contract_repos') or [])}`",
        f"- Strict runtime: `{snapshot['strict_runtime']}`",
        "",
        format_markdown_result(handoff),
    ]
    return "\n".join(lines)


def format_published_index(history_dir: Path) -> str:
    json_files = sorted(history_dir.glob("*.json"))
    lines = ["# Published Reviewer Handoff Index", "", f"- History dir: `{history_dir}`", f"- Reports: `{len(json_files)}`"]
    if json_files:
        lines.extend(["", "| Snapshot | OK | Release | Contract | Generated |", "| --- | --- | --- | --- | --- |"])
        for path in reversed(json_files):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                lines.append(f"| `{path.name}` | unreadable | - | - | - |")
                continue
            lines.append(
                " | ".join(
                    [
                        f"| `{path.name}`",
                        f"`{payload.get('ok')}`",
                        f"`{payload.get('release_version')}`",
                        f"`{payload.get('contract_path')}`",
                        f"`{payload.get('generated_at')}` |",
                    ]
                )
            )
    return "\n".join(lines)


def write_published_status(snapshot: dict[str, Any], publish_dir: Path) -> dict[str, str]:
    publish_dir.mkdir(parents=True, exist_ok=True)
    history_dir = publish_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    stem = _history_stem(snapshot)
    latest_md = publish_dir / "reviewer-handoff-latest.md"
    latest_json = publish_dir / "reviewer-handoff-latest.json"
    readme_md = publish_dir / "README.md"
    history_md = history_dir / f"{stem}.md"
    history_json = history_dir / f"{stem}.json"
    index_md = publish_dir / "INDEX.md"
    manifest_json = publish_dir / "manifest.json"

    markdown_text = format_published_status_page(snapshot) + "\n"
    json_text = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"

    latest_md.write_text(markdown_text, encoding="utf-8")
    latest_json.write_text(json_text, encoding="utf-8")
    history_md.write_text(markdown_text, encoding="utf-8")
    history_json.write_text(json_text, encoding="utf-8")
    index_md.write_text(format_published_index(history_dir) + "\n", encoding="utf-8")
    readme_md.write_text(
        "\n".join(
            [
                "# Published Reviewer Handoff Index",
                "",
                "This directory contains generated reviewer-handoff status pages.",
                "",
                "- [Latest Markdown Snapshot](reviewer-handoff-latest.md)",
                "- [Latest JSON Snapshot](reviewer-handoff-latest.json)",
                "- [History Index](INDEX.md)",
                "- `manifest.json`",
                "",
                f"Latest generated_at: `{snapshot['generated_at']}`",
                f"Release version: `{snapshot['release_version']}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_json.write_text(
        json.dumps(
            {
                "generated_at": snapshot["generated_at"],
                "release_version": snapshot["release_version"],
                "contract_path": snapshot.get("contract_path"),
                "external_contract_repos": snapshot.get("external_contract_repos") or [],
                "external_contract_repo_count": len(snapshot.get("external_contract_repos") or []),
                "strict_runtime": snapshot["strict_runtime"],
                "trust_ok": snapshot["handoff"].get("trust_signal", {}).get("ok"),
                "release_ok": snapshot["handoff"].get("release_surface", {}).get("ok"),
                "handoff_clean_identity": snapshot["handoff"].get("handoff_clean_identity"),
                "lint_status": snapshot["handoff"].get("reviewer_lint", {}).get("status"),
                "lint_violation_count": snapshot["handoff"].get("reviewer_lint", {}).get("violation_count"),
                "lint_highest_severity": snapshot["handoff"].get("reviewer_lint", {}).get("highest_severity"),
                "lint_policy": snapshot["handoff"].get("reviewer_lint_policy") or {},
                "override_decision_reason": (
                    (snapshot["handoff"].get("reviewer_lint_policy") or {}).get("override_decision_reason")
                ),
                "published": {
                    "markdown": str(latest_md),
                    "json": str(latest_json),
                    "readme": str(readme_md),
                    "index": str(index_md),
                },
                "history": {
                    "markdown": str(history_md),
                    "json": str(history_json),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "latest_md": str(latest_md),
        "latest_json": str(latest_json),
        "readme_md": str(readme_md),
        "history_md": str(history_md),
        "history_json": str(history_json),
        "index_md": str(index_md),
        "manifest_json": str(manifest_json),
    }


def format_publication_index(
    snapshot: dict[str, Any],
    *,
    bundle_paths: dict[str, str] | None = None,
    published_paths: dict[str, str] | None = None,
) -> str:
    fact_summaries = _external_project_facts_summaries(snapshot)
    lines = [
        "# Reviewer Handoff Publication Index",
        "",
        f"- Generated at: `{snapshot['generated_at']}`",
        f"- Release version: `{snapshot['release_version']}`",
        f"- Contract path: `{snapshot.get('contract_path')}`",
        f"- External contract repos: `{len(snapshot.get('external_contract_repos') or [])}`",
        f"- Strict runtime: `{snapshot['strict_runtime']}`",
        "",
        "## Surfaces",
        "",
        f"- Bundle published: `{bundle_paths is not None}`",
        f"- Status pages published: `{published_paths is not None}`",
    ]

    if fact_summaries:
        lines.extend(["", "## External Fact States", ""] + [f"- `{item}`" for item in fact_summaries])

    if bundle_paths:
        lines.extend(
            [
                "",
                "## Bundle Paths",
                "",
                f"- Latest JSON: `{bundle_paths['latest_json']}`",
                f"- Latest Text: `{bundle_paths['latest_txt']}`",
                f"- Latest Markdown: `{bundle_paths['latest_md']}`",
                f"- History JSON: `{bundle_paths['history_json']}`",
                f"- History Text: `{bundle_paths['history_txt']}`",
                f"- History Markdown: `{bundle_paths['history_md']}`",
                f"- Index: `{bundle_paths['index_md']}`",
                f"- Manifest: `{bundle_paths['manifest_json']}`",
            ]
        )

    if published_paths:
        lines.extend(
            [
                "",
                "## Published Status Paths",
                "",
                f"- Latest Markdown: `{published_paths['latest_md']}`",
                f"- Latest JSON: `{published_paths['latest_json']}`",
                f"- Readme: `{published_paths['readme_md']}`",
                f"- History Markdown: `{published_paths['history_md']}`",
                f"- History JSON: `{published_paths['history_json']}`",
                f"- Index: `{published_paths['index_md']}`",
                f"- Manifest: `{published_paths['manifest_json']}`",
            ]
        )

    return "\n".join(lines)


def write_publication_manifest(
    snapshot: dict[str, Any],
    root_dir: Path,
    *,
    bundle_paths: dict[str, str] | None = None,
    published_paths: dict[str, str] | None = None,
) -> dict[str, str]:
    root_dir.mkdir(parents=True, exist_ok=True)
    manifest_json = root_dir / "PUBLICATION_MANIFEST.json"
    index_md = root_dir / "PUBLICATION_INDEX.md"
    readme_md = root_dir / "README.md"
    handoff = snapshot.get("handoff") or {}
    lint = handoff.get("reviewer_lint") or {}
    lint_policy = handoff.get("reviewer_lint_policy") or {}
    manifest_payload = {
        "ok": snapshot["ok"],
        "generated_at": snapshot["generated_at"],
        "project_root": snapshot["project_root"],
        "publication_root": str(root_dir),
        "publication_scope": "reviewer-handoff-root",
        "release_version": snapshot["release_version"],
        "contract_path": snapshot.get("contract_path"),
        "external_contract_repos": snapshot.get("external_contract_repos") or [],
        "external_contract_repo_count": len(snapshot.get("external_contract_repos") or []),
        "external_onboarding_project_facts": _external_project_facts_summaries(snapshot),
        "strict_runtime": snapshot["strict_runtime"],
        "trust_ok": handoff.get("trust_signal", {}).get("ok"),
        "release_ok": handoff.get("release_surface", {}).get("ok"),
        "handoff_clean_identity": handoff.get("handoff_clean_identity"),
        "lint_status": lint.get("status"),
        "lint_violation_count": lint.get("violation_count"),
        "lint_highest_severity": lint.get("highest_severity"),
        "lint_violations": lint.get("violations") or [],
        "lint_policy": lint_policy,
        "bundle_published": bundle_paths is not None,
        "status_pages_published": published_paths is not None,
        "override_decision_reason": (
            lint_policy.get("override_decision_reason")
        ),
        "bundle": bundle_paths,
        "published": published_paths,
        "readme_md": str(readme_md),
    }

    manifest_json.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    index_md.write_text(
        format_publication_index(snapshot, bundle_paths=bundle_paths, published_paths=published_paths) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Generated Reviewer Handoff",
        "",
        f"- Summary: `ok={snapshot['ok']} | trust={snapshot['handoff'].get('trust_signal', {}).get('ok')} | release={snapshot['handoff'].get('release_surface', {}).get('ok')}`",
        f"- Generated at: `{snapshot['generated_at']}`",
        f"- Release version: `{snapshot['release_version']}`",
        "",
        "This directory is the stable root for generated reviewer-handoff publication outputs.",
    ]
    fact_summaries = _external_project_facts_summaries(snapshot)
    if fact_summaries:
        lines.extend(["", "## External Fact States", ""] + [f"- `{item}`" for item in fact_summaries])
    lines.extend(
        [
            "",
            "## Entry Points",
            "",
            "- [Publication Index](PUBLICATION_INDEX.md)",
            "- [Publication Manifest](PUBLICATION_MANIFEST.json)",
        ]
    )
    if bundle_paths:
        lines.extend(
            [
                "",
                "## Bundle",
                "",
                f"- Bundle manifest: `{Path(bundle_paths['manifest_json']).name}`",
                f"- Latest text: `{Path(bundle_paths['latest_txt']).name}`",
                f"- Latest markdown: `{Path(bundle_paths['latest_md']).name}`",
                f"- Bundle index: `{Path(bundle_paths['index_md']).name}`",
            ]
        )
    if published_paths:
        lines.extend(
            [
                "",
                "## Published Site",
                "",
                f"- Site manifest: `{Path(published_paths['manifest_json']).name}`",
                f"- Site readme: `{Path(published_paths['readme_md']).parent.name}/{Path(published_paths['readme_md']).name}`",
                f"- Site latest markdown: `{Path(published_paths['latest_md']).parent.name}/{Path(published_paths['latest_md']).name}`",
                f"- Site index: `{Path(published_paths['index_md']).parent.name}/{Path(published_paths['index_md']).name}`",
            ]
        )
    readme_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "manifest_json": str(manifest_json),
        "index_md": str(index_md),
        "readme_md": str(readme_md),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a reviewer-handoff snapshot bundle.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--plan", default="PLAN.md")
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--contract")
    parser.add_argument("--external-contract-repo", action="append", default=[])
    parser.add_argument("--strict-runtime", action="store_true")
    parser.add_argument("--release-bundle-manifest")
    parser.add_argument("--release-publication-manifest")
    parser.add_argument(
        "--fail-on-non-clean",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--allow-non-clean", action="store_true")
    parser.add_argument(
        "--allow-non-clean-reason-code",
        choices=(
            "manual_audit_required",
            "known_policy_violation_for_review",
            "pipeline_debugging_only",
            "temporary_reader_visibility",
            "other_requires_note",
        ),
    )
    parser.add_argument("--allow-non-clean-reason-note")
    parser.add_argument("--format", choices=("human", "json", "markdown"), default="human")
    parser.add_argument("--output")
    parser.add_argument("--write-bundle")
    parser.add_argument("--publish-status-dir")
    parser.add_argument("--publication-root")
    parser.add_argument("--publish-docs-status", action="store_true")
    args = parser.parse_args()
    if args.allow_non_clean and not args.allow_non_clean_reason_code:
        parser.error("--allow-non-clean requires --allow-non-clean-reason-code")
    if (
        args.allow_non_clean
        and args.allow_non_clean_reason_code == "other_requires_note"
        and not (args.allow_non_clean_reason_note or "").strip()
    ):
        parser.error(
            "--allow-non-clean-reason-note is required when reason code is other_requires_note"
        )

    project_root = Path(args.project_root).resolve()
    snapshot = build_reviewer_handoff_snapshot(
        project_root=project_root,
        plan_path=Path(args.plan),
        release_version=args.release_version,
        contract_file=Path(args.contract).resolve() if args.contract else None,
        external_contract_repos=[Path(item).resolve() for item in args.external_contract_repo],
        strict_runtime=args.strict_runtime,
        release_bundle_manifest=Path(args.release_bundle_manifest).resolve() if args.release_bundle_manifest else None,
        release_publication_manifest=(
            Path(args.release_publication_manifest).resolve() if args.release_publication_manifest else None
        ),
        fail_on_non_clean=bool(args.fail_on_non_clean),
        allow_non_clean=bool(args.allow_non_clean),
        lint_override_source="cli_allow_non_clean" if args.allow_non_clean else None,
        override_reason_code=args.allow_non_clean_reason_code,
        override_reason_note=args.allow_non_clean_reason_note,
    )
    handoff = snapshot["handoff"]
    if args.format == "json":
        rendered = json.dumps(snapshot, ensure_ascii=False, indent=2)
    elif args.format == "markdown":
        rendered = format_markdown_result(handoff)
    else:
        rendered = format_human_result(handoff)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")

    bundle_dir, published_dir, publication_root = resolve_publication_paths(
        project_root=project_root,
        release_version=args.release_version,
        write_bundle=args.write_bundle,
        publish_status_dir=args.publish_status_dir,
        publication_root=args.publication_root,
        publish_docs_status=args.publish_docs_status,
    )
    print(rendered)

    if bundle_dir is not None:
        paths = write_snapshot_bundle(snapshot, bundle_dir)
        if args.format == "human":
            print("")
            print("[reviewer_handoff_snapshot]")
            for key, value in paths.items():
                print(f"{key}={value}")
    else:
        paths = None
    if published_dir is not None:
        published = write_published_status(snapshot, published_dir)
        if args.format == "human":
            print("")
            print("[reviewer_handoff_published]")
            for key, value in published.items():
                print(f"{key}={value}")
    else:
        published = None
    if publication_root is not None:
        publication = write_publication_manifest(
            snapshot,
            publication_root,
            bundle_paths=paths,
            published_paths=published,
        )
        if args.format == "human":
            print("")
            print("[reviewer_handoff_publication]")
            for key, value in publication.items():
                print(f"{key}={value}")

    return 0 if snapshot["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
