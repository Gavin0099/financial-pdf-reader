#!/usr/bin/env python3
"""
Context-aware rule pack classification based on RULE_REGISTRY.md.

Step 4: Rule Classification + Context-Aware Activation
"""

from __future__ import annotations

import re
from pathlib import Path


RULE_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "governance" / "RULE_REGISTRY.md"


def _parse_yaml_block(text: str) -> dict:
    """Parse a simple flat YAML block (key: value + key: [a, b, c])."""
    result: dict[str, object] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value.startswith("[") and raw_value.endswith("]"):
            inner = raw_value[1:-1]
            result[key] = [v.strip() for v in inner.split(",") if v.strip()]
        else:
            # Strip optional surrounding quotes
            if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in ('"', "'"):
                raw_value = raw_value[1:-1]
            result[key] = raw_value
    return result


def load_rule_registry(registry_path: Path | str | None = None) -> list[dict]:
    """
    Parse RULE_REGISTRY.md and return a list of rule pack metadata dicts.

    Each dict has at minimum: name, load_mode, repo_type (list), task_type (list).
    Returns [] if the file does not exist or contains no rule packs.
    """
    path = Path(registry_path) if registry_path is not None else RULE_REGISTRY_PATH
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")

    heading_pattern = re.compile(r"^###\s+(\S+)\s*$", re.MULTILINE)
    yaml_block_pattern = re.compile(r"```yaml\n(.*?)```", re.DOTALL)

    packs: list[dict] = []
    heading_matches = list(heading_pattern.finditer(text))

    for i, heading_match in enumerate(heading_matches):
        pack_name = heading_match.group(1)
        # Slice text from this heading to the next (or end of file)
        segment_start = heading_match.end()
        segment_end = heading_matches[i + 1].start() if i + 1 < len(heading_matches) else len(text)
        segment = text[segment_start:segment_end]

        yaml_match = yaml_block_pattern.search(segment)
        if not yaml_match:
            continue

        pack_data = _parse_yaml_block(yaml_match.group(1))
        pack_data.setdefault("name", pack_name)

        # Normalise list fields
        for field in ("repo_type", "task_type", "risk_level"):
            value = pack_data.get(field)
            if isinstance(value, str):
                pack_data[field] = [value]
            elif not isinstance(value, list):
                pack_data[field] = ["all"]

        packs.append(pack_data)

    return packs


def _matches_trigger(pack: dict, repo_type: str, task_type: str, risk_level: str) -> bool:
    """
    Return True if the pack's trigger conditions are satisfied.

    A condition matches when:
    - The pack list contains "all", OR
    - The provided value appears in the pack list.
    """
    repo_types: list[str] = pack.get("repo_type", ["all"])
    task_types: list[str] = pack.get("task_type", ["all"])
    # risk_level filtering is optional — most packs accept "all"
    risk_levels: list[str] = pack.get("risk_level", ["all"])

    repo_ok = "all" in repo_types or repo_type in repo_types
    task_ok = "all" in task_types or task_type in task_types
    risk_ok = "all" in risk_levels or risk_level in risk_levels

    return repo_ok and task_ok and risk_ok


def filter_rule_packs(
    registry: list[dict],
    repo_type: str,
    task_type: str = "general",
    risk_level: str = "medium",
) -> list[str]:
    """
    Return the list of rule pack names that should be activated for the given context.

    - load_mode=always  → always included (common)
    - load_mode=context_aware → included only when trigger conditions match
    - Other load_modes  → skipped
    """
    active: list[str] = []
    for pack in registry:
        load_mode = pack.get("load_mode", "context_aware")
        name = pack.get("name", "")
        if not name:
            continue
        if load_mode == "always":
            active.append(name)
        elif load_mode == "context_aware":
            if _matches_trigger(pack, repo_type, task_type, risk_level):
                active.append(name)
        # advisory or unknown load_modes are skipped
    return active


_SCAN_EXCLUDED_DIRS = frozenset({
    ".git", "examples", "tests", "fixtures", "docs",
    "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache",
})


def detect_repo_type(project_root: Path) -> str:
    """
    Detect the repo type from project structure signals.

    Returns one of: firmware | product | service | tooling

    Detection priority (first match wins):
      firmware  — CMakeLists.txt present OR .c files present, AND no package.json
      product   — package.json OR .csproj OR .swift present
      service   — requirements.txt or pyproject.toml AND .py files present
      tooling   — fallback default

    Excluded from scan: examples/, tests/, fixtures/, docs/, .git/, node_modules/
    (these directories contain sample files that should not influence detection)
    """
    if not project_root.exists():
        return "tooling"

    # Collect file names and extensions; skip non-source directories.
    all_files = [
        f for f in project_root.rglob("*")
        if f.is_file() and not (_SCAN_EXCLUDED_DIRS & set(f.parts))
    ]
    names = {f.name for f in all_files}
    suffixes = {f.suffix.lower() for f in all_files}

    has_cmake = "CMakeLists.txt" in names
    has_makefile = "Makefile" in names
    has_c_files = ".c" in suffixes
    has_package_json = "package.json" in names
    has_csproj = any(f.suffix.lower() == ".csproj" for f in all_files)
    has_swift = any(f.suffix.lower() == ".swift" for f in all_files)
    has_requirements = "requirements.txt" in names or "pyproject.toml" in names
    has_py = ".py" in suffixes

    # firmware: C/CMake signals without Node.js product signals
    if (has_cmake or has_c_files) and not has_package_json:
        return "firmware"

    # product: Node.js / .NET / Swift project
    if has_package_json or has_csproj or has_swift:
        return "product"

    # service: Python project
    if has_requirements and has_py:
        return "service"

    return "tooling"


# ── Coarse task topic model ───────────────────────────────────────────────────

# Rule packs that are always safe to include regardless of topic.
_UNIVERSAL_PACKS: frozenset[str] = frozenset({
    "common", "refactor", "release", "review_gate",
})

# For each topic, packs that are conclusively NOT relevant.
# Conservative by design: only packs with strong exclusive domain signals go here.
# General language packs (python, cpp, csharp, swift) are NOT denied anywhere;
# they are too generic to exclude for any topic safely.
_TOPIC_DENY_PACKS: dict[str, frozenset[str]] = {
    "general": frozenset(),
    "kernel_driver": frozenset({
        "avalonia", "electron", "nextjs", "typescript", "supabase", "firmware_isr",
    }),
    "firmware": frozenset({
        "avalonia", "electron", "nextjs", "typescript", "supabase",
        "kernel-driver", "kmdf", "wdm", "umdf",
    }),
    "ui_presentation": frozenset({
        "kernel-driver", "kmdf", "wdm", "umdf", "firmware_isr",
    }),
    "api_schema": frozenset({
        "kernel-driver", "kmdf", "wdm", "umdf", "firmware_isr", "avalonia",
    }),
    "runtime_governance": frozenset(),
}

# Keyword patterns (regex, word-boundary-aware) → topic.
# Listed in specificity order; first match wins.
_TASK_TOPIC_KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("kernel_driver", [
        r"\birql\b", r"\birp\b", r"\bdpc\b", r"\bisr\b",
        r"\bwdm\b", r"\bkmdf\b", r"\bumdf\b",
        r"\bkernel.driver\b", r"\bkd-\d+\b", r"\bkstate\b",
    ]),
    ("firmware", [
        r"\bfirmware\b", r"\bembedded\b", r"\brtos\b",
        r"\bflash\b", r"\bdma\b", r"\bbootloader\b",
    ]),
    ("ui_presentation", [
        r"\bavalonia\b", r"\belectron\b", r"\bnextjs?\b",
        r"\bfrontend\b", r"\bcomponent\b", r"\brender(ing)?\b",
        r"\breact\b", r"\bvue\b",
    ]),
    ("runtime_governance", [
        r"\bgovernance\b", r"\bruntime.hook\b",
        r"\baudit\b", r"\bvalidator\b",
    ]),
    ("api_schema", [
        r"\bapi\b", r"\bschema\b", r"\bendpoint\b",
        r"\brest\b", r"\bgraphql\b", r"\bsupabase\b",
    ]),
]

# Explicit rule-name → topic inference (takes precedence over keyword scan).
_PACK_TOPIC_HINTS: dict[str, str] = {
    "kernel-driver": "kernel_driver",
    "kmdf": "kernel_driver",
    "wdm": "kernel_driver",
    "umdf": "kernel_driver",
    "firmware": "firmware",
    "firmware_isr": "firmware",
    "avalonia": "ui_presentation",
    "electron": "ui_presentation",
    "nextjs": "ui_presentation",
    "supabase": "api_schema",
}


def classify_task_topic(
    task_text: str = "",
    requested_rules: list[str] | None = None,
) -> str:
    """
    Return a coarse topic label for a given task.

    Priority:
    1. If any requested rule pack strongly implies a domain, use that topic.
    2. Scan task_text for keyword signals.
    3. Default to 'general' (no filtering).
    """
    # 1. Explicit rule-name inference
    for pack in (requested_rules or []):
        hint = _PACK_TOPIC_HINTS.get(pack)
        if hint:
            return hint

    # 2. Keyword scan
    text_lower = task_text.lower()
    for topic, patterns in _TASK_TOPIC_KEYWORD_RULES:
        for pattern in patterns:
            if re.search(pattern, text_lower):
                return topic

    return "general"


def filter_rules_by_topic(
    requested_rules: list[str],
    task_topic: str,
) -> tuple[list[str], list[str]]:
    """
    Remove rule packs that are conclusively not relevant for the given task_topic.

    Returns:
        (active_rules, filtered_out_rules)

    Design (conservative denylist):
    - topic='general' or unknown → no filtering; all rules pass through
    - Universal packs (common, refactor, release, review_gate) always pass
    - Packs in _TOPIC_DENY_PACKS[topic] are filtered out
    - All other packs pass — general language packs (python, cpp, csharp, swift)
      are never denied because they have no strong exclusive domain affinity
    """
    if task_topic == "general" or task_topic not in _TOPIC_DENY_PACKS:
        return list(requested_rules), []

    deny = _TOPIC_DENY_PACKS[task_topic] - _UNIVERSAL_PACKS  # never deny universal packs
    active = [p for p in requested_rules if p not in deny]
    filtered_out = [p for p in requested_rules if p in deny]
    return active, filtered_out
