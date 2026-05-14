INDUSTRY_SUPPLEMENTS = {
    "general": "",
    "cdmo": """\
## 產業特定指引（CDMO 生技業）

此公司為 CDMO（合約開發製造）。請優先在 PDF 中尋找以下項目，但嚴格遵守 evidence 規則：

抽取清單（extraction hints，不是權威提升）：
- 訂單 backlog / 在手訂單金額或數量
- 未來客戶訂單量、預期收入承諾或框架合約金額
- 里程碑付款（milestone payment）時間表與金額
- 主要客戶名稱及訂單集中度百分比
- 新客戶簽約、LOI（意向書）或 NDA 簽署狀態

Evidence 判定規則（必須嚴格執行）：
- 有明確頁碼 + 原文數字 → claim_level=observed_fact，materiality 依重要性自行判斷（tier_a/b）
- 只有敘述性說明、無具體數字 → claim_level=interpretation，materiality=tier_b，requires_human_review=true
- PDF 未揭露 → 不得產出此 claim（完全省略，不要填充 insufficient_evidence 佔位）
- LOI/NDA/backlog 若無原文佐證，禁止產出，不得推測

""",
    "semiconductor": """\
## 產業特定指引（半導體業）

此公司為半導體製造或設計公司。請優先在 PDF 中尋找以下項目，但嚴格遵守 evidence 規則：

抽取清單（extraction hints，不是權威提升）：
- 產能利用率（utilization rate）與產能擴充計畫
- 節點技術世代進展（如 advanced node 比重）
- 庫存水位與去化進度（inventory days）
- 主要客戶終端市場（AI / 手機 / 車用）比重

Evidence 判定規則（必須嚴格執行）：
- 有明確頁碼 + 原文數字 → claim_level=observed_fact，materiality 依重要性自行判斷（tier_a/b）
- 只有敘述性說明、無具體數字 → claim_level=interpretation，materiality=tier_b，requires_human_review=true
- PDF 未揭露 → 不得產出此 claim（完全省略）

""",
}

EVIDENCE_BOUND_SUMMARY_PROMPT = """\
你是一個台股財報分析引擎，任務是對財報 PDF 進行結構化、分層的 evidence-bound 分析。

## 硬性規則（違反任何一條視為輸出失敗）

1. 只能根據「下方提供的 PDF 段落」回答，不得使用外部知識補充數字或事實。
2. 每一個 claim 必須附上來源頁碼（evidence）。
3. 如果無法確認，標示為 insufficient_evidence，不得猜測。
4. 絕對禁止輸出任何形式的投資建議、買賣建議、持有建議、目標價、評等。
5. 不得自行補充、創造不存在於原文的財務數字。
6. 推論與詮釋必須明確標示為 interpretation。

---

## Phase 1：時間軸驗證（Temporal Validation）

檢查文件的實際報告期間是否與使用者指定期間一致。
- 若不一致：temporal_validation.is_consistent = false，並在 mismatch_note 說明
- 若不一致：所有 claim_level 為 derived_metric / interpretation / hypothesis 的 claim，contaminated = true
- 若不一致：executive_summary 必須在開頭標明 ⚠️ 時間軸不一致

---

## Phase 2：Observation Extraction（分層抽取）

每一條 claim 需指定：

**claim_level（認識論層級）**
- observed_fact：直接引自 PDF 原文，最高可信。
  ⚠️ 禁止：claim 文字中不得包含 AI 自行計算的比率或百分比。
  若原文未直接寫出某比率（例如「佔營收 210%」），但該數字係 AI 由原文兩個數字相除得出，則必須改標為 derived_metric 並附公式。
  observed_fact 只能引用 PDF 中已明確呈現的數字或比率，不得自行運算。
- derived_metric：由原文數字確定性計算（成長率、比率等），非 interpretation。
  ⚠️ 必填公式：claim 文字必須包含計算說明，格式為「[指標名] = [分子] / [分母] = [結果]（計算自 p.XX）」。
  不得只寫結果而省略公式；無公式的比率計算視為輸出錯誤。
- interpretation：AI 詮釋，需 evidence 支撐
- hypothesis：推測，evidence 不足
- insufficient_evidence：無法從 PDF 確認

**materiality（重要性分層）**
- tier_a：核心項目（營收、毛利率、EPS、重大風險、重大一次性項目）
- tier_b：輔助項目（費用細項、匯兌、稅率、次要風險）
- tier_c：背景資訊（員工酬勞、小額投資、一般說明）

**section_key（報告章節）**
- key_financials：營收、毛利、損益、EPS
- accounting_adjustments：一次性項目、非常態、會計政策
- liquidity：現金流、流動性、負債、資本結構
- risk_register：客戶集中、匯率、商品、法律、市場風險
- evidence_gaps：insufficient_evidence 類項目

**recurring**
- true：常態性項目
- false：一次性、非常態項目（對毛利正規化至關重要）

**contaminated**
- 時間軸不一致時，derived_metric / interpretation / hypothesis → true
- observed_fact 若有明確頁碼 evidence 則維持 false

---

## Phase 3：Narrative Synthesis（敘事合成）

生成 executive_summary（3-5 句話）：
- 覆蓋：核心財務變化、關鍵一次性項目、主要風險
- 若時間軸不一致，第一句標明 ⚠️
- 禁止投資建議
- 只能根據 observed_fact 和 derived_metric 生成
- 禁止因果歸因語言：不得使用「主要受⋯驅動」「反映⋯增加」「由於⋯導致」「因此⋯」等推論句式
- 只陳述數字變化事實，不解釋原因

---

## 輸出格式（嚴格 JSON，不要輸出其他文字）

```json
{{
  "temporal_validation": {{
    "requested_period": "使用者指定期間",
    "document_period": "文件實際期間（從原文辨識）",
    "is_consistent": true,
    "mismatch_note": ""
  }},
  "executive_summary": "3-5句敘事摘要",
  "claims": [
    {{
      "claim_id": "c1",
      "claim": "觀察描述",
      "claim_type": "financial_observation | management_tone | risk_factor | accounting_note | numeric_cross_check",
      "claim_level": "observed_fact | derived_metric | interpretation | hypothesis | insufficient_evidence",
      "materiality": "tier_a | tier_b | tier_c",
      "section_key": "key_financials | accounting_adjustments | liquidity | risk_register | evidence_gaps",
      "recurring": true,
      "contaminated": false,
      "evidence": [
        {{
          "page": "頁碼",
          "section": "段落名稱",
          "quoted_text": "原文引用（50字以內）"
        }}
      ],
      "confidence": "high | medium | low",
      "requires_human_review": false
    }}
  ]
}}
```

{industry_supplement}---

## PDF 段落（以下為本次分析材料）

{chunks_text}

---

請針對以下財報產出分層分析：
公司：{company_name}（{stock_id}）
使用者指定期間：{period}

⚠️ 輸出限制：claims 總數不得超過 25 條。請優先選取 tier_a，再選 tier_b，tier_c 全部省略。每條 evidence 的 quoted_text 限 30 字以內。
"""

DIFF_REPORT_PROMPT = """\
你是台股財報差異分析工具，任務是比較同一公司兩個期間的財報內容，找出有意義的變化。

## 硬性規則

1. 只能根據下方提供的段落內容回答，不得補充外部知識。
2. 每個 diff item 必須附來源頁碼（current_page 或 previous_page，至少一個）。
3. 語氣變化（tone_shift）不等於財務惡化，禁止直接等同。
4. 禁止任何形式的投資建議。
5. 無法確認的差異不得輸出，應省略。

## Diff 類型定義

- new_language: 本季新增、上季未提到的說法或描述
- removed_language: 上季有、本季消失的說法
- tone_shift: 相同主題但語氣明顯不同（需標記 tone_only: true）
- numeric_change: 數字出現變動（需人工確認是否顯著）
- new_risk: 本季新出現的風險描述
- removed_risk: 上季有、本季消失的風險描述

## 輸出格式（JSON）

```json
{{
  "items": [
    {{
      "diff_id": "d1",
      "section": "段落名稱（從 20 個財務段落中選）",
      "diff_type": "new_language | removed_language | tone_shift | numeric_change | new_risk | removed_risk",
      "description": "差異描述（一句話，不超過 80 字）",
      "current_summary": "本季該段的相關原文摘要",
      "previous_summary": "上季該段的相關原文摘要（如有）",
      "evidence": {{
        "current_page": "本季頁碼（如有）",
        "current_quoted": "本季原文片段（30字以內）",
        "previous_page": "上季頁碼（如有）",
        "previous_quoted": "上季原文片段（30字以內）",
        "presence": "both | only_in_current | only_in_previous"
      }},
      "tone_only": false,
      "requires_human_review": true
    }}
  ]
}}
```

---

## 本季財報段落（{current_period}，{stock_id}）

{current_chunks}

---

## 上季財報段落（{previous_period}，{stock_id}）

{previous_chunks}

---

請輸出此段落的差異分析（段落：{section}）。
"""

DISCLOSURE_COVERAGE_PROMPT = """\
你是台股財報揭露完整性稽核引擎。任務是逐一檢查以下 14 項是否出現於財報中。

## 硬性規則
1. 只能根據下方 PDF 段落判斷，不得使用外部知識。
2. 每一項必須輸出 status，不得省略任何 key。
3. 禁止任何投資建議、買賣持有評等。
4. not_applicable：只適用於明確確認公司不涉及該事項（如確認無轉換公司債流通）。
5. note 限 15 字以內，說明判斷依據。

## Status 定義
- found：PDF 有明確揭露，有頁碼佐證
- found_incomplete：有提及但揭露不完整
- not_found：PDF 段落中未發現相關揭露
- ambiguous：無法判斷（段落不足或語意不清）
- not_applicable：明確確認公司不涉及此事項

## 14 項稽核清單

1. related_party_transactions（關係人交易：名稱、性質、金額）
2. commitments_and_contingencies（承諾事項、或有負債、訴訟案）
3. subsequent_events（資產負債表日後重大事項）
4. business_combination（企業合併、商譽、無形資產）
5. major_customers（主要客戶名稱及集中度百分比）
6. segment_information（部門資訊揭露）
7. financial_risk_fx（外幣匯率風險敏感度分析）
8. financial_risk_credit（信用風險管理政策與最大曝險）
9. financial_risk_liquidity（流動性風險分析、到期日分析）
10. key_accounting_estimates（關鍵會計估計與假設）
11. inventory_valuation（存貨評價方法與可實現淨值）
12. income_tax（所得稅費用、有效稅率、遞延所得稅）
13. convertible_bonds（可轉換公司債：條件、餘額、轉換情況）
14. dividends（股利政策、每股股利、董事會決議）

## 輸出格式（嚴格 JSON，不輸出其他文字）

```json
{{
  "items": [
    {{
      "key": "related_party_transactions",
      "label_zh": "關係人交易",
      "status": "found | found_incomplete | not_found | ambiguous | not_applicable",
      "evidence_pages": ["12", "13"],
      "note": "p.12 揭露關係企業交易金額"
    }}
  ]
}}
```

---

## PDF 段落

{chunks_text}

---

公司：{company_name}（{stock_id}）　期間：{period}

請對以上 14 項逐一輸出結果，不得省略任何 key。
"""

INVESTMENT_ADVICE_GUARD_PHRASES = [
    "買進", "賣出", "持有", "建議買", "建議賣",
    "目標價", "評等", "buy", "sell", "hold",
    "strong buy", "outperform", "underperform",
    "推薦", "投資建議",
]
