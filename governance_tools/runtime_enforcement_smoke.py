#!/usr/bin/env python3
"""
Runtime Enforcement Boundary Smoke — second framework risk signal source.

Validates that the framework's own runtime enforcement entrypoints are
functioning.  When a check fails, writes a framework risk signal via the
same mechanism as governance_drift_checker.  When all checks pass, clears any
previously written signal from this source.

This module exists to prove that framework_risk_signal is not a drift-specific
hack but a reusable stateful control substrate.  Two independent signal sources
(drift-triggered and enforcement-boundary-triggered) sharing one signal file
validates extensibility of the pattern.

Checks
──────
  pre_task_ok          run_pre_task_check returns ok=True against framework root
  session_start_ok     build_session_start_context returns ok=True
  dispatch_ok          dispatch_event does not raise and returns a result envelope

All checks are run against the framework's own PLAN.md and "common" rule pack,
with no external contract, so no external repo dependency exists.

Usage
─────
    python governance_tools/runtime_enforcement_smoke.py
    python governance_tools/runtime_enforcement_smoke.py --emit-signal
    python governance_tools/runtime_enforcement_smoke.py --format json

Exit codes: 0=ok, 1=failure
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.framework_risk_signal import (
    clear_risk_signal,
    write_risk_signal,
)
from governance_tools.framework_versioning import repo_root_from_tooling

# The single KNOWN_COMPONENTS entry this module maps to.
_AFFECTED_COMPONENT = "runtime_enforcement_entrypoint"
_SMOKE_SOURCE = "runtime_enforcement_smoke"


@dataclass
class EnforcementSmokeResult:
    ok: bool
    framework_root: str
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    signal_written: bool = False
    signal_cleared: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _run_pre_task_smoke(framework_root: Path) -> tuple[bool, str | None]:
    """
    Run a minimal run_pre_task_check against the framework root.
    Returns (ok, error_detail_or_None).
    """
    try:
        from runtime_hooks.core.pre_task_check import run_pre_task_check
        result = run_pre_task_check(
            project_root=framework_root,
            rules="common",
            risk="low",
            oversight="auto",
            memory_mode="candidate",
            task_text="enforcement boundary smoke",
            task_level="L1",
        )
        if result.get("ok"):
            return True, None
        return False, f"pre_task ok=False: {result.get('errors', [])}"
    except Exception:
        return False, f"pre_task raised: {traceback.format_exc(limit=3)}"


def _run_session_start_smoke(framework_root: Path) -> tuple[bool, str | None]:
    """
    Run a minimal build_session_start_context against the framework root.
    Returns (ok, error_detail_or_None).
    """
    try:
        from runtime_hooks.core.session_start import build_session_start_context
        plan_path = framework_root / "PLAN.md"
        if not plan_path.exists():
            return False, "PLAN.md not found in framework root"
        result = build_session_start_context(
            project_root=framework_root,
            plan_path=plan_path,
            rules="common",
            risk="low",
            oversight="auto",
            memory_mode="candidate",
            task_text="enforcement boundary smoke",
            task_level="L1",
        )
        if result.get("ok"):
            return True, None
        return False, f"session_start ok=False: {result.get('state', {}).get('error')}"
    except Exception:
        return False, f"session_start raised: {traceback.format_exc(limit=3)}"


def _run_dispatch_smoke(framework_root: Path) -> tuple[bool, str | None]:
    """
    Run a minimal dispatch_event against the framework root using the shared
    session_start example, overriding project_root to the framework root.
    Returns (ok, error_detail_or_None).
    """
    try:
        from runtime_hooks.dispatcher import dispatch_event
        from runtime_hooks.runtime_path_overrides import apply_runtime_path_overrides

        example_path = (
            framework_root / "runtime_hooks" / "examples" / "shared" / "session_start.shared.json"
        )
        if not example_path.exists():
            return False, f"shared example not found: {example_path}"

        event = json.loads(example_path.read_text(encoding="utf-8"))
        event = apply_runtime_path_overrides(
            event,
            project_root=framework_root,
            plan_path=framework_root / "PLAN.md",
        )
        envelope = dispatch_event(event)
        if not isinstance(envelope, dict):
            return False, f"dispatch_event returned non-dict: {type(envelope)}"
        result = envelope.get("result") or {}
        if result.get("ok", True):  # default True: some dispatch paths don't set ok
            return True, None
        return False, f"dispatch envelope ok=False: {result.get('errors', [])}"
    except Exception:
        return False, f"dispatch raised: {traceback.format_exc(limit=3)}"


def check_enforcement_boundary(
    framework_root: Path | None = None,
    *,
    emit_risk_signal: bool = False,
) -> EnforcementSmokeResult:
    """
    Run all enforcement boundary smoke checks.

    When emit_risk_signal=True:
      - any failure  → write_risk_signal(["runtime_enforcement_entrypoint"])
      - all pass     → clear_risk_signal() (event-based decay, same as drift checker)

    Returns EnforcementSmokeResult.
    """
    fw_root = (framework_root or repo_root_from_tooling()).resolve()

    checks: dict[str, bool] = {}
    errors: list[str] = []

    pre_ok, pre_err = _run_pre_task_smoke(fw_root)
    checks["pre_task_ok"] = pre_ok
    if pre_err:
        errors.append(f"pre_task_ok: {pre_err}")

    session_ok, session_err = _run_session_start_smoke(fw_root)
    checks["session_start_ok"] = session_ok
    if session_err:
        errors.append(f"session_start_ok: {session_err}")

    dispatch_ok, dispatch_err = _run_dispatch_smoke(fw_root)
    checks["dispatch_ok"] = dispatch_ok
    if dispatch_err:
        errors.append(f"dispatch_ok: {dispatch_err}")

    overall_ok = all(checks.values())
    signal_written = False
    signal_cleared = False

    if emit_risk_signal:
        if not overall_ok:
            write_risk_signal(
                fw_root,
                affected_components=[_AFFECTED_COMPONENT],
                severity="critical",
                source=_SMOKE_SOURCE,
            )
            signal_written = True
        else:
            signal_cleared = clear_risk_signal(fw_root)

    return EnforcementSmokeResult(
        ok=overall_ok,
        framework_root=str(fw_root),
        checks=checks,
        errors=errors,
        signal_written=signal_written,
        signal_cleared=signal_cleared,
    )


def format_human(result: EnforcementSmokeResult) -> str:
    lines = [
        "[runtime_enforcement_smoke]",
        f"ok={result.ok}",
        f"framework_root={result.framework_root}",
    ]
    lines.append("[checks]")
    for key, val in result.checks.items():
        lines.append(f"  {key:<25} {'PASS' if val else 'FAIL'}")
    if result.errors:
        lines.append(f"errors ({len(result.errors)}):")
        for err in result.errors:
            lines.append(f"  - {err}")
    if result.signal_written:
        lines.append(f"signal_written=True (component={_AFFECTED_COMPONENT})")
    if result.signal_cleared:
        lines.append("signal_cleared=True")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate framework runtime enforcement boundary and optionally write risk signal."
    )
    parser.add_argument(
        "--emit-signal",
        action="store_true",
        help="Write risk signal on failure; clear it on pass.",
    )
    parser.add_argument(
        "--framework-root",
        help="Explicit framework root path (default: auto-detect from tooling).",
    )
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    fw_root = Path(args.framework_root).resolve() if args.framework_root else None
    result = check_enforcement_boundary(fw_root, emit_risk_signal=args.emit_signal)
    if args.format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_human(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
