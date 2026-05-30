"""
KPI Normalization Service — v1
--------------------------------
從 PDFTable（markdown 格式）中提取 8 個核心 KPI 數值。

v1 範圍：
- 數字解析：逗號分隔、括號負數、% 後綴、空白/破折號
- Keyword 搜尋：label 欄（第一欄）匹配，取當期值欄（第二欄）
- 單位偵測：回傳 unit_hint 但不做換算（千元 vs 百萬 vs 億 是 v2）
- 信心度：依 PDFTable.extraction_quality 判斷

不在 v1 範圍：
- 跨頁表格合併
- 單位自動換算
- 多期比對
"""
import re
from typing import Optional

from models.documents import PDFDocument, PDFTable


# ── 8 個 KPI 的中英文關鍵字 ──────────────────────────────────────────────────

_KPI_KEYWORDS: dict[str, list[str]] = {
    "revenue": [
        "營業收入", "收入淨額", "銷貨收入", "營收合計",
        "Revenue", "Net Revenue", "Net Sales",
    ],
    "gross_margin": [
        "毛利率", "銷貨毛利率", "Gross Margin", "Gross Profit Margin",
    ],
    "operating_income": [
        "營業利益", "營業損益", "營業利益（損失）",
        "Operating Income", "Operating Profit", "Income from Operations",
    ],
    "net_income": [
        "本期淨利", "稅後淨利", "本期稅後淨利", "歸屬於母公司業主之淨利",
        "Net Income", "Net Profit", "Profit for the Period",
    ],
    "eps": [
        "每股盈餘", "基本每股盈餘", "每股淨利",
        "EPS", "Earnings Per Share", "Basic EPS",
    ],
    "cash_and_equiv": [
        "現金及約當現金", "現金與約當現金", "期末現金及約當現金",
        "Cash and Cash Equivalents", "Cash & Equivalents",
    ],
    "total_debt": [
        "短期借款", "長期借款", "應付公司債", "一年內到期長期負債",
        "Short-term Borrowings", "Long-term Debt", "Borrowings",
    ],
    "operating_cash_flow": [
        "營業活動之現金流量", "營業活動現金流量", "來自營業活動之淨現金",
        "Operating Cash Flow", "Net Cash from Operating Activities",
        "Cash from Operations",
    ],
}

# 單位關鍵字（偵測用，不換算）
_UNIT_HINTS = ["千元", "仟元", "百萬元", "億元", "元", "新台幣千元", "USD thousands"]


# ── 純函數 ────────────────────────────────────────────────────────────────────

def parse_number(text: str) -> Optional[float]:
    """
    將表格儲存格文字轉為 float。

    處理：
    - 逗號分隔：1,234,567 → 1234567.0
    - 括號負數：(1,234) → -1234.0
    - % 後綴：37.5% → 37.5
    - 空白 / 破折號 → None
    - 數字後接中文單位：取數字部分（不換算）
    """
    if not text:
        return None
    t = text.strip()
    if not t or t in ("-", "—", "－", "–", "N/A", "n/a", "--", "＊"):
        return None

    negative = False
    if t.startswith("(") and t.endswith(")"):
        t = t[1:-1]
        negative = True
    elif t.startswith("（") and t.endswith("）"):
        t = t[1:-1]
        negative = True

    # 移除 % 後綴與其他非數字結尾
    t = t.rstrip("% ％").strip()

    # 移除千分位逗號
    t = t.replace(",", "").replace("，", "")

    # 取開頭數字部分（忽略中文單位後綴如「千元」）
    m = re.match(r"^(-?\d+(?:\.\d+)?)", t)
    if not m:
        return None

    try:
        value = float(m.group(1))
    except ValueError:
        return None

    return -value if negative else value


def detect_unit(markdown: str) -> Optional[str]:
    """從 markdown 表格的標題行或任意位置偵測單位提示。"""
    for hint in _UNIT_HINTS:
        if hint in markdown:
            return hint
    return None


def parse_markdown_rows(markdown: str) -> list[list[str]]:
    """
    將 markdown table 解析為 list of rows（各 row 為 list of cell strings）。
    跳過分隔行（ --- ）。
    """
    rows: list[list[str]] = []
    for line in markdown.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c).issubset(set("-: \t")) for c in cells if c):
            continue  # 分隔行
        rows.append(cells)
    return rows


def extract_kpi_from_markdown(
    markdown: str,
    keywords: list[str],
) -> tuple[Optional[float], str]:
    """
    在 markdown table 中搜尋 KPI。

    策略：
    - 掃描每行的 label 欄（第一欄）
    - 若命中任一 keyword，依序嘗試第二欄到最後一欄取數值
    - 回傳 (value, raw_cell_text)，找不到回傳 (None, "")
    """
    rows = parse_markdown_rows(markdown)
    for row in rows:
        if len(row) < 2:
            continue
        label = row[0]
        if any(kw in label for kw in keywords):
            # 從第二欄開始依序找第一個可解析的數值
            for col in range(1, len(row)):
                raw = row[col]
                value = parse_number(raw)
                if value is not None:
                    return value, raw
    return None, ""


# ── 主流程 ────────────────────────────────────────────────────────────────────

def extract_kpis(document_id: str) -> dict:
    """
    對文件的所有 PDFTable 進行 KPI 提取。
    需先執行 /extract-tables。

    回傳格式：
    {
      "document_id": "...",
      "period": "2025Q4",
      "kpis": {
        "revenue": {"value": 1234567, "raw_text": "1,234,567",
                    "unit_hint": "千元", "page": 5,
                    "table_id": "...", "confidence": "high"},
        "gross_margin": null,
        ...
      },
      "found_count": 5,
      "not_found": ["gross_margin", ...]
    }
    """
    doc = PDFDocument.objects(document_id=document_id).first()
    if not doc:
        raise ValueError(f"Document not found: {document_id}")

    tables = list(PDFTable.objects(document_id=document_id).order_by("page"))
    if not tables:
        raise ValueError(
            f"No tables found for document {document_id}. "
            "Run /extract-tables first."
        )

    kpis: dict[str, Optional[dict]] = {}

    for kpi_id, keywords in _KPI_KEYWORDS.items():
        hit = None
        for table in tables:
            value, raw = extract_kpi_from_markdown(table.table_markdown, keywords)
            if value is not None:
                hit = {
                    "value": value,
                    "raw_text": raw,
                    "unit_hint": detect_unit(table.table_markdown),
                    "page": table.page,
                    "table_id": table.table_id,
                    "confidence": (
                        "high" if table.extraction_quality == "high" else "medium"
                    ),
                }
                break
        kpis[kpi_id] = hit

    found = [k for k, v in kpis.items() if v is not None]
    not_found = [k for k, v in kpis.items() if v is None]

    return {
        "document_id": document_id,
        "period": doc.period,
        "kpis": kpis,
        "found_count": len(found),
        "not_found": not_found,
    }
