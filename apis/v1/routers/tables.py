from fastapi import APIRouter, HTTPException, Depends
from models.documents import PDFTable
from services.text_extraction import extract_tables, find_numeric_evidence
from auth.jwt_bearer import JWTBearer

router = APIRouter(dependencies=[Depends(JWTBearer())])


@router.post("/{document_id}/extract-tables")
async def extract_document_tables(document_id: str):
    """
    抽取文件中所有表格，轉成 markdown 格式存入 PDFTable。
    品質差的表格自動標記 requires_human_review=True。
    """
    try:
        result = extract_tables(document_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{document_id}/tables")
async def get_tables(document_id: str, page: int | None = None, section: str | None = None):
    """
    查詢文件的表格。可加 ?page=18 或 ?section=存貨 過濾。
    """
    query = PDFTable.objects(document_id=document_id)
    if page is not None:
        query = query.filter(page=page)
    if section:
        query = query.filter(section=section)

    tables = query.order_by("page", "table_index")
    if not tables:
        raise HTTPException(status_code=404, detail="No tables found. Run /extract-tables first.")

    return [
        {
            "table_id": t.table_id,
            "page": t.page,
            "section": t.section,
            "table_index": t.table_index,
            "row_count": t.row_count,
            "col_count": t.col_count,
            "extraction_quality": t.extraction_quality,
            "requires_human_review": t.requires_human_review,
            "table_markdown": t.table_markdown,
        }
        for t in tables
    ]


@router.get("/{document_id}/numeric-check")
async def numeric_cross_check(document_id: str, number: str):
    """
    在文件表格中搜尋特定數字，回傳可能的 evidence 來源。
    用於驗證 AI summary 中數字 claim 的可信度。

    例如：?number=12.3 或 ?number=1,234,567
    """
    if not number:
        raise HTTPException(status_code=400, detail="number 參數不可為空")

    matches = find_numeric_evidence(document_id, number)

    return {
        "number_queried": number,
        "matches_found": len(matches),
        "evidence": matches,
        "verdict": (
            "confirmed" if matches else "unreliable"
        ),
        "note": (
            "數字在表格中找到來源" if matches
            else "無法在已抽取表格中確認此數字，請人工核實"
        ),
    }
