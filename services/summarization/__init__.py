"""
Summarization Service — Phase 2 + Semantic Layering
-----------------------------------------------------
呼叫 Claude API，產出 evidence-bound 財報摘要。

架構：
1. Temporal Validation  — 時間軸一致性檢查，不一致時標記 contaminated
2. Observation Extraction — 分層抽取（claim_level + materiality + section_key）
3. Narrative Synthesis  — executive_summary

Evidence discipline：
- 每個 claim 必須有 evidence，否則自動降級為 insufficient_evidence
- 若 AI 輸出含投資建議詞彙，整份 report 標記 investment_advice_detected=True
- contaminated=True 的 claim 不納入 evidence_status 計算
"""
import json
import re
import uuid

import anthropic

from config.config import AnthropicConfig
from models.documents import PDFDocument, PDFChunk
from models.reports import AIReport, AIClaim, ClaimEvidence
from services.dashboard_contract import (
    DASHBOARD_CONTRACT_VERSION,
    METRIC_TYPE,
    TREND_ENUM,
    serialize_summary_response,
    validate_dashboard_contract_v1,
)
from prompts import (
    EVIDENCE_BOUND_SUMMARY_PROMPT, INVESTMENT_ADVICE_GUARD_PHRASES,
    INDUSTRY_SUPPLEMENTS, RHETORICAL_RISK_PHRASES, FORWARD_LOOKING_INDICATOR_PHRASES,
)

_client = None


_METRIC_REGISTRY = {
    "revenue": ["營收", "收入", "revenue"],
    "gross_margin": ["毛利率", "gross margin"],
    "operating_income": ["營業利益", "operating income", "營業淨利"],
    "eps": ["eps", "每股盈餘", "每股"],
    "cash": ["現金", "cash"],
    "debt": ["負債", "借款", "debt"],
    "fx": ["匯率", "匯兌", "fx"],
    "customer_concentration": ["客戶集中", "單一客戶", "concentration"],
}


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=AnthropicConfig.API_KEY)
    return _client


def _retrieve_chunks(document_id: str, max_chunks: int = 60) -> list[PDFChunk]:
    return list(
        PDFChunk.objects(document_id=document_id)
        .order_by("page")
        .limit(max_chunks)
    )


def _build_chunks_text(chunks: list[PDFChunk]) -> str:
    parts = []
    for c in chunks:
        parts.append(f"[p.{c.page}]\n{c.text}")
    return "\n\n---\n\n".join(parts)


def _check_investment_advice(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in INVESTMENT_ADVICE_GUARD_PHRASES)


_VALID_CLAIM_TYPE = {"financial_observation", "management_tone", "risk_factor", "accounting_note", "numeric_cross_check"}
_VALID_CLAIM_LEVEL = {"observed_fact", "derived_metric", "interpretation", "hypothesis", "insufficient_evidence"}
_VALID_MATERIALITY = {"tier_a", "tier_b", "tier_c"}
_VALID_SECTION_KEY = {"key_financials", "accounting_adjustments", "liquidity", "risk_register", "pipeline", "evidence_gaps"}
_VALID_SOURCE_TYPE = {"financial_evidence", "operational_evidence", "strategic_narrative", "management_expectation"}
_VALID_CONFIDENCE = {"high", "medium", "low"}

# Keywords triggering OC-1 (non-recurring COGS/gross-margin items)
_OC1_TRIGGER_KEYWORDS = ["迴轉利益", "跌價損失", "存貨跌價", "減損損失", "不動產減損", "廠房減損"]
# Keywords triggering OC-2 liquidity items (debt/dividend side)
_OC2_CASH_KEYWORDS = ["現金", "約當現金", "cash", "cash balance", "cash equivalent"]
_OC2_DEBT_KEYWORDS = [
    "短期借款",
    "長期借款",
    "一年內到期長期負債",
    "借款",
    "流動負債",
    "公司債",
    "應付公司債",
    "可轉債",
    "可轉換公司債",
    "商業本票",
    "ECB",
    "convertible bond",
    "corporate bond",
    "應付股利",
]
# Keywords indicating OC-1 adjustment already present
_OC1_ADJUSTMENT_KEYWORDS = ["調整後毛利率", "排除此項目"]
# Keywords indicating OC-2 safety margin already present
_OC2_SAFETY_KEYWORDS = ["安全墊", "現金安全墊", "liquidity_safety_margin"]


def _contains_any(text: str, keywords: list[str]) -> bool:
    lower = (text or "").lower()
    return any(kw.lower() in lower for kw in keywords)


def _check_completeness(claims: list[AIClaim]) -> list[str]:
    """
    Post-processing completeness validator.
    OC-1: non-recurring gross-margin items → require adjustment derived_metric
    OC-2: cash + debt/dividend coexist → require safety margin derived_metric
    Returns list of warning strings (empty = all complete).
    """
    warnings: list[str] = []

    # OC-1 check
    oc1_triggers = [
        c for c in claims
        if not c.recurring
        and c.section_key in ("accounting_adjustments", "key_financials")
        and any(kw in c.claim for kw in _OC1_TRIGGER_KEYWORDS)
    ]
    has_oc1_adjustment = any(
        c.claim_level == "derived_metric"
        and c.section_key == "accounting_adjustments"
        and any(kw in c.claim for kw in _OC1_ADJUSTMENT_KEYWORDS)
        for c in claims
    )
    if oc1_triggers and not has_oc1_adjustment:
        trigger_names = [c.claim[:30] for c in oc1_triggers[:2]]
        warnings.append(
            f"OC-1: 存在非常態毛利項目（{'; '.join(trigger_names)}...）但缺少調整後毛利率 derived_metric"
        )

    # OC-2 check
    has_cash_claim = any(
        c.section_key == "liquidity" and _contains_any(c.claim, _OC2_CASH_KEYWORDS)
        for c in claims
    )
    has_debt_claim = any(
        c.section_key == "liquidity"
        and _contains_any(c.claim, _OC2_DEBT_KEYWORDS)
        for c in claims
    )
    has_oc2_safety = any(
        c.claim_level == "derived_metric"
        and c.section_key == "liquidity"
        and _contains_any(c.claim, _OC2_SAFETY_KEYWORDS)
        for c in claims
    )
    if has_cash_claim and has_debt_claim and not has_oc2_safety:
        warnings.append(
            "OC-2: 現金與短借/可轉債/股利並存但缺少現金安全墊 derived_metric（liquidity）"
        )

    return warnings


def _parse_claims(raw_json: dict, document_id: str, temporal_consistent: bool) -> list[AIClaim]:
    claims = []
    for item in raw_json.get("claims", []):
        evidence_list = []
        for ev in item.get("evidence", []):
            evidence_list.append(
                ClaimEvidence(
                    document_id=document_id,
                    page=str(ev.get("page", "unknown")),
                    section=ev.get("section", "unknown"),
                    quoted_text=ev.get("quoted_text", ""),
                )
            )

        # Governance: 沒有 evidence → 強制降級
        claim_level = item.get("claim_level", "interpretation")
        if claim_level not in _VALID_CLAIM_LEVEL:
            claim_level = "interpretation"
        if not evidence_list and claim_level not in ("insufficient_evidence",):
            claim_level = "insufficient_evidence"

        # Temporal contamination enforcement
        contaminated = item.get("contaminated", False)
        if not temporal_consistent and claim_level in ("derived_metric", "interpretation", "hypothesis"):
            contaminated = True

        # Source type governance
        source_type = item.get("source_type", "financial_evidence")
        if source_type not in _VALID_SOURCE_TYPE:
            source_type = "financial_evidence"
        forward_looking = item.get("forward_looking", False)
        confidence = item.get("confidence", "medium")
        if confidence not in _VALID_CONFIDENCE:
            confidence = "medium"
        requires_human_review = item.get("requires_human_review", False)

        # Governance: narrative source types 不得為 observed_fact → 強制降為 interpretation
        if source_type in ("strategic_narrative", "management_expectation") and claim_level == "observed_fact":
            claim_level = "interpretation"

        # Governance: management_expectation confidence 上限 = medium
        if source_type == "management_expectation" and confidence == "high":
            confidence = "medium"

        # Governance: forward_looking → requires_human_review
        if forward_looking:
            requires_human_review = True

        # Forward-looking implication guard: auto-detect on narrative types
        # Overrides Claude's forward_looking=False if indicator words are found.
        if not forward_looking and source_type in ("strategic_narrative", "management_expectation"):
            claim_text = item.get("claim", "")
            if any(p in claim_text for p in FORWARD_LOOKING_INDICATOR_PHRASES):
                forward_looking = True
                requires_human_review = True

        # Rhetorical risk scan: only for narrative source types
        rhetorical_risk_flag = False
        rhetorical_risk_terms = []
        if source_type in ("strategic_narrative", "management_expectation"):
            claim_text = item.get("claim", "")
            hits = [phrase for phrase in RHETORICAL_RISK_PHRASES if phrase in claim_text]
            if hits:
                rhetorical_risk_flag = True
                rhetorical_risk_terms = hits

        # Quotation layer: attribution prefix for narrative source types (fail-closed, service-enforced)
        _ATTRIBUTION_MAP = {
            "strategic_narrative": "公司宣稱：",
            "management_expectation": "管理層表示：",
        }
        attribution_prefix = _ATTRIBUTION_MAP.get(source_type, "")

        claim_type = item.get("claim_type", "financial_observation")
        if claim_type not in _VALID_CLAIM_TYPE:
            claim_type = "financial_observation"
        materiality = item.get("materiality", "tier_b")
        if materiality not in _VALID_MATERIALITY:
            materiality = "tier_b"
        section_key = item.get("section_key", "key_financials")
        if section_key not in _VALID_SECTION_KEY:
            section_key = "key_financials"

        claims.append(
            AIClaim(
                claim_id=item.get("claim_id", str(uuid.uuid4())),
                claim=item.get("claim", ""),
                claim_type=claim_type,
                claim_level=claim_level,
                materiality=materiality,
                section_key=section_key,
                recurring=item.get("recurring", True),
                contaminated=contaminated,
                source_type=source_type,
                forward_looking=forward_looking,
                rhetorical_risk_flag=rhetorical_risk_flag,
                rhetorical_risk_terms=rhetorical_risk_terms,
                attribution_prefix=attribution_prefix,
                evidence=evidence_list,
                confidence=confidence,
                requires_human_review=requires_human_review,
            )
        )
    return claims


def _match_metric(claim_text: str) -> str | None:
    lower = (claim_text or "").lower()
    for metric, keywords in _METRIC_REGISTRY.items():
        if any(kw.lower() in lower for kw in keywords):
            return metric
    return None


def _extract_delta(claim_text: str) -> float | None:
    if not claim_text:
        return None
    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(pp|%)", claim_text.lower())
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    if "下降" in claim_text or "減少" in claim_text or "drop" in claim_text.lower() or "down" in claim_text.lower():
        val = -abs(val)
    elif "增加" in claim_text or "成長" in claim_text or "up" in claim_text.lower():
        val = abs(val)
    return val


def _direction_from_text(claim_text: str, delta: float | None) -> str:
    if delta is not None:
        if delta > 0:
            return "up"
        if delta < 0:
            return "down"
        return "flat"
    lower = (claim_text or "").lower()
    if any(x in lower for x in ["下降", "減少", "衰退", "drop", "down"]):
        return "down"
    if any(x in lower for x in ["增加", "成長", "提升", "up", "increase"]):
        return "up"
    return "flat"


_METRIC_BASE_IMPACT: dict[str, str] = {
    "gross_margin":           "high",
    "operating_income":       "high",
    "eps":                    "high",
    "revenue":                "medium",
    "cash":                   "medium",
    "debt":                   "medium",
    "fx":                     "low",
    "customer_concentration": "low",
}
_IMPACT_RANK  = {"high": 2, "medium": 1, "low": 0}
_IMPACT_LABEL = {2: "high", 1: "medium", 0: "low"}
_DOWN_ESCALATE_METRICS = {"revenue", "cash"}


def _calc_impact(metric_id: str, delta_pct: float | None, direction: str) -> str:
    """Multi-factor materiality: base importance + delta magnitude + directional risk."""
    base = _METRIC_BASE_IMPACT.get(metric_id, "medium")
    rank = _IMPACT_RANK[base]
    if delta_pct is not None:
        abs_delta = abs(delta_pct)
        if abs_delta >= 15:
            rank = min(rank + 1, 2)
        elif abs_delta < 2:
            rank = max(rank - 1, 0)
    if direction == "down" and metric_id in _DOWN_ESCALATE_METRICS:
        if delta_pct is not None and abs(delta_pct) >= 10:
            rank = min(rank + 1, 2)
    return _IMPACT_LABEL[rank]


def _build_dashboard_payload(
    clean_claims: list[AIClaim],
    all_claims: list[AIClaim],
    temporal_consistent: bool,
    narrative_flag: bool,
    narrative_density_score: float,
    narrative_density_weighted_score: float,
) -> dict:
    metrics: dict[str, dict] = {}
    for c in clean_claims:
        metric = _match_metric(c.claim)
        if not metric:
            continue
        delta = _extract_delta(c.claim)
        direction = _direction_from_text(c.claim, delta)
        priority = {"tier_a": 3, "tier_b": 2, "tier_c": 1}.get(c.materiality, 1)
        current = metrics.get(metric)
        if current and current["priority"] > priority:
            continue
        metrics[metric] = {
            "metric_id": metric,
            "metric_type": METRIC_TYPE.get(metric, "other"),
            "label": metric.replace("_", " ").title(),
            "direction": direction,
            "delta_pct": delta,
            "evidence_claim_ids": [c.claim_id],
            "priority": priority,
            "claim_text": c.claim,
            "confidence": c.confidence,
        }

    what_changed = []
    for key in ["revenue", "gross_margin", "operating_income", "eps", "cash"]:
        if key in metrics:
            m = metrics[key]
            what_changed.append(
                {
                    "metric_id": m["metric_id"],
                    "metric_type": m["metric_type"],
                    "label": m["label"],
                    "direction": m["direction"],
                    "delta_pct": m["delta_pct"],
                    "evidence_claim_ids": m["evidence_claim_ids"],
                    "impact": _calc_impact(key, m["delta_pct"], m["direction"]),
                    "claim_text": m["claim_text"],
                    "confidence": m["confidence"],
                }
            )

    causal_edges = []
    if "revenue" in metrics and "gross_margin" in metrics:
        causal_edges.append(
            {
                "source_metric": "revenue",
                "target_metric": "gross_margin",
                "relation": "positive_driver",
                "confidence": "medium",
                "evidence_claim_ids": metrics["revenue"]["evidence_claim_ids"] + metrics["gross_margin"]["evidence_claim_ids"],
            }
        )
    if "gross_margin" in metrics and "operating_income" in metrics:
        causal_edges.append(
            {
                "source_metric": "gross_margin",
                "target_metric": "operating_income",
                "relation": "positive_driver",
                "confidence": "high",
                "evidence_claim_ids": metrics["gross_margin"]["evidence_claim_ids"] + metrics["operating_income"]["evidence_claim_ids"],
            }
        )
    if "operating_income" in metrics and "eps" in metrics:
        causal_edges.append(
            {
                "source_metric": "operating_income",
                "target_metric": "eps",
                "relation": "positive_driver",
                "confidence": "high",
                "evidence_claim_ids": metrics["operating_income"]["evidence_claim_ids"] + metrics["eps"]["evidence_claim_ids"],
            }
        )

    adjustments = [
        {
            "claim_id": c.claim_id,
            "claim": c.claim,
            "metric_id": _match_metric(c.claim),
            "evidence_claim_ids": [c.claim_id],
            "requires_human_review": bool(c.requires_human_review),
            "comparability": "low",
        }
        for c in clean_claims
        if not c.recurring
    ]

    gross_margin_drop = next((abs(w["delta_pct"]) for w in what_changed if w["metric_id"] == "gross_margin" and w["delta_pct"] is not None and w["delta_pct"] < 0), 0.0)
    cash_claims = [c for c in clean_claims if _match_metric(c.claim) == "cash"]
    fx_claims = [c for c in clean_claims if _match_metric(c.claim) == "fx"]
    concentration_claims = [c for c in clean_claims if _match_metric(c.claim) == "customer_concentration"]

    risk_surface = [
        {
            "risk_id": "customer_concentration",
            "label": "Customer concentration",
            "severity": "high" if concentration_claims else "medium",
            "severity_reason": "customer_concentration_claim_present" if concentration_claims else "no_explicit_ratio_claim",
            "trend": "up" if concentration_claims else "flat",
            "evidence_claim_ids": [c.claim_id for c in concentration_claims[:3]],
            "rule_id": "RISK-CUST-001",
        },
        {
            "risk_id": "margin_pressure",
            "label": "Margin pressure",
            "severity": "high" if gross_margin_drop >= 10 else ("medium" if gross_margin_drop >= 5 else "low"),
            "severity_reason": f"gross_margin_drop_pp={gross_margin_drop}",
            "trend": "up" if gross_margin_drop > 0 else "flat",
            "evidence_claim_ids": [m["evidence_claim_ids"][0] for m in what_changed if m["metric_id"] == "gross_margin"],
            "rule_id": "RISK-MARGIN-010PP",
        },
        {
            "risk_id": "liquidity",
            "label": "Liquidity pressure",
            "severity": "medium" if (not cash_claims) else "low",
            "severity_reason": "cash_claim_missing" if not cash_claims else "cash_claim_present",
            "trend": "up" if not cash_claims else "flat",
            "evidence_claim_ids": [c.claim_id for c in cash_claims[:3]],
            "rule_id": "RISK-LIQ-001",
        },
        {
            "risk_id": "fx_exposure",
            "label": "FX exposure",
            "severity": "medium" if fx_claims else "low",
            "severity_reason": "fx_claim_present" if fx_claims else "fx_claim_missing",
            "trend": "up" if fx_claims else "flat",
            "evidence_claim_ids": [c.claim_id for c in fx_claims[:3]],
            "rule_id": "RISK-FX-001",
        },
    ]

    contaminated_count = sum(1 for c in all_claims if c.contaminated)
    transparency = {
        "evidence_coverage_pct": round((sum(1 for c in clean_claims if c.evidence) / len(clean_claims)) * 100, 1) if clean_claims else 0.0,
        "temporal_consistent": temporal_consistent,
        "non_recurring_count": len(adjustments),
        "contaminated_count": contaminated_count,
        "narrative_density_score": narrative_density_score,
        "narrative_density_weighted_score": narrative_density_weighted_score,
        "narrative_flag": narrative_flag,
        "human_review_count": sum(1 for c in clean_claims if c.requires_human_review),
    }

    return {
        "contract_version": DASHBOARD_CONTRACT_VERSION,
        "metrics": [v for v in metrics.values()],
        "what_changed": what_changed,
        "causal_edges": causal_edges,
        "adjustments": adjustments,
        "risk_surface": risk_surface,
        "transparency": transparency,
    }


def generate_summary(document_id: str) -> dict:
    """
    主流程：取 chunks → 呼叫 Claude → Temporal Validation → 分層抽取 → 存 AIReport
    """
    doc = PDFDocument.objects(document_id=document_id).first()
    if not doc:
        raise ValueError(f"Document not found: {document_id}")

    if doc.status != "completed":
        raise ValueError(f"Document not yet ingested (status={doc.status}). Run /ingest first.")

    chunks = _retrieve_chunks(document_id)
    if not chunks:
        raise ValueError("No chunks found. Run /ingest first.")

    chunks_text = _build_chunks_text(chunks)
    industry_type = getattr(doc, 'industry_type', 'general') or 'general'
    supplement = INDUSTRY_SUPPLEMENTS.get(industry_type, "")
    prompt = EVIDENCE_BOUND_SUMMARY_PROMPT.format(
        chunks_text=chunks_text,
        company_name=doc.company_name,
        stock_id=doc.stock_id,
        period=doc.period,
        industry_supplement=supplement,
    )

    client = _get_client()
    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        raise RuntimeError(f"Claude API 錯誤 ({type(e).__name__}): {e}") from e

    try:
        raw_text = message.content[0].text
    except (IndexError, AttributeError) as e:
        raise RuntimeError(f"Claude 回傳內容為空或格式不符: {e}") from e

    # 抽出 JSON block
    try:
        json_start = raw_text.index("{")
        json_end = raw_text.rindex("}") + 1
        raw_json = json.loads(raw_text[json_start:json_end])
    except (ValueError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Claude 回傳格式無法解析: {e}\n原文: {raw_text[:500]}") from e

    # --- Temporal Validation ---
    tv = raw_json.get("temporal_validation", {})
    temporal_consistent = tv.get("is_consistent", True)
    temporal_note = tv.get("mismatch_note", "")
    document_period = tv.get("document_period", doc.period)
    requested_period = tv.get("requested_period", doc.period)

    # Guard: if user did not explicitly provide a requested period, do NOT treat as mismatch.
    # This prevents false contamination cascades when upload flow allows optional period.
    _unknown_tokens = {"", "unknown", "UNKNOWN", "n/a", "N/A", "null", "None"}
    requested_missing = str(requested_period).strip() in _unknown_tokens
    if requested_missing:
        temporal_consistent = True
        temporal_note = ""
        requested_period = document_period

    # --- Executive Summary ---
    executive_summary = raw_json.get("executive_summary", "")

    # --- Claims ---
    claims = _parse_claims(raw_json, document_id, temporal_consistent)

    # Evidence status：只計算非 contaminated 的 claims
    clean_claims = [c for c in claims if not c.contaminated]
    total_clean = len(clean_claims)
    insufficient = sum(1 for c in clean_claims if c.claim_level == "insufficient_evidence")

    if total_clean == 0:
        evidence_status = "insufficient"
    elif insufficient == 0:
        evidence_status = "complete"
    elif insufficient < total_clean:
        evidence_status = "partial"
    else:
        evidence_status = "insufficient"

    # Narrative density governance
    _narrative_types = {"strategic_narrative", "management_expectation"}
    _non_gap = [c for c in clean_claims if c.claim_level != "insufficient_evidence"]
    narrative_count = sum(1 for c in _non_gap if c.source_type in _narrative_types)
    total_non_gap = len(_non_gap)
    narrative_density_score = round(narrative_count / total_non_gap, 2) if total_non_gap else 0.0

    # Text-length weighted density
    narrative_text_len = sum(len(c.claim) for c in _non_gap if c.source_type in _narrative_types)
    total_text_len = sum(len(c.claim) for c in _non_gap)
    narrative_density_weighted_score = round(narrative_text_len / total_text_len, 2) if total_text_len else 0.0

    narrative_flag = narrative_density_score > 0.6 or narrative_density_weighted_score > 0.6

    investment_advice_detected = _check_investment_advice(raw_text)

    # --- Output Completeness Validation (OC-1, OC-2) ---
    completeness_warnings = _check_completeness(claims)
    dashboard_payload = _build_dashboard_payload(
        clean_claims=clean_claims,
        all_claims=claims,
        temporal_consistent=temporal_consistent,
        narrative_flag=narrative_flag,
        narrative_density_score=narrative_density_score,
        narrative_density_weighted_score=narrative_density_weighted_score,
    )
    dashboard_contract_errors = validate_dashboard_contract_v1(dashboard_payload)
    dashboard_contract_valid = len(dashboard_contract_errors) == 0

    report = AIReport(
        report_id=str(uuid.uuid4()),
        document_id=document_id,
        stock_id=doc.stock_id,
        period=doc.period,
        report_type="single_summary",
        temporal_consistent=temporal_consistent,
        temporal_note=temporal_note,
        executive_summary=executive_summary,
        narrative_density_score=narrative_density_score,
        narrative_density_weighted_score=narrative_density_weighted_score,
        narrative_flag=narrative_flag,
        claims=claims,
        evidence_status=evidence_status,
        investment_advice_detected=investment_advice_detected,
        completeness_warnings=completeness_warnings,
        dashboard=dashboard_payload,
        dashboard_contract_valid=dashboard_contract_valid,
        dashboard_contract_errors=dashboard_contract_errors,
    )
    report.save()

    return serialize_summary_response(
        report,
        document_period=document_period,
        requested_period=requested_period,
    )
