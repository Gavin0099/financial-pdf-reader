"""
Table Extraction Service — Phase 5
------------------------------------
從 PDF 每頁抽取表格，轉成 markdown，存入 PDFTable。

原則：
- 表格抽取失敗時標記 extraction_quality=failed + requires_human_review=True
- 每個表格必須帶頁碼（page），不允許 null
- 表格欄位錯位時降級 extraction_quality=low
- AI 引用的數字 claim 可以連回 PDFTable 做 cross-check
"""
import re
import uuid
from pathlib import Path

import pdfplumber

from models.documents import PDFDocument, PDFTable
from services.classification import classify_chunk


def _rows_to_markdown(rows: list[list]) -> str:
    """把 pdfplumber 抽出的 rows 轉成 markdown table"""
    if not rows:
        return ""

    # 清理 None 值
    clean_rows = []
    for row in rows:
        clean_rows.append([str(cell).strip() if cell is not None else "" for cell in row])

    if not clean_rows:
        return ""

    header = clean_rows[0]
    col_count = len(header)

    lines = []
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * col_count) + " |")
    for row in clean_rows[1:]:
        # 補齊欄數
        padded = row + [""] * (col_count - len(row))
        lines.append("| " + " | ".join(padded[:col_count]) + " |")

    return "\n".join(lines)


def _assess_quality(rows: list[list]) -> str:
    """根據表格結構評估抽取品質"""
    if not rows or len(rows) < 2:
        return "low"

    col_counts = [len(r) for r in rows]
    max_cols = max(col_counts)
    min_cols = min(col_counts)

    # 如果欄數差異超過 50%，表示欄位可能錯位
    if min_cols < max_cols * 0.5:
        return "low"
    if min_cols < max_cols * 0.8:
        return "medium"
    return "high"


def extract_tables(document_id: str) -> dict:
    """
    對已上傳的 PDF 逐頁抽取表格，存入 PDFTable。

    回傳 extraction summary。
    """
    doc = PDFDocument.objects(document_id=document_id).first()
    if not doc:
        raise ValueError(f"Document not found: {document_id}")

    if not Path(doc.file_path).exists():
        raise FileNotFoundError(f"PDF file missing: {doc.file_path}")

    tables_created = 0
    tables_failed = 0
    pages_with_tables = 0

    with pdfplumber.open(doc.file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            try:
                raw_tables = page.extract_tables()
            except Exception:
                tables_failed += 1
                continue

            if not raw_tables:
                continue

            pages_with_tables += 1

            for table_index, rows in enumerate(raw_tables):
                if not rows:
                    continue

                markdown = _rows_to_markdown(rows)
                quality = _assess_quality(rows)

                if not markdown:
                    tables_failed += 1
                    continue

                # 對表格內容做 section 分類
                section, _ = classify_chunk(markdown, use_llm_fallback=False)

                table = PDFTable(
                    table_id=str(uuid.uuid4()),
                    document_id=document_id,
                    stock_id=doc.stock_id,
                    period=doc.period,
                    page=page_num,
                    section=section,
                    table_index=table_index,
                    table_markdown=markdown,
                    row_count=len(rows),
                    col_count=len(rows[0]) if rows else 0,
                    extraction_quality=quality,
                    requires_human_review=(quality == "low"),
                )
                table.save()
                tables_created += 1

    return {
        "document_id": document_id,
        "tables_created": tables_created,
        "tables_failed": tables_failed,
        "pages_with_tables": pages_with_tables,
    }


def find_numeric_evidence(document_id: str, number_str: str) -> list[dict]:
    """
    在 PDFTable 中搜尋包含特定數字的表格，作為 claim 的 evidence。
    回傳 [{table_id, page, section, markdown_snippet}]
    """
    # 清理數字字串（移除逗號、空格）
    clean_num = re.sub(r"[,\s]", "", number_str)

    tables = PDFTable.objects(document_id=document_id)
    matches = []

    for t in tables:
        # 在 markdown 中搜尋數字
        clean_md = re.sub(r"[,\s]", "", t.table_markdown)
        if clean_num in clean_md:
            # 找出包含數字的那一行
            snippet = ""
            for line in t.table_markdown.split("\n"):
                if re.sub(r"[,\s]", "", line) and clean_num in re.sub(r"[,\s]", "", line):
                    snippet = line.strip()[:120]
                    break

            matches.append({
                "table_id": t.table_id,
                "page": t.page,
                "section": t.section,
                "extraction_quality": t.extraction_quality,
                "requires_human_review": t.requires_human_review,
                "markdown_snippet": snippet,
            })

    return matches
