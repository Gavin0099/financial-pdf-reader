#!/usr/bin/env python3
"""
📅 Plan Freshness Checker — PLAN.md 新鮮度檢查工具
Priority: 8 (Governance Tooling)

功能:
  讀取 PLAN.md 的 header 欄位，檢查文件是否在有效期內。
  (freshness policy 定義於 governance/PLAN.md § 2.1)

用法:
  python plan_freshness.py                    # 讀取當前目錄的 PLAN.md
  python plan_freshness.py --file /path/PLAN.md
  python plan_freshness.py --format json
  python plan_freshness.py --threshold 14     # override threshold（天）

退出碼:
  0 = FRESH  (距今 ≤ threshold)
  1 = STALE  (距今 > threshold)
  2 = CRITICAL (距今 > 2× threshold) 或找不到 PLAN.md / 欄位缺失
"""

import re
import sys
import json
import argparse
from datetime import date, datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── 預設 Freshness Policy 閾值（天） ─────────────────────────────────────
POLICY_DEFAULTS = {
    "sprint": 7,
    "phase": 30,
}

STATUS_FRESH    = "FRESH"
STATUS_STALE    = "STALE"
STATUS_CRITICAL = "CRITICAL"
STATUS_ERROR    = "ERROR"


@dataclass
class FreshnessResult:
    status: str                        # FRESH / STALE / CRITICAL / ERROR
    last_updated: Optional[date]
    owner: Optional[str]
    policy: Optional[str]
    threshold_days: Optional[int]
    days_since_update: Optional[int]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_header_fields(text: str) -> dict:
    """
    從 PLAN.md 解析 header 的 blockquote 欄位。

    支援格式:
      > **欄位名**: 值
    """
    fields = {}
    pattern = r'>\s*\*\*([^*]+)\*\*\s*:\s*(.+)'
    for match in re.finditer(pattern, text):
        key = match.group(1).strip()
        value = match.group(2).strip()
        fields[key] = value
    return fields


def parse_policy(policy_str: str) -> Optional[int]:
    """
    從 Freshness policy 字串解析閾值天數。

    範例:
      "Sprint (7d)"  → 7
      "Phase (30d)"  → 30
      "Custom (14d)" → 14
    """
    if not policy_str:
        return None

    # 先嘗試從括號內解析天數
    match = re.search(r'\((\d+)d\)', policy_str, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # fallback: 用 policy 名稱對照預設值
    lower = policy_str.lower()
    for key, days in POLICY_DEFAULTS.items():
        if key in lower:
            return days

    return None


def check_freshness(
    plan_path: Path,
    threshold_override: Optional[int] = None,
    today: Optional[date] = None,
) -> FreshnessResult:
    """主檢查邏輯。"""
    if today is None:
        today = date.today()

    # ── 讀取檔案 ──────────────────────────────────────────────────────────
    if not plan_path.exists():
        return FreshnessResult(
            status=STATUS_ERROR,
            last_updated=None,
            owner=None,
            policy=None,
            threshold_days=None,
            days_since_update=None,
            errors=[f"找不到 PLAN.md: {plan_path}"],
        )

    text = plan_path.read_text(encoding="utf-8")
    fields = parse_header_fields(text)

    errors = []
    warnings = []

    # ── 解析 最後更新 ──────────────────────────────────────────────────────
    raw_date = fields.get("最後更新", "").strip()
    last_updated: Optional[date] = None

    if not raw_date:
        errors.append(
            "'最後更新' 欄位缺失（需格式: YYYY-MM-DD）\n"
            "  框架使用繁體中文欄位名。請在 PLAN.md 開頭加入:\n"
            "  > **最後更新**: YYYY-MM-DD\n"
            "  > **Owner**: <負責人>\n"
            "  > **Freshness**: Sprint (7d)"
        )
    else:
        try:
            last_updated = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            errors.append(
                f"'最後更新' 格式錯誤: '{raw_date}'（正確格式: YYYY-MM-DD）"
            )

    # ── 解析 Owner ────────────────────────────────────────────────────────
    owner = fields.get("Owner", "").strip() or None
    if not owner:
        warnings.append("'Owner' 欄位缺失（建議填寫負責人）")

    # ── 解析 Freshness Policy ─────────────────────────────────────────────
    policy_raw = fields.get("Freshness", "").strip() or None
    threshold_days: Optional[int] = None

    if threshold_override is not None:
        threshold_days = threshold_override
    elif policy_raw:
        threshold_days = parse_policy(policy_raw)
        if threshold_days is None:
            warnings.append(
                f"無法解析 Freshness policy: '{policy_raw}'，"
                f"使用預設值 7d。格式範例: Sprint (7d)"
            )
            threshold_days = 7
    else:
        warnings.append("'Freshness' 欄位缺失，使用預設值 7d")
        threshold_days = 7

    # ── 若有解析錯誤，直接回傳 ERROR ──────────────────────────────────────
    if errors:
        return FreshnessResult(
            status=STATUS_ERROR,
            last_updated=last_updated,
            owner=owner,
            policy=policy_raw,
            threshold_days=threshold_days,
            days_since_update=None,
            errors=errors,
            warnings=warnings,
        )

    # ── 計算新鮮度 ────────────────────────────────────────────────────────
    days_since = (today - last_updated).days

    if days_since <= threshold_days:
        status = STATUS_FRESH
    elif days_since <= threshold_days * 2:
        status = STATUS_STALE
        warnings.append(
            f"PLAN.md 已 {days_since} 天未更新（閾值: {threshold_days}d）"
            f" — 請更新本週聚焦或變更歷史"
        )
    else:
        status = STATUS_CRITICAL
        errors.append(
            f"PLAN.md 嚴重過期：已 {days_since} 天未更新"
            f"（臨界值: {threshold_days * 2}d）"
            f" — 計畫可能已失效，請立即更新"
        )

    return FreshnessResult(
        status=status,
        last_updated=last_updated,
        owner=owner,
        policy=policy_raw,
        threshold_days=threshold_days,
        days_since_update=days_since,
        errors=errors,
        warnings=warnings,
    )


def format_human(result: FreshnessResult, plan_path: Path) -> str:
    """Human-readable 輸出格式。"""
    lines = []

    status_icon = {
        STATUS_FRESH:    "✅",
        STATUS_STALE:    "⚠️ ",
        STATUS_CRITICAL: "🔴",
        STATUS_ERROR:    "🚨",
    }.get(result.status, "❓")

    lines.append(f"📅 PLAN.md Freshness — {plan_path}")
    lines.append("")
    lines.append(f"  {'最後更新':<12} = {result.last_updated or '缺失'}")
    lines.append(f"  {'Owner':<12} = {result.owner or '缺失'}")
    lines.append(f"  {'Policy':<12} = {result.policy or '未設定'}")
    if result.threshold_days is not None:
        lines.append(f"  {'Threshold':<12} = {result.threshold_days}d")
    else:
        lines.append(f"  {'Threshold':<12} = N/A")
    if result.days_since_update is not None:
        lines.append(f"  {'距今':<12} = {result.days_since_update}d")
    else:
        lines.append(f"  {'距今':<12} = N/A")
    lines.append("")
    lines.append(f"{status_icon} {result.status}")

    if result.errors:
        lines.append("")
        lines.append(f"❌ {len(result.errors)} 個錯誤:")
        for err in result.errors:
            lines.append(f"   • {err}")

    if result.warnings:
        lines.append("")
        lines.append(f"⚠️  {len(result.warnings)} 個警告:")
        for w in result.warnings:
            lines.append(f"   • {w}")

    return "\n".join(lines)


def format_json(result: FreshnessResult, plan_path: Path) -> str:
    """JSON 輸出格式（供 CI / 自動化使用）。"""
    output = {
        "plan_path": str(plan_path),
        "status": result.status,
        "last_updated": result.last_updated.isoformat() if result.last_updated else None,
        "owner": result.owner,
        "policy": result.policy,
        "threshold_days": result.threshold_days,
        "days_since_update": result.days_since_update,
        "errors": result.errors,
        "warnings": result.warnings,
    }
    return json.dumps(output, ensure_ascii=False, indent=2)


def main():
    # Windows 終端機的 UTF-8 相容性
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Plan Freshness Checker — 檢查 PLAN.md 是否在有效期內"
    )
    parser.add_argument(
        "--file", "-f",
        default="PLAN.md",
        help="PLAN.md 路徑（預設: 當前目錄的 PLAN.md）",
    )
    parser.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="輸出格式 (預設: human)",
    )
    parser.add_argument(
        "--threshold", "-t",
        type=int,
        default=None,
        help="Override freshness threshold（天）。覆蓋 PLAN.md 中的 Freshness policy",
    )
    args = parser.parse_args()

    plan_path = Path(args.file)
    result = check_freshness(plan_path, threshold_override=args.threshold)

    if args.format == "json":
        print(format_json(result, plan_path))
    else:
        print(format_human(result, plan_path))

    # 退出碼
    if result.status in (STATUS_CRITICAL, STATUS_ERROR):
        sys.exit(2)
    elif result.status == STATUS_STALE:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
