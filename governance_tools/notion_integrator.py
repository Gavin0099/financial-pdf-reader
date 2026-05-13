#!/usr/bin/env python3
"""
📋 Notion Integrator - Notion API 自動整合工具
Priority: 8 (Productivity Tooling)

功能:
1. 從 memory/01_active_task.md 解析任務
2. 自動建立對應的 Notion Database Page
3. 任務 ID 寫回本地（防止重複建立）

設計原則:
- PLAN.md-First: PLAN.md 為 Single Source of Truth（見 docs/notion-source-of-truth.md）
- 敏感資訊防護: 送出前掃描 title/description
- 錯誤優雅降級: API 失敗時不影響本地工作流
- 無第三方依賴: 僅使用 stdlib (urllib, json, re)

環境變數:
  NOTION_API_KEY      Notion Integration Token (必要)
  NOTION_DATABASE_ID  目標 Database ID (可用 --database-id 覆寫)

使用範例:
  python governance_tools/notion_integrator.py --list-databases
  python governance_tools/notion_integrator.py --sync --database-id <DB_ID>
  python governance_tools/notion_integrator.py --sync --database-id <DB_ID> --format json
"""

import os
import re
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import urllib.request
import urllib.error


class NotionClient:
    """Notion REST API 客戶端（v2022-06-28）"""

    API_BASE = "https://api.notion.com/v1"
    NOTION_VERSION = "2022-06-28"
    REQUEST_TIMEOUT = 30  # seconds
    MAX_RETRIES = 3
    _RETRY_DELAYS = (1, 2, 4)  # exponential backoff (seconds)

    # 敏感資訊偵測規則（與 linear_integrator 相同）
    _SENSITIVE_PATTERNS: List[Tuple[re.Pattern, str]] = [
        (re.compile(r'(lin_api_|sk-|xox[baprs]-|secret_)[A-Za-z0-9_\-]{10,}', re.IGNORECASE), 'API_KEY'),
        (re.compile(r'\b(password|passwd|secret|token)\s*[=:]\s*\S+', re.IGNORECASE), 'CREDENTIAL'),
        (re.compile(r'-----BEGIN\s+(?:\w+\s+)?PRIVATE KEY-----', re.IGNORECASE), 'PRIVATE_KEY'),
        (re.compile(r'[A-Za-z0-9+/]{40,}={0,2}(?=\s|$)'), 'POSSIBLE_SECRET'),
    ]

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: Notion Integration Token（如未提供，從環境變數讀取）
        """
        self.api_key = api_key or os.getenv("NOTION_API_KEY")
        if not self.api_key:
            raise ValueError(
                "NOTION_API_KEY 未設定\n"
                "請設定環境變數: export NOTION_API_KEY='secret_xxxx'\n"
                "取得方式: https://www.notion.so/my-integrations → 建立 Integration → 複製 Internal Integration Token"
            )

    def scan_sensitive(self, text: str) -> List[str]:
        """
        掃描文字中的敏感資訊。

        Returns:
            偵測到的敏感類型清單（空清單表示安全）
        """
        found = []
        for pattern, label in self._SENSITIVE_PATTERNS:
            if pattern.search(text):
                found.append(label)
        return found

    def _request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict] = None,
    ) -> Dict:
        """
        執行 Notion REST API 請求（含 timeout）。

        Args:
            method:   HTTP method (GET/POST/PATCH)
            endpoint: API 路徑，如 "/pages" 或 "/databases/{id}/query"
            payload:  JSON body（GET 時為 None）

        Raises:
            urllib.error.HTTPError: HTTP 層錯誤
            urllib.error.URLError:  網路層錯誤
        """
        url = f"{self.API_BASE}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": self.NOTION_VERSION,
            "Content-Type": "application/json",
        }
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise urllib.error.HTTPError(e.url, e.code, body, e.headers, None)
        except urllib.error.URLError as e:
            raise urllib.error.URLError(f"網路錯誤: {e.reason}")

    def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict] = None,
    ) -> Dict:
        """
        帶重試機制的 API 請求。

        - HTTP 429 / 5xx → 指數退避重試（最多 MAX_RETRIES 次）
        - 其他錯誤    → 直接拋出

        Raises:
            Exception: 超過重試次數或不可重試的錯誤
        """
        last_exc: Optional[Exception] = None
        for attempt, delay in enumerate(self._RETRY_DELAYS, start=1):
            try:
                return self._request(method, endpoint, payload)
            except urllib.error.HTTPError as e:
                last_exc = e
                retryable = e.code in (429, 502, 503, 504)
                if retryable and attempt < self.MAX_RETRIES:
                    print(
                        f"⚠️  Notion API {e.code} (attempt {attempt}/{self.MAX_RETRIES})，"
                        f"{delay}s 後重試..."
                    )
                    time.sleep(delay)
                    continue
                # 嘗試解析 Notion 錯誤訊息
                try:
                    err_body = json.loads(e.reason)
                    err_msg = err_body.get("message", e.reason)
                except Exception:
                    err_msg = e.reason
                raise Exception(
                    f"Notion API 錯誤 ({e.code}): {err_msg}\n"
                    f"{'已達重試上限。' if retryable else '請確認 Integration Token 與權限。'}"
                ) from e
            except urllib.error.URLError as e:
                last_exc = e
                if attempt < self.MAX_RETRIES:
                    print(f"⚠️  {e.reason} (attempt {attempt}/{self.MAX_RETRIES})，{delay}s 後重試...")
                    time.sleep(delay)
                    continue
                raise Exception(f"網路錯誤: {e.reason}") from e
        raise Exception(f"請求失敗，已重試 {self.MAX_RETRIES} 次") from last_exc

    # ─────────────────────────────────────────────────────────────
    # Database 操作
    # ─────────────────────────────────────────────────────────────

    def search_databases(self) -> List[Dict]:
        """
        搜尋 Integration 有權存取的 Database。

        Returns:
            [{"id": "db-uuid", "title": "My DB", "url": "https://notion.so/..."}, ...]
        """
        result = self._request_with_retry(
            "POST",
            "/search",
            {"filter": {"value": "database", "property": "object"}},
        )
        databases = []
        for obj in result.get("results", []):
            title_parts = obj.get("title", [])
            title = "".join(p.get("plain_text", "") for p in title_parts) or "(無標題)"
            databases.append({
                "id": obj["id"],
                "title": title,
                "url": obj.get("url", ""),
            })
        return databases

    def query_database(self, database_id: str) -> List[Dict]:
        """
        查詢 Database 中的所有 Page（用於檢查是否已同步）。

        Returns:
            [{"id": "page-uuid", "title": "...", "notion_id": "...", "url": "..."}, ...]
        """
        results = []
        cursor = None
        while True:
            payload: Dict = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            data = self._request_with_retry("POST", f"/databases/{database_id}/query", payload)
            for page in data.get("results", []):
                title = self._extract_page_title(page)
                results.append({
                    "id": page["id"],
                    "title": title,
                    "url": page.get("url", ""),
                })
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return results

    # ─────────────────────────────────────────────────────────────
    # Page 操作
    # ─────────────────────────────────────────────────────────────

    def create_page(
        self,
        database_id: str,
        title: str,
        description: str = "",
        status: str = "Todo",
    ) -> Dict:
        """
        在 Database 中建立一個新 Page（任務卡片）。

        Properties 設計（標準欄位，建議 Database 包含）:
            Name    — Title （必要）
            Status  — Select: Todo / In Progress / Done
            Source  — Rich Text: "PLAN.md"
            Notes   — Rich Text: description

        Args:
            database_id: 目標 Notion Database ID
            title:       頁面標題（任務名稱）
            description: 任務描述（存入 Notes）
            status:      初始狀態（預設 "Todo"）

        Returns:
            {"id": "page-uuid", "url": "https://notion.so/...", "identifier": "page-uuid-short"}

        Raises:
            ValueError: 偵測到敏感資訊
            Exception:  API 錯誤
        """
        # 敏感資訊防護
        for field, value in [("title", title), ("description", description)]:
            hits = self.scan_sensitive(value)
            if hits:
                raise ValueError(
                    f"拒絕送出：{field} 含疑似敏感資訊 {hits}\n"
                    f"  請移除 API Key、密碼、Token 等內容後再重試。"
                )

        payload = {
            "parent": {"database_id": database_id},
            "properties": {
                "Name": {
                    "title": [{"type": "text", "text": {"content": title}}]
                },
                "Status": {
                    "select": {"name": status}
                },
                "Source": {
                    "rich_text": [{"type": "text", "text": {"content": "PLAN.md"}}]
                },
            },
        }

        # Notes 欄位（description 不為空才加）
        if description:
            payload["properties"]["Notes"] = {
                "rich_text": [{"type": "text", "text": {"content": description[:2000]}}]
            }

        # Page body（description 作為第一個段落）
        if description:
            payload["children"] = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": description[:2000]}}]
                    },
                }
            ]

        result = self._request_with_retry("POST", "/pages", payload)
        page_id = result["id"]
        short_id = page_id.replace("-", "")[:8].upper()  # 用於本地標記
        return {
            "id": page_id,
            "url": result.get("url", f"https://notion.so/{page_id.replace('-', '')}"),
            "identifier": short_id,
        }

    # ─────────────────────────────────────────────────────────────
    # 內部工具
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_page_title(page: Dict) -> str:
        """從 page 物件中提取 title（容錯處理）"""
        props = page.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                parts = prop.get("title", [])
                return "".join(p.get("plain_text", "") for p in parts)
        return "(無標題)"


class NotionIntegrator:
    """Notion 與本地 memory/ 的同步協調器（PLAN.md 為 Source of Truth）"""

    # 本地標記格式：任務後加 [NOTION:XXXXXXXX]（8 字元短 ID）
    _NOTION_ID_PATTERN = re.compile(r'\[NOTION:([A-F0-9]{8})\]')
    # 任務行格式：- [ ] 或 - [x]
    _TASK_PATTERN = re.compile(r'- \[([ x])\] (.+?)(?:\n|$)')

    def __init__(self, memory_root: Path, client: NotionClient):
        self.memory_root = Path(memory_root)
        self.active_task_file = self.memory_root / "01_active_task.md"
        self.knowledge_base_file = self.memory_root / "03_knowledge_base.md"
        self.client = client

    def parse_active_task(self) -> List[Dict]:
        """
        從 01_active_task.md 解析待辦任務。

        Returns:
            [
                {
                    "title": str,
                    "description": str,
                    "is_completed": bool,
                    "notion_id": str | None,   # 已同步則有短 ID
                },
                ...
            ]
        """
        if not self.active_task_file.exists():
            return []

        content = self.active_task_file.read_text(encoding="utf-8")
        tasks = []
        for match in self._TASK_PATTERN.finditer(content):
            is_completed = match.group(1) == "x"
            task_text = match.group(2)

            notion_match = self._NOTION_ID_PATTERN.search(task_text)
            notion_id = notion_match.group(1) if notion_match else None
            clean_title = self._NOTION_ID_PATTERN.sub("", task_text).strip()

            tasks.append({
                "title": clean_title,
                "description": clean_title,
                "is_completed": is_completed,
                "notion_id": notion_id,
            })
        return tasks

    def sync_task_to_notion(
        self,
        task: Dict,
        database_id: str,
    ) -> Optional[str]:
        """
        同步單一任務到 Notion Database。

        Args:
            task:        parse_active_task() 回傳的任務物件
            database_id: 目標 Notion Database ID

        Returns:
            Notion short ID（8 字元）或 None（失敗時）
        """
        if task.get("notion_id"):
            print(f"⏭️  任務已同步: {task['title']} [NOTION:{task['notion_id']}]")
            return task["notion_id"]

        try:
            result = self.client.create_page(
                database_id=database_id,
                title=task["title"],
                description=task["description"],
                status="Todo",
            )
            short_id = result["identifier"]
            print(f"✅ 建立 Notion Page: {short_id} - {task['title']}")
            print(f"   URL: {result['url']}")

            self._log_sync_event(task["title"], short_id, result["url"])
            return short_id

        except Exception as e:
            print(f"❌ 同步失敗: {task['title']}")
            print(f"   錯誤: {e}")
            return None

    def update_active_task_with_notion_ids(self, task_id_mapping: Dict[str, str]):
        """
        將 Notion short ID 寫回 01_active_task.md。

        Args:
            task_id_mapping: {"Task title": "XXXXXXXX", ...}
        """
        if not self.active_task_file.exists():
            return

        content = self.active_task_file.read_text(encoding="utf-8")
        for task_title, notion_id in task_id_mapping.items():
            pattern = rf'(- \[ \] {re.escape(task_title)})(?!\s*\[NOTION:)'
            replacement = rf'\1 [NOTION:{notion_id}]'
            content = re.sub(pattern, replacement, content)

        self.active_task_file.write_text(content, encoding="utf-8")
        print(f"✅ 已更新 {len(task_id_mapping)} 個任務的 Notion ID")

    def _log_sync_event(self, task_title: str, notion_id: str, url: str):
        """記錄同步事件到 knowledge_base"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = (
            f"\n### Notion Sync: {task_title} ({timestamp})\n"
            f"- **Notion ID**: [{notion_id}]({url})\n"
            f"- **Status**: Created\n"
        )
        with open(self.knowledge_base_file, "a", encoding="utf-8") as f:
            f.write(log_entry)


def main():
    """CLI 入口"""
    import argparse
    import sys

    # Windows 終端機 UTF-8 相容性
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Notion Integrator — PLAN.md → Notion Database 同步工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  # 列出 Integration 可存取的 Database
  python governance_tools/notion_integrator.py --list-databases

  # 同步未完成任務到指定 Database
  python governance_tools/notion_integrator.py --sync --database-id <DB_ID>

  # JSON 輸出（CI/dashboard 用）
  python governance_tools/notion_integrator.py --sync --database-id <DB_ID> --format json

環境變數:
  NOTION_API_KEY      Integration Token（必要）
  NOTION_DATABASE_ID  預設 Database ID（可省略 --database-id）
        """,
    )
    parser.add_argument("--memory-root", default="./memory", help="memory/ 目錄路徑（預設: ./memory）")
    parser.add_argument("--list-databases", action="store_true", help="列出 Integration 可存取的 Database")
    parser.add_argument("--sync", action="store_true", help="同步所有未完成任務到 Notion Database")
    parser.add_argument(
        "--database-id",
        default=os.getenv("NOTION_DATABASE_ID", ""),
        help="目標 Notion Database ID（也可設 NOTION_DATABASE_ID 環境變數）",
    )
    parser.add_argument(
        "--batch-delay",
        type=float,
        default=0.3,
        help="批次同步時每個 Page 間的延遲秒數（預設 0.3，避免 rate limit）",
    )
    parser.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="輸出格式（預設: human）",
    )

    args = parser.parse_args()

    def _json_out(data: dict):
        print(json.dumps(data, ensure_ascii=False))

    def _err(msg: str, exit_code: int = 1):
        if args.format == "json":
            _json_out({"status": "error", "error": msg})
        else:
            print(f"❌ {msg}")
        sys.exit(exit_code)

    try:
        client = NotionClient()
        integrator = NotionIntegrator(Path(args.memory_root), client)

        # ── --list-databases ──────────────────────────────────────
        if args.list_databases:
            databases = client.search_databases()
            if args.format == "json":
                _json_out({"databases": databases})
            else:
                if not databases:
                    print("⚠️  找不到任何 Database（請確認 Integration 已被加入至目標 Database）")
                else:
                    print("📋 可存取的 Databases:")
                    for db in databases:
                        print(f"  - {db['title']}")
                        print(f"    ID : {db['id']}")
                        print(f"    URL: {db['url']}")
            return

        # ── --sync ────────────────────────────────────────────────
        if args.sync:
            if not args.database_id:
                _err(
                    "請用 --database-id 指定 Database ID，"
                    "或設定 NOTION_DATABASE_ID 環境變數\n"
                    "（先執行 --list-databases 查看可用 Database）"
                )

            tasks = integrator.parse_active_task()
            pending = [t for t in tasks if not t["is_completed"] and not t["notion_id"]]

            if args.format != "json":
                print(f"📊 找到 {len(pending)} 個未同步的任務")

            task_id_mapping: Dict[str, str] = {}
            errors: List[str] = []

            for i, task in enumerate(pending):
                if i > 0 and args.batch_delay > 0:
                    time.sleep(args.batch_delay)
                notion_id = integrator.sync_task_to_notion(task, database_id=args.database_id)
                if notion_id:
                    task_id_mapping[task["title"]] = notion_id
                else:
                    errors.append(task["title"])

            if task_id_mapping:
                integrator.update_active_task_with_notion_ids(task_id_mapping)

            if args.format == "json":
                _json_out({
                    "status": "ok" if not errors else "partial",
                    "synced": list(task_id_mapping.values()),
                    "failed": errors,
                    "database_id": args.database_id,
                })
            else:
                print(f"\n✅ 完成: {len(task_id_mapping)} 個同步，{len(errors)} 個失敗")
            return

        # ── 無指令 ────────────────────────────────────────────────
        parser.print_help()

    except ValueError as e:
        _err(str(e))
    except Exception as e:
        _err(str(e))


if __name__ == "__main__":
    main()
