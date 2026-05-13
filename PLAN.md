# PLAN.md — Taiwan Financial PDF Reader

> **專案類型**: PDF Analysis Tool
> **技術棧**: Python / FastAPI / MongoDB Atlas / ChromaDB / Claude API
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
├─ [⏳] Phase 0: Repo Bootstrap & Backend 跑起來
├─ [⏳] Phase 1: PDF Ingestion MVP（page-aware）
├─ [⏳] Phase 2: Evidence-Bound Summary
├─ [⏳] Phase 3: Financial Section Classification
├─ [⏳] Phase 4: Two-PDF Diff Report
├─ [⏳] Phase 5: Table Extraction & Numeric Cross-Check
├─ [⏳] Phase 6: Taiwan Data Source Integration
└─ [⏳] Phase 7: Governance Layer
```

**當前 Phase**: **Phase 0 — Repo Bootstrap**

---

## Phase 0: Repo Bootstrap（當前 🔄）

**目標**: Backend `/health` 正常回應，MongoDB Atlas 連線成功

**任務清單**:
```
├─ [⏳] 1. 建立 MongoDB Atlas 免費叢集
├─ [⏳] 2. 設定 .env（MONGODB_URL + ANTHROPIC_API_KEY）
├─ [⏳] 3. 補完 config/ module
├─ [⏳] 4. 安裝 dependencies
├─ [⏳] 5. 啟動 FastAPI，確認 /health 回 200
```

**Gate 條件**:
- [ ] `GET /health` 回 `{"status": "ok"}`
- [ ] MongoDB Atlas 連線不報錯
- [ ] 不出現 ImportError

---

## Phase 1: PDF Ingestion MVP

**目標**: 上傳一份台股財報 PDF，每個 chunk 都保留頁碼

**任務清單**:
```
├─ [⏳] 1. 新增 Taiwan PDF document model（stock_id / period / document_type）
├─ [⏳] 2. PDF extraction 改成 page-aware（pdfplumber）
├─ [⏳] 3. 每個 chunk 帶 page metadata
├─ [⏳] 4. 儲存 raw PDF + extracted chunks
├─ [⏳] 5. POST /api/v1/documents/upload 端點
├─ [⏳] 6. POST /api/v1/documents/{id}/ingest 端點
```

**Gate 條件**:
- [ ] 可上傳一份台股財報 PDF
- [ ] 每個 chunk 都有 page_number
- [ ] 不允許產生沒有 page reference 的回答

---

## Phase 2: Evidence-Bound Summary

**目標**: 產出單份 PDF 的財報摘要，每點都附來源頁碼

**Gate 條件**:
- [ ] Summary 每一點都有 evidence（source_pdf + page）
- [ ] 沒有 evidence 的內容輸出 insufficient_evidence
- [ ] 不出現買進、賣出、持有建議

---

## Phase 3: Financial Section Classification

**目標**: 將 PDF chunks 自動分類（營收、毛利率、存貨…等 20 類）

---

## Phase 4: Two-PDF Diff Report

**目標**: 比較兩份財報，找出新增/消失說法與語氣變化

---

## Phase 5: Table Extraction

**目標**: 抽出財務表格，對 AI summary 中的數字做 evidence check

---

## Phase 6: Taiwan Data Source Integration

**目標**: 補上結構化台股資料（月營收、財務比率）作為輔助基準

---

## Phase 7: Governance Layer

**目標**: 導入 evidence discipline，每個 claim 都有 claim_level 與 evidence 狀態

**Claim Levels**: `observed_fact` / `derived_metric` / `interpretation` / `hypothesis` / `insufficient_evidence`

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
| 2026-05-13 | 專案啟動，governance 導入，PLAN.md 建立 |
