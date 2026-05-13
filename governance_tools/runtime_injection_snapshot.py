#!/usr/bin/env python3
"""
Load the minimal runtime injection snapshot used by runtime hooks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.domain_contract_loader import _as_list, _parse_contract_yaml


def default_snapshot_path(framework_root: Path) -> Path:
    return framework_root / "governance" / "runtime_injection_snapshot.v0.yaml"


def load_runtime_injection_snapshot(
    framework_root: Path,
    *,
    snapshot_file: Path | None = None,
) -> dict:
    path = (snapshot_file or default_snapshot_path(framework_root)).resolve()
    data = _parse_contract_yaml(path.read_text(encoding="utf-8"))

    return {
        "name": str(data.get("name") or path.stem),
        "policy_version": str(data.get("policy_version") or "unknown"),
        "path": str(path),
        "source_refs": _as_list(data.get("source_refs")),
        "task_level_scope": [item for item in _as_list(data.get("task_level_scope")) if item],
        "target_agent_classes": [item for item in _as_list(data.get("target_agent_classes")) if item],
        "consumption_requirements": [item for item in _as_list(data.get("consumption_requirements")) if item],
        "validation_requirements": [item for item in _as_list(data.get("validation_requirements")) if item],
        "escalation_triggers": [item for item in _as_list(data.get("escalation_triggers")) if item],
    }


def format_human(snapshot: dict) -> str:
    lines = [
        "[runtime_injection_snapshot]",
        f"name={snapshot['name']}",
        f"policy_version={snapshot['policy_version']}",
        f"path={snapshot['path']}",
        f"task_level_scope={','.join(snapshot['task_level_scope'])}",
        f"target_agent_classes={','.join(snapshot['target_agent_classes'])}",
        f"consumption_requirements={','.join(snapshot['consumption_requirements'])}",
        f"validation_requirements={','.join(snapshot['validation_requirements'])}",
        f"escalation_triggers={','.join(snapshot['escalation_triggers'])}",
    ]
    if snapshot["source_refs"]:
        lines.append(f"source_refs={','.join(snapshot['source_refs'])}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the minimal runtime injection snapshot.")
    parser.add_argument("--framework-root", default=".")
    parser.add_argument("--snapshot")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    snapshot = load_runtime_injection_snapshot(
        Path(args.framework_root).resolve(),
        snapshot_file=Path(args.snapshot).resolve() if args.snapshot else None,
    )

    if args.format == "json":
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        print(format_human(snapshot))


if __name__ == "__main__":
    main()

