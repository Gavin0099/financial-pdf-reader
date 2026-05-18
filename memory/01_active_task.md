# Active Task

**最後更新**: 2026-05-16（Phase 11A 完成，Cloud Run 部署完成）
**當前 Phase**: Phase 11A 完成 — Output Completeness Rules (OC-1/OC-2)

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

### Phase 6 ✅
- `ExternalDataRecord` model（is_auxiliary 永遠=True，防止混淆）
- FinMind API 整合（月營收 + 財務報表，資料來源標示）
- Period 轉日期範圍（2026Q1 → 2026-01-01 ~ 2026-03-31）
- Cross-check：consistent / needs_review / not_comparable（不輸出投資判斷）
- POST /{stock_id}/fetch-revenue（月營收）
- POST /{stock_id}/fetch-financials（財務報表）
- GET /{stock_id}/crosscheck（PDF 數字 vs 外部資料）
- GET /{stock_id}/external-data（快取查詢）

### Phase 7 ✅
- `core/governance.py`：GovernanceViolation / GovernanceAuditResult dataclass
- R1-R7 完整實作（R1 evidence required, R2 numeric source, R3 auto-downgrade, R4 investment advice, R5 cross-doc, R7 trend language）
- `services/audit/__init__.py`：run_audit() 執行稽核
- `apis/v1/routers/audit.py`：GET /{document_id}/audit
- `AGENTS.md` 部署到根目錄，修復 memory 更新遺漏問題
- `memory/2026-05-13.md` daily log 建立

### Phase 8 ✅
- `tests/test_governance.py`：R1-R7 unit tests，44 tests passed，純 Python 無外部依賴
- `requirements.txt` 清理：移除 chromadb、langchain\*、sentence-transformers、huggingface-hub、beanie、motor；補上 python-dotenv

### Phase 9B ✅
- HTML UI 全面重設計：Key Findings grid、section tabs、collapsible evidence
- Claim-level badge 改為中性色系（觀察類型，不是情緒）
- 一次性項目 badge 改為中性灰

### Phase 9C ✅
- `PDFDocument.industry_type` field（general / cdmo / semiconductor）
- 上傳表單加入產業別下拉選單
- `INDUSTRY_SUPPLEMENTS` dict — extraction hint（非 authority grant）
- **Governance fix**: supplement 改為 evidence-first，不自動升 tier_a
- Executive Summary 禁用因果歸因語言

### Phase 9D ✅
- 14 項法定揭露稽核（台灣第 12、17 條 + IFRS）
- `models/disclosures/`、`services/disclosure_coverage/`、`apis/v1/routers/disclosures.py`
- 使用 claude-haiku-4-5（成本低）；缺失 key 自動填補 ambiguous
- `tests/test_disclosure_coverage.py`：10 tests 通過
- UI Step 4：14 項 coverage matrix

### Phase 9E ✅
- 6 個財報警示 pattern（純 Python，不呼叫 Claude）
- `reasoning_patterns/`：schemas + 6 pattern 定義
- `services/reasoning_patterns/`：evidence_resolver + engine + run_pattern_analysis()
- `models/patterns/`：PatternRunResult + PatternRunReport
- `apis/v1/routers/patterns.py`：POST /{id}/patterns/run
- UI Step 5：pattern 結果 + source claims accordion
- Guards hardcoded：CLAIM_LEVEL=interpretation、REQUIRES_REVIEW=True、IN_KEY_FINDINGS=False
- `tests/test_reasoning_patterns.py`：14 tests 通過

### Phase 9F ✅
- `non_recurring_eps`：加 `_AMOUNT_KEYWORDS` filter（bare qualitative → insufficient_evidence）
- `fx_driven_profit`：加第二個 filter 要求量化金額；排除 bare "元" 避免「美元」誤觸發
- `prompts/__init__.py`：observed_fact 禁止 AI 自算比率；derived_metric 必填公式
- UI：Key Findings 上限 4 條（原 6），超出顯示「+N 條請見分頁」
- `tests/test_reasoning_patterns.py`：新增 test 11/12；共 16 tests 通過

### Phase 10A ✅
- UI 詮釋隔離：interpretation/hypothesis 預設折疊（`.interp-section`）
- `EVIDENCE_DISTANCE` 常數 + `.ed-label` badge（5 個層級）
- `renderClaim()` 加 ed-label；interpretation 前綴「可能需要檢查：」
- `.interp-disclaimer` 警告橫幅；`toggleInterp()` 展開收起

### Phase 10B ✅
- `AIClaim`：加 `source_type`（4 choices）+ `forward_looking: bool`
- `AIReport`：加 `narrative_density_score: float` + `narrative_flag: bool`
- `prompts/__init__.py`：加 `pipeline` section_key；加 source_type/forward_looking 定義 + governance 規則；CDMO supplement 擴充
- `services/summarization/_parse_claims()`：3 條 governance 規則（observed_fact 降級/confidence cap/forward_looking）
- `generate_summary()`：計算 narrative_density_score + narrative_flag（score > 0.6 觸發）
- UI：`SOURCE_TYPE_BADGE`；pipeline 🔬 tab；narrative banner；fwd-tag
- `tests/test_source_type_governance.py`：9 tests；共 25 tests 通過

### Phase 10C ✅
- `prompts/__init__.py`：加 `RHETORICAL_RISK_PHRASES`（16 個語氣詞）
- `AIClaim`：加 `rhetorical_risk_flag: bool` + `rhetorical_risk_terms: list[str]`
- `AIReport`：加 `narrative_density_weighted_score: float`（文字長度加權）
- `_parse_claims()`：語氣掃描（只掃 narrative types）
- `generate_summary()`：加權密度；narrative_flag = count > 0.6 OR weighted > 0.6
- UI：banner 顯示雙指標；`.rhet-tag`（hover 顯示命中詞）
- `tests/test_rhetorical_governance.py`：8 tests；共 33 tests 通過

### Phase 10D ✅
- `prompts/__init__.py`：加 `FORWARD_LOOKING_INDICATOR_PHRASES`（14 個詞）
- `_parse_claims()`：auto-detect forward_looking（only strategic/management，覆蓋 Claude 的 False）
- 自動設 requires_human_review=True
- `tests/test_forward_looking_guard.py`：9 tests

### Phase 10E ✅
- Quotation-layer：「公司宣稱 X」≠「X 成立」
- `services/summarization/quotation_layer.py`：quote_attribution prefix
- management_claim vs observed_fact 區分強化

### Phase 11A ✅（2026-05-16）
- `services/summarization/output_completeness.py`：OC-1、OC-2 rules
- OC-1：adjusted_gross_margin 有 non-recurring adjustments 才計算
- OC-2：liquidity_safety_margin（現金安全墊）= cash / (operating_expense / 4)
- `AIReport.completeness_warnings: list[str]`（空 list = 無警告）
- `services/dashboard_contract.py` 新建（修復缺失模組 ImportError）：`DASHBOARD_CONTRACT_VERSION`、`METRIC_TYPE`、`TREND_ENUM`、`validate_dashboard_contract_v1`、`serialize_summary_response`
- `services/summarization/__init__.py`：移除 `"metric": m["metric"]`（KeyError 修復）
- UI：`.completeness-banner` 黃色警告橫幅（有警告才顯示）
- UI：全面中文化（30+ 標籤翻譯）

## 部署狀態（2026-05-16）

- 平台：**GCP Cloud Run**（已從 Railway 遷移）
- Service URL：`https://financial-pdf-reader-647193990749.asia-east1.run.app`
- GCP Project：`hearth-491015`，Region：`asia-east1`，Memory：512Mi
- MongoDB Atlas：Cluster `cluster0.4sqzpoq.mongodb.net`，Network Access `0.0.0.0/0`

## 測試總覽

| 測試檔案 | Tests | 說明 |
|---------|-------|------|
| test_governance.py | 44 | R1-R7 governance rules（Phase 8）|
| test_reasoning_patterns.py | 16 | Pattern engine（9E + 9F）|
| test_disclosure_coverage.py | 10 | Disclosure coverage（9D）|
| test_source_type_governance.py | 9 | Source type governance（10B）|
| test_forward_looking_guard.py | 9 | Forward-looking auto-detect（10D）|
| test_rhetorical_governance.py | 8 | Rhetorical risk + weighted density（10C）|
| **合計** | **96** | **全部通過** |

### Phase 2A ✅（2026-05-17）
- UI Semantic Color System：4 色語意固定（綠/黃/紅/藍）
- `b-review` 藍色 badge（review ≠ risk，修正 uncertainty-risk collapse）
- `attn-tag-risk / attn-tag-watch / attn-tag-info / attn-tag-oc` 標籤分類
- KPI Impact badge 分色（高=紅，中=橘，低=灰）

### Phase 2B ✅（2026-05-17）
- `computeNarrative()` client-side 函式：從 dashboard data 推斷主結論
- 三種結論：🟢 整體穩健 / 🟡 短期波動 / 🔴 結構壓力
- Primary Narrative Card（Layer 0）：主結論 + 信心程度 + 主要原因 + 需觀察清單
- Hero KPI Card（`fc-hero`）：高影響第一張卡片雙欄展示
- Review Workflow Panel：可展開 N 條待確認，分類 epistemic failure mode
- `toggleReviewPanel()` 函式
- `static/mock_results.html` 更新為 Phase 2A/2B 預覽

### Phase 2C ✅（2026-05-18）
- **Narrative Explainability Layer**：`computeNarrative()` 收集 `evidence_claim_ids`，顯示主結論依據（最多 3 條 claim + 頁碼）+ 衝突訊號；`toggleNarrEv()` 展開收起
- **Review Severity Model L1-L4**：`_reviewSeverityLevel()` 函式；`SEV_META/SEV_ORDER` dict；待確認清單依嚴重度排序；每條前綴 badge（L4=紅/L3=黃/L2=藍/L1=灰）；header 更新
- **`tests/test_quotation_layer.py`**：9 tests，Phase 10E 缺失測試補齊，全數通過

### Phase 2D ✅（2026-05-18）
- **Materiality Engine**：`_METRIC_BASE_IMPACT` dict + `_calc_impact(metric_id, delta_pct, direction)`（三因子：base 重要性 + 變化幅度升降 + 方向風險）；取代 `_build_dashboard_payload` 中硬編碼規則
- **Cloud Run Step 5 確認**：patterns router 已掛載，`reasoning_patterns/` 已在 COPY 範圍，6 個 pattern 正常載入

| 測試檔案 | Tests | 說明 |
|---------|-------|------|
| test_quotation_layer.py | 9 | Attribution prefix (Phase 10E) |
| **合計** | **109** | **全部通過** |

## 下一步候選（Backlog）

### P2（後端/測試）
- OC-2 關鍵字邊界補強（公司債 vs 可轉債 等邊界詞）
- Auth wiring（`auth/` 骨架存在，未接路由）
- DiffReport R6 audit endpoint（選做）
- Mini Trend Strip（需多期資料，先跳過）
- [x] Promoted memory: Fix HTTP 500 / ValidationError / ROC year bugs; implement Phase 11A Output Completeness Rules (OC-1/OC-2); fix session auto-memory pipeline
- [x] Promoted memory: Fix HTTP 500 / ValidationError / ROC year bugs; implement Phase 11A Output Completeness Rules (OC-1/OC-2); fix session auto-memory pipeline
- [x] Promoted memory: Fix HTTP 500 / ValidationError / ROC year bugs; implement Phase 11A Output Completeness Rules (OC-1/OC-2); fix session auto-memory pipeline
- [x] Promoted memory: Fix HTTP 500 / ValidationError / ROC year bugs; implement Phase 11A Output Completeness Rules (OC-1/OC-2); fix session auto-memory pipeline
- [x] Promoted memory: Fix HTTP 500 / ValidationError / ROC year bugs; implement Phase 11A Output Completeness Rules (OC-1/OC-2); fix session auto-memory pipeline
