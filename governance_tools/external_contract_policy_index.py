#!/usr/bin/env python3
"""
Build a cross-repo index over external contract enforcement policies.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.domain_contract_loader import load_domain_contract
from governance_tools.domain_governance_metadata import domain_risk_tier
from governance_tools.human_summary import build_summary_line


def _contract_path_for_repo(repo_root: Path) -> Path:
    return repo_root / "contract.yaml"


def _enforcement_profile(validator_count: int, hard_stop_rules: list[str]) -> str:
    if validator_count <= 0:
        return "discovery-only"
    if hard_stop_rules:
        return "mixed"
    return "advisory-only"


def _build_entry(repo_root: Path) -> dict:
    repo_root = repo_root.resolve()
    contract_path = _contract_path_for_repo(repo_root)
    if not contract_path.is_file():
        return {
            "repo_root": str(repo_root),
            "ok": False,
            "error": "contract.yaml not found",
            "contract_path": str(contract_path),
        }

    contract = load_domain_contract(contract_path)
    assert contract is not None
    raw = contract.get("raw") or {}
    validators = contract.get("validators") or []
    hard_stop_rules = [str(item) for item in raw.get("hard_stop_rules") or []]
    domain = str(raw.get("domain") or contract.get("name") or "unknown")
    return {
        "repo_root": str(repo_root),
        "ok": True,
        "contract_path": str(contract_path),
        "contract_name": contract.get("name"),
        "domain": domain,
        "risk_tier": domain_risk_tier(domain),
        "documents_count": len(contract.get("documents") or []),
        "rule_root_count": len(contract.get("rule_roots") or []),
        "validator_count": len(validators),
        "validator_ready_count": sum(1 for item in validators if item.get("exists")),
        "hard_stop_rules": hard_stop_rules,
        "hard_stop_rule_count": len(hard_stop_rules),
        "enforcement_profile": _enforcement_profile(len(validators), hard_stop_rules),
    }


def _entry_priority(entry: dict) -> tuple[int, int, str]:
    ok_rank = 0 if entry.get("ok") is False else 1
    hard_stop_rank = 0 if entry.get("hard_stop_rule_count", 0) > 0 else 1
    repo_root = entry.get("repo_root", "")
    return (ok_rank, hard_stop_rank, repo_root)


def build_external_contract_policy_index(repo_roots: list[Path]) -> dict:
    entries = sorted((_build_entry(path) for path in repo_roots), key=_entry_priority)
    return {
        "ok": all(entry.get("ok") for entry in entries),
        "repo_count": len(repo_roots),
        "indexed_count": len(entries),
        "entries": entries,
    }


def format_human(result: dict) -> str:
    lines = [
        "[external_contract_policy_index]",
        build_summary_line(
            f"ok={result['ok']}",
            f"repos={result['repo_count']}",
            f"indexed={result['indexed_count']}",
        ),
        f"ok={result['ok']}",
        f"repo_count={result['repo_count']}",
        f"indexed_count={result['indexed_count']}",
    ]

    entries = result.get("entries") or []
    if entries:
        lines.append("[contracts]")
        for entry in entries:
            if not entry.get("ok"):
                lines.append(
                    " | ".join(
                        [
                            entry["repo_root"],
                            f"ok={entry['ok']}",
                            f"error={entry.get('error')}",
                        ]
                    )
                )
                continue
            lines.append(
                " | ".join(
                    [
                        entry["repo_root"],
                        f"domain={entry['domain']}",
                        f"risk={entry['risk_tier']}",
                        f"profile={entry['enforcement_profile']}",
                        f"validators={entry['validator_ready_count']}/{entry['validator_count']}",
                        f"hard_stop_rules={','.join(entry['hard_stop_rules']) or '-'}",
                    ]
                )
            )
    return "\n".join(lines)


def format_markdown(result: dict) -> str:
    lines = [
        "# Domain Enforcement Matrix",
        "",
        build_summary_line(
            f"ok={result['ok']}",
            f"repos={result['repo_count']}",
            f"indexed={result['indexed_count']}",
        ),
        "",
        "| Repo | Domain | Risk Tier | Enforcement Profile | Validators | Hard-Stop Rules |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in result.get("entries") or []:
        if not entry.get("ok"):
            lines.append(
                f"| `{Path(entry['repo_root']).name}` | - | - | error | - | {entry.get('error')} |"
            )
            continue
        validators = f"{entry['validator_ready_count']}/{entry['validator_count']}"
        hard_stop_rules = ", ".join(entry["hard_stop_rules"]) if entry["hard_stop_rules"] else "-"
        lines.append(
            f"| `{Path(entry['repo_root']).name}` | `{entry['domain']}` | `{entry['risk_tier']}` | `{entry['enforcement_profile']}` | `{validators}` | `{hard_stop_rules}` |"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a framework-level index for external contract enforcement policies.")
    parser.add_argument("--repo", action="append", default=[], help="External repo root to include. Can be repeated.")
    parser.add_argument("--format", choices=("human", "json", "markdown"), default="human")
    parser.add_argument("--output")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = build_external_contract_policy_index([Path(item) for item in args.repo])
    if args.format == "json":
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
    elif args.format == "markdown":
        rendered = format_markdown(result)
    else:
        rendered = format_human(result)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
