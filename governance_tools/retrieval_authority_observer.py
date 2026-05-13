#!/usr/bin/env python3
"""
Advisory retrieval authority observer (v0.1).

Observation-only:
- no retrieval modifications
- no gate/block/escalation
- pattern/citation based signals only
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_CANDIDATE_CONTEXT_PATTERNS = (
    r"\bcandidate-only\b",
    r"\bcandidate context\b",
    r"\bcandidate memory suggests\b",
    r"\bcandidate memory indicates\b",
    r"\bcandidate memory shows\b",
    r"候選記憶",
)

_CANDIDATE_OVERRIDE_PATTERNS = (
    r"\boverride canonical\b",
    r"\bignore canonical\b",
    r"\bcanonical (?:is )?outdated\b",
    r"\bcandidate (?:is )?authoritative\b",
)

_TEXT_CANONICAL_PATTERNS = (r"\bcanonical memory\b", r"正式記憶")
_TEXT_CANDIDATE_PATTERNS = (r"\bcandidate memory\b", r"候選記憶")
_TEXT_SUPERSEDED_PATTERNS = (r"\bsuperseded\b", r"\bdeprecated\b", r"已過期", r"已取代")


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _any_pattern(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def _count_hits(patterns: tuple[str, ...], text: str) -> int:
    return sum(1 for p in patterns if re.search(p, text, flags=re.IGNORECASE))


def observe(payload: dict[str, Any]) -> dict[str, Any]:
    response_text = str(payload.get("response_text") or "")
    refs = payload.get("memory_refs") or []
    refs = refs if isinstance(refs, list) else []

    used_canonical_from_refs = any(
        (str(r.get("source_type", "")).lower() == "canonical")
        and (str(r.get("validity_state", "active")).lower() == "active")
        for r in refs
        if isinstance(r, dict)
    )
    used_candidate_from_refs = any(
        str(r.get("source_type", "")).lower() == "candidate"
        for r in refs
        if isinstance(r, dict)
    )
    used_superseded_from_refs = any(
        str(r.get("validity_state", "")).lower() in {"superseded", "deprecated"}
        for r in refs
        if isinstance(r, dict)
    )

    used_canonical_from_text = _any_pattern(_TEXT_CANONICAL_PATTERNS, response_text)
    used_candidate_from_text = _any_pattern(_TEXT_CANDIDATE_PATTERNS, response_text)
    used_superseded_from_text = _any_pattern(_TEXT_SUPERSEDED_PATTERNS, response_text)

    used_canonical = used_canonical_from_refs or used_canonical_from_text
    used_candidate = used_candidate_from_refs or used_candidate_from_text
    used_superseded = used_superseded_from_refs or used_superseded_from_text

    explicit_candidate_context = _any_pattern(_CANDIDATE_CONTEXT_PATTERNS, response_text)
    candidate_override_signal = _any_pattern(_CANDIDATE_OVERRIDE_PATTERNS, response_text)

    authority_conflict = bool(
        used_candidate and used_canonical and candidate_override_signal and not explicit_candidate_context
    )

    if refs:
        authority_evidence_level = "explicit"
    elif used_canonical or used_candidate or used_superseded:
        authority_evidence_level = "weak"
    else:
        authority_evidence_level = "none"

    needs_human_review = bool(used_superseded or authority_conflict)

    pattern_hits = {
        "candidate_context_hits": _count_hits(_CANDIDATE_CONTEXT_PATTERNS, response_text),
        "candidate_override_hits": _count_hits(_CANDIDATE_OVERRIDE_PATTERNS, response_text),
        "canonical_text_hits": _count_hits(_TEXT_CANONICAL_PATTERNS, response_text),
        "candidate_text_hits": _count_hits(_TEXT_CANDIDATE_PATTERNS, response_text),
        "superseded_text_hits": _count_hits(_TEXT_SUPERSEDED_PATTERNS, response_text),
    }

    return {
        "schema_version": "0.1",
        "session_id": str(payload.get("session_id") or ""),
        "generated_at_utc": _now_utc(),
        "advisory_only": True,
        "observation": {
            "used_canonical": used_canonical,
            "used_candidate": used_candidate,
            "used_superseded": used_superseded,
            "explicit_candidate_context": explicit_candidate_context,
            "authority_conflict": authority_conflict,
            "authority_evidence_level": authority_evidence_level,
            "needs_human_review": needs_human_review,
            "missed_active_memory": "unknown",
        },
        "evidence": {
            "memory_refs_count": len(refs),
            "pattern_hits": pattern_hits,
        },
        "notes": "observation-only v0.1; pattern/citation based; no semantic correctness claim",
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Generate retrieval authority advisory (v0.1).")
    parser.add_argument("--input", required=True, help="Path to JSON payload containing response_text and optional memory_refs.")
    parser.add_argument("--output", required=True, help="Path to write advisory JSON.")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    advisory = observe(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(advisory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
