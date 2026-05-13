#!/usr/bin/env python3
"""
manage_agent_closeout.py — Agent integration manager for session closeout.

Manages installation, verification, repair, uninstallation, and capability
reporting of session closeout integrations across AI agents.

The core closeout pipeline (session_closeout_entry.py) is agent-agnostic.
This tool manages how each agent *triggers* that pipeline. Each agent is
implemented as an adapter with a defined contract:

    detect()        — detect if the agent is present/configured in this repo
    capability()    — report tier, label, surface description
    install()       — install the closeout trigger
    verify()        — verify the trigger is correctly installed
    repair()        — install if missing, re-install if broken
    uninstall()     — remove the installed trigger
    print_manual()  — print manual steps for agents without automation

Capability tiers are assigned based on *integration surface*, not product brand:

    Tier A  Native lifecycle hooks
            Agent has a formal session/lifecycle hook surface.
            Closeout fires automatically.
            Current: Claude Code, Copilot CLI/cloud agent, Gemini CLI

    Tier B  Wrapper-based integration
            No stable native session-end hook, but can be connected via
            launcher, task wrapper, or equivalent mechanism.
            Current: Codex CLI (sessionEnd hook not confirmed in docs)

    Tier C  Manual only
            No reliable automation surface. User must run closeout manually.
            Current: ChatGPT web

    Tier D  Unknown / unverified
            Insufficient documentation to classify. Stub provided.

Usage:
    python -m governance_tools.manage_agent_closeout status
    python -m governance_tools.manage_agent_closeout capabilities
    python -m governance_tools.manage_agent_closeout install --agent claude
    python -m governance_tools.manage_agent_closeout install --agent all
    python -m governance_tools.manage_agent_closeout verify --agent copilot
    python -m governance_tools.manage_agent_closeout repair --agent gemini
    python -m governance_tools.manage_agent_closeout uninstall --agent claude
    python -m governance_tools.manage_agent_closeout print-manual --agent chatgpt-web
"""

from __future__ import annotations

import abc
import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── Capability tier constants ─────────────────────────────────────────────────

TIER_A = "A"
TIER_B = "B"
TIER_C = "C"
TIER_D = "D"

TIER_LABELS = {
    TIER_A: "Native lifecycle hooks (fully automated)",
    TIER_B: "Wrapper-based integration (semi-automated)",
    TIER_C: "Manual only (no automation surface)",
    TIER_D: "Unknown / unverified",
}


# ── Adapter base contract ─────────────────────────────────────────────────────

class AgentAdapter(abc.ABC):
    """
    Abstract base for all agent closeout adapters.

    Each adapter knows:
    - Which config files to read/write
    - How to detect whether the agent is present
    - How to install, verify, repair, and uninstall the closeout trigger
    - What tier this agent belongs to (and why)
    - What manual steps to print for partially/non-automated agents
    """

    @property
    @abc.abstractmethod
    def agent_id(self) -> str:
        """Unique identifier, e.g. 'claude', 'copilot', 'gemini'."""

    @property
    @abc.abstractmethod
    def display_name(self) -> str:
        """Human-readable name, e.g. 'Claude Code'."""

    @property
    @abc.abstractmethod
    def tier(self) -> str:
        """Capability tier: A, B, C, or D."""

    @property
    @abc.abstractmethod
    def surface_description(self) -> str:
        """One sentence describing the integration surface and why it has this tier."""

    def capability(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "tier": self.tier,
            "tier_label": TIER_LABELS.get(self.tier, "Unknown"),
            "surface_description": self.surface_description,
        }

    @abc.abstractmethod
    def detect(self, project_root: Path) -> dict[str, Any]:
        """
        Detect whether this agent appears to be active in the project.
        Returns: {"detected": bool, "evidence": str}
        """

    @abc.abstractmethod
    def install(self, project_root: Path, framework_root: Path) -> dict[str, Any]:
        """
        Install the closeout trigger.
        Returns: {"status": str, "location": str|None, "message": str}
        Status values: installed | already_installed | manual_only | error
        """

    @abc.abstractmethod
    def verify(self, project_root: Path, framework_root: Path) -> dict[str, Any]:
        """
        Verify the trigger is correctly installed.
        Returns: {"installed": bool, "location": str|None, "note": str,
                  "manual_only": bool}
        """

    def repair(self, project_root: Path, framework_root: Path) -> dict[str, Any]:
        """
        Repair the integration. Default: verify then install if missing.
        Adapters may override for agent-specific repair logic.
        """
        v = self.verify(project_root, framework_root)
        if v["installed"] or v.get("manual_only"):
            return {
                "agent": self.agent_id,
                "status": "no_repair_needed",
                "message": "Integration is already correctly configured.",
                "location": v.get("location"),
            }
        result = self.install(project_root, framework_root)
        return {"agent": self.agent_id, "repaired": True, **result}

    def uninstall(self, project_root: Path) -> dict[str, Any]:
        """
        Remove the installed trigger.
        Default implementation: no-op with explanation.
        Override in adapters that write config files.
        """
        return {
            "agent": self.agent_id,
            "status": "not_implemented",
            "message": f"Uninstall not implemented for {self.display_name}.",
        }

    @abc.abstractmethod
    def print_manual(self, framework_root: Path) -> str:
        """
        Return human-readable manual closeout instructions for this agent.
        Always implemented — even Tier A agents benefit from a manual fallback doc.
        """


# ── Shared helpers ────────────────────────────────────────────────────────────

def _resolve_framework_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _fmt_cmd(template: str, framework_root: Path) -> str:
    return template.replace("{framework_root}", str(framework_root).replace("\\", "/"))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


_CLOSEOUT_CMD = (
    "python {framework_root}/governance_tools/session_closeout_entry.py "
    "--project-root . 2>/dev/null || true"
)
_CLOSEOUT_CMD_BARE = (
    "python {framework_root}/governance_tools/session_closeout_entry.py "
    "--project-root ."
)


# ── Claude Code adapter ───────────────────────────────────────────────────────

class ClaudeAdapter(AgentAdapter):
    """
    Claude Code (claude.ai/code, VS Code extension, CLI).

    Integration surface: .claude/settings.json or ~/.claude/settings.json
    Hook key: hooks.Stop[].hooks[].command
    Reference: Claude Code documentation — hooks configuration

    Tier A: Claude Code has a formal Stop hook that fires at session end.
    """

    @property
    def agent_id(self) -> str:
        return "claude"

    @property
    def display_name(self) -> str:
        return "Claude Code"

    @property
    def tier(self) -> str:
        return TIER_A

    @property
    def surface_description(self) -> str:
        return (
            "Claude Code Stop hook in .claude/settings.json. "
            "Fires automatically at every session end."
        )

    def detect(self, project_root: Path) -> dict[str, Any]:
        has_dir = (project_root / ".claude").is_dir()
        return {
            "detected": has_dir,
            "evidence": ".claude/ directory present" if has_dir else "no .claude/ directory",
        }

    def _find_installed(self, project_root: Path, framework_root: Path) -> tuple[bool, str | None]:
        candidates = [
            project_root / ".claude" / "settings.json",
            project_root / ".claude" / "settings.local.json",
            Path.home() / ".claude" / "settings.json",
        ]
        for p in candidates:
            data = _read_json(p)
            for group in data.get("hooks", {}).get("Stop", []):
                for h in (group.get("hooks", []) if isinstance(group, dict) else []):
                    if "session_closeout_entry" in h.get("command", ""):
                        return True, str(p)
        return False, None

    def install(self, project_root: Path, framework_root: Path) -> dict[str, Any]:
        installed, loc = self._find_installed(project_root, framework_root)
        if installed:
            return {
                "status": "already_installed",
                "location": loc,
                "message": "Governance stop hook already present.",
            }
        settings_path = project_root / ".claude" / "settings.json"
        data = _read_json(settings_path)
        data.setdefault("hooks", {}).setdefault("Stop", [{"hooks": []}])
        if not data["hooks"]["Stop"]:
            data["hooks"]["Stop"] = [{"hooks": []}]
        if "hooks" not in data["hooks"]["Stop"][0]:
            data["hooks"]["Stop"][0]["hooks"] = []
        data["hooks"]["Stop"][0]["hooks"].append({
            "type": "command",
            "command": _fmt_cmd(_CLOSEOUT_CMD, framework_root),
            "statusMessage": "Running governance session closeout...",
        })
        _write_json(settings_path, data)
        return {
            "status": "installed",
            "location": str(settings_path),
            "message": f"Governance Stop hook added to {settings_path}.",
        }

    def verify(self, project_root: Path, framework_root: Path) -> dict[str, Any]:
        installed, loc = self._find_installed(project_root, framework_root)
        return {
            "installed": installed,
            "manual_only": False,
            "location": loc,
            "note": (
                f"Stop hook found in {Path(loc).name}" if installed
                else "No governance stop hook found in .claude/settings.json or ~/.claude/settings.json"
            ),
        }

    def uninstall(self, project_root: Path) -> dict[str, Any]:
        settings_path = project_root / ".claude" / "settings.json"
        data = _read_json(settings_path)
        stop = data.get("hooks", {}).get("Stop", [])
        changed = False
        for group in stop:
            if isinstance(group, dict) and "hooks" in group:
                before = len(group["hooks"])
                group["hooks"] = [
                    h for h in group["hooks"]
                    if "session_closeout_entry" not in h.get("command", "")
                ]
                changed = changed or len(group["hooks"]) < before
        if changed:
            _write_json(settings_path, data)
            return {
                "agent": self.agent_id,
                "status": "uninstalled",
                "location": str(settings_path),
                "message": "Governance stop hook removed from .claude/settings.json",
            }
        return {
            "agent": self.agent_id,
            "status": "not_found",
            "message": "No governance stop hook found to remove.",
        }

    def print_manual(self, framework_root: Path) -> str:
        cmd = _fmt_cmd(_CLOSEOUT_CMD_BARE, framework_root)
        return (
            f"[{self.display_name}] Manual closeout (fallback if stop hook is not installed):\n\n"
            f"    {cmd}\n\n"
            f"Or install the stop hook:\n\n"
            f"    python -m governance_tools.manage_agent_closeout install --agent claude"
        )


# ── Copilot adapter ───────────────────────────────────────────────────────────

class CopilotAdapter(AgentAdapter):
    """
    GitHub Copilot CLI / cloud agent.

    Integration surface: .github/hooks/session-end.json (or session_end.json)
    Hook key: hooks.sessionEnd[].bash / .powershell
    Reference: https://docs.github.com/en/copilot/reference/hooks-configuration

    Tier A: Copilot CLI and cloud agent have a native sessionEnd lifecycle hook
    stored in .github/hooks/. Confirmed in official GitHub documentation.

    Fallback: .vscode/tasks.json task (for VS Code-only usage without CLI hooks).
    The fallback is NOT the primary path — it is recorded as secondary only.
    """

    HOOKS_DIR = ".github/hooks"
    HOOK_FILE = "session-end.json"

    @property
    def agent_id(self) -> str:
        return "copilot"

    @property
    def display_name(self) -> str:
        return "GitHub Copilot"

    @property
    def tier(self) -> str:
        return TIER_A

    @property
    def surface_description(self) -> str:
        return (
            "Copilot CLI / cloud agent: native sessionEnd lifecycle hook "
            "in .github/hooks/session-end.json. "
            "VS Code task in .vscode/tasks.json is a secondary fallback only."
        )

    def detect(self, project_root: Path) -> dict[str, Any]:
        has_github = (project_root / ".github").is_dir()
        return {
            "detected": has_github,
            "evidence": ".github/ directory present" if has_github else "no .github/ directory",
        }

    def _hook_path(self, project_root: Path) -> Path:
        return project_root / self.HOOKS_DIR / self.HOOK_FILE

    def _is_hook_installed(self, project_root: Path) -> bool:
        p = self._hook_path(project_root)
        if not p.exists():
            return False
        data = _read_json(p)
        hooks = data.get("hooks", {}).get("sessionEnd", [])
        return any("session_closeout_entry" in h.get("bash", "") for h in hooks)

    def install(self, project_root: Path, framework_root: Path) -> dict[str, Any]:
        if self._is_hook_installed(project_root):
            return {
                "status": "already_installed",
                "location": str(self._hook_path(project_root)),
                "message": "Copilot sessionEnd hook already present.",
            }
        hook_path = self._hook_path(project_root)
        data = _read_json(hook_path)
        data.setdefault("hooks", {}).setdefault("sessionEnd", [])
        bash_cmd = _fmt_cmd(_CLOSEOUT_CMD, framework_root)
        ps_cmd = bash_cmd.replace("2>/dev/null", "2>$null")
        data["hooks"]["sessionEnd"].append({
            "type": "command",
            "bash": bash_cmd,
            "powershell": ps_cmd,
            "timeoutSec": 30,
        })
        _write_json(hook_path, data)
        return {
            "status": "installed",
            "location": str(hook_path),
            "message": (
                f"Copilot sessionEnd hook written to {hook_path}. "
                "Fires automatically when Copilot CLI / cloud agent session ends."
            ),
        }

    def verify(self, project_root: Path, framework_root: Path) -> dict[str, Any]:
        installed = self._is_hook_installed(project_root)
        hook_path = self._hook_path(project_root)
        return {
            "installed": installed,
            "manual_only": False,
            "location": str(hook_path) if installed else None,
            "note": (
                f"sessionEnd hook found in {self.HOOK_FILE}" if installed
                else f"No governance hook found in {self.HOOKS_DIR}/{self.HOOK_FILE}"
            ),
        }

    def uninstall(self, project_root: Path) -> dict[str, Any]:
        hook_path = self._hook_path(project_root)
        data = _read_json(hook_path)
        hooks = data.get("hooks", {}).get("sessionEnd", [])
        before = len(hooks)
        data["hooks"]["sessionEnd"] = [
            h for h in hooks
            if "session_closeout_entry" not in h.get("bash", "")
        ]
        if len(data["hooks"]["sessionEnd"]) < before:
            _write_json(hook_path, data)
            return {
                "agent": self.agent_id,
                "status": "uninstalled",
                "location": str(hook_path),
                "message": "Governance sessionEnd hook removed.",
            }
        return {"agent": self.agent_id, "status": "not_found", "message": "No governance hook found to remove."}

    def print_manual(self, framework_root: Path) -> str:
        cmd = _fmt_cmd(_CLOSEOUT_CMD_BARE, framework_root)
        return (
            f"[{self.display_name}] Manual closeout (if native hook is not active):\n\n"
            f"    {cmd}\n\n"
            f"Primary integration: sessionEnd hook in {self.HOOKS_DIR}/{self.HOOK_FILE}\n"
            f"Install with: python -m governance_tools.manage_agent_closeout install --agent copilot"
        )


# ── Gemini CLI adapter ────────────────────────────────────────────────────────

class GeminiAdapter(AgentAdapter):
    """
    Gemini CLI (and VS Code Gemini Code Assist in agent mode, which is CLI-driven).

    Integration surface: .gemini/settings.json (project) or ~/.gemini/settings.json (user)
    Hook key: hooks.SessionEnd (list of hook objects)
    Reference: https://geminicli.com/docs/hooks/reference/
               Google Cloud — Gemini CLI hooks documentation

    Hook object schema (confirmed):
        {"command": "...", "timeout": 30}
    Hook input: JSON via stdin with fields session_id, transcript_path, cwd,
                hook_event_name, timestamp.
    Exit codes: 0=success, 2=block, others=warning.

    Tier A: Gemini CLI has native SessionEnd lifecycle hook support, confirmed
    in official documentation. VS Code Gemini Code Assist agent mode is
    driven by Gemini CLI.
    """

    CONFIG_PATH = ".gemini/settings.json"
    HOOK_EVENT = "SessionEnd"

    @property
    def agent_id(self) -> str:
        return "gemini"

    @property
    def display_name(self) -> str:
        return "Gemini CLI"

    @property
    def tier(self) -> str:
        return TIER_A

    @property
    def surface_description(self) -> str:
        return (
            "Gemini CLI native SessionEnd hook in .gemini/settings.json. "
            "Also covers VS Code Gemini Code Assist agent mode (CLI-driven). "
            "Hook receives session_id, transcript_path, cwd via stdin JSON."
        )

    def detect(self, project_root: Path) -> dict[str, Any]:
        has_dir = (project_root / ".gemini").is_dir()
        return {
            "detected": has_dir,
            "evidence": ".gemini/ directory present" if has_dir else "no .gemini/ directory",
        }

    def _settings_path(self, project_root: Path) -> Path:
        return project_root / self.CONFIG_PATH

    def _is_hook_installed(self, project_root: Path) -> bool:
        data = _read_json(self._settings_path(project_root))
        hooks = data.get("hooks", {}).get(self.HOOK_EVENT, [])
        return any("session_closeout_entry" in h.get("command", "") for h in hooks)

    def install(self, project_root: Path, framework_root: Path) -> dict[str, Any]:
        if self._is_hook_installed(project_root):
            return {
                "status": "already_installed",
                "location": str(self._settings_path(project_root)),
                "message": f"Gemini {self.HOOK_EVENT} hook already present.",
            }
        settings_path = self._settings_path(project_root)
        data = _read_json(settings_path)
        data.setdefault("hooks", {}).setdefault(self.HOOK_EVENT, [])
        data["hooks"][self.HOOK_EVENT].append({
            "command": _fmt_cmd(_CLOSEOUT_CMD, framework_root),
            "timeout": 30,
        })
        _write_json(settings_path, data)
        return {
            "status": "installed",
            "location": str(settings_path),
            "message": (
                f"Gemini {self.HOOK_EVENT} hook written to {settings_path}. "
                "Fires automatically when Gemini CLI session ends."
            ),
        }

    def verify(self, project_root: Path, framework_root: Path) -> dict[str, Any]:
        installed = self._is_hook_installed(project_root)
        p = self._settings_path(project_root)
        return {
            "installed": installed,
            "manual_only": False,
            "location": str(p) if installed else None,
            "note": (
                f"{self.HOOK_EVENT} hook found in {self.CONFIG_PATH}" if installed
                else f"No governance hook found in {self.CONFIG_PATH}"
            ),
        }

    def uninstall(self, project_root: Path) -> dict[str, Any]:
        settings_path = self._settings_path(project_root)
        data = _read_json(settings_path)
        hooks = data.get("hooks", {}).get(self.HOOK_EVENT, [])
        before = len(hooks)
        data["hooks"][self.HOOK_EVENT] = [
            h for h in hooks
            if "session_closeout_entry" not in h.get("command", "")
        ]
        if len(data["hooks"][self.HOOK_EVENT]) < before:
            _write_json(settings_path, data)
            return {
                "agent": self.agent_id,
                "status": "uninstalled",
                "location": str(settings_path),
                "message": f"Governance {self.HOOK_EVENT} hook removed.",
            }
        return {"agent": self.agent_id, "status": "not_found", "message": "No governance hook found to remove."}

    def print_manual(self, framework_root: Path) -> str:
        cmd = _fmt_cmd(_CLOSEOUT_CMD_BARE, framework_root)
        return (
            f"[{self.display_name}] Manual closeout (if native hook is not active):\n\n"
            f"    {cmd}\n\n"
            f"Primary integration: {self.HOOK_EVENT} hook in {self.CONFIG_PATH}\n"
            f"Install with: python -m governance_tools.manage_agent_closeout install --agent gemini"
        )


# ── ChatGPT web adapter ───────────────────────────────────────────────────────

class ChatGPTWebAdapter(AgentAdapter):
    """
    ChatGPT web product (chat.openai.com).

    No local session lifecycle hook surface exists.
    ChatGPT web does not interact with local repo files or have a hook
    mechanism that can trigger local commands.

    Tier C: Manual only. Closeout must be run explicitly by the user.
    """

    @property
    def agent_id(self) -> str:
        return "chatgpt-web"

    @property
    def display_name(self) -> str:
        return "ChatGPT (web)"

    @property
    def tier(self) -> str:
        return TIER_C

    @property
    def surface_description(self) -> str:
        return (
            "ChatGPT web has no local session lifecycle hook. "
            "No automated integration is possible. Manual closeout only."
        )

    def detect(self, project_root: Path) -> dict[str, Any]:
        return {"detected": False, "evidence": "ChatGPT web leaves no detectable local artifacts"}

    def install(self, project_root: Path, framework_root: Path) -> dict[str, Any]:
        return {
            "status": "manual_only",
            "location": None,
            "message": (
                "ChatGPT web has no local hook surface. No installation possible.\n"
                f"Run manually: {_fmt_cmd(_CLOSEOUT_CMD_BARE, framework_root)}"
            ),
        }

    def verify(self, project_root: Path, framework_root: Path) -> dict[str, Any]:
        return {
            "installed": False,
            "manual_only": True,
            "location": None,
            "note": "Manual only — no automatable integration surface exists for ChatGPT web",
        }

    def uninstall(self, project_root: Path) -> dict[str, Any]:
        return {
            "agent": self.agent_id,
            "status": "not_applicable",
            "message": "ChatGPT web has no installed integration to remove.",
        }

    def print_manual(self, framework_root: Path) -> str:
        cmd = _fmt_cmd(_CLOSEOUT_CMD_BARE, framework_root)
        return (
            f"[{self.display_name}] Manual closeout — run this before ending each ChatGPT session:\n\n"
            f"    {cmd}\n\n"
            f"ChatGPT web has no local hook surface. Automation is not possible.\n"
            f"Recommended: add this command to your session-end checklist or shell alias."
        )


# ── Codex CLI adapter ─────────────────────────────────────────────────────────

class CodexCLIAdapter(AgentAdapter):
    """
    OpenAI Codex CLI (open-source terminal agent, npm installable).

    Integration surface: under investigation.
    Confirmed: has 'notify' webhook feature and userPromptSubmit hook.
    Unconfirmed: explicit sessionEnd hook with stable config schema.

    Tier B: Wrapper-based. A sessionEnd-equivalent hook has not been confirmed
    in official documentation. Codex CLI can be wrapped at the launcher level,
    but no direct config-file-based sessionEnd hook is currently verified.

    This adapter is a stub. The install/verify paths produce informational output
    until the Codex CLI hook surface is confirmed and stabilized.
    """

    @property
    def agent_id(self) -> str:
        return "codex"

    @property
    def display_name(self) -> str:
        return "OpenAI Codex CLI"

    @property
    def tier(self) -> str:
        return TIER_B

    @property
    def surface_description(self) -> str:
        return (
            "Codex CLI has webhook notify and userPromptSubmit hooks confirmed. "
            "sessionEnd hook not confirmed in official docs. "
            "Tier B (wrapper-based) until sessionEnd surface is verified. "
            "This adapter is a stub — install produces manual instructions only."
        )

    def detect(self, project_root: Path) -> dict[str, Any]:
        # Codex CLI does not leave a standard detectable config file
        return {"detected": False, "evidence": "No standard Codex CLI config file detected"}

    def install(self, project_root: Path, framework_root: Path) -> dict[str, Any]:
        cmd = _fmt_cmd(_CLOSEOUT_CMD_BARE, framework_root)
        return {
            "status": "manual_only",
            "location": None,
            "message": (
                "Codex CLI sessionEnd hook is not confirmed in official documentation. "
                "Automated installation is not available yet.\n\n"
                f"Manual closeout: {cmd}\n\n"
                "When Codex CLI sessionEnd hook surface is confirmed, "
                "this adapter will be updated to support automated installation."
            ),
        }

    def verify(self, project_root: Path, framework_root: Path) -> dict[str, Any]:
        return {
            "installed": False,
            "manual_only": True,
            "location": None,
            "note": (
                "Codex CLI sessionEnd hook not yet confirmed — stub adapter only. "
                "Tier B assigned pending verification."
            ),
        }

    def uninstall(self, project_root: Path) -> dict[str, Any]:
        return {
            "agent": self.agent_id,
            "status": "not_applicable",
            "message": "No automated integration installed for Codex CLI (stub adapter).",
        }

    def print_manual(self, framework_root: Path) -> str:
        cmd = _fmt_cmd(_CLOSEOUT_CMD_BARE, framework_root)
        return (
            f"[{self.display_name}] Manual closeout — run before ending each Codex session:\n\n"
            f"    {cmd}\n\n"
            f"Status: sessionEnd hook not confirmed in official Codex CLI docs.\n"
            f"This adapter will be upgraded when hook surface is verified."
        )


# ── Registry ──────────────────────────────────────────────────────────────────

_ADAPTERS: dict[str, AgentAdapter] = {
    a.agent_id: a for a in [
        ClaudeAdapter(),
        CopilotAdapter(),
        GeminiAdapter(),
        ChatGPTWebAdapter(),
        CodexCLIAdapter(),
    ]
}

KNOWN_AGENTS = list(_ADAPTERS.keys())


def get_adapter(agent_id: str) -> AgentAdapter | None:
    return _ADAPTERS.get(agent_id)


# ── Operations ────────────────────────────────────────────────────────────────

def op_status(project_root: Path, framework_root: Path) -> list[dict[str, Any]]:
    results = []
    for agent_id, adapter in _ADAPTERS.items():
        v = adapter.verify(project_root, framework_root)
        cap = adapter.capability()
        results.append({
            "agent_id": agent_id,
            "display_name": cap["display_name"],
            "tier": cap["tier"],
            "tier_label": cap["tier_label"],
            "installed": v["installed"],
            "manual_only": v.get("manual_only", False),
            "location": v.get("location"),
            "note": v.get("note"),
        })
    return results


def op_capabilities() -> list[dict[str, Any]]:
    return [a.capability() for a in _ADAPTERS.values()]


# ── Output formatting ─────────────────────────────────────────────────────────

def _fmt_status_human(results: list[dict[str, Any]]) -> str:
    lines = ["[manage_agent_closeout] status\n"]
    for r in results:
        if r["installed"]:
            marker = "✓"
        elif r["manual_only"]:
            marker = "—"
        else:
            marker = "✗"
        lines.append(
            f"  {marker} {r['display_name']:<24} "
            f"Tier {r['tier']}  {r['note']}"
        )
    lines += [
        "",
        "Legend: ✓ installed   ✗ not installed   — manual/stub only",
    ]
    return "\n".join(lines)


def _fmt_capabilities_human(caps: list[dict[str, Any]]) -> str:
    lines = ["[manage_agent_closeout] capabilities\n"]
    for c in caps:
        lines.append(f"  {c['display_name']:<24} Tier {c['tier']}  {c['tier_label']}")
        lines.append(f"      {c['surface_description']}")
        lines.append("")
    return "\n".join(lines)


def _fmt_op_human(result: dict[str, Any], operation: str) -> str:
    agent = result.get("agent", "?")
    if "installed" in result and operation in ("verify",):
        status_val = (
            "installed" if result["installed"]
            else "manual_only" if result.get("manual_only")
            else "not_installed"
        )
    else:
        status_val = result.get("status", "?")
    lines = [
        f"[manage_agent_closeout] {operation} --agent {agent}",
        f"status={status_val}",
    ]
    if result.get("location"):
        lines.append(f"location={result['location']}")
    msg = result.get("message") or result.get("note", "")
    if msg:
        lines.append(f"message={msg}")
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Manage session closeout integrations for AI agents. "
            "The core closeout pipeline (session_closeout_entry.py) is agent-agnostic. "
            "This tool manages how each agent triggers that pipeline."
        )
    )
    parser.add_argument("--project-root", default=".", help="Project root (default: .)")
    parser.add_argument("--format", choices=["human", "json"], default="human")

    sub = parser.add_subparsers(dest="operation", required=True)

    sub.add_parser("status", help="Show integration status for all agents")
    sub.add_parser("capabilities", help="Show capability tiers for all agents")

    for op in ("install", "verify", "repair", "uninstall"):
        p = sub.add_parser(op, help=f"{op.capitalize()} integration for an agent")
        p.add_argument("--agent", choices=KNOWN_AGENTS + ["all"], required=True)

    pm = sub.add_parser("print-manual", help="Print manual closeout instructions for an agent")
    pm.add_argument("--agent", choices=KNOWN_AGENTS, required=True)

    args = parser.parse_args()
    project_root = Path(args.project_root).resolve()
    framework_root = _resolve_framework_root()

    if args.operation == "status":
        results = op_status(project_root, framework_root)
        if args.format == "json":
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(_fmt_status_human(results))
        return 0

    if args.operation == "capabilities":
        caps = op_capabilities()
        if args.format == "json":
            print(json.dumps(caps, ensure_ascii=False, indent=2))
        else:
            print(_fmt_capabilities_human(caps))
        return 0

    if args.operation == "print-manual":
        adapter = get_adapter(args.agent)
        if not adapter:
            print(f"Unknown agent: {args.agent}", file=sys.stderr)
            return 1
        print(adapter.print_manual(framework_root))
        return 0

    # install / verify / repair / uninstall
    agents = KNOWN_AGENTS if args.agent == "all" else [args.agent]
    results = []
    for agent_id in agents:
        adapter = get_adapter(agent_id)
        if not adapter:
            results.append({"agent": agent_id, "status": "unknown_agent"})
            continue
        if args.operation == "install":
            r = adapter.install(project_root, framework_root)
            results.append({"agent": agent_id, **r})
        elif args.operation == "verify":
            r = adapter.verify(project_root, framework_root)
            results.append({"agent": agent_id, **r})
        elif args.operation == "repair":
            results.append(adapter.repair(project_root, framework_root))
        elif args.operation == "uninstall":
            results.append(adapter.uninstall(project_root))

    if args.format == "json":
        out = results[0] if len(results) == 1 else results
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(_fmt_op_human(r, args.operation))

    if args.operation == "verify":
        all_ok = all(r.get("installed") or r.get("manual_only") for r in results)
        return 0 if all_ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
