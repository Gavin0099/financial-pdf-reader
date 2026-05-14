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
- Phase 7: Governance Layer（R1-R7 audit engine，GovernanceViolation，/audit endpoint）
- Phase 8: Tests + Cleanup（44 tests，requirements.txt 清理）
- Phase 9B: UI Redesign（Key Findings grid，中性色碼）
- Phase 9C: Industry Type + CDMO Supplement（evidence-first governance fix）
- Phase 9D: Disclosure Coverage Engine（14 items，Haiku，10 tests）
- Phase 9E: Pattern Registry（6 patterns，純 Python，14 tests）
- Phase 9F: Pattern Trigger Precision（amount keyword filter；observed_fact 禁止 AI 自算比率；derived_metric 必填公式；KF 上限降為 4）
- Phase 10A: Interpretation Isolation（interpretation/hypothesis 預設折疊；ed-label；「可能需要檢查：」前綴）
- Phase 10B: Source Type Layer（source_type 4 types；forward_looking；narrative_density_score；pipeline section_key）
- Phase 10C: Rhetorical Risk Classifier（RHETORICAL_RISK_PHRASES；narrative_density_weighted_score；雙軸 banner）
- Phase 10D: Forward-Looking Implication Guard（FORWARD_LOOKING_INDICATOR_PHRASES；auto-detect implicit forward-looking）

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
- `core/governance.py` 是 R1-R7 的唯一真實來源，不得在其他地方重複定義規則
- AGENTS.md 部署到專案根目錄才能讓 Claude Code 在 session 啟動時讀取記憶更新協議
- R3 auto-fix（summarization 已自動降級）標記為 warning 而非 error，避免 false positive
- Industry supplement = extraction hint only，不是 authority grant — 有頁碼才能 tier_a
- Pattern 結果永遠是 interpretation + requires_review=True，不進 Key Findings（hardcoded）
- FX 損益不自動標為一次性（fx_driven_profit pattern 無 recurring filter）
- Disclosure Coverage Engine 只判斷「揭露是否存在」，not_applicable 不計入 not_found
- non_recurring_eps：bare "元" 保留（EPS 格式 "0.5 元"）；fx_driven_profit：排除 bare "元"（避免匹配「美元」）
- observed_fact 禁止含 AI 自算比率；derived_metric 必填計算公式
- claim_level（HOW confident）與 source_type（WHAT TYPE）是兩個正交維度
- strategic_narrative / management_expectation 不得為 observed_fact（服務層 fail-closed 降級）
- management_expectation confidence 上限 = medium（服務層 cap）
- Rhetorical scan 只掃 narrative 類型；financial_evidence 不受影響（避免「營收大幅增加」誤傷）
- narrative_flag = count density > 0.6 OR weighted density > 0.6（任一超標觸發）
- Forward-looking guard 只掃 strategic_narrative / management_expectation；auto-override Claude 的 forward_looking=False

## Memory 漏記根本原因（2026-05-14 分析）

**規則存在但沒有強制執行機制**：
1. AGENTS.md session start 協議只是文字規則，沒有工具層強制
2. `scripts/closeout.ps1`（AGENTS.md 引用）不存在 → DoD 無法 fail-closed
3. Session context 壓縮後重啟，AI 不知道 memory 沒更新
4. 沒有 git pre-push hook 檢查 memory 是否同步

**修正方向**：建立 `scripts/closeout.ps1` + git pre-push hook
