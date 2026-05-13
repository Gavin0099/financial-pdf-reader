#!/usr/bin/env python3
"""
Canonical Governance Contract renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json


REQUIRED_KEYS = ("LANG", "LEVEL", "SCOPE", "PLAN", "LOADED", "CONTEXT", "PRESSURE")


@dataclass(frozen=True)
class GovernanceContract:
    lang: str
    level: str
    scope: str
    plan: str
    loaded: str
    context: str
    pressure: str

    def as_fields(self) -> dict[str, str]:
        return {
            "LANG": self.lang,
            "LEVEL": self.level,
            "SCOPE": self.scope,
            "PLAN": self.plan,
            "LOADED": self.loaded,
            "CONTEXT": self.context,
            "PRESSURE": self.pressure,
        }


def render_contract_block(contract: GovernanceContract) -> str:
    fields = contract.as_fields()
    _validate_required_fields(fields)
    lines = ["[Governance Contract]"]
    lines.extend(f"{key} = {fields[key]}" for key in REQUIRED_KEYS)
    return "\n".join(lines)


def contract_hash(block: str) -> str:
    return hashlib.sha256(block.encode("utf-8")).hexdigest()


def render_contract_payload(contract: GovernanceContract) -> dict[str, object]:
    block = render_contract_block(contract)
    return {
        "contract_block": block,
        "contract_hash": contract_hash(block),
        "fields": contract.as_fields(),
    }


def payload_json(contract: GovernanceContract) -> str:
    return json.dumps(render_contract_payload(contract), ensure_ascii=False, indent=2)


def _validate_required_fields(fields: dict[str, str]) -> None:
    missing = [key for key in REQUIRED_KEYS if not str(fields.get(key, "")).strip()]
    if missing:
        raise ValueError(f"missing required contract field(s): {missing}")

