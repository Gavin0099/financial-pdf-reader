#!/usr/bin/env python3
"""
Rule pack discovery and loading helpers.
"""

from __future__ import annotations

import re
from pathlib import Path

from governance_tools.rule_classifier import (
    detect_repo_type,
    filter_rule_packs,
    load_rule_registry,
)


DEFAULT_RULES_ROOT = Path(__file__).resolve().parent.parent / "governance" / "rules"

RULE_PACK_CATEGORIES = {
    "common": "scope",
    "refactor": "scope",
    "release": "scope",
    "cpp": "language",
    "python": "language",
    "csharp": "language",
    "swift": "language",
    "objective-c": "language",
    "avalonia": "framework",
    "electron": "framework",
    "kernel-driver": "platform",
    "kmdf": "platform",
    "wdm": "platform",
    "umdf": "platform",
    "gl-hub-vendor-cmd": "platform",
}


def parse_rule_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else value.split(",")
    parsed = []
    seen = set()
    for item in raw_items:
        name = item.strip()
        if not name or name in seen:
            continue
        parsed.append(name)
        seen.add(name)
    return parsed


def _normalize_rules_roots(rules_root: Path | list[Path] | tuple[Path, ...] | None = None) -> list[Path]:
    if rules_root is None:
        return [DEFAULT_RULES_ROOT]
    if isinstance(rules_root, Path):
        return [rules_root]
    return list(rules_root)


def available_rule_packs(rules_root: Path | list[Path] | tuple[Path, ...] = DEFAULT_RULES_ROOT) -> set[str]:
    packs = set()
    for root in _normalize_rules_roots(rules_root):
        if not root.exists():
            continue
        packs.update(entry.name for entry in root.iterdir() if entry.is_dir())
    return packs


def _read_rule_file(rule_file: Path, rules_root: Path) -> dict:
    text = rule_file.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else rule_file.stem
    try:
        display_path = str(rule_file.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        try:
            display_path = str(rule_file.relative_to(rules_root.parent))
        except ValueError:
            display_path = str(rule_file)
    return {
        "path": display_path,
        "title": title,
        "content": text.strip(),
    }


def rule_pack_category(name: str) -> str:
    return RULE_PACK_CATEGORIES.get(name, "custom")


def load_rule_content(requested_rules: list[str], rules_root: Path | list[Path] | tuple[Path, ...] = DEFAULT_RULES_ROOT) -> dict:
    rules_roots = _normalize_rules_roots(rules_root)
    available = available_rule_packs(rules_roots)
    active_rules = []
    missing = []

    for name in requested_rules:
        if name not in available:
            missing.append(name)
            continue
        pack_dir = next((root / name for root in rules_roots if (root / name).exists()), None)
        if pack_dir is None:
            missing.append(name)
            continue
        active_rules.append(
            {
                "name": name,
                "category": rule_pack_category(name),
                "files": [_read_rule_file(rule_file, pack_dir.parent) for rule_file in sorted(pack_dir.glob("*.md"))],
            }
        )

    return {
        "requested": requested_rules,
        "active_rules": active_rules,
        "missing": missing,
        "valid": not missing,
    }


_REGISTRY_CACHE: list[dict] | None = None


def get_rule_registry(registry_path: Path | str | None = None) -> list[dict]:
    """Return the rule registry, using a module-level cache after the first load."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is None:
        _REGISTRY_CACHE = load_rule_registry(registry_path)
    return _REGISTRY_CACHE


def invalidate_registry_cache() -> None:
    """Invalidate the cached rule registry (useful for testing)."""
    global _REGISTRY_CACHE
    _REGISTRY_CACHE = None


def get_context_aware_rule_packs(
    project_root: Path,
    task_type: str = "general",
    risk_level: str = "medium",
    rules_root: "Path | list[Path] | tuple[Path, ...] | None" = None,
) -> dict:
    """
    Return context-aware rule packs based on detected repo type and task type.

    Returns a dict with:
        repo_type      — detected repo type (firmware/product/service/tooling)
        task_type      — the task type passed in
        active_packs   — list of rule pack names that should be activated
        registry_count — number of packs in the registry
    """
    registry = get_rule_registry()
    repo_type = detect_repo_type(project_root)
    active_packs = filter_rule_packs(
        registry,
        repo_type=repo_type,
        task_type=task_type,
        risk_level=risk_level,
    )
    return {
        "repo_type": repo_type,
        "task_type": task_type,
        "active_packs": active_packs,
        "registry_count": len(registry),
    }


def describe_rule_selection(
    requested_rules: list[str],
    rules_root: Path | list[Path] | tuple[Path, ...] = DEFAULT_RULES_ROOT,
) -> dict:
    loaded = load_rule_content(requested_rules, rules_root)
    resolved = []

    for pack in loaded["active_rules"]:
        resolved.append(
            {
                "name": pack["name"],
                "category": pack["category"],
                "files": [entry["path"] for entry in pack["files"]],
            }
        )

    return {
        "requested": requested_rules,
        "resolved": resolved,
        "missing": loaded["missing"],
        "valid": loaded["valid"],
    }
