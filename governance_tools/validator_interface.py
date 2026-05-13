#!/usr/bin/env python3
"""
Shared validator interface for external domain validators.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field


VALIDATOR_RESULT_SCHEMA_VERSION = "1.0"
VALIDATOR_PAYLOAD_SCHEMA_VERSION = "1.0"


@dataclass
class ValidatorResult:
    ok: bool
    rule_ids: list[str]
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence_summary: str = ""
    metadata: dict[str, object] = field(default_factory=dict)
    schema_version: str = VALIDATOR_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


class DomainValidator(ABC):
    @property
    @abstractmethod
    def rule_ids(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def validate(self, payload: dict) -> ValidatorResult:
        raise NotImplementedError
