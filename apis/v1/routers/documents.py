import uuid
import re
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from pydantic import BaseModel

from models.documents import PDFDocument, PDFChunk
from services.pdf_ingestion import ingest_pdf, save_uploaded_file
from auth.jwt_bearer import JWTBearer

router = APIRouter(dependencies=[Depends(JWTBearer())])


def _infer_document_meta(file_name: str, stock_id: str, company_name: str, period: str) -> tuple[str, str, str]:
    """
    將 upload 表單欄位改為選填：
    - 有填就用使用者值
    - 未填則優先從檔名推斷
    - 都推不到則使用保守預設，避免阻塞上傳流程
    """
    stem = (file_name or "").rsplit(".", 1)[0]

    inferred_stock = stock_id.strip() if stock_id else ""
    if not inferred_stock:
        m_stock = re.search(r"\b(\d{4})\b", stem)
        inferred_stock = m_stock.group(1) if m_stock else "UNKNOWN"

    inferred_period = period.strip() if period else ""
    if not inferred_period:
        m_period = re.search(r"(20\d{2}\s*[Qq][1-4])", stem)
        inferred_period = m_period.group(1).replace(" ", "").upper() if m_period else "UNKNOWN"

    inferred_company = company_name.strip() if company_name else ""
    if not inferred_company:
        # 嘗試移除常見 token 後取剩餘片段
        candidate = re.sub(r"(20\d{2}\s*[Qq][1-4])", "", stem)
        candidate = re.sub(r"\b\d{4}\b", "", candidate)
        candidate = re.sub(r"[_\-\s]+", " ", candidate).strip()
        inferred_company = candidate or "未命名公司"

    return inferred_stock, inferred_company, inferred_period


# ── Request / Response schemas ────────────────────────────────────────────────

class UploadResponse(BaseModel):
    document_id: str
    status: str
    message: str


class IngestResponse(BaseModel):
    document_id: str
    pages_extracted: int
    chunks_created: int
    status: str


class ChunkOut(BaseModel):
    chunk_id: str
    page: int
    section: str
    text: str
    char_count: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    stock_id: str = Form(""),
    company_name: str = Form(""),
    period: str = Form(""),
    document_type: str = Form("quarterly_report"),
    industry_type: str = Form("general"),
):
    """
    上傳台股財報 PDF。
    儲存到本地後建立 PDFDocument 記錄，等待 /ingest 呼叫。
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只接受 PDF 檔案")

    document_id = str(uuid.uuid4())
    file_bytes = await file.read()
    safe_name = f"{document_id}_{file.filename}"
    file_path = save_uploaded_file(file_bytes, safe_name)
    final_stock_id, final_company_name, final_period = _infer_document_meta(
        file.filename or "",
        stock_id,
        company_name,
        period,
    )

    doc = PDFDocument(
        document_id=document_id,
        stock_id=final_stock_id,
        company_name=final_company_name,
        period=final_period,
        document_type=document_type,
        industry_type=industry_type,
        file_name=file.filename,
        file_path=file_path,
        file_size_bytes=len(file_bytes),
    )
    doc.save()

    return UploadResponse(
        document_id=document_id,
        status="uploaded",
        message=f"PDF 已上傳，共 {len(file_bytes)} bytes。呼叫 /ingest 開始解析。",
    )


@router.post("/{document_id}/ingest", response_model=IngestResponse)
async def ingest_document(document_id: str):
    """
    對已上傳的 PDF 執行文字抽取，產生帶頁碼的 chunks。
    """
    try:
        result = ingest_pdf(document_id)
        return IngestResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{document_id}/chunks", response_model=list[ChunkOut])
async def get_chunks(document_id: str, page: int | None = None):
    """
    查詢 document 的 chunks。可加 ?page=12 只看特定頁。
    """
    query = PDFChunk.objects(document_id=document_id)
    if page is not None:
        query = query.filter(page=page)

    chunks = query.order_by("page")
    if not chunks:
        raise HTTPException(status_code=404, detail="找不到 chunks，請先執行 /ingest")

    return [
        ChunkOut(
            chunk_id=c.chunk_id,
            page=c.page,
            section=c.section,
            text=c.text,
            char_count=c.char_count,
        )
        for c in chunks
    ]


@router.get("/{document_id}", response_model=dict)
async def get_document(document_id: str):
    """取得 document 基本資訊"""
    doc = PDFDocument.objects(document_id=document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "document_id": doc.document_id,
        "stock_id": doc.stock_id,
        "company_name": doc.company_name,
        "period": doc.period,
        "document_type": doc.document_type,
        "file_name": doc.file_name,
        "total_pages": doc.total_pages,
        "status": doc.status,
        "created_at": str(doc.created_at),
    }
