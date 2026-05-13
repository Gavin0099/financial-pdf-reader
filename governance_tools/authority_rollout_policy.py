#!/usr/bin/env python3
"""
Single rollout policy source for authority strict-mode enforcement (E1C).

Goals:
- Keep default compatibility mode (no breaking adoption by default).
- Allow explicit caller override to take precedence over policy config.
- Make policy resolution auditable for reviewer surfaces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_POLICY_MODE = "compatibility"
STRICT_POLICY_MODE = "strict_register_required"


@dataclass(frozen=True)
class AuthorityRolloutPolicy:
    require_register: bool
    require_log: bool
    policy_source: str
    policy_mode: str
    explicit_override: bool


def default_policy_file(project_root: Path) -> Path:
    return project_root / "artifacts" / "governance" / "authority-rollout-policy.json"


def _mode_to_require_register(mode: str) -> bool:
    if mode == STRICT_POLICY_MODE:
        return True
    if mode == DEFAULT_POLICY_MODE:
        return False
    return False


def _resolve_config_mode(policy_file: Path) -> tuple[str, str]:
    if not policy_file.is_file():
        return DEFAULT_POLICY_MODE, "default_compatibility"
    try:
        payload = json.loads(policy_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_POLICY_MODE, "policy_file_unreadable_fallback_default"
    mode = payload.get("policy_mode")
    if not isinstance(mode, str):
        return DEFAULT_POLICY_MODE, "policy_file_invalid_fallback_default"
    if mode not in {DEFAULT_POLICY_MODE, STRICT_POLICY_MODE}:
        return DEFAULT_POLICY_MODE, "policy_file_unknown_mode_fallback_default"
    return mode, "policy_file"


def _read_require_log(policy_file: Path) -> bool:
    if not policy_file.is_file():
        return False
    try:
        payload = json.loads(policy_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    value = payload.get("require_log")
    return bool(value) if isinstance(value, bool) else False


def resolve_authority_rollout_policy(
    *,
    project_root: Path,
    require_register_override: bool | None = None,
    require_log_override: bool | None = None,
    policy_file: Path | None = None,
) -> AuthorityRolloutPolicy:
    """
    Resolve strict-mode rollout policy with auditable precedence.

    Precedence:
    1) explicit override from caller (highest)
    2) policy config file
    3) default compatibility (lowest)
    """
    resolved_policy_file = policy_file or default_policy_file(project_root)
    explicit_override = False

    if require_register_override is not None:
        mode = STRICT_POLICY_MODE if require_register_override else DEFAULT_POLICY_MODE
        require_register = bool(require_register_override)
        policy_source = "explicit_override"
        explicit_override = True
    else:
        mode, policy_source = _resolve_config_mode(resolved_policy_file)
        require_register = _mode_to_require_register(mode)

    if require_log_override is not None:
        require_log = bool(require_log_override)
        explicit_override = True
    else:
        require_log = _read_require_log(resolved_policy_file)

    return AuthorityRolloutPolicy(
        require_register=require_register,
        require_log=require_log,
        policy_source=policy_source,
        policy_mode=mode,
        explicit_override=explicit_override,
    )

