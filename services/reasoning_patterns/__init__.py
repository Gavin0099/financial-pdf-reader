"""
Reasoning Pattern Analysis Service
Runs all 6 patterns against existing claims from the latest AIReport.
No Claude API calls — pure property + keyword matching.
"""
import uuid
from datetime import datetime, timezone

from models.documents import PDFDocument
from models.reports import AIReport
from models.patterns import PatternRunReport, PatternRunResult
from reasoning_patterns import PATTERN_REGISTRY
from services.reasoning_patterns.engine import evaluate_pattern


def _claim_to_dict(c) -> dict:
    """Convert AIClaim EmbeddedDocument to a plain dict for pattern matching."""
    return {
        "claim_id":   c.claim_id,
        "claim":      c.claim,
        "claim_type": c.claim_type,
        "claim_level": c.claim_level,
        "materiality": c.materiality,
        "section_key": c.section_key,
        "recurring":   c.recurring,
        "contaminated": c.contaminated,
    }


def run_pattern_analysis(document_id: str) -> dict:
    """
    Run all 6 reasoning patterns against the latest AIReport claims.

    Returns a dict suitable for direct JSON serialization.
    Raises:
        ValueError — document not found or not ingested, or no AIReport
    """
    doc = PDFDocument.objects(document_id=document_id).first()
    if not doc:
        raise ValueError(f"Document not found: {document_id}")
    if doc.status != "completed":
        raise ValueError(f"Document {document_id} not ingested (status={doc.status})")

    report = AIReport.objects(document_id=document_id).order_by("-created_at").first()
    if not report:
        raise ValueError("No AIReport found for this document. Run /summary first.")

    # Exclude contaminated claims from pattern analysis
    clean_claims = [
        _claim_to_dict(c)
        for c in report.claims
        if not c.contaminated
    ]

    results = []
    for pattern in PATTERN_REGISTRY:
        trigger = evaluate_pattern(pattern, clean_claims)
        results.append(PatternRunResult(
            pattern_id=pattern.pattern_id,
            name_zh=pattern.name_zh,
            status=trigger.status,
            generated_observation=trigger.generated_observation,
            source_claim_ids=[c["claim_id"] for c in trigger.source_claims],
            missing_evidence_keys=trigger.missing_keys,
            requires_review=(trigger.status == "triggered"),
        ))

    triggered     = sum(1 for r in results if r.status == "triggered")
    not_triggered = sum(1 for r in results if r.status == "not_triggered")
    insufficient  = sum(1 for r in results if r.status == "insufficient_evidence")

    run = PatternRunReport(
        run_id=str(uuid.uuid4()),
        document_id=document_id,
        stock_id=doc.stock_id,
        period=doc.period,
        results=results,
        triggered_count=triggered,
        not_triggered_count=not_triggered,
        insufficient_count=insufficient,
    )
    run.save()

    # Build source claims lookup for response
    claim_lookup = {c["claim_id"]: c for c in clean_claims}

    return {
        "run_id":            run.run_id,
        "document_id":       document_id,
        "stock_id":          doc.stock_id,
        "period":            doc.period,
        "triggered_count":   triggered,
        "not_triggered_count": not_triggered,
        "insufficient_count": insufficient,
        "results": [
            {
                "pattern_id":           r.pattern_id,
                "name_zh":              r.name_zh,
                "status":               r.status,
                "generated_observation": r.generated_observation,
                "requires_review":      r.requires_review,
                "claim_level":          "interpretation",   # guard — always interpretation
                "in_key_findings":      False,               # guard — never in Key Findings
                "source_claims": [
                    {
                        "claim_id":    cid,
                        "claim":       claim_lookup.get(cid, {}).get("claim", ""),
                        "section_key": claim_lookup.get(cid, {}).get("section_key", ""),
                        "materiality": claim_lookup.get(cid, {}).get("materiality", ""),
                    }
                    for cid in r.source_claim_ids
                ],
                "missing_evidence_keys": r.missing_evidence_keys,
            }
            for r in results
        ],
    }
