from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class QuickLogRow:
    run_id: str
    arm: str
    task_id: str
    tokens_per_accepted_fix: str


@dataclass
class RunRecord:
    run_id: str
    arm: str
    task_id: str
    accepted_change_count: Optional[str]
    actionable_fix_latency_sec: Optional[str]
    tokens_per_reviewer_accepted_fix: Optional[str]


RUN_ID_PATTERN = re.compile(r'run_id:\s*"([^"]+)"')
ARM_PATTERN = re.compile(r'arm:\s*"([^"]+)"')
TASK_PATTERN = re.compile(r'task_id:\s*"([^"]+)"')
ACCEPTED_PATTERN = re.compile(r"accepted_change_count:\s*(.+)")
LATENCY_PATTERN = re.compile(r"actionable_fix_latency_sec:\s*(.+)")
TOKENS_PATTERN = re.compile(r"tokens_per_reviewer_accepted_fix:\s*(.+)")


def _clean_scalar(value: str) -> str:
    cleaned = value.strip()
    if cleaned.endswith(","):
        cleaned = cleaned[:-1].strip()
    if cleaned.startswith('"') and cleaned.endswith('"'):
        cleaned = cleaned[1:-1]
    return cleaned


def parse_quick_log_rows(content: str) -> List[QuickLogRow]:
    rows: List[QuickLogRow] = []
    in_table = False
    for line in content.splitlines():
        if line.startswith("| run_id | arm | task_id |"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("---"):
            break
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().split("|")]
        if len(cells) < 10:
            continue
        run_id = cells[1]
        if run_id == "---":
            continue
        arm = cells[2]
        task_id = cells[3]
        tokens_per_accepted_fix = cells[8]
        rows.append(
            QuickLogRow(
                run_id=run_id,
                arm=arm,
                task_id=task_id,
                tokens_per_accepted_fix=tokens_per_accepted_fix,
            )
        )
    return rows


def parse_run_records(content: str) -> List[RunRecord]:
    records: List[RunRecord] = []
    for block in content.split("```yaml"):
        if "run_id:" not in block:
            continue
        run_id_match = RUN_ID_PATTERN.search(block)
        arm_match = ARM_PATTERN.search(block)
        task_match = TASK_PATTERN.search(block)
        if not run_id_match or not arm_match or not task_match:
            continue

        accepted = _extract_value(block, ACCEPTED_PATTERN)
        latency = _extract_value(block, LATENCY_PATTERN)
        tokens = _extract_value(block, TOKENS_PATTERN)

        records.append(
            RunRecord(
                run_id=run_id_match.group(1),
                arm=arm_match.group(1),
                task_id=task_match.group(1),
                accepted_change_count=accepted,
                actionable_fix_latency_sec=latency,
                tokens_per_reviewer_accepted_fix=tokens,
            )
        )
    records.extend(_parse_compact_observed_runs(content))
    return records


def _extract_value(block: str, pattern: re.Pattern[str]) -> Optional[str]:
    match = pattern.search(block)
    if not match:
        return None
    return _clean_scalar(match.group(1))


def _parse_compact_observed_runs(content: str) -> List[RunRecord]:
    records: List[RunRecord] = []
    compact_match = re.search(
        r"### Additional Observed Runs \(Compact\)\s*```yaml(.*?)```",
        content,
        flags=re.S,
    )
    if not compact_match:
        return records
    compact_block = compact_match.group(1)
    item_blocks = re.split(r"\n-\s+run_id:\s*", compact_block)
    for item in item_blocks[1:]:
        first_line, *_ = item.splitlines()
        run_id = _clean_scalar(first_line)
        arm_match = re.search(r"\n\s*arm:\s*(.+)", item)
        task_match = re.search(r"\n\s*task_id:\s*(.+)", item)
        accepted_match = re.search(r"\n\s*accepted_change_count:\s*(.+)", item)
        if not arm_match or not task_match:
            continue
        records.append(
            RunRecord(
                run_id=run_id,
                arm=_clean_scalar(arm_match.group(1)),
                task_id=_clean_scalar(task_match.group(1)),
                accepted_change_count=_clean_scalar(accepted_match.group(1)) if accepted_match else None,
                actionable_fix_latency_sec=None,
                tokens_per_reviewer_accepted_fix=None,
            )
        )
    return records


def _is_missing(value: Optional[str]) -> bool:
    if value is None:
        return True
    normalized = value.strip().lower()
    return normalized in {"tbd", "n/a", "na", "unknown", ""}


def build_gap_report(rows: List[QuickLogRow], records: List[RunRecord]) -> Dict[str, object]:
    by_task: Dict[str, Dict[str, object]] = {}
    for row in rows:
        task = by_task.setdefault(
            row.task_id,
            {
                "task_id": row.task_id,
                "quick_log_rows": [],
                "runs": {},
            },
        )
        task["quick_log_rows"].append(
            {
                "run_id": row.run_id,
                "arm": row.arm,
                "tokens_per_accepted_fix": row.tokens_per_accepted_fix,
                "tokens_missing": _is_missing(row.tokens_per_accepted_fix),
            }
        )

    for record in records:
        task = by_task.setdefault(
            record.task_id,
            {
                "task_id": record.task_id,
                "quick_log_rows": [],
                "runs": {},
            },
        )
        task["runs"][record.run_id] = {
            "run_id": record.run_id,
            "arm": record.arm,
            "accepted_change_count": record.accepted_change_count,
            "actionable_fix_latency_sec": record.actionable_fix_latency_sec,
            "tokens_per_reviewer_accepted_fix": record.tokens_per_reviewer_accepted_fix,
            "missing": {
                "accepted_change_count": _is_missing(record.accepted_change_count),
                "actionable_fix_latency_sec": _is_missing(record.actionable_fix_latency_sec),
                "tokens_per_reviewer_accepted_fix": _is_missing(record.tokens_per_reviewer_accepted_fix),
            },
        }

    task_summaries: List[Dict[str, object]] = []
    total_missing_items = 0
    for task_id in sorted(by_task.keys()):
        task_data = by_task[task_id]
        runs = task_data["runs"]
        run_ids = sorted(runs.keys())
        missing_items = 0
        for run_id in run_ids:
            missing_map = runs[run_id]["missing"]
            missing_items += sum(1 for value in missing_map.values() if value)
        for row in task_data["quick_log_rows"]:
            if row["tokens_missing"]:
                missing_items += 1
        total_missing_items += missing_items
        task_summaries.append(
            {
                "task_id": task_id,
                "run_count": len(run_ids),
                "quick_log_row_count": len(task_data["quick_log_rows"]),
                "missing_items": missing_items,
                "runs": [runs[run_id] for run_id in run_ids],
                "quick_log_rows": task_data["quick_log_rows"],
            }
        )

    return {
        "task_count": len(task_summaries),
        "total_missing_items": total_missing_items,
        "tasks": task_summaries,
    }


def format_markdown(report: Dict[str, object], source_path: Path) -> str:
    lines: List[str] = []
    lines.append("# AB Cost Parity Gap Report")
    lines.append("")
    lines.append(f"- source: `{source_path.as_posix()}`")
    lines.append(f"- task_count: `{report['task_count']}`")
    lines.append(f"- total_missing_items: `{report['total_missing_items']}`")
    lines.append("")
    lines.append("## Task Gap Summary")
    lines.append("")
    lines.append("| task_id | run_count | quick_log_rows | missing_items |")
    lines.append("|---|---:|---:|---:|")
    for task in report["tasks"]:
        lines.append(
            f"| {task['task_id']} | {task['run_count']} | {task['quick_log_row_count']} | {task['missing_items']} |"
        )

    lines.append("")
    lines.append("## Detailed Missing Fields")
    lines.append("")
    for task in report["tasks"]:
        lines.append(f"### {task['task_id']}")
        lines.append("")
        for run in task["runs"]:
            missing_keys = [k for k, v in run["missing"].items() if v]
            if not missing_keys:
                continue
            lines.append(
                f"- run `{run['run_id']}` ({run['arm']}): missing `{', '.join(missing_keys)}`"
            )
        for row in task["quick_log_rows"]:
            if row["tokens_missing"]:
                lines.append(
                    f"- quick-log row `{row['run_id']}` ({row['arm']}): missing `tokens_per_accepted_fix`"
                )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run(ledger_path: Path, markdown_out: Path, json_out: Path) -> int:
    content = ledger_path.read_text(encoding="utf-8")
    rows = parse_quick_log_rows(content)
    records = parse_run_records(content)
    report = build_gap_report(rows, records)

    markdown_out.parent.mkdir(parents=True, exist_ok=True)
    markdown_out.write_text(format_markdown(report, ledger_path), encoding="utf-8")
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    return 0 if report["total_missing_items"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit AB cost parity gaps from run ledger.")
    parser.add_argument(
        "--ledger-path",
        default="docs/ab-v1.2-run-ledger.md",
        help="Path to AB run ledger markdown.",
    )
    parser.add_argument(
        "--markdown-out",
        default="docs/status/ab-cost-parity-gap-2026-05-12.md",
        help="Output markdown report path.",
    )
    parser.add_argument(
        "--json-out",
        default="docs/status/ab-cost-parity-gap-2026-05-12.json",
        help="Output JSON report path.",
    )
    args = parser.parse_args()
    return run(
        ledger_path=Path(args.ledger_path),
        markdown_out=Path(args.markdown_out),
        json_out=Path(args.json_out),
    )


if __name__ == "__main__":
    raise SystemExit(main())
