#!/usr/bin/env python3
"""
Heuristic architecture drift checks for changed files or diff text.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from governance_tools.validator_interface import DomainValidator, ValidatorResult



PRIVATE_PEER_INCLUDE_RE = re.compile(
    r'#include\s+[<"](?P<path>(?:\.\./|[A-Za-z0-9_\-]+/).*(?:Global\.h|GlMySql\.h|[^">]+\.h))[>"]'
)
ADDITIONAL_INCLUDE_RE = re.compile(
    r"AdditionalIncludeDirectories\s*[:=]?.*(etoken_server|database_service|DongleServer|SERVERMultithread)",
    re.IGNORECASE,
)
BOUNDARY_DRIFT_RE = re.compile(
    r"\b(Domain|Infrastructure|Adapter|Application)\b.{0,40}\b(move|depend|reference|cross|leak)\b",
    re.IGNORECASE,
)
PYTHON_IMPORT_RE = re.compile(r"^\s*(?:from\s+([A-Za-z0-9_\.]+)\s+import|import\s+([A-Za-z0-9_\.]+))", re.MULTILINE)
CSHARP_USING_RE = re.compile(r"^\s*using\s+([A-Za-z0-9_\.]+)\s*;", re.MULTILINE)
SWIFT_IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z0-9_\.]+)\s*$", re.MULTILINE)
CPP_INCLUDE_RE = re.compile(r'#include\s+[<"]([^">]+)[>"]')


def _dependency_edges(path: Path, text: str) -> set[str]:
    suffix = path.suffix.lower()
    edges: set[str] = set()

    if suffix in {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}:
        edges.update(match.group(1).strip() for match in CPP_INCLUDE_RE.finditer(text))
    elif suffix == ".py":
        for match in PYTHON_IMPORT_RE.finditer(text):
            edge = match.group(1) or match.group(2)
            if edge:
                edges.add(edge.strip())
    elif suffix == ".cs":
        edges.update(match.group(1).strip() for match in CSHARP_USING_RE.finditer(text))
    elif suffix == ".swift":
        edges.update(match.group(1).strip() for match in SWIFT_IMPORT_RE.finditer(text))

    return {edge for edge in edges if edge}


def extract_dependency_manifest(file_paths: list[Path]) -> dict:
    entries: list[dict] = []

    for path in sorted(file_paths):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="ignore")
        edges = sorted(_dependency_edges(path, text))
        if edges:
            entries.append(
                {
                    "path": str(path).replace("\\", "/"),
                    "edges": edges,
                }
            )

    return {"entries": entries}


def diff_dependency_manifests(before: dict, after: dict, *, scope: str = "feature") -> dict:
    before_edges = {
        f"{entry['path']}::{edge}"
        for entry in before.get("entries", [])
        for edge in entry.get("edges", [])
    }
    after_edges = {
        f"{entry['path']}::{edge}"
        for entry in after.get("entries", [])
        for edge in entry.get("edges", [])
    }

    added = sorted(after_edges - before_edges)
    removed = sorted(before_edges - after_edges)
    warnings: list[str] = []
    errors: list[str] = []
    findings: list[dict] = []

    for item in added:
        _, edge = item.split("::", 1)
        if "../" in edge:
            errors.append(f"New cross-project dependency edge detected: {edge}")
            findings.append({"kind": "new_cross_project_dependency_edge", "severity": "error", "detail": edge})
        elif scope == "refactor":
            warnings.append(f"Refactor introduced new dependency edge: {edge}")
            findings.append({"kind": "new_dependency_edge", "severity": "warning", "detail": edge})

    return {
        "ok": len(errors) == 0,
        "added": added,
        "removed": removed,
        "warnings": warnings,
        "errors": errors,
        "findings": findings,
    }


def _scan_text(text: str, *, scope: str = "feature") -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    findings: list[dict] = []

    for match in PRIVATE_PEER_INCLUDE_RE.finditer(text):
        include_path = match.group("path")
        if "../" in include_path or "/" in include_path:
            errors.append(f"Cross-project private include detected: {include_path}")
            findings.append(
                {
                    "kind": "cross_project_private_include",
                    "severity": "error",
                    "detail": include_path,
                }
            )

    if ADDITIONAL_INCLUDE_RE.search(text):
        detail = ADDITIONAL_INCLUDE_RE.search(text).group(1)
        errors.append(f"AdditionalIncludeDirectories references peer-private path: {detail}")
        findings.append(
            {
                "kind": "additional_include_peer_path",
                "severity": "error",
                "detail": detail,
            }
        )

    if scope == "refactor":
        for match in BOUNDARY_DRIFT_RE.finditer(text):
            detail = match.group(0).strip()
            warnings.append(f"Potential refactor boundary drift: {detail}")
            findings.append(
                {
                    "kind": "refactor_boundary_drift",
                    "severity": "warning",
                    "detail": detail,
                }
            )

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "findings": findings,
    }


def check_architecture_drift(
    file_paths: list[Path] | None = None,
    diff_text: str = "",
    scope: str = "feature",
    before_files: list[Path] | None = None,
    after_files: list[Path] | None = None,
) -> dict:
    file_paths = file_paths or []
    before_files = before_files or []
    after_files = after_files or []
    aggregate = {"ok": True, "errors": [], "warnings": [], "findings": [], "files": []}

    if diff_text:
        result = _scan_text(diff_text, scope=scope)
        aggregate["errors"].extend(result["errors"])
        aggregate["warnings"].extend(result["warnings"])
        aggregate["findings"].extend(result["findings"])

    for path in file_paths:
        text = path.read_text(encoding="utf-8")
        result = _scan_text(text, scope=scope)
        aggregate["files"].append({"path": str(path), "ok": result["ok"]})
        aggregate["errors"].extend(result["errors"])
        aggregate["warnings"].extend(result["warnings"])
        aggregate["findings"].extend(result["findings"])

    dependency_diff = None
    if before_files or after_files:
        before_manifest = extract_dependency_manifest(before_files)
        after_manifest = extract_dependency_manifest(after_files)
        dependency_diff = diff_dependency_manifests(before_manifest, after_manifest, scope=scope)
        aggregate["errors"].extend(dependency_diff["errors"])
        aggregate["warnings"].extend(dependency_diff["warnings"])
        aggregate["findings"].extend(dependency_diff["findings"])
        aggregate["dependency_diff"] = dependency_diff

    aggregate["ok"] = len(aggregate["errors"]) == 0
    return aggregate


class ArchitectureDriftValidator(DomainValidator):
    @property
    def rule_ids(self) -> list[str]:
        return ["feature", "refactor"]

    def validate(self, payload: dict) -> ValidatorResult:
        checks = payload.get("checks", {})
        diff_text = payload.get("response_text", "")
        scope = payload.get("contract_fields", {}).get("SCOPE", "feature")

        result_dict = check_architecture_drift(
            file_paths=[],
            diff_text=diff_text,
            scope=scope,
            before_files=[],
            after_files=[]
        )
        return ValidatorResult(
            ok=result_dict.get("ok", False),
            rule_ids=self.rule_ids,
            violations=result_dict.get("errors", []),
            warnings=result_dict.get("warnings", []),
            evidence_summary=str(result_dict.get("findings", [])),
            metadata={"files_scanned": result_dict.get("files", [])}
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Check architecture drift heuristics.")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--diff-file")
    parser.add_argument("--before", action="append", default=[])
    parser.add_argument("--after", action="append", default=[])
    parser.add_argument("--scope", default="feature")
    args = parser.parse_args()

    diff_text = Path(args.diff_file).read_text(encoding="utf-8") if args.diff_file else ""
    result = check_architecture_drift(
        file_paths=[Path(path) for path in args.file],
        diff_text=diff_text,
        scope=args.scope,
        before_files=[Path(path) for path in args.before],
        after_files=[Path(path) for path in args.after],
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
