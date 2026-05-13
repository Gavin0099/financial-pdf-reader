#!/usr/bin/env python3
"""
Intake external project facts into a provenance-rich framework artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from memory_pipeline.memory_layout import resolve_memory_file

SCHEMA_VERSION = "1.0"
ARTIFACT_TYPE = "external-project-facts-intake"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_external_project_facts_file(repo_root: Path, logical_name: str = "tech_stack") -> Path:
    memory_root = repo_root / "memory"
    candidate = resolve_memory_file(memory_root, logical_name)
    if not candidate.exists():
        raise FileNotFoundError(
            f"external project facts not found under {memory_root}; expected mapping for {logical_name}"
        )
    return candidate


def build_external_project_facts_intake(repo_root: Path) -> dict:
    repo_root = repo_root.resolve()
    memory_root = repo_root / "memory"
    captured_at = datetime.now(timezone.utc).isoformat()

    fact_sources = []
    contents = {}
    expected_logical_names = ["tech_stack", "knowledge_base", "review_log", "active_task"]
    missing_logical_names = []

    for logical_name in expected_logical_names:
        try:
            source_file = resolve_external_project_facts_file(repo_root, logical_name)
            content = source_file.read_text(encoding="utf-8", errors="replace")
            fact_sources.append({
                "logical_name": logical_name,
                "source_file": str(source_file),
                "source_filename": source_file.name,
                "content_sha256": _sha256_text(content),
            })
            contents[logical_name] = content
        except FileNotFoundError:
            missing_logical_names.append(logical_name)

    if not fact_sources:
        raise FileNotFoundError(
            f"No external project facts found under {memory_root}"
        )

    primary = next((f for f in fact_sources if f["logical_name"] == "tech_stack"), fact_sources[0])

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "captured_at": captured_at,
        "repo": {
            "name": repo_root.name,
            "root": str(repo_root),
        },
        "fact_source": primary,
        "fact_sources": fact_sources,
        "expected_logical_names": expected_logical_names,
        "present_logical_names": [item["logical_name"] for item in fact_sources],
        "missing_logical_names": missing_logical_names,
        "memory_schema_status": "partial" if missing_logical_names else "complete",
        "provenance": {
            "source_type": "external-memory-facts",
            "sync_direction": "external_to_framework",
            "memory_root": str(memory_root),
            "repo_root": str(repo_root),
            "captured_from": str(primary["source_file"]),
        },
        "content": contents.get(primary["logical_name"], ""),
        "contents": contents,
    }


def default_output_path(project_root: Path, repo_root: Path) -> Path:
    return project_root / "artifacts" / "external-project-facts" / f"{repo_root.name}.json"


def write_intake_artifact(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def format_human(payload: dict, output_path: Path | None = None) -> str:
    lines = [
        "[external_project_facts_intake]",
        f"repo={payload['repo']['name']}",
        f"repo_root={payload['repo']['root']}",
    ]
    for source in payload.get("fact_sources", [payload["fact_source"]]):
        lines.append(f"source_file={source['source_file']}")
        lines.append(f"source_filename={source['source_filename']}")
        lines.append(f"content_sha256={source['content_sha256']}")
    lines.append(f"memory_schema_status={payload.get('memory_schema_status')}")
    if payload.get("missing_logical_names"):
        lines.append(f"missing_logical_names={','.join(payload['missing_logical_names'])}")
    lines.append(f"sync_direction={payload['provenance']['sync_direction']}")
    if output_path is not None:
        lines.append(f"output={output_path}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Intake external project facts into a framework artifact.")
    parser.add_argument("--repo", required=True, help="External repo root")
    parser.add_argument("--project-root", default=".", help="Framework project root for default artifact output")
    parser.add_argument("--output", help="Optional explicit output path")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    project_root = Path(args.project_root).resolve()
    payload = build_external_project_facts_intake(repo_root)
    output_path = Path(args.output).resolve() if args.output else default_output_path(project_root, repo_root)
    write_intake_artifact(payload, output_path)

    if args.format == "json":
        print(json.dumps({**payload, "output": str(output_path)}, ensure_ascii=False, indent=2))
    else:
        print(format_human(payload, output_path))


if __name__ == "__main__":
    main()
