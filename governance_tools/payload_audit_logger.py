#!/usr/bin/env python3
"""
payload_audit_logger.py

記錄每次 session_start 實際載入的 governance payload。
目的：建立 token 基線，識別黑洞，作為 Step 3-5 優化的量測依據。

使用方式：
    由 session_start.py 在 build_session_start_context() 結束時呼叫。
    透過環境變數 GOVERNANCE_PAYLOAD_AUDIT=1 開關（預設關閉）。

stdlib-only — 不依賴 PyYAML / tiktoken（可選，自動 fallback）。
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Token 計算 ──────────────────────────────────────────────────────────────

try:
    import tiktoken as _tiktoken  # type: ignore
    _ENCODER = _tiktoken.get_encoding("cl100k_base")
    _TIKTOKEN_AVAILABLE = True
except Exception:
    _ENCODER = None
    _TIKTOKEN_AVAILABLE = False


def count_tokens_estimate(text: str) -> int:
    """粗估 token 數（word count × 1.3），tiktoken 不可用時的備援。"""
    return int(len(text.split()) * 1.3)


def count_tokens(text: str) -> dict:
    """
    回傳 token 計數。

    Returns:
        {
            "exact": int | None,    # tiktoken 精確值，不可用時為 None
            "estimate": int,        # 粗估值，永遠有值
            "method": str           # "tiktoken" | "estimate"
        }
    """
    estimate = count_tokens_estimate(text)
    if _TIKTOKEN_AVAILABLE and _ENCODER is not None:
        try:
            exact = len(_ENCODER.encode(text))
            return {"exact": exact, "estimate": estimate, "method": "tiktoken"}
        except Exception:
            pass
    return {"exact": None, "estimate": estimate, "method": "estimate"}


def count_file_tokens(filepath: Path) -> dict:
    """讀取檔案並計算 token 數。檔案不存在或讀取失敗時回傳 0。"""
    if not filepath.exists():
        return {"exact": 0, "estimate": 0, "method": "n/a", "error": "file_not_found"}
    try:
        content = filepath.read_text(encoding="utf-8")
        result = count_tokens(content)
        result["char_count"] = len(content)
        result["line_count"] = content.count("\n")
        return result
    except Exception as exc:
        return {"exact": None, "estimate": 0, "method": "error", "error": str(exc)}


# ── Audit Record ────────────────────────────────────────────────────────────

def build_audit_record(
    task_level: str,
    task_type: str,
    files_loaded: list[str],
    domain_contracts: list[str],
    memory_files: list[str],
    extra_context: Optional[dict] = None,
) -> dict:
    """
    建立一筆 payload audit 記錄。

    Args:
        task_level:      "L0" | "L1" | "L2" | "onboarding"
        task_type:       "ui" | "schema" | "api" | "domain" | "test" | "general" | "onboarding"
        files_loaded:    governance 文件路徑清單
        domain_contracts: domain contract 路徑清單
        memory_files:    memory/*.md 路徑清單
        extra_context:   其他任意 metadata
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    def _measure(paths: list[str]) -> dict:
        return {f: count_file_tokens(Path(f)) for f in paths}

    governance_tokens = _measure(files_loaded)
    contract_tokens = _measure(domain_contracts)
    memory_tokens = _measure(memory_files)

    def _sum(token_dict: dict) -> int:
        total = 0
        for v in token_dict.values():
            val = v.get("exact") if v.get("exact") is not None else v.get("estimate", 0)
            total += val
        return total

    governance_total = _sum(governance_tokens)
    contract_total = _sum(contract_tokens)
    memory_total = _sum(memory_tokens)
    grand_total = governance_total + contract_total + memory_total
    method = "tiktoken" if _TIKTOKEN_AVAILABLE else "estimate"

    return {
        "audit_id": hashlib.sha256(
            f"{timestamp}{task_level}{task_type}".encode()
        ).hexdigest()[:12],
        "timestamp": timestamp,
        "task_level": task_level,
        "task_type": task_type,
        "token_summary": {
            "governance_files": governance_total,
            "domain_contracts": contract_total,
            "memory_files": memory_total,
            "grand_total": grand_total,
            "token_method": method,
        },
        "files_loaded": {
            "governance": governance_tokens,
            "domain_contracts": contract_tokens,
            "memory": memory_tokens,
        },
        "file_counts": {
            "governance": len(files_loaded),
            "domain_contracts": len(domain_contracts),
            "memory": len(memory_files),
        },
        "extra_context": extra_context or {},
    }


# ── Write & Read ────────────────────────────────────────────────────────────

AUDIT_DIR = Path("docs/payload-audit")
AUDIT_LOG_FILE = AUDIT_DIR / "audit_log.jsonl"


def write_audit_record(record: dict) -> Path:
    """
    將 audit record 寫入 JSONL log 檔，並同步更新 .governance-state.yaml 摘要。
    """
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    _update_governance_state(record)
    return AUDIT_LOG_FILE


def _update_governance_state(record: dict) -> None:
    """
    把最新一筆 audit 摘要寫入 .governance-state.yaml。
    不依賴 PyYAML — 使用簡單文字替換。失敗時靜默跳過（不影響主流程）。
    """
    state_file = Path(".governance-state.yaml")
    if not state_file.exists():
        return
    try:
        content = state_file.read_text(encoding="utf-8")
        payload_block = (
            "payload_audit:\n"
            f"  last_audit_id: \"{record['audit_id']}\"\n"
            f"  last_audit_time: \"{record['timestamp']}\"\n"
            f"  last_task_level: \"{record['task_level']}\"\n"
            f"  last_grand_total_tokens: {record['token_summary']['grand_total']}\n"
            f"  token_method: \"{record['token_summary']['token_method']}\"\n"
        )
        # 若已有 payload_audit 區塊，替換之；否則追加
        if "payload_audit:" in content:
            import re
            # 替換從 payload_audit: 開始到下一個頂層 key 或 EOF
            content = re.sub(
                r"^payload_audit:.*?(?=^\w|\Z)",
                payload_block,
                content,
                flags=re.MULTILINE | re.DOTALL,
            )
        else:
            content = content.rstrip("\n") + "\n" + payload_block
        state_file.write_text(content, encoding="utf-8")
    except Exception:
        pass  # governance-state 更新失敗不影響主流程


def read_audit_log(
    task_level: Optional[str] = None,
    task_type: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """
    讀取 audit log，支援依 task_level / task_type 過濾。
    回傳依時間倒序的記錄清單。
    """
    if not AUDIT_LOG_FILE.exists():
        return []

    records: list[dict] = []
    with open(AUDIT_LOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if task_level and rec.get("task_level") != task_level:
                    continue
                if task_type and rec.get("task_type") != task_type:
                    continue
                records.append(rec)
            except json.JSONDecodeError:
                continue

    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return records[:limit]


# ── Baseline Report Generator ───────────────────────────────────────────────

def generate_baseline_report(task_level: str, records: list[dict]) -> str:
    """根據多筆 audit records 產出 markdown baseline 報告。"""
    if not records:
        return f"# {task_level} Baseline\n\n> Status: PENDING — 尚無資料，需跑真實 session 後產出。\n"

    totals = [r["token_summary"]["grand_total"] for r in records]
    gov_totals = [r["token_summary"]["governance_files"] for r in records]
    contract_totals = [r["token_summary"]["domain_contracts"] for r in records]
    memory_totals = [r["token_summary"]["memory_files"] for r in records]

    def avg(lst: list) -> int:
        return sum(lst) // len(lst) if lst else 0

    # Top 3 token 黑洞（跨所有 records 累計）
    file_token_sum: dict[str, int] = {}
    for r in records:
        for category in ("governance", "domain_contracts", "memory"):
            for fname, tdata in r["files_loaded"].get(category, {}).items():
                val = tdata.get("exact") if tdata.get("exact") is not None else tdata.get("estimate", 0)
                file_token_sum[fname] = file_token_sum.get(fname, 0) + val

    top3 = sorted(file_token_sum.items(), key=lambda x: x[1], reverse=True)[:3]
    method = records[0]["token_summary"].get("token_method", "unknown")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    report = (
        f"# {task_level} Payload Baseline\n\n"
        f"> 產出日期: {now}\n"
        f"> 樣本數: {len(records)} 筆\n"
        f"> Token 計算方式: {method}\n\n"
        "## Token 分布（平均值）\n\n"
        "| 類別 | 平均 Token 數 | 占比 |\n"
        "|------|-------------|------|\n"
        f"| Governance 文件 | {avg(gov_totals):,} | {avg(gov_totals) * 100 // max(avg(totals), 1)}% |\n"
        f"| Domain Contracts | {avg(contract_totals):,} | {avg(contract_totals) * 100 // max(avg(totals), 1)}% |\n"
        f"| Memory 檔案 | {avg(memory_totals):,} | {avg(memory_totals) * 100 // max(avg(totals), 1)}% |\n"
        f"| **總計** | **{avg(totals):,}** | 100% |\n\n"
        "## Top 3 Token 黑洞\n\n"
        f"| 排名 | 檔案 | 累計 Token（{len(records)} sessions） |\n"
        "|------|------|--------------------------------------|\n"
    )
    for i, (fname, total) in enumerate(top3, 1):
        report += f"| {i} | `{fname}` | {total:,} |\n"

    report += (
        "\n## 各 Session 明細\n\n"
        "| Audit ID | 時間 | Task Type | 總 Token |\n"
        "|----------|------|-----------|----------|\n"
    )
    for r in records[:20]:
        report += (
            f"| {r['audit_id']} | {r['timestamp'][:16]} | "
            f"{r['task_type']} | {r['token_summary']['grand_total']:,} |\n"
        )

    report += "\n## 優化建議\n\n"
    if top3:
        report += f"Top 1 黑洞 `{top3[0][0]}` 是最優先的砍除/摘要化目標。\n"
        if avg(contract_totals) > avg(gov_totals):
            report += "Domain contract 占比高於 governance 文件 — 優先建立 adapter summary（Step 4 工作）。\n"
        if avg(memory_totals) > avg(gov_totals) * 0.5:
            report += "Memory 占比偏高 — 優先推進 Step 3 incremental memory。\n"

    return report


# ── 環境開關 ────────────────────────────────────────────────────────────────

def is_audit_enabled() -> bool:
    """Audit 預設關閉。設定 GOVERNANCE_PAYLOAD_AUDIT=1 開啟。"""
    return os.environ.get("GOVERNANCE_PAYLOAD_AUDIT", "0") == "1"


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Payload audit log reader / baseline generator.")
    sub = parser.add_subparsers(dest="cmd")

    show = sub.add_parser("show", help="Show audit log entries")
    show.add_argument("--task-level", help="Filter by task level")
    show.add_argument("--task-type", help="Filter by task type")
    show.add_argument("--limit", type=int, default=20)
    show.add_argument("--format", choices=["human", "json"], default="human")

    gen = sub.add_parser("baseline", help="Generate baseline report from log")
    gen.add_argument("--task-level", required=True)
    gen.add_argument("--output", help="Write report to file")

    args = parser.parse_args()

    if args.cmd == "show":
        records = read_audit_log(
            task_level=args.task_level,
            task_type=args.task_type,
            limit=args.limit,
        )
        if args.format == "json":
            print(json.dumps(records, ensure_ascii=False, indent=2))
        else:
            print(f"[payload_audit] records={len(records)}")
            for r in records:
                print(
                    f"  {r['audit_id']} | {r['timestamp'][:16]} | "
                    f"{r['task_level']} | {r['task_type']} | "
                    f"tokens={r['token_summary']['grand_total']}"
                )
    elif args.cmd == "baseline":
        records = read_audit_log(task_level=args.task_level)
        report = generate_baseline_report(args.task_level, records)
        if args.output:
            Path(args.output).write_text(report, encoding="utf-8")
            print(f"Report written to {args.output}")
        else:
            print(report)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
