#!/usr/bin/env python3
"""Canonical legacy-only capability policy for version-compat runtime gating."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


LEGACY_CAPABILITY_POLICY_VERSION = "0.1"


@dataclass(frozen=True)
class LegacyCapabilityPolicy:
    policy_version: str
    mode: str
    allowed_features: list[str] = field(default_factory=list)
    disabled_features: list[str] = field(default_factory=list)
    artifact_write_policy: dict[str, object] = field(default_factory=dict)
    human_surface_requirements: list[str] = field(default_factory=list)
    no_reinference_rule: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_legacy_capability_policy(*, disabled_runtime_features: list[str] | None = None) -> LegacyCapabilityPolicy:
    disabled = sorted(disabled_runtime_features or [])
    return LegacyCapabilityPolicy(
        policy_version=LEGACY_CAPABILITY_POLICY_VERSION,
        mode="legacy_only",
        allowed_features=[
            "core_pre_task_check",
            "core_post_task_check",
            "basic_version_compatibility_artifact_write",
        ],
        disabled_features=disabled,
        artifact_write_policy={
            "allowed": [
                "artifacts/governance/version_compatibility.json",
            ],
            "disallowed": [
                "canonical_closeout_artifacts",
                "session_index_artifacts",
                "decision_context_bridge_artifacts",
                "feature_gated_runtime_extension_artifacts",
            ],
        },
        human_surface_requirements=[
            "status=degraded",
            "mode=legacy_only",
            "reason=version_compatibility_migration_required",
            "legacy_only_boundary=feature_gated_runtime_extensions_not_loaded",
            "version_compat_disabled=<disabled_runtime_features>",
        ],
        no_reinference_rule=(
            "legacy_only feature allow/deny decisions must come from "
            "version_compatibility.enabled_runtime_features and "
            "version_compatibility.disabled_runtime_features only; "
            "session_start and downstream consumers must not re-infer capabilities."
        ),
    )
