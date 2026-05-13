from fastapi import APIRouter, HTTPException
from services.audit import run_audit

router = APIRouter()


@router.get("/{document_id}/audit")
async def audit_document(document_id: str, report_id: str | None = None):
    """
    對已產生的 AIReport 執行 R1-R7 governance 稽核。

    - report_id: 指定特定報告（可選，省略時取最新一份）
    - 回傳 violations（errors）和 warnings 清單
    - passed=True 代表 0 violations（warnings 不影響通過）

    R1: 每個 claim 必須有 evidence
    R2: 數字 claim 必須有 quoted_text 來源
    R3: 無 evidence 的 claim_level 必須是 hypothesis / insufficient_evidence
    R4: 不允許投資建議
    R5: evidence document_id 必須與當前文件一致
    R7: 不允許用單季資料推論長期趨勢
    """
    try:
        result = run_audit(document_id, report_id=report_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
