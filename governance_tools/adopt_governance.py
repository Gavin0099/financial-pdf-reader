#!/usr/bin/env python3
"""
adopt_governance.py — Cross-platform Python equivalent of init-governance.sh.

Designed for Windows users who cannot run bash scripts.

Usage:
    python governance_tools/adopt_governance.py --target /path/to/repo
    python governance_tools/adopt_governance.py --target . --refresh
    python governance_tools/adopt_governance.py --target . --dry-run
    python governance_tools/adopt_governance.py --target . --framework-root /path/to/framework

Modes:
    (default)  adopt-existing: fills governance gaps without overwriting anything
    --refresh  refresh-baseline: recomputes hashes + inventory; no template files copied

What adopt-existing does:
    1. Copies AGENTS.base.md from framework baseline (always; protected file)
    2. Creates AGENTS.md, contract.yaml from template (only if missing)
    3. Creates PLAN.md from template (only if not found in common locations)
    4. Creates .github/workflows/governance-drift.yml (only if missing)
    5. Generates .governance/baseline.yaml with hashes + inventory
    6. Runs drift checker inline and prints findings

What adopt-existing does NOT do:
    - Set plan_required_sections (no mandate imposed on existing repos)
    - Overwrite files that already exist
    - Install git hooks (optional; use scripts/install-hooks.sh on Linux/Mac)

What --refresh does:
    1. Reads plan_path and plan_required_sections from existing baseline.yaml
    2. Recomputes sha256 hashes for all tracked files
    3. Re-detects plan_section_inventory from current PLAN.md
    4. Rewrites .governance/baseline.yaml (preserves mandate, updates hashes + inventory)
    5. Runs drift checker inline

What --refresh does NOT do:
    - Copy or overwrite any template files
    - Change plan_required_sections
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.framework_versioning import (
    discover_framework_root,
    repo_root_from_tooling,
)
from memory_pipeline.memory_layout import MEMORY_FILE_ALIASES


# ── Plan path discovery ────────────────────────────────────────────────────────

_PLAN_SEARCH_PATHS = ["PLAN.md", "governance/PLAN.md", "memory/PLAN.md", "docs/PLAN.md"]
_MEMORY_SCAFFOLD_TEMPLATES: dict[str, str] = {
    "active_task": (
        "# Active Task\n\n"
        "## Current Status\n\n"
        "- Adopted governance baseline.\n\n"
        "## Next Steps\n\n"
        "- Update this file when task state changes.\n"
    ),
    "tech_stack": (
        "# Tech Stack\n\n"
        "## Repo Facts\n\n"
        "- Fill in runtime, language, and tooling facts for this repo.\n"
    ),
    "knowledge_base": (
        "# Knowledge Base\n\n"
        "## Gotchas\n\n"
        "- Record troubleshooting notes, anti-patterns, and fixes here.\n"
    ),
    "review_log": (
        "# Review Log\n\n"
        "## Entries\n\n"
        "- Append review summaries and validation history here.\n"
    ),
}


def _ensure_governance_markdown_pack(repo_root: Path, framework_root: Path, dry_run: bool) -> None:
    source_root = framework_root / "governance"
    target_root = repo_root / "governance"
    if not source_root.is_dir():
        return

    for source in sorted(source_root.glob("*.md")):
        # Root PLAN.md is handled separately by the existing adopt flow.
        if source.name == "PLAN.md":
            continue

        target = target_root / source.name
        if target.exists():
            print(f"  governance/{source.name} -- kept as-is (already exists)")
            continue

        if dry_run:
            print(f"  [dry-run] governance/{source.name} -- would copy canonical governance doc")
            continue

        target_root.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  governance/{source.name} -- copied canonical governance doc")


def _ensure_governance_rules_pack(repo_root: Path, framework_root: Path, dry_run: bool) -> None:
    source_root = framework_root / "governance" / "rules"
    target_root = repo_root / "governance" / "rules"
    if not source_root.is_dir():
        return

    for source in sorted(source_root.rglob("*")):
        if source.is_dir():
            continue

        relative = source.relative_to(source_root)
        target = target_root / relative
        if target.exists():
            print(f"  governance/rules/{relative.as_posix()} -- kept as-is (already exists)")
            continue

        if dry_run:
            print(f"  [dry-run] governance/rules/{relative.as_posix()} -- would copy canonical rule pack file")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  governance/rules/{relative.as_posix()} -- copied canonical rule pack file")


def _discover_plan_path(repo_root: Path) -> Path | None:
    """Return the first PLAN.md found in standard locations, or None."""
    for rel in _PLAN_SEARCH_PATHS:
        p = repo_root / rel
        if p.exists():
            return p
    return None


def _ensure_memory_scaffold(repo_root: Path, dry_run: bool) -> None:
    memory_root = repo_root / "memory"
    for logical_name, candidate_names in MEMORY_FILE_ALIASES.items():
        existing = next((memory_root / name for name in candidate_names if (memory_root / name).exists()), None)
        if existing is not None:
            print(f"  memory/{existing.name} -- kept as-is ({logical_name} already exists)")
            continue

        target = memory_root / candidate_names[0]
        if dry_run:
            print(f"  [dry-run] memory/{target.name} -- would create minimal scaffold ({logical_name})")
            continue

        memory_root.mkdir(parents=True, exist_ok=True)
        target.write_text(_MEMORY_SCAFFOLD_TEMPLATES[logical_name], encoding="utf-8")
        print(f"  memory/{target.name} -- created minimal scaffold ({logical_name})")


def _ensure_contract_agents_base_reference(contract_path: Path, dry_run: bool) -> bool:
    """
    Ensure existing contract.yaml references AGENTS.base.md in ai_behavior_override.

    Returns True when the file was modified.
    """
    from governance_tools.domain_contract_loader import _as_list, _parse_contract_yaml

    text = contract_path.read_text(encoding="utf-8")
    data = _parse_contract_yaml(text)
    referenced = set(_as_list(data.get("documents"))) | set(_as_list(data.get("ai_behavior_override")))
    if "AGENTS.base.md" in referenced:
        print("  contract.yaml — AGENTS.base.md reference already present")
        return False

    lines = text.splitlines()
    inserted = False
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped == "ai_behavior_override: []":
            lines[index] = "ai_behavior_override:"
            lines.insert(index + 1, "  - AGENTS.base.md")
            inserted = True
            break
        if stripped == "ai_behavior_override:":
            insert_at = index + 1
            while insert_at < len(lines):
                candidate = lines[insert_at]
                if candidate.startswith("  - ") or not candidate.strip():
                    insert_at += 1
                    continue
                break
            lines.insert(insert_at, "  - AGENTS.base.md")
            inserted = True
            break

    if not inserted:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["ai_behavior_override:", "  - AGENTS.base.md"])

    if dry_run:
        print("  [dry-run] contract.yaml — would add AGENTS.base.md to ai_behavior_override")
        return True

    contract_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("  contract.yaml — added AGENTS.base.md to ai_behavior_override")
    return True


def _ensure_contract_governance_docs(contract_path: Path, dry_run: bool) -> bool:
    from governance_tools.domain_contract_loader import _as_list, _parse_contract_yaml

    text = contract_path.read_text(encoding="utf-8")
    data = _parse_contract_yaml(text)
    documents = set(_as_list(data.get("documents")))
    required = ["AGENTS.base.md", "PLAN.md", "governance/TESTING.md", "governance/ARCHITECTURE.md"]
    missing = [entry for entry in required if entry not in documents]
    if not missing:
        print("  contract.yaml -- governance document references already present")
        return False

    lines = text.splitlines()
    inserted = False
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped == "documents: []":
            lines[index] = "documents:"
            for offset, entry in enumerate(missing, start=1):
                lines.insert(index + offset, f"  - {entry}")
            inserted = True
            break
        if stripped == "documents:":
            insert_at = index + 1
            while insert_at < len(lines):
                candidate = lines[insert_at]
                if candidate.startswith("  - ") or not candidate.strip():
                    insert_at += 1
                    continue
                break
            for offset, entry in enumerate(missing):
                lines.insert(insert_at + offset, f"  - {entry}")
            inserted = True
            break

    if not inserted:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("documents:")
        for entry in missing:
            lines.append(f"  - {entry}")

    if dry_run:
        print(f"  [dry-run] contract.yaml -- would add {', '.join(missing)} to documents")
        return True

    contract_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  contract.yaml -- added {', '.join(missing)} to documents")
    return True


def _empty_agents_sections(repo_root: Path) -> list[str]:
    agents_path = repo_root / "AGENTS.md"
    if not agents_path.exists():
        return []
    from governance_tools.governance_drift_checker import _find_empty_governance_sections

    return _find_empty_governance_sections(agents_path.read_text(encoding="utf-8"))


def _placeholder_agents_sections(repo_root: Path) -> list[str]:
    agents_path = repo_root / "AGENTS.md"
    if not agents_path.exists():
        return []

    import re

    key_re = re.compile(r"<!--\s*governance:key=(\S+)\s*-->")
    lines = agents_path.read_text(encoding="utf-8").splitlines()
    placeholders: list[str] = []
    i = 0
    while i < len(lines):
        match = key_re.match(lines[i].strip())
        if not match:
            i += 1
            continue
        key = match.group(1)
        i += 1
        content_lines: list[str] = []
        in_comment = False
        while i < len(lines) and not lines[i].strip().startswith("##"):
            stripped = lines[i].strip()
            i += 1
            if not stripped:
                continue
            if in_comment:
                if "-->" in stripped:
                    in_comment = False
                continue
            if stripped.startswith("<!--"):
                if "-->" not in stripped:
                    in_comment = True
                continue
            content_lines.append(stripped)
        if not content_lines:
            continue
        if all(line.startswith("N/A") for line in content_lines):
            placeholders.append(key)
    return placeholders


def _print_refresh_delta_summary(
    *,
    previous_hashes: dict[str, str],
    current_hashes: dict[str, str],
    previous_inventory: list[str],
    current_inventory: list[str],
) -> None:
    changed_files = [
        name
        for name, current_hash in current_hashes.items()
        if previous_hashes.get(name) and previous_hashes.get(name) != current_hash
    ]
    added_sections = [item for item in current_inventory if item not in previous_inventory]
    removed_sections = [item for item in previous_inventory if item not in current_inventory]

    if not changed_files and not added_sections and not removed_sections:
        print("  Refresh delta: no tracked hash or plan inventory changes detected")
        return

    print("  Refresh delta summary:")
    if changed_files:
        print(f"    - tracked hash changes: {', '.join(changed_files)}")
    if added_sections:
        print(f"    - plan sections added: {', '.join(added_sections)}")
    if removed_sections:
        print(f"    - plan sections removed: {', '.join(removed_sections)}")


# ── File hashing ──────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── PLAN.md heading inventory ─────────────────────────────────────────────────

def _detect_plan_sections(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.startswith("## ")]


# ── Source commit ─────────────────────────────────────────────────────────────

def _git_head_sha(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        sha = result.stdout.strip()
        return sha if len(sha) == 40 else "unknown"
    except Exception:
        return "unknown"


# ── Baseline YAML writer ──────────────────────────────────────────────────────

def _write_baseline_yaml(
    repo_root: Path,
    framework_root: Path,
    plan_rel: str,
    inventory: list[str],
    dry_run: bool,
    plan_required_sections: list[str] | None = None,
) -> None:
    """Generate .governance/baseline.yaml."""
    from governance_tools.framework_versioning import current_framework_release

    gov_dir = repo_root / ".governance"
    baseline_path = gov_dir / "baseline.yaml"

    agents_base = repo_root / "AGENTS.base.md"
    plan_path = repo_root / plan_rel
    contract_path = repo_root / "contract.yaml"
    agents_path = repo_root / "AGENTS.md"

    def _hash_or_zero(p: Path) -> str:
        return _sha256(p) if p.exists() else ("0" * 64)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commit = _git_head_sha(repo_root)
    baseline_version = "1.0.0"

    plan_path_block = ""
    if plan_rel != "PLAN.md":
        plan_path_block = f"plan_path: {plan_rel}\n"

    inventory_block = ""
    if inventory:
        lines = "".join(f'  - "{s}"\n' for s in inventory)
        inventory_block = f"plan_section_inventory:\n{lines}"

    content = (
        "# .governance/baseline.yaml\n"
        "# Written by governance_tools/adopt_governance.py — do not edit manually.\n"
        "# Verified by: python governance_tools/governance_drift_checker.py --repo .\n"
        "#\n"
        "# Semantic layers in this file:\n"
        "#   PROVENANCE  — who generated this baseline and from which commit\n"
        "#   INTEGRITY   — sha256 hashes + overridability of tracked files\n"
        "#   CONTRACT    — governance mandates that MUST be satisfied (enforced by drift checker)\n"
        "#   OBSERVED    — snapshot of repo structure at adoption time (informational, not enforced)\n"
        "\n"
        "# ── PROVENANCE ────────────────────────────────────────────────────────────────\n"
        f'schema_version: "1"\n'
        f"baseline_version: {baseline_version}\n"
        f"source_commit: {commit}\n"
        f"framework_root: {framework_root}\n"
        f"initialized_at: {now}\n"
        f"initialized_by: governance_tools/adopt_governance.py\n"
        f"{plan_path_block}"
        "\n"
        "# ── INTEGRITY ─────────────────────────────────────────────────────────────────\n"
        "# sha256.<file>: hash recorded at init/refresh time; \"protected\" files are hash-verified\n"
        "# overridable.<file>: protected = must not change | overridable = repo may extend freely\n"
        f"sha256.AGENTS.base.md: {_hash_or_zero(agents_base)}\n"
        f"sha256.PLAN.md: {_hash_or_zero(plan_path)}\n"
        f"sha256.contract.yaml: {_hash_or_zero(contract_path)}\n"
        f"sha256.AGENTS.md: {_hash_or_zero(agents_path)}\n"
        "overridable.AGENTS.base.md: protected\n"
        "overridable.PLAN.md: overridable\n"
        "overridable.contract.yaml: overridable\n"
        "overridable.AGENTS.md: overridable\n"
        "\n"
        "# ── CONTRACT (framework-enforced mandates) ────────────────────────────────────\n"
        "# Fields listed here are actively checked by drift checker; violations block ci/gate.\n"
        "# CONTRACT layer policy: only values that affect validation judgments belong here.\n"
        "#   Do NOT use this layer for metadata, notes, or domain-specific configuration.\n"
        "# plan_required_sections: ## headings that MUST be present in PLAN.md (governance mandate).\n"
        "#   Empty = no mandate enforced (adopt-existing default). Set explicitly to harden.\n"
        "# plan_freshness_threshold_days: CONTRACT OVERRIDE — changes the staleness threshold\n"
        "#   for plan_freshness check. Default: 14d (framework default) or PLAN.md Freshness header.\n"
        "contract_required_fields:\n"
        "  - name\n"
        "  - framework_interface_version\n"
        "  - framework_compatible\n"
        "  - domain\n"
        + (
            "plan_required_sections:\n"
            + "".join(f'  - "{s}"\n' for s in plan_required_sections)
            if plan_required_sections
            else ""
        )
        + "\n"
        "# ── OBSERVED (repo snapshot — informational only, never enforced) ──────────────\n"
        "# plan_section_inventory: ## headings detected in PLAN.md at adoption/refresh time.\n"
        "#   Drift checker surfaces these for visibility but never fails on missing inventory items.\n"
        f"{inventory_block}"
    )

    if dry_run:
        print(f"  [dry-run] Would write: {baseline_path}")
        return

    gov_dir.mkdir(exist_ok=True)
    baseline_path.write_text(content, encoding="utf-8")
    print(f"  Wrote {baseline_path}")


# ── Main adopt logic ──────────────────────────────────────────────────────────

# ── Step 6: Payload layering + onboarding fix ─────────────────────────────────

def _detect_repo_type(repo_root: Path) -> str:
    """
    Heuristically detect repo type based on file presence.
    Returns: "firmware" | "product" | "service" | "generic"
    """
    has_cmake = (repo_root / "CMakeLists.txt").exists() or any(repo_root.rglob("CMakeLists.txt"))
    has_c = any(repo_root.rglob("*.c"))
    has_cpp = any(repo_root.rglob("*.cpp")) or any(repo_root.rglob("*.h"))
    has_driver = any(repo_root.rglob("*.inf")) or any(repo_root.rglob("*.sys"))
    has_package_json = (repo_root / "package.json").exists()
    has_pyproject = (repo_root / "pyproject.toml").exists() or (repo_root / "setup.py").exists()

    if has_driver or has_cmake or (has_c and has_cpp):
        return "firmware"
    if has_package_json:
        return "product"
    if has_pyproject:
        return "service"
    return "generic"


def _get_default_rule_packs(target_repo_root: Path) -> list[str]:
    """
    Determine default rule packs for a repo based on its detected type.
    Never returns 'onboarding' — that is not a valid rule pack name.
    """
    from governance_tools.rule_pack_loader import available_rule_packs

    repo_type = _detect_repo_type(target_repo_root)
    framework_root = Path(__file__).resolve().parent.parent
    rules_root = framework_root / "governance" / "rules"
    available = available_rule_packs(rules_root)

    packs: list[str] = []
    if "common" in available:
        packs.append("common")

    if repo_type == "firmware":
        for candidate in ("cpp", "kernel-driver"):
            if candidate in available:
                packs.append(candidate)
    elif repo_type == "product":
        for candidate in ("typescript",):
            if candidate in available:
                packs.append(candidate)
    elif repo_type == "service":
        for candidate in ("python",):
            if candidate in available:
                packs.append(candidate)

    return packs


def _write_payload_layering_config(target_repo_root: Path, repo_type: str) -> None:
    """
    Write .governance-payload-config.yaml to an adopted repo so that
    session_start can automatically use layered loading without manual config.
    """
    text = (
        "payload_layering:\n"
        "  version: '1.0.0'\n"
        f"  repo_type: {repo_type}\n"
        "  l0_context:\n"
        "    always_load:\n"
        "    - governance/SYSTEM_PROMPT.md\n"
        "    - governance/AGENT.md\n"
        "    - PLAN.md\n"
        "    forbidden_load:\n"
        "    - governance/ARCHITECTURE.md\n"
        "    - governance/REVIEW_CRITERIA.md\n"
        "    - governance/HUMAN-OVERSIGHT.md\n"
        "    - governance/NATIVE-INTEROP.md\n"
        "    domain_contract_policy: skip\n"
        "  memory_policy: incremental\n"
        "  authority_table_path: governance/AUTHORITY.md\n"
        "  rule_registry_path: governance/RULE_REGISTRY.md\n"
    )
    config_path = target_repo_root / ".governance-payload-config.yaml"
    config_path.write_text(text, encoding="utf-8")


def _write_session_defaults(target_repo_root: Path, repo_type: str) -> None:
    """
    Update .governance-state.yaml with session defaults so adopted repos
    start with the right configuration out of the box.
    """
    state_file = target_repo_root / ".governance-state.yaml"
    if not state_file.exists():
        return
    content = state_file.read_text(encoding="utf-8")
    if "session_defaults:" in content:
        return  # already written; avoid duplication
    block = (
        "\nsession_defaults:\n"
        f"  repo_type: {repo_type}\n"
        "  task_level_detection: auto\n"
        "  domain_summary_first: true\n"
        "  memory_mode: incremental\n"
    )
    state_file.write_text(content + block, encoding="utf-8")


def adopt_existing(
    repo_root: Path,
    framework_root: Path,
    dry_run: bool = False,
) -> int:
    """
    Run the adopt-existing flow. Returns exit code (0 = success, 1 = errors found).
    """
    repo_root = repo_root.resolve()
    framework_root = framework_root.resolve()
    baseline_source = framework_root / "baselines" / "repo-min"

    print(f"Adopting governance baseline into existing repo: {repo_root}")
    print(f"Baseline source: {baseline_source}")
    print()

    if not (repo_root / ".git").exists():
        print(f"ERROR: {repo_root} is not a git repository (.git not found)")
        return 1

    if not baseline_source.is_dir():
        print(f"ERROR: baseline source not found: {baseline_source}")
        print("  Set --framework-root or GOVERNANCE_FRAMEWORK_ROOT env var to the framework installation.")
        return 1

    # ── Discover PLAN.md ──────────────────────────────────────────────────────
    plan_path = _discover_plan_path(repo_root)
    if plan_path:
        plan_rel = str(plan_path.relative_to(repo_root)).replace("\\", "/")
        if plan_rel != "PLAN.md":
            print(f"  PLAN.md — found at {plan_rel} (non-standard location; plan_path recorded in baseline)")
        else:
            if not dry_run:
                print(f"  PLAN.md — kept as-is (already exists)")
    else:
        plan_rel = "PLAN.md"
        target_plan = repo_root / "PLAN.md"
        if dry_run:
            print(f"  [dry-run] PLAN.md — would copy from template (missing)")
        else:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            plan_text = (baseline_source / "PLAN.md").read_text(encoding="utf-8")
            plan_text = plan_text.replace("YYYY-MM-DD", today)
            plan_text = plan_text.replace("<repo-owner>", "TODO")
            target_plan.write_text(plan_text, encoding="utf-8")
            print(f"  PLAN.md — copied from template (was missing)")

    # ── AGENTS.base.md — always copy (protected) ─────────────────────────────
    target_agents_base = repo_root / "AGENTS.base.md"
    if dry_run:
        print(f"  [dry-run] AGENTS.base.md — would copy (protected baseline, always refreshed)")
    else:
        import shutil
        shutil.copy2(baseline_source / "AGENTS.base.md", target_agents_base)
        print(f"  Copied AGENTS.base.md (protected baseline)")

    # Minimal CI drift workflow - copy from template only if missing
    target_drift_workflow = repo_root / ".github" / "workflows" / "governance-drift.yml"
    source_drift_workflow = baseline_source / ".github" / "workflows" / "governance-drift.yml"
    if target_drift_workflow.exists():
        print("  .github/workflows/governance-drift.yml -- kept as-is (already exists)")
    else:
        if dry_run:
            print("  [dry-run] .github/workflows/governance-drift.yml -- would copy from template (missing)")
        else:
            target_drift_workflow.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_drift_workflow, target_drift_workflow)
            print("  .github/workflows/governance-drift.yml -- copied from template (was missing)")

    # ── Overridable files — copy from template only if missing ────────────────
    for fname in ("AGENTS.md", "contract.yaml"):
        target = repo_root / fname
        if target.exists():
            print(f"  {fname} — kept as-is (already exists)")
            if fname == "contract.yaml":
                _ensure_contract_agents_base_reference(target, dry_run=dry_run)
                _ensure_contract_governance_docs(target, dry_run=dry_run)
        else:
            if dry_run:
                print(f"  [dry-run] {fname} — would copy from template (missing)")
            else:
                template_text = (baseline_source / fname).read_text(encoding="utf-8")
                if fname == "contract.yaml":
                    slug = repo_root.name.lower().replace(" ", "-")
                    template_text = template_text.replace("<repo-name>-contract", f"{slug}-contract")
                    template_text = template_text.replace("<domain>", slug)
                target.write_text(template_text, encoding="utf-8")
                print(f"  {fname} — copied from template (was missing)")

    # ── Detect plan inventory ─────────────────────────────────────────────────
    effective_plan = repo_root / plan_rel
    inventory: list[str] = []
    if effective_plan.exists():
        inventory = _detect_plan_sections(effective_plan.read_text(encoding="utf-8"))
        if inventory:
            print()
            print(f"  plan_section_inventory: {len(inventory)} heading(s) observed in {plan_rel}")
            for s in inventory:
                print(f"    {s}")
            print("  (recorded as inventory; no sections are enforced until you set plan_required_sections)")

    # ── Write baseline.yaml ───────────────────────────────────────────────────
    print()
    _write_baseline_yaml(
        repo_root=repo_root,
        framework_root=framework_root,
        plan_rel=plan_rel,
        inventory=inventory,
        dry_run=dry_run,
    )

    print()
    _ensure_memory_scaffold(repo_root, dry_run=dry_run)

    print()
    _ensure_governance_markdown_pack(repo_root, framework_root, dry_run=dry_run)

    print()
    _ensure_governance_rules_pack(repo_root, framework_root, dry_run=dry_run)

    if dry_run:
        print()
        print("Dry-run complete. No files were written.")
        return 0

    # ── Post-adoption drift summary (summary-first) ───────────────────────────
    print()
    print("─" * 60)
    print("Post-adoption drift check:")
    print("─" * 60)
    drift_ok = False
    drift_severity = "unknown"
    drift_checks: dict[str, bool] = {}
    drift_warnings: list[str] = []
    try:
        from governance_tools.governance_drift_checker import check_governance_drift
        drift = check_governance_drift(repo_root, framework_root=framework_root)
        drift_ok = drift.ok
        drift_severity = drift.severity
        drift_checks = drift.checks
        drift_warnings = drift.warnings or []
        checks_passed = sum(1 for v in drift_checks.values() if v)
        checks_total = len(drift_checks)
        # ── Summary-first header ──────────────────────────────────────────────
        print(f"[adopt_governance]")
        print(f"ok={drift_ok} | severity={drift_severity} | checks={checks_passed}/{checks_total}")
        if drift_warnings:
            for w in drift_warnings[:5]:
                print(f"  warning: {w}")
        print()
        # ── Per-check detail ──────────────────────────────────────────────────
        for check_name, passed in sorted(drift_checks.items()):
            status = "PASS" if passed else "FAIL"
            print(f"  {status}: {check_name}")
    except Exception as exc:
        print(f"  (drift check failed: {exc})")

    # ── Step 6: Write payload layering config ─────────────────────────────────
    if not dry_run:
        repo_type = _detect_repo_type(repo_root)
        _write_payload_layering_config(repo_root, repo_type)
        print(f"  Wrote .governance-payload-config.yaml (repo_type={repo_type})")
        _write_session_defaults(repo_root, repo_type)
        if (repo_root / ".governance-state.yaml").exists():
            print(f"  Updated .governance-state.yaml with session_defaults")
    else:
        repo_type = _detect_repo_type(repo_root)
        print(f"  [dry-run] Would write .governance-payload-config.yaml (repo_type={repo_type})")

    print()
    print("Adoption complete. Next steps:")
    print("  1. Fix any FAIL/warning items shown above")
    print(f"  2. When files change: python governance_tools/adopt_governance.py --target {repo_root} --refresh")
    print(f"  3. Commit: git add AGENTS.base.md AGENTS.md PLAN.md contract.yaml .governance/baseline.yaml")
    print(f"  4. Verify: python governance_tools/governance_drift_checker.py --repo {repo_root}")
    placeholder_agents_sections = _placeholder_agents_sections(repo_root)
    if placeholder_agents_sections:
        print()
        print("  Repo-specific AGENTS.md sections still worth filling:")
        for key in placeholder_agents_sections:
            print(f"    - {key}")
        print("  (Keeping N/A is valid, but these are the first repo-specific prompts to customize.)")
    print()
    print("  Reference: docs/minimum-legal-schema.md — expected check states, field semantics, and")
    print("             which False results are non-blocking by design")
    return 0


# ── Baseline reader (for --refresh) ──────────────────────────────────────────

def _read_baseline_state(repo_root: Path) -> dict:
    """Read key baseline state from existing baseline.yaml."""
    from governance_tools.domain_contract_loader import _parse_contract_yaml

    baseline_path = repo_root / ".governance" / "baseline.yaml"
    if not baseline_path.exists():
        return {"plan_rel": "PLAN.md", "required": [], "inventory": [], "hashes": {}}

    data = _parse_contract_yaml(baseline_path.read_text(encoding="utf-8"))
    plan_rel = str(data.get("plan_path") or "PLAN.md")

    raw_required = data.get("plan_required_sections")
    if isinstance(raw_required, list):
        required = [str(s) for s in raw_required]
    else:
        required = []

    raw_inventory = data.get("plan_section_inventory")
    if isinstance(raw_inventory, list):
        inventory = [str(s) for s in raw_inventory]
    else:
        inventory = []

    hashes = {
        "AGENTS.base.md": str(data.get("sha256.AGENTS.base.md") or ""),
        "PLAN.md": str(data.get("sha256.PLAN.md") or ""),
        "contract.yaml": str(data.get("sha256.contract.yaml") or ""),
        "AGENTS.md": str(data.get("sha256.AGENTS.md") or ""),
    }

    return {"plan_rel": plan_rel, "required": required, "inventory": inventory, "hashes": hashes}



# ── Refresh baseline ──────────────────────────────────────────────────────────

def refresh_baseline(
    repo_root: Path,
    framework_root: Path,
    dry_run: bool = False,
) -> int:
    """Re-hash tracked files and refresh plan_section_inventory.

    Equivalent to: bash scripts/init-governance.sh --target <repo> --refresh-baseline

    Preserves plan_required_sections from the existing baseline (governance mandate).
    Does NOT copy or overwrite any template files.
    """
    repo_root = repo_root.resolve()
    framework_root = framework_root.resolve()

    print(f"Refreshing baseline hashes and section inventory: {repo_root}")
    print()

    baseline_path = repo_root / ".governance" / "baseline.yaml"
    if not baseline_path.exists():
        print("ERROR: no .governance/baseline.yaml found")
        print("  Run adopt first: python governance_tools/adopt_governance.py --target .")
        return 1

    # ── Read existing state ───────────────────────────────────────────────────
    state = _read_baseline_state(repo_root)
    plan_rel = state["plan_rel"]
    required = state["required"]
    previous_inventory = state.get("inventory", [])
    previous_hashes = state.get("hashes", {})

    if required:
        print(f"  Preserved {len(required)} plan_required_sections from existing baseline")

    # ── Re-detect plan inventory ──────────────────────────────────────────────
    plan_path = repo_root / plan_rel
    inventory: list[str] = []
    if plan_path.exists():
        inventory = _detect_plan_sections(plan_path.read_text(encoding="utf-8"))
        if inventory:
            print(f"  plan_section_inventory: {len(inventory)} heading(s) in {plan_rel}")

    if dry_run:
        print()
        print(f"  [dry-run] Would recompute hashes for: AGENTS.base.md AGENTS.md {plan_rel} contract.yaml")
        if required:
            print(f"  [dry-run] plan_required_sections — {len(required)} section(s) preserved")
        print(f"  [dry-run] Would rewrite: {baseline_path}")
        print()
        print("Dry-run complete. No files were written.")
        return 0

    # ── Write refreshed baseline ──────────────────────────────────────────────
    # Build the required_block to re-inject into _write_baseline_yaml content.
    # We do this by writing baseline via the standard writer then appending
    # the plan_required_sections block if it was present before.
    _write_baseline_yaml(
        repo_root=repo_root,
        framework_root=framework_root,
        plan_rel=plan_rel,
        inventory=inventory,
        dry_run=False,
        plan_required_sections=required,
    )

    current_hashes = {
        "AGENTS.base.md": _sha256(repo_root / "AGENTS.base.md") if (repo_root / "AGENTS.base.md").exists() else "",
        "PLAN.md": _sha256(repo_root / plan_rel) if (repo_root / plan_rel).exists() else "",
        "contract.yaml": _sha256(repo_root / "contract.yaml") if (repo_root / "contract.yaml").exists() else "",
        "AGENTS.md": _sha256(repo_root / "AGENTS.md") if (repo_root / "AGENTS.md").exists() else "",
    }

    print()
    _print_refresh_delta_summary(
        previous_hashes=previous_hashes,
        current_hashes=current_hashes,
        previous_inventory=previous_inventory,
        current_inventory=inventory,
    )

    print()
    print("Refresh complete. Verify with:")
    print(f"  python governance_tools/governance_drift_checker.py --repo {repo_root}")
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def _resolve_framework_root(target: Path, cli_value: str | None) -> Path:
    """Resolve framework root using the standard priority chain."""
    if cli_value:
        return Path(cli_value).resolve()
    import os
    env_root = os.environ.get("GOVERNANCE_FRAMEWORK_ROOT", "").strip()
    if env_root:
        return Path(env_root).resolve()
    discovered = discover_framework_root(target)
    return discovered if discovered else repo_root_from_tooling()


def _check_env() -> int:
    """Check that the environment is ready to run the framework. Exit 0 if ok."""
    import importlib
    ok = True

    py = sys.version_info
    print(f"[OK]   Python {py.major}.{py.minor}.{py.micro} available")

    for pkg, install_hint in [
        ("yaml", "pip install pyyaml"),
        ("pytest", "pip install pytest"),
    ]:
        try:
            importlib.import_module(pkg)
            label = "pyyaml" if pkg == "yaml" else pkg
            print(f"[OK]   {label} installed")
        except ImportError:
            label = "pyyaml" if pkg == "yaml" else pkg
            print(f"[FAIL] {label} not found — run: {install_hint}")
            ok = False

    if ok:
        print("\nEnvironment ready. Next step:")
        print("  python governance_tools/adopt_governance.py --target /path/to/your/repo")
    else:
        print("\nFix the above before running adopt.")

    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Adopt or refresh AI Governance Framework baseline (cross-platform)."
    )
    parser.add_argument("--target", help="Path to the target repository")
    parser.add_argument("--framework-root", help="Path to framework installation (auto-detected if omitted)")
    parser.add_argument("--refresh", action="store_true",
                        help="Refresh mode: recompute hashes + inventory without copying template files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing files")
    parser.add_argument("--check-env", action="store_true",
                        help="Check that Python and required packages are available, then exit")
    args = parser.parse_args()

    if args.check_env:
        return _check_env()

    if not args.target:
        parser.error("--target is required unless --check-env is specified")

    target = Path(args.target).resolve()
    framework_root = _resolve_framework_root(target, args.framework_root)

    if args.refresh:
        return refresh_baseline(target, framework_root, dry_run=args.dry_run)
    return adopt_existing(target, framework_root, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
