#!/usr/bin/env python3
"""
Detect lightweight drift between feature surface and project docs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.feature_surface_snapshot import build_feature_surface_snapshot
from governance_tools.human_summary import build_summary_line

_PHASE_PATTERN = re.compile(r"\bPhase\s+(\d+)\b", re.IGNORECASE)


def _extract_phase_numbers(text: str) -> list[int]:
    return sorted({int(match.group(1)) for match in _PHASE_PATTERN.finditer(text)})


def _route_keywords(routes: list[str]) -> dict[str, str]:
    keywords: dict[str, str] = {}
    for route in routes:
        for part in route.split("/"):
            token = part.strip().lower()
            if not token or token.startswith("["):
                continue
            if token == "api":
                continue
            keywords.setdefault(token, route)
    return keywords


def _migration_keywords(migrations: list[str]) -> dict[str, str]:
    keywords: dict[str, str] = {}
    for migration in migrations:
        for token in re.split(r"[^a-zA-Z0-9]+", migration.lower()):
            if len(token) < 4 or token.isdigit():
                continue
            keywords.setdefault(token, migration)
    return keywords


def _load_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, PermissionError):
        return ""


def assess_doc_drift(project_root: Path, plan_path: Path | None = None, readme_paths: list[Path] | None = None) -> dict[str, object]:
    plan_file = (plan_path or (project_root / "PLAN.md")).resolve()
    explicit_readmes = readme_paths or []
    if explicit_readmes:
        readmes = [path.resolve() for path in explicit_readmes]
    else:
        readmes = [project_root / "README.md"]
        readmes.extend(
            sorted(
                path
                for path in project_root.glob("*/README.md")
                if not path.parts[-2].startswith(".")
            )
        )
        readmes = [path.resolve() for path in readmes if path.exists()]

    snapshot = build_feature_surface_snapshot(project_root)
    plan_text = _load_text(plan_file) if plan_file.exists() else ""
    readme_texts = {str(path): _load_text(path) for path in readmes}

    plan_phases = _extract_phase_numbers(plan_text)
    readme_phases = {path: _extract_phase_numbers(text) for path, text in readme_texts.items()}

    warnings: list[str] = []
    errors: list[str] = []
    checks: list[dict[str, object]] = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            warnings.append(f"{name}: {detail}")

    if not plan_file.exists():
        errors.append(f"PLAN.md not found: {plan_file}")

    if plan_phases:
        highest_plan_phase = max(plan_phases)
        for path, phases in readme_phases.items():
            if phases and max(phases) < highest_plan_phase:
                add_check(
                    f"phase-sync:{Path(path).name}",
                    False,
                    f"README phase {max(phases)} trails PLAN phase {highest_plan_phase}",
                )
            else:
                add_check(f"phase-sync:{Path(path).name}", True, "phase markers are not obviously behind")
    else:
        warnings.append("plan-phase: no explicit Phase markers found in PLAN.md")

    combined_docs = "\n".join([plan_text, *readme_texts.values()]).lower()
    undocumented_routes = []
    for token, route in _route_keywords(snapshot["app_routes"] + snapshot["api_routes"]).items():
        if token not in combined_docs:
            undocumented_routes.append({"token": token, "route": route})
    undocumented_migrations = []
    for token, migration in _migration_keywords(snapshot["migrations"]).items():
        if token not in combined_docs:
            undocumented_migrations.append({"token": token, "migration": migration})

    add_check(
        "feature-doc-coverage:routes",
        len(undocumented_routes) == 0,
        f"{len(undocumented_routes)} route keywords are not mentioned in PLAN/README",
    )
    add_check(
        "feature-doc-coverage:migrations",
        len(undocumented_migrations) == 0,
        f"{len(undocumented_migrations)} migration keywords are not mentioned in PLAN/README",
    )

    return {
        "ok": len(errors) == 0 and all(check["ok"] for check in checks),
        "project_root": str(project_root.resolve()),
        "plan_path": str(plan_file),
        "readme_paths": list(readme_texts.keys()),
        "surface": snapshot,
        "plan_phases": plan_phases,
        "readme_phases": readme_phases,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "undocumented_routes": undocumented_routes,
        "undocumented_migrations": undocumented_migrations,
    }


def format_human(result: dict[str, object]) -> str:
    lines = [
        "[doc_drift_checker]",
        build_summary_line(
            f"ok={result['ok']}",
            f"checks={len(result['checks'])}",
            f"undocumented_routes={len(result['undocumented_routes'])}",
            f"undocumented_migrations={len(result['undocumented_migrations'])}",
        ),
        f"project_root={result['project_root']}",
        f"plan_path={result['plan_path']}",
    ]
    for path in result["readme_paths"]:
        phases = result["readme_phases"].get(path) or []
        lines.append(f"readme={path} | phases={','.join(str(item) for item in phases) or '<none>'}")
    for warning in result["warnings"]:
        lines.append(f"warning: {warning}")
    for error in result["errors"]:
        lines.append(f"error: {error}")
    for item in result["undocumented_routes"]:
        lines.append(f"undocumented_route={item['route']} | token={item['token']}")
    for item in result["undocumented_migrations"]:
        lines.append(f"undocumented_migration={item['migration']} | token={item['token']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect lightweight drift between feature surface and docs.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--plan", help="Optional PLAN.md path override.")
    parser.add_argument("--readme", action="append", default=[], help="Optional README path. Repeatable.")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    result = assess_doc_drift(
        Path(args.project_root).resolve(),
        plan_path=Path(args.plan).resolve() if args.plan else None,
        readme_paths=[Path(item) for item in args.readme] if args.readme else None,
    )
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
