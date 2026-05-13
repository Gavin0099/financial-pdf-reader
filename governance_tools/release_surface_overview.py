#!/usr/bin/env python3
"""
Aggregate release-facing readiness, package, and publication surfaces into one reviewer-first overview.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.authority_rollout_policy import resolve_authority_rollout_policy
from governance_tools.human_summary import build_summary_line
from governance_tools.escalation_authority_writer import assess_authority_directory
from governance_tools.release_package_publication_reader import (
    assess_publication_manifest,
    default_docs_release_publication_manifest_path,
)
from governance_tools.release_package_reader import (
    assess_manifest,
    default_docs_release_manifest_path,
    default_manifest_path,
)
from governance_tools.release_package_summary import assess_release_package
from governance_tools.release_readiness import assess_release_readiness
from governance_tools.structural_promotion_gate import evaluate_gate as evaluate_structural_promotion_gate


def default_artifact_publication_manifest_path(project_root: Path, *, version: str) -> Path:
    return default_manifest_path(project_root, version=version).with_name("PUBLICATION_MANIFEST.json")


def _missing_surface(kind: str, source: str, path: Path | None = None) -> dict[str, Any]:
    return {
        "available": False,
        "ok": True,
        "kind": kind,
        "source": source,
        "manifest_file": str(path) if path else None,
        "error": "not_available",
    }


def _assess_bundle_manifest(
    *,
    project_root: Path,
    version: str,
    bundle_manifest: Path | None,
) -> dict[str, Any]:
    if bundle_manifest is not None:
        result = assess_manifest(bundle_manifest.resolve())
        result["available"] = True
        result["source"] = "explicit"
        return result

    docs_manifest = default_docs_release_manifest_path(project_root, version=version)
    if docs_manifest.is_file():
        result = assess_manifest(docs_manifest)
        result["available"] = True
        result["source"] = "docs-release"
        return result

    artifact_manifest = default_manifest_path(project_root, version=version)
    if artifact_manifest.is_file():
        result = assess_manifest(artifact_manifest)
        result["available"] = True
        result["source"] = "artifact-bundle"
        return result

    return _missing_surface("bundle_manifest", "unavailable", docs_manifest)


def _assess_publication_manifest(
    *,
    project_root: Path,
    version: str,
    publication_manifest: Path | None,
) -> dict[str, Any]:
    if publication_manifest is not None:
        result = assess_publication_manifest(publication_manifest.resolve())
        result["available"] = True
        result["source"] = "explicit"
        return result

    docs_manifest = default_docs_release_publication_manifest_path(project_root)
    if docs_manifest.is_file():
        result = assess_publication_manifest(docs_manifest)
        result["available"] = True
        result["source"] = "docs-release-root"
        return result

    artifact_manifest = default_artifact_publication_manifest_path(project_root, version=version)
    if artifact_manifest.is_file():
        result = assess_publication_manifest(artifact_manifest)
        result["available"] = True
        result["source"] = "artifact-bundle"
        return result

    return _missing_surface("publication_manifest", "unavailable", docs_manifest)


def _commands(version: str) -> list[dict[str, str]]:
    return [
        {
            "name": "release_readiness",
            "command": f"python governance_tools/release_readiness.py --version {version} --format human",
        },
        {
            "name": "release_package_summary",
            "command": f"python governance_tools/release_package_summary.py --version {version} --format human",
        },
        {
            "name": "release_package_snapshot_docs",
            "command": f"python governance_tools/release_package_snapshot.py --version {version} --publish-docs-release --format human",
        },
        {
            "name": "release_package_reader_docs",
            "command": f"python governance_tools/release_package_reader.py --version {version} --project-root . --docs-release --format human",
        },
        {
            "name": "release_package_publication_reader_docs",
            "command": "python governance_tools/release_package_publication_reader.py --project-root . --docs-release-root --format human",
        },
        {
            "name": "structural_promotion_gate",
            "command": "python governance_tools/structural_promotion_gate.py --memory-root memory --project-root .",
        },
    ]


def assess_release_surface(
    project_root: Path,
    *,
    version: str,
    bundle_manifest: Path | None = None,
    publication_manifest: Path | None = None,
    authority_require_register: bool | None = None,
    authority_require_log: bool | None = None,
    authority_policy_file: Path | None = None,
) -> dict[str, Any]:
    readiness = assess_release_readiness(project_root, version=version)
    package = assess_release_package(project_root, version=version)
    bundle = _assess_bundle_manifest(
        project_root=project_root,
        version=version,
        bundle_manifest=bundle_manifest,
    )
    publication = _assess_publication_manifest(
        project_root=project_root,
        version=version,
        publication_manifest=publication_manifest,
    )
    authority_policy = resolve_authority_rollout_policy(
        project_root=project_root,
        require_register_override=authority_require_register,
        require_log_override=authority_require_log,
        policy_file=authority_policy_file,
    )
    escalation_authority = assess_authority_directory(
        project_root,
        require_register=authority_policy.require_register,
        require_log=authority_policy.require_log,
    )
    structural_promotion = evaluate_structural_promotion_gate(
        project_root / "memory",
        project_root,
        project_root / "governance" / "STRUCTURAL_PROMOTION_COVERAGE_CLOSEOUT_2026-04-30.md",
    )
    lifecycle_effective = dict(escalation_authority.get("lifecycle_effective_by_escalation") or {})
    escalation_authority["lifecycle_effective_by_escalation"] = lifecycle_effective
    escalation_authority["precedence_applied"] = bool(
        escalation_authority.get("precedence_applied")
        or escalation_authority.get("source") == "authority-writer-monopoly"
    )

    return {
        "ok": readiness["ok"]
        and package["ok"]
        and bundle["ok"]
        and publication["ok"]
        and escalation_authority["ok"]
        and bool(structural_promotion.get("promotion_allowed")),
        "project_root": str(project_root),
        "version": version,
        "readiness": readiness,
        "package": package,
        "bundle_manifest": bundle,
        "publication_manifest": publication,
        "escalation_authority": escalation_authority,
        "authority_rollout_policy": {
            "require_register": authority_policy.require_register,
            "require_log": authority_policy.require_log,
            "policy_source": authority_policy.policy_source,
            "policy_mode": authority_policy.policy_mode,
            "explicit_override": authority_policy.explicit_override,
        },
        "structural_promotion_allowed": bool(structural_promotion.get("promotion_allowed", False)),
        "structural_failure_class": str(structural_promotion.get("failure_class", "")),
        "structural_blocked_reasons": list(structural_promotion.get("blocked_reasons") or []),
        "structural_authority_rate": structural_promotion.get("structural_authority_rate"),
        "structural_promotion": structural_promotion,
        "commands": _commands(version),
    }


def format_human_result(result: dict[str, Any]) -> str:
    readiness = result["readiness"]
    package = result["package"]
    bundle = result["bundle_manifest"]
    publication = result["publication_manifest"]
    escalation_authority = result["escalation_authority"]
    structural_promotion = result.get("structural_promotion") or {}
    authority_policy = result.get("authority_rollout_policy") or {}
    summary_line = build_summary_line(
        f"ok={result['ok']}",
        f"version={result['version']}",
        f"readiness={readiness['ok']}",
        f"package={package['ok']}",
        f"bundle={'missing' if not bundle['available'] else bundle['ok']}",
        f"publication={'missing' if not publication['available'] else publication['ok']}",
        f"escalation_authority={'missing' if not escalation_authority['available'] else escalation_authority['ok']}",
        f"structural_promotion={structural_promotion.get('promotion_allowed')}",
    )
    lines = [
        summary_line,
        "[release_surface_overview]",
        f"project_root={result['project_root']}",
        f"version={result['version']}",
        f"readiness_ok={readiness['ok']}",
        f"package_ok={package['ok']}",
        f"bundle_available={bundle['available']}",
        f"bundle_source={bundle['source']}",
        f"publication_available={publication['available']}",
        f"publication_source={publication['source']}",
        f"escalation_authority_available={escalation_authority['available']}",
        f"escalation_authority_source={escalation_authority['source']}",
        f"authority_policy_mode={authority_policy.get('policy_mode')}",
        f"authority_policy_source={authority_policy.get('policy_source')}",
        f"structural_promotion_allowed={structural_promotion.get('promotion_allowed')}",
    ]
    if bundle.get("manifest_file"):
        lines.append(f"bundle_manifest_file={bundle['manifest_file']}")
    if publication.get("manifest_file"):
        lines.append(f"publication_manifest_file={publication['manifest_file']}")

    lines.extend(
        [
            "[release_readiness]",
            f"checks={len(readiness['checks'])}",
            f"warnings={len(readiness['warnings'])}",
            f"errors={len(readiness['errors'])}",
            "[release_package]",
            f"release_docs={package['existing_release_docs']}/{package['release_doc_count']}",
            f"status_docs={package['existing_status_docs']}/{package['status_doc_count']}",
        ]
    )

    lines.append("[bundle_manifest]")
    if bundle["available"]:
        lines.extend(
            [
                f"ok={bundle['ok']}",
                f"source={bundle['source']}",
                f"version={bundle.get('version')}",
                f"latest_md={bundle.get('latest_md')}",
                f"readme_md={bundle.get('readme_md')}",
            ]
        )
    else:
        lines.extend(
            [
                "available=False",
                f"source={bundle['source']}",
                f"suggested_command=python governance_tools/release_package_snapshot.py --version {result['version']} --publish-docs-release --format human",
            ]
        )

    lines.append("[publication_manifest]")
    if publication["available"]:
        lines.extend(
            [
                f"ok={publication['ok']}",
                f"source={publication['source']}",
                f"scope={publication.get('publication_scope')}",
                f"version={publication.get('version')}",
                f"readme_md={publication.get('readme_md')}",
            ]
        )
    else:
        lines.extend(
            [
                "available=False",
                f"source={publication['source']}",
                f"suggested_command=python governance_tools/release_package_publication_reader.py --project-root . --docs-release-root --format human",
            ]
        )

    lines.append("[escalation_authority]")
    if escalation_authority["available"]:
        lines.extend(
            [
                f"ok={escalation_authority['ok']}",
                f"source={escalation_authority['source']}",
                f"artifacts_read={escalation_authority['artifacts_read']}",
                f"precedence_applied={escalation_authority.get('precedence_applied')}",
                f"decision_source={escalation_authority.get('decision_source')}",
                f"register_required_mode={escalation_authority.get('register_required_mode')}",
                f"register_present={escalation_authority.get('register_present')}",
                f"release_blocked={escalation_authority['release_blocked']}",
                "lifecycle_effective_by_escalation="
                + json.dumps(escalation_authority.get("lifecycle_effective_by_escalation") or {}, ensure_ascii=False, sort_keys=True),
            ]
        )
        reasons = escalation_authority.get("release_block_reasons") or []
        if reasons:
            lines.append(f"release_block_reasons={','.join(reasons)}")
    else:
        lines.extend(
            [
                "available=False",
                f"source={escalation_authority['source']}",
                "suggested_command=python governance_tools/escalation_authority_writer.py --project-root . --mode assess --format human",
            ]
        )

    lines.append("[authority_rollout_policy]")
    lines.extend(
        [
            f"require_register={authority_policy.get('require_register')}",
            f"require_log={authority_policy.get('require_log')}",
            f"policy_mode={authority_policy.get('policy_mode')}",
            f"policy_source={authority_policy.get('policy_source')}",
            f"explicit_override={authority_policy.get('explicit_override')}",
        ]
    )
    lines.append("[structural_promotion_gate]")
    lines.extend(
        [
            f"ok={structural_promotion.get('ok')}",
            f"promotion_allowed={structural_promotion.get('promotion_allowed')}",
            f"failure_class={structural_promotion.get('failure_class')}",
            f"claim_boundary={structural_promotion.get('claim_boundary')}",
            f"test_execution_degraded_reason={structural_promotion.get('test_execution_degraded_reason')}",
            f"blocked_reasons={','.join(structural_promotion.get('blocked_reasons') or [])}",
        ]
    )

    lines.append("[commands]")
    for item in result["commands"]:
        lines.append(f"{item['name']}={item['command']}")

    return "\n".join(lines)


def format_markdown_result(result: dict[str, Any]) -> str:
    readiness = result["readiness"]
    package = result["package"]
    bundle = result["bundle_manifest"]
    publication = result["publication_manifest"]
    escalation_authority = result["escalation_authority"]
    structural_promotion = result.get("structural_promotion") or {}
    authority_policy = result.get("authority_rollout_policy") or {}
    summary_line = build_summary_line(
        f"ok={result['ok']}",
        f"version={result['version']}",
        f"readiness={readiness['ok']}",
        f"package={package['ok']}",
        f"bundle={'missing' if not bundle['available'] else bundle['ok']}",
        f"publication={'missing' if not publication['available'] else publication['ok']}",
        f"escalation_authority={'missing' if not escalation_authority['available'] else escalation_authority['ok']}",
        f"structural_promotion={structural_promotion.get('promotion_allowed')}",
    )

    lines = [
        "# Release Surface Overview",
        "",
        f"- Summary: `{summary_line}`",
        f"- Project root: `{result['project_root']}`",
        f"- Version: `{result['version']}`",
        "",
        "## Surface Status",
        "",
        "| Surface | Status | Detail |",
        "| --- | --- | --- |",
        f"| Release readiness | `{readiness['ok']}` | checks=`{len(readiness['checks'])}` warnings=`{len(readiness['warnings'])}` errors=`{len(readiness['errors'])}` |",
        f"| Release package | `{package['ok']}` | release_docs=`{package['existing_release_docs']}/{package['release_doc_count']}` status_docs=`{package['existing_status_docs']}/{package['status_doc_count']}` |",
        f"| Bundle manifest | `{'missing' if not bundle['available'] else bundle['ok']}` | source=`{bundle['source']}` manifest=`{bundle.get('manifest_file')}` |",
        f"| Publication manifest | `{'missing' if not publication['available'] else publication['ok']}` | source=`{publication['source']}` manifest=`{publication.get('manifest_file')}` |",
        f"| Escalation authority | `{'missing' if not escalation_authority['available'] else escalation_authority['ok']}` | source=`{escalation_authority['source']}` decision_source=`{escalation_authority.get('decision_source')}` register_required=`{escalation_authority.get('register_required_mode')}` register_present=`{escalation_authority.get('register_present')}` artifacts=`{escalation_authority.get('artifacts_read')}` precedence_applied=`{escalation_authority.get('precedence_applied')}` release_blocked=`{escalation_authority.get('release_blocked')}` trust_root_evidence_level=`{escalation_authority.get('trust_root_evidence_level')}` |",
        f"| Structural promotion gate | `{structural_promotion.get('promotion_allowed')}` | failure_class=`{structural_promotion.get('failure_class')}` claim_boundary=`{structural_promotion.get('claim_boundary')}` blocked=`{','.join(structural_promotion.get('blocked_reasons') or [])}` |",
        f"| Authority rollout policy | `{authority_policy.get('policy_mode')}` | source=`{authority_policy.get('policy_source')}` require_register=`{authority_policy.get('require_register')}` require_log=`{authority_policy.get('require_log')}` explicit_override=`{authority_policy.get('explicit_override')}` |",
        "",
        "### Escalation Lifecycle Effective State",
        "",
        f"- `lifecycle_effective_by_escalation={json.dumps(escalation_authority.get('lifecycle_effective_by_escalation') or {}, ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Suggested Commands",
        "",
    ]
    for item in result["commands"]:
        lines.append(f"- `{item['command']}`")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize release-facing surfaces in one reviewer-first view.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--version", required=True)
    parser.add_argument("--bundle-manifest")
    parser.add_argument("--publication-manifest")
    parser.add_argument(
        "--authority-require-register",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("--authority-policy-file")
    parser.add_argument("--format", choices=("human", "json", "markdown"), default="human")
    parser.add_argument("--output")
    args = parser.parse_args()

    result = assess_release_surface(
        Path(args.project_root).resolve(),
        version=args.version,
        bundle_manifest=Path(args.bundle_manifest).resolve() if args.bundle_manifest else None,
        publication_manifest=Path(args.publication_manifest).resolve() if args.publication_manifest else None,
        authority_require_register=args.authority_require_register,
        authority_policy_file=Path(args.authority_policy_file).resolve() if args.authority_policy_file else None,
    )
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
