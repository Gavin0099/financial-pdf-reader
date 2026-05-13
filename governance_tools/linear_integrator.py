#!/usr/bin/env python3
"""
📋 Linear Integrator - Linear API 自動整合工具
Priority: 9 (Productivity Tooling)

功能:
1. 從 memory/01_active_task.md 解析任務
2. 自動建立對應的 Linear Issue
3. 雙向同步狀態 (Linear ↔ active_task)

設計原則:
- Linear-First: 優先使用 Linear 作為 Source of Truth
- 審計可追溯: 每個操作都記錄在 memory/03_knowledge_base.md
- 錯誤優雅降級: API 失敗時不影響本地工作流
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


class LinearClient:
    """Linear GraphQL API 客戶端"""

    API_ENDPOINT = "https://api.linear.app/graphql"
    REQUEST_TIMEOUT = 30  # seconds
    MAX_RETRIES = 3
    _RETRY_DELAYS = (1, 2, 4)  # exponential backoff (seconds)

    # 敏感資訊偵測規則 (pattern, label)
    _SENSITIVE_PATTERNS: List[Tuple[re.Pattern, str]] = [
        (re.compile(r'(lin_api_|sk-|xox[baprs]-)[A-Za-z0-9_\-]{10,}', re.IGNORECASE), 'API_KEY'),
        (re.compile(r'\b(password|passwd|secret|token)\s*[=:]\s*\S+', re.IGNORECASE), 'CREDENTIAL'),
        (re.compile(r'-----BEGIN\s+(?:\w+\s+)?PRIVATE KEY-----', re.IGNORECASE), 'PRIVATE_KEY'),
        (re.compile(r'[A-Za-z0-9+/]{40,}={0,2}(?=\s|$)'), 'POSSIBLE_SECRET'),  # base64 blob
    ]

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: Linear API Key (如未提供,從環境變數讀取)
        """
        self.api_key = api_key or os.getenv("LINEAR_API_KEY")
        if not self.api_key:
            raise ValueError(
                "LINEAR_API_KEY 未設定\n"
                "請設定環境變數: export LINEAR_API_KEY='your_key_here'\n"
                "或在 ~/.bashrc 中加入此行"
            )

    def scan_sensitive(self, text: str) -> List[str]:
        """
        掃描文字中的敏感資訊。

        Returns:
            偵測到的敏感類型清單 (空清單表示安全)
        """
        found = []
        for pattern, label in self._SENSITIVE_PATTERNS:
            if pattern.search(text):
                found.append(label)
        return found

    def _graphql_request(self, query: str, variables: Optional[Dict] = None) -> Dict:
        """
        執行 GraphQL 請求（含 timeout）。

        Raises:
            urllib.error.HTTPError: HTTP 層錯誤
            urllib.error.URLError: 網路層錯誤（DNS、連線失敗等）
        """
        payload = {"query": query, "variables": variables or {}}
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.api_key,
        }
        request = urllib.request.Request(
            self.API_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.REQUEST_TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise urllib.error.HTTPError(e.url, e.code, error_body, e.headers, None)
        except urllib.error.URLError as e:
            raise urllib.error.URLError(f"網路錯誤: {e.reason}")

    def _graphql_request_with_retry(
        self, query: str, variables: Optional[Dict] = None
    ) -> Dict:
        """
        帶重試機制的 GraphQL 請求。

        - HTTP 429 / 5xx → 指數退避重試（最多 MAX_RETRIES 次）
        - 其他錯誤    → 直接拋出

        Raises:
            Exception: 超過重試次數或不可重試的錯誤
        """
        last_exc: Optional[Exception] = None
        for attempt, delay in enumerate(self._RETRY_DELAYS, start=1):
            try:
                return self._graphql_request(query, variables)
            except urllib.error.HTTPError as e:
                last_exc = e
                retryable = e.code in (429, 502, 503, 504)
                if retryable and attempt < self.MAX_RETRIES:
                    print(
                        f"⚠️  Linear API {e.code} (attempt {attempt}/{self.MAX_RETRIES})，"
                        f"{delay}s 後重試..."
                    )
                    time.sleep(delay)
                    continue
                raise Exception(
                    f"Linear API 錯誤 ({e.code}): {e.reason}\n"
                    f"{'已達重試上限。' if retryable else '請確認 API Key 與參數。'}"
                ) from e
            except urllib.error.URLError as e:
                last_exc = e
                if attempt < self.MAX_RETRIES:
                    print(f"⚠️  {e.reason} (attempt {attempt}/{self.MAX_RETRIES})，{delay}s 後重試...")
                    time.sleep(delay)
                    continue
                raise Exception(f"網路錯誤: {e.reason}") from e
        raise Exception(f"請求失敗，已重試 {self.MAX_RETRIES} 次") from last_exc
    
    def create_issue(
        self,
        title: str,
        description: str,
        team_id: str,
        priority: int = 2,  # 0=None, 1=Urgent, 2=High, 3=Medium, 4=Low
        labels: Optional[List[str]] = None
    ) -> Dict:
        """
        建立 Linear Issue
        
        Args:
            title: Issue 標題
            description: Issue 描述 (支援 Markdown)
            team_id: Team ID (可從 Linear URL 取得)
            priority: 優先級 (0-4)
            labels: 標籤列表
        
        Returns:
            {
                "id": "issue_uuid",
                "url": "https://linear.app/team/issue/XXX-123",
                "identifier": "XXX-123"
            }
        """
        query = """
        mutation CreateIssue($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue {
                    id
                    identifier
                    url
                }
            }
        }
        """
        
        variables = {
            "input": {
                "title": title,
                "description": description,
                "teamId": team_id,
                "priority": priority,
                "labelIds": labels or []
            }
        }
        
        # 敏感資訊防護：掃描 title 與 description
        for field, value in [("title", title), ("description", description)]:
            hits = self.scan_sensitive(value)
            if hits:
                raise ValueError(
                    f"拒絕送出：{field} 含疑似敏感資訊 {hits}\n"
                    f"  請移除 API Key、密碼、Token 等內容後再重試。"
                )

        result = self._graphql_request_with_retry(query, variables)

        if result.get("data", {}).get("issueCreate", {}).get("success"):
            issue = result["data"]["issueCreate"]["issue"]
            return {
                "id": issue["id"],
                "url": issue["url"],
                "identifier": issue["identifier"],
            }
        else:
            errors = result.get("errors", [])
            raise Exception(f"建立 Issue 失敗: {errors}")
    
    def get_team_info(self) -> List[Dict]:
        """
        取得所有 Team 資訊
        
        Returns:
            [
                {"id": "team_uuid", "name": "Engineering", "key": "ENG"},
                ...
            ]
        """
        query = """
        query {
            teams {
                nodes {
                    id
                    name
                    key
                }
            }
        }
        """
        
        result = self._graphql_request_with_retry(query)
        return result.get("data", {}).get("teams", {}).get("nodes", [])
    
    def update_issue_status(self, issue_id: str, state_id: str) -> bool:
        """
        更新 Issue 狀態
        
        Args:
            issue_id: Issue UUID
            state_id: 狀態 UUID (可從 Linear 介面取得)
        
        Returns:
            成功/失敗
        """
        query = """
        mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
            }
        }
        """
        
        variables = {
            "id": issue_id,
            "input": {"stateId": state_id}
        }
        
        result = self._graphql_request_with_retry(query, variables)
        return result.get("data", {}).get("issueUpdate", {}).get("success", False)


class LinearIntegrator:
    """Linear 與本地 memory/ 的雙向同步協調器"""
    
    def __init__(self, memory_root: Path, linear_client: LinearClient):
        self.memory_root = Path(memory_root)
        self.active_task_file = self.memory_root / "01_active_task.md"
        self.knowledge_base_file = self.memory_root / "03_knowledge_base.md"
        self.linear = linear_client
    
    def parse_active_task(self) -> List[Dict]:
        """
        從 01_active_task.md 解析待辦任務
        
        Returns:
            [
                {
                    "title": "Task title",
                    "description": "Task details",
                    "is_completed": False,
                    "linear_id": None  # 如果已同步則有 ID
                },
                ...
            ]
        """
        if not self.active_task_file.exists():
            return []
        
        with open(self.active_task_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        tasks = []
        
        # 匹配 "- [ ] Task description" 或 "- [x] Task description"
        task_pattern = r'- \[([ x])\] (.+?)(?:\n|$)'
        
        for match in re.finditer(task_pattern, content):
            is_completed = match.group(1) == 'x'
            task_text = match.group(2)
            
            # 檢查是否已有 Linear ID (格式: [LINEAR:XXX-123])
            linear_match = re.search(r'\[LINEAR:([A-Z]+-\d+)\]', task_text)
            linear_id = linear_match.group(1) if linear_match else None
            
            # 移除 Linear ID 標記,取得乾淨的標題
            clean_title = re.sub(r'\[LINEAR:[A-Z]+-\d+\]', '', task_text).strip()
            
            tasks.append({
                "title": clean_title,
                "description": clean_title,  # 簡化版,可擴充為讀取詳細描述
                "is_completed": is_completed,
                "linear_id": linear_id
            })
        
        return tasks
    
    def sync_task_to_linear(
        self,
        task: Dict,
        team_id: str,
        priority: int = 2
    ) -> Optional[str]:
        """
        同步單一任務到 Linear
        
        Args:
            task: parse_active_task() 回傳的任務物件
            team_id: Linear Team ID
            priority: 優先級
        
        Returns:
            Linear Issue Identifier (e.g., "ENG-123") 或 None (如失敗)
        """
        if task.get("linear_id"):
            print(f"⏭️  任務已同步: {task['title']} [{task['linear_id']}]")
            return task['linear_id']
        
        try:
            result = self.linear.create_issue(
                title=task['title'],
                description=task['description'],
                team_id=team_id,
                priority=priority
            )
            
            identifier = result['identifier']
            print(f"✅ 建立 Linear Issue: {identifier} - {task['title']}")
            print(f"   URL: {result['url']}")
            
            # 記錄到 knowledge_base
            self._log_sync_event(task['title'], identifier, result['url'])
            
            return identifier
            
        except Exception as e:
            print(f"❌ 同步失敗: {task['title']}")
            print(f"   錯誤: {e}")
            return None
    
    def update_active_task_with_linear_ids(self, task_id_mapping: Dict[str, str]):
        """
        將 Linear ID 寫回 01_active_task.md
        
        Args:
            task_id_mapping: {"Task title": "ENG-123", ...}
        """
        if not self.active_task_file.exists():
            return
        
        with open(self.active_task_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        for task_title, linear_id in task_id_mapping.items():
            # 尋找對應的任務行並加上 [LINEAR:XXX-123] 標記
            pattern = rf'(- \[ \] {re.escape(task_title)})(?!\[LINEAR:)'
            replacement = rf'\1 [LINEAR:{linear_id}]'
            content = re.sub(pattern, replacement, content)
        
        with open(self.active_task_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"✅ 已更新 {len(task_id_mapping)} 個任務的 Linear ID")
    
    def _log_sync_event(self, task_title: str, linear_id: str, url: str):
        """記錄同步事件到 knowledge_base"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_entry = f"""
### Linear Sync: {task_title} ({timestamp})
- **Linear ID**: [{linear_id}]({url})
- **Status**: Created
"""
        
        # Append 到 knowledge_base (如果檔案不存在則建立)
        with open(self.knowledge_base_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)


def main():
    """CLI 入口"""
    import argparse
    import sys

    # Windows 終端機 UTF-8 相容性
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Linear Integrator - Linear API 整合工具")
    parser.add_argument("--memory-root", default="./memory", help="memory/ 目錄路徑")
    parser.add_argument("--list-teams", action="store_true", help="列出所有 Team")
    parser.add_argument("--sync", action="store_true", help="同步所有未完成任務到 Linear")
    parser.add_argument("--team-id", help="Linear Team ID (用於 --sync)")
    parser.add_argument("--priority", type=int, default=2, help="優先級 (0-4, 預設 2=High)")
    parser.add_argument(
        "--batch-delay", type=float, default=0.5,
        help="批次同步時每個 Issue 間的延遲秒數（預設 0.5，降低 rate limit 風險）"
    )
    parser.add_argument(
        "--format", choices=["human", "json"], default="human",
        help="輸出格式 (預設: human)"
    )

    args = parser.parse_args()

    def _output(data: dict):
        """根據 --format 輸出結果"""
        if args.format == "json":
            print(json.dumps(data, ensure_ascii=False))
        else:
            # human-readable 已在各操作內 print，此處輸出摘要
            status = data.get("status", "ok")
            if status != "ok":
                print(f"❌ {data.get('error', status)}")

    try:
        linear = LinearClient()
        integrator = LinearIntegrator(Path(args.memory_root), linear)

        if args.list_teams:
            teams = linear.get_team_info()
            if args.format == "json":
                print(json.dumps({"teams": teams}, ensure_ascii=False))
            else:
                print("📋 可用的 Teams:")
                for team in teams:
                    print(f"  - {team['name']} (Key: {team['key']}, ID: {team['id']})")

        elif args.sync:
            if not args.team_id:
                _output({"status": "error", "error": "請使用 --team-id 指定 Team（先執行 --list-teams 查看）"})
                sys.exit(1)

            tasks = integrator.parse_active_task()
            incomplete_tasks = [t for t in tasks if not t["is_completed"] and not t["linear_id"]]

            if args.format != "json":
                print(f"📊 找到 {len(incomplete_tasks)} 個未同步的任務")

            task_id_mapping = {}
            errors = []
            for i, task in enumerate(incomplete_tasks):
                if i > 0 and args.batch_delay > 0:
                    time.sleep(args.batch_delay)
                linear_id = integrator.sync_task_to_linear(
                    task, team_id=args.team_id, priority=args.priority
                )
                if linear_id:
                    task_id_mapping[task["title"]] = linear_id
                else:
                    errors.append(task["title"])

            if task_id_mapping:
                integrator.update_active_task_with_linear_ids(task_id_mapping)

            if args.format == "json":
                print(json.dumps({
                    "status": "ok" if not errors else "partial",
                    "synced": list(task_id_mapping.values()),
                    "failed": errors,
                }, ensure_ascii=False))

        else:
            parser.print_help()

    except ValueError as e:
        msg = str(e)
        if args.format == "json":
            print(json.dumps({"status": "error", "error": msg}, ensure_ascii=False))
        else:
            print(f"❌ 設定錯誤: {msg}")
        sys.exit(1)
    except Exception as e:
        msg = str(e)
        if args.format == "json":
            print(json.dumps({"status": "error", "error": msg}, ensure_ascii=False))
        else:
            print(f"❌ 執行錯誤: {msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
