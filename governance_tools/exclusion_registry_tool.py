#!/usr/bin/env python3
"""
Exclusion registry tool — E2b/E2c.

Reads governance/test_exclusion_registry.yaml and provides:

  generate-filter   Print the pytest -k expression derived from active rules
  audit             Report expired, unjustified, or stale exclusion entries
  show              Pretty-print all active / inactive entries
  validate          Exit 1 if any integrity constraint is violated

Exit codes
----------
  0  all checks pass
  1  audit found issues (expired/missing-justification/no-owner) OR
     validate found integrity violations
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "governance" / "test_exclusion_registry.yaml"

# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class ExclusionEntry:
    id: str
    pattern: str
    scope: str
    failure_kind: str
    justification: str
    owner: str
    added_at: str
    expiry: str
    revalidation_trigger: str
    active: bool

    def expiry_date(self) -> Optional[date]:
        try:
            return datetime.strptime(self.expiry, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    def is_expired(self, as_of: Optional[date] = None) -> bool:
        d = self.expiry_date()
        if d is None:
            return False
        return d < (as_of or date.today())

    def integrity_errors(self) -> list[str]:
        errors = []
        if not self.justification.strip():
            errors.append("missing justification")
        if not self.owner.strip():
            errors.append("missing owner")
        if self.expiry_date() is None:
            errors.append(f"unparseable expiry: {self.expiry!r}")
        if not self.revalidation_trigger.strip():
            errors.append("missing revalidation_trigger")
        return errors


@dataclass
class RegistryAuditResult:
    total: int
    active: int
    inactive: int
    expired: list[str]
    missing_justification: list[str]
    missing_owner: list[str]
    integrity_errors: dict[str, list[str]]
    ok: bool

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "active": self.active,
            "inactive": self.inactive,
            "expired": self.expired,
            "missing_justification": self.missing_justification,
            "missing_owner": self.missing_owner,
            "integrity_errors": self.integrity_errors,
            "ok": self.ok,
        }


# ── Loader ────────────────────────────────────────────────────────────────────

def load_registry(path: Path) -> list[ExclusionEntry]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = []
    for item in raw.get("exclusions", []):
        entries.append(ExclusionEntry(
            id=item.get("id", ""),
            pattern=item.get("pattern", ""),
            scope=item.get("scope", "test_name_contains"),
            failure_kind=item.get("failure_kind", "unknown"),
            justification=str(item.get("justification", "")).strip(),
            owner=str(item.get("owner", "")).strip(),
            added_at=str(item.get("added_at", "")),
            expiry=str(item.get("expiry", "")),
            revalidation_trigger=str(item.get("revalidation_trigger", "")).strip(),
            active=bool(item.get("active", True)),
        ))
    return entries


# ── generate-filter ───────────────────────────────────────────────────────────

def generate_filter(entries: list[ExclusionEntry], *, warn_expired: bool = True) -> str:
    """
    Build a pytest -k expression from active exclusion rules.
    Expired-but-still-active entries are included with a warning.
    """
    active = [e for e in entries if e.active]
    if not active:
        return ""

    warnings = []
    parts = []
    for e in active:
        if warn_expired and e.is_expired():
            warnings.append(f"WARNING: exclusion {e.id} ({e.pattern!r}) is expired (expiry={e.expiry})")
        parts.append(f"not {e.pattern}")

    if warnings:
        for w in warnings:
            print(w, file=sys.stderr)

    return " and ".join(parts)


# ── audit ─────────────────────────────────────────────────────────────────────

def audit_registry(entries: list[ExclusionEntry]) -> RegistryAuditResult:
    active = [e for e in entries if e.active]
    inactive = [e for e in entries if not e.active]

    expired = [e.id for e in active if e.is_expired()]
    missing_just = [e.id for e in entries if not e.justification]
    missing_owner = [e.id for e in entries if not e.owner]

    integrity: dict[str, list[str]] = {}
    for e in entries:
        errs = e.integrity_errors()
        if errs:
            integrity[e.id] = errs

    ok = (
        len(expired) == 0
        and len(missing_just) == 0
        and len(missing_owner) == 0
        and len(integrity) == 0
    )

    return RegistryAuditResult(
        total=len(entries),
        active=len(active),
        inactive=len(inactive),
        expired=expired,
        missing_justification=missing_just,
        missing_owner=missing_owner,
        integrity_errors=integrity,
        ok=ok,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage and audit the test exclusion registry."
    )
    parser.add_argument(
        "--registry", default=str(_DEFAULT_REGISTRY),
        help="Path to test_exclusion_registry.yaml",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # generate-filter
    p_gen = sub.add_parser(
        "generate-filter",
        help="Print pytest -k expression for active exclusion rules",
    )
    p_gen.add_argument(
        "--format", choices=["k-expression", "json"], default="k-expression",
    )
    p_gen.add_argument(
        "--no-warn-expired", action="store_true",
        help="Suppress warnings for expired-but-active entries",
    )

    # audit
    p_audit = sub.add_parser(
        "audit",
        help="Check for expired, unjustified, or integrity-violating entries",
    )
    p_audit.add_argument("--format", choices=["human", "json"], default="human")

    # show
    p_show = sub.add_parser("show", help="List all entries")
    p_show.add_argument("--active-only", action="store_true")
    p_show.add_argument("--format", choices=["human", "json"], default="human")

    # validate
    sub.add_parser("validate", help="Exit 1 if any integrity constraint is violated")

    args = parser.parse_args()
    registry_path = Path(args.registry)

    if not registry_path.exists():
        print(f"Registry not found: {registry_path}", file=sys.stderr)
        sys.exit(2)

    entries = load_registry(registry_path)

    if args.command == "generate-filter":
        warn = not getattr(args, "no_warn_expired", False)
        k_expr = generate_filter(entries, warn_expired=warn)
        if args.format == "json":
            print(json.dumps({"k_expression": k_expr, "active_count": len([e for e in entries if e.active])}, indent=2))
        else:
            print(k_expr)
        sys.exit(0)

    elif args.command == "audit":
        result = audit_registry(entries)
        if args.format == "json":
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"[exclusion_registry audit]")
            print(f"total={result.total}  active={result.active}  inactive={result.inactive}")
            print(f"ok={result.ok}")
            if result.expired:
                print(f"\nEXPIRED (must renew or remove):")
                for eid in result.expired:
                    print(f"  {eid}")
            if result.missing_justification:
                print(f"\nMISSING JUSTIFICATION:")
                for eid in result.missing_justification:
                    print(f"  {eid}")
            if result.missing_owner:
                print(f"\nMISSING OWNER:")
                for eid in result.missing_owner:
                    print(f"  {eid}")
            if result.integrity_errors:
                print(f"\nINTEGRITY ERRORS:")
                for eid, errs in result.integrity_errors.items():
                    print(f"  {eid}: {', '.join(errs)}")
            if result.ok:
                print("\nAll exclusion entries pass integrity checks.")
        sys.exit(0 if result.ok else 1)

    elif args.command == "show":
        shown = [e for e in entries if e.active] if args.active_only else entries
        if args.format == "json":
            print(json.dumps([
                {
                    "id": e.id,
                    "pattern": e.pattern,
                    "failure_kind": e.failure_kind,
                    "active": e.active,
                    "expired": e.is_expired(),
                    "owner": e.owner,
                    "expiry": e.expiry,
                }
                for e in shown
            ], indent=2))
        else:
            for e in shown:
                expired_marker = " [EXPIRED]" if e.is_expired() else ""
                active_marker = "" if e.active else " [inactive]"
                print(f"{e.id}{active_marker}{expired_marker}  pattern={e.pattern!r}  kind={e.failure_kind}  owner={e.owner}  expiry={e.expiry}")
        sys.exit(0)

    elif args.command == "validate":
        result = audit_registry(entries)
        if not result.ok:
            print("Exclusion registry integrity check FAILED:", file=sys.stderr)
            for eid, errs in result.integrity_errors.items():
                print(f"  {eid}: {', '.join(errs)}", file=sys.stderr)
            if result.expired:
                print(f"  Expired entries: {result.expired}", file=sys.stderr)
        sys.exit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
