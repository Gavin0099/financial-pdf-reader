#!/usr/bin/env python3
"""
Shared summary-line formatting for governance tool human output.
"""

from __future__ import annotations


def build_summary_line(*parts: str | None) -> str:
    values = [part for part in parts if part]
    return "summary=" + " | ".join(values)
