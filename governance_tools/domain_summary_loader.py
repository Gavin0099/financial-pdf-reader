#!/usr/bin/env python3
"""
Domain adapter summary loader — summary-first domain contract loading.

Step 4: Token optimisation for rich domain contracts (e.g. KDC).

When a domain adapter summary exists in docs/domain-summaries/, the full
inline documents are replaced with the slim summary, reducing token usage
significantly (target: 13,605 → ~1,500 tokens for KDC).
"""

from __future__ import annotations

import re
from pathlib import Path


DOMAIN_SUMMARIES_DIR = Path(__file__).resolve().parent.parent / "docs" / "domain-summaries"


def _slug(name: str) -> str:
    """Convert a domain name to a filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _extract_domain_name(contract_file: Path) -> str:
    """Extract the domain name from a contract.yaml file."""
    try:
        text = contract_file.read_text(encoding="utf-8")
        match = re.search(r"^domain:\s*(.+)$", text, re.MULTILINE)
        if match:
            return match.group(1).strip().strip("\"'")
    except OSError:
        pass
    # Fallback: use the parent directory name
    return contract_file.parent.name


def load_domain_summary(
    contract_file: Path,
    summaries_dir: Path | None = None,
) -> dict | None:
    """
    Look for a domain adapter summary file for the given contract.

    Search order:
    1. {summaries_dir}/{slug}-adapter-summary.md
    2. {summaries_dir}/{slug}.md

    Returns a dict with keys: domain, content, source
    Returns None if no summary file is found.
    """
    sdir = Path(summaries_dir) if summaries_dir is not None else DOMAIN_SUMMARIES_DIR
    if not sdir.exists():
        return None

    domain_name = _extract_domain_name(contract_file)
    slug = _slug(domain_name)

    candidates = [
        sdir / f"{slug}-adapter-summary.md",
        sdir / f"{slug}.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                content = candidate.read_text(encoding="utf-8")
            except OSError:
                continue
            return {
                "domain": domain_name,
                "content": content,
                "source": str(candidate),
            }
    return None


def inject_domain_summary(
    domain_contract: dict,
    contract_file: Path,
    summaries_dir: Path | None = None,
) -> dict:
    """
    If a summary exists for this contract, return a slim version of domain_contract.

    The slim version:
    - Adds a "summary" key with the summary markdown text
    - Adds "summary_source" and "slim=True" markers
    - Clears "documents" and "ai_behavior_override" lists (major token sources)
    - Records "documents_skipped" count for auditability

    Returns the original dict unchanged if no summary is found.
    """
    if not domain_contract:
        return domain_contract

    summary_data = load_domain_summary(contract_file, summaries_dir)
    if not summary_data:
        return domain_contract  # No summary → keep full contract (existing behaviour)

    result = dict(domain_contract)
    result["summary"] = summary_data["content"]
    result["summary_source"] = summary_data["source"]
    result["slim"] = True
    result["documents_skipped"] = len(domain_contract.get("documents", []))
    result["overrides_skipped"] = len(domain_contract.get("ai_behavior_override", []))
    result["documents"] = []
    result["ai_behavior_override"] = []
    return result


def detect_required_domains(project_root: Path) -> list[str]:
    """
    Detect which domain contracts are required for this project.

    Reads contract.yaml from project_root and extracts the domain name.
    Returns [] if no contract.yaml is found or the domain field is absent.
    """
    contract_file = project_root / "contract.yaml"
    if not contract_file.exists():
        return []
    try:
        text = contract_file.read_text(encoding="utf-8")
        match = re.search(r"^domain:\s*(.+)$", text, re.MULTILINE)
        if match:
            return [match.group(1).strip().strip("\"'")]
    except OSError:
        pass
    return []


def load_domain_contract(
    contract_file: Path,
    summary_first: bool = True,
    summaries_dir: Path | None = None,
) -> dict:
    """
    Load a domain contract with optional summary-first optimisation.

    Wraps governance_tools.domain_contract_loader.load_domain_contract.
    When summary_first=True and a summary exists, the full documents are
    replaced with the slim summary (reducing token usage ≥ 50%).
    """
    from governance_tools.domain_contract_loader import load_domain_contract as _load_full

    contract = _load_full(contract_file)
    if contract and summary_first:
        return inject_domain_summary(contract, contract_file, summaries_dir)
    return contract
