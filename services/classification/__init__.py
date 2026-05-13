"""
Financial Section Classification Service — Phase 3
----------------------------------------------------
將 PDFChunk 分類到 20 個台股財報常見段落。

策略：
1. Rule-based keyword matching（快、確定性高）
2. LLM-assisted fallback（Claude，僅在 rule 無法確認時使用）

原則：
- 分類失敗 → section = "unknown"，不中斷流程
- 每個 chunk 都可以有人工修正欄位（manual_section）
- LLM 分類結果標記 confidence = "low"，rule 結果標記 confidence = "high"
"""
import json
from typing import Optional

import anthropic

from config.config import AnthropicConfig
from models.documents import PDFChunk

# ── 20 個財務段落定義 ────────────────────────────────────────────────────────

SECTIONS = [
    "營收",
    "毛利率",
    "營業利益",
    "淨利",
    "EPS",
    "存貨",
    "應收帳款",
    "現金流",
    "資本支出",
    "負債",
    "匯率影響",
    "產能",
    "稼動率",
    "客戶需求",
    "產業展望",
    "風險因素",
    "重大會計估計",
    "會計政策變更",
    "管理層展望",
    "董事會說明",
]

# ── Rule-based keyword mapping ────────────────────────────────────────────────

SECTION_KEYWORDS: dict[str, list[str]] = {
    "營收": ["營業收入", "營收", "revenue", "net revenue", "銷貨收入", "淨收入"],
    "毛利率": ["毛利", "毛利率", "gross profit", "gross margin", "銷貨成本"],
    "營業利益": ["營業利益", "營業損益", "operating income", "operating profit", "營業費用"],
    "淨利": ["本期淨利", "稅後淨利", "淨損益", "net income", "net profit", "歸屬於母公司"],
    "EPS": ["每股盈餘", "每股淨利", "earnings per share", "eps", "基本每股"],
    "存貨": ["存貨", "庫存", "inventory", "在製品", "製成品", "原料"],
    "應收帳款": ["應收帳款", "應收票據", "accounts receivable", "trade receivable", "應收款項"],
    "現金流": ["現金流量", "cash flow", "營業活動", "投資活動", "融資活動", "自由現金流"],
    "資本支出": ["資本支出", "capital expenditure", "capex", "購置不動產", "廠房及設備"],
    "負債": ["負債", "借款", "應付帳款", "debt", "liability", "長期負債", "短期借款"],
    "匯率影響": ["匯率", "外幣", "匯兌", "exchange rate", "foreign currency", "美元", "匯兌損益"],
    "產能": ["產能", "capacity", "晶圓", "wafer", "fab", "擴產", "新廠"],
    "稼動率": ["稼動率", "utilization", "產能利用率", "稼働率"],
    "客戶需求": ["客戶需求", "customer demand", "終端需求", "下游", "庫存調整", "拉貨"],
    "產業展望": ["產業展望", "市場展望", "industry outlook", "半導體", "市場趨勢", "景氣"],
    "風險因素": ["風險", "risk", "不確定性", "uncertainty", "地緣政治", "供應鏈風險"],
    "重大會計估計": ["重大會計估計", "關鍵估計", "critical accounting", "商譽減損", "資產減損"],
    "會計政策變更": ["會計政策", "accounting policy", "新準則", "ifrs", "會計原則變更"],
    "管理層展望": ["展望", "outlook", "guidance", "預期", "下季", "下半年", "未來"],
    "董事會說明": ["董事會", "board", "股利", "dividend", "股東會", "重大決議"],
}

_llm_client: Optional[anthropic.Anthropic] = None


def _get_llm_client() -> anthropic.Anthropic:
    global _llm_client
    if _llm_client is None:
        _llm_client = anthropic.Anthropic(api_key=AnthropicConfig.API_KEY)
    return _llm_client


def classify_by_rule(text: str) -> Optional[str]:
    """
    Rule-based 分類：掃描 keywords，回傳命中最多的段落。
    若沒有命中回傳 None。
    """
    lower = text.lower()
    scores: dict[str, int] = {}
    for section, keywords in SECTION_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw.lower() in lower)
        if count > 0:
            scores[section] = count

    if not scores:
        return None
    return max(scores, key=lambda s: scores[s])


def classify_by_llm(text: str) -> Optional[str]:
    """
    LLM-assisted 分類：只有 rule-based 回傳 None 時才呼叫。
    要求 Claude 從 SECTIONS 列表中選一個，或回傳 "unknown"。
    """
    sections_str = "、".join(SECTIONS)
    prompt = f"""你是台股財報分類工具。以下是財報中的一段文字，請從候選段落中選出最符合的一個。

候選段落（只能選這些，或回傳 unknown）：
{sections_str}、unknown

財報文字：
{text[:800]}

只回傳一個段落名稱，不要其他文字。例如：存貨"""

    try:
        client = _get_llm_client()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}],
        )
        result = message.content[0].text.strip()
        return result if result in SECTIONS else "unknown"
    except Exception:
        return "unknown"


def classify_chunk(text: str, use_llm_fallback: bool = True) -> tuple[str, str]:
    """
    回傳 (section, method)
    method: "rule" | "llm" | "fallback"
    """
    section = classify_by_rule(text)
    if section:
        return section, "rule"

    if use_llm_fallback:
        section = classify_by_llm(text)
        return section or "unknown", "llm"

    return "unknown", "fallback"


def classify_document(document_id: str, use_llm_fallback: bool = True) -> dict:
    """
    對整份文件的所有 chunks 進行分類，更新 PDFChunk.section。
    分類失敗時 section = "unknown"，不中斷流程。
    """
    chunks = list(PDFChunk.objects(document_id=document_id).order_by("page"))
    if not chunks:
        raise ValueError(f"No chunks found for document {document_id}")

    stats = {"rule": 0, "llm": 0, "fallback": 0, "unknown": 0}
    section_counts: dict[str, int] = {}

    for chunk in chunks:
        try:
            section, method = classify_chunk(chunk.text, use_llm_fallback)
        except Exception:
            section, method = "unknown", "fallback"

        chunk.section = section
        chunk.save()

        stats[method] = stats.get(method, 0) + 1
        section_counts[section] = section_counts.get(section, 0) + 1

    stats["unknown"] = section_counts.get("unknown", 0)

    return {
        "document_id": document_id,
        "total_chunks": len(chunks),
        "classification_stats": stats,
        "section_distribution": dict(
            sorted(section_counts.items(), key=lambda x: x[1], reverse=True)
        ),
    }


def manual_override(chunk_id: str, section: str) -> dict:
    """人工修正單一 chunk 的分類"""
    if section not in SECTIONS and section != "unknown":
        raise ValueError(f"Invalid section: {section}. Must be one of {SECTIONS + ['unknown']}")

    chunk = PDFChunk.objects(chunk_id=chunk_id).first()
    if not chunk:
        raise ValueError(f"Chunk not found: {chunk_id}")

    old_section = chunk.section
    chunk.section = section
    chunk.save()

    return {
        "chunk_id": chunk_id,
        "old_section": old_section,
        "new_section": section,
        "method": "manual",
    }
