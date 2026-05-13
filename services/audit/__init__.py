"""
Audit Service — Phase 7
-------------------------
從 MongoDB 取出 AIReport，執行 R1-R7 governance 稽核，回傳可讀稽核報告。
"""
from __future__ import annotations

from models.reports import AIReport
from core.governance import audit_claims, GovernanceAuditResult


def _claim_to_dict(claim) -> dict:
    """把 AIClaim EmbeddedDocument 轉成可傳給 audit_claims 的 dict"""
    return {
        "claim_id": claim.claim_id,
        "claim": claim.claim,
        "claim_level": claim.claim_level,
        "claim_type": claim.claim_type,
        "evidence": [
            {
                "document_id": e.document_id,
                "page": e.page,
                "section": e.section,
                "quoted_text": e.quoted_text,
            }
            for e in claim.evidence
        ],
    }


def run_audit(document_id: str, report_id: str | None = None) -> dict:
    """
    對指定文件的 AIReport 執行完整 governance 稽核。
    若 report_id 為 None，取最新一份報告。

    Returns dict with full audit results.
    """
    if report_id:
        report = AIReport.objects(report_id=report_id, document_id=document_id).first()
    else:
        report = (
            AIReport.objects(document_id=document_id)
            .order_by("-created_at")
            .first()
        )

    if not report:
        raise ValueError(f"AIReport not found for document_id={document_id}")

    claims_dicts = [_claim_to_dict(c) for c in report.claims]

    result: GovernanceAuditResult = audit_claims(
        report_id=report.report_id,
        document_id=document_id,
        claims=claims_dicts,
        investment_advice_detected=report.investment_advice_detected,
    )

    def _serialize_violation(v) -> dict:
        return {
            "rule": v.rule,
            "claim_id": v.claim_id,
            "description": v.description,
            "severity": v.severity,
            "auto_fixed": v.auto_fixed,
            "fix_description": v.fix_description,
        }

    return {
        "report_id": result.report_id,
        "document_id": result.document_id,
        "total_claims": result.total_claims,
        "passed": result.passed,
        "violation_count": result.violation_count,
        "warning_count": result.warning_count,
        "violations": [_serialize_violation(v) for v in result.violations],
        "warnings": [_serialize_violation(w) for w in result.warnings],
        "summary": _build_summary(result),
    }


def _build_summary(result: GovernanceAuditResult) -> str:
    """給人看的一句話摘要"""
    if result.passed and result.warning_count == 0:
        return f"PASSED — {result.total_claims} claims 全部通過 R1-R7 稽核，無違規無警告"
    elif result.passed:
        return (
            f"PASSED WITH WARNINGS — {result.total_claims} claims，"
            f"0 violations, {result.warning_count} warnings（建議人工確認）"
        )
    else:
        rules = sorted({v.rule for v in result.violations})
        return (
            f"FAILED — {result.total_claims} claims，"
            f"{result.violation_count} violations（{', '.join(rules)}），"
            f"{result.warning_count} warnings"
        )
