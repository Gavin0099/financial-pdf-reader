#!/usr/bin/env python3
"""
Generate a minimal runtime surface manifest for the framework.

This first slice is inventory-first and signal-bearing:

- inventories execution, evidence, and authority surfaces
- emits passive consistency signals
- does not alter governance verdicts
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.framework_versioning import repo_root_from_tooling


KNOWN_ADAPTERS: dict[str, dict[str, Any]] = {
    "claude_code": {
        "supported_events": ["pre_task", "post_task", "normalize_event"],
        "normalizer_path": "runtime_hooks/adapters/claude_code/normalize_event.py",
        "runner_path": "runtime_hooks/adapters/shared_adapter_runner.py",
        "contract_dependency": [
            "runtime_hooks/ADAPTER_CONTRACT.md",
            "runtime_hooks/event_contract.md",
        ],
        "notes": "Harness-specific wrapper for Claude Code payload normalization.",
    },
    "codex": {
        "supported_events": ["pre_task", "post_task", "normalize_event"],
        "normalizer_path": "runtime_hooks/adapters/codex/normalize_event.py",
        "runner_path": "runtime_hooks/adapters/shared_adapter_runner.py",
        "contract_dependency": [
            "runtime_hooks/ADAPTER_CONTRACT.md",
            "runtime_hooks/event_contract.md",
        ],
        "notes": "Harness-specific wrapper for Codex payload normalization.",
    },
    "gemini": {
        "supported_events": ["pre_task", "post_task", "normalize_event"],
        "normalizer_path": "runtime_hooks/adapters/gemini/normalize_event.py",
        "runner_path": "runtime_hooks/adapters/shared_adapter_runner.py",
        "contract_dependency": [
            "runtime_hooks/ADAPTER_CONTRACT.md",
            "runtime_hooks/event_contract.md",
        ],
        "notes": "Harness-specific wrapper for Gemini payload normalization.",
    },
}

KNOWN_RUNTIME_ENTRYPOINTS: dict[str, dict[str, Any]] = {
    "session_start": {
        "path": "runtime_hooks/core/session_start.py",
        "category": "runtime-startup",
        "input_mode": "python-cli-and-dispatch",
        "primary_output": "startup context envelope",
        "artifact_effect": "governance startup context and handoff summary",
    },
    "pre_task_check": {
        "path": "runtime_hooks/core/pre_task_check.py",
        "category": "runtime-gate",
        "input_mode": "python-cli-and-dispatch",
        "primary_output": "pre-task decision envelope",
        "artifact_effect": "warnings/errors plus decision-boundary effect",
    },
    "post_task_check": {
        "path": "runtime_hooks/core/post_task_check.py",
        "category": "runtime-gate",
        "input_mode": "python-cli-and-dispatch",
        "primary_output": "post-task validation envelope",
        "artifact_effect": "validator/evidence evaluation before session close",
    },
    "session_end": {
        "path": "runtime_hooks/core/session_end.py",
        "category": "runtime-close",
        "input_mode": "python-cli",
        "primary_output": "runtime close envelope",
        "artifact_effect": "writes runtime verdict, trace, and canonical closeout artifacts",
    },
    "_canonical_closeout": {
        "path": "runtime_hooks/core/_canonical_closeout.py",
        "category": "runtime-close",
        "input_mode": "internal-library",
        "primary_output": "canonical closeout artifact",
        "artifact_effect": "writes artifacts/runtime/closeouts/{session_id}.json and appends session-index.ndjson",
    },
    "_canonical_closeout_context": {
        "path": "runtime_hooks/core/_canonical_closeout_context.py",
        "category": "runtime-init",
        "input_mode": "internal-library",
        "primary_output": "closeout continuity context",
        "artifact_effect": "reads artifacts/runtime/closeouts/ to inject prior-session context at session start",
    },
    "dispatcher": {
        "path": "runtime_hooks/dispatcher.py",
        "category": "shared-dispatch",
        "input_mode": "shared-event-json",
        "primary_output": "event routing envelope",
        "artifact_effect": "routes normalized event payloads into runtime core checks",
    },
    "smoke_test": {
        "path": "runtime_hooks/smoke_test.py",
        "category": "runtime-smoke",
        "input_mode": "native-or-shared-example-payloads",
        "primary_output": "smoke execution summary",
        "artifact_effect": "replays documented runtime entry surfaces end-to-end",
    },
    "run_runtime_governance": {
        "path": "scripts/run-runtime-governance.sh",
        "category": "shared-enforcement",
        "input_mode": "shell-wrapper",
        "primary_output": "hook-or-ci execution status",
        "artifact_effect": "shared enforcement entrypoint for local hooks and CI",
    },
}

CORE_SUPPORT_FILES = {
    "decision_policy_v1_runtime.py",
    "evidence_integrity_gate.py",
    "human_summary.py",
    "payload_audit_logger.py",
    "__init__.py",
}

KNOWN_OPERATOR_TOOLS: dict[str, dict[str, Any]] = {
    "adopt_governance": {
        "path": "governance_tools/adopt_governance.py",
        "category": "adoption",
        "canonical_use": "adopt framework baseline into an existing repo",
        "human_track": True,
        "agent_track": True,
        "produces_artifact": True,
    },
    "governance_drift_checker": {
        "path": "governance_tools/governance_drift_checker.py",
        "category": "drift",
        "canonical_use": "check baseline, contract, and governance drift state",
        "human_track": True,
        "agent_track": True,
        "produces_artifact": True,
    },
    "quickstart_smoke": {
        "path": "governance_tools/quickstart_smoke.py",
        "category": "smoke",
        "canonical_use": "verify documented quickstart path against real runtime hooks",
        "human_track": True,
        "agent_track": True,
        "produces_artifact": True,
    },
    "runtime_enforcement_smoke": {
        "path": "governance_tools/runtime_enforcement_smoke.py",
        "category": "smoke",
        "canonical_use": "validate framework runtime enforcement entrypoints",
        "human_track": False,
        "agent_track": True,
        "produces_artifact": True,
    },
    "reviewer_handoff_summary": {
        "path": "governance_tools/reviewer_handoff_summary.py",
        "category": "reviewer-handoff",
        "canonical_use": "generate reviewer-facing handoff summary",
        "human_track": True,
        "agent_track": True,
        "produces_artifact": True,
    },
    "trust_signal_overview": {
        "path": "governance_tools/trust_signal_overview.py",
        "category": "release-surface",
        "canonical_use": "summarize trust and release-facing governance signals",
        "human_track": True,
        "agent_track": True,
        "produces_artifact": True,
    },
}

KNOWN_EVIDENCE_SURFACES: list[dict[str, Any]] = [
    {
        "surface_name": "runtime_verdict_artifact",
        "path_pattern": "artifacts/runtime/verdicts/<session_id>.json",
        "producer": "session_end",
        "artifact_type": "runtime-verdict",
        "machine_readable": True,
        "human_auditable": True,
        "used_by": ["reviewer_reconstruction", "runtime_audit"],
    },
    {
        "surface_name": "runtime_trace_artifact",
        "path_pattern": "artifacts/runtime/traces/<session_id>.json",
        "producer": "session_end",
        "artifact_type": "runtime-trace",
        "machine_readable": True,
        "human_auditable": True,
        "used_by": ["reviewer_reconstruction", "runtime_audit"],
    },
    {
        "surface_name": "reviewer_handoff_summary",
        "path_pattern": "artifacts/reviewer-handoff/<release>/latest.json",
        "producer": "reviewer_handoff_summary",
        "artifact_type": "reviewer-handoff",
        "machine_readable": True,
        "human_auditable": True,
        "used_by": ["reviewer_entrypoint", "release_review"],
    },
    {
        "surface_name": "quickstart_smoke_terminal_output",
        "path_pattern": "stdout:quickstart_smoke",
        "producer": "quickstart_smoke",
        "artifact_type": "smoke-terminal-output",
        "machine_readable": False,
        "human_auditable": True,
        "used_by": ["adoption_review", "agent_adoption_baseline"],
    },
    {
        "surface_name": "governance_drift_checker_output",
        "path_pattern": "stdout:governance_drift_checker",
        "producer": "governance_drift_checker",
        "artifact_type": "drift-structured-output",
        "machine_readable": False,
        "human_auditable": True,
        "used_by": ["adoption_review", "framework_risk_triage"],
    },
]

KNOWN_AUTHORITY_SURFACES: list[dict[str, Any]] = [
    {
        "authority_surface": "governance_authority_table",
        "declared_source": "governance/AUTHORITY.md",
        "scope": "governance document loading and authority precedence reference",
        "can_change_verdict": False,
        "notes": "Canonical authority inventory for governance documents.",
    },
    {
        "authority_surface": "runtime_decision_model",
        "declared_source": "governance/governance_decision_model.v2.6.json",
        "scope": "verdict impact, ownership, precedence, and determinism contract",
        "can_change_verdict": True,
        "notes": "Primary machine-readable governance decision source.",
    },
    {
        "authority_surface": "decision_boundary_model",
        "declared_source": "docs/decision-boundary-layer.md",
        "scope": "design-level pre-decision constraint model",
        "can_change_verdict": False,
        "notes": "Design boundary reference; not a direct runtime verdict source.",
    },
    {
        "authority_surface": "agent_adoption_boundary",
        "declared_source": "docs/beta-gate/agent-adoption-pass-criteria.md",
        "scope": "agent-assisted adoption evaluation semantics and authority boundaries",
        "can_change_verdict": False,
        "notes": "Gate-evaluation surface, not runtime verdict logic.",
    },
]


def _git_commit(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return None
    return completed.stdout.strip() or None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_adapter_inventory(repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    adapters_dir = repo_root / "runtime_hooks" / "adapters"
    found = {
        path.name
        for path in adapters_dir.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }
    inventory: list[dict[str, Any]] = []
    orphan: list[dict[str, str]] = []
    for name, meta in KNOWN_ADAPTERS.items():
        entry = {"adapter_family": name, **meta}
        inventory.append(entry)
        if not (adapters_dir / name).is_dir():
            orphan.append({"type": "adapter_family", "name": name, "reason": "declared in manifest but adapter directory is missing"})
    unknown = [
        {"type": "adapter_family", "name": name, "reason": "present in runtime_hooks/adapters but not declared in manifest"}
        for name in sorted(found - set(KNOWN_ADAPTERS))
    ]
    return inventory, unknown, orphan


def _build_runtime_entrypoints(repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    core_dir = repo_root / "runtime_hooks" / "core"
    found_core = {
        path.name
        for path in core_dir.glob("*.py")
        if path.name not in CORE_SUPPORT_FILES and not path.name.startswith("__")
    }
    known_core_files = {
        Path(meta["path"]).name
        for meta in KNOWN_RUNTIME_ENTRYPOINTS.values()
        if meta["path"].startswith("runtime_hooks/core/")
    }
    inventory: list[dict[str, Any]] = []
    orphan: list[dict[str, str]] = []
    for name, meta in KNOWN_RUNTIME_ENTRYPOINTS.items():
        inventory.append({"entrypoint_name": name, **meta})
        if not (repo_root / meta["path"]).exists():
            orphan.append({"type": "runtime_entrypoint", "name": name, "reason": "declared in manifest but path is missing"})
    unknown = [
        {"type": "runtime_entrypoint", "name": name.replace(".py", ""), "reason": "present in runtime_hooks/core but not declared in manifest"}
        for name in sorted(found_core - known_core_files)
    ]
    return inventory, unknown, orphan


def _build_tool_inventory(repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    inventory: list[dict[str, Any]] = []
    orphan: list[dict[str, str]] = []
    for name, meta in KNOWN_OPERATOR_TOOLS.items():
        inventory.append({"tool_name": name, **meta})
        if not (repo_root / meta["path"]).exists():
            orphan.append({"type": "governance_tool", "name": name, "reason": "declared in manifest but tool path is missing"})
    return inventory, orphan


def _build_evidence_inventory() -> list[dict[str, Any]]:
    return [dict(item) for item in KNOWN_EVIDENCE_SURFACES]


def _build_authority_inventory(repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    inventory: list[dict[str, Any]] = []
    orphan: list[dict[str, str]] = []
    for item in KNOWN_AUTHORITY_SURFACES:
        inventory.append(dict(item))
        if not (repo_root / item["declared_source"]).exists():
            orphan.append({
                "type": "authority_surface",
                "name": item["authority_surface"],
                "reason": "declared source file is missing",
            })
    return inventory, orphan


def _evidence_surface_mismatches(
    runtime_entrypoints: list[dict[str, Any]],
    tool_entries: list[dict[str, Any]],
    evidence_surfaces: list[dict[str, Any]],
) -> list[dict[str, str]]:
    producers = {entry["entrypoint_name"] for entry in runtime_entrypoints} | {entry["tool_name"] for entry in tool_entries}
    mismatches: list[dict[str, str]] = []
    for surface in evidence_surfaces:
        producer = surface["producer"]
        if producer not in producers:
            mismatches.append({
                "type": "evidence_surface_mismatch",
                "name": surface["surface_name"],
                "reason": f"producer '{producer}' is not declared in runtime entrypoints or tool inventory",
            })
    return mismatches


def build_runtime_surface_manifest(repo_root: Path | None = None) -> dict[str, Any]:
    root = (repo_root or repo_root_from_tooling()).resolve()
    adapters, unknown_adapters, orphan_adapters = _build_adapter_inventory(root)
    runtime_entrypoints, unknown_entrypoints, orphan_entrypoints = _build_runtime_entrypoints(root)
    tool_entries, orphan_tools = _build_tool_inventory(root)
    evidence_surfaces = _build_evidence_inventory()
    authority_surfaces, orphan_authority = _build_authority_inventory(root)
    evidence_mismatches = _evidence_surface_mismatches(runtime_entrypoints, tool_entries, evidence_surfaces)

    consistency = {
        "unknown_surfaces": unknown_adapters + unknown_entrypoints,
        "orphan_surfaces": orphan_adapters + orphan_entrypoints + orphan_tools + orphan_authority,
        "evidence_surface_mismatch": evidence_mismatches,
        "signal_posture": "soft-enforcement",
    }

    return {
        "generated_at": _utc_now(),
        "repo_root": str(root),
        "repo_commit": _git_commit(root),
        "adapters": adapters,
        "runtime_entrypoints": runtime_entrypoints,
        "tool_entries": tool_entries,
        "evidence_surfaces": evidence_surfaces,
        "authority_surfaces": authority_surfaces,
        "consistency": consistency,
    }


def manifest_has_consistency_signal(manifest: dict[str, Any]) -> bool:
    consistency = manifest["consistency"]
    return any(
        consistency[key]
        for key in ("unknown_surfaces", "orphan_surfaces", "evidence_surface_mismatch")
    )


def render_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# Runtime Surface Manifest",
        "",
        f"- generated_at: `{manifest.get('generated_at')}`",
        f"- repo_commit: `{manifest.get('repo_commit')}`",
        f"- signal_posture: `{manifest['consistency']['signal_posture']}`",
        "",
        "## Adapter Inventory",
        "",
        "| Adapter | Events | Normalizer | Runner |",
        "|---|---|---|---|",
    ]
    for entry in manifest["adapters"]:
        lines.append(
            f"| `{entry['adapter_family']}` | `{', '.join(entry['supported_events'])}` | "
            f"`{entry['normalizer_path']}` | `{entry['runner_path']}` |"
        )

    lines += [
        "",
        "## Runtime Entrypoints",
        "",
        "| Entrypoint | Category | Path | Primary Output |",
        "|---|---|---|---|",
    ]
    for entry in manifest["runtime_entrypoints"]:
        lines.append(
            f"| `{entry['entrypoint_name']}` | `{entry['category']}` | "
            f"`{entry['path']}` | {entry['primary_output']} |"
        )

    lines += [
        "",
        "## Governance Tool Entries",
        "",
        "| Tool | Category | Human Track | Agent Track | Produces Artifact |",
        "|---|---|---|---|---|",
    ]
    for entry in manifest["tool_entries"]:
        lines.append(
            f"| `{entry['tool_name']}` | `{entry['category']}` | "
            f"`{entry['human_track']}` | `{entry['agent_track']}` | `{entry['produces_artifact']}` |"
        )

    lines += [
        "",
        "## Evidence Surfaces",
        "",
        "| Surface | Producer | Artifact Type | Human Auditable |",
        "|---|---|---|---|",
    ]
    for entry in manifest["evidence_surfaces"]:
        lines.append(
            f"| `{entry['surface_name']}` | `{entry['producer']}` | "
            f"`{entry['artifact_type']}` | `{entry['human_auditable']}` |"
        )

    lines += [
        "",
        "## Authority Surfaces",
        "",
        "| Surface | Declared Source | Can Change Verdict |",
        "|---|---|---|",
    ]
    for entry in manifest["authority_surfaces"]:
        lines.append(
            f"| `{entry['authority_surface']}` | `{entry['declared_source']}` | "
            f"`{entry['can_change_verdict']}` |"
        )

    consistency = manifest["consistency"]
    lines += [
        "",
        "## Consistency Signals",
        "",
        f"- unknown_surfaces: `{len(consistency['unknown_surfaces'])}`",
        f"- orphan_surfaces: `{len(consistency['orphan_surfaces'])}`",
        f"- evidence_surface_mismatch: `{len(consistency['evidence_surface_mismatch'])}`",
        "",
    ]
    if consistency["unknown_surfaces"]:
        lines.append("### Unknown Surfaces")
        lines.append("")
        for item in consistency["unknown_surfaces"]:
            lines.append(f"- `{item['type']}` `{item['name']}`: {item['reason']}")
        lines.append("")
    if consistency["orphan_surfaces"]:
        lines.append("### Orphan Surfaces")
        lines.append("")
        for item in consistency["orphan_surfaces"]:
            lines.append(f"- `{item['type']}` `{item['name']}`: {item['reason']}")
        lines.append("")
    if consistency["evidence_surface_mismatch"]:
        lines.append("### Evidence Surface Mismatch")
        lines.append("")
        for item in consistency["evidence_surface_mismatch"]:
            lines.append(f"- `{item['name']}`: {item['reason']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _write_outputs(repo_root: Path, manifest: dict[str, Any]) -> tuple[Path, Path]:
    generated_dir = repo_root / "docs" / "status" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    generated_json = generated_dir / "runtime-surface-manifest.json"
    generated_md = repo_root / "docs" / "status" / "runtime-surface-manifest.md"
    generated_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    generated_md.write_text(render_markdown(manifest), encoding="utf-8")
    return generated_json, generated_md


def format_human(manifest: dict[str, Any]) -> str:
    consistency = manifest["consistency"]
    return "\n".join([
        "[runtime_surface_manifest]",
        f"repo_commit={manifest.get('repo_commit')}",
        f"adapters={len(manifest['adapters'])}",
        f"runtime_entrypoints={len(manifest['runtime_entrypoints'])}",
        f"tool_entries={len(manifest['tool_entries'])}",
        f"evidence_surfaces={len(manifest['evidence_surfaces'])}",
        f"authority_surfaces={len(manifest['authority_surfaces'])}",
        f"unknown_surfaces={len(consistency['unknown_surfaces'])}",
        f"orphan_surfaces={len(consistency['orphan_surfaces'])}",
        f"evidence_surface_mismatch={len(consistency['evidence_surface_mismatch'])}",
        f"signal_posture={consistency['signal_posture']}",
    ])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a minimal runtime surface manifest.")
    parser.add_argument("--repo-root", help="Framework repo root (default: auto-detect).")
    parser.add_argument("--format", choices=("human", "json", "markdown"), default="human")
    parser.add_argument("--write", action="store_true", help="Write generated JSON and Markdown outputs to docs/status/.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else None
    manifest = build_runtime_surface_manifest(repo_root)
    if args.write:
        _write_outputs(Path(manifest["repo_root"]), manifest)

    if args.format == "json":
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    elif args.format == "markdown":
        print(render_markdown(manifest), end="")
    else:
        print(format_human(manifest))
    return 1 if manifest_has_consistency_signal(manifest) else 0


if __name__ == "__main__":
    raise SystemExit(main())
