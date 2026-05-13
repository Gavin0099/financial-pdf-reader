#!/usr/bin/env python3
"""
Discovery and execution helpers for external domain validators.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.domain_contract_loader import load_domain_contract
from governance_tools.validator_interface import (
    DomainValidator,
    VALIDATOR_PAYLOAD_SCHEMA_VERSION,
    ValidatorResult,
)


C_FUNCTION_DEF_RE = re.compile(
    r"\b(?:void|int|char|short|long|unsigned|signed|static|inline|__interrupt|interrupt)\b"
    r"[\w\s\*]*?\b([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*\)\s*\{",
    re.MULTILINE,
)


def _normalize_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    rendered = str(value).strip()
    return [rendered] if rendered else []


def _extract_isr_code(checks: dict) -> str:
    for key in ("isr_code", "interrupt_handler_code", "irq_code"):
        value = checks.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for text in _candidate_c_texts(checks):
        for block in _extract_c_function_blocks(text):
            if _looks_like_interrupt_function(block["name"], block["body"]):
                return block["body"]
    return ""


def _extract_interrupt_functions(changed_functions: list[str]) -> list[str]:
    detected = []
    for item in changed_functions:
        if _looks_like_interrupt_function(item, ""):
            detected.append(item)
    return detected


def _looks_like_interrupt_function(name: str, body: str) -> bool:
    interrupt_markers = ("isr", "irq", "interrupt")
    normalized_name = name.lower()
    normalized_body = body.lower()
    return any(marker in normalized_name for marker in interrupt_markers) or "__interrupt" in normalized_body or " interrupt " in normalized_body


def _extract_c_function_blocks(text: str) -> list[dict]:
    blocks = []
    for match in C_FUNCTION_DEF_RE.finditer(text):
        name = match.group(1)
        start = match.start()
        brace_depth = 0
        end = None
        for index in range(match.end() - 1, len(text)):
            char = text[index]
            if char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth -= 1
                if brace_depth == 0:
                    end = index + 1
                    break
        snippet = text[start:end].strip() if end else text[start:match.end()].strip()
        blocks.append({"name": name, "body": snippet})
    return blocks


def _normalize_diff_text(text: str) -> str:
    normalized_lines = []
    for line in text.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-", " ")):
            normalized_lines.append(line[1:])
        else:
            normalized_lines.append(line)
    return "\n".join(normalized_lines)


def _load_diff_file_texts(checks: dict) -> list[str]:
    texts = []
    for item in _normalize_string_list(checks.get("diff_file") or checks.get("diff_files")):
        path = Path(item)
        if not path.exists() or not path.is_file():
            continue
        try:
            texts.append(_normalize_diff_text(path.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    return texts


def _load_changed_file_texts(checks: dict) -> list[str]:
    texts = []
    for item in _normalize_string_list(checks.get("changed_files") or checks.get("files")):
        path = Path(item)
        if not path.exists() or not path.is_file():
            continue
        try:
            texts.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return texts


def _candidate_c_texts(checks: dict) -> list[str]:
    candidates = []
    for key in ("diff_text", "before_code", "after_code", "source_text"):
        value = checks.get(key)
        if isinstance(value, str) and value.strip():
            if key == "diff_text":
                candidates.append(_normalize_diff_text(value))
            else:
                candidates.append(value)
    candidates.extend(_load_diff_file_texts(checks))
    candidates.extend(_load_changed_file_texts(checks))
    return candidates


def _extract_changed_functions(checks: dict) -> list[str]:
    explicit = _normalize_string_list(checks.get("changed_functions"))
    if explicit:
        return explicit

    candidates: list[str] = []
    for text in _candidate_c_texts(checks):
        for block in _extract_c_function_blocks(text):
            if block["name"] not in candidates:
                candidates.append(block["name"])
    return candidates


def _load_module_from_path(module_path: Path):
    module_name = f"domain_validator_{module_path.stem}_{abs(hash(str(module_path)))}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def discover_domain_validators(contract_file: str | Path | None) -> list[dict]:
    contract = load_domain_contract(contract_file)
    if not contract:
        return []

    discovered = []
    for item in contract.get("validators", []):
        validator_path = Path(item["path"])
        entry = {
            "name": item["name"],
            "path": item["path"],
            "exists": item["exists"],
            "ok": False,
            "rule_ids": [],
            "errors": [],
            "validator": None,
        }
        if not validator_path.exists():
            entry["errors"].append("validator file not found")
            discovered.append(entry)
            continue

        try:
            module = _load_module_from_path(validator_path)
            validator_instance = None
            for value in module.__dict__.values():
                if isinstance(value, type) and issubclass(value, DomainValidator) and value is not DomainValidator:
                    validator_instance = value()
                    break
            if validator_instance is None:
                entry["errors"].append("no DomainValidator implementation found")
            else:
                entry["ok"] = True
                entry["validator"] = validator_instance
                entry["rule_ids"] = list(validator_instance.rule_ids)
        except Exception as exc:  # pragma: no cover
            entry["errors"].append(str(exc))
        discovered.append(entry)
    return discovered


def preflight_domain_validators(contract_file: str | Path | None) -> dict | None:
    contract = load_domain_contract(contract_file)
    if not contract:
        return None

    validators = discover_domain_validators(contract_file)
    return {
        "ok": all(item["ok"] for item in validators),
        "count": len(validators),
        "validators": [
            {
                "name": item["name"],
                "path": item["path"],
                "ok": item["ok"],
                "rule_ids": item["rule_ids"],
                "errors": item["errors"],
            }
            for item in validators
        ],
    }


def build_domain_validation_payload(
    *,
    response_text: str,
    checks: dict | None,
    fields: dict,
    resolved_rules: list[str],
    domain_contract: dict | None,
    contract_file: str | Path | None = None,
) -> dict:
    effective_checks = checks or {}
    changed_functions = _extract_changed_functions(effective_checks)
    changed_files = _normalize_string_list(effective_checks.get("changed_files") or effective_checks.get("files"))
    contract_raw = (domain_contract or {}).get("raw") or {}
    contract_path = str(Path(contract_file).resolve()) if contract_file else None
    evidence_envelope = {
        "schema_version": VALIDATOR_PAYLOAD_SCHEMA_VERSION,
        "checks": effective_checks,
        "source_keys": sorted(str(key) for key in effective_checks.keys()),
        "response_present": bool(response_text.strip()),
        "changed_files": changed_files,
        "provenance": {
            "contract_path": contract_path,
            "contract_name": (domain_contract or {}).get("name"),
            "contract_domain": contract_raw.get("domain") or (domain_contract or {}).get("name"),
            "plugin_version": contract_raw.get("plugin_version"),
            "framework_interface_version": contract_raw.get("framework_interface_version"),
        },
    }
    return {
        "schema_version": VALIDATOR_PAYLOAD_SCHEMA_VERSION,
        "payload_type": "domain-validator-payload",
        "rule_ids": resolved_rules,
        "checks": effective_checks,
        "response_text": response_text,
        "contract_fields": fields,
        "isr_code": _extract_isr_code(effective_checks),
        "changed_functions": changed_functions,
        "interrupt_functions": _extract_interrupt_functions(changed_functions),
        "changed_files": changed_files,
        "domain_documents": (domain_contract or {}).get("documents", []),
        "ai_behavior_override": (domain_contract or {}).get("ai_behavior_override", []),
        "contract_snapshot": {
            "name": (domain_contract or {}).get("name"),
            "domain": contract_raw.get("domain") or (domain_contract or {}).get("name"),
            "plugin_version": contract_raw.get("plugin_version"),
            "framework_interface_version": contract_raw.get("framework_interface_version"),
            "rules": resolved_rules,
            "risk": fields.get("RISK"),
            "oversight": fields.get("OVERSIGHT"),
            "memory_mode": fields.get("MEMORY_MODE"),
        },
        "evidence_envelope": evidence_envelope,
        "compatibility": {
            "additive_fields_allowed": True,
            "legacy_top_level_fields_preserved": True,
        },
    }


def run_domain_validators(
    *,
    contract_file: str | Path | None,
    payload: dict,
    active_rule_ids: list[str],
) -> list[dict]:
    results = []
    for item in discover_domain_validators(contract_file):
        validator = item.get("validator")
        if not item["ok"] or validator is None:
            results.append(
                {
                    "name": item["name"],
                    "ok": False,
                    "rule_ids": item["rule_ids"],
                    "violations": [],
                    "warnings": [],
                    "evidence_summary": "",
                    "metadata": {},
                    "errors": item["errors"],
                }
            )
            continue

        if not (set(item["rule_ids"]) & set(active_rule_ids)):
            continue

        result = validator.validate(payload)
        if not isinstance(result, ValidatorResult):
            raise TypeError(f"{item['name']} returned unsupported result type")
        rendered = result.to_dict()
        rendered["name"] = item["name"]
        results.append(rendered)
    return results
