#!/usr/bin/env python3
"""
Capture a lightweight feature-surface snapshot from routes and migrations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.human_summary import build_summary_line


def _normalize_route(path: Path, root: Path, suffix: str) -> str:
    relative = path.relative_to(root)
    parts = list(relative.parts[:-1])
    if parts and parts[0] == "api":
        parts = parts[1:]
    if parts and parts[-1] in {"page", "route"}:
        parts = parts[:-1]
    route = "/" + "/".join(parts)
    return route if route != "/" else suffix


def build_feature_surface_snapshot(project_root: Path) -> dict[str, object]:
    candidate_app_roots = [
        project_root / "app",
        project_root / "src" / "app",
    ]
    app_roots = [path for path in candidate_app_roots if path.is_dir()]

    if len(app_roots) > 1:
        print("warning: multiple app route roots detected", file=sys.stderr)

    supabase_root = project_root / "supabase" / "migrations"
    db_root = project_root / "db" / "migrations"

    page_files: list[tuple[Path, Path]] = []  # (file_path, root_path)
    route_files: list[tuple[Path, Path]] = []  # (file_path, root_path)

    for app_root in app_roots:
        pages = sorted(
            [
                path
                for path in app_root.rglob("*")
                if path.is_file() and path.stem == "page" and path.suffix in {".ts", ".tsx", ".js", ".jsx", ".mdx"}
            ]
        )
        page_files.extend([(path, app_root) for path in pages])

        api_root = app_root / "api"
        if api_root.is_dir():
            routes = sorted(
                [
                    path
                    for path in api_root.rglob("*")
                    if path.is_file() and path.stem == "route" and path.suffix in {".ts", ".tsx", ".js", ".jsx"}
                ]
            )
            route_files.extend([(path, api_root) for path in routes])

    migrations = []
    for root in (supabase_root, db_root):
        if root.is_dir():
            migrations.extend(sorted(root.glob("*.sql")))

    app_routes = sorted(list(set(_normalize_route(path, root, "/") for path, root in page_files)))
    api_routes = sorted(list(set(_normalize_route(path, root, "/") for path, root in route_files)))
    migration_names = [path.stem for path in migrations]

    return {
        "project_root": str(project_root.resolve()),
        "app_route_count": len(app_routes),
        "api_route_count": len(api_routes),
        "migration_count": len(migration_names),
        "app_routes": app_routes,
        "api_routes": api_routes,
        "migrations": migration_names,
    }


def format_human(snapshot: dict[str, object]) -> str:
    lines = [
        "[feature_surface_snapshot]",
        build_summary_line(
            f"app_routes={snapshot['app_route_count']}",
            f"api_routes={snapshot['api_route_count']}",
            f"migrations={snapshot['migration_count']}",
        ),
        f"project_root={snapshot['project_root']}",
    ]
    for route in snapshot["app_routes"]:
        lines.append(f"app_route={route}")
    for route in snapshot["api_routes"]:
        lines.append(f"api_route={route}")
    for migration in snapshot["migrations"]:
        lines.append(f"migration={migration}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a lightweight feature-surface snapshot.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    snapshot = build_feature_surface_snapshot(Path(args.project_root).resolve())
    if args.format == "json":
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        print(format_human(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
