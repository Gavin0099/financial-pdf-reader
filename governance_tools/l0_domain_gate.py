"""
l0_domain_gate.py

L0 任務的 domain contract 載入閘門。

設計原則：
- L0 任務預設不載入任何 domain contract（full 或 summary）
- 若任務描述含 domain-related 關鍵字 → 自動升級為 L1（upgrade trigger 處理）
- 若明確傳入 --force-domain → 允許在 L0 載入 summary（不載 full contract）

這個閘門解決了 Step 5 的未達標問題：
    L0 現況：10,264 tok（domain_contract 占 3,522 = 34%）
    L0 目標：< 9,665 tok
    修復後預估：10,264 - 3,522 = 6,742 tok（達標）
"""

from __future__ import annotations


# L0 domain contract 政策
L0_DOMAIN_POLICY = {
    "default": "skip",            # 預設跳過 domain contract
    "force_flag": "force-domain", # CLI flag 允許覆蓋
    "force_mode": "summary_only", # force 時只允許 summary，不允許 full contract
    "upgrade_on_domain_keyword": True,  # domain 關鍵字觸發 L1 升級（已在 task_level_detector 處理）
}

# 會觸發升級的 domain 關鍵字（供 session_start 的 upgrade trigger 使用）
# 注意：這些已在 task_level_detector.py 的 L0_VETO_KEYWORDS 中有部分覆蓋
# 這裡是 domain-contract-specific 的精確清單
DOMAIN_UPGRADE_KEYWORDS = [
    "kdc", "kernel-driver", "kernel driver",
    "usb hub", "usb-hub",
    "ic verification", "ic-verification",
    "domain contract", "contract validation",
    "isr", "irql", "dpc", "dispatch_level",
    "kmdf", "wdm", "driver model",
]


def should_load_domain_contract(
    task_level: str,
    force_domain: bool = False,
    task_description: str = "",
) -> tuple[bool, str]:
    """
    判斷當前任務是否應該載入 domain contract。

    Args:
        task_level:       "L0" | "L1" | "L2"
        force_domain:     CLI --force-domain flag
        task_description: 任務描述（用於 domain keyword 檢查）

    Returns:
        (should_load, load_mode)
        - should_load: True = 載入，False = 跳過
        - load_mode: "summary" | "full" | "skip"
    """
    # L1 / L2：永遠載入（summary-first，Step 4 已處理）
    if task_level in ("L1", "L2"):
        return True, "summary"

    # L0：預設跳過
    if task_level == "L0":
        if force_domain:
            # --force-domain：允許 summary，不允許 full
            return True, "summary"

        # 檢查是否含 domain 關鍵字（理論上已被 upgrade trigger 升級為 L1）
        # 這裡作為雙重保護
        desc_lower = task_description.lower()
        if any(kw in desc_lower for kw in DOMAIN_UPGRADE_KEYWORDS):
            # 含 domain 關鍵字但仍是 L0（代表 upgrade trigger 可能沒有命中）
            # 保守策略：允許 summary 載入（而不是完全跳過）
            return True, "summary"

        return False, "skip"

    # 未知 level：保守允許
    return True, "summary"


def get_l0_domain_skip_reason(task_description: str = "") -> str:
    """回傳 L0 跳過 domain contract 的說明（供 audit log 使用）。"""
    desc_lower = task_description.lower()
    if any(kw in desc_lower for kw in DOMAIN_UPGRADE_KEYWORDS):
        return "L0 with domain keywords — using summary as safety measure"
    return "L0 default policy: domain contract skipped to reduce token usage"
