# Knowledge Base

**最後更新**: 2026-05-14（Phase 10D 完成）

## Data Models 總覽

### PDFDocument（collection: pdf_documents）
| 欄位 | 型別 | 說明 |
|------|------|------|
| document_id | str | UUID |
| stock_id | str | 台股代號 e.g. "2330" |
| company_name | str | 公司名稱 |
| period | str | e.g. "2026Q1" |
| document_type | str | quarterly_report / annual_report / earnings_release |
| file_path | str | 本地 PDF 路徑 |
| total_pages | int | 總頁數 |
| status | str | uploaded / ingesting / completed / failed |

### PDFChunk（collection: pdf_chunks）
| 欄位 | 型別 | 說明 |
|------|------|------|
| chunk_id | str | UUID |
| document_id | str | 對應 PDFDocument |
| page | int | **必填**，1-based 頁碼 |
| section | str | 財務段落分類（Phase 3，ingest 時 rule-based 自動填入）|
| content_type | str | text / table |
| text | str | chunk 文字內容 |
| char_count | int | 字元數 |
| confidence | str | high / medium / low |

### PDFTable（collection: pdf_tables）Phase 5
| 欄位 | 型別 | 說明 |
|------|------|------|
| table_id | str | UUID |
| document_id | str | 對應 PDFDocument |
| page | int | **必填**，1-based 頁碼 |
| section | str | 段落分類 |
| table_index | int | 同頁第幾個表格（0-based）|
| table_markdown | str | markdown 格式表格 |
| extraction_quality | str | high / medium / low / failed |
| requires_human_review | bool | low quality 時自動=True |

### AIReport（collection: ai_reports）Phase 2 + 10B + 10C
| 欄位 | 型別 | 說明 |
|------|------|------|
| report_id | str | UUID |
| document_id | str | 對應 PDFDocument |
| claims | list[AIClaim] | AI 觀察列表 |
| evidence_status | str | complete / partial / insufficient |
| investment_advice_detected | bool | Governance guard flag |
| narrative_density_score | float | 0.0–1.0：strategic/management claim 數佔比（10B）|
| narrative_density_weighted_score | float | 0.0–1.0：文字長度加權佔比（10C）|
| narrative_flag | bool | count > 0.6 OR weighted > 0.6 時 True（10B/10C）|

### AIClaim（embedded in AIReport）
| 欄位 | 型別 | 說明 |
|------|------|------|
| claim_id | str | UUID |
| claim | str | 觀察描述 |
| claim_type | str | financial_observation / management_tone / risk_factor / accounting_note / numeric_cross_check |
| claim_level | str | 見下表（HOW confident）|
| source_type | str | financial_evidence / operational_evidence / strategic_narrative / management_expectation（10B，WHAT TYPE）|
| forward_looking | bool | True = 未來預期/計畫；服務層 auto-detect（10B/10D）|
| rhetorical_risk_flag | bool | strategic/management claims 含高確信語氣詞（10C）|
| rhetorical_risk_terms | list[str] | 命中的語氣詞（10C）|
| section_key | str | key_financials / accounting_adjustments / liquidity / risk_register / pipeline / evidence_gaps |
| evidence | list[ClaimEvidence] | 來源列表（必須有頁碼）|
| requires_human_review | bool | 數字異常 / 語氣重大變化 / forward_looking 時自動 True |

### DiffReport（collection: diff_reports）Phase 4
| 欄位 | 型別 | 說明 |
|------|------|------|
| diff_report_id | str | UUID |
| current_document_id | str | 本季 PDF |
| previous_document_id | str | 上季 PDF |
| stock_id | str | 必須相同公司 |
| items | list[DiffItem] | 差異項目列表 |
| sections_compared | list | 共同分析的段落 |
| sections_only_current | list | 只在本季出現的段落 |
| sections_only_previous | list | 只在上季出現的段落 |

### DiffItem（embedded in DiffReport）
| 欄位 | 型別 | 說明 |
|------|------|------|
| diff_type | str | new_language / removed_language / tone_shift / numeric_change / new_risk / removed_risk |
| tone_only | bool | tone_shift 時=True，禁止等同財務惡化 |
| evidence.presence | str | both / only_in_current / only_in_previous |
| requires_human_review | bool | 預設=True |

### PDFDocument.industry_type（Phase 9C）
| 值 | 說明 |
|----|------|
| general | 一般產業（預設）|
| cdmo | 委託開發製造（Backlog/LOI/Milestone）|
| semiconductor | 半導體（稼動率/ASP/先進製程）|

### DisclosureCoverageReport（collection: disclosure_coverage_reports）Phase 9D
| 欄位 | 型別 | 說明 |
|------|------|------|
| coverage_id | str | UUID |
| document_id | str | 對應 PDFDocument |
| items | list[DisclosureCoverageItem] | 14 條 |
| found_count | int | status=found 數量 |
| not_found_count | int | status=not_found 數量（不含 not_applicable）|
| not_applicable_count | int | status=not_applicable 數量 |
| total_count | int | 永遠=14 |

### PatternRunReport（collection: pattern_run_reports）Phase 9E
| 欄位 | 型別 | 說明 |
|------|------|------|
| run_id | str | UUID |
| document_id | str | 對應 PDFDocument |
| results | list[PatternRunResult] | 6 條（對應 6 個 pattern）|
| triggered_count | int | status=triggered 數量 |
| insufficient_count | int | status=insufficient_evidence 數量 |

### PatternRunResult（embedded in PatternRunReport）
| 欄位 | 型別 | 說明 |
|------|------|------|
| pattern_id | str | e.g. "debt_maturity_risk" |
| status | str | triggered / not_triggered / insufficient_evidence |
| generated_observation | str | observation_template 原文（只在 triggered 時有值）|
| source_claim_ids | list[str] | 觸發的 claim IDs |
| requires_review | bool | triggered 時=True，其餘=False |
| claim_level | str | **永遠 = interpretation**（guard）|
| in_key_findings | bool | **永遠 = False**（guard）|

### ExternalDataRecord（collection: external_data）Phase 6
| 欄位 | 型別 | 說明 |
|------|------|------|
| record_id | str | UUID |
| stock_id | str | 台股代號 |
| data_type | str | monthly_revenue / financial_statement / cash_flow |
| data_source | str | e.g. "FinMind/TaiwanStockMonthRevenue" |
| payload | dict | FinMind 原始資料 |
| is_auxiliary | bool | **永遠=True**，不得作為主要 evidence |

---

## Source Type 定義（Phase 10B）

| source_type | 說明 | 可為 observed_fact? | confidence 上限 |
|-------------|------|:-------------------:|:---------------:|
| financial_evidence | 財報數字、報表附注、會計政策 | ✓ | high |
| operational_evidence | 業務章節具體事實（廠房、產能、認證）| ✓ | high |
| strategic_narrative | 管理層/公司戰略說法 | ✗（→ interpretation）| high |
| management_expectation | 明確展望/指引 | ✗（→ interpretation）| medium |

## 服務層 Governance Guards 執行順序（`_parse_claims()`）

```
1. no evidence → force insufficient_evidence
2. temporal inconsistency → contaminated=True
3. strategic/management + observed_fact → downgrade to interpretation
4. management_expectation + confidence=high → cap at medium
5. forward_looking=True (Claude) → requires_human_review=True
6. narrative type + FORWARD_LOOKING_INDICATOR_PHRASES → auto-set forward_looking=True
7. narrative type + RHETORICAL_RISK_PHRASES → rhetorical_risk_flag=True + terms
```

所有 guard 只能降級/標記，不能提升 claim 可信度（fail-closed）。

## 詞彙列表位置

| 常數 | 檔案 | 說明 |
|------|------|------|
| INVESTMENT_ADVICE_GUARD_PHRASES | prompts/__init__.py | 投資建議偵測，掃全文 |
| RHETORICAL_RISK_PHRASES | prompts/__init__.py | 高確信語氣，只掃 narrative claims |
| FORWARD_LOOKING_INDICATOR_PHRASES | prompts/__init__.py | 前瞻指示詞，只掃 narrative claims |

---

## Claim Level 定義

| Level | 意義 | Evidence 要求 |
|-------|------|--------------|
| observed_fact | 直接引自原文 | 必須有 quoted_text |
| derived_metric | 由原文數字計算 | 必須有來源頁碼 |
| interpretation | AI 詮釋 | 必須有 evidence |
| hypothesis | AI 推測 | evidence 不足但存在 |
| insufficient_evidence | 無法確認 | evidence 為空，**自動降級** |

---

## Financial Section Taxonomy（20 個，Phase 3）

```
營收、毛利率、營業利益、淨利、EPS、
存貨、應收帳款、現金流、資本支出、負債、
匯率影響、產能、稼動率、客戶需求、產業展望、
風險因素、重大會計估計、會計政策變更、管理層展望、董事會說明
```

---

## Governance Rules（R1-R7，Phase 7 已系統化）

實作位置：`core/governance.py`、稽核服務：`services/audit/`

| Rule | 說明 | 嚴重度 | 實作 |
|------|------|--------|------|
| R1 | 每個 claim 必須有 evidence | error | check_r1() |
| R2 | 數字 claim（derived_metric）必須有 quoted_text | error | check_r2() |
| R3 | 沒有 evidence 時降級為 hypothesis 或 insufficient_evidence | warning（auto-fixed）| check_r3() |
| R4 | 不允許 investment recommendation | error | check_r4_report() + check_r4_claim() |
| R5 | 不允許跨文件推論未標示來源 | warning | check_r5() |
| R6 | 不允許把語氣變化直接說成財務惡化（tone_only flag）| 由 DiffItem.tone_only 保障 | Phase 4 |
| R7 | 不允許用單季資料推論長期趨勢（關鍵詞掃描）| warning | check_r7_claim() |

### GovernanceAuditResult 欄位

| 欄位 | 說明 |
|------|------|
| passed | True = 0 violations（warning 不影響）|
| violation_count | error 數量 |
| warning_count | warning 數量 |
| violations | list[GovernanceViolation] |
| warnings | list[GovernanceViolation] |
| summary | 人類可讀一句話摘要 |

---

## 外部資料源

| 來源 | 資料類型 | 合法性 | 注意事項 |
|------|---------|--------|---------|
| FinMind | 月營收、財務報表 | TWSE/MOPS 公開資料彙整 | 免費版每小時 600 次 |
| TWSE | 即時/歷史行情 | 政府公開資料 | 直接抓需遵守條款 |
| MOPS（公開資訊觀測站）| 財報原始文件 | 政府公開資料 | PDF 需人工上傳 |
