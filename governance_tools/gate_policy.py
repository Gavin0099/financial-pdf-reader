#!/usr/bin/env python3
"""
gate_policy.py — load and evaluate the test-result gate policy.

The policy authorises (or withholds authorisation for) session closeout
based on the failure_disposition in the test-result artifact.

Policy discovery order (E5 — repo-local authority):
  1. <project_root>/governance/gate_policy.yaml      policy_source = repo_local
  2. <framework_root>/governance/gate_policy.yaml    policy_source = framework_default
  3. Built-in hardcoded defaults                     policy_source = builtin_default

The authority source is always visible to reviewers through provenance fields.
If a consuming repo has not placed its own gate_policy.yaml, a
``repo_local_policy_missing`` warning is emitted so adoption gaps are
explicit — not silently absorbed by a framework default.

Three concerns are handled here and nowhere else:

  1. Artifact state classification
       absent    — file does not exist
       malformed — file exists but is not valid JSON or missing expected keys
       stale     — file exists and is valid but its mtime exceeds the
                   artifact_stale_seconds threshold in the policy
       ok        — file is valid and fresh

  2. Gate evaluation
       Given a failure_disposition dict and the loaded policy, decide whether
       to block and produce a list of gate errors / warnings.

  3. Fail-mode enforcement
       strict     — absent/malformed are gate errors; stale is a warning
       permissive — all anomalous states are silently skipped
       audit      — anomalous states become warnings, gate is never triggered
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

# ── Constants ─────────────────────────────────────────────────────────────────

FAIL_MODE_STRICT = "strict"
FAIL_MODE_PERMISSIVE = "permissive"
FAIL_MODE_AUDIT = "audit"

ARTIFACT_STATE_ABSENT = "absent"
ARTIFACT_STATE_MALFORMED = "malformed"
ARTIFACT_STATE_STALE = "stale"
ARTIFACT_STATE_OK = "ok"

POLICY_SOURCE_REPO_LOCAL = "repo_local"
POLICY_SOURCE_FRAMEWORK_DEFAULT = "framework_default"
POLICY_SOURCE_BUILTIN_DEFAULT = "builtin_default"

# Framework-level default policy file (shipped with the framework).
_FRAMEWORK_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "governance" / "gate_policy.yaml"
)

# Relative path within a project_root where the repo-local policy lives.
_REPO_POLICY_RELPATH = Path("governance") / "gate_policy.yaml"

# Legacy alias kept so existing call-sites that pass an explicit path still work.
_DEFAULT_POLICY_PATH = _FRAMEWORK_POLICY_PATH

_DEFAULTS: dict[str, Any] = {
    "version": "1",
    "fail_mode": FAIL_MODE_STRICT,
    "blocking_actions": ["production_fix_required"],
    "unknown_treatment": {"mode": "block_if_count_exceeds", "threshold": 3},
    "artifact_stale_seconds": 86400,
    "canonical_audit_trend": {"window_size": 20, "signal_threshold_ratio": 0.5},
}


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class GatePolicy:
    fail_mode: str
    blocking_actions: list[str]
    unknown_treatment_mode: str
    unknown_treatment_threshold: int
    artifact_stale_seconds: int
    # canonical_audit_trend — configurable sliding-window advisory trend.
    # These values are consumed by _compute_canonical_audit_trend() in
    # session_end_hook.py.  They never affect gate.blocked.
    canonical_audit_trend_window_size: int = 20
    canonical_audit_trend_signal_threshold_ratio: float = 0.5
    # skip_test_result_check — structural absence declaration.
    # Set True for repos that cannot produce a test-result artifact by design
    # (e.g. C++ projects, documentation repos).  Suppresses
    # test_result_artifact_absent from canonical_path_audit signals.
    # Does NOT affect gate.blocked.  Does NOT suppress canonical_interpretation_missing.
    skip_test_result_check: bool = False
    # skip_type — classification for skip_test_result_check=True repos.
    # structural : repo cannot produce a test artifact by design (non-Python stack,
    #              doc-only repo, firmware tool with no Python test runner)
    # temporary  : artifact lifecycle is theoretically possible but not yet wired
    #              (e.g. Python repo without pytest runner, CI-gated test suite)
    # None (absent): unclassified; treated as temporary in fleet analysis.
    # Only meaningful when skip_test_result_check=True.
    skip_type: str | None = None
    # hook_coverage_tier — declares the session_end_hook triggering mechanism.
    # A: native auto-closeout (Claude Code Stop hook)
    # B: wrapper-based (Copilot VS Code task, Gemini CLI wrapper)
    # C: manual only
    # None (absent): treated conservatively as Tier A by closeout enforcement.
    # Invalid value: raises ValueError at load time (config error, not silent fallback).
    hook_coverage_tier: str | None = None
    # Provenance — always set by load_policy(); never set manually.
    # policy_source   : who owns this policy decision
    # policy_path     : actual filesystem path used (empty string = builtin)
    # fallback_used   : True when project_root policy was absent and we fell back
    # repo_policy_present : True when project_root/governance/gate_policy.yaml exists
    source: str = "defaults"                       # legacy; kept for compat
    policy_source: str = POLICY_SOURCE_BUILTIN_DEFAULT
    policy_path: str = ""
    fallback_used: bool = False
    repo_policy_present: bool = False
    # Set when the YAML file existed but failed to parse; None otherwise.
    # Distinguishes parse-error fallback from normal builtin/framework fallback.
    policy_load_error: str | None = None

    def to_provenance_dict(self) -> dict:
        """Serialisable snapshot for embedding in session artifacts."""
        d: dict = {
            "policy_source": self.policy_source,
            "policy_path": self.policy_path,
            "fallback_used": self.fallback_used,
            "repo_policy_present": self.repo_policy_present,
            "skip_type": self.skip_type,
        }
        if self.policy_load_error is not None:
            d["policy_load_error"] = self.policy_load_error
        return d


@dataclass
class ArtifactResult:
    """Result of reading and classifying the test-result artifact."""
    state: str                              # absent | malformed | stale | ok
    failure_disposition: dict | None = None
    stale_seconds: float | None = None     # age when state=stale
    load_error: str | None = None          # message when state=malformed    # True when the artifact JSON contains a "failure_disposition" key,
    # regardless of whether its value is null.  False when the artifact is
    # absent, malformed, or was produced by a tool that omitted the key.
    #
    # Canonical ingestor (test_result_ingestor._base_result) always emits
    # this key (value may be null when there are no failing tests).  A
    # non-canonical artifact — or one produced by an older tool version —
    # will have failure_disposition_key_present=False.
    failure_disposition_key_present: bool = False

@dataclass
class GateDecision:
    """
    The final gate verdict produced by evaluate_gate().

    blocked     — True if the gate decided to block session closeout
    errors      — messages that must surface as result["errors"]
    warnings    — messages that must surface as result["warnings"]
    artifact_state — the classified state of the artifact
    """
    blocked: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifact_state: str = ARTIFACT_STATE_ABSENT


# ── Policy loading ────────────────────────────────────────────────────────────

def load_policy(
    project_root: Path | None = None,
    *,
    path: Path | None = None,  # explicit override; bypasses discovery
) -> GatePolicy:
    """
    Discover and load the gate policy with explicit precedence:

      1. ``path`` (explicit override, for tests / CLI)
      2. ``project_root / governance / gate_policy.yaml``  → policy_source=repo_local
      3. framework ``governance/gate_policy.yaml``         → policy_source=framework_default
      4. Built-in hardcoded _DEFAULTS                      → policy_source=builtin_default

    ``fallback_used`` is True when a consuming repo has no local policy and
    execution fell back to (3) or (4).

    ``repo_policy_present`` records whether the repo-local file exists,
    regardless of whether it was loaded (useful for adoption gap detection).
    """
    # ── Explicit override (tests, CLI) — no fallback, no provenance ──────────
    if path is not None:
        return _load_from_path(path, policy_source=POLICY_SOURCE_REPO_LOCAL,
                               fallback_used=False, repo_policy_present=True)

    # ── Discovery: check repo-local first ────────────────────────────────────
    repo_local_path: Path | None = None
    repo_policy_present = False
    if project_root is not None:
        candidate = project_root / _REPO_POLICY_RELPATH
        repo_policy_present = candidate.exists()
        if repo_policy_present:
            repo_local_path = candidate

    if repo_local_path is not None:
        return _load_from_path(
            repo_local_path,
            policy_source=POLICY_SOURCE_REPO_LOCAL,
            fallback_used=False,
            repo_policy_present=True,
        )

    # ── Fallback 1: framework default ────────────────────────────────────────
    if _FRAMEWORK_POLICY_PATH.exists():
        policy = _load_from_path(
            _FRAMEWORK_POLICY_PATH,
            policy_source=POLICY_SOURCE_FRAMEWORK_DEFAULT,
            fallback_used=(project_root is not None),  # only a fallback if discovery was tried
            repo_policy_present=repo_policy_present,
        )
        return policy

    # ── Fallback 2: builtin defaults — hardcoded minimum ────────────────────
    raw = dict(_DEFAULTS)
    return _build_policy(
        raw,
        source="builtin_defaults",
        policy_source=POLICY_SOURCE_BUILTIN_DEFAULT,
        policy_path="",
        fallback_used=True,
        repo_policy_present=repo_policy_present,
    )


def _load_from_path(
    target: Path,
    *,
    policy_source: str,
    fallback_used: bool,
    repo_policy_present: bool,
) -> GatePolicy:
    """Internal: load a specific path and return a GatePolicy with provenance."""
    raw: dict[str, Any] = dict(_DEFAULTS)
    if not _HAS_YAML:
        # F2: configuration integrity guard (repo-local policy only).
        #
        # A repo-local gate_policy.yaml represents an explicit user decision:
        # "this repo's policy is defined here".  If PyYAML is unavailable we
        # cannot honour that decision, and silently substituting builtin defaults
        # would be a policy source substitution — the system would behave as if
        # no external policy existed, with no visible signal.
        #
        # Guard applies ONLY to repo_local (user-declared file).  When loading
        # the framework-shipped default, falling back to builtin default is
        # acceptable because neither file represents a consuming-repo decision.
        if policy_source == POLICY_SOURCE_REPO_LOCAL:
            raise RuntimeError(
                f"gate_policy.yaml is present at {target} "
                f"but PyYAML is not installed; "
                f"cannot load external policy file — "
                f"refusing silent fallback to builtin default. "
                f"Fix: pip install pyyaml  (or: pip install -r requirements.txt)"
            )
        # Framework default or explicit-override path with no pyyaml:
        # fall back to builtin so the system can still operate.
        return _build_policy(
            raw,
            source=f"builtin_defaults (yaml unavailable, checked {target})",
            policy_source=POLICY_SOURCE_BUILTIN_DEFAULT,
            policy_path=str(target),
            fallback_used=True,
            repo_policy_present=repo_policy_present,
        )
    try:
        loaded = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        raw.update({k: v for k, v in loaded.items() if v is not None})
    except Exception as exc:
        return _build_policy(
            dict(_DEFAULTS),
            source=f"builtin_defaults (load error: {exc}; path={target})",
            policy_source=POLICY_SOURCE_BUILTIN_DEFAULT,
            policy_path=str(target),
            fallback_used=True,
            repo_policy_present=repo_policy_present,
            policy_load_error=str(exc),
        )
    # _build_policy() runs OUTSIDE the yaml try/except so that ValueError from
    # invalid config values (e.g. bad hook_coverage_tier) propagates to the
    # caller rather than being silently absorbed into a builtin fallback.
    return _build_policy(
        raw,
        source=str(target),
        policy_source=policy_source,
        policy_path=str(target),
        fallback_used=fallback_used,
        repo_policy_present=repo_policy_present,
    )


def _build_policy(
    raw: dict[str, Any],
    source: str,
    policy_source: str = POLICY_SOURCE_BUILTIN_DEFAULT,
    policy_path: str = "",
    fallback_used: bool = False,
    repo_policy_present: bool = False,
    policy_load_error: str | None = None,
) -> GatePolicy:
    ut = raw.get("unknown_treatment") or {}
    if isinstance(ut, str):
        # allow shorthand: unknown_treatment: never_block
        ut = {"mode": ut, "threshold": 0}
    cat = raw.get("canonical_audit_trend") or {}
    # hook_coverage_tier: validate before constructing policy so an invalid value
    # is a hard config error — not a silent fallback to defaults.
    tier_raw = raw.get("hook_coverage_tier", None)
    if tier_raw is not None:
        tier_str = str(tier_raw).strip()
        if tier_str not in ("A", "B", "C"):
            raise ValueError(
                f"gate_policy: invalid hook_coverage_tier {tier_raw!r} — "
                "must be one of: A, B, C"
            )
    else:
        tier_str = None
    # skip_type: validate when present
    skip_type_raw = raw.get("skip_type", None)
    if skip_type_raw is not None:
        skip_type_str = str(skip_type_raw).strip()
        if skip_type_str not in ("structural", "temporary"):
            raise ValueError(
                f"gate_policy: invalid skip_type {skip_type_raw!r} — "
                "must be one of: structural, temporary"
            )
    else:
        skip_type_str = None
    return GatePolicy(
        fail_mode=str(raw.get("fail_mode", FAIL_MODE_STRICT)),
        blocking_actions=list(raw.get("blocking_actions", ["production_fix_required"])),
        unknown_treatment_mode=str(ut.get("mode", "block_if_count_exceeds")),
        unknown_treatment_threshold=int(ut.get("threshold", 3)),
        artifact_stale_seconds=int(raw.get("artifact_stale_seconds", 86400)),
        canonical_audit_trend_window_size=int(cat.get("window_size", 20)),
        canonical_audit_trend_signal_threshold_ratio=float(
            cat.get("signal_threshold_ratio", 0.5)
        ),
        skip_test_result_check=bool(raw.get("skip_test_result_check", False)),
        hook_coverage_tier=tier_str,
        skip_type=skip_type_str,
        source=source,
        policy_source=policy_source,
        policy_path=policy_path,
        fallback_used=fallback_used,
        repo_policy_present=repo_policy_present,
        policy_load_error=policy_load_error,
    )


# ── Artifact state classification ─────────────────────────────────────────────

def classify_artifact(
    artifact_path: Path,
    policy: GatePolicy,
) -> ArtifactResult:
    """
    Classify the test-result artifact into one of four states.

    absent    — path does not exist
    malformed — path exists but JSON is invalid or failure_disposition key absent
    stale     — JSON is valid but file is older than policy.artifact_stale_seconds
    ok        — valid and fresh
    """
    if not artifact_path.exists():
        return ArtifactResult(state=ARTIFACT_STATE_ABSENT)

    # Load JSON
    try:
        text = artifact_path.read_text(encoding="utf-8")
        data = json.loads(text)
    except Exception as exc:
        return ArtifactResult(state=ARTIFACT_STATE_MALFORMED, load_error=str(exc))

    if not isinstance(data, dict):
        return ArtifactResult(
            state=ARTIFACT_STATE_MALFORMED,
            load_error="artifact root is not a JSON object",
        )

    # Stale check (only when stale detection is enabled)
    if policy.artifact_stale_seconds > 0:
        try:
            age = time.time() - artifact_path.stat().st_mtime
            if age > policy.artifact_stale_seconds:
                # Still load disposition so stale-but-valid artifacts can
                # contribute classification data for audit mode.
                return ArtifactResult(
                    state=ARTIFACT_STATE_STALE,
                    failure_disposition=data.get("failure_disposition"),
                    failure_disposition_key_present="failure_disposition" in data,
                    stale_seconds=age,
                )
        except OSError:
            pass  # stat failed — treat as ok, ignore stale check

    return ArtifactResult(
        state=ARTIFACT_STATE_OK,
        failure_disposition=data.get("failure_disposition"),
        failure_disposition_key_present="failure_disposition" in data,
    )


# ── Gate evaluation ───────────────────────────────────────────────────────────

def evaluate_gate(
    artifact_result: ArtifactResult,
    policy: GatePolicy,
) -> GateDecision:
    """
    Apply the gate policy to an ArtifactResult and return a GateDecision.

    fail_mode determines how non-ok artifact states are handled.
    The gate is only ever triggered (blocked=True) in strict or permissive
    modes with a valid disposition — audit mode never blocks.
    """
    state = artifact_result.state

    # ── Audit mode: never block, only record ──────────────────────────────────
    if policy.fail_mode == FAIL_MODE_AUDIT:
        warnings: list[str] = []
        if state == ARTIFACT_STATE_ABSENT:
            warnings.append(
                "[gate_policy:audit] test-result artifact absent — gate skipped"
            )
        elif state == ARTIFACT_STATE_MALFORMED:
            warnings.append(
                f"[gate_policy:audit] test-result artifact malformed "
                f"({artifact_result.load_error}) — gate skipped"
            )
        elif state == ARTIFACT_STATE_STALE:
            warnings.append(
                f"[gate_policy:audit] test-result artifact stale "
                f"({artifact_result.stale_seconds:.0f}s old) — gate skipped"
            )
        # Even in audit mode, surface disposition advisory warnings
        if artifact_result.failure_disposition:
            _add_advisory_warnings(artifact_result.failure_disposition, policy, warnings)
        return GateDecision(blocked=False, warnings=warnings, artifact_state=state)

    # ── Strict: absent and malformed are errors ───────────────────────────────
    if policy.fail_mode == FAIL_MODE_STRICT:
        if state == ARTIFACT_STATE_ABSENT:
            return GateDecision(
                blocked=True,
                errors=[
                    "[gate_policy:strict] test-result artifact absent — "
                    "run test_result_ingestor --out artifacts/runtime/test-results/latest.json "
                    "before session closeout"
                ],
                artifact_state=state,
            )
        if state == ARTIFACT_STATE_MALFORMED:
            return GateDecision(
                blocked=True,
                errors=[
                    f"[gate_policy:strict] test-result artifact malformed "
                    f"({artifact_result.load_error}) — cannot evaluate gate"
                ],
                artifact_state=state,
            )
        if state == ARTIFACT_STATE_STALE:
            # Stale in strict: warn but still evaluate the gate
            stale_warning = (
                f"[gate_policy:strict] test-result artifact is stale "
                f"({artifact_result.stale_seconds:.0f}s > "
                f"{policy.artifact_stale_seconds}s threshold) — "
                f"gate applied using stale data"
            )
            decision = _evaluate_disposition(artifact_result.failure_disposition, policy, state)
            decision.warnings.insert(0, stale_warning)
            return decision

    # ── Permissive: absent / malformed / stale all skip silently ─────────────
    if policy.fail_mode == FAIL_MODE_PERMISSIVE:
        if state in (ARTIFACT_STATE_ABSENT, ARTIFACT_STATE_MALFORMED, ARTIFACT_STATE_STALE):
            return GateDecision(blocked=False, artifact_state=state)

    # ── ok (or permissive with ok): evaluate disposition ─────────────────────
    return _evaluate_disposition(artifact_result.failure_disposition, policy, state)


def _evaluate_disposition(
    disp: dict | None,
    policy: GatePolicy,
    artifact_state: str,
) -> GateDecision:
    """
    Given a (possibly None) failure_disposition dict and the policy, produce
    a GateDecision based on blocking_actions and unknown_treatment.
    """
    if not disp:
        # No disposition = no failures, or ingestor returned None.
        return GateDecision(blocked=False, artifact_state=artifact_state)

    errors: list[str] = []
    warnings: list[str] = []
    blocked = False

    by_action = disp.get("by_action") or {}

    # Blocking actions
    for action in policy.blocking_actions:
        count = by_action.get(action, 0)
        if count > 0:
            blocked = True
            errors.append(
                f"[GATE:{action}] {count} test failure(s) classified as "
                f"{action} — production code must be fixed before session can close"
            )

    # Unknown treatment
    unknown_count = disp.get("unknown_count", 0)
    mode = policy.unknown_treatment_mode
    threshold = policy.unknown_treatment_threshold

    if mode == "always_block" and unknown_count > 0:
        blocked = True
        errors.append(
            f"[GATE:unknown] {unknown_count} unclassified failure(s) — "
            f"policy=always_block requires resolution before closeout"
        )
    elif mode == "block_if_count_exceeds" and unknown_count > threshold:
        blocked = True
        errors.append(
            f"[GATE:unknown] {unknown_count} unclassified failure(s) exceeds threshold "
            f"({threshold}) — taxonomy must be expanded before closeout"
        )
    elif unknown_count > 0:
        warnings.append(
            f"[gate_policy] {unknown_count} unclassified failure(s) — "
            f"consider expanding taxonomy (unknown_treatment={mode})"
        )

    # Advisory warnings regardless of block status
    _add_advisory_warnings(disp, policy, warnings)

    return GateDecision(blocked=blocked, errors=errors, warnings=warnings, artifact_state=artifact_state)


def _add_advisory_warnings(disp: dict, policy: GatePolicy, warnings: list[str]) -> None:
    """Append non-blocking advisory notices from disposition to warnings list."""
    if disp.get("taxonomy_expansion_signal"):
        uc = disp.get("unknown_count", 0)
        ut = disp.get("unknown_threshold", 0)
        if not any("taxonomy_expansion_signal" in w for w in warnings):
            warnings.append(
                f"[gate_policy:signal] taxonomy_expansion_signal: "
                f"{uc} unknown failures >= escalation threshold ({ut})"
            )
