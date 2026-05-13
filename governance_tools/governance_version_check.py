#!/usr/bin/env python3
"""Governance version compatibility check — read-only, no migration.

Compares a repo's .governance/version_manifest.yaml against the framework's
governance/runtime/required_versions.yaml and emits a compatibility verdict.

Verdicts:
  compatible                 All version requirements and all features satisfied.
  compatible_with_degradation  Extended features disabled; core runtime still runs.
  migration_required         Core features disabled; new-version features must not activate.
  unsupported                Manifest missing or unreadable; cannot claim governance active.

This tool does NOT perform migration.  It does NOT mutate any governance state.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


GOVERNANCE_VERSION_CHECK_SCHEMA_VERSION = "1.0"
ALLOWED_VERDICTS = (
    "compatible",
    "compatible_with_degradation",
    "migration_required",
    "unsupported",
)

DEFAULT_REQUIRED_VERSIONS_PATH = "governance/runtime/required_versions.yaml"
DEFAULT_VERSION_MANIFEST_PATH = ".governance/version_manifest.yaml"
DEFAULT_ARTIFACT_PATH = "artifacts/governance/version_compatibility.json"


# ---------------------------------------------------------------------------
# Version comparison (stdlib only, no packaging dependency)
# ---------------------------------------------------------------------------

def _parse_version(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in str(v).strip().split("."))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"unparseable version string: {v!r}") from exc


def _satisfies(actual: str, requirement: str) -> bool:
    """Return True if *actual* version satisfies *requirement* constraint.

    Only ">=" is supported in v0.1.
    """
    requirement = requirement.strip()
    if not requirement.startswith(">="):
        raise ValueError(
            f"unsupported version operator in {requirement!r} — only '>=' is supported in v0.1"
        )
    req = _parse_version(requirement[2:])
    act = _parse_version(actual)
    length = max(len(req), len(act))
    req = req + (0,) * (length - len(req))
    act = act + (0,) * (length - len(act))
    return act >= req


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class VersionCheck:
    key: str
    required: str
    actual: str | None
    satisfied: bool
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class VersionCompatibilityResult:
    schema_version: str
    checked_at: str
    repo_manifest_found: bool
    framework_version: str
    verdict: str
    checks: list[VersionCheck] = field(default_factory=list)
    enabled_runtime_features: list[str] = field(default_factory=list)
    disabled_runtime_features: list[str] = field(default_factory=list)
    missing_migrations: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Return (data, error_msg). error_msg is None on success."""
    if not path.is_file():
        return None, f"not_found:{path}"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None, f"yaml_not_a_mapping:{path}"
        return data, None
    except Exception as exc:
        return None, f"yaml_parse_error:{exc}"


def _run_version_checks(
    manifest: dict[str, Any],
    required: dict[str, str],
) -> list[VersionCheck]:
    checks: list[VersionCheck] = []
    for key, requirement in required.items():
        actual = manifest.get(key)
        if actual is None:
            checks.append(VersionCheck(
                key=key,
                required=requirement,
                actual=None,
                satisfied=False,
                note="key_missing_in_manifest",
            ))
            continue
        actual_str = str(actual)
        try:
            satisfied = _satisfies(actual_str, requirement)
            checks.append(VersionCheck(key=key, required=requirement, actual=actual_str, satisfied=satisfied))
        except ValueError as exc:
            checks.append(VersionCheck(
                key=key,
                required=requirement,
                actual=actual_str,
                satisfied=False,
                note=f"comparison_error:{exc}",
            ))
    return checks


def _evaluate_features(
    manifest: dict[str, Any],
    features: dict[str, Any],
) -> tuple[list[str], list[str], list[str]]:
    """Return (enabled_features, disabled_features, missing_migrations)."""
    enabled: list[str] = []
    disabled: list[str] = []
    missing_migrations: set[str] = set()

    for feature_name, feature_spec in features.items():
        requires = feature_spec.get("requires", {})
        feature_ok = True
        for key, req in requires.items():
            actual = manifest.get(key)
            if actual is None:
                feature_ok = False
                missing_migrations.add(f"{key}:{req}")
                continue
            try:
                if not _satisfies(str(actual), req):
                    feature_ok = False
                    missing_migrations.add(f"{key}:{req}")
            except ValueError:
                feature_ok = False
                missing_migrations.add(f"{key}:{req}")

        if feature_ok:
            enabled.append(feature_name)
        else:
            disabled.append(feature_name)

    return sorted(enabled), sorted(disabled), sorted(missing_migrations)


def _determine_verdict(
    disabled_features: list[str],
    core_features: set[str],
) -> str:
    if not disabled_features:
        return "compatible"
    if any(f in core_features for f in disabled_features):
        return "migration_required"
    return "compatible_with_degradation"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_version_compatibility(
    *,
    required_versions_path: Path,
    version_manifest_path: Path,
    checked_at: str | None = None,
) -> VersionCompatibilityResult:
    """Run the version compatibility check and return a structured result.

    Does not write any artifact — caller decides what to do with the result.
    """
    if checked_at is None:
        checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Load framework required_versions
    req_data, req_err = _load_yaml(required_versions_path)
    if req_err:
        return VersionCompatibilityResult(
            schema_version=GOVERNANCE_VERSION_CHECK_SCHEMA_VERSION,
            checked_at=checked_at,
            repo_manifest_found=False,
            framework_version="unknown",
            verdict="unsupported",
            error=f"required_versions_load_error:{req_err}",
        )

    framework_version = str(req_data.get("framework_version", "unknown"))
    required: dict[str, str] = req_data.get("required", {})
    features: dict[str, Any] = req_data.get("features", {})
    core_features: set[str] = {
        name for name, spec in features.items()
        if isinstance(spec, dict) and spec.get("tier") == "core"
    }

    # Load repo version_manifest
    manifest_data, manifest_err = _load_yaml(version_manifest_path)
    if manifest_err:
        return VersionCompatibilityResult(
            schema_version=GOVERNANCE_VERSION_CHECK_SCHEMA_VERSION,
            checked_at=checked_at,
            repo_manifest_found=False,
            framework_version=framework_version,
            verdict="unsupported",
            error=f"version_manifest_load_error:{manifest_err}",
        )

    # Run checks
    checks = _run_version_checks(manifest_data, required)
    enabled, disabled, missing_migrations = _evaluate_features(manifest_data, features)
    verdict = _determine_verdict(disabled, core_features)

    return VersionCompatibilityResult(
        schema_version=GOVERNANCE_VERSION_CHECK_SCHEMA_VERSION,
        checked_at=checked_at,
        repo_manifest_found=True,
        framework_version=framework_version,
        verdict=verdict,
        checks=checks,
        enabled_runtime_features=enabled,
        disabled_runtime_features=disabled,
        missing_migrations=missing_migrations,
    )


def write_compatibility_artifact(result: VersionCompatibilityResult, artifact_path: Path) -> None:
    """Write the compatibility result to a JSON artifact file."""
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(result.to_dict(), indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Reviewer-readable summary
# ---------------------------------------------------------------------------

def format_summary(result: VersionCompatibilityResult) -> str:
    verdict = result.verdict
    ok_label = "ok" if verdict == "compatible" else verdict.upper()
    lines: list[str] = []
    lines.append(f"Governance version compatibility: [{ok_label}]")
    lines.append(f"  framework_version  : {result.framework_version}")
    lines.append(f"  checked_at         : {result.checked_at}")
    lines.append(f"  repo_manifest_found: {'yes' if result.repo_manifest_found else 'no'}")

    if result.error:
        lines.append(f"  error              : {result.error}")
        return "\n".join(lines)

    lines.append(f"  verdict            : {verdict}")
    lines.append(f"  enabled_features   : {len(result.enabled_runtime_features)}")
    lines.append(f"  disabled_features  : {len(result.disabled_runtime_features)}")
    lines.append(f"  missing_migrations : {len(result.missing_migrations)}")

    if result.checks:
        lines.append("")
        lines.append("  Version checks:")
        for c in result.checks:
            mark = "ok  " if c.satisfied else "FAIL"
            actual_str = c.actual if c.actual is not None else "<missing>"
            lines.append(f"    {mark} {c.key}: required={c.required}  actual={actual_str}")
            if c.note:
                lines.append(f"        note: {c.note}")

    if result.disabled_runtime_features:
        lines.append("")
        lines.append("  Disabled features:")
        for f in result.disabled_runtime_features:
            lines.append(f"    - {f}")

    if result.missing_migrations:
        lines.append("")
        lines.append("  Missing migrations (upgrade needed):")
        for m in result.missing_migrations:
            lines.append(f"    - {m}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check governance version compatibility (read-only).",
    )
    parser.add_argument(
        "--required-versions",
        default=None,
        help=f"Path to required_versions.yaml (default: <root>/{DEFAULT_REQUIRED_VERSIONS_PATH})",
    )
    parser.add_argument(
        "--version-manifest",
        default=None,
        help=f"Path to version_manifest.yaml (default: <root>/{DEFAULT_VERSION_MANIFEST_PATH})",
    )
    parser.add_argument(
        "--write-artifact",
        default=None,
        metavar="PATH",
        help=f"Write compatibility JSON artifact to PATH (default: <root>/{DEFAULT_ARTIFACT_PATH})",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit JSON instead of human-readable summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parent.parent

    required_versions_path = (
        Path(args.required_versions)
        if args.required_versions
        else project_root / DEFAULT_REQUIRED_VERSIONS_PATH
    )
    version_manifest_path = (
        Path(args.version_manifest)
        if args.version_manifest
        else project_root / DEFAULT_VERSION_MANIFEST_PATH
    )

    result = check_version_compatibility(
        required_versions_path=required_versions_path,
        version_manifest_path=version_manifest_path,
    )

    if args.write_artifact:
        artifact_path = Path(args.write_artifact)
    elif args.write_artifact is None and not args.json_output:
        # Default: write artifact to standard location when running as CLI
        artifact_path = project_root / DEFAULT_ARTIFACT_PATH
        write_compatibility_artifact(result, artifact_path)

    if args.json_output:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(format_summary(result))

    return 0 if result.verdict in ("compatible", "compatible_with_degradation") else 1


if __name__ == "__main__":
    sys.exit(main())
