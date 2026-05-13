# Active Task

**最後更新**: 2026-05-13
**當前 Phase**: Phase 2 完成，準備進 Phase 3

## 已完成

### Phase 0 ✅
- MongoDB Atlas 連線、`/health` 正常、`config/` module

### Phase 1 ✅
- `PDFDocument` / `PDFChunk` models
- pdfplumber page-aware 抽取
- POST /upload, POST /{id}/ingest, GET /{id}/chunks

### Phase 2 ✅
- `AIReport` / `AIClaim` / `ClaimEvidence` models
- Claude API 整合（claude-sonnet-4-6）
- Evidence-bound prompt（每 claim 必附頁碼）
- 無 evidence → 自動降級 `insufficient_evidence`
- 投資建議詞彙偵測 → `investment_advice_detected` flag
- POST /{id}/summary, GET /{id}/summary/{report_id}

## 下一步：Phase 3 — Financial Section Classification

**目標**: 將 PDFChunk 分類到 20 個財務段落
- rule-based keyword matching（快速）
- LLM-assisted fallback（不確定時）
- 結果存入 `PDFChunk.section`
- 分類失敗不中斷 ingestion（section = "unknown"）
