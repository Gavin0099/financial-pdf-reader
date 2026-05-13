"""
governance_tools/e1b_consumer_audit.py
=======================================
E1b Consumer Audit — Text Scanner.

Scans consumer text (summaries, reports, comments, scripts) for violations
of the semantic limits defined in docs/e1b-classification-semantic-limits.md
and docs/e1b-consumer-audit-checklist.md.

Four forbidden patterns:
  P1  transitioning_active implied as improvement / positive trend
  P2  lifecycle classification count used in numeric risk/score formula
  P3  temporal accumulation implied to improve model classification accuracy
  P4  READY gate verdict equated with classifier validated / safe to promote

Usage
-----
    from governance_tools.e1b_consumer_audit import scan_consumer_text

    violations = scan_consumer_text(text)
    if violations:
        for v in violations:
            print(f"[{v['pattern_id']}] {v['description']}")
            print(f"  matched: {v['excerpt']}")
    else:
        print("no violations found")

Design notes
------------
- scan_consumer_text() is purely detection — it cannot block at runtime.
  It surfaces violations so a human or CI check can act on them.
- False negatives (missed violations) are acceptable; false positives
  (flagging legitimate text) degrade trust and must be minimized.
- Patterns are narrow-band: they require the forbidden combination, not
  individual words in isolation.
- Reference: docs/e1b-consumer-audit-checklist.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


# ── Pattern registry ──────────────────────────────────────────────────────────
# Each entry maps to one of the 4 forbidden patterns in the checklist.
# "regexes": list of patterns (any match → violation).
# All patterns are case-insensitive.

_PATTERNS: list[dict[str, Any]] = [
    {
        "pattern_id": "P1",
        "description": (
            "transitioning_active used to imply improvement, progress, or positive trend "
            "(forbidden — the label is semantically neutral, not directional)"
        ),
        "regexes": [
            # "transitioning[...] improv / positive trend / on track / progressing"
            r"(?i)transitioning.{0,80}"
            r"(improv|positive.{0,5}trend|on.{0,3}track|progressing|getting\s+better)",
            # reverse order
            r"(?i)(improv|positive.{0,5}trend|on.{0,3}track|progressing|getting\s+better)"
            r".{0,80}transitioning",
        ],
    },
    {
        "pattern_id": "P2",
        "description": (
            "lifecycle classification count used in numeric risk/score formula "
            "(forbidden — neutral label must not become a risk weight)"
        ),
        "regexes": [
            # transitioning_count ± operator
            r"(?i)transitioning.{0,8}count.{0,40}[\+\-\*\/]",
            # operator ± transitioning_count
            r"(?i)[\+\-\*\/].{0,40}transitioning.{0,8}count",
            # risk_score / risk score + transitioning anywhere nearby
            r"(?i)risk.{0,10}score.{0,60}transitioning",
            r"(?i)transitioning.{0,60}risk.{0,10}score",
        ],
    },
    {
        "pattern_id": "P3",
        "description": (
            "temporal accumulation implied to improve classification accuracy or reliability "
            "(forbidden — time raises reviewer confidence, not model precision)"
        ),
        "regexes": [
            # observed / multiple days / longer → more reliable / more accurate
            r"(?i)(observed?\b|observation|multiple\s+days?|multiple\s+sessions?|longer\s+observ)"
            r".{0,80}(more\s+reliable|more\s+accurate|higher\s+precision|more\s+confident)",
            # reverse
            r"(?i)(more\s+reliable|more\s+accurate|higher\s+precision|more\s+confident)"
            r".{0,80}(observed?\b|observation|multiple\s+days?|multiple\s+sessions?|longer\s+observ)",
            # "classification is more reliable" (with or without temporal context)
            r"(?i)classif\w{0,20}\s+is\s+more\s+reliable",
        ],
    },
    {
        "pattern_id": "P4",
        "description": (
            "READY gate verdict equated with classifier validated, classification proven, "
            "or safe to promote "
            "(forbidden — READY is a policy proxy, not a classification proof)"
        ),
        "regexes": [
            # "likely ready for promotion/promote"
            r"(?i)likely\s+ready\s+for\s+promot",
            # gate passed/ready → promote
            r"(?i)(gate|verdict).{0,30}(passed|ready).{0,80}promot",
            # READY + classifier reliable / classification validated / can promote
            r"(?i)\bREADY\b.{0,80}"
            r"(classifier.{0,10}reliable|classification.{0,10}valid|safe.{0,5}promot|can\s+promot)",
        ],
    },
]

# Reviewer-summary forbidden taxonomy (Phase 3.3 socio-semantic boundary).
_REVIEWER_PATTERNS: list[dict[str, Any]] = [
    {
        "pattern_id": "R1",
        "category": "readiness_claim",
        "description": (
            "reviewer summary declares readiness from observation-only artifacts"
        ),
        "regexes": [
            r"(?i)\breadiness\b.{0,20}(is|has|already)?\s*(met|established|confirmed|stands|成立)",
            r"(?i)(足以|可).{0,12}(支持|support).{0,12}(升格|promot|readiness)",
        ],
    },
    {
        "pattern_id": "R2",
        "category": "promotion_claim",
        "description": (
            "reviewer summary recommends or implies promotion from observation-only signals"
        ),
        "regexes": [
            r"(?i)(ready|safe|enough).{0,20}(for\s+)?promot",
            r"(?i)support\s+promot",
            r"(?i)(足以|可).{0,20}(support|支持).{0,20}promot",
            r"(?i)(可|應該|值得).{0,12}(升格|promot)",
        ],
    },
    {
        "pattern_id": "R3",
        "category": "stability_claim",
        "description": (
            "reviewer summary declares stability conclusion from observation-only data"
        ),
        "regexes": [
            r"(?i)(已經|already|can\s+be|可視為).{0,20}(stable|stability|穩定)",
            r"(?i)(整體|overall).{0,20}(穩定|stable|健康|healthy)",
        ],
    },
    {
        "pattern_id": "R4",
        "category": "quality_verdict",
        "description": (
            "reviewer summary gives evaluative quality verdict from observation-only data"
        ),
        "regexes": [
            r"(?i)(趨勢|trend).{0,20}(正向|positive|good)",
            r"(?i)(狀態|state).{0,20}(令人安心|reassuring|looks\s+good)",
        ],
    },
    {
        "pattern_id": "R5",
        "category": "directional_interpretation",
        "description": (
            "reviewer summary implies directional interpretation without phase transition"
        ),
        "regexes": [
            r"(?i)(朝|toward).{0,20}(interpretation|判讀|升格)",
            r"(?i)(具備|has).{0,20}(判讀|interpretation).{0,20}(基礎|basis)",
        ],
    },
    {
        "pattern_id": "R6",
        "category": "confidence_laundering",
        "description": (
            "reviewer summary launders a forbidden conclusion via hedging language"
        ),
        "regexes": [
            r"(?i)(雖然|although|while).{0,80}(不能|not).{0,40}(結論|conclude).{0,80}(可視為|basically|大致上).{0,40}(穩定|stable|readiness|ready)",
            r"(?i)(不構成|does\s+not\s+constitute).{0,50}(promot|升格).{0,80}(但|but).{0,40}(健康|healthy|ready|stability|穩定)",
        ],
    },
]


# ── Public API ─────────────────────────────────────────────────────────────────

def scan_consumer_text(text: str) -> list[dict[str, str]]:
    """
    Scan text for E1b consumer anti-patterns.

    Parameters
    ----------
    text : str
        Any text artifact — summary, report, code comment, narrative.

    Returns
    -------
    list[dict]
        Each dict has:
          pattern_id  : "P1" | "P2" | "P3" | "P4"
          description : human-readable rule that was violated
          excerpt     : the matched text (truncated to 120 chars)

        Returns an empty list when no violations are found.

    Design boundary
    ---------------
    Detection scope: the four forbidden patterns from the checklist.
    False negatives (missed violations) are acceptable.
    False positives must be minimized — patterns require the forbidden
    combination, not individual words in isolation.
    """
    violations: list[dict[str, str]] = []
    for entry in _PATTERNS:
        for regex in entry["regexes"]:
            for match in re.finditer(regex, text):
                violations.append({
                    "pattern_id": entry["pattern_id"],
                    "description": entry["description"],
                    "excerpt": match.group(0)[:120],
                })
    return violations


def violation_pattern_ids(text: str) -> set[str]:
    """
    Convenience helper: return only the set of pattern IDs found in text.

    Useful for assertions: ``assert "P1" in violation_pattern_ids(text)``
    """
    return {v["pattern_id"] for v in scan_consumer_text(text)}


def scan_reviewer_summary_text(text: str) -> list[dict[str, str]]:
    """
    Scan human-authored reviewer summaries for socio-semantic backdoor claims.

    This scanner enforces the reviewer interpretation boundary introduced in
    Phase 3.3. It is intentionally conservative and focused on high-risk
    phrasing classes.
    """
    violations: list[dict[str, str]] = []
    for entry in _REVIEWER_PATTERNS:
        for regex in entry["regexes"]:
            for match in re.finditer(regex, text):
                violations.append({
                    "pattern_id": entry["pattern_id"],
                    "category": entry["category"],
                    "description": entry["description"],
                    "excerpt": match.group(0)[:120],
                })
    return violations


def lint_reviewer_summary_text(text: str) -> dict[str, Any]:
    """
    Return linter result with clean/non-clean status for reviewer summaries.
    """
    violations = scan_reviewer_summary_text(text)
    return {
        "status": "clean" if not violations else "non-clean",
        "violation_count": len(violations),
        "violations": violations,
    }


def _read_text_input(path: str | None) -> str:
    if path is None or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lint reviewer summary text against Phase 3.3 boundary."
    )
    parser.add_argument(
        "--input",
        help="Path to text/markdown file. Use '-' or omit to read stdin.",
        default="-",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit machine-readable JSON.",
    )
    args = parser.parse_args(argv)

    text = _read_text_input(args.input)
    result = lint_reviewer_summary_text(text)

    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status={result['status']}")
        print(f"violations={result['violation_count']}")
        for v in result["violations"]:
            print(
                f"[{v['pattern_id']}/{v['category']}] {v['description']} :: {v['excerpt']}"
            )

    return 0 if result["status"] == "clean" else 2


if __name__ == "__main__":
    sys.exit(main())
