# Workflow

## API 使用流程（目前可用）

```
1. POST /api/v1/documents/upload
   Body: form-data { file, stock_id, company_name, period, document_type }
   → 回傳 document_id

2. POST /api/v1/documents/{document_id}/ingest
   → 抽取文字，產生帶頁碼的 chunks
   → 回傳 pages_extracted, chunks_created

3. POST /api/v1/documents/{document_id}/summary
   → 呼叫 Claude API，產生 evidence-bound 摘要
   → 回傳 claims（每條附 page + quoted_text）

4. GET /api/v1/documents/{document_id}/chunks?page=12
   → 查詢特定頁碼的 chunks

5. GET /api/v1/documents/{document_id}/summary/{report_id}
   → 取回已產生的報告
```

## 啟動指令

```bash
cd /e/BackUp/Git_EE/financial-pdf-reader
python -m uvicorn app:app --host 0.0.0.0 --port 8080 --reload
# Swagger UI: http://localhost:8080/docs
```

## Governance 工具

```bash
python governance_tools/memory_janitor.py --check
python governance_tools/plan_freshness.py
```

## Git Flow

```bash
git add <files>
git commit -m "feat: ..."
git push origin main
```
