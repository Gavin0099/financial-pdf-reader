#!/usr/bin/env python3
"""
Validate machine-readable [Governance Contract] blocks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.rule_pack_loader import available_rule_packs, parse_rule_list


VALID_LANG = {"C", "C++", "C#", "ObjC", "Swift", "JS", "Python"}
VALID_LEVEL = {"L0", "L1", "L2"}
VALID_SCOPE = {"feature", "refactor", "bugfix", "I/O", "tooling", "review", "governance", "kernel-driver"}
VALID_PRESSURE_LEVELS = {"SAFE", "WARNING", "CRITICAL", "EMERGENCY"}
VALID_RISK_LEVELS = {"low", "medium", "high"}
VALID_OVERSIGHT_LEVELS = {"auto", "review-required", "human-approval"}
VALID_MEMORY_MODES = {"stateless", "candidate", "durable"}

REQUIRED_LOADED = {"SYSTEM_PROMPT", "HUMAN-OVERSIGHT"}
DISPLAY_FIELDS = [
    "LANG",
    "LEVEL",
    "SCOPE",
    "PLAN",
    "LOADED",
    "CONTEXT",
    "PRESSURE",
    "RULES",
    "RISK",
    "OVERSIGHT",
    "MEMORY_MODE",
    "AGENT_ID",
    "SESSION",
]


@dataclass
class ValidationResult:
    compliant: bool
    contract_found: bool
    fields: dict
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def extract_contract_block(text: str) -> Optional[str]:
    code_match = re.search(r"```[^\n]*\n\[Governance Contract\]\n(.*?)```", text, re.DOTALL)
    if code_match:
        return code_match.group(0)

    plain_match = re.search(r"\[Governance Contract\]\n((?:[A-Z_]+\s*=\s*.*\n?)*)", text)
    if plain_match and plain_match.group(1).strip():
        return plain_match.group(0)
    return None


def parse_contract_fields(block: str) -> dict:
    fields: dict[str, str] = {}
    for line in block.splitlines():
        stripped = line.strip()
        if "=" not in line or stripped.startswith("[") or stripped.startswith("`"):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            fields[key] = value.strip()
    return fields


def _validate_choice(fields: dict, key: str, valid_values: set[str], errors: list[str]) -> None:
    value = fields.get(key, "").strip()
    if not value:
        errors.append(f"{key} field is required")
        return
    if value not in valid_values:
        errors.append(f"{key} invalid: '{value}'. Allowed: {sorted(valid_values)}")


def _validate_rules(fields: dict, errors: list[str], available: set[str] | None = None) -> None:
    rules_raw = fields.get("RULES", "").strip()
    if not rules_raw:
        errors.append("RULES field is required")
        return

    rule_names = parse_rule_list(rules_raw)
    if not rule_names:
        errors.append("RULES must contain at least one rule pack")
        return

    available = available or available_rule_packs()
    invalid = [name for name in rule_names if name not in available]
    if invalid:
        errors.append(
            f"RULES contains unknown rule pack(s): {invalid}. Available: {sorted(available)}"
        )


def validate_contract(text: str, available_rules: set[str] | None = None) -> ValidationResult:
    block = extract_contract_block(text)
    if block is None:
        return ValidationResult(
            compliant=False,
            contract_found=False,
            fields={},
            errors=["[Governance Contract] block not found"],
        )

    fields = parse_contract_fields(block)
    errors: list[str] = []
    warnings: list[str] = []

    lang = fields.get("LANG", "").strip()
    if not lang:
        errors.append("LANG field is required")
    elif lang not in VALID_LANG:
        errors.append(f"LANG invalid: '{lang}'. Allowed: {sorted(VALID_LANG)}")

    level = fields.get("LEVEL", "").strip()
    if not level:
        errors.append("LEVEL field is required")
    elif level not in VALID_LEVEL:
        errors.append(f"LEVEL invalid: '{level}'. Allowed: {sorted(VALID_LEVEL)}")

    scope = fields.get("SCOPE", "").strip()
    if not scope:
        errors.append("SCOPE field is required")
    elif scope not in VALID_SCOPE:
        errors.append(f"SCOPE invalid: '{scope}'. Allowed: {sorted(VALID_SCOPE)}")

    if not fields.get("PLAN", "").strip():
        warnings.append("PLAN missing; recommended to bind responses to PLAN.md")

    loaded_raw = fields.get("LOADED", "").strip()
    if not loaded_raw:
        errors.append("LOADED field is required")
    else:
        loaded_docs = {doc.strip() for doc in loaded_raw.split(",") if doc.strip()}
        missing_required = REQUIRED_LOADED - loaded_docs
        if missing_required:
            errors.append(f"LOADED missing required documents: {sorted(missing_required)}")

    context = fields.get("CONTEXT", "").strip()
    if not context:
        errors.append("CONTEXT field is required")
    else:
        if "->" not in context and "--" not in context:
            errors.append("CONTEXT must include active scope using '->' or '--'")
        if "NOT:" not in context:
            errors.append("CONTEXT must include a 'NOT:' exclusion clause")

    pressure = fields.get("PRESSURE", "").strip()
    if not pressure:
        errors.append("PRESSURE field is required")
    else:
        level_name = pressure.split("(")[0].strip()
        if level_name not in VALID_PRESSURE_LEVELS:
            errors.append(
                f"PRESSURE invalid: '{level_name}'. Allowed: {sorted(VALID_PRESSURE_LEVELS)}"
            )
        if "(" not in pressure or "/" not in pressure:
            warnings.append("PRESSURE should include line-count context, e.g. SAFE (45/200)")

    _validate_rules(fields, errors, available=available_rules)
    _validate_choice(fields, "RISK", VALID_RISK_LEVELS, errors)
    _validate_choice(fields, "OVERSIGHT", VALID_OVERSIGHT_LEVELS, errors)
    _validate_choice(fields, "MEMORY_MODE", VALID_MEMORY_MODES, errors)

    agent_id = fields.get("AGENT_ID", "").strip()
    session = fields.get("SESSION", "").strip()
    if agent_id:
        if not session:
            errors.append("AGENT_ID requires SESSION in YYYY-MM-DD-NN format")
        elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d+", session):
            errors.append(f"SESSION invalid: '{session}'. Expected YYYY-MM-DD-NN format")
    elif session:
        warnings.append("SESSION provided without AGENT_ID")

    return ValidationResult(
        compliant=len(errors) == 0,
        contract_found=True,
        fields=fields,
        errors=errors,
        warnings=warnings,
    )


def format_human(result: ValidationResult) -> str:
    if not result.contract_found:
        return "ERROR: [Governance Contract] block not found"

    lines = ["[Governance Contract] validation", ""]
    for key in DISPLAY_FIELDS:
        lines.append(f"{key:<12} = {result.fields.get(key, '<missing>')}")

    lines.append("")
    lines.append(f"errors: {len(result.errors)}")
    for err in result.errors:
        lines.append(f"- {err}")

    if result.warnings:
        lines.append("")
        lines.append(f"warnings: {len(result.warnings)}")
        for warning in result.warnings:
            lines.append(f"- {warning}")

    return "\n".join(lines)


def format_json(result: ValidationResult) -> str:
    return json.dumps(
        {
            "compliant": result.compliant,
            "contract_found": result.contract_found,
            "fields": result.fields,
            "errors": result.errors,
            "warnings": result.warnings,
        },
        ensure_ascii=False,
        indent=2,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a machine-readable [Governance Contract] block."
    )
    parser.add_argument("--file", "-f", help="Text file containing the AI response.")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    if args.file:
        try:
            text = Path(args.file).read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"ERROR: file not found: {args.file}", file=sys.stderr)
            sys.exit(2)
    else:
        text = sys.stdin.read()

    result = validate_contract(text)
    print(format_json(result) if args.format == "json" else format_human(result))

    if not result.contract_found:
        sys.exit(2)
    if not result.compliant:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
