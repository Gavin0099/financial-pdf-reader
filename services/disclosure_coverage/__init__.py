"""
Disclosure Coverage Service — 財報揭露完整性稽核
-------------------------------------------------
使用 claude-haiku-4-5 逐一檢查 14 項法定揭露事項是否出現於財報 PDF。

輸出只包含稽核狀態（found / found_incomplete / not_found / ambiguous / not_applicable），
不產生任何投資結論。
"""
import json
import uuid

import anthropic

from config.config import AnthropicConfig
from models.disclosures import (
    DISCLOSURE_REGISTRY,
    DisclosureCoverageItem,
    DisclosureCoverageReport,
)
from models.documents import PDFChunk, PDFDocument
from prompts import DISCLOSURE_COVERAGE_PROMPT

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=AnthropicConfig.API_KEY)
    return _client


def check_disclosure_coverage(document_id: str) -> dict:
    """
    對已 ingest 的 PDF 執行 14 項法定揭露完整性稽核。
    返回 coverage dict，並持久化 DisclosureCoverageReport 到 MongoDB。
    """
    doc = PDFDocument.objects(document_id=document_id).first()
    if not doc:
        raise ValueError(f"Document not found: {document_id}")
    if doc.status != "completed":
        raise ValueError(f"Document not ingested (status={doc.status}). Run /ingest first.")

    chunks = list(
        PDFChunk.objects(document_id=document_id).order_by("page").limit(60)
    )
    if not chunks:
        raise ValueError("No chunks found. Run /ingest first.")

    chunks_text = "\n\n---\n\n".join(f"[p.{c.page}]\n{c.text}" for c in chunks)
    prompt = DISCLOSURE_COVERAGE_PROMPT.format(
        chunks_text=chunks_text,
        company_name=doc.company_name,
        stock_id=doc.stock_id,
        period=doc.period,
    )

    message = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = message.content[0].text

    try:
        json_start = raw_text.index("{")
        json_end = raw_text.rindex("}") + 1
        raw_json = json.loads(raw_text[json_start:json_end])
    except (ValueError, json.JSONDecodeError) as e:
        raise RuntimeError(
            f"Coverage 回傳格式無法解析: {e}\n原文: {raw_text[:400]}"
        ) from e

    # Build items — guarantee all 14 registry keys are present
    items_by_key = {item["key"]: item for item in raw_json.get("items", [])}
    items: list[DisclosureCoverageItem] = []
    for key, label_zh in DISCLOSURE_REGISTRY:
        raw = items_by_key.get(key, {})
        items.append(
            DisclosureCoverageItem(
                key=key,
                label_zh=label_zh,
                status=raw.get("status", "ambiguous"),
                evidence_pages=raw.get("evidence_pages", []),
                note=raw.get("note", ""),
            )
        )

    status_counts = {
        s: sum(1 for i in items if i.status == s)
        for s in ["found", "found_incomplete", "not_found", "not_applicable"]
    }

    report = DisclosureCoverageReport(
        coverage_id=str(uuid.uuid4()),
        document_id=document_id,
        stock_id=doc.stock_id,
        period=doc.period,
        items=items,
        found_count=status_counts["found"],
        found_incomplete_count=status_counts["found_incomplete"],
        not_found_count=status_counts["not_found"],
        not_applicable_count=status_counts["not_applicable"],
        total_count=14,
    )
    report.save()

    return {
        "coverage_id": report.coverage_id,
        "document_id": document_id,
        "stock_id": doc.stock_id,
        "period": doc.period,
        "found_count": status_counts["found"],
        "found_incomplete_count": status_counts["found_incomplete"],
        "not_found_count": status_counts["not_found"],
        "not_applicable_count": status_counts["not_applicable"],
        "total_count": 14,
        "items": [
            {
                "key": i.key,
                "label_zh": i.label_zh,
                "status": i.status,
                "evidence_pages": i.evidence_pages,
                "note": i.note,
            }
            for i in items
        ],
    }
