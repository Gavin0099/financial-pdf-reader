from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


_LAYER1_CLAIM_PATTERNS: list[dict[str, Any]] = [
    {
        "rule_id": "C1",
        "claim_type": "readiness_claim",
        "severity": "high",
        "skip_if_negated": True,
        "regexes": [
            r"(?i)\bread(y|iness)\b.{0,24}(met|established|confirmed|成立|已成)",
            r"(?i)(可|足以).{0,20}(support|支持).{0,20}(readiness|ready)",
            r"(?i)\breadiness\b.{0,24}(basis|foundation|approach|forming|基礎|成形|正在形成)",
            r"(?i)\b(status|next|overall|狀態|状态)\s*:\s*(ready(\s*for\s*review)?|ready-?ish|r4r|gtg)\b",
            r"(?i)(可往下走|可往下一步|可往下階段)",
        ],
    },
    {
        "rule_id": "C2",
        "claim_type": "promotion_claim",
        "severity": "high",
        "skip_if_negated": True,
        "regexes": [
            r"(?i)\bpromot(e|ion)\b",
            r"(?i)(可|值得|應該|足以).{0,20}(升格|promot)",
            r"(?i)\bpromo(\s*candidate|[-\s]?ish)?\b",
            r"(?i)(可升|可升格)",
            r"(?i)\bpromotion\s+context\b",
        ],
    },
    {
        "rule_id": "C3",
        "claim_type": "stability_claim",
        "severity": "high",
        "skip_if_negated": True,
        "regexes": [
            r"(?i)(可視為|can\s+be|already|已經).{0,20}(stable|stability|穩定)",
            r"(?i)(穩定性).{0,20}(結論|已成|成立)",
            r"(?i)\b(status|overall|狀態|状态)\s*:\s*(stable|stability|穩定|穩)\b",
            r"(?i)\boverall\s+stability\b",
            r"(?i)(看起來|looks|seems).{0,10}(stable|穩定)",
        ],
    },
    {
        "rule_id": "C4",
        "claim_type": "quality_verdict",
        "severity": "medium",
        "skip_if_negated": True,
        "regexes": [
            r"(?i)(整體|overall).{0,20}(healthy|健康|令人安心|reassuring|looks\s+good)",
            r"(?i)(趨勢|trend).{0,20}(正向|positive)",
            r"(?i)\b(status|overall|狀態|状态)\s*:\s*(healthy|健康|positive|正向)\b",
            r"(?i)(整體|overall).{0,10}(偏正向|正向)",
        ],
    },
    {
        "rule_id": "C5",
        "claim_type": "directional_interpretation",
        "severity": "medium",
        "skip_if_negated": True,
        "regexes": [
            r"(?i)(朝|toward|towards).{0,20}(interpretation|判讀|升格)",
            r"(?i)(進一步).{0,20}(判讀|interpretation).{0,20}(基礎|basis)",
            r"(?i)\bnext\s*:\s*(move|go|proceed).{0,24}(toward|to).{0,20}(interpretation|判讀|升格)",
        ],
    },
    {
        "rule_id": "C6",
        "claim_type": "confidence_laundering",
        "severity": "high",
        "skip_if_negated": False,
        "regexes": [
            r"(?i)(雖然|although|while).{0,80}(不能|not).{0,40}(結論|conclude).{0,80}(可視為|basically|大致上).{0,40}(穩定|stable|ready|健康)",
            r"(?i)(不構成|does\s+not\s+constitute).{0,60}(依據|basis|promot|升格).{0,80}(但|but).{0,40}(健康|stable|ready|正向)",
            r"(?i)(不構成|does\s+not\s+constitute).{0,60}(promot|升格).{0,80}(但|but).{0,40}(建議|suggest).{0,60}(升格|promot|討論|discussion)",
        ],
    },
]

_LAYER2_ARGUMENT_PATTERNS: list[dict[str, Any]] = [
    {
        "rule_id": "A1",
        "claim_type": "confidence_laundering",
        "severity": "high",
        "skip_if_negated": False,
        "regexes": [
            r"(?i)(雖然|although|while).{0,120}(但|but).{0,120}(可視為|視為|indicates|shows)",
            r"(?i)(不能|not).{0,60}(直接下結論|conclude).{0,120}(不過|however|but).{0,80}(可|still|仍可)",
        ],
    },
    {
        "rule_id": "A2",
        "claim_type": "directional_interpretation",
        "severity": "medium",
        "skip_if_negated": False,
        "regexes": [
            r"(?i)(在|under).{0,40}(不做|without).{0,40}(interpretation|判讀).{0,80}(仍可|still).{0,60}(看出|infer|imply)",
            r"(?i)(先堆|accumulat\w*).{0,120}(觀測|observation).{0,120}(因此|therefore).{0,60}(可|can).{0,40}(判讀|interpret|結論)",
        ],
    },
]

_NEGATION_TOKENS: tuple[str, ...] = (
    "不支援",
    "不作",
    "未進",
    "禁用",
    "policy only",
    "僅作政策說明",
    "not support",
    "does not support",
    "do not",
    "must not",
    "without",
)


def _is_negated_context(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - 80): min(len(text), end + 40)].lower()
    return any(tok in window for tok in _NEGATION_TOKENS)


def _collect_violations(
    text: str,
    registry: list[dict[str, Any]],
    layer: str,
) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for rule in registry:
        for regex in rule["regexes"]:
            for m in re.finditer(regex, text):
                if rule.get("skip_if_negated", False) and _is_negated_context(
                    text, m.start(), m.end()
                ):
                    continue
                violations.append(
                    {
                        "layer": layer,
                        "rule_id": rule["rule_id"],
                        "claim_type": rule["claim_type"],
                        "severity": rule["severity"],
                        "excerpt": m.group(0)[:160],
                    }
                )
    return violations


def lint_text(text: str) -> dict[str, Any]:
    violations = _collect_violations(text, _LAYER1_CLAIM_PATTERNS, "layer1_claim") + _collect_violations(
        text, _LAYER2_ARGUMENT_PATTERNS, "layer2_argument"
    )
    return {
        "status": "clean" if not violations else "non-clean",
        "violation_count": len(violations),
        "violations": violations,
    }


def _read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lint reviewer artifacts for forbidden interpretation transport.")
    p.add_argument("--input", default="-", help="input file path or '-' for stdin")
    p.add_argument("--json", action="store_true", dest="emit_json")
    args = p.parse_args(argv)

    result = lint_text(_read_input(args.input))
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status={result['status']}")
        print(f"violations={result['violation_count']}")
        for v in result["violations"]:
            print(
                f"[{v['layer']}/{v['rule_id']}/{v['claim_type']}/{v['severity']}] {v['excerpt']}"
            )
    return 0 if result["status"] == "clean" else 2


if __name__ == "__main__":
    sys.exit(main())
