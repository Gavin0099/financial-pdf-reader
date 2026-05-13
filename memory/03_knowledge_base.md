# Knowledge Base

**最後更新**: 2026-05-13（Phase 6 完成）

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

### AIReport（collection: ai_reports）Phase 2
| 欄位 | 型別 | 說明 |
|------|------|------|
| report_id | str | UUID |
| document_id | str | 對應 PDFDocument |
| claims | list[AIClaim] | AI 觀察列表 |
| evidence_status | str | complete / partial / insufficient |
| investment_advice_detected | bool | Governance guard flag |

### AIClaim（embedded in AIReport）
| 欄位 | 型別 | 說明 |
|------|------|------|
| claim_id | str | UUID |
| claim | str | 觀察描述 |
| claim_type | str | financial_observation / management_tone / risk_factor / accounting_note / numeric_cross_check |
| claim_level | str | 見下表 |
| evidence | list[ClaimEvidence] | 來源列表（必須有頁碼）|
| requires_human_review | bool | 數字異常 / 語氣重大變化 / 附註 |

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

## Governance Rules（R1-R7，Phase 7 將系統化）

| Rule | 說明 |
|------|------|
| R1 | 每個 claim 必須有 evidence |
| R2 | 數字 claim 必須有 source table 或 source text |
| R3 | 沒有 evidence 時降級為 hypothesis 或 insufficient_evidence |
| R4 | 不允許 investment recommendation |
| R5 | 不允許跨文件推論未標示來源 |
| R6 | 不允許把語氣變化直接說成財務惡化（tone_only flag）|
| R7 | 不允許用單季資料推論長期趨勢 |

---

## 外部資料源

| 來源 | 資料類型 | 合法性 | 注意事項 |
|------|---------|--------|---------|
| FinMind | 月營收、財務報表 | TWSE/MOPS 公開資料彙整 | 免費版每小時 600 次 |
| TWSE | 即時/歷史行情 | 政府公開資料 | 直接抓需遵守條款 |
| MOPS（公開資訊觀測站）| 財報原始文件 | 政府公開資料 | PDF 需人工上傳 |
