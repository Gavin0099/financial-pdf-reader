# Active Task

**最後更新**: 2026-05-13
**當前 Phase**: Phase 5 完成，準備進 Phase 6

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

### Phase 3 ✅
- 20 個財務段落的 keyword mapping（rule-based）
- Claude Haiku LLM fallback（rule 無法判斷時）
- ingest 時自動 rule-based 分類（不呼叫 LLM，保持速度）
- POST /{id}/classify（可單獨觸發，支援 LLM fallback）
- PATCH /chunks/section（人工修正）
- GET /sections（列出合法分類）

### Phase 4 ✅
- `DiffReport` / `DiffItem` / `DiffEvidence` models
- Section-level comparison（共同段落 + only_current + only_previous）
- 6 種 diff_type：new_language / removed_language / tone_shift / numeric_change / new_risk / removed_risk
- Governance: tone_shift 標記 tone_only=True，禁止等同財務惡化
- 每個 diff item 至少一個來源頁碼，無來源自動跳過
- POST /api/v1/reports/diff，GET /api/v1/reports/diff/{id}

### Phase 5 ✅
- `PDFTable` model（帶頁碼、section、markdown、品質評估）
- pdfplumber 逐頁表格抽取，轉 markdown
- extraction_quality：high / medium / low / failed
- 品質 low → requires_human_review=True 自動標記
- POST /{id}/extract-tables（抽取表格）
- GET /{id}/tables（查詢，支援 ?page / ?section 過濾）
- GET /{id}/numeric-check?number=12.3（數字 cross-check，回傳 confirmed/unreliable）

## 下一步：Phase 6 — Taiwan Data Source Integration

**目標**: 補上結構化台股資料作為輔助基準
- 評估合法資料源（公開資訊觀測站 / FinMind）
- 月營收、基本財務比率
- 與 PDF 報告做 cross-check
- 外部資料來源必須標示 source，不混淆 PDF 原文
