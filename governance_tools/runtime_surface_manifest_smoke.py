#!/usr/bin/env python3
"""
Smoke-check the runtime surface manifest consistency layer.

This does not change governance verdicts. It only verifies whether the
generated manifest currently emits any soft-enforcement consistency signals.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.framework_versioning import repo_root_from_tooling
from governance_tools.runtime_surface_manifest import (
    build_runtime_surface_manifest,
    manifest_has_consistency_signal,
)


@dataclass
class RuntimeSurfaceManifestSmokeResult:
    ok: bool
    repo_root: str
    repo_commit: str | None
    unknown_surfaces: list[dict[str, str]] = field(default_factory=list)
    orphan_surfaces: list[dict[str, str]] = field(default_factory=list)
    evidence_surface_mismatch: list[dict[str, str]] = field(default_factory=list)
    signal_posture: str = "soft-enforcement"

    def to_dict(self) -> dict:
        return asdict(self)


def check_runtime_surface_manifest(repo_root: Path | None = None) -> RuntimeSurfaceManifestSmokeResult:
    root = (repo_root or repo_root_from_tooling()).resolve()
    manifest = build_runtime_surface_manifest(root)
    consistency = manifest["consistency"]
    return RuntimeSurfaceManifestSmokeResult(
        ok=not manifest_has_consistency_signal(manifest),
        repo_root=str(root),
        repo_commit=manifest.get("repo_commit"),
        unknown_surfaces=consistency["unknown_surfaces"],
        orphan_surfaces=consistency["orphan_surfaces"],
        evidence_surface_mismatch=consistency["evidence_surface_mismatch"],
        signal_posture=consistency["signal_posture"],
    )


def format_human(result: RuntimeSurfaceManifestSmokeResult) -> str:
    lines = [
        "[runtime_surface_manifest_smoke]",
        f"ok={result.ok}",
        f"repo_root={result.repo_root}",
        f"repo_commit={result.repo_commit}",
        f"signal_posture={result.signal_posture}",
        f"unknown_surfaces={len(result.unknown_surfaces)}",
        f"orphan_surfaces={len(result.orphan_surfaces)}",
        f"evidence_surface_mismatch={len(result.evidence_surface_mismatch)}",
    ]
    if result.unknown_surfaces:
        lines.append("[unknown_surfaces]")
        for item in result.unknown_surfaces:
            lines.append(f"  - {item['type']}::{item['name']} :: {item['reason']}")
    if result.orphan_surfaces:
        lines.append("[orphan_surfaces]")
        for item in result.orphan_surfaces:
            lines.append(f"  - {item['type']}::{item['name']} :: {item['reason']}")
    if result.evidence_surface_mismatch:
        lines.append("[evidence_surface_mismatch]")
        for item in result.evidence_surface_mismatch:
            lines.append(f"  - {item['name']} :: {item['reason']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-check runtime surface manifest consistency signals.")
    parser.add_argument("--repo-root", help="Framework repo root (default: auto-detect).")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else None
    result = check_runtime_surface_manifest(repo_root)
    if args.format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_human(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
