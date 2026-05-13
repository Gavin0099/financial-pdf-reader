"""
PDF Ingestion Service
---------------------
上傳 PDF → 保留頁碼 → 切 chunk → 存 MongoDB

Phase 1 原則：
- 每個 chunk 必須有 page（不允許 page=None）
- 每頁獨立抽取，不跨頁合併
- 失敗時 document status 標記為 failed，不靜默吞錯
"""
import os
import uuid
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

from config.config import StorageConfig
from models.documents import PDFDocument, PDFChunk


def save_uploaded_file(file_bytes: bytes, file_name: str) -> str:
    """把上傳的 PDF 存到本地，回傳完整路徑"""
    upload_dir = Path(StorageConfig.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / file_name
    dest.write_bytes(file_bytes)
    return str(dest)


def extract_pages(file_path: str) -> list[dict]:
    """
    用 pdfplumber 逐頁抽取文字。
    回傳 list of {"page": int, "text": str}
    """
    pages = []
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages.append({"page": i, "text": text.strip()})
    return pages


def chunk_page(page_num: int, text: str, max_chars: int = 1500) -> list[dict]:
    """
    把單頁文字切成不超過 max_chars 的 chunks。
    每個 chunk 都繼承原頁碼。
    """
    if not text:
        return []

    chunks = []
    while text:
        segment = text[:max_chars]
        # 盡量在空白處斷行，避免切斷字詞
        if len(text) > max_chars:
            break_at = segment.rfind("\n")
            if break_at < max_chars * 0.5:
                break_at = max_chars
            segment = text[:break_at].strip()
            text = text[break_at:].strip()
        else:
            text = ""

        if segment:
            chunks.append({"page": page_num, "text": segment})

    return chunks


def ingest_pdf(document_id: str) -> dict:
    """
    主流程：根據 document_id 找 PDFDocument，抽取文字，存 PDFChunk。

    回傳 ingestion summary。
    """
    doc = PDFDocument.objects(document_id=document_id).first()
    if not doc:
        raise ValueError(f"Document not found: {document_id}")

    if not os.path.exists(doc.file_path):
        doc.status = "failed"
        doc.save()
        raise FileNotFoundError(f"PDF file missing: {doc.file_path}")

    doc.status = "ingesting"
    doc.save()

    try:
        pages = extract_pages(doc.file_path)
        doc.total_pages = len(pages)

        chunks_created = 0
        for page_data in pages:
            page_num = page_data["page"]
            raw_text = page_data["text"]

            for chunk_data in chunk_page(page_num, raw_text):
                chunk = PDFChunk(
                    chunk_id=str(uuid.uuid4()),
                    document_id=document_id,
                    stock_id=doc.stock_id,
                    period=doc.period,
                    page=chunk_data["page"],
                    text=chunk_data["text"],
                    char_count=len(chunk_data["text"]),
                )
                chunk.save()
                chunks_created += 1

        doc.status = "completed"
        doc.ingested_at = datetime.now(timezone.utc)
        doc.save()

        return {
            "document_id": document_id,
            "pages_extracted": len(pages),
            "chunks_created": chunks_created,
            "status": "completed",
        }

    except Exception as e:
        doc.status = "failed"
        doc.save()
        raise RuntimeError(f"Ingestion failed: {e}") from e
