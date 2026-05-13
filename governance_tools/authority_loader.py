#!/usr/bin/env python3
"""
authority_loader.py

讀取 governance 文件的 YAML frontmatter，提供 authority filter 介面。
給 session_start.py 使用，決定哪些文件應該被載入。

Usage:
    from governance_tools.authority_loader import load_authority_table, filter_for_session
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal, Optional


AudienceType = Literal["agent-runtime", "agent-on-demand", "human-only"]
AuthorityLevel = Literal["canonical", "reference", "derived"]
LoadMode = Literal["always", "on-demand", "incremental", "never"]

_AUTHORITY_PRIORITY: dict[str, int] = {
    "canonical": 0,
    "reference": 1,
    "derived": 2,
}


def parse_frontmatter(filepath: Path) -> dict:
    """
    讀取 markdown 文件的 YAML frontmatter。
    回傳 dict；若無 frontmatter 或解析失敗，回傳 {}。
    不依賴 PyYAML — 用 stdlib 手動解析簡單 key: value 格式。
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}

    if not content.startswith("---"):
        return {}

    # 找結束 marker（第二個 '---'）
    rest = content[3:]
    end_idx = rest.find("\n---")
    if end_idx == -1:
        return {}

    fm_text = rest[:end_idx].strip()
    result: dict = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        value = raw_value.strip()
        # 處理 ~ (YAML null)
        if value == "~" or value == "null":
            result[key] = None
        elif value.lower() == "true":
            result[key] = True
        elif value.lower() == "false":
            result[key] = False
        else:
            result[key] = value
    return result


def load_authority_table(governance_dir: Path) -> list[dict]:
    """
    讀取 governance/ 目錄下所有 *.md 文件的 frontmatter，
    回傳 authority table（list of dicts）。

    只包含有 frontmatter 的文件（無 frontmatter 的被跳過）。
    """
    table: list[dict] = []
    if not governance_dir.is_dir():
        return table

    for md_file in sorted(governance_dir.glob("*.md")):
        meta = parse_frontmatter(md_file)
        if not meta:
            continue
        table.append({
            "file": str(md_file),
            "filename": md_file.name,
            "audience": meta.get("audience", "agent-on-demand"),
            "authority": meta.get("authority", "reference"),
            "can_override": meta.get("can_override", False),
            "overridden_by": meta.get("overridden_by"),
            "default_load": meta.get("default_load", "on-demand"),
        })
    return table


def filter_for_session(
    authority_table: list[dict],
    include_on_demand: bool = False,
) -> list[str]:
    """
    依 session context 過濾出應載入的文件路徑清單。

    Args:
        authority_table:  load_authority_table() 的輸出
        include_on_demand: True 時加入 agent-on-demand 文件（L1/L2）
                           False 時只取 always（L0）

    Returns:
        應載入的文件路徑清單（human-only 永遠排除）
    """
    result: list[str] = []
    for entry in authority_table:
        # human-only 永遠不載
        if entry["audience"] == "human-only":
            continue
        # never 永遠不載
        if entry["default_load"] == "never":
            continue
        # always 永遠載（canonical/derived agent-runtime）
        if entry["default_load"] == "always":
            result.append(entry["file"])
            continue
        # incremental：不在一般 filter 中，由 memory pipeline 獨立處理
        if entry["default_load"] == "incremental":
            continue
        # on-demand 依 include_on_demand 決定
        if entry["default_load"] == "on-demand" and include_on_demand:
            result.append(entry["file"])

    return result


def get_human_only_files(authority_table: list[dict]) -> list[str]:
    """
    回傳所有 human-only 文件路徑清單。
    用於 session_start 的安全斷言，確保 agent 未載入這些文件。
    """
    return [
        entry["file"]
        for entry in authority_table
        if entry["audience"] == "human-only"
    ]


def resolve_conflict(entries: list[dict]) -> Optional[dict]:
    """
    當多個 entry 對同一文件 key 有衝突時，依 authority 優先序回傳勝者。
    優先序：canonical(0) > reference(1) > derived(2)
    """
    if not entries:
        return None
    return min(entries, key=lambda e: _AUTHORITY_PRIORITY.get(e.get("authority", "derived"), 99))


def validate_session_payload(
    allowed_files: list[str],
    authority_table: list[dict],
) -> dict:
    """
    驗證 session payload 中沒有違規載入 human-only 文件。

    Returns:
        {"ok": bool, "violations": list[str]}
    """
    human_only = set(get_human_only_files(authority_table))
    violations = [f for f in allowed_files if f in human_only]
    return {
        "ok": len(violations) == 0,
        "violations": violations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Authority loader — show governance file authority table."
    )
    parser.add_argument(
        "--governance-dir",
        default="governance",
        help="Path to governance/ directory (default: governance)",
    )
    parser.add_argument(
        "--task-level",
        choices=["L0", "L1", "L2"],
        default="L1",
        help="Task level: L0 (always only) | L1/L2 (always + on-demand)",
    )
    parser.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
    )
    args = parser.parse_args()

    governance_dir = Path(args.governance_dir)
    table = load_authority_table(governance_dir)
    include_on_demand = args.task_level != "L0"
    allowed = filter_for_session(table, include_on_demand=include_on_demand)
    human_only = get_human_only_files(table)
    validation = validate_session_payload(allowed, table)

    result = {
        "task_level": args.task_level,
        "governance_dir": str(governance_dir),
        "total_files": len(table),
        "allowed_files": allowed,
        "human_only_files": human_only,
        "validation": validation,
        "authority_table": table,
    }

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"[authority_loader]")
        print(f"task_level={args.task_level}")
        print(f"total_files={len(table)}")
        print(f"allowed_count={len(allowed)}")
        print(f"human_only_count={len(human_only)}")
        print(f"validation_ok={validation['ok']}")
        if allowed:
            print(f"allowed_files={','.join(Path(f).name for f in allowed)}")
        if human_only:
            print(f"human_only_files={','.join(Path(f).name for f in human_only)}")
        if validation["violations"]:
            for v in validation["violations"]:
                print(f"VIOLATION: {v}")

    raise SystemExit(0 if validation["ok"] else 1)


if __name__ == "__main__":
    main()
