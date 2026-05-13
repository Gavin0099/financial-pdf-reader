#!/usr/bin/env python3
"""
🧹 Memory Janitor - 自動記憶掃除守護程式
Priority: 8 (Memory Stewardship)

功能:
1. 監控 memory/01_active_task.md 行數
2. 當超過閾值時產出掃除建議
3. 自動將過期內容歸檔到 archive/，原位置保留 pointer

設計原則:
- 完全自動化,無需人工介入
- 複製（非移動）原始內容到 archive/，原位置保留 pointer 供追溯
- 寫入 archive/manifest.json 完整 audit trail
- 產出人類可讀的稽核報告
"""

import os
import re
import json
from pathlib import Path
from datetime import datetime
from typing import Tuple, List, Dict


class MemoryJanitor:
    """記憶掃除執行器"""
    
    # 閾值設定
    HOT_MEMORY_SOFT_LIMIT = 180  # 軟限制:產出警告
    HOT_MEMORY_HARD_LIMIT = 200  # 硬限制:建議掃除
    HOT_MEMORY_CRITICAL = 250    # 緊急限制:強制停止

    HOT_MEMORY_SOFT_SIZE_LIMIT = 8000
    HOT_MEMORY_HARD_SIZE_LIMIT = 10000
    HOT_MEMORY_CRITICAL_SIZE_LIMIT = 12000
    
    def __init__(self, memory_root: Path):
        """
        Args:
            memory_root: memory/ 資料夾根目錄路徑
        """
        self.memory_root = Path(memory_root)
        self.active_task_file = self.memory_root / "01_active_task.md"
        self.archive_dir = self.memory_root / "archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        
    def check_hot_memory_status(self) -> Tuple[int, int, str]:
        """
        檢查熱記憶狀態
        
        Returns:
            (行數, 字元數, 狀態碼)
            狀態碼: "SAFE" | "WARNING" | "CRITICAL" | "EMERGENCY"
        """
        if not self.active_task_file.exists():
            return 0, 0, "SAFE"
        
        with open(self.active_task_file, 'r', encoding='utf-8') as f:
            content = f.read()
            line_count = len(content.splitlines())
            char_count = len(content)
        
        if line_count >= self.HOT_MEMORY_CRITICAL or char_count >= self.HOT_MEMORY_CRITICAL_SIZE_LIMIT:
            return line_count, char_count, "EMERGENCY"
        elif line_count >= self.HOT_MEMORY_HARD_LIMIT or char_count >= self.HOT_MEMORY_HARD_SIZE_LIMIT:
            return line_count, char_count, "CRITICAL"
        elif line_count >= self.HOT_MEMORY_SOFT_LIMIT or char_count >= self.HOT_MEMORY_SOFT_SIZE_LIMIT:
            return line_count, char_count, "WARNING"
        else:
            return line_count, char_count, "SAFE"
    
    def generate_warning_message(self, line_count: int, char_count: int, status: str) -> str:
        """產出警告訊息 (供 AI 在回應末尾顯示)"""
        if status == "EMERGENCY":
            return f"🚨 **熱記憶緊急超限** ({line_count}/200 行, {char_count}/10000 字元) - **立即停止任務,強制執行掃除**"
        elif status == "CRITICAL":
            return f"⚠️ **熱記憶超過硬限制** ({line_count}/200 行, {char_count}/10000 字元) - 建議執行 `python memory_janitor.py --clean`"
        elif status == "WARNING":
            return f"⚠️ 熱記憶接近上限 ({line_count}/200 行, {char_count}/10000 字元),建議儘快掃除"
        else:
            return ""
    
    def analyze_archivable_content(self) -> Dict[str, List[str]]:
        """
        分析可歸檔的內容區塊
        
        Returns:
            {
                "completed_tasks": ["## Task 1", "## Task 2"],
                "obsolete_decisions": ["- [Decision] ...", ...],
                "archived_references": ["See ADR-0001", ...]
            }
        """
        if not self.active_task_file.exists():
            return {"completed_tasks": [], "obsolete_decisions": [], "archived_references": []}
        
        with open(self.active_task_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 使用簡單的啟發式規則
        completed_tasks = re.findall(r'##\s+.*?\[x\].*?(?=##|\Z)', content, re.DOTALL)
        obsolete_patterns = [
            r'~~.*?~~',  # 刪除線標記的過期內容
            r'\(Superseded.*?\)',  # 標記為被取代的決策
        ]
        
        obsolete_decisions = []
        for pattern in obsolete_patterns:
            obsolete_decisions.extend(re.findall(pattern, content))
        
        # 尋找 ADR 引用 (表示已正式文件化,可從熱記憶移除)
        archived_references = re.findall(r'ADR-\d{4}', content)
        
        return {
            "completed_tasks": completed_tasks,
            "obsolete_decisions": obsolete_decisions,
            "archived_references": list(set(archived_references))
        }
    
    def create_archive_plan(self) -> str:
        """
        產出歸檔計畫 (Markdown 格式,供人工確認)
        
        Returns:
            Markdown 格式的掃除計畫報告
        """
        line_count, char_count, status = self.check_hot_memory_status()
        archivable = self.analyze_archivable_content()
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        report = f"""# 🧹 記憶掃除計畫
**執行時間**: {timestamp}
**當前狀態**: {status} ({line_count} 行, {char_count} 字元)

---

## 📊 可歸檔內容分析

### ✅ 已完成任務 ({len(archivable['completed_tasks'])})
"""
        for task in archivable['completed_tasks'][:5]:  # 只顯示前5個
            preview = task[:100].replace('\n', ' ')
            report += f"- {preview}...\n"
        
        report += f"""
### 🗑️ 過期決策 ({len(archivable['obsolete_decisions'])})
"""
        for decision in archivable['obsolete_decisions'][:5]:
            report += f"- {decision}\n"
        
        report += f"""
### 📚 已歸檔引用 ({len(archivable['archived_references'])})
"""
        for ref in archivable['archived_references']:
            report += f"- {ref}\n"
        
        report += f"""
---

## 🎯 建議行動

"""
        if status == "EMERGENCY":
            report += "**立即停止當前任務** → 人工審核並執行掃除 → 重新開始對話\n"
        elif status == "CRITICAL":
            report += "建議執行: `python memory_janitor.py --execute`\n"
        elif status == "WARNING":
            report += "建議在下一個自然中斷點執行掃除\n"
        else:
            report += "目前狀態良好,無需掃除\n"
        
        return report
    
    def _load_manifest(self) -> dict:
        """載入 manifest.json（不存在則回傳空結構）。"""
        manifest_path = self.archive_dir / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"version": "1.0", "archives": []}

    def _save_manifest(self, manifest: dict) -> None:
        """寫入 manifest.json。"""
        manifest_path = self.archive_dir / "manifest.json"
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    def execute_cleanup(self, dry_run: bool = True) -> str:
        """
        執行實際掃除 (copy + pointer + manifest)

        行為 (BUG-001 修正):
          1. 複製 01_active_task.md 全文到 archive/active_task_{timestamp}.md
          2. 將 01_active_task.md 截短為 header + Next Steps
          3. 在截短後的 01_active_task.md 頂部插入 pointer 區塊
          4. 將本次操作記錄到 archive/manifest.json

        Args:
            dry_run: True = 僅模擬,不實際修改檔案

        Returns:
            執行報告（str）
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dt_human = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        archive_filename = f"active_task_{timestamp}.md"
        archive_file = self.archive_dir / archive_filename

        if not self.active_task_file.exists():
            return "⚠️ active_task.md 不存在,無需掃除"

        with open(self.active_task_file, 'r', encoding='utf-8') as f:
            content = f.read()

        original_lines = len(content.splitlines())
        original_chars = len(content)
        _, _, status = self.check_hot_memory_status()

        if dry_run:
            return (
                f"[dry-run] 將執行以下操作:\n"
                f"  1. 複製 {self.active_task_file} ({original_lines} 行) → {archive_file}\n"
                f"  2. 截短 {self.active_task_file}，保留 header + Next Steps\n"
                f"  3. 在原檔頂部插入 pointer 區塊\n"
                f"  4. 記錄到 {self.archive_dir / 'manifest.json'}"
            )

        # ── 步驟 1: 複製完整內容到 archive ─────────────────────────────
        with open(archive_file, 'w', encoding='utf-8') as f:
            f.write(content)

        # ── 步驟 2: 建立截短後的內容 ──────────────────────────────────
        lines = content.splitlines()
        # 只取前 20 行但排除「## Next Steps」以後的部分（避免重複）
        next_steps_match = re.search(r'##\s+Next Steps.*?(?=##|\Z)', content, re.DOTALL)
        next_steps = next_steps_match.group(0).strip() if next_steps_match else ""

        # 找出 Next Steps 開始的行號，header 只取到那之前
        next_steps_start_line = None
        if next_steps_match:
            preceding = content[:next_steps_match.start()]
            next_steps_start_line = preceding.count('\n')

        header_end = min(20, next_steps_start_line if next_steps_start_line is not None else len(lines))
        header = '\n'.join(lines[:header_end])

        # ── 步驟 3: 插入 pointer 區塊 ─────────────────────────────────
        pointer_block = (
            f"<!-- ARCHIVED: {archive_filename} ({dt_human}) -->\n"
            f"<!-- 完整歷史請查閱: archive/{archive_filename} -->\n"
            f"\n"
            f"> **[歸檔紀錄]** {dt_human} — 本檔案已歸檔至 `archive/{archive_filename}`\n"
            f"> 歸檔原因: 記憶壓力 {status}（原始 {original_lines} 行, {original_chars} 字元）\n"
            f"\n"
            f"---\n\n"
        )

        new_content = pointer_block + header + "\n\n---\n\n" + next_steps + "\n"
        new_lines = len(new_content.splitlines())

        with open(self.active_task_file, 'w', encoding='utf-8') as f:
            f.write(new_content)

        # ── 步驟 4: 寫入 manifest ─────────────────────────────────────
        manifest = self._load_manifest()
        manifest["archives"].append({
            "timestamp": timestamp,
            "datetime": dt_human,
            "archive_file": f"archive/{archive_filename}",
            "source_file": str(self.active_task_file),
            "original_lines": original_lines,
            "new_lines": new_lines,
            "reason": f"Memory pressure: {status} ({original_lines}/{self.HOT_MEMORY_HARD_LIMIT} lines, {original_chars}/{self.HOT_MEMORY_HARD_SIZE_LIMIT} chars)",
        })
        self._save_manifest(manifest)

        return (
            f"✅ 掃除完成\n"
            f"  歸檔: {archive_file}\n"
            f"  原始行數: {original_lines} → 截短後: {new_lines} 行\n"
            f"  Pointer 已插入 {self.active_task_file}\n"
            f"  Manifest 已更新: {self.archive_dir / 'manifest.json'} "
            f"（共 {len(manifest['archives'])} 筆紀錄）"
        )


def main():
    """CLI 入口"""
    import argparse
    import sys

    # Windows 終端機的 UTF-8 相容性
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Memory Janitor - 記憶掃除工具")
    parser.add_argument('--memory-root', default='./memory', help='memory/ 目錄路徑')
    parser.add_argument('--check', action='store_true', help='僅檢查狀態')
    parser.add_argument('--plan', action='store_true', help='產出掃除計畫')
    parser.add_argument('--execute', action='store_true', help='執行實際掃除（copy+pointer+manifest）')
    parser.add_argument('--dry-run', action='store_true', help='模擬執行 (不實際修改檔案)')
    parser.add_argument('--manifest', action='store_true', help='顯示 archive/manifest.json 內容')
    parser.add_argument('--format', choices=['human', 'json'], default='human', help='輸出格式 (預設: human)')

    args = parser.parse_args()

    janitor = MemoryJanitor(Path(args.memory_root))

    if args.check:
        line_count, char_count, status = janitor.check_hot_memory_status()
        warning = janitor.generate_warning_message(line_count, char_count, status)
        if args.format == 'json':
            print(json.dumps({
                "status": status,
                "line_count": line_count,
                "char_count": char_count,
                "soft_limit": janitor.HOT_MEMORY_SOFT_LIMIT,
                "hard_limit": janitor.HOT_MEMORY_HARD_LIMIT,
                "critical": janitor.HOT_MEMORY_CRITICAL,
                "soft_size_limit": janitor.HOT_MEMORY_SOFT_SIZE_LIMIT,
                "hard_size_limit": janitor.HOT_MEMORY_HARD_SIZE_LIMIT,
                "critical_size_limit": janitor.HOT_MEMORY_CRITICAL_SIZE_LIMIT,
            }, ensure_ascii=False))
        else:
            print(f"狀態: {status} ({line_count} 行, {char_count} 字元)")
            if warning:
                print(warning)

    elif args.plan:
        if args.format == 'json':
            line_count, char_count, status = janitor.check_hot_memory_status()
            archivable = janitor.analyze_archivable_content()
            recommendation_map = {
                "EMERGENCY": "stop_and_manual_review",
                "CRITICAL": "execute_cleanup_now",
                "WARNING": "cleanup_at_next_break",
                "SAFE": "no_action_needed",
            }
            print(json.dumps({
                "status": status,
                "line_count": line_count,
                "char_count": char_count,
                "soft_limit": janitor.HOT_MEMORY_SOFT_LIMIT,
                "hard_limit": janitor.HOT_MEMORY_HARD_LIMIT,
                "critical": janitor.HOT_MEMORY_CRITICAL,
                "soft_size_limit": janitor.HOT_MEMORY_SOFT_SIZE_LIMIT,
                "hard_size_limit": janitor.HOT_MEMORY_HARD_SIZE_LIMIT,
                "critical_size_limit": janitor.HOT_MEMORY_CRITICAL_SIZE_LIMIT,
                "archivable": {
                    "completed_tasks": len(archivable["completed_tasks"]),
                    "obsolete_decisions": len(archivable["obsolete_decisions"]),
                    "archived_references": len(archivable["archived_references"]),
                },
                "recommendation": recommendation_map.get(status, "unknown"),
            }, ensure_ascii=False))
        else:
            plan = janitor.create_archive_plan()
            print(plan)

    elif args.execute:
        result = janitor.execute_cleanup(dry_run=args.dry_run)
        print(result)

    elif args.manifest:
        manifest = janitor._load_manifest()
        if args.format == 'json':
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        else:
            archives = manifest.get("archives", [])
            if not archives:
                print("(尚無歸檔紀錄)")
            else:
                print(f"📚 Archive Manifest — {len(archives)} 筆紀錄\n")
                for entry in archives:
                    print(f"  [{entry['datetime']}] {entry['archive_file']}")
                    print(f"    {entry['original_lines']} → {entry['new_lines']} 行 | {entry['reason']}")

    else:
        # 預設行為:檢查並提示
        line_count, char_count, status = janitor.check_hot_memory_status()
        if status != "SAFE":
            plan = janitor.create_archive_plan()
            print(plan)
        else:
            print(f"✅ 熱記憶狀態良好 ({line_count} 行, {char_count} 字元)")


if __name__ == "__main__":
    main()
