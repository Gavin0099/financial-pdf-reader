"""
Diff Service — Phase 4
------------------------
比較兩份台股財報，找出 section-level 差異。

流程：
1. 取兩份文件的所有 chunks，按 section 分組
2. 找出共同段落、只在本季、只在上季的段落
3. 對每個共同段落呼叫 Claude，產生 diff items
4. 每個 diff item 必須有來源頁碼
5. 語氣變化明確標記 tone_only=True，不等同財務惡化

Governance：
- 不允許跨文件推論未標示來源
- 不允許把語氣變化直接說成財務惡化
- 不允許用單季資料推論長期趨勢
"""
import json
import uuid
from collections import defaultdict
from typing import Optional

import anthropic

from config.config import AnthropicConfig
from models.documents import PDFDocument, PDFChunk
from models.reports import DiffReport, DiffItem, DiffEvidence
from prompts import DIFF_REPORT_PROMPT, INVESTMENT_ADVICE_GUARD_PHRASES
from services.classification import SECTIONS

_client: Optional[anthropic.Anthropic] = None

# 每份文件每個 section 最多送幾個 chunks 給 Claude
MAX_CHUNKS_PER_SECTION = 8


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=AnthropicConfig.API_KEY)
    return _client


def _get_section_chunks(document_id: str) -> dict[str, list[PDFChunk]]:
    """回傳 {section: [chunks]}，unknown 段落不納入 diff"""
    chunks = PDFChunk.objects(document_id=document_id).order_by("page")
    grouped: dict[str, list[PDFChunk]] = defaultdict(list)
    for c in chunks:
        if c.section and c.section != "unknown":
            grouped[c.section].append(c)
    return dict(grouped)


def _chunks_to_text(chunks: list[PDFChunk], max_chunks: int = MAX_CHUNKS_PER_SECTION) -> str:
    parts = [f"[p.{c.page}]\n{c.text}" for c in chunks[:max_chunks]]
    return "\n\n---\n\n".join(parts)


def _check_investment_advice(text: str) -> bool:
    lower = text.lower()
    return any(p in lower for p in INVESTMENT_ADVICE_GUARD_PHRASES)


def _diff_section(
    section: str,
    current_chunks: list[PDFChunk],
    previous_chunks: list[PDFChunk],
    current_doc: PDFDocument,
    previous_doc: PDFDocument,
) -> list[DiffItem]:
    """對單一 section 呼叫 Claude，回傳 DiffItem 列表"""
    current_text = _chunks_to_text(current_chunks)
    previous_text = _chunks_to_text(previous_chunks)

    prompt = DIFF_REPORT_PROMPT.format(
        section=section,
        stock_id=current_doc.stock_id,
        current_period=current_doc.period,
        previous_period=previous_doc.period,
        current_chunks=current_text or "(本季無此段落資料)",
        previous_chunks=previous_text or "(上季無此段落資料)",
    )

    client = _get_client()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = message.content[0].text

    try:
        js = raw_text[raw_text.index("{"):raw_text.rindex("}") + 1]
        raw_json = json.loads(js)
    except (ValueError, json.JSONDecodeError):
        return []

    items = []
    for item in raw_json.get("items", []):
        ev_data = item.get("evidence", {})
        presence = ev_data.get("presence", "both")

        # Governance: at least one page reference required
        c_page = str(ev_data.get("current_page", "")).strip()
        p_page = str(ev_data.get("previous_page", "")).strip()
        if not c_page and not p_page:
            continue  # 無來源，跳過

        evidence = DiffEvidence(
            current_document_id=current_doc.document_id if c_page else "",
            current_page=c_page,
            current_quoted=ev_data.get("current_quoted", "")[:100],
            previous_document_id=previous_doc.document_id if p_page else "",
            previous_page=p_page,
            previous_quoted=ev_data.get("previous_quoted", "")[:100],
            presence=presence if presence in ("both", "only_in_current", "only_in_previous") else "both",
        )

        diff_type = item.get("diff_type", "new_language")
        valid_types = {"new_language", "removed_language", "tone_shift", "numeric_change", "new_risk", "removed_risk"}
        if diff_type not in valid_types:
            diff_type = "new_language"

        items.append(DiffItem(
            diff_id=item.get("diff_id", str(uuid.uuid4())),
            section=section,
            diff_type=diff_type,
            description=item.get("description", ""),
            current_summary=item.get("current_summary", "")[:300],
            previous_summary=item.get("previous_summary", "")[:300],
            evidence=evidence,
            tone_only=item.get("tone_only", diff_type == "tone_shift"),
            requires_human_review=item.get("requires_human_review", True),
        ))
    return items


def generate_diff(current_document_id: str, previous_document_id: str) -> dict:
    """
    主流程：取兩份文件的 chunks → section-level diff → 存 DiffReport
    """
    current_doc = PDFDocument.objects(document_id=current_document_id).first()
    previous_doc = PDFDocument.objects(document_id=previous_document_id).first()

    if not current_doc:
        raise ValueError(f"Current document not found: {current_document_id}")
    if not previous_doc:
        raise ValueError(f"Previous document not found: {previous_document_id}")
    if current_doc.stock_id != previous_doc.stock_id:
        raise ValueError(
            f"Stock ID mismatch: {current_doc.stock_id} vs {previous_doc.stock_id}. "
            "Diff must compare same company."
        )
    if current_doc.status != "completed" or previous_doc.status != "completed":
        raise ValueError("Both documents must be ingested (status=completed) before diff.")

    current_by_section = _get_section_chunks(current_document_id)
    previous_by_section = _get_section_chunks(previous_document_id)

    current_sections = set(current_by_section.keys())
    previous_sections = set(previous_by_section.keys())
    shared_sections = current_sections & previous_sections
    only_current = current_sections - previous_sections
    only_previous = previous_sections - current_sections

    all_items: list[DiffItem] = []

    # Diff shared sections
    for section in sorted(shared_sections):
        try:
            items = _diff_section(
                section,
                current_by_section[section],
                previous_by_section[section],
                current_doc,
                previous_doc,
            )
            all_items.extend(items)
        except Exception:
            continue  # 單一 section 失敗不中斷整體流程

    # Mark only_in_current sections as potential new content
    for section in only_current:
        chunks = current_by_section[section]
        if chunks:
            page = str(chunks[0].page)
            all_items.append(DiffItem(
                diff_id=str(uuid.uuid4()),
                section=section,
                diff_type="new_language",
                description=f"本季新出現段落「{section}」，上季無對應內容",
                current_summary=chunks[0].text[:200],
                previous_summary="",
                evidence=DiffEvidence(
                    current_document_id=current_document_id,
                    current_page=page,
                    current_quoted=chunks[0].text[:80],
                    presence="only_in_current",
                ),
                tone_only=False,
                requires_human_review=True,
            ))

    # Mark only_in_previous sections as removed content
    for section in only_previous:
        chunks = previous_by_section[section]
        if chunks:
            page = str(chunks[0].page)
            all_items.append(DiffItem(
                diff_id=str(uuid.uuid4()),
                section=section,
                diff_type="removed_language",
                description=f"上季存在段落「{section}」，本季無對應內容",
                current_summary="",
                previous_summary=chunks[0].text[:200],
                evidence=DiffEvidence(
                    previous_document_id=previous_document_id,
                    previous_page=page,
                    previous_quoted=chunks[0].text[:80],
                    presence="only_in_previous",
                ),
                tone_only=False,
                requires_human_review=True,
            ))

    report = DiffReport(
        diff_report_id=str(uuid.uuid4()),
        current_document_id=current_document_id,
        previous_document_id=previous_document_id,
        stock_id=current_doc.stock_id,
        current_period=current_doc.period,
        previous_period=previous_doc.period,
        items=all_items,
        sections_compared=sorted(shared_sections),
        sections_only_current=sorted(only_current),
        sections_only_previous=sorted(only_previous),
        requires_human_review=True,
    )
    report.save()

    return _serialize_report(report)


def _serialize_report(report: DiffReport) -> dict:
    return {
        "diff_report_id": report.diff_report_id,
        "stock_id": report.stock_id,
        "current_period": report.current_period,
        "previous_period": report.previous_period,
        "sections_compared": report.sections_compared,
        "sections_only_current": report.sections_only_current,
        "sections_only_previous": report.sections_only_previous,
        "total_items": len(report.items),
        "requires_human_review": report.requires_human_review,
        "items": [
            {
                "diff_id": it.diff_id,
                "section": it.section,
                "diff_type": it.diff_type,
                "description": it.description,
                "current_summary": it.current_summary,
                "previous_summary": it.previous_summary,
                "tone_only": it.tone_only,
                "requires_human_review": it.requires_human_review,
                "evidence": {
                    "current_page": it.evidence.current_page if it.evidence else "",
                    "current_quoted": it.evidence.current_quoted if it.evidence else "",
                    "previous_page": it.evidence.previous_page if it.evidence else "",
                    "previous_quoted": it.evidence.previous_quoted if it.evidence else "",
                    "presence": it.evidence.presence if it.evidence else "both",
                },
            }
            for it in report.items
        ],
    }
