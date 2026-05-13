# PLAN.md — Taiwan Financial PDF Reader

> **專案類型**: PDF Analysis Tool
> **技術棧**: Python / FastAPI / MongoDB Atlas / Claude API / pdfplumber
> **複雜度**: L2
> **Owner**: User
> **最後更新**: 2026-05-13
> **Freshness**: Sprint (7d)
> **Planning Window**: 2026-05 ~ 2026-08

---

## 專案目標

以 FastAPI 為基底，建立一套「台股 PDF 財報閱讀壓縮器」，協助使用者快速讀懂台股財報。

**Bounded Context**:
- 台股財報 PDF 上傳、文字/表格抽取（含頁碼）
- 產生有來源依據的財報摘要（每點附頁碼）
- 比較兩份財報的差異（diff report）
- 每個 AI 判斷都可回溯 PDF 頁碼與原文

**不負責**:
- 不做自動選股、買賣建議、股價預測
- 不做投資組合推薦
- 不做即時交易訊號
- 不把 AI 推論包裝成事實

---

## 階段總覽

```
├─ [✅] Phase 0: Repo Bootstrap & Backend 跑起來
├─ [✅] Phase 1: PDF Ingestion MVP（page-aware）
├─ [✅] Phase 2: Evidence-Bound Summary
├─ [✅] Phase 3: Financial Section Classification
├─ [✅] Phase 4: Two-PDF Diff Report
├─ [✅] Phase 5: Table Extraction & Numeric Cross-Check
├─ [✅] Phase 6: Taiwan Data Source Integration
├─ [✅] Phase 7: Governance Layer（R1-R7）
└─ [⏳] Phase 8: Tests + Cleanup（規劃中）
```

**當前 Phase**: **Phase 7 完成 — 準備 Phase 8**

---

## Phase 0: Repo Bootstrap ✅

**目標**: Backend `/health` 正常回應，MongoDB Atlas 連線成功

**完成項目**:
- MongoDB Atlas 免費叢集
- `.env`（MONGODB_URL + ANTHROPIC_API_KEY）
- `config/` module
- FastAPI `/health` → `{"status": "ok"}`

---

## Phase 1: PDF Ingestion MVP ✅

**目標**: 上傳一份台股財報 PDF，每個 chunk 都保留頁碼

**完成項目**:
- `PDFDocument` / `PDFChunk` models（mongoengine）
- pdfplumber page-aware 抽取
- `POST /api/v1/documents/upload`
- `POST /api/v1/documents/{id}/ingest`
- `GET /api/v1/documents/{id}/chunks`

---

## Phase 2: Evidence-Bound Summary ✅

**目標**: 產出單份 PDF 的財報摘要，每點都附來源頁碼

**完成項目**:
- `AIReport` / `AIClaim` / `ClaimEvidence` models
- Claude claude-sonnet-4-6 API 整合
- Evidence-bound prompt（每 claim 必附頁碼）
- 無 evidence → 自動降級 `insufficient_evidence`
- 投資建議詞彙偵測 → `investment_advice_detected` flag
- `POST /{id}/summary`, `GET /{id}/summary/{report_id}`

---

## Phase 3: Financial Section Classification ✅

**目標**: 將 PDF chunks 自動分類（20 個財務段落）

**完成項目**:
- 20 個財務段落 keyword mapping（rule-based）
- Claude Haiku LLM fallback
- ingest 時自動 rule-based 分類
- `POST /{id}/classify`, `PATCH /chunks/section`, `GET /sections`

---

## Phase 4: Two-PDF Diff Report ✅

**目標**: 比較兩份財報，找出新增/消失說法與語氣變化

**完成項目**:
- `DiffReport` / `DiffItem` / `DiffEvidence` models
- Section-level comparison（6 種 diff_type）
- tone_shift 強制標記 tone_only=True（R6）
- `POST /api/v1/reports/diff`, `GET /api/v1/reports/diff/{id}`

---

## Phase 5: Table Extraction ✅

**目標**: 抽出財務表格，對 AI summary 中的數字做 evidence check

**完成項目**:
- `PDFTable` model（markdown、品質評估）
- pdfplumber 逐頁表格抽取
- `POST /{id}/extract-tables`
- `GET /{id}/tables`
- `GET /{id}/numeric-check?number=12.3`

---

## Phase 6: Taiwan Data Source Integration ✅

**目標**: 補上結構化台股資料（月營收、財務比率）作為輔助基準

**完成項目**:
- `ExternalDataRecord` model（is_auxiliary 永遠=True）
- FinMind API 整合（月營收 + 財務報表）
- cross-check → consistent / needs_review / not_comparable
- `POST /{stock_id}/fetch-revenue`, `POST /{stock_id}/fetch-financials`
- `GET /{stock_id}/crosscheck`, `GET /{stock_id}/external-data`

---

## Phase 7: Governance Layer ✅

**目標**: 導入 evidence discipline，每個 claim 都有 claim_level 與 evidence 狀態

**完成項目**:
- `core/governance.py`：GovernanceViolation / GovernanceAuditResult + R1-R7 rule checkers
- `services/audit/`：run_audit() 執行稽核
- `GET /api/v1/documents/{id}/audit`
- `AGENTS.md` 部署至根目錄，修復 memory + PLAN.md 更新遺漏問題

**Claim Levels**: `observed_fact` / `derived_metric` / `interpretation` / `hypothesis` / `insufficient_evidence`

---

## Phase 8: Tests + Cleanup（規劃中 ⏳）

**目標**: 補齊測試、清理未使用依賴

**候選任務**:
- [ ] `tests/` — R1-R7 unit tests（pytest + mongomock，已在 requirements.txt）
- [ ] `requirements.txt` 清理（移除未使用：chromadb、langchain、sentence-transformers 等）
- [ ] DiffReport R6 audit endpoint（`GET /api/v1/reports/diff/{id}/audit`）

**Gate 條件**:
- [ ] `pytest tests/` 全綠
- [ ] `requirements.txt` 只保留實際使用的依賴

---

## AI 協作規則

**AI 在實作任何功能前，必須確認**:
1. 這項任務在當前 Phase 的範圍內嗎？
2. 是否在「不負責」清單中？
3. 每個 AI claim 是否有 evidence？

**禁止**:
- 產生無來源的財報結論
- 輸出投資建議（任何形式）
- 把推論寫成事實
- 自行補數字

---

## 變更歷史

| 日期 | 變更內容 |
|------|---------|
| 2026-05-13 | 專案啟動，Phase 0~7 完成，PLAN.md 補齊至真實進度 |
