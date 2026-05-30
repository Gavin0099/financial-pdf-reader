# PLAN.md — Taiwan Financial PDF Reader

> **專案類型**: PDF Analysis Tool
> **技術棧**: Python / FastAPI / MongoDB Atlas / Claude API / pdfplumber
> **複雜度**: L2
> **Owner**: User
> **最後更新**: 2026-05-30
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
├─ [✅] Phase 0:  Repo Bootstrap & Backend 跑起來
├─ [✅] Phase 1:  PDF Ingestion MVP（page-aware）
├─ [✅] Phase 2:  Evidence-Bound Summary
├─ [✅] Phase 3:  Financial Section Classification
├─ [✅] Phase 4:  Two-PDF Diff Report
├─ [✅] Phase 5:  Table Extraction & Numeric Cross-Check
├─ [✅] Phase 6:  Taiwan Data Source Integration
├─ [✅] Phase 7:  Governance Layer（R1-R7）
├─ [✅] Phase 8:  Tests + Cleanup
├─ [✅] Phase 9B: UI Redesign（Key Findings grid, tabs, collapsible evidence）
├─ [✅] Phase 9C: Industry Type Field + CDMO/半導體 Prompt Supplement
├─ [✅] Phase 9D: Disclosure Coverage Engine（14 項法定揭露稽核）
├─ [✅] Phase 9E: Financial Review Pattern Registry（6 個財報檢查模式）
├─ [✅] Phase 9F: Pattern Trigger Precision + Claim Discipline
├─ [✅] Phase 10A: Interpretation Isolation UI
├─ [✅] Phase 10B: Source Type Layer + Narrative Density
├─ [✅] Phase 10C: Rhetorical Risk Classifier
├─ [✅] Phase 10D: Forward-Looking Implication Guard
├─ [✅] Phase 10E: Quotation Layer（Attribution Prefix）
├─ [✅] Phase 11A: Output Completeness Rules（OC-1/OC-2）
├─ [✅] Phase 2A:  UI Semantic Color System
├─ [✅] Phase 2B:  Cognitive Workflow UI（Primary Narrative + Review Panel）
├─ [✅] Phase 2C:  Narrative Explainability + Review Severity L1-L4
├─ [✅] Phase 2D:  Materiality Engine
├─ [✅] Auth:      JWT protection 全路由覆蓋
├─ [✅] Audit:     DiffReport R6 audit endpoint
├─ [✅] Governance: ai-governance-framework sync + adopt baseline
└─ [🚧] Phase 3A: Multi-Period Trend（進行中）
```

**當前 Phase**: **Phase 3A — Multi-Period KPI Trend**

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
- `AGENTS.md` 部署至根目錄

**Claim Levels**: `observed_fact` / `derived_metric` / `interpretation` / `hypothesis` / `insufficient_evidence`

---

## Phase 8: Tests + Cleanup ✅

**目標**: 補齊測試、清理未使用依賴

**完成項目**:
- `tests/test_governance.py` — R1-R7 unit tests，44 tests passed
- `requirements.txt` 清理 — 移除 chromadb、langchain* 等 8 個未使用套件

---

## Phase 9B: UI Redesign ✅

**目標**: 重建 HTML UI — Key Findings grid、tabs、collapsible evidence、claim-level 色碼（中性）

**完成項目**:
- Key Findings grid（tier_a + observed_fact/derived_metric only，上限 4 條）
- 各 section tabs（核心財務 / 會計調整 / 流動性 / 風險 / Pipeline / 不足）
- Collapsible evidence per claim
- Claim-level badge 中性色系；一次性項目 badge 中性灰

---

## Phase 9C: Industry Type + Prompt Supplement ✅

**目標**: 上傳時可標記產業別（一般/CDMO/半導體），依產業注入 extraction hint

**完成項目**:
- `PDFDocument.industry_type` field（choices: general/cdmo/semiconductor）
- 上傳表單新增產業別下拉選單
- `INDUSTRY_SUPPLEMENTS` dict — extraction hint（非 authority grant）
- CDMO supplement：Backlog、LOI、Milestone payment
- Evidence-first governance：有頁碼 → observed_fact；僅描述 → interpretation + review
- Executive Summary 禁用因果歸因語言

---

## Phase 9D: Disclosure Coverage Engine ✅

**目標**: 獨立第二條 pipeline，系統化檢查 14 項法定揭露是否出現於財報

**完成項目**:
- `DISCLOSURE_REGISTRY`：14 項（台灣第 12、17 條 + IFRS）
- `STATUS_CHOICES`：found / found_incomplete / not_found / ambiguous / not_applicable
- `models/disclosures/`、`services/disclosure_coverage/`、`apis/v1/routers/disclosures.py`
- claude-haiku-4-5（低成本）；缺失 key 自動填補 ambiguous
- UI Step 4：14 項 coverage matrix
- `tests/test_disclosure_coverage.py`：10 tests 通過

---

## Phase 9E: Financial Review Pattern Registry ✅

**目標**: 第三條 pipeline，6 個財報警示 pattern，純 Python claim 屬性掃描，不呼叫 Claude

**完成項目**:
- `reasoning_patterns/schemas.py`：ClaimPropertyFilter / PatternDefinition / TriggerResult
- 6 個 pattern：operating_vs_net_income / non_recurring_eps / fx_driven_profit /
  expense_ratio_offset / debt_maturity_risk / customer_concentration
- `services/reasoning_patterns/`：evidence_resolver + engine + run_pattern_analysis()
- `models/patterns/`：PatternRunResult + PatternRunReport
- `apis/v1/routers/patterns.py`：POST /{id}/patterns/run
- UI Step 5：pattern 結果 + source claims accordion
- `tests/test_reasoning_patterns.py`：14 tests 通過

**Guards（hardcoded）**: CLAIM_LEVEL=interpretation、REQUIRES_REVIEW=True、IN_KEY_FINDINGS=False

---

## Phase 9F: Pattern Trigger Precision ✅

**目標**: 降低 pattern 誤觸發率，收緊 claim discipline

**完成項目**:
- `non_recurring_eps`：加 `_AMOUNT_KEYWORDS` filter（bare qualitative → insufficient_evidence）
- `fx_driven_profit`：加量化金額第二層 filter；排除 bare "元" 避免「美元」誤觸發
- `prompts/__init__.py`：observed_fact 禁止 AI 自算比率；derived_metric 必填公式
- Key Findings 上限降為 4 條（原 6），超出顯示「+N 條請見分頁」
- `tests/test_reasoning_patterns.py`：共 16 tests 通過

---

## Phase 10A: Interpretation Isolation UI ✅

**目標**: UI 層隔離 AI 詮釋與直接事實，防止詮釋被當成事實閱讀

**完成項目**:
- interpretation/hypothesis 預設折疊（`.interp-section`）
- `EVIDENCE_DISTANCE` 常數 + `.ed-label` badge（5 個層級）
- `renderClaim()` 加 ed-label；interpretation 前綴「可能需要檢查：」
- `.interp-disclaimer` 警告橫幅；`toggleInterp()` 展開收起

---

## Phase 10B: Source Type Layer + Narrative Density ✅

**目標**: 為每個 claim 標記資訊來源類型（財報數字/運營事實/戰略敘事/管理展望），並量測敘事密度

**完成項目**:
- `AIClaim`：加 `source_type`（4 choices）+ `forward_looking: bool`
- `AIReport`：加 `narrative_density_score: float` + `narrative_flag: bool`
- `prompts/__init__.py`：source_type/forward_looking 定義 + governance 規則
- `_parse_claims()`：observed_fact 降級 / confidence cap / forward_looking 規則
- `generate_summary()`：計算 narrative_density_score + narrative_flag（score > 0.6）
- UI：SOURCE_TYPE_BADGE；pipeline 🔬 tab；narrative banner；fwd-tag
- `tests/test_source_type_governance.py`：9 tests 通過

---

## Phase 10C: Rhetorical Risk Classifier ✅

**目標**: 偵測語氣過強的敘事型 claim，雙軸密度評分

**完成項目**:
- `RHETORICAL_RISK_PHRASES`（16 個語氣詞）
- `AIClaim`：加 `rhetorical_risk_flag: bool` + `rhetorical_risk_terms: list[str]`
- `AIReport`：加 `narrative_density_weighted_score: float`（文字長度加權）
- `_parse_claims()`：語氣掃描（只掃 narrative types，不影響 financial_evidence）
- narrative_flag = count density > 0.6 OR weighted > 0.6
- UI：banner 顯示雙指標；`.rhet-tag`（hover 顯示命中詞）
- `tests/test_rhetorical_governance.py`：8 tests 通過

---

## Phase 10D: Forward-Looking Implication Guard ✅

**目標**: 自動偵測隱性前瞻語言，不依賴 Claude 自我標記

**完成項目**:
- `FORWARD_LOOKING_INDICATOR_PHRASES`（14 個詞）
- `_parse_claims()`：auto-detect forward_looking（只掃 strategic/management，覆蓋 Claude False）
- 自動設 requires_human_review=True
- `tests/test_forward_looking_guard.py`：9 tests 通過

---

## Phase 10E: Quotation Layer（Attribution Prefix）✅

**目標**: 明確區分「公司宣稱 X」與「X 成立」，引用型敘事必加歸因前綴

**完成項目**:
- `AIClaim.attribution_prefix` field
- `_parse_claims()`：`_ATTRIBUTION_MAP`：strategic_narrative → "公司宣稱："；management_expectation → "管理層表示："
- UI：`.attr-prefix` CSS；renderClaim() 前綴歸因標籤

---

## Phase 11A: Output Completeness Rules（OC-1/OC-2）✅

**目標**: 後處理驗證器，確保財報中有非常態項目或流動性壓力時，AI 必須產出對應的衍生指標

**完成項目**:
- `prompts/__init__.py`：Phase 2.5 Output Completeness Rules 段落
  - OC-1（Gross Margin Adjustment）：recurring=false + 毛利相關 → 必填調整後毛利率 derived_metric
  - OC-2（Liquidity Safety Margin）：現金 + 借款/股利並存 → 必填現金安全墊 derived_metric
- `_check_completeness(claims)`：後處理驗證，回傳 list[str] warnings
- `AIReport.completeness_warnings`：ListField(StringField())
- `apis/v1/routers/summary.py`：GET endpoint 回傳 completeness_warnings
- UI：OC 警告黃色橫幅（completeness-banner），只在有警告時顯示
- `services/dashboard_contract.py`：新建模組（DASHBOARD_CONTRACT_VERSION / METRIC_TYPE /
  TREND_ENUM / validate_dashboard_contract_v1 / serialize_summary_response）
- Bug fix：`_build_dashboard_payload` 移除不存在的 `m["metric"]` KeyError

---

## Phase 2A: UI Semantic Color System ✅

**目標**: 修正 UI 色彩混亂，建立語意固定的 4 色系統

**完成項目**:
- 4 色語意固定：綠（事實）/ 黃（警示）/ 紅（風險）/ 藍（待審）
- `b-review` 藍色 badge（review ≠ risk，修正 uncertainty-risk collapse）
- `attn-tag-risk / attn-tag-watch / attn-tag-info / attn-tag-oc` 標籤分類
- KPI Impact badge 分色（高=紅，中=橘，低=灰）

---

## Phase 2B: Cognitive Workflow UI ✅

**目標**: 建立 L0 主結論 card，使閱讀流程符合認知層次

**完成項目**:
- `computeNarrative()` client-side 函式（🟢/🟡/🔴 三種主結論）
- Primary Narrative Card（Layer 0）：主結論 + 信心程度 + 主要原因 + 需觀察清單
- Hero KPI Card（`fc-hero`）：高影響第一張卡片雙欄展示
- Review Workflow Panel：N 條待確認，分類 epistemic failure mode
- `static/mock_results.html` Phase 2A/2B 預覽

---

## Phase 2C: Narrative Explainability + Review Severity L1-L4 ✅

**目標**: 主結論附依據，待審清單依嚴重度排序

**完成項目**:
- `computeNarrative()` 收集 `evidence_claim_ids`（最多 3 條 claim + 頁碼）+ 衝突訊號
- `_reviewSeverityLevel()` 函式；`SEV_META/SEV_ORDER` dict
- 待確認清單依 L4→L1 排序；每條前綴 badge（L4=紅/L3=黃/L2=藍/L1=灰）
- `tests/test_quotation_layer.py`：9 tests 補齊 Phase 10E

---

## Phase 2D: Materiality Engine ✅

**目標**: 用三因子公式取代 dashboard hardcode 規則，KPI 影響程度可計算

**完成項目**:
- `_METRIC_BASE_IMPACT` dict + `_calc_impact(metric_id, delta_pct, direction)`
- 三因子：base 重要性 × 變化幅度升降 × 方向風險
- 取代 `_build_dashboard_payload` 中硬編碼規則

---

## Phase 3A: Multi-Period Trend 🚧

**目標**: 讓使用者上傳同公司 2-4 季財報，自動產生 KPI 跨期趨勢，可視化變化走勢

**範圍**:
- 接收多個 `document_id`（已各自 ingest + summary 完成）
- 從各期 `AIReport` 聚合固定 KPI（營收、毛利率、現金、負債比等）
- 輸出 `TrendReport`：每個 KPI 跨期的 value list + direction + governance warning
- UI：Trend Strip — 每個 KPI 一欄，橫軸為期別，顯示值與方向箭頭

**Governance guards**:
- R7 guard：不可從 2 期以下資料推論「長期趨勢」
- 每個 trend point 必須有 source document_id（防止跨文件推論未標示）
- 只顯示 observed_fact / derived_metric 的 KPI，不混入 interpretation

**API**:
- `POST /api/v1/reports/trend`（body: `{document_ids: [...], kpi_list?: [...]}`）
- `GET /api/v1/reports/trend/{trend_report_id}`

**模型**:
- `TrendReport`：trend_report_id / stock_id / periods / kpis / created_at
- `TrendPoint`：period / document_id / value / unit / source_claim_id / governance_flags

**完成項目**:
- [ ] `models/trends/` TrendReport + TrendPoint
- [ ] `services/trend/` — KPI 聚合 + R7 guard
- [ ] `apis/v1/routers/trends.py`
- [ ] UI Trend Strip（Static HTML）
- [ ] Tests

---

## Backlog

### 下一步（Phase 3B）
- Report Export：分析結果輸出 JSON / PDF，配合 `dashboard_contract.schema.json`

### 技術債
- PLAN.md freshness：每次 sprint 完成後更新（7d threshold）

---

## Anti-Goals（本階段不做）

- 不做自動選股、買賣建議、股價預測
- 不做投資組合推薦
- 不做即時交易訊號
- 不把 AI 推論包裝成事實
- 不做 multi-tenant / 帳號系統（Auth 是骨架，不是當前 Sprint）
- 不做即時 WebSocket streaming（Claude API 回應以 REST 為主）

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

## 測試總覽（截至 2026-05-30）

| 測試檔案 | Tests | 說明 |
|---------|-------|------|
| test_governance.py | 49 | R1-R7 governance rules |
| test_reasoning_patterns.py | 16 | Pattern engine（9E + 9F）|
| test_source_type_governance.py | 9 | Source type governance（10B）|
| test_rhetorical_governance.py | 8 | Rhetorical risk + weighted density（10C）|
| test_forward_looking_guard.py | 9 | Forward-looking auto-detect（10D）|
| test_disclosure_coverage.py | 10 | Disclosure coverage engine（9D）|
| test_quotation_layer.py | 9 | Attribution prefix（10E）|
| test_dashboard_contract.py | 104 | Dashboard contract schema |
| test_audit_service.py | 3 | Diff audit service edge-cases |
| test_diff_audit_api.py | 3 | R6 audit API |
| test_auth_wiring.py | 6 | JWT auth wiring |
| test_auth_wiring_extended.py | 5 | JWT auth extended coverage |
| test_output_completeness.py | 8 | OC-1/OC-2 rules |
| **合計** | **239** | ⚠ API 層測試需 mongoengine + httpx |

---

## 變更歷史

| 日期 | 變更內容 |
|------|---------|
| 2026-05-13 | 專案啟動，Phase 0~7 完成 |
| 2026-05-13 | Phase 8 ✅: 44 tests 全綠，requirements.txt 清理 |
| 2026-05-14 | Phase 9B ✅: UI 重設計 |
| 2026-05-14 | Phase 9C ✅: industry_type + CDMO/半導體 supplement |
| 2026-05-14 | Phase 9D ✅: Disclosure Coverage Engine，10 tests |
| 2026-05-14 | Phase 9E ✅: Pattern Registry，6 patterns，14 tests |
| 2026-05-15 | Phase 9F ✅: Pattern precision + claim discipline |
| 2026-05-15 | Phase 10A ✅: Interpretation isolation UI |
| 2026-05-15 | Phase 10B ✅: Source type + narrative density |
| 2026-05-15 | Phase 10C ✅: Rhetorical risk classifier |
| 2026-05-15 | Phase 10D ✅: Forward-looking guard |
| 2026-05-15 | Phase 10E ✅: Quotation layer / attribution prefix |
| 2026-05-15 | Phase 11A ✅: Output Completeness Rules OC-1/OC-2 |
| 2026-05-15 | Bug fix: HTTP 500 / ValidationError / ROC year 民國年轉換 |
| 2026-05-15 | Bug fix: session closeout auto-memory pipeline |
| 2026-05-16 | Bug fix: dashboard_contract.py 缺失（後端 import 錯誤）+ KeyError m["metric"] |
| 2026-05-16 | UI: completeness_warnings OC 警告橫幅顯示 |
| 2026-05-17 | Phase 2A ✅: UI Semantic Color System（4 色語意固定）|
| 2026-05-17 | Phase 2B ✅: Cognitive Workflow UI（Primary Narrative Card + Review Panel）|
| 2026-05-18 | Phase 2C ✅: Narrative Explainability + Review Severity L1-L4 + test_quotation_layer.py |
| 2026-05-18 | Phase 2D ✅: Materiality Engine _calc_impact() |
| 2026-05-20 | Auth ✅: JWT guard 擴展至全部 write routers（documents/classification/tables/data_source/disclosures）|
| 2026-05-20 | Audit ✅: DiffReport R6 audit endpoint + test_diff_audit_api.py |
| 2026-05-20 | UI ✅: JWT token input + Diff Audit panel（static/index.html）|
| 2026-05-30 | Governance ✅: ai-governance-framework sync（7 新文件 + fleet/）|
| 2026-05-30 | Fix ✅: JWT guard 加至 audit.py；OC-2 debt keywords 補強（長期借款 / 應付公司債 / ECB 等）|
| 2026-05-30 | Deploy ✅: Cloud Run revision 00007-7bz |
| 2026-05-30 | Governance ✅: adopt_governance baseline（17/18 checks PASS）|
| 2026-05-30 | Phase 3A 🚧: Multi-Period Trend 開始 |
