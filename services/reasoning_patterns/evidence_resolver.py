"""
Evidence Resolver — find claims matching a ClaimPropertyFilter.
Pure Python, no I/O, no API calls.
"""
from reasoning_patterns.schemas import ClaimPropertyFilter


def find_matching_claims(claims: list[dict], f: ClaimPropertyFilter) -> list[dict]:
    """Return claims matching ALL non-None criteria in filter."""
    result = []
    for c in claims:
        if f.section_keys and c.get("section_key") not in f.section_keys:
            continue
        if f.materiality and c.get("materiality") not in f.materiality:
            continue
        if f.recurring is not None:
            claim_recurring = c.get("recurring")
            # treat None/missing as True (recurring by default)
            if claim_recurring is None:
                claim_recurring = True
            if bool(claim_recurring) != f.recurring:
                continue
        if f.claim_types and c.get("claim_type") not in f.claim_types:
            continue
        if f.keywords:
            text = c.get("claim", "").lower()
            if not any(kw.lower() in text for kw in f.keywords):
                continue
        result.append(c)
    return result
