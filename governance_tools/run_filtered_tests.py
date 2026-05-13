#!/usr/bin/env python3
"""
run_filtered_tests.py — canonical filtered test suite entrypoint (E2+).

This is the ONLY authorised way to run the framework's filtered core suite.
Direct use of `pytest -k "not xxx..."` with hand-written exclusion strings
is a governance violation. All exclusions must flow through
governance/test_exclusion_registry.yaml.

Why this matters
----------------
Without a single enforced entrypoint, the exclusion registry exists but can
be bypassed — hand-written -k strings drift, and the registry becomes
documentation rather than a governing constraint.

Usage
-----
  python governance_tools/run_filtered_tests.py
  python governance_tools/run_filtered_tests.py --dry-run
  python governance_tools/run_filtered_tests.py -- tests/test_foo.py -v
  python governance_tools/run_filtered_tests.py --format json

Exit codes match pytest (0 = all passed, 1 = failures, 2 = interrupted, etc.)
In --dry-run mode, exits 0 after printing the resolved command.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.exclusion_registry_tool import (
    load_registry,
    generate_filter,
    audit_registry,
)

_DEFAULT_REGISTRY = (
    Path(__file__).resolve().parent.parent / "governance" / "test_exclusion_registry.yaml"
)
_DEFAULT_TEST_DIR = "tests/"


def build_pytest_command(
    k_expression: str,
    *,
    test_paths: list[str],
    extra_args: list[str],
) -> list[str]:
    cmd = [sys.executable, "-m", "pytest"]
    cmd.extend(test_paths)
    if k_expression:
        cmd += ["-k", k_expression]
    cmd.extend(extra_args)
    return cmd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the filtered core test suite using exclusions from "
            "governance/test_exclusion_registry.yaml. "
            "Do NOT use pytest -k directly — use this tool instead."
        ),
        epilog=(
            "Any arguments after -- are passed through to pytest verbatim.\n"
            "Example: python run_filtered_tests.py -- tests/test_foo.py -v"
        ),
    )
    parser.add_argument(
        "--registry",
        default=str(_DEFAULT_REGISTRY),
        help="Path to test_exclusion_registry.yaml",
    )
    parser.add_argument(
        "--test-dir",
        default=_DEFAULT_TEST_DIR,
        help="Test directory (default: tests/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved pytest command without running it",
    )
    parser.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="Output format for dry-run / pre-run info",
    )
    parser.add_argument(
        "--skip-audit",
        action="store_true",
        help="Skip registry integrity audit before running (not recommended)",
    )
    # Collect passthrough args after --
    try:
        sep = argv.index("--") if argv else -1
    except ValueError:
        sep = -1

    if sep >= 0:
        our_argv = (argv or sys.argv[1:])[:sep]
        passthrough = (argv or sys.argv[1:])[sep + 1 :]
    else:
        our_argv = argv
        passthrough = []

    args = parser.parse_args(our_argv)

    registry_path = Path(args.registry)
    if not registry_path.exists():
        print(f"[run_filtered_tests] ERROR: registry not found: {registry_path}", file=sys.stderr)
        return 2

    entries = load_registry(registry_path)

    # Integrity audit (warn on issues, don't block by default)
    if not args.skip_audit:
        audit = audit_registry(entries)
        if not audit.ok:
            print(
                "[run_filtered_tests] WARNING: registry has integrity issues "
                "(run exclusion_registry_tool.py audit for details)",
                file=sys.stderr,
            )
            if audit.expired:
                print(f"  Expired entries: {audit.expired}", file=sys.stderr)

    k_expr = generate_filter(entries, warn_expired=True)
    test_paths = [args.test_dir]
    cmd = build_pytest_command(k_expr, test_paths=test_paths, extra_args=passthrough)

    if args.dry_run:
        if args.format == "json":
            print(json.dumps({
                "command": cmd,
                "k_expression": k_expr,
                "active_exclusions": len([e for e in entries if e.active]),
                "registry": str(registry_path),
            }, indent=2))
        else:
            print("[run_filtered_tests] dry-run — resolved command:")
            print("  " + " ".join(cmd))
            print(f"\n  k_expression: {k_expr}")
            print(f"  active_exclusions: {len([e for e in entries if e.active])}")
        return 0

    if args.format == "json":
        # Print metadata to stderr so it doesn't pollute pytest stdout
        meta = {
            "k_expression": k_expr,
            "active_exclusions": len([e for e in entries if e.active]),
            "registry": str(registry_path),
        }
        print(json.dumps(meta), file=sys.stderr)
    else:
        print(f"[run_filtered_tests] registry={registry_path.name}  active_exclusions={len([e for e in entries if e.active])}")
        print(f"[run_filtered_tests] k_expression: {k_expr}\n")

    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
