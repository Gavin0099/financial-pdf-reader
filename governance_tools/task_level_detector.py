#!/usr/bin/env python3
"""
task_level_detector.py

L0/L1/L2 自動偵測邏輯。
當 CLI 未明確傳入 --task-level 時，依 task_description 關鍵字推斷。

使用優先序：
    1. 明確傳入（--task-level CLI arg）→ 直接使用，不推斷
    2. 自動偵測（task_description keyword matching）
    3. 預設 L1（保守策略）

Step 5: L0 Payload Short-Circuit
"""

from __future__ import annotations


# ── L0 關鍵字（任何一個命中 → 候選 L0）
L0_KEYWORDS: list[str] = [
    # UI / 視覺
    "ui", "layout", "style", "css", "color", "colour", "font",
    "button", "icon", "spacing", "padding", "margin", "alignment",
    "responsive", "dark mode", "light mode", "theme", "tailwind",
    "component", "visual", "display", "render",
    # 文件 / 說明
    "readme", "comment", "docstring", "typo", "wording",
    "documentation", "doc update", "description",
    # 輕量修正
    "rename variable", "rename function", "rename file",
    "copy", "paste", "duplicate",
]

# ── L0 否決關鍵字（命中任何一個 → 強制升級為 L1，即使有 L0 關鍵字）
L0_VETO_KEYWORDS: list[str] = [
    # Schema / DB
    "schema", "migration", "database", "supabase", "postgres",
    "table", "column", "index", "foreign key",
    # API / 後端邏輯
    "api", "endpoint", "route", "middleware", "auth", "authentication",
    "authorization", "permission", "rls", "policy",
    # 架構 / 設計
    "architecture", "refactor", "restructure", "design pattern",
    "dependency", "interface", "contract",
    # Domain 相關
    "isr", "interrupt", "irql", "dpc", "kernel", "driver",
    "firmware", "embedded", "hardware",
    # 安全 / 風險
    "security", "vulnerability", "cve", "injection", "xss", "csrf",
    "secret", "key", "token", "password", "credential",
    # 發版
    "release", "deploy", "version", "changelog", "tag", "publish",
]

# ── L2 關鍵字（命中 → 最高風險，強制 L2）
L2_KEYWORDS: list[str] = [
    "breaking change", "breaking-change",
    "major refactor", "architectural change",
    "cross-repo", "multi-repo",
    "domain contract change", "contract update",
    "external api change",
]

_VALID_LEVELS = frozenset({"L0", "L1", "L2"})


def detect_task_level(
    task_description: str,
    explicit_level: str | None = None,
) -> str:
    """
    偵測任務的 level。

    Args:
        task_description: 任務描述文字
        explicit_level:   CLI 或 caller 明確傳入的 level（優先）

    Returns:
        "L0" | "L1" | "L2"
    """
    # 明確傳入優先
    if explicit_level and explicit_level.upper() in _VALID_LEVELS:
        return explicit_level.upper()

    desc_lower = task_description.lower()

    # L2 檢查（最優先否決）
    if any(kw in desc_lower for kw in L2_KEYWORDS):
        return "L2"

    # Veto 檢查（否決 L0 降級）
    if any(kw in desc_lower for kw in L0_VETO_KEYWORDS):
        return "L1"

    # L0 關鍵字檢查
    if any(kw in desc_lower for kw in L0_KEYWORDS):
        return "L0"

    # 預設 L1（保守策略）
    return "L1"


def get_l0_context_limits() -> dict:
    """
    回傳 L0 任務的 context 限制規格。
    session_start.py 讀取此規格決定哪些文件可以/不可以載入。

    Returns:
        {
            "always_load": [...],      # 永遠載入（不可省略）
            "forbidden_load": [...],   # 永遠不載入
            "upgrade_triggers": [...]  # 這些條件命中時升級為 L1
        }
    """
    return {
        "always_load": [
            "governance/SYSTEM_PROMPT.md",
            "governance/AGENT.md",
            "PLAN.md",
        ],
        "forbidden_load": [
            "governance/ARCHITECTURE.md",
            "governance/REVIEW_CRITERIA.md",
            "governance/HUMAN-OVERSIGHT.md",
            "governance/NATIVE-INTEROP.md",
        ],
        "upgrade_triggers": [
            {
                "condition": "task touches schema or migration",
                "keywords": ["schema", "migration", "table", "column"],
                "escalate_to": "L1",
                "load_addition": ["governance/ARCHITECTURE.md"],
            },
            {
                "condition": "task touches external domain contract",
                "keywords": ["kdc", "kernel", "driver", "isr", "irql"],
                "escalate_to": "L1",
                "load_addition": ["domain_summary"],
            },
            {
                "condition": "risk_level is high or critical",
                "risk_threshold": "high",
                "escalate_to": "L1",
                "load_addition": ["governance/ARCHITECTURE.md"],
            },
        ],
    }


def apply_upgrade_triggers(
    task_level: str,
    task_description: str,
    risk_level: str = "low",
) -> tuple[str, list[str]]:
    """
    檢查 upgrade triggers，決定最終 task_level 和需要額外載入的文件。

    Args:
        task_level:       當前 task_level（可能已是 L0）
        task_description: 任務描述
        risk_level:       risk 評估值 (low/medium/high/critical)

    Returns:
        (final_level, additional_loads)
        - final_level:      最終決定的 level（可能從 L0 升級為 L1）
        - additional_loads: 需要額外載入的文件/資源清單（已去重）
    """
    if task_level != "L0":
        return task_level, []

    limits = get_l0_context_limits()
    desc_lower = task_description.lower()
    additional_loads: list[str] = []
    escalated = False

    _risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    for trigger in limits["upgrade_triggers"]:
        triggered = False

        keywords = trigger.get("keywords", [])
        if keywords and any(kw in desc_lower for kw in keywords):
            triggered = True

        risk_threshold = trigger.get("risk_threshold")
        if risk_threshold:
            if _risk_order.get(risk_level, 0) >= _risk_order.get(risk_threshold, 99):
                triggered = True

        if triggered:
            escalate_to = trigger.get("escalate_to", "L1")
            if escalate_to == "L1":
                escalated = True
            additional_loads.extend(trigger.get("load_addition", []))

    final_level = "L1" if escalated else "L0"
    return final_level, list(dict.fromkeys(additional_loads))  # deduplicate preserving order
