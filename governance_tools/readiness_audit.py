#!/usr/bin/env python3
"""
Readiness audit — scan one or more repos and report their closeout readiness level.

Purpose: understand distribution before fixing. Phase 1 of the three-phase
closeout readiness rollout (docs/closeout-readiness-rollout.md).

Usage:
    # Single repo
    python -m governance_tools.readiness_audit --repo /path/to/repo

    # Multiple repos (space-separated)
    python -m governance_tools.readiness_audit --repo /path/a /path/b /path/c

    # Scan a directory for repos (one level deep)
    python -m governance_tools.readiness_audit --scan-dir /workspace

    # JSON output
    python -m governance_tools.readiness_audit --repo /path/to/repo --format json

Output:
    Table showing: repo → level → limiting_factor → suggested_next_step

Reads:
    Uses detect_readiness_level() from session_end_hook — same logic as runtime.

Does NOT modify any repo. Read-only audit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from governance_tools.session_end_hook import detect_readiness_level


# ── Suggested next steps per limiting factor ─────────────────────────────────

_NEXT_STEP: dict[str, str] = {
    "artifacts_not_writable": (
        "mkdir -p artifacts/runtime && chmod -R u+w artifacts/"
    ),
    "schema_doc_present": (
        "Ensure docs/session-closeout-schema.md exists in the framework repo"
    ),
    "agents_base_has_obligation": (
        "python -m governance_tools.upgrade_closeout --repo <repo>"
    ),
    "agents_base_has_anchor_guidance": (
        "python -m governance_tools.upgrade_closeout --repo <repo>  "
        "(re-run to patch anchor guidance)"
    ),
    "prior_verdict_artifacts_exist": (
        "Run one session with a valid closeout to produce the first verdict artifact; "
        "or run: python -m governance_tools.session_end_hook --project-root <repo>"
    ),
    "tool_artifact_signals_configured": (
        "Update session_end_hook.py _TOOL_ARTIFACT_SIGNALS for this repo's toolchain"
    ),
}

_LEVEL_LABEL = {
    0: "Hook entry only",
    1: "Canonical closeout ready",
    2: "Content governed",
    3: "Cross-referenced",
}


def _next_step_for(limiting_factor: str | None, repo: Path) -> str:
    if limiting_factor is None:
        return "—"
    template = _NEXT_STEP.get(limiting_factor, f"Resolve: {limiting_factor}")
    return template.replace("<repo>", str(repo))


def audit_repo(repo: Path, framework_root: Path) -> dict[str, Any]:
    """Run readiness detection on a single repo. Returns structured result."""
    repo = repo.resolve()
    if not repo.exists():
        return {
            "repo": str(repo),
            "error": "path does not exist",
            "level": None,
            "limiting_factor": None,
            "suggested_next_step": None,
        }

    try:
        result = detect_readiness_level(repo, framework_root)
        level = result.get("level", 0)
        limiting = result.get("limiting_factor")
        return {
            "repo": str(repo),
            "level": level,
            "level_label": _LEVEL_LABEL.get(level, str(level)),
            "limiting_factor": limiting,
            "suggested_next_step": result.get("suggested_next_step") or _next_step_for(limiting, repo),
            "closeout_activation_state": result.get("closeout_activation_state", "unknown"),
            "activation_recency": result.get("activation_recency"),
            "activation_gap": result.get("activation_gap"),
            "checklist": result.get("checklist", {}),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "repo": str(repo),
            "error": str(exc),
            "level": None,
            "limiting_factor": None,
            "suggested_next_step": None,
        }


def _collect_repos(args: argparse.Namespace) -> list[Path]:
    repos: list[Path] = []

    if args.repo:
        for r in args.repo:
            repos.append(Path(r))

    if args.scan_dir:
        scan = Path(args.scan_dir)
        if not scan.is_dir():
            print(f"[readiness_audit] scan-dir does not exist: {scan}", file=sys.stderr)
            sys.exit(1)
        # Include the scan dir itself if it's a git repo
        if (scan / ".git").exists():
            repos.append(scan)
        # Plus any immediate subdirectories that are git repos
        for child in sorted(scan.iterdir()):
            if child.is_dir() and (child / ".git").exists() and child != scan:
                repos.append(child)

    return repos


def _print_table(results: list[dict[str, Any]]) -> None:
    # Column widths
    repo_width = max(len("REPO"), max((len(r["repo"]) for r in results), default=4))
    repo_width = min(repo_width, 55)  # cap to 55 chars

    header = (
        f"{'REPO':<{repo_width}}  {'LVL':>3}  {'ACTIVATION':<16}  LIMITING FACTOR / NEXT STEP"
    )
    print(header)
    print("-" * min(len(header) + 40, 120))

    for r in results:
        repo_display = r["repo"]
        if len(repo_display) > repo_width:
            repo_display = "…" + repo_display[-(repo_width - 1):]

        if r["error"]:
            print(f"{repo_display:<{repo_width}}  {'ERR':>3}  {'—':<16}  {r['error']}")
            continue

        level = str(r["level"])
        activation = r.get("closeout_activation_state", "—")
        recency = r.get("activation_recency")
        # Abbreviate activation for column; show recency if observed
        act_short = {"observed": "observed", "pending": "pending", "unknown": "—"}.get(activation, activation)
        if recency:
            act_short = f"{act_short}/{recency}"
        limiting = r.get("limiting_factor") or "—"
        next_step = r.get("suggested_next_step") or "—"

        # Shorten next_step to fit terminal
        next_col = f"{limiting}  →  {next_step}"
        if len(next_col) > 70:
            next_col = next_col[:67] + "…"

        print(f"{repo_display:<{repo_width}}  {level:>3}  {act_short:<16}  {next_col}")


def _print_summary(results: list[dict[str, Any]]) -> None:
    from collections import Counter
    good = [r for r in results if r["error"] is None]
    errors = sum(1 for r in results if r["error"])
    total = len(results)

    level_counts = Counter(r["level"] for r in good)
    factor_counts = Counter(r.get("limiting_factor") for r in good if r.get("limiting_factor"))
    activation_counts = Counter(r.get("closeout_activation_state", "unknown") for r in good)

    print()
    print("── Structural level distribution ─────────────────────────────────────")
    for lvl in sorted(level_counts):
        label = _LEVEL_LABEL.get(lvl, str(lvl))
        bar = "█" * level_counts[lvl]
        print(f"  Level {lvl} ({label:<28}): {level_counts[lvl]:>3}  {bar}")
    if errors:
        print(f"  Errors (could not audit)              : {errors:>3}")
    print(f"  Total repos scanned                   : {total:>3}")

    if factor_counts:
        print()
        print("── Adoption blockers (limiting_factor counts) ────────────────────────")
        for factor, count in factor_counts.most_common():
            bar = "█" * count
            print(f"  {factor:<44}: {count:>3}  {bar}")

    if activation_counts:
        print()
        print("── Activation state (observed=ran before, pending=not yet) ───────────")
        for state in ("observed", "pending", "unknown"):
            if state in activation_counts:
                bar = "█" * activation_counts[state]
                print(f"  {state:<44}: {activation_counts[state]:>3}  {bar}")
        # Recency breakdown for observed repos
        recency_counts: Counter = Counter(
            r.get("activation_recency")
            for r in good
            if r.get("closeout_activation_state") == "observed" and r.get("activation_recency")
        )
        if recency_counts:
            for recency, count in recency_counts.most_common():
                bar = "█" * count
                print(f"    of which {recency:<40}: {count:>3}  {bar}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit closeout readiness levels across one or more repos."
    )
    parser.add_argument(
        "--repo",
        nargs="+",
        metavar="PATH",
        help="One or more repo paths to audit",
    )
    parser.add_argument(
        "--scan-dir",
        metavar="DIR",
        help="Scan a directory for git repos (one level deep)",
    )
    parser.add_argument(
        "--framework-root",
        metavar="PATH",
        default=str(Path(__file__).resolve().parents[1]),
        help="Path to the ai-governance-framework repo (default: auto-detected)",
    )
    parser.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human)",
    )
    args = parser.parse_args()

    if not args.repo and not args.scan_dir:
        parser.print_help()
        sys.exit(1)

    repos = _collect_repos(args)
    if not repos:
        print("[readiness_audit] No repos found to audit.", file=sys.stderr)
        sys.exit(1)

    framework_root = Path(args.framework_root).resolve()
    results = [audit_repo(repo, framework_root) for repo in repos]

    if args.format == "json":
        print(json.dumps(results, indent=2))
        return

    # Human output
    _print_table(results)
    _print_summary(results)


if __name__ == "__main__":
    main()
