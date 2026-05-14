"""
Summarization Service — Phase 2 + Semantic Layering
-----------------------------------------------------
呼叫 Claude API，產出 evidence-bound 財報摘要。

架構：
1. Temporal Validation  — 時間軸一致性檢查，不一致時標記 contaminated
2. Observation Extraction — 分層抽取（claim_level + materiality + section_key）
3. Narrative Synthesis  — executive_summary

Evidence discipline：
- 每個 claim 必須有 evidence，否則自動降級為 insufficient_evidence
- 若 AI 輸出含投資建議詞彙，整份 report 標記 investment_advice_detected=True
- contaminated=True 的 claim 不納入 evidence_status 計算
"""
import json
import uuid

import anthropic

from config.config import AnthropicConfig
from models.documents import PDFDocument, PDFChunk
from models.reports import AIReport, AIClaim, ClaimEvidence
from prompts import EVIDENCE_BOUND_SUMMARY_PROMPT, INVESTMENT_ADVICE_GUARD_PHRASES

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=AnthropicConfig.API_KEY)
    return _client


def _retrieve_chunks(document_id: str, max_chunks: int = 60) -> list[PDFChunk]:
    return list(
        PDFChunk.objects(document_id=document_id)
        .order_by("page")
        .limit(max_chunks)
    )


def _build_chunks_text(chunks: list[PDFChunk]) -> str:
    parts = []
    for c in chunks:
        parts.append(f"[p.{c.page}]\n{c.text}")
    return "\n\n---\n\n".join(parts)


def _check_investment_advice(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in INVESTMENT_ADVICE_GUARD_PHRASES)


def _parse_claims(raw_json: dict, document_id: str, temporal_consistent: bool) -> list[AIClaim]:
    claims = []
    for item in raw_json.get("claims", []):
        evidence_list = []
        for ev in item.get("evidence", []):
            evidence_list.append(
                ClaimEvidence(
                    document_id=document_id,
                    page=str(ev.get("page", "unknown")),
                    section=ev.get("section", "unknown"),
                    quoted_text=ev.get("quoted_text", ""),
                )
            )

        # Governance: 沒有 evidence → 強制降級
        claim_level = item.get("claim_level", "interpretation")
        if not evidence_list and claim_level not in ("insufficient_evidence",):
            claim_level = "insufficient_evidence"

        # Temporal contamination enforcement
        contaminated = item.get("contaminated", False)
        if not temporal_consistent and claim_level in ("derived_metric", "interpretation", "hypothesis"):
            contaminated = True

        claims.append(
            AIClaim(
                claim_id=item.get("claim_id", str(uuid.uuid4())),
                claim=item.get("claim", ""),
                claim_type=item.get("claim_type", "financial_observation"),
                claim_level=claim_level,
                materiality=item.get("materiality", "tier_b"),
                section_key=item.get("section_key", "key_financials"),
                recurring=item.get("recurring", True),
                contaminated=contaminated,
                evidence=evidence_list,
                confidence=item.get("confidence", "medium"),
                requires_human_review=item.get("requires_human_review", False),
            )
        )
    return claims


def generate_summary(document_id: str) -> dict:
    """
    主流程：取 chunks → 呼叫 Claude → Temporal Validation → 分層抽取 → 存 AIReport
    """
    doc = PDFDocument.objects(document_id=document_id).first()
    if not doc:
        raise ValueError(f"Document not found: {document_id}")

    if doc.status != "completed":
        raise ValueError(f"Document not yet ingested (status={doc.status}). Run /ingest first.")

    chunks = _retrieve_chunks(document_id)
    if not chunks:
        raise ValueError("No chunks found. Run /ingest first.")

    chunks_text = _build_chunks_text(chunks)
    prompt = EVIDENCE_BOUND_SUMMARY_PROMPT.format(
        chunks_text=chunks_text,
        company_name=doc.company_name,
        stock_id=doc.stock_id,
        period=doc.period,
    )

    client = _get_client()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = message.content[0].text

    # 抽出 JSON block
    try:
        json_start = raw_text.index("{")
        json_end = raw_text.rindex("}") + 1
        raw_json = json.loads(raw_text[json_start:json_end])
    except (ValueError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Claude 回傳格式無法解析: {e}\n原文: {raw_text[:500]}") from e

    # --- Temporal Validation ---
    tv = raw_json.get("temporal_validation", {})
    temporal_consistent = tv.get("is_consistent", True)
    temporal_note = tv.get("mismatch_note", "")
    document_period = tv.get("document_period", doc.period)
    requested_period = tv.get("requested_period", doc.period)

    # --- Executive Summary ---
    executive_summary = raw_json.get("executive_summary", "")

    # --- Claims ---
    claims = _parse_claims(raw_json, document_id, temporal_consistent)

    # Evidence status：只計算非 contaminated 的 claims
    clean_claims = [c for c in claims if not c.contaminated]
    total_clean = len(clean_claims)
    insufficient = sum(1 for c in clean_claims if c.claim_level == "insufficient_evidence")

    if total_clean == 0:
        evidence_status = "insufficient"
    elif insufficient == 0:
        evidence_status = "complete"
    elif insufficient < total_clean:
        evidence_status = "partial"
    else:
        evidence_status = "insufficient"

    investment_advice_detected = _check_investment_advice(raw_text)

    report = AIReport(
        report_id=str(uuid.uuid4()),
        document_id=document_id,
        stock_id=doc.stock_id,
        period=doc.period,
        report_type="single_summary",
        temporal_consistent=temporal_consistent,
        temporal_note=temporal_note,
        executive_summary=executive_summary,
        claims=claims,
        evidence_status=evidence_status,
        investment_advice_detected=investment_advice_detected,
    )
    report.save()

    total = len(claims)
    contaminated_count = sum(1 for c in claims if c.contaminated)

    return {
        "report_id": report.report_id,
        "document_id": document_id,
        "stock_id": doc.stock_id,
        "period": doc.period,
        "temporal_consistent": temporal_consistent,
        "temporal_note": temporal_note,
        "document_period": document_period,
        "requested_period": requested_period,
        "executive_summary": executive_summary,
        "total_claims": total,
        "contaminated_count": contaminated_count,
        "insufficient_evidence_count": insufficient,
        "evidence_status": evidence_status,
        "investment_advice_detected": investment_advice_detected,
        "claims": [
            {
                "claim_id": c.claim_id,
                "claim": c.claim,
                "claim_type": c.claim_type,
                "claim_level": c.claim_level,
                "materiality": c.materiality,
                "section_key": c.section_key,
                "recurring": c.recurring,
                "contaminated": c.contaminated,
                "confidence": c.confidence,
                "requires_human_review": c.requires_human_review,
                "evidence": [
                    {
                        "page": e.page,
                        "section": e.section,
                        "quoted_text": e.quoted_text,
                    }
                    for e in c.evidence
                ],
            }
            for c in claims
        ],
    }
