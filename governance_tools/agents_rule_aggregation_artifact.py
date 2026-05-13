#!/usr/bin/env python3
"""Persisted artifact contract for AGENTS rule aggregation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from governance_tools.agents_rule_evidence_aggregation import AgentsRuleAggregationResult
from governance_tools.agents_rule_promotion_schema import AgentsRulePromotionLedgerEntry


AGENTS_RULE_AGGREGATION_ARTIFACT_SCHEMA_VERSION = "0.1"
ALLOWED_ARTIFACT_SOURCES: tuple[str, ...] = ("manual_or_test_fixture",)
DEFAULT_ARTIFACT_PATH = "artifacts/governance/agents_rule_candidates.json"


@dataclass
class AgentsRuleAggregationArtifact:
    schema_version: str
    generated_at: str
    source: str
    candidates: list[dict[str, object]] = field(default_factory=list)
    suppressed_candidates: list[dict[str, object]] = field(default_factory=list)
    ledger_refs: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.schema_version != AGENTS_RULE_AGGREGATION_ARTIFACT_SCHEMA_VERSION:
            raise ValueError(
                "unsupported schema_version: "
                f"{self.schema_version} (expected {AGENTS_RULE_AGGREGATION_ARTIFACT_SCHEMA_VERSION})"
            )
        if not self.generated_at:
            raise ValueError("generated_at must not be empty")
        if self.source not in ALLOWED_ARTIFACT_SOURCES:
            raise ValueError(f"unsupported source: {self.source}")
        if not isinstance(self.candidates, list):
            raise ValueError("candidates must be a list")
        if not isinstance(self.suppressed_candidates, list):
            raise ValueError("suppressed_candidates must be a list")
        if not isinstance(self.ledger_refs, list):
            raise ValueError("ledger_refs must be a list")
        for ref in self.ledger_refs:
            if not isinstance(ref, str) or not ref.strip():
                raise ValueError("ledger_refs must be list[str] with non-empty values")
        for item in self.candidates:
            _validate_aggregation_entry(item, suppressed=False)
        for item in self.suppressed_candidates:
            _validate_aggregation_entry(item, suppressed=True)

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return asdict(self)


def _validate_aggregation_entry(item: dict[str, object], *, suppressed: bool) -> None:
    if not isinstance(item, dict):
        raise ValueError("artifact candidate entry must be a dict")
    candidate_id = item.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("artifact candidate entry requires non-empty candidate_id")
    counted_refs = item.get("counted_evidence_refs")
    if not isinstance(counted_refs, list):
        raise ValueError("artifact candidate entry requires counted_evidence_refs list")
    duplicate_refs = item.get("duplicate_evidence_refs")
    if not isinstance(duplicate_refs, list):
        raise ValueError("artifact candidate entry requires duplicate_evidence_refs list")
    evidence_count = item.get("evidence_count")
    if not isinstance(evidence_count, int) or evidence_count < 0:
        raise ValueError("artifact candidate entry requires evidence_count >= 0")
    resurfacing_allowed = item.get("resurfacing_allowed")
    if not isinstance(resurfacing_allowed, bool):
        raise ValueError("artifact candidate entry requires resurfacing_allowed bool")
    if suppressed and resurfacing_allowed:
        raise ValueError("suppressed candidate entry must have resurfacing_allowed=false")
    if not suppressed and item.get("suppressed_by_ledger") is True:
        raise ValueError("active candidate entry must not be suppressed_by_ledger=true")


def make_aggregation_artifact(
    *,
    generated_at: str,
    source: str = "manual_or_test_fixture",
    candidates: list[AgentsRuleAggregationResult] | None = None,
    suppressed_candidates: list[AgentsRuleAggregationResult] | None = None,
    ledger_entries: list[AgentsRulePromotionLedgerEntry] | None = None,
) -> AgentsRuleAggregationArtifact:
    return AgentsRuleAggregationArtifact(
        schema_version=AGENTS_RULE_AGGREGATION_ARTIFACT_SCHEMA_VERSION,
        generated_at=generated_at,
        source=source,
        candidates=[item.to_dict() for item in (candidates or [])],
        suppressed_candidates=[item.to_dict() for item in (suppressed_candidates or [])],
        ledger_refs=[entry.review_ref for entry in (ledger_entries or [])],
    )
