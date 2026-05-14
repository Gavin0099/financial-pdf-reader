"""
Pattern Engine — evaluate a PatternDefinition against a list of claims.
Pure Python, no I/O, no API calls.

Guard constants (enforced at this layer):
  CLAIM_LEVEL = "interpretation"   — patterns never produce observed_fact
  REQUIRES_REVIEW = True           — all triggered patterns need human review
  IN_KEY_FINDINGS = False          — patterns never enter Key Findings
"""
from reasoning_patterns.schemas import PatternDefinition, TriggerResult
from services.reasoning_patterns.evidence_resolver import find_matching_claims

# Guard rails — never change these
GUARD_CLAIM_LEVEL = "interpretation"
GUARD_REQUIRES_REVIEW = True
GUARD_IN_KEY_FINDINGS = False


def evaluate_pattern(pattern: PatternDefinition, claims: list[dict]) -> TriggerResult:
    """
    Evaluate one pattern against claims.
    ALL required_filters must have at least 1 matching claim to trigger.
    If any filter has no matches → insufficient_evidence (not not_triggered).
    """
    matched_per_filter: list[list[dict]] = []
    missing: list[str] = []

    for i, f in enumerate(pattern.required_filters):
        matched = find_matching_claims(claims, f)
        if matched:
            matched_per_filter.append(matched)
        else:
            label = f.inspect_description or f"filter_{i}"
            missing.append(label)

    if missing:
        return TriggerResult(
            status="insufficient_evidence",
            missing_keys=missing,
        )

    # Flatten + deduplicate by claim_id
    seen: set[str] = set()
    unique: list[dict] = []
    for group in matched_per_filter:
        for c in group:
            cid = c.get("claim_id", "")
            if cid not in seen:
                seen.add(cid)
                unique.append(c)

    if not unique:
        return TriggerResult(status="not_triggered")

    return TriggerResult(
        status="triggered",
        source_claims=unique,
        generated_observation=pattern.observation_template,
    )
