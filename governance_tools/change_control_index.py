#!/usr/bin/env python3
"""
Build an index over generated change-control artifacts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.contract_context import extract_contract_context, normalize_session_start_payload
from governance_tools.domain_governance_metadata import domain_priority_rank
from governance_tools.human_summary import build_summary_line


def _extract_summary_line(path: Path) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("summary="):
            return line
    return None


def _priority_score(summary_line: str | None, session_start_json: Path | None = None) -> tuple[int, int, int, str]:
    if not summary_line:
        return (99, 99, 99, "")

    text = summary_line.lower()
    risk_order = {
        "proposal_risk=high": 0,
        "proposal_risk=medium": 1,
        "proposal_risk=low": 2,
    }
    risk_rank = 3
    for token, rank in risk_order.items():
        if token in text:
            risk_rank = rank
            break

    domain_rank = _domain_priority_rank(session_start_json)
    decision_rank = 1 if "runtime_decision=blocked" in text else 0
    promoted_rank = 1 if "promoted=false" in text else 0
    return (risk_rank, domain_rank, -decision_rank - promoted_rank, text)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def _domain_priority_rank(session_start_json: Path | None) -> int:
    if session_start_json is None or not session_start_json.exists():
        return 99

    try:
        payload = normalize_session_start_payload(_load_json(session_start_json))
    except (OSError, json.JSONDecodeError):
        return 99

    contract_context = extract_contract_context(payload)
    return domain_priority_rank(contract_context.get("domain"))


def _contract_resolution_suffix(session_start_json: Path | None) -> str:
    if session_start_json is None or not session_start_json.exists():
        return ""

    try:
        payload = normalize_session_start_payload(_load_json(session_start_json))
    except (OSError, json.JSONDecodeError):
        return ""

    contract_context = extract_contract_context(payload)

    parts = []
    if contract_context.get("source"):
        parts.append(f"contract_source={contract_context['source']}")
    if contract_context.get("name"):
        parts.append(f"contract_name={contract_context['name']}")
    if contract_context.get("domain"):
        parts.append(f"contract_domain={contract_context['domain']}")
    if contract_context.get("plugin_version"):
        parts.append(f"plugin_version={contract_context['plugin_version']}")
    if contract_context.get("risk_tier") and contract_context.get("risk_tier") != "unknown":
        parts.append(f"contract_risk_tier={contract_context['risk_tier']}")
    return " | " + " | ".join(parts) if parts else ""


def build_change_control_index(artifacts_dir: Path) -> str:
    summary_files = sorted(artifacts_dir.glob("*_change_control_summary.txt"))
    session_files = sorted(artifacts_dir.glob("*_session_start.txt"))
    json_files = sorted(artifacts_dir.glob("*_session_start.json"))
    json_lookup = {path.name.replace("_session_start.json", ""): path for path in json_files}
    summary_entries = [(path, _extract_summary_line(path)) for path in summary_files]
    priority_entries = sorted(
        summary_entries,
        key=lambda item: _priority_score(
            item[1],
            json_lookup.get(item[0].name.replace("_change_control_summary.txt", "")),
        ),
    )

    lines = ["[change_control_index]", f"artifacts_dir={artifacts_dir}"]
    lines.append(
        build_summary_line(
            f"change_control_summaries={len(summary_files)}",
            f"session_start_notes={len(session_files)}",
            f"session_start_envelopes={len(json_files)}",
        )
    )
    lines.append("[review_order]")
    lines.append("1. read [priority_change_control_summaries] first")
    lines.append("2. inspect *_session_start.txt if proposal/startup context needs more detail")
    lines.append("3. inspect *_session_start.json for machine-readable detail")

    if priority_entries:
        lines.append("[priority_change_control_summaries]")
        for path, summary_line in priority_entries:
            session_start_json = json_lookup.get(path.name.replace("_change_control_summary.txt", ""))
            suffix = _contract_resolution_suffix(session_start_json)
            if summary_line:
                lines.append(f"{path.name} | {summary_line}{suffix}")
            else:
                lines.append(path.name)

    if summary_entries:
        lines.append("[change_control_summaries]")
        for path, summary_line in summary_entries:
            session_start_json = json_lookup.get(path.name.replace("_change_control_summary.txt", ""))
            suffix = _contract_resolution_suffix(session_start_json)
            if summary_line:
                lines.append(f"{path.name} | {summary_line}{suffix}")
            else:
                lines.append(path.name)

    if session_files:
        lines.append("[session_start_notes]")
        for path in session_files:
            lines.append(path.name)

    if json_files:
        lines.append("[session_start_envelopes]")
        for path in json_files:
            lines.append(path.name)

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an index for change-control artifacts.")
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    rendered = build_change_control_index(Path(args.artifacts_dir))
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
