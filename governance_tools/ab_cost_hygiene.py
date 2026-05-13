from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List


MISSING_TOKENS = {"tbd", "unknown", "null", "n/a", "na", ""}


@dataclass
class HygieneIssue:
    line_number: int
    field: str
    value: str
    reason: str


def _normalize_value(raw: str) -> str:
    text = raw.strip().strip('"')
    if text.lower() in MISSING_TOKENS or text.lower().startswith("tbd"):
        return "insufficient_data"
    return text


def normalize_ledger_cost_fields(content: str) -> tuple[str, int]:
    updated = content
    replacements = 0

    # YAML-like fields in run blocks.
    field_patterns = (
        r'(^\s*actionable_fix_latency_sec:\s*)("?[^"\n]+"?)\s*$',
        r'(^\s*tokens_per_reviewer_accepted_fix:\s*)("?[^"\n]+"?)\s*$',
    )
    for pattern in field_patterns:
        regex = re.compile(pattern, flags=re.M)

        def repl(match: re.Match[str]) -> str:
            nonlocal replacements
            prefix = match.group(1)
            value = match.group(2)
            normalized = _normalize_value(value)
            if normalized != value.strip().strip('"'):
                replacements += 1
            return f'{prefix}"{normalized}"'

        updated = regex.sub(repl, updated)

    # Quick log table col: tokens_per_accepted_fix (8th cell).
    lines = updated.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("| 2026-"):
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 10:
            continue
        old = cells[8]
        new = _normalize_value(old)
        if new != old:
            cells[8] = new
            replacements += 1
            lines[i] = "| " + " | ".join(cells[1:-1]) + " |"

    return "\n".join(lines) + ("\n" if updated.endswith("\n") else ""), replacements


def validate_ledger_cost_hygiene(content: str) -> List[HygieneIssue]:
    issues: List[HygieneIssue] = []
    for index, line in enumerate(content.splitlines(), start=1):
        lowered = line.lower()
        if "actionable_fix_latency_sec:" in line or "tokens_per_reviewer_accepted_fix:" in line:
            value = line.split(":", 1)[1].strip().strip('"')
            if value.lower().startswith("tbd"):
                field = line.split(":", 1)[0].strip()
                issues.append(
                    HygieneIssue(
                        line_number=index,
                        field=field,
                        value=value,
                        reason="placeholder_tbd_disallowed",
                    )
                )
        if line.startswith("| 2026-"):
            cells = [cell.strip() for cell in line.split("|")]
            if len(cells) >= 10:
                token_value = cells[8]
                if token_value.lower().startswith("tbd"):
                    issues.append(
                        HygieneIssue(
                            line_number=index,
                            field="tokens_per_accepted_fix",
                            value=token_value,
                            reason="placeholder_tbd_disallowed",
                        )
                    )
        if ("actionable_fix_latency_sec:" in line or "tokens_per_reviewer_accepted_fix:" in line) and re.search(
            r":\s*0\s*$", line
        ):
            field = line.split(":", 1)[0].strip()
            issues.append(
                HygieneIssue(
                    line_number=index,
                    field=field,
                    value="0",
                    reason="zero_value_requires_explicit_measurement_context",
                )
            )
        if line.startswith("| 2026-"):
            cells = [cell.strip() for cell in line.split("|")]
            if len(cells) >= 10 and cells[8] == "0":
                issues.append(
                    HygieneIssue(
                        line_number=index,
                        field="tokens_per_accepted_fix",
                        value="0",
                        reason="zero_value_requires_explicit_measurement_context",
                    )
                )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize and validate AB ledger cost-field hygiene.")
    parser.add_argument("--ledger-path", default="docs/ab-v1.2-run-ledger.md")
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--json-out",
        default="docs/status/ab-cost-hygiene-report-2026-05-12.json",
    )
    args = parser.parse_args()

    ledger_path = Path(args.ledger_path)
    content = ledger_path.read_text(encoding="utf-8")

    if args.write:
        normalized, replacements = normalize_ledger_cost_fields(content)
        if normalized != content:
            ledger_path.write_text(normalized, encoding="utf-8")
            content = normalized
        else:
            replacements = 0
    else:
        replacements = 0

    issues = validate_ledger_cost_hygiene(content)
    report = {
        "ledger_path": ledger_path.as_posix(),
        "write_applied": bool(args.write),
        "replacements": replacements,
        "issue_count": len(issues),
        "issues": [issue.__dict__ for issue in issues],
    }
    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0 if len(issues) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
