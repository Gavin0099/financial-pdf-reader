#!/usr/bin/env python3
"""Schema helpers for AGENTS.md candidate-rule promotion."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field


ALLOWED_CANDIDATE_TYPES: tuple[str, ...] = (
    "must_test_path",
    "forbidden_behavior",
    "escalation_trigger",
    "risk_level_boundary",
)

SECTION_KEY_BY_CANDIDATE_TYPE: dict[str, str] = {
    "must_test_path": "must_test_paths",
    "forbidden_behavior": "forbidden_behaviors",
    "escalation_trigger": "escalation_triggers",
    "risk_level_boundary": "risk_levels",
}

ALLOWED_REPO_SPECIFICITY: tuple[str, ...] = ("low", "medium", "high")
ALLOWED_REPO_SPECIFICITY_BASIS: tuple[str, ...] = (
    "real_path",
    "real_command",
    "irreversible_boundary",
    "concrete_side_effect",
    "generic_only",
)
ALLOWED_CANDIDATE_STATUS: tuple[str, ...] = (
    "observed",
    "needs_human_review",
    "rejected",
)
ALLOWED_PROMOTION_DECISION: tuple[str, ...] = (
    "approved",
    "rejected",
    "needs_revision",
)
ALLOWED_PATCH_STATUS: tuple[str, ...] = (
    "not_proposed",
    "proposed",
    "landed",
)

_NORMALIZE_WHITESPACE_RE = re.compile(r"\s+")
_NORMALIZE_SLUG_RE = re.compile(r"[^a-z0-9._/\-]+")


def section_key_for_candidate_type(candidate_type: str) -> str:
    try:
        return SECTION_KEY_BY_CANDIDATE_TYPE[candidate_type]
    except KeyError as exc:
        raise ValueError(f"unsupported candidate_type: {candidate_type}") from exc


def normalize_candidate_text(candidate_type: str, candidate: str) -> str:
    section_key_for_candidate_type(candidate_type)
    text = _NORMALIZE_WHITESPACE_RE.sub(" ", candidate.strip().lower())
    if not text:
        raise ValueError("candidate text must not be empty")

    if candidate_type == "must_test_path":
        normalized = text.replace("\\", "/")
        normalized = re.sub(r"/+", "/", normalized)
        if "/" not in normalized and "." not in normalized:
            raise ValueError(
                "must_test_path canonicalization requires a concrete path-like candidate"
            )
        return normalized.strip("/")

    normalized = _NORMALIZE_SLUG_RE.sub("_", text).strip("_")
    if not normalized:
        raise ValueError("normalized candidate must not be empty")
    return normalized


def build_candidate_id(candidate_type: str, normalized_candidate: str) -> str:
    section_key_for_candidate_type(candidate_type)
    if not normalized_candidate:
        raise ValueError("normalized_candidate must not be empty")
    # Identity must be stable across wording variation. Hash only the canonical
    # normalized value, never human_candidate / review_note / prose variants.
    digest = hashlib.sha256(normalized_candidate.encode("utf-8")).hexdigest()[:12]
    return f"{candidate_type}:{normalized_candidate}:{digest}"


@dataclass
class AgentsRuleCandidate:
    candidate_id: str
    candidate_type: str
    section_key: str
    normalized_candidate: str
    human_candidate: str
    evidence_count: int
    evidence_window_days: int
    observed_from: list[str] = field(default_factory=list)
    repo_specificity: str = "medium"
    repo_specificity_basis: list[str] = field(default_factory=list)
    status: str = "needs_human_review"
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    evidence_refs: list[str] = field(default_factory=list)

    def validate(self) -> None:
        expected_section_key = section_key_for_candidate_type(self.candidate_type)
        if self.section_key != expected_section_key:
            raise ValueError(
                f"section_key mismatch: expected {expected_section_key}, got {self.section_key}"
            )
        if self.repo_specificity not in ALLOWED_REPO_SPECIFICITY:
            raise ValueError(f"unsupported repo_specificity: {self.repo_specificity}")
        invalid_basis = [
            item for item in self.repo_specificity_basis if item not in ALLOWED_REPO_SPECIFICITY_BASIS
        ]
        if invalid_basis:
            raise ValueError(f"unsupported repo_specificity_basis: {invalid_basis}")
        if self.status not in ALLOWED_CANDIDATE_STATUS:
            raise ValueError(f"unsupported candidate status: {self.status}")
        if self.evidence_count < 1:
            raise ValueError("evidence_count must be >= 1")
        if self.evidence_window_days < 1:
            raise ValueError("evidence_window_days must be >= 1")
        if not self.observed_from:
            raise ValueError("observed_from must not be empty")
        if not self.normalized_candidate:
            raise ValueError("normalized_candidate must not be empty")
        expected_id = build_candidate_id(self.candidate_type, self.normalized_candidate)
        if self.candidate_id != expected_id:
            raise ValueError(
                f"candidate_id mismatch: expected {expected_id}, got {self.candidate_id}"
            )
        if self.repo_specificity == "high" and not any(
            item in self.repo_specificity_basis
            for item in ("real_path", "real_command", "irreversible_boundary", "concrete_side_effect")
        ):
            raise ValueError(
                "repo_specificity=high requires a concrete basis such as real_path / real_command / irreversible_boundary / concrete_side_effect"
            )

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return asdict(self)


@dataclass
class AgentsRulePromotionLedgerEntry:
    candidate_id: str
    promotion_decision: str
    approved_by: str
    review_source: str
    review_ref: str
    approved_at: str
    target_section: str
    evidence_refs: list[str] = field(default_factory=list)
    review_note: str | None = None
    agents_patch_status: str = "not_proposed"
    suppress_resurfacing_days: int = 0
    suppression_until: str | None = None
    resurfacing_condition: str | None = None

    def validate(self) -> None:
        if self.promotion_decision not in ALLOWED_PROMOTION_DECISION:
            raise ValueError(f"unsupported promotion_decision: {self.promotion_decision}")
        if not self.candidate_id:
            raise ValueError("candidate_id must not be empty")
        if not self.approved_by:
            raise ValueError("approved_by must not be empty")
        if not self.review_source:
            raise ValueError("review_source must not be empty")
        if not self.review_ref:
            raise ValueError("review_ref must not be empty")
        if not self.approved_at:
            raise ValueError("approved_at must not be empty")
        if self.target_section not in SECTION_KEY_BY_CANDIDATE_TYPE.values():
            raise ValueError(f"unsupported target_section: {self.target_section}")
        if self.agents_patch_status not in ALLOWED_PATCH_STATUS:
            raise ValueError(f"unsupported agents_patch_status: {self.agents_patch_status}")
        if self.suppress_resurfacing_days < 0:
            raise ValueError("suppress_resurfacing_days must be >= 0")
        if self.promotion_decision == "approved" and not self.evidence_refs:
            raise ValueError("approved promotion requires evidence_refs")
        if self.promotion_decision in {"rejected", "needs_revision"} and not self.review_note:
            raise ValueError(
                f"{self.promotion_decision} promotion requires review_note"
            )
        if self.promotion_decision == "rejected":
            if self.suppress_resurfacing_days < 1:
                raise ValueError("rejected promotion requires suppress_resurfacing_days >= 1")
            if not self.suppression_until:
                raise ValueError("rejected promotion requires suppression_until")
            if not self.resurfacing_condition:
                raise ValueError("rejected promotion requires resurfacing_condition")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return asdict(self)


def make_candidate(
    *,
    candidate_type: str,
    human_candidate: str,
    evidence_count: int,
    evidence_window_days: int,
    observed_from: list[str],
    repo_specificity: str,
    repo_specificity_basis: list[str],
    first_seen_at: str | None,
    last_seen_at: str | None,
    evidence_refs: list[str] | None = None,
    status: str = "needs_human_review",
) -> AgentsRuleCandidate:
    normalized_candidate = normalize_candidate_text(candidate_type, human_candidate)
    return AgentsRuleCandidate(
        candidate_id=build_candidate_id(candidate_type, normalized_candidate),
        candidate_type=candidate_type,
        section_key=section_key_for_candidate_type(candidate_type),
        normalized_candidate=normalized_candidate,
        human_candidate=human_candidate,
        evidence_count=evidence_count,
        evidence_window_days=evidence_window_days,
        observed_from=list(observed_from),
        repo_specificity=repo_specificity,
        repo_specificity_basis=list(repo_specificity_basis),
        status=status,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        evidence_refs=list(evidence_refs or []),
    )
