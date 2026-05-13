#!/usr/bin/env python3
"""
Validate whether AI Governance git hooks are installed correctly for a target repo.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


FRAMEWORK_MARKER = "AI Governance Framework"
REQUIRED_FRAMEWORK_FILES = [
    "scripts/lib/python.sh",
    "scripts/run-runtime-governance.sh",
    "governance_tools/plan_freshness.py",
    "governance_tools/contract_validator.py",
]


@dataclass
class HookInstallResult:
    valid: bool
    repo_root: str
    hook_dir: str
    framework_root: str | None
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _contains_framework_marker(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        return FRAMEWORK_MARKER in path.read_text(encoding="utf-8")
    except OSError:
        return False


def _normalize_framework_root(raw_value: str) -> Path:
    """Accept Windows-native paths and Git Bash/MSYS paths like /e/work/repo."""
    candidate = raw_value.strip()
    msys_match = re.match(r"^/([a-zA-Z])/(.*)$", candidate)
    if msys_match:
        drive = msys_match.group(1).upper()
        remainder = msys_match.group(2).replace("/", "\\")
        return Path(f"{drive}:\\{remainder}").expanduser()
    return Path(candidate).expanduser()


def validate_hook_install(repo_root: Path, framework_root: Path | None = None) -> HookInstallResult:
    repo_root = repo_root.resolve()
    hook_dir = repo_root / ".git" / "hooks"
    checks: dict[str, bool] = {}
    errors: list[str] = []
    warnings: list[str] = []

    if not hook_dir.is_dir():
        return HookInstallResult(
            valid=False,
            repo_root=str(repo_root),
            hook_dir=str(hook_dir),
            framework_root=None,
            checks={"git_hooks_dir_present": False},
            errors=[f"missing git hooks directory: {hook_dir}"],
        )

    checks["git_hooks_dir_present"] = True

    pre_commit = hook_dir / "pre-commit"
    pre_push = hook_dir / "pre-push"
    config_file = hook_dir / "ai-governance-framework-root"

    checks["pre_commit_installed"] = _contains_framework_marker(pre_commit)
    checks["pre_push_installed"] = _contains_framework_marker(pre_push)
    checks["framework_root_config_present"] = config_file.is_file()

    if not checks["pre_commit_installed"]:
        errors.append(f"missing AI Governance pre-commit hook: {pre_commit}")
    if not checks["pre_push_installed"]:
        errors.append(f"missing AI Governance pre-push hook: {pre_push}")

    resolved_framework_root = framework_root.resolve() if framework_root is not None else None
    if config_file.is_file():
        raw_value = config_file.read_text(encoding="utf-8").strip()
        if raw_value:
            resolved_framework_root = _normalize_framework_root(raw_value)
        else:
            errors.append(f"framework root config is empty: {config_file}")
    elif resolved_framework_root is not None:
        warnings.append(
            f"ai-governance-framework-root not found; using explicit framework root: {resolved_framework_root}"
        )
    else:
        warnings.append(
            "ai-governance-framework-root not found; temporarily treating the target repo as the framework root."
        )
        resolved_framework_root = repo_root

    if resolved_framework_root is not None:
        checks["framework_root_exists"] = resolved_framework_root.is_dir()
        if not checks["framework_root_exists"]:
            errors.append(f"framework root does not exist: {resolved_framework_root}")
        else:
            for relpath in REQUIRED_FRAMEWORK_FILES:
                key = f"framework_file:{relpath}"
                present = (resolved_framework_root / relpath).is_file()
                checks[key] = present
                if not present:
                    errors.append(f"framework root missing required file: {resolved_framework_root / relpath}")
    else:
        checks["framework_root_exists"] = False

    return HookInstallResult(
        valid=len(errors) == 0,
        repo_root=str(repo_root),
        hook_dir=str(hook_dir),
        framework_root=(
            str(resolved_framework_root.resolve())
            if resolved_framework_root and resolved_framework_root.exists()
            else (str(resolved_framework_root) if resolved_framework_root else None)
        ),
        checks=checks,
        errors=errors,
        warnings=warnings,
    )


def format_human(result: HookInstallResult) -> str:
    lines = [
        "AI Governance Hook Install Validation",
        "",
        f"valid              = {result.valid}",
        f"repo_root          = {result.repo_root}",
        f"hook_dir           = {result.hook_dir}",
        f"framework_root     = {result.framework_root or '<missing>'}",
        "",
        "[checks]",
    ]
    for key in sorted(result.checks):
        lines.append(f"{key:<32} = {result.checks[key]}")

    if result.errors:
        lines.append("")
        lines.append(f"errors: {len(result.errors)}")
        for item in result.errors:
            lines.append(f"- {item}")

    if result.warnings:
        lines.append("")
        lines.append(f"warnings: {len(result.warnings)}")
        for item in result.warnings:
            lines.append(f"- {item}")

    return "\n".join(lines)


def format_json(result: HookInstallResult) -> str:
    return json.dumps(
        {
            "valid": result.valid,
            "repo_root": result.repo_root,
            "hook_dir": result.hook_dir,
            "framework_root": result.framework_root,
            "checks": result.checks,
            "errors": result.errors,
            "warnings": result.warnings,
        },
        ensure_ascii=False,
        indent=2,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate AI Governance hook installation state for a target repo."
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Target git repo root to inspect (default: current directory).",
    )
    parser.add_argument(
        "--framework-root",
        help="Optional explicit framework root to validate against when hooks are not installed yet.",
    )
    parser.add_argument(
        "--format",
        choices=("human", "json"),
        default="human",
        help="Output format.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    result = validate_hook_install(
        Path(args.repo),
        framework_root=Path(args.framework_root) if args.framework_root else None,
    )
    if args.format == "json":
        print(format_json(result))
    else:
        print(format_human(result))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
