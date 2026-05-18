"""
Governance Rules Engine — Phase 7
-----------------------------------
R1-R7 是系統的核心 evidence discipline，讓每個 AI 輸出可被稽核。

R1: 每個 claim 必須有 evidence
R2: 數字 claim（derived_metric）必須有 quoted_text 作為來源
R3: 沒有 evidence 時 claim_level 必須是 hypothesis 或 insufficient_evidence
R4: 不允許 investment recommendation（investment_advice_detected=True → 標記）
R5: 不允許跨文件推論未標示來源（evidence document_id 必須一致）
R6: 不允許把語氣變化直接說成財務惡化（DiffItem.tone_only 必須=True when tone_shift）
R7: 不允許用單季資料推論長期趨勢（掃描長期趨勢關鍵詞）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ── 長期趨勢關鍵詞（R7）──────────────────────────────────────────────────────
_R7_TREND_PHRASES = [
    "長期趨勢", "持續成長", "未來幾年", "長期而言", "趨勢持續",
    "long-term trend", "sustained growth", "over the next few years",
    "consistent growth", "trend will continue",
]

# ── 投資建議詞（R4 補充掃描）──────────────────────────────────────────────────
_R4_ADVICE_PHRASES = [
    "建議買入", "建議賣出", "建議持有", "投資建議", "目標價",
    "buy recommendation", "sell recommendation", "hold recommendation",
    "investment advice", "target price",
]


# ─────────────────────────────────────────────────────────────────────────────
# Violation dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GovernanceViolation:
    """一條 governance rule 違規記錄"""
    rule: Literal["R1", "R2", "R3", "R4", "R5", "R6", "R7"]
    description: str
    claim_id: str | None = None          # 哪個 claim 違規（如適用）
    severity: Literal["error", "warning"] = "error"
    auto_fixed: bool = False             # 是否已在 ingest/summary 時自動修正
    fix_description: str = ""


@dataclass
class GovernanceAuditResult:
    """一份 AIReport 的完整稽核結果"""
    report_id: str
    document_id: str
    total_claims: int
    violations: list[GovernanceViolation] = field(default_factory=list)
    warnings: list[GovernanceViolation] = field(default_factory=list)

    @property
    def violation_count(self) -> int:
        return len(self.violations)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    @property
    def passed(self) -> bool:
        """只有 0 個 error 才算通過（warning 不影響通過）"""
        return self.violation_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# Per-rule checkers
# ─────────────────────────────────────────────────────────────────────────────

def check_r1(claim_id: str, evidence: list) -> GovernanceViolation | None:
    """R1: 每個 claim 必須有 evidence（除非 claim_level=insufficient_evidence）"""
    if not evidence:
        return GovernanceViolation(
            rule="R1",
            claim_id=claim_id,
            description="Claim 沒有任何 evidence，R1 違規",
            severity="error",
        )
    return None


def check_r2(claim_id: str, claim_level: str, evidence: list) -> GovernanceViolation | None:
    """R2: derived_metric（數字 claim）必須有非空 quoted_text"""
    if claim_level != "derived_metric":
        return None
    has_source = any(str(e.get("quoted_text") or "").strip() for e in evidence)
    if not has_source:
        return GovernanceViolation(
            rule="R2",
            claim_id=claim_id,
            description="數字 claim（derived_metric）沒有 quoted_text 來源，R2 違規",
            severity="error",
        )
    return None


def check_r3(claim_id: str, claim_level: str, evidence: list) -> GovernanceViolation | None:
    """R3: 沒有 evidence 時 claim_level 必須是 hypothesis 或 insufficient_evidence"""
    if evidence:
        return None
    allowed_no_evidence_levels = {"hypothesis", "insufficient_evidence"}
    if claim_level not in allowed_no_evidence_levels:
        return GovernanceViolation(
            rule="R3",
            claim_id=claim_id,
            description=(
                f"Claim 沒有 evidence 但 claim_level={claim_level!r}，"
                "應為 hypothesis 或 insufficient_evidence，R3 違規"
            ),
            severity="error",
            auto_fixed=True,
            fix_description="summarization service 已於 generate_summary() 自動降級",
        )
    return None


def check_r4_report(investment_advice_detected: bool) -> GovernanceViolation | None:
    """R4: investment_advice_detected=True 代表報告含投資建議，標記為 error"""
    if investment_advice_detected:
        return GovernanceViolation(
            rule="R4",
            claim_id=None,
            description="報告含投資建議詞彙（investment_advice_detected=True），R4 違規",
            severity="error",
        )
    return None


def check_r4_claim(claim_id: str, claim_text: str) -> GovernanceViolation | None:
    """R4: claim 文字本身含投資建議詞彙"""
    lower = claim_text.lower()
    found = [p for p in _R4_ADVICE_PHRASES if p.lower() in lower]
    if found:
        return GovernanceViolation(
            rule="R4",
            claim_id=claim_id,
            description=f"Claim 含投資建議詞彙 {found}，R4 違規",
            severity="error",
        )
    return None


def check_r5(claim_id: str, document_id: str, evidence: list) -> GovernanceViolation | None:
    """R5: evidence 的 document_id 必須與報告 document_id 一致（防止未標示跨文件推論）"""
    for ev in evidence:
        ev_doc = str(ev.get("document_id") or "")
        if ev_doc and ev_doc != document_id:
            return GovernanceViolation(
                rule="R5",
                claim_id=claim_id,
                description=(
                    f"Evidence 引用了不同文件 document_id={ev_doc!r}，"
                    "跨文件推論必須明確標示，R5 違規"
                ),
                severity="warning",
            )
    return None


def check_r7_claim(claim_id: str, claim_text: str) -> GovernanceViolation | None:
    """R7: claim 含長期趨勢關鍵詞（單季資料不得推論長期趨勢）"""
    lower = claim_text.lower()
    found = [p for p in _R7_TREND_PHRASES if p.lower() in lower]
    if found:
        return GovernanceViolation(
            rule="R7",
            claim_id=claim_id,
            description=f"Claim 含長期趨勢推論詞彙 {found}，單季資料不可用於長期趨勢判斷，R7 違規",
            severity="warning",
        )
    return None


def check_r6_diff(diff_id: str, diff_type: str, tone_only: bool) -> GovernanceViolation | None:
    """R6: tone_shift diff item must be explicitly marked tone_only=True."""
    if diff_type != "tone_shift":
        return None
    if tone_only:
        return None
    return GovernanceViolation(
        rule="R6",
        claim_id=diff_id,
        description="tone_shift item must set tone_only=True to avoid financial-overstatement drift",
        severity="error",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main audit function
# ─────────────────────────────────────────────────────────────────────────────

def audit_claims(
    report_id: str,
    document_id: str,
    claims: list[dict],
    investment_advice_detected: bool,
) -> GovernanceAuditResult:
    """
    對一份 AIReport 的所有 claims 執行 R1-R7 稽核。

    claims: list of dicts with keys:
        claim_id, claim, claim_level, claim_type, evidence (list of dicts)
    """
    result = GovernanceAuditResult(
        report_id=report_id,
        document_id=document_id,
        total_claims=len(claims),
    )

    # R4: report-level check
    v = check_r4_report(investment_advice_detected)
    if v:
        result.violations.append(v)

    for c in claims:
        cid = c.get("claim_id", "unknown")
        claim_text = c.get("claim", "")
        claim_level = c.get("claim_level", "interpretation")
        evidence = c.get("evidence", [])

        # R1
        v = check_r1(cid, evidence)
        if v:
            result.violations.append(v)

        # R2
        v = check_r2(cid, claim_level, evidence)
        if v:
            result.violations.append(v)

        # R3
        v = check_r3(cid, claim_level, evidence)
        if v:
            # R3 violations that were auto-fixed are warnings, not errors
            if v.auto_fixed:
                result.warnings.append(v)
            else:
                result.violations.append(v)

        # R4: claim-level
        v = check_r4_claim(cid, claim_text)
        if v:
            result.violations.append(v)

        # R5
        v = check_r5(cid, document_id, evidence)
        if v:
            result.warnings.append(v)

        # R7
        v = check_r7_claim(cid, claim_text)
        if v:
            result.warnings.append(v)

    return result


def audit_diff_items(
    report_id: str,
    document_id: str,
    items: list[dict],
) -> GovernanceAuditResult:
    """Audit diff items with R6 guard."""
    result = GovernanceAuditResult(
        report_id=report_id,
        document_id=document_id,
        total_claims=len(items),
    )
    for item in items:
        diff_id = item.get("diff_id", "unknown")
        diff_type = item.get("diff_type", "")
        tone_only = bool(item.get("tone_only", False))
        v = check_r6_diff(diff_id, diff_type, tone_only)
        if v:
            result.violations.append(v)
    return result
