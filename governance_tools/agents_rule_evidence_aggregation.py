#!/usr/bin/env python3
"""Aggregation contract helpers for AGENTS rule-promotion evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from governance_tools.agents_rule_promotion_schema import (
    ALLOWED_REPO_SPECIFICITY,
    AgentsRuleCandidate,
    AgentsRulePromotionLedgerEntry,
)


def _parse_utc_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _specificity_rank(value: str) -> int:
    order = {"low": 0, "medium": 1, "high": 2}
    try:
        return order[value]
    except KeyError as exc:
        raise ValueError(f"unsupported repo_specificity: {value}") from exc


def _specificity_from_basis(basis: list[str]) -> str:
    concrete = {
        "real_path",
        "real_command",
        "irreversible_boundary",
        "concrete_side_effect",
    }
    if any(item in concrete for item in basis):
        return "high"
    if "generic_only" in basis:
        return "low"
    return "medium"


@dataclass
class AgentsRuleEvidenceEvent:
    candidate_id: str
    evidence_ref: str
    observed_at: str
    repo_specificity: str
    repo_specificity_basis: list[str] = field(default_factory=list)
    source: str | None = None

    def validate(self) -> None:
        if not self.candidate_id:
            raise ValueError("candidate_id must not be empty")
        if not self.evidence_ref:
            raise ValueError("evidence_ref must not be empty")
        _parse_utc_timestamp(self.observed_at)
        if self.repo_specificity not in ALLOWED_REPO_SPECIFICITY:
            raise ValueError(f"unsupported repo_specificity: {self.repo_specificity}")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return asdict(self)


@dataclass
class AgentsRuleAggregationResult:
    candidate_id: str
    aggregation_key: str
    counted_evidence_refs: list[str]
    duplicate_evidence_refs: list[str]
    evidence_count: int
    first_seen_at: str
    last_seen_at: str
    evidence_window_days: int
    repo_specificity: str
    resurfacing_allowed: bool
    resurfacing_reason: str
    suppressed_by_ledger: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def aggregate_candidate_evidence(
    candidate: AgentsRuleCandidate,
    events: list[AgentsRuleEvidenceEvent],
    ledger_entries: list[AgentsRulePromotionLedgerEntry] | None = None,
    now_utc: str | None = None,
) -> AgentsRuleAggregationResult:
    candidate.validate()
    ledger_entries = list(ledger_entries or [])
    candidate_events = [event for event in events if event.candidate_id == candidate.candidate_id]
    for event in candidate_events:
        event.validate()

    first_seen = _parse_utc_timestamp(candidate.first_seen_at) if candidate.first_seen_at else None
    last_seen = _parse_utc_timestamp(candidate.last_seen_at) if candidate.last_seen_at else None
    if first_seen and last_seen and last_seen < first_seen:
        raise ValueError("candidate last_seen_at must be >= first_seen_at")

    unique_events: dict[str, AgentsRuleEvidenceEvent] = {}
    duplicate_refs: list[str] = []
    for event in sorted(candidate_events, key=lambda item: (item.evidence_ref, item.observed_at)):
        observed_at = _parse_utc_timestamp(event.observed_at)
        if first_seen and observed_at < first_seen:
            continue
        if last_seen and observed_at > last_seen:
            continue
        if event.evidence_ref in unique_events:
            duplicate_refs.append(event.evidence_ref)
            continue
        unique_events[event.evidence_ref] = event

    counted_refs = sorted(unique_events)
    counted_events = [unique_events[ref] for ref in counted_refs]
    evidence_count = len(counted_events)

    derived_specificity = candidate.repo_specificity
    concrete_present = any(
        _specificity_from_basis(event.repo_specificity_basis) == "high" for event in counted_events
    )
    generic_only = counted_events and all(
        _specificity_from_basis(event.repo_specificity_basis) == "low" for event in counted_events
    )
    if generic_only and _specificity_rank(derived_specificity) > _specificity_rank("low"):
        derived_specificity = "low"
    elif concrete_present and _specificity_rank(derived_specificity) < _specificity_rank("high"):
        derived_specificity = "high"

    resurfacing_allowed = True
    resurfacing_reason = "no_rejection_suppression"
    suppressed_by_ledger = False
    rejected_entries = [
        entry
        for entry in ledger_entries
        if entry.candidate_id == candidate.candidate_id and entry.promotion_decision == "rejected"
    ]
    if rejected_entries:
        latest_rejection = max(rejected_entries, key=lambda entry: entry.approved_at)
        latest_rejection.validate()
        now_value = _parse_utc_timestamp(now_utc) if now_utc else datetime.now(timezone.utc)
        suppression_until = _parse_utc_timestamp(latest_rejection.suppression_until or latest_rejection.approved_at)
        if now_value < suppression_until:
            resurfacing_allowed = False
            resurfacing_reason = "suppressed_until_not_reached"
            suppressed_by_ledger = True
        elif latest_rejection.resurfacing_condition == "material_evidence_increase":
            previous_count = len(latest_rejection.evidence_refs)
            if evidence_count <= previous_count:
                resurfacing_allowed = False
                resurfacing_reason = "material_evidence_increase_not_met"
                suppressed_by_ledger = True
            else:
                resurfacing_reason = "material_evidence_increase_met"
        else:
            resurfacing_reason = "suppression_expired"

    return AgentsRuleAggregationResult(
        candidate_id=candidate.candidate_id,
        aggregation_key=candidate.candidate_id,
        counted_evidence_refs=counted_refs,
        duplicate_evidence_refs=sorted(set(duplicate_refs)),
        evidence_count=evidence_count,
        first_seen_at=candidate.first_seen_at or "",
        last_seen_at=candidate.last_seen_at or "",
        evidence_window_days=candidate.evidence_window_days,
        repo_specificity=derived_specificity,
        resurfacing_allowed=resurfacing_allowed,
        resurfacing_reason=resurfacing_reason,
        suppressed_by_ledger=suppressed_by_ledger,
    )


def build_rejection_suppression_window(
    approved_at: str,
    suppress_resurfacing_days: int,
) -> str:
    if suppress_resurfacing_days < 1:
        raise ValueError("suppress_resurfacing_days must be >= 1")
    approved_dt = _parse_utc_timestamp(approved_at)
    return (approved_dt + timedelta(days=suppress_resurfacing_days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
