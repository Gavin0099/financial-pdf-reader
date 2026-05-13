from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_backfill_yaml(path: Path) -> dict[str, dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    matches = list(re.finditer(r"(^|\n)-\s+run_id:\s*\"([^\"]+)\"(.*?)(?=\n-\s+run_id:|\Z)", text, flags=re.S))
    result: dict[str, dict[str, str]] = {}
    for match in matches:
        run_id = match.group(2).strip()
        block = match.group(3)
        latency_match = re.search(r"actionable_fix_latency_sec:\s*(.+)", block)
        latency_value_match = re.search(r"actionable_fix_latency_sec:\s*.*?\n\s*value:\s*(.+)", block, flags=re.S)
        tokens_match = re.search(r"tokens_per_reviewer_accepted_fix:\s*(.+)", block)
        tokens_value_match = re.search(r"tokens_per_reviewer_accepted_fix:\s*.*?\n\s*value:\s*(.+)", block, flags=re.S)
        if not (latency_match or latency_value_match) or not (tokens_match or tokens_value_match):
            continue
        if latency_value_match:
            latency = latency_value_match.group(1).strip().strip('"')
        else:
            latency = latency_match.group(1).strip().strip('"')
        if tokens_value_match:
            tokens = tokens_value_match.group(1).strip().strip('"')
        else:
            tokens = tokens_match.group(1).strip().strip('"')
        if latency.lower() == "null":
            latency = "insufficient_data"
        if tokens.lower() == "null":
            tokens = "insufficient_data"
        # Pending-field mode: only apply when both fields are explicit numeric scalars.
        if not latency.isdigit() or not tokens.isdigit():
            continue
        result[run_id] = {
            "actionable_fix_latency_sec": latency,
            "tokens_per_reviewer_accepted_fix": tokens,
            "tokens_per_accepted_fix": tokens,
        }
    return result


def apply_backfill(ledger_text: str, backfill: dict[str, dict[str, str]]) -> tuple[str, int]:
    lines = ledger_text.splitlines()
    replacements = 0

    # Quick table replacement by run_id row.
    for i, line in enumerate(lines):
        if not line.startswith("| 2026-"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 10:
            continue
        run_id = cells[1]
        if run_id not in backfill:
            continue
        new_tokens = backfill[run_id]["tokens_per_accepted_fix"]
        if cells[8] != new_tokens:
            cells[8] = new_tokens
            lines[i] = "| " + " | ".join(cells[1:-1]) + " |"
            replacements += 1

    updated = "\n".join(lines) + ("\n" if ledger_text.endswith("\n") else "")

    # YAML block replacement for full run blocks.
    for run_id, payload in backfill.items():
        block_pattern = re.compile(
            rf'(run_id:\s*"{re.escape(run_id)}".*?metrics:\s*.*?)(\n\s*actionable_fix_latency_sec:\s*".*?")(\n\s*tokens_per_reviewer_accepted_fix:\s*".*?")',
            flags=re.S,
        )
        new_fragment = (
            r'\1'
            + f'\n  actionable_fix_latency_sec: "{payload["actionable_fix_latency_sec"]}"'
            + f'\n  tokens_per_reviewer_accepted_fix: "{payload["tokens_per_reviewer_accepted_fix"]}"'
        )
        updated, count = block_pattern.subn(new_fragment, updated, count=1)
        replacements += count * 2

    return updated, replacements


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply AB cost backfill data into run ledger.")
    parser.add_argument("--ledger-path", default="docs/ab-v1.2-run-ledger.md")
    parser.add_argument("--backfill-path", default="docs/status/ab-cost-backfill-data-2026-05-12.yaml")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report-path", default="docs/status/ab-cost-backfill-apply-report-2026-05-12.json")
    args = parser.parse_args()

    ledger_path = Path(args.ledger_path)
    backfill_path = Path(args.backfill_path)

    backfill = parse_backfill_yaml(backfill_path)
    original = ledger_path.read_text(encoding="utf-8")
    updated, replacements = apply_backfill(original, backfill)

    if args.write and updated != original:
        ledger_path.write_text(updated, encoding="utf-8")

    report = {
        "ledger_path": ledger_path.as_posix(),
        "backfill_path": backfill_path.as_posix(),
        "run_count": len(backfill),
        "replacements": replacements,
        "write_applied": bool(args.write),
    }
    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
