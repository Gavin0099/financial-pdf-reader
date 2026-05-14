# Workflow

**最後更新**: 2026-05-14（Phase 10D 完成）

## 完整 API 使用流程

```
=== 單份 PDF 分析 ===

1. POST /api/v1/documents/upload
   Body: form-data { file, stock_id, company_name, period, document_type }
   → 回傳 document_id

2. POST /api/v1/documents/{document_id}/ingest
   → 抽取文字（page-aware）+ rule-based section 分類
   → 回傳 pages_extracted, chunks_created

3. POST /api/v1/documents/{document_id}/extract-tables  ← Phase 5
   → 抽取所有表格，轉 markdown
   → 回傳 tables_created, pages_with_tables

4. POST /api/v1/documents/{document_id}/summary  ← Phase 2
   → 呼叫 Claude，產生 evidence-bound 摘要
   → 每個 claim 附 page + quoted_text

5. GET /api/v1/documents/{document_id}/numeric-check?number=12.3  ← Phase 5
   → 在表格中搜尋數字 → confirmed / unreliable

=== 輔助查詢 ===

GET /api/v1/documents/{document_id}/chunks?page=12
   → 查詢特定頁的 chunks

GET /api/v1/documents/{document_id}/chunks?section=存貨
   → 查詢特定段落的 chunks（Phase 3 分類後有效）

POST /api/v1/documents/{document_id}/classify?use_llm_fallback=true  ← Phase 3
   → 用 Claude Haiku 重新分類（比 ingest 時精準）
   → 回傳 section_distribution

PATCH /api/v1/documents/chunks/section  ← Phase 3
   Body: { chunk_id, section }
   → 人工修正 chunk 分類

GET /api/v1/documents/{document_id}/tables?page=18&section=存貨  ← Phase 5
   → 查詢表格（可過濾頁碼 / 段落）

=== 兩份 PDF Diff ===

POST /api/v1/reports/diff  ← Phase 4
   Body: { current_document_id, previous_document_id }
   → 比較兩份財報，找出差異（需同公司）
   → 回傳 diff items（每條有頁碼、presence、tone_only）

GET /api/v1/reports/diff/{diff_report_id}  ← Phase 4
   → 取回已產生的 diff report

=== 外部資料（輔助，非主要 evidence）===

POST /api/v1/stocks/{stock_id}/fetch-revenue?period=2026Q1  ← Phase 6
   → 從 FinMind 抓月營收（當季三個月）

POST /api/v1/stocks/{stock_id}/fetch-financials?period=2026Q1  ← Phase 6
   → 從 FinMind 抓財務報表科目

GET /api/v1/stocks/{stock_id}/crosscheck?period=2026Q1&metric=revenue&pdf_value=12345  ← Phase 6
   → PDF 數字 vs 外部資料 → consistent / needs_review / not_comparable

GET /api/v1/stocks/{stock_id}/external-data  ← Phase 6
   → 列出已快取的外部資料記錄

=== Governance 稽核（Phase 7）===

GET /api/v1/documents/{document_id}/audit  ← Phase 7
   → 對最新 AIReport 執行 R1-R7 稽核
   → 回傳 violations（errors）+ warnings + passed（bool）+ summary

GET /api/v1/documents/{document_id}/audit?report_id=<uuid>  ← Phase 7
   → 對指定 report_id 執行稽核

=== 法定揭露稽核（Phase 9D）===

POST /api/v1/documents/{document_id}/disclosure-coverage  ← Phase 9D
   → 呼叫 claude-haiku-4-5，檢查 14 項法定揭露
   → 回傳 items（14 條）+ found_count + not_found_count + not_applicable_count

=== 財報檢查模式（Phase 9E）===

POST /api/v1/documents/{document_id}/patterns/run  ← Phase 9E
   → 純 Python，不呼叫 Claude，掃描現有 claims 屬性
   → 回傳 results（6 條）+ triggered_count + insufficient_count
   → 每個 result 含 source_claims + missing_evidence_keys
```

## 建議標準操作流程（SOP）

```
1. upload（含 industry_type）→ 2. ingest → 3. extract-tables → 4. summary
   ↓
5. 若需精準分類：classify（LLM）
6. 若需比較兩季：diff
7. 若需外部驗證：fetch-financials → crosscheck
8. 若需 governance 稽核：audit
9. 若需法定揭露稽核：disclosure-coverage（Haiku，~10-20s）
10. 若需財報警示 pattern：patterns/run（純 Python，<1s）
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
git commit -m "feat/fix: ..."
git push origin main
```
