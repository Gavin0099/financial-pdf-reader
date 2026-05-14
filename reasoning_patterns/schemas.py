"""
Reasoning Patterns — Schemas
Dataclasses for pattern definitions and trigger results.
No Claude API calls. Pure Python logic.
"""
from dataclasses import dataclass, field


@dataclass
class ClaimPropertyFilter:
    """
    A filter for matching claims by property criteria + keywords.
    All non-None fields must match for a claim to be included.
    """
    section_keys:  list[str] | None = None  # whitelist of section_key values
    materiality:   list[str] | None = None  # e.g. ["tier_a", "tier_b"]
    recurring:     bool      | None = None  # None = don't care
    claim_types:   list[str] | None = None  # e.g. ["financial_observation"]
    keywords:      list[str] | None = None  # any keyword in claim text (OR match, case-insensitive)
    inspect_description: str = ""           # human-readable description for insufficient_evidence


@dataclass
class PatternDefinition:
    """
    A financial review pattern.
    ALL required_filters must have at least one matching claim to trigger.
    """
    pattern_id:           str
    name_zh:              str
    observation_template: str              # bounded observation text (no investment advice)
    required_filters:     list[ClaimPropertyFilter] = field(default_factory=list)
    inspect_description:  str = ""         # overall description of what is being checked


@dataclass
class TriggerResult:
    """Result of evaluating a pattern against a set of claims."""
    status:               str              # "triggered" | "not_triggered" | "insufficient_evidence"
    source_claims:        list[dict] = field(default_factory=list)
    missing_keys:         list[str]  = field(default_factory=list)
    generated_observation: str = ""

    # Guard: patterns always produce interpretation level, never enter Key Findings
    CLAIM_LEVEL: str = "interpretation"
    REQUIRES_REVIEW: bool = True
    IN_KEY_FINDINGS: bool = False
