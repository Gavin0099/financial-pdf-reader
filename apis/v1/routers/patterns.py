from fastapi import APIRouter, HTTPException

from services.reasoning_patterns import run_pattern_analysis

router = APIRouter()


@router.post("/{document_id}/patterns/run")
async def run_patterns(document_id: str):
    """
    執行 6 個財報檢查模式，基於現有 claims 屬性掃描，不呼叫 Claude API。
    輸出永遠為 interpretation 層級，不進 Key Findings。
    """
    try:
        return run_pattern_analysis(document_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
