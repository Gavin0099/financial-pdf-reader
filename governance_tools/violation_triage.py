#!/usr/bin/env python3
"""
Violation triage schema, CI gate evaluation, and triage workflow.

Modes:
  generate  — convert tool JSON output into a triage template
              (if --triage-file provided, merges existing human annotations)
  evaluate  — read a triage file and evaluate the CI gate result

Exit codes (evaluate mode):
  0  — all clear (or only FP violations)
  1  — TP or unreviewed CRITICAL violations (code must be fixed / triage required)
  2  — FN violations detected (framework bug — highest priority)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SCHEMA_VERSION = "1.0"

VALID_TRIAGE_TYPES = frozenset({"TP", "FP", "FN"})
VALID_ROOT_CAUSES = frozenset({"contract", "validator", "context", "flow"})
VALID_ACTIONS = frozenset({"fix_rule", "add_validator", "improve_context", "fix_flow", "ignore"})

# Only CRITICAL unreviewed violations block CI
CI_BLOCKING_SEVERITIES = frozenset({"CRITICAL"})


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class TriageEntry:
    type: Optional[str] = None          # TP | FP | FN  (None = unreviewed)
    root_cause: Optional[str] = None    # contract | validator | context | flow
    action: Optional[str] = None        # fix_rule | add_validator | improve_context | fix_flow | ignore
    notes: str = ""
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None


@dataclass
class Violation:
    id: str
    rule_id: str
    severity: str       # CRITICAL | WARNING | INFO
    category: str       # contract | doc | runtime | alignment
    message: str
    location: str = ""
    triage: TriageEntry = field(default_factory=TriageEntry)

    def fingerprint(self) -> str:
        """Stable merge key: hash of (rule_id, location) — message-independent."""
        raw = f"{self.rule_id}|{self.location}"
        return hashlib.sha256(raw.encode()).hexdigest()[:8]


@dataclass
class TriageReport:
    schema_version: str
    tool: str
    generated_at: str
    context: dict
    violations: list

    def stats(self) -> dict:
        total = len(self.violations)
        by_severity: dict[str, int] = {}
        by_type: dict[str, int] = {"TP": 0, "FP": 0, "FN": 0, "unreviewed": 0}
        for v in self.violations:
            by_severity[v.severity] = by_severity.get(v.severity, 0) + 1
            t = v.triage.type
            if t in VALID_TRIAGE_TYPES:
                by_type[t] += 1
            else:
                by_type["unreviewed"] += 1
        unreviewed_critical = sum(
            1 for v in self.violations
            if v.severity in CI_BLOCKING_SEVERITIES and v.triage.type is None
        )
        return {
            "total": total,
            "unreviewed_critical": unreviewed_critical,
            "by_severity": by_severity,
            "by_type": by_type,
        }

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "tool": self.tool,
            "generated_at": self.generated_at,
            "context": self.context,
            "violations": [
                {
                    "id": v.id,
                    "rule_id": v.rule_id,
                    "severity": v.severity,
                    "category": v.category,
                    "message": v.message,
                    "location": v.location,
                    "triage": asdict(v.triage),
                }
                for v in self.violations
            ],
            "stats": self.stats(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TriageReport":
        violations = []
        for v in data.get("violations", []):
            td = v.get("triage") or {}
            violations.append(Violation(
                id=v.get("id", ""),
                rule_id=v.get("rule_id", ""),
                severity=v.get("severity", "CRITICAL"),
                category=v.get("category", "contract"),
                message=v.get("message", ""),
                location=v.get("location", ""),
                triage=TriageEntry(
                    type=td.get("type"),
                    root_cause=td.get("root_cause"),
                    action=td.get("action"),
                    notes=td.get("notes") or "",
                    reviewed_by=td.get("reviewed_by"),
                    reviewed_at=td.get("reviewed_at"),
                ),
            ))
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            tool=data.get("tool", "unknown"),
            generated_at=data.get("generated_at", ""),
            context=data.get("context") or {},
            violations=violations,
        )


# ── Converters ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_id(prefix: str, seq: int) -> str:
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{prefix}-{date}-{seq:03d}"


def _parse_rule_id(message: str) -> str:
    """Derive a stable rule_id from an error/warning message."""
    msg_lower = message.lower()
    field_map = [
        ("lang", "LANG"),
        ("level", "LEVEL"),
        ("scope", "SCOPE"),
        ("loaded", "LOADED"),
        ("context", "CONTEXT"),
        ("pressure", "PRESSURE"),
        ("rules", "RULES"),
        ("risk", "RISK"),
        ("oversight", "OVERSIGHT"),
        ("memory_mode", "MEMORY_MODE"),
        ("agent_id", "AGENT_ID"),
        ("session", "SESSION"),
        ("plan", "PLAN"),
    ]
    for key, label in field_map:
        if key not in msg_lower:
            continue
        if "missing" in msg_lower:
            return f"{label}-missing"
        if "required" in msg_lower or "field is" in msg_lower:
            return f"{label}-required"
        if "invalid" in msg_lower:
            return f"{label}-invalid"
        if "unknown" in msg_lower:
            return f"{label}-unknown"
        return f"{label}-error"
    if "contract" in msg_lower and "not found" in msg_lower:
        return "CONTRACT-missing"
    if "governance doc" in msg_lower:
        return "GOV-doc-missing"
    if "workflow" in msg_lower:
        return "GOV-workflow-missing"
    if "runtime enforcement" in msg_lower:
        return "GOV-runtime-missing"
    if "build-boundary" in msg_lower:
        return "GOV-alignment-build-boundary"
    if "refactor" in msg_lower and "incomplete" in msg_lower:
        return "GOV-alignment-refactor-incomplete"
    if "rule pack" in msg_lower:
        return "GOV-rule-pack-missing"
    if "release" in msg_lower:
        return "GOV-release-readiness"
    if "external" in msg_lower and "onboarding" in msg_lower:
        return "GOV-external-onboarding"
    # Fallback: slugify first 4 words
    words = message.split()[:4]
    slug = "-".join(re.sub(r"[:.,'\"()]+", "", w).lower() for w in words if re.sub(r"[:.,'\"()]+", "", w))
    return slug or "unknown"


def _parse_location(message: str) -> str:
    """Extract a location hint from an error message."""
    for field_name in [
        "LANG", "LEVEL", "SCOPE", "LOADED", "CONTEXT", "PRESSURE",
        "RULES", "RISK", "OVERSIGHT", "MEMORY_MODE", "AGENT_ID", "SESSION", "PLAN",
    ]:
        if field_name in message.upper():
            return f"Governance Contract / {field_name}"
    m = re.search(r"governance/\S+", message)
    if m:
        return m.group(0)
    m = re.search(r"runtime_hooks/\S+", message)
    if m:
        return m.group(0)
    return ""


def from_contract_validator_json(data: dict, context: Optional[dict] = None) -> TriageReport:
    """Convert contract_validator --format json output into a TriageReport."""
    violations: list[Violation] = []
    seq = 1
    for err in data.get("errors", []):
        violations.append(Violation(
            id=_make_id("cv", seq),
            rule_id=_parse_rule_id(err),
            severity="CRITICAL",
            category="contract",
            message=err,
            location=_parse_location(err),
        ))
        seq += 1
    for warn in data.get("warnings", []):
        violations.append(Violation(
            id=_make_id("cv", seq),
            rule_id=_parse_rule_id(warn),
            severity="WARNING",
            category="contract",
            message=warn,
            location=_parse_location(warn),
        ))
        seq += 1
    return TriageReport(
        schema_version=SCHEMA_VERSION,
        tool="contract_validator",
        generated_at=_now_iso(),
        context=context or {"source": "contract_validator"},
        violations=violations,
    )


def from_governance_auditor_json(data: dict, context: Optional[dict] = None) -> TriageReport:
    """Convert governance_auditor --format json output into a TriageReport."""
    _cat_map = {
        "doc:": "doc",
        "docs:": "doc",
        "runtime:": "runtime",
        "workflow:": "runtime",
        "alignment:": "alignment",
        "rule-pack:": "contract",
        "release:": "doc",
        "external:": "doc",
    }
    violations: list[Violation] = []
    seq = 1
    for check in data.get("checks", []):
        if check.get("ok"):
            continue
        name = check.get("name", "unknown")
        detail = check.get("detail", "")
        category = next(
            (cat for prefix, cat in _cat_map.items() if name.startswith(prefix)),
            "doc",
        )
        violations.append(Violation(
            id=_make_id("ga", seq),
            rule_id=f"auditor:{name}",
            severity="CRITICAL",
            category=category,
            message=detail,
            location=name,
        ))
        seq += 1
    for warning in data.get("warnings", []):
        violations.append(Violation(
            id=_make_id("ga", seq),
            rule_id=_parse_rule_id(warning),
            severity="WARNING",
            category="doc",
            message=warning,
            location="",
        ))
        seq += 1
    return TriageReport(
        schema_version=SCHEMA_VERSION,
        tool="governance_auditor",
        generated_at=_now_iso(),
        context=context or {"project_root": data.get("project_root", ".")},
        violations=violations,
    )


# ── Merge ─────────────────────────────────────────────────────────────────────

def merge_triage(existing: TriageReport, new: TriageReport) -> TriageReport:
    """
    Merge human triage annotations from *existing* into *new*.

    Matches by fingerprint (stable hash of rule_id + location).
    Only carries forward entries where triage.type is non-null.
    """
    reviewed: dict[str, TriageEntry] = {
        v.fingerprint(): v.triage
        for v in existing.violations
        if v.triage.type is not None
    }
    merged: list[Violation] = []
    for v in new.violations:
        fp = v.fingerprint()
        if fp in reviewed:
            v.triage = reviewed[fp]
        merged.append(v)
    return TriageReport(
        schema_version=new.schema_version,
        tool=new.tool,
        generated_at=new.generated_at,
        context=new.context,
        violations=merged,
    )


# ── CI Gate ───────────────────────────────────────────────────────────────────

@dataclass
class CIGateResult:
    ok: bool
    exit_code: int          # 0=pass, 1=TP/unreviewed-critical, 2=FN (framework bug)
    annotations: list       # [{level, file, message}]
    summary: str


def evaluate_ci_gate(report: TriageReport) -> CIGateResult:
    """
    Evaluate the CI gate from a triage report.

    Exit codes:
      0  — all clear (no violations, or only FP)
      1  — TP or unreviewed CRITICAL (code fix or triage required)
      2  — FN violations (framework bug — highest priority)
    """
    annotations = []
    has_fn = False
    has_fail = False

    for v in report.violations:
        t = v.triage.type
        loc = v.location or v.rule_id

        if t == "FN":
            has_fn = True
            has_fail = True
            annotations.append({
                "level": "error",
                "file": loc,
                "message": (
                    f"[FN] Framework missed this — fix validator: "
                    f"{v.message} (rule: {v.rule_id})"
                ),
            })
        elif t == "TP":
            has_fail = True
            annotations.append({
                "level": "error",
                "file": loc,
                "message": f"[TP] Real violation — code must be fixed: {v.message} (rule: {v.rule_id})",
            })
        elif t is None and v.severity in CI_BLOCKING_SEVERITIES:
            has_fail = True
            annotations.append({
                "level": "error",
                "file": loc,
                "message": (
                    f"[UNREVIEWED] Triage required before merge: "
                    f"{v.message} (rule: {v.rule_id})"
                ),
            })
        elif t == "FP":
            annotations.append({
                "level": "warning",
                "file": loc,
                "message": f"[FP] Known false positive (tracked for framework improvement): {v.message}",
            })
        elif t is None and v.severity == "WARNING":
            annotations.append({
                "level": "notice",
                "file": loc,
                "message": f"[UNREVIEWED-WARN] {v.message} (rule: {v.rule_id})",
            })

    stats = report.stats()
    if has_fn:
        exit_code = 2
        fn_count = stats["by_type"]["FN"]
        summary = f"FAIL (exit 2) — {fn_count} FN: framework bugs require validator fixes"
    elif has_fail:
        exit_code = 1
        parts = []
        tp = stats["by_type"]["TP"]
        unrev = stats["unreviewed_critical"]
        if tp:
            parts.append(f"{tp} TP (code fix required)")
        if unrev:
            parts.append(f"{unrev} unreviewed critical (triage required)")
        summary = "FAIL — " + "; ".join(parts)
    else:
        exit_code = 0
        fp = stats["by_type"]["FP"]
        total = stats["total"]
        summary = f"PASS — {total} violation(s) total ({fp} FP tracked)"

    return CIGateResult(
        ok=not has_fail,
        exit_code=exit_code,
        annotations=annotations,
        summary=summary,
    )


# ── Human output ──────────────────────────────────────────────────────────────

def format_human_gate(result: CIGateResult, report: TriageReport) -> str:
    stats = report.stats()
    lines = [
        "[violation_triage]",
        f"summary={result.summary}",
        f"ok={result.ok}",
        f"exit_code={result.exit_code}",
        f"total_violations={stats['total']}",
        f"unreviewed_critical={stats['unreviewed_critical']}",
    ]
    for key in ("TP", "FP", "FN", "unreviewed"):
        lines.append(f"type_{key}={stats['by_type'].get(key, 0)}")
    for ann in result.annotations:
        lines.append(f"{ann['level'].upper()}: [{ann['file']}] {ann['message']}")
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Violation triage schema, CI gate, and triage workflow."
    )
    parser.add_argument(
        "--mode",
        choices=["generate", "evaluate"],
        required=True,
        help=(
            "generate: convert tool JSON → triage template "
            "(pass --triage-file to merge existing annotations); "
            "evaluate: read triage file and evaluate CI gate"
        ),
    )
    parser.add_argument("--input", "-i", help="Tool JSON output file (generate mode)")
    parser.add_argument(
        "--input-format",
        choices=["contract_validator", "governance_auditor", "triage"],
        default="triage",
    )
    parser.add_argument(
        "--triage-file", "-t",
        help=(
            "Existing triage JSON: generate mode merges annotations; "
            "evaluate mode uses as gate input"
        ),
    )
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    def _read_json(path: str) -> dict:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def _write(text: str) -> None:
        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        else:
            print(text)

    if args.mode == "generate":
        if not args.input:
            print("ERROR: --input required for generate mode", file=sys.stderr)
            sys.exit(2)
        data = _read_json(args.input)
        fmt = args.input_format
        if fmt == "contract_validator":
            report = from_contract_validator_json(data)
        elif fmt == "governance_auditor":
            report = from_governance_auditor_json(data)
        else:
            report = TriageReport.from_dict(data)
        if args.triage_file and Path(args.triage_file).is_file():
            existing = TriageReport.from_dict(_read_json(args.triage_file))
            report = merge_triage(existing, report)
        _write(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        sys.exit(0)

    elif args.mode == "evaluate":
        if not args.triage_file:
            print("ERROR: --triage-file required for evaluate mode", file=sys.stderr)
            sys.exit(2)
        report = TriageReport.from_dict(_read_json(args.triage_file))
        result = evaluate_ci_gate(report)
        if args.format == "json":
            output = json.dumps(
                {
                    "ok": result.ok,
                    "exit_code": result.exit_code,
                    "summary": result.summary,
                    "annotations": result.annotations,
                    "stats": report.stats(),
                },
                ensure_ascii=False,
                indent=2,
            )
        else:
            output = format_human_gate(result, report)
        _write(output)
        sys.exit(result.exit_code)


if __name__ == "__main__":
    main()
