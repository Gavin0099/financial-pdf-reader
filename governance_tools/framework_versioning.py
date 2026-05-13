#!/usr/bin/env python3
"""
Helpers for reading framework release metadata and external adoption locks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


_README_VERSION_PATTERN = re.compile(r"- version:\s*`([^`]+)`")
# Badge format: [![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)]
_README_BADGE_VERSION_PATTERN = re.compile(r"badge/version-(\d+\.\d+\.\d+(?:-[^-\s]+)?)-")
# CHANGELOG.md: ## v1.1.0 or ## 1.1.0 (first match = latest release)
_CHANGELOG_VERSION_RE = re.compile(r"^##\s+v?(\d+\.\d+\.\d+(?:-[^\s]+)?)", re.MULTILINE)
_CANONICAL_FRAMEWORK_REPO = "https://github.com/Gavin0099/ai-governance-framework.git"


@dataclass
class FrameworkVersionStatus:
    current_release: str | None
    adopted_release: str | None
    adopted_commit: str | None
    framework_repo: str | None
    canonical_framework_repo: str
    framework_interface_version: str | None
    compatibility_range: str | None
    lock_file: str | None
    state: str
    reasons: list[str]


def is_framework_root(path: Path) -> bool:
    """Return True if *path* looks like an AI Governance Framework installation.

    Checks for the presence of any of:
      - governance_tools/    (Python tooling directory)
      - governance/          (governance data directory)
      - docs/governance-runtime*  (documentation marker)
    """
    return (
        (path / "governance_tools").is_dir()
        or (path / "governance").is_dir()
        or any(path.glob("docs/governance-runtime*"))
    )


def discover_framework_root(start_path: Path) -> Path | None:
    """Walk upward from *start_path* to find a framework root directory.

    Returns the first ancestor that satisfies :func:`is_framework_root`,
    or ``None`` if none is found before reaching the filesystem root.

    Edge cases (nested repos, monorepos, symlinks) are intentionally NOT
    handled — callers that need deterministic behaviour should supply an
    explicit path via CLI or GOVERNANCE_FRAMEWORK_ROOT env var.
    """
    current = start_path.resolve()
    while True:
        if is_framework_root(current):
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def repo_root_from_tooling() -> Path:
    """Return the framework root directory.

    Resolution order:
      1. GOVERNANCE_FRAMEWORK_ROOT env var — allows repos that vendor a copy of
         governance_tools/ to point back to the real framework installation.
      2. __file__ parent.parent — correct when running from the framework itself.
    """
    import os
    env_root = os.environ.get("GOVERNANCE_FRAMEWORK_ROOT", "").strip()
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parent.parent


def current_framework_release(project_root: Path | None = None) -> str | None:
    """Return the current framework version string.

    Resolution order:
    1. README.md list format:  ``- version: `1.1.0` ``
    2. README.md badge format: ``badge/version-1.1.0-blue``
    3. CHANGELOG.md first heading: ``## v1.1.0``
    """
    root = project_root.resolve() if project_root else repo_root_from_tooling()
    readme = root / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        match = _README_VERSION_PATTERN.search(text)
        if match:
            return match.group(1).strip()
        match = _README_BADGE_VERSION_PATTERN.search(text)
        if match:
            return match.group(1).strip()
    changelog = root / "CHANGELOG.md"
    if changelog.exists():
        match = _CHANGELOG_VERSION_RE.search(changelog.read_text(encoding="utf-8"))
        if match:
            return match.group(1).strip()
    return None


def load_framework_lock(repo_root: Path) -> dict[str, object] | None:
    lock_path = repo_root / "governance" / "framework.lock.json"
    if not lock_path.exists():
        return None
    payload = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    payload["_lock_file"] = str(lock_path.resolve())
    return payload


def _normalize_version(version: str | None) -> tuple[int, int, int, str] | None:
    if not version:
        return None
    raw = version.strip()
    if raw.startswith("v"):
        raw = raw[1:]
    core, sep, suffix = raw.partition("-")
    parts = core.split(".")
    if not all(part.isdigit() for part in parts):
        return None
    ints = [int(part) for part in parts]
    while len(ints) < 3:
        ints.append(0)
    return ints[0], ints[1], ints[2], suffix if sep else ""


def compare_versions(left: str | None, right: str | None) -> int | None:
    left_norm = _normalize_version(left)
    right_norm = _normalize_version(right)
    if left_norm is None or right_norm is None:
        return None
    left_core = left_norm[:3]
    right_core = right_norm[:3]
    if left_core < right_core:
        return -1
    if left_core > right_core:
        return 1
    left_suffix = left_norm[3]
    right_suffix = right_norm[3]
    if left_suffix == right_suffix:
        return 0
    if not left_suffix:
        return 1
    if not right_suffix:
        return -1
    if left_suffix < right_suffix:
        return -1
    if left_suffix > right_suffix:
        return 1
    return 0


def compare_version_cores(left: str | None, right: str | None) -> int | None:
    left_norm = _normalize_version(left)
    right_norm = _normalize_version(right)
    if left_norm is None or right_norm is None:
        return None
    left_core = left_norm[:3]
    right_core = right_norm[:3]
    if left_core < right_core:
        return -1
    if left_core > right_core:
        return 1
    return 0


def is_release_compatible(current_release: str | None, compatibility_range: str | None) -> bool | None:
    if not current_release or not compatibility_range:
        return None
    comparators = [item.strip() for item in compatibility_range.split(",") if item.strip()]
    if not comparators:
        return None
    for comparator in comparators:
        operator = None
        for candidate in (">=", "<=", ">", "<", "=="):
            if comparator.startswith(candidate):
                operator = candidate
                break
        if operator is None:
            return None
        version = comparator[len(operator):].strip()
        comparison = compare_version_cores(current_release, version)
        if comparison is None:
            return None
        if operator == ">=" and comparison < 0:
            return False
        if operator == "<=" and comparison > 0:
            return False
        if operator == ">" and comparison <= 0:
            return False
        if operator == "<" and comparison >= 0:
            return False
        if operator == "==" and comparison != 0:
            return False
    return True


def assess_framework_version_status(repo_root: Path, contract_raw: dict[str, object] | None = None) -> FrameworkVersionStatus:
    lock_payload = load_framework_lock(repo_root)
    current_release = current_framework_release()
    adopted_release = None
    adopted_commit = None
    framework_repo = None
    interface_version = None
    compatibility_range = None
    lock_file = None
    reasons: list[str] = []

    if contract_raw:
        interface_version = str(contract_raw.get("framework_interface_version") or "") or None
        compatibility_range = str(contract_raw.get("framework_compatible") or "") or None

    if lock_payload:
        framework_repo = str(lock_payload.get("framework_repo") or "") or None
        adopted_release = str(lock_payload.get("adopted_release") or "") or None
        adopted_commit = str(lock_payload.get("adopted_commit") or "") or None
        interface_version = str(lock_payload.get("framework_interface_version") or interface_version or "") or None
        compatibility_range = str(lock_payload.get("framework_compatible") or compatibility_range or "") or None
        lock_file = str(lock_payload.get("_lock_file"))
    else:
        reasons.append("framework lock file missing")

    if framework_repo and framework_repo.rstrip("/") != _CANONICAL_FRAMEWORK_REPO.rstrip("/"):
        reasons.append("framework repo does not match canonical official remote")

    compatibility_ok = is_release_compatible(current_release, compatibility_range)
    if compatibility_ok is False:
        reasons.append("current framework release is outside declared compatibility range")
    elif compatibility_ok is None and compatibility_range:
        reasons.append("compatibility range could not be evaluated")

    if not current_release:
        state = "unknown"
        reasons.append("current framework release could not be determined")
    elif not adopted_release:
        state = "unknown"
        reasons.append("adopted release not recorded")
    else:
        comparison = compare_versions(adopted_release, current_release)
        if comparison is None:
            state = "unknown"
            reasons.append("adopted release could not be compared to current release")
        elif compatibility_ok is False:
            state = "incompatible"
        elif comparison < 0:
            state = "outdated"
            reasons.append("adopted release is older than current framework release")
        elif comparison == 0:
            state = "current"
        else:
            state = "ahead"
            reasons.append("adopted release is newer than the local framework release")

    return FrameworkVersionStatus(
        current_release=current_release,
        adopted_release=adopted_release,
        adopted_commit=adopted_commit,
        framework_repo=framework_repo,
        canonical_framework_repo=_CANONICAL_FRAMEWORK_REPO,
        framework_interface_version=interface_version,
        compatibility_range=compatibility_range,
        lock_file=lock_file,
        state=state,
        reasons=reasons,
    )
