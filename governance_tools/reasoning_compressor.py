#!/usr/bin/env python3
"""
reasoning_compressor.py

把 verbose prose reasoning fragment 壓縮為 structured JSON，
prose 作為備用（human-readable fallback）。

壓縮前（現況）：
    "Detected missing evidence because rule RUNTIME_POLICY_023
     requires ISR evidence but none was provided in the task context.
     This violates the kernel driver contract section 3.2."

壓縮後（structured 主）：
    {
        "rule_id": "RUNTIME_POLICY_023",
        "violation_type": "missing_evidence",
        "policy_refs": ["KDC-3.2"],
        "severity": "high",
        "prose": "..."   # 保留，但不是主要 context 消耗
    }
"""

from __future__ import annotations

import json
import re
from typing import Any


# ── Violation Type 分類 ──────────────────────────────────────────────────────

VIOLATION_TYPE_PATTERNS: list[tuple[str, str]] = [
    # (regex pattern, violation_type)
    (r"missing evidence|evidence.*not.*provided|no evidence", "missing_evidence"),
    (r"stale|outdated|expired|freshness", "staleness_violation"),
    (r"unknown rule pack|invalid rule", "invalid_rule_pack"),
    (r"contract.*violat|violat.*contract", "contract_violation"),
    (r"hard.?stop|blocked|forbidden operation", "hard_stop"),
    (r"permission|unauthorized|not allowed", "permission_violation"),
    (r"schema.*invalid|invalid.*schema", "schema_violation"),
    (r"placeholder|not filled|empty", "incomplete_artifact"),
]

# ── Policy Reference 抽取 ────────────────────────────────────────────────────

POLICY_REF_PATTERNS: list[str] = [
    r"RUNTIME_POLICY_\d+",
    r"KDC-[\d.]+",
    r"USB-HUB-[\d.]+",
    r"GOVERNANCE-[\d.]+",
    r"P-\d{3}",
]

# ── Rule ID 抽取 ─────────────────────────────────────────────────────────────

RULE_ID_PATTERN = re.compile(
    r"\b([A-Z][A-Z0-9_]*_RULE_\d+|RULE_[A-Z0-9_]+|[A-Z]{2,}_\d{3,})\b"
)

_PROSE_TRUNCATE_LEN = 200


def classify_violation_type(prose: str) -> str:
    """從 prose 文字推斷 violation type。"""
    prose_lower = prose.lower()
    for pattern, violation_type in VIOLATION_TYPE_PATTERNS:
        if re.search(pattern, prose_lower):
            return violation_type
    return "generic_violation"


def extract_policy_refs(prose: str) -> list[str]:
    """從 prose 文字抽取 policy reference（如 RUNTIME_POLICY_023）。"""
    refs: list[str] = []
    for pattern in POLICY_REF_PATTERNS:
        refs.extend(re.findall(pattern, prose))
    return list(dict.fromkeys(refs))  # deduplicate, preserve order


def extract_rule_ids(prose: str) -> list[str]:
    """從 prose 文字抽取 rule ID。"""
    return list(dict.fromkeys(RULE_ID_PATTERN.findall(prose)))


def compress_fragment(
    prose: str,
    rule_id: str | None = None,
    severity: str = "medium",
    keep_prose: bool = True,
) -> dict[str, Any]:
    """
    將單一 reasoning fragment prose 壓縮為 structured dict。

    Args:
        prose:       原始 reasoning 文字
        rule_id:     已知的 rule_id（若無則從 prose 抽取）
        severity:    "low" | "medium" | "high" | "critical"
        keep_prose:  True = 保留原始 prose 作為 fallback（截斷至 200 chars）

    Returns:
        {
            "rule_id": str,
            "violation_type": str,
            "policy_refs": [...],
            "severity": str,
            "prose": str | None   # keep_prose=True 時保留
        }
    """
    extracted_rule_ids = extract_rule_ids(prose)
    effective_rule_id = rule_id or (extracted_rule_ids[0] if extracted_rule_ids else "UNKNOWN")

    compressed: dict[str, Any] = {
        "rule_id": effective_rule_id,
        "violation_type": classify_violation_type(prose),
        "policy_refs": extract_policy_refs(prose),
        "severity": severity,
    }

    if keep_prose:
        if len(prose) > _PROSE_TRUNCATE_LEN:
            compressed["prose"] = prose[:_PROSE_TRUNCATE_LEN] + "..."
        else:
            compressed["prose"] = prose

    return compressed


def compress_fragments(
    fragments: list[str | dict],
    keep_prose: bool = True,
) -> list[dict[str, Any]]:
    """
    批次壓縮 reasoning fragment 清單。

    Args:
        fragments: prose 字串清單，或已有部分結構的 dict 清單
        keep_prose: True = 所有 fragment 保留 prose fallback

    Returns:
        壓縮後的 structured fragment 清單
    """
    result: list[dict[str, Any]] = []
    for fragment in fragments:
        if isinstance(fragment, str):
            result.append(compress_fragment(fragment, keep_prose=keep_prose))
        elif isinstance(fragment, dict):
            # 已有結構的 dict：補充缺少的欄位
            prose = fragment.get("prose") or fragment.get("text") or ""
            compressed = compress_fragment(
                prose=prose,
                rule_id=fragment.get("rule_id"),
                severity=fragment.get("severity", "medium"),
                keep_prose=keep_prose,
            )
            # 保留原有的額外欄位（不覆蓋已計算的欄位）
            for k, v in fragment.items():
                if k not in compressed:
                    compressed[k] = v
            result.append(compressed)
    return result


def estimate_compression_ratio(original_fragments: list[str]) -> dict:
    """
    估算壓縮前後的 token 數差異（粗估：1 token ≈ 4 chars）。
    用於驗證壓縮效果。
    """
    original_chars = sum(len(f) for f in original_fragments)
    original_tokens = max(original_chars // 4, 1)

    compressed = compress_fragments(original_fragments, keep_prose=False)
    compressed_chars = len(json.dumps(compressed, ensure_ascii=False))
    compressed_tokens = compressed_chars // 4

    reduction = original_tokens - compressed_tokens
    reduction_pct = round((1 - compressed_tokens / original_tokens) * 100, 1)

    return {
        "original_tokens": original_tokens,
        "compressed_tokens": compressed_tokens,
        "reduction": reduction,
        "reduction_pct": reduction_pct,
    }
