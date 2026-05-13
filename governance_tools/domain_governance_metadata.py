#!/usr/bin/env python3
"""
Shared governance metadata for external domain contracts.
"""

from __future__ import annotations


DOMAIN_PRIORITY_RANK = {
    "kernel-driver": 0,
    "firmware": 1,
    "gl-hub-vendor-cmd": 1,
    "ic-verification": 2,
}

DOMAIN_RISK_TIER = {
    "kernel-driver": "high",
    "firmware": "medium",
    "gl-hub-vendor-cmd": "high",
    "ic-verification": "medium",
}


def normalize_domain_name(value: str | None) -> str:
    return str(value or "").strip().lower()


def domain_priority_rank(domain: str | None) -> int:
    normalized = normalize_domain_name(domain)
    if not normalized:
        return 99
    for known_domain, rank in DOMAIN_PRIORITY_RANK.items():
        if known_domain in normalized:
            return rank
    return DOMAIN_PRIORITY_RANK.get(normalized, 50)


def domain_risk_tier(domain: str | None) -> str:
    normalized = normalize_domain_name(domain)
    if not normalized:
        return "unknown"
    for known_domain, tier in DOMAIN_RISK_TIER.items():
        if known_domain in normalized:
            return tier
    if "firmware" in normalized:
        return "medium"
    return DOMAIN_RISK_TIER.get(normalized, "unknown")
