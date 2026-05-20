from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from services.classification import classify_document, manual_override, SECTIONS
from auth.jwt_bearer import JWTBearer

router = APIRouter(dependencies=[Depends(JWTBearer())])


class ManualOverrideRequest(BaseModel):
    chunk_id: str
    section: str


@router.post("/{document_id}/classify")
async def classify_doc(document_id: str, use_llm_fallback: bool = True):
    """
    對已 ingest 的文件執行段落分類。
    先用 rule-based，不確定時用 Claude Haiku fallback。
    """
    try:
        result = classify_document(document_id, use_llm_fallback=use_llm_fallback)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/chunks/section")
async def override_section(body: ManualOverrideRequest):
    """人工修正單一 chunk 的段落分類"""
    try:
        return manual_override(body.chunk_id, body.section)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sections")
async def list_sections():
    """列出所有合法的段落分類名稱"""
    return {"sections": SECTIONS, "total": len(SECTIONS)}
