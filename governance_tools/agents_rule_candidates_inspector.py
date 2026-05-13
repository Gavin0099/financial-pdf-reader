#!/usr/bin/env python3
"""Read and validate the AGENTS rule candidates artifact; output reviewer-readable summary.

This is a reader/inspector only.  It does not write, promote, or mutate anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.agents_rule_aggregation_artifact import (
    DEFAULT_ARTIFACT_PATH,
    AgentsRuleAggregationArtifact,
)


# ---------------------------------------------------------------------------
# Load + validate
# ---------------------------------------------------------------------------

def load_artifact(artifact_path: Path) -> dict[str, Any]:
    """Load JSON from *artifact_path* and return raw dict, or error dict."""
    if not artifact_path.is_file():
        return {
            "ok": False,
            "exists": False,
            "artifact_file": str(artifact_path),
            "error": "artifact_not_found",
        }
    try:
        raw = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "exists": True,
            "artifact_file": str(artifact_path),
            "error": f"artifact_unreadable: {exc}",
        }
    return {"ok": True, "exists": True, "artifact_file": str(artifact_path), "raw": raw}


def validate_artifact(raw: dict[str, Any]) -> tuple[AgentsRuleAggregationArtifact | None, str | None]:
    """Construct and validate the artifact dataclass.  Returns (artifact, error_msg)."""
    try:
        artifact = AgentsRuleAggregationArtifact(
            schema_version=raw.get("schema_version", ""),
            generated_at=raw.get("generated_at", ""),
            source=raw.get("source", ""),
            candidates=raw.get("candidates", []),
            suppressed_candidates=raw.get("suppressed_candidates", []),
            ledger_refs=raw.get("ledger_refs", []),
        )
        artifact.validate()
        return artifact, None
    except (ValueError, TypeError) as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

def inspect_artifact(artifact_path: Path) -> dict[str, Any]:
    """Return a structured inspection result dict."""
    load_result = load_artifact(artifact_path)
    if not load_result.get("ok"):
        return {
            "ok": False,
            "exists": load_result.get("exists", False),
            "artifact_file": load_result.get("artifact_file", str(artifact_path)),
            "validation_ok": False,
            "error": load_result.get("error", "unknown_load_error"),
            "active_count": 0,
            "suppressed_count": 0,
            "ledger_ref_count": 0,
            "promotion": "none",
            "agents_mutation": "none",
        }

    raw = load_result["raw"]
    artifact, validation_error = validate_artifact(raw)

    if artifact is None:
        return {
            "ok": False,
            "exists": True,
            "artifact_file": load_result["artifact_file"],
            "schema_version": raw.get("schema_version"),
            "generated_at": raw.get("generated_at"),
            "source": raw.get("source"),
            "validation_ok": False,
            "error": f"contract_violation: {validation_error}",
            "active_count": 0,
            "suppressed_count": 0,
            "ledger_ref_count": 0,
            "promotion": "none",
            "agents_mutation": "none",
        }

    # Per-candidate summaries (lightweight — no re-validation, just shape extraction)
    active_summaries = _summarise_entries(artifact.candidates, suppressed=False)
    suppressed_summaries = _summarise_entries(artifact.suppressed_candidates, suppressed=True)

    return {
        "ok": True,
        "exists": True,
        "artifact_file": load_result["artifact_file"],
        "schema_version": artifact.schema_version,
        "generated_at": artifact.generated_at,
        "source": artifact.source,
        "validation_ok": True,
        "active_count": len(artifact.candidates),
        "suppressed_count": len(artifact.suppressed_candidates),
        "ledger_ref_count": len(artifact.ledger_refs),
        "ledger_refs": list(artifact.ledger_refs),
        "promotion": "none",
        "agents_mutation": "none",
        "active_candidates": active_summaries,
        "suppressed_candidates": suppressed_summaries,
    }


def _summarise_entries(entries: list[dict[str, Any]], *, suppressed: bool) -> list[dict[str, Any]]:
    summaries = []
    for entry in entries:
        if not isinstance(entry, dict):
            summaries.append({"error": "non-dict entry"})
            continue
        summaries.append({
            "candidate_id": entry.get("candidate_id", "<missing>"),
            "evidence_count": entry.get("evidence_count", 0),
            "evidence_window_days": entry.get("evidence_window_days"),
            "repo_specificity": entry.get("repo_specificity"),
            "resurfacing_allowed": entry.get("resurfacing_allowed"),
            "resurfacing_reason": entry.get("resurfacing_reason"),
            "suppressed_by_ledger": entry.get("suppressed_by_ledger"),
            "first_seen_at": entry.get("first_seen_at"),
            "last_seen_at": entry.get("last_seen_at"),
            "suppressed": suppressed,
        })
    return summaries


# ---------------------------------------------------------------------------
# Reviewer-readable output
# ---------------------------------------------------------------------------

def format_summary(result: dict[str, Any]) -> str:
    lines: list[str] = []
    ok_label = "ok" if result.get("ok") else "FAIL"
    lines.append(f"AGENTS rule candidates: [{ok_label}]")
    lines.append(f"  artifact_file   : {result.get('artifact_file', 'unknown')}")

    if not result.get("exists"):
        lines.append("  exists          : no  (artifact not found)")
        lines.append(f"  error           : {result.get('error', '')}")
        return "\n".join(lines)

    lines.append(f"  schema_version  : {result.get('schema_version', '<missing>')}")
    lines.append(f"  generated_at    : {result.get('generated_at', '<missing>')}")
    lines.append(f"  source          : {result.get('source', '<missing>')}")
    lines.append(f"  validation_ok   : {'yes' if result.get('validation_ok') else 'FAIL'}")

    if not result.get("validation_ok"):
        lines.append(f"  error           : {result.get('error', '')}")
        return "\n".join(lines)

    lines.append(f"  active          : {result.get('active_count', 0)}")
    lines.append(f"  suppressed      : {result.get('suppressed_count', 0)}")
    lines.append(f"  ledger_refs     : {result.get('ledger_ref_count', 0)}")
    lines.append(f"  promotion       : {result.get('promotion', 'none')}")
    lines.append(f"  AGENTS.md mut   : {result.get('agents_mutation', 'none')}")

    active = result.get("active_candidates", [])
    if active:
        lines.append("")
        lines.append("  Active candidates:")
        for entry in active:
            cid = entry.get("candidate_id", "<missing>")
            ec = entry.get("evidence_count", 0)
            rs = entry.get("repo_specificity", "?")
            lines.append(f"    - {cid}")
            lines.append(f"        evidence_count={ec}  repo_specificity={rs}")

    suppressed = result.get("suppressed_candidates", [])
    if suppressed:
        lines.append("")
        lines.append("  Suppressed candidates:")
        for entry in suppressed:
            cid = entry.get("candidate_id", "<missing>")
            reason = entry.get("resurfacing_reason", "?")
            lines.append(f"    - {cid}")
            lines.append(f"        resurfacing_reason={reason}")

    refs = result.get("ledger_refs", [])
    if refs:
        lines.append("")
        lines.append("  Ledger refs:")
        for ref in refs:
            lines.append(f"    - {ref}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect the AGENTS rule candidates artifact (read-only).",
    )
    parser.add_argument(
        "--artifact",
        default=None,
        help=(
            "Path to agents_rule_candidates.json "
            f"(default: <project_root>/{DEFAULT_ARTIFACT_PATH})"
        ),
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
    if args.artifact:
        artifact_path = Path(args.artifact)
    else:
        artifact_path = project_root / DEFAULT_ARTIFACT_PATH

    result = inspect_artifact(artifact_path)

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        print(format_summary(result))

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
