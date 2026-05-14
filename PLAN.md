# PLAN.md — Taiwan Financial PDF Reader

> **專案類型**: PDF Analysis Tool
> **技術棧**: Python / FastAPI / MongoDB Atlas / Claude API / pdfplumber
> **複雜度**: L2
> **Owner**: User
> **最後更新**: 2026-05-14
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
├─ [✅] Phase 8: Tests + Cleanup
├─ [✅] Phase 9B: UI Redesign（Key Findings grid, tabs, collapsible evidence）
├─ [✅] Phase 9C: Industry Type Field + CDMO/半導體 Prompt Supplement
├─ [✅] Phase 9D: Disclosure Coverage Engine（14 項法定揭露稽核）
└─ [✅] Phase 9E: Financial Review Pattern Registry（6 個財報檢查模式）
```

**當前 Phase**: **Phase 9E 完成 — 三條 pipeline 齊備**

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

## Phase 8: Tests + Cleanup ✅

**目標**: 補齊測試、清理未使用依賴

**完成項目**:
- [x] `tests/test_governance.py` — R1-R7 unit tests，44 tests，44 passed
- [x] `requirements.txt` 清理 — 移除 chromadb、langchain\*、sentence-transformers、huggingface-hub、beanie、motor；新增 python-dotenv（實際使用但遺漏）

**Gate 條件**:
- [x] `pytest tests/` 全綠（44 passed）
- [x] `requirements.txt` 只保留實際使用的依賴

---

## Phase 9B: UI Redesign ✅

**目標**: 重建 HTML UI — Key Findings grid、tabs、collapsible evidence、claim-level 色碼（中性）

**完成項目**:
- Key Findings grid（tier_a + observed_fact/derived_metric only）
- 各 section tabs（核心財務 / 會計調整 / 流動性 / 風險 / 不足）
- Collapsible evidence per claim
- Claim-level badge 改為中性色系（不用情緒色）
- 一次性項目 badge 改為中性灰（非橙色）

---

## Phase 9C: Industry Type + Prompt Supplement ✅

**目標**: 上傳時可標記產業別（一般/CDMO/半導體），依產業注入 extraction hint

**完成項目**:
- `PDFDocument.industry_type` field（choices: general/cdmo/semiconductor）
- 上傳表單新增產業別下拉選單
- `INDUSTRY_SUPPLEMENTS` dict（general/cdmo/semiconductor）
- CDMO supplement：Backlog、LOI、Milestone payment 提取提示
- **Governance fix**: supplement 改為 evidence-first 規則，非 authority grant
  - 有頁碼佐證 → claim_level=observed_fact，materiality 獨立判斷
  - 僅描述性提及 → interpretation + tier_b + requires_human_review=True
  - PDF 中不存在 → 完全不產生 claim
- Executive Summary prompt 新增禁用因果歸因語言（"主要受⋯驅動"）

---

## Phase 9D: Disclosure Coverage Engine ✅

**目標**: 獨立第二條 pipeline，系統化檢查 14 項法定揭露是否出現於財報

**完成項目**:
- `DISCLOSURE_REGISTRY`：14 項（台灣第 12、17 條 + IFRS）
- `STATUS_CHOICES`：found / found_incomplete / not_found / ambiguous / not_applicable
- `models/disclosures/`：DisclosureCoverageItem + DisclosureCoverageReport
- `services/disclosure_coverage/`：check_disclosure_coverage()
  - 使用 claude-haiku-4-5（成本約為 Sonnet 1/10）
  - Claude 漏回的 key 自動填補為 ambiguous（guarantee 14 keys）
- `apis/v1/routers/disclosures.py`：POST /{id}/disclosure-coverage
- UI Step 4：14 項 coverage matrix 顯示
- `tests/test_disclosure_coverage.py`：10 tests 全通過

**Guard**:
- 只判斷「揭露是否存在」，不代表財報品質或投資建議
- not_applicable 不計入 not_found_count

---

## Phase 9E: Financial Review Pattern Registry ✅

**目標**: 第三條 pipeline，6 個財報警示 pattern，純 Python claim 屬性掃描，不呼叫 Claude

**完成項目**:
- `reasoning_patterns/schemas.py`：ClaimPropertyFilter / PatternDefinition / TriggerResult
- 6 個 pattern（獨立檔案）：
  1. `operating_vs_net_income`：營業損益與稅後損益方向差異
  2. `non_recurring_eps`：非常態項目影響 EPS
  3. `fx_driven_profit`：匯兌損益影響損益
  4. `expense_ratio_offset`：獲利趨勢與營收趨勢不一致
  5. `debt_maturity_risk`：短期債務/可轉債到期壓力
  6. `customer_concentration`：客戶集中度風險
- `services/reasoning_patterns/`：evidence_resolver + engine + 主服務
- `models/patterns/`：PatternRunResult + PatternRunReport
- `apis/v1/routers/patterns.py`：POST /{id}/patterns/run
- UI Step 5：pattern 結果 + source claims accordion
- `tests/test_reasoning_patterns.py`：14 tests 全通過

**Guard（hardcoded）**:
- CLAIM_LEVEL = "interpretation"（永遠不升級）
- REQUIRES_REVIEW = True（永遠需人工確認）
- IN_KEY_FINDINGS = False（不進 Key Findings）
- contaminated claims 排除於 pattern 分析
- FX 損益不自動標為一次性

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
| 2026-05-13 | Phase 8: tests/test_governance.py 44 tests 全綠 |
| 2026-05-13 | Phase 8 ✅: requirements.txt 清理，移除 chromadb/langchain 等 8 個未使用套件 |
| 2026-05-14 | Phase 9B ✅: UI 重設計 — Key Findings grid、tabs、中性色碼 |
| 2026-05-14 | Phase 9C ✅: industry_type field + CDMO/半導體 prompt supplement（evidence-first governance fix）|
| 2026-05-14 | Phase 9D ✅: Disclosure Coverage Engine — 14 項法定揭露，10 tests 通過 |
| 2026-05-14 | Phase 9E ✅: Pattern Registry — 6 patterns，純 Python 不呼叫 Claude，14 tests 通過 |