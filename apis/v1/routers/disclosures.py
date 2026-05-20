from fastapi import APIRouter, HTTPException, Depends

from services.disclosure_coverage import check_disclosure_coverage
from auth.jwt_bearer import JWTBearer

router = APIRouter(dependencies=[Depends(JWTBearer())])


@router.post("/{document_id}/disclosure-coverage")
async def create_disclosure_coverage(document_id: str):
    """
    對已 ingest 的 PDF 執行 14 項法定揭露完整性稽核。
    只輸出 found / found_incomplete / not_found / ambiguous / not_applicable。
    不產生投資結論。
    """
    try:
        return check_disclosure_coverage(document_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
