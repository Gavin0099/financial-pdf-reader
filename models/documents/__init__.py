from mongoengine import (
    Document,
    StringField,
    DateTimeField,
    IntField,
    FloatField,
    BooleanField,
    ListField,
    EmbeddedDocument,
    EmbeddedDocumentField,
)
from datetime import datetime, timezone


class PDFDocument(Document):
    """一份台股財報 PDF"""
    document_id = StringField(required=True, unique=True)
    stock_id = StringField(required=True)          # e.g. "2330"
    company_name = StringField(required=True)      # e.g. "台積電"
    period = StringField(required=True)            # e.g. "2026Q1"
    document_type = StringField(
        required=True,
        choices=["quarterly_report", "annual_report", "earnings_release"],
        default="quarterly_report",
    )
    file_name = StringField(required=True)
    file_path = StringField(required=True)         # 本地儲存路徑
    file_size_bytes = IntField(default=0)
    total_pages = IntField(default=0)
    status = StringField(
        choices=["uploaded", "ingesting", "completed", "failed"],
        default="uploaded",
    )
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))
    ingested_at = DateTimeField()

    meta = {"collection": "pdf_documents"}


class PDFChunk(Document):
    """PDF 中的一個文字 chunk，必須帶頁碼"""
    chunk_id = StringField(required=True, unique=True)
    document_id = StringField(required=True)       # 對應 PDFDocument.document_id
    stock_id = StringField(required=True)
    period = StringField(required=True)
    page = IntField(required=True)                 # 1-based 頁碼，核心欄位
    section = StringField(default="unknown")       # Phase 3 分類後填入
    content_type = StringField(
        choices=["text", "table"],
        default="text",
    )
    text = StringField(required=True)
    char_count = IntField(default=0)
    confidence = StringField(
        choices=["high", "medium", "low"],
        default="medium",
    )
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    meta = {
        "collection": "pdf_chunks",
        "indexes": ["document_id", "page", "stock_id", "period"],
    }
