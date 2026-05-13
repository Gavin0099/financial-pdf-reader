# Knowledge Base

## Data Models

### PDFDocument（collection: pdf_documents）
| 欄位 | 型別 | 說明 |
|------|------|------|
| document_id | str | UUID，唯一識別 |
| stock_id | str | 台股代號，e.g. "2330" |
| company_name | str | 公司名稱 |
| period | str | 財報期間，e.g. "2026Q1" |
| document_type | str | quarterly_report / annual_report |
| file_path | str | 本地 PDF 路徑 |
| total_pages | int | 總頁數 |
| status | str | uploaded / ingesting / completed / failed |

### PDFChunk（collection: pdf_chunks）
| 欄位 | 型別 | 說明 |
|------|------|------|
| chunk_id | str | UUID |
| document_id | str | 對應 PDFDocument |
| page | int | **必填**，1-based 頁碼 |
| section | str | 財務段落分類（Phase 3 填入） |
| text | str | chunk 文字內容 |
| char_count | int | 字元數 |

### AIReport（collection: ai_reports）
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
| claim_level | str | observed_fact / derived_metric / interpretation / hypothesis / insufficient_evidence |
| evidence | list[ClaimEvidence] | 來源列表（必須有頁碼） |
| requires_human_review | bool | 標記需人工確認 |

## Claim Level 定義

| Level | 意義 | Evidence 要求 |
|-------|------|--------------|
| observed_fact | 直接引自原文 | 必須有 quoted_text |
| derived_metric | 由原文數字計算 | 必須有來源頁碼 |
| interpretation | AI 詮釋 | 必須有 evidence |
| hypothesis | AI 推測 | evidence 不足但存在 |
| insufficient_evidence | 無法確認 | evidence 為空 |

## Financial Section Taxonomy（Phase 3）

```
營收、毛利率、營業利益、淨利、EPS、
存貨、應收帳款、現金流、資本支出、負債、
匯率影響、產能、稼動率、客戶需求、產業展望、
風險因素、重大會計估計、會計政策變更、管理層展望、董事會說明
```
