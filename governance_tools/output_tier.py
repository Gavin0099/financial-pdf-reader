#!/usr/bin/env python3
"""
output_tier.py

定義 output tier 模型與 task_level → tier 自動映射。

設計原則：
    可見度 = 可重建能力（reconstructability），不是 inline token 數
    Tier 1：agent 做決策需要的最小集合
    Tier 2：debug / reviewer 需要的推論過程
    Tier 3：完整 trace，存 offline，不進 context
"""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any


class OutputTier(IntEnum):
    TIER1 = 1   # decision cost only — agent runtime
    TIER2 = 2   # + observability — on-demand
    TIER3 = 3   # + presentation — offline artifact


# task_level → 預設 output tier 映射
TASK_LEVEL_TIER_MAP: dict[str, OutputTier] = {
    "L0": OutputTier.TIER1,
    "L1": OutputTier.TIER2,
    "L2": OutputTier.TIER3,
}

GOVERNANCE_AUDIT_DIR = Path(".governance-audit")


def get_default_tier(task_level: str) -> OutputTier:
    """依 task_level 回傳預設 output tier。"""
    return TASK_LEVEL_TIER_MAP.get(task_level.upper(), OutputTier.TIER2)


@dataclass
class TieredOutput:
    """
    三層輸出結構。
    建構時填入所有層的資料，render 時依 tier 決定輸出哪些。
    """

    # ── Tier 1：必要（所有 tier 都包含）──────────────────────────────
    verdict: str                          # "pass" | "fail" | "warn"
    violations: list[dict]                # [{rule_id, severity, evidence_id}]
    evidence_ids: list[str]               # 指向 evidence 的引用
    trace_id: str                         # 唯一識別，用於查詢 Tier 3
    task_level: str
    repo_type: str

    # ── Tier 2：可調（L1+ 才包含）────────────────────────────────────
    reasoning_fragments: list[dict] = field(default_factory=list)
    # [{rule_id, structured: {...}, prose: "..."}]
    policy_refs: list[str] = field(default_factory=list)
    # ["RUNTIME_POLICY_023", ...]
    decision_path: list[str] = field(default_factory=list)
    # ["step1: ...", "step2: ..."]（壓縮後的結構化步驟）

    # ── Tier 3：展示（L2 或 offline 才包含）──────────────────────────
    full_trace: dict = field(default_factory=dict)
    onboarding_narrative: str = ""
    reviewer_notes: str = ""

    def render(self, tier: OutputTier) -> dict:
        """
        依指定 tier 輸出對應的 dict。
        Tier 3 不直接 return（太大），而是寫入 .governance-audit/ 並回傳引用。
        """
        output: dict[str, Any] = {
            # Tier 1 永遠包含
            "verdict": self.verdict,
            "violations": self.violations,
            "evidence_ids": self.evidence_ids,
            "trace_id": self.trace_id,
            "task_level": self.task_level,
            "repo_type": self.repo_type,
            "output_tier": int(tier),
        }

        if tier >= OutputTier.TIER2:
            output["reasoning_fragments"] = self.reasoning_fragments
            output["policy_refs"] = self.policy_refs
            output["decision_path"] = self.decision_path

        if tier >= OutputTier.TIER3:
            # Tier 3 不 inline，寫 offline 並回傳路徑
            artifact_path = _write_tier3_artifact(self)
            output["full_trace_ref"] = str(artifact_path)
            output["onboarding_narrative_ref"] = str(artifact_path)
            # 不 inline full_trace 和 narrative

        return output

    def render_for_task_level(self, task_level: str) -> dict:
        """依 task_level 自動決定 tier 並 render。"""
        tier = get_default_tier(task_level)
        return self.render(tier)


def _write_tier3_artifact(output: TieredOutput) -> Path:
    """
    將 Tier 3 完整資料寫入 .governance-audit/ 目錄。
    檔名：{trace_id}.json
    """
    GOVERNANCE_AUDIT_DIR.mkdir(exist_ok=True)

    artifact = {
        "trace_id": output.trace_id,
        "written_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "task_level": output.task_level,
        "verdict": output.verdict,
        "full_trace": output.full_trace,
        "onboarding_narrative": output.onboarding_narrative,
        "reviewer_notes": output.reviewer_notes,
        "reasoning_fragments": output.reasoning_fragments,
        "policy_refs": output.policy_refs,
        "decision_path": output.decision_path,
    }

    artifact_path = GOVERNANCE_AUDIT_DIR / f"{output.trace_id}.json"
    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return artifact_path


def generate_trace_id(task_description: str, task_level: str) -> str:
    """產生唯一 trace_id（16 字元 hex）。"""
    raw = f"{task_description}{task_level}{datetime.datetime.now(datetime.timezone.utc).isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def load_tier3_artifact(trace_id: str, audit_dir: Path | None = None) -> dict | None:
    """從 .governance-audit/ 讀取 Tier 3 artifact。"""
    base = audit_dir if audit_dir is not None else GOVERNANCE_AUDIT_DIR
    artifact_path = base / f"{trace_id}.json"
    if not artifact_path.exists():
        return None
    return json.loads(artifact_path.read_text(encoding="utf-8"))
