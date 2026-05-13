# Long-Term Memory

**專案**: Taiwan Financial PDF Reader
**目標**: 台股 PDF 財報閱讀壓縮器，每個 AI 結論都可回溯 PDF 頁碼

## 核心原則（永久有效）

1. **Evidence First**: 每個 claim 必須有 source_pdf + page + quoted_text
2. **AI 只是壓縮層**: 摘要、分類、差異整理。不做最終投資判斷
3. **Diff > 絕對摘要**: 系統最大價值在找出變化，不只是重述
4. **禁止投資建議**: 任何形式的買/賣/持有建議都是系統失敗

## 技術棧

- Backend: FastAPI + Python 3.11+
- DB: MongoDB Atlas（雲端，免費 M0）
- LLM: Claude claude-sonnet-4-6 via Anthropic SDK
- PDF: pdfplumber（page-aware 抽取）
- Governance: ai-governance-framework（已部署）

## 已完成 Phases

- Phase 0: Repo Bootstrap（MongoDB Atlas + /health）
- Phase 1: PDF Ingestion MVP（page-aware chunks）
- Phase 2: Evidence-Bound Summary（Claude API + governance guards）
- Phase 3: Financial Section Classification（rule-based + Claude Haiku fallback）
- Phase 4: Two-PDF Diff Report（section-level，tone_only flag，evidence required）
- Phase 5: Table Extraction（pdfplumber，markdown，numeric cross-check）
- Phase 6: Taiwan Data Source（FinMind API，auxiliary only，cross-check）

## 重要設計決策

- `PDFChunk.page` 為必填欄位，不允許 null
- `AIClaim.claim_level` 沒有 evidence 時強制降級為 `insufficient_evidence`
- `AIReport.investment_advice_detected` 是 governance audit flag
- chunk max_chars = 1500，max_chunks per summary = 60
- diff: max 8 chunks per section per document 送給 Claude
- DiffItem 無頁碼來源 → 自動跳過，不存入報告
- tone_shift 強制標記 tone_only=True，禁止直接等同財務惡化
- numeric-check: 在 PDFTable 中搜尋數字 → confirmed / unreliable
- extraction_quality=low → requires_human_review=True（自動）
- ExternalDataRecord.is_auxiliary 永遠=True，禁止作為主要 evidence
- FinMind cross-check 只輸出 consistent/needs_review/not_comparable，不輸出投資判斷
