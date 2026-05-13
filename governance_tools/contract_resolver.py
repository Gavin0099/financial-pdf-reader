#!/usr/bin/env python3
"""
Resolve domain contract paths with explicit, environment, and discovery fallbacks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


MAX_DISCOVERY_ASCENT = 3
CONTRACT_ENV_VAR = "AI_GOVERNANCE_CONTRACT"


@dataclass
class ContractResolution:
    path: Path | None
    source: str
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def _search_upward_for_contract(start_root: Path, max_ascent: int = MAX_DISCOVERY_ASCENT) -> Path | None:
    current = start_root.resolve()
    for depth in range(max_ascent + 1):
        candidate = current / "contract.yaml"
        if candidate.exists():
            return candidate.resolve()
        if (current / ".git").exists():
            break
        if current.parent == current:
            break
        if depth == max_ascent:
            break
        current = current.parent
    return None


def resolve_contract(
    explicit_path: str | Path | None = None,
    *,
    project_root: str | Path | None = None,
    extra_paths: list[str | Path] | None = None,
    env_var: str = CONTRACT_ENV_VAR,
) -> ContractResolution:
    if explicit_path is not None:
        explicit = Path(explicit_path).expanduser().resolve()
        if explicit.exists():
            return ContractResolution(path=explicit, source="explicit")
        return ContractResolution(
            path=None,
            source="explicit",
            error=f"Explicit contract path does not exist: {explicit}",
        )

    env_value = os.environ.get(env_var, "").strip()
    if env_value:
        env_path = Path(env_value).expanduser().resolve()
        if env_path.exists():
            return ContractResolution(path=env_path, source="env")
        env_warning = f"{env_var} points to a missing contract: {env_path}"
    else:
        env_warning = None

    candidates: list[Path] = []
    search_roots: list[Path] = []
    if project_root is not None:
        search_roots.append(Path(project_root).resolve())
    for item in extra_paths or []:
        if item is None:
            continue
        path = Path(item).resolve()
        search_roots.append(path.parent if path.is_file() else path)
    # Only fall back to cwd when no project_root was given; adding cwd unconditionally
    # would cause spurious ambiguity when the framework itself has a contract.yaml.
    if project_root is None and not extra_paths:
        search_roots.append(Path.cwd().resolve())

    seen_roots: set[Path] = set()
    for root in search_roots:
        if root in seen_roots:
            continue
        seen_roots.add(root)
        candidate = _search_upward_for_contract(root)
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    warnings: list[str] = []
    if env_warning:
        warnings.append(env_warning)

    if len(candidates) > 1:
        joined = ", ".join(str(path) for path in candidates)
        warnings.append(
            "Multiple contract.yaml candidates were discovered; specify --contract explicitly: "
            f"{joined}"
        )
        return ContractResolution(path=None, source="not_found", warnings=warnings)

    if len(candidates) == 1:
        return ContractResolution(path=candidates[0], source="discovery", warnings=warnings)

    return ContractResolution(path=None, source="not_found", warnings=warnings)
