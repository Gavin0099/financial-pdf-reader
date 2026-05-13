#!/usr/bin/env python3
"""
Assess repo-specific AGENTS.md calibration maturity without turning it into a hard gate.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


_GOVERNANCE_KEY_RE = re.compile(r"<!--\s*governance:key=(\S+)\s*-->")
_COMMENT_START_RE = re.compile(r"<!--")
_COMMENT_END_RE = re.compile(r"-->")
_PATHLIKE_RE = re.compile(r"(?:^|[\s`])(?:[\w.-]+[\\/])+[\w.*-]+")
_FILELIKE_RE = re.compile(r"\b[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|cs|java|kt|cpp|c|h|hpp|md|yaml|yml|json|toml|ini|sh)\b")
_COMMAND_RE = re.compile(
    r"(`[^`]+`|\b(?:pytest|npm|pnpm|yarn|cargo|go test|dotnet test|python -m|python |make |tox|uv run|ruff|mypy)\b)",
    re.IGNORECASE,
)
_SEQUENCE_RE = re.compile(r"\b[\w.-]+\s*(?:->|→)\s*[\w.-]+\b")
_PLACEHOLDER_RE = re.compile(r"^n/?a(?:\b|$)", re.IGNORECASE)
_GENERIC_PHRASES = (
    "important code",
    "critical paths",
    "don't break production",
    "do not break production",
    "run tests before merge",
    "public api changes",
    "database schema changes",
    "external dependencies",
)
_REVIEW_MARKERS = (
    "<!-- governance:reviewer_verified -->",
    "<!-- reviewer_verified -->",
)
_CALIBRATION_PROMPTS = [
    "Which single repo path is most dangerous to break?",
    "Which concrete command or test proves that path still works?",
    "Which class of changes in this repo must escalate to L2?",
    "Which shortcut is absolutely forbidden in this repo?",
]


@dataclass
class AgentsCalibrationMaturity:
    status: str
    reason: str
    path: str | None
    section_states: dict[str, str] = field(default_factory=dict)
    repo_specific_signals: list[str] = field(default_factory=list)
    reviewer_signal: str | None = None
    next_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_governance_sections(text: str) -> dict[str, list[str]]:
    lines = text.splitlines()
    sections: dict[str, list[str]] = {}
    i = 0
    while i < len(lines):
        match = _GOVERNANCE_KEY_RE.match(lines[i].strip())
        if not match:
            i += 1
            continue
        key = match.group(1)
        i += 1
        content: list[str] = []
        in_comment = False
        while i < len(lines) and not lines[i].strip().startswith("##"):
            raw = lines[i]
            stripped = raw.strip()
            i += 1
            if not stripped:
                continue
            if in_comment:
                if _COMMENT_END_RE.search(stripped):
                    in_comment = False
                continue
            if _COMMENT_START_RE.match(stripped):
                if not _COMMENT_END_RE.search(stripped):
                    in_comment = True
                continue
            content.append(stripped)
        sections[key] = content
    return sections


def _is_placeholder_line(line: str) -> bool:
    normalized = line.strip()
    if not normalized:
        return True
    if _PLACEHOLDER_RE.match(normalized):
        return True
    return False


def _line_signal(line: str) -> str | None:
    if _PATHLIKE_RE.search(line) or _FILELIKE_RE.search(line):
        return f"path_or_file:{line}"
    if _COMMAND_RE.search(line):
        return f"command:{line}"
    if _SEQUENCE_RE.search(line):
        return f"sequence_boundary:{line}"
    return None


def _looks_generic(line: str) -> bool:
    lowered = line.lower()
    return any(phrase in lowered for phrase in _GENERIC_PHRASES)


def _reviewer_signal(repo_root: Path, agents_text: str) -> str | None:
    for marker in _REVIEW_MARKERS:
        if marker in agents_text:
            return "agents_comment_marker"

    review_path = repo_root / ".governance" / "agents_calibration_review.json"
    if not review_path.exists():
        return None

    try:
        payload = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if payload.get("status") == "reviewer_verified" or payload.get("reviewer_verified") is True:
        return str(review_path)
    return None


def assess_agents_calibration_maturity(repo_root: Path) -> AgentsCalibrationMaturity:
    repo_root = repo_root.resolve()
    agents_path = repo_root / "AGENTS.md"
    if not agents_path.exists():
        return AgentsCalibrationMaturity(
            status="scaffold_only",
            reason="agents_md_missing",
            path=None,
            next_questions=list(_CALIBRATION_PROMPTS),
        )

    text = agents_path.read_text(encoding="utf-8")
    sections = _parse_governance_sections(text)
    if not sections:
        return AgentsCalibrationMaturity(
            status="scaffold_only",
            reason="governance_key_sections_missing",
            path=str(agents_path),
            next_questions=list(_CALIBRATION_PROMPTS),
        )

    section_states: dict[str, str] = {}
    meaningful_lines: list[str] = []
    generic_lines: list[str] = []
    repo_specific_signals: list[str] = []

    for key, lines in sections.items():
        real_lines = [line for line in lines if not _is_placeholder_line(line)]
        if not real_lines:
            section_states[key] = "placeholder_only"
            continue
        section_states[key] = "filled"
        meaningful_lines.extend(real_lines)
        for line in real_lines:
            signal = _line_signal(line)
            if signal:
                repo_specific_signals.append(signal)
            elif _looks_generic(line):
                generic_lines.append(line)

    reviewer_signal = _reviewer_signal(repo_root, text)

    if not meaningful_lines:
        return AgentsCalibrationMaturity(
            status="scaffold_only",
            reason="all_key_sections_are_NA",
            path=str(agents_path),
            section_states=section_states,
            reviewer_signal=reviewer_signal,
            next_questions=list(_CALIBRATION_PROMPTS),
        )

    if repo_specific_signals:
        status = "reviewer_verified" if reviewer_signal else "repo_specific_minimal"
        reason = (
            "reviewer_verified_signal_present"
            if reviewer_signal
            else "repo_local_paths_commands_or_boundaries_detected"
        )
        return AgentsCalibrationMaturity(
            status=status,
            reason=reason,
            path=str(agents_path),
            section_states=section_states,
            repo_specific_signals=repo_specific_signals,
            reviewer_signal=reviewer_signal,
        )

    return AgentsCalibrationMaturity(
        status="generic_filled",
        reason="no_repo_local_paths_commands_or_boundaries_detected",
        path=str(agents_path),
        section_states=section_states,
        reviewer_signal=reviewer_signal,
        next_questions=list(_CALIBRATION_PROMPTS),
    )
