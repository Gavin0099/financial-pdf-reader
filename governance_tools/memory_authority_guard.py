#!/usr/bin/env python3
"""
Memory Authority Guard — Phase 1 (warning mode, non-blocking)

Checks that memory entries are properly bound to traceable sources.

Two memory types:
  - session-derived (daily files: memory/YYYY-MM-DD.md)
      Binding requirement: commit_hash (resolved, not "pending"/"UNCOMMITTED") OR session_id
  - structural long-term (memory/00_long_term.md)
      Binding requirement: promoted_by marker in each ## section

Checks:
  1. unbound_memory              — daily entry lacks commit_hash + session_id
  2. structural_memory_auto_write — 00_long_term.md section lacks promoted_by
  3. private_memory_cited        — closeout artifact cites .claude private memory path
  4. missing_canonical_memory   — commits in git log but no daily memory file

Phase 1: warnings only. Exit code always 0. JSON to stdout.

See: governance/MEMORY_AUTHORITY_CONTRACT.md
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── regex patterns ────────────────────────────────────────────────────────────

# Match both human-written ("commit hash:") and auto-generated ("commit:") entry formats.
# A real hash is 5-40 hex chars.
_ENTRY_SPLIT = re.compile(r'(?m)^(?=- (?:memory_type|what[_ ]changed):)')
_COMMIT_RESOLVED = re.compile(
    r'commit(?:\s+hash)?:\s*`?([a-f0-9]{5,40})`?', re.IGNORECASE
)
_COMMIT_PENDING = re.compile(
    r'commit(?:\s+hash)?:\s*pending', re.IGNORECASE
)
_COMMIT_UNCOMMITTED = re.compile(
    r'commit(?:\s+hash)?:\s*UNCOMMITTED', re.IGNORECASE
)
_SESSION_ID = re.compile(r'session[_\s]id:\s*(\S+)', re.IGNORECASE)
_MEMORY_TYPE = re.compile(r'memory_type:\s*(\S+)', re.IGNORECASE)
_WRITER = re.compile(r'writer:\s*(\S+)', re.IGNORECASE)
_RECORD_FORMAT_VERSION = re.compile(r'record_format_version:\s*(\S+)', re.IGNORECASE)
_PROMOTED_BY = re.compile(r'promoted_by:', re.IGNORECASE)
_PROMOTION_STATUS = re.compile(r'<!--\s*promotion_status:\s*(\w+)', re.IGNORECASE)
_SECTION_H2 = re.compile(r'^## ', re.MULTILINE)
_PRIVATE_MEMORY_PATH = re.compile(
    r'[Cc]:\\[Uu]sers\\[^\\]+\\.claude\\projects', re.IGNORECASE
)
_CANONICAL_MEMORY_WRITER = "governance_tools.memory_record"

# Daily files dated on or after this date are required to use canonical writer format.
# Before this date, old-format entries (- what changed:) are grandfathered.
# Set to the day after canonical writer was committed (2026-04-30 commit 6d77f2d).
_CANONICAL_WRITER_REQUIRED_FROM = "2026-05-01"

# ── helpers ───────────────────────────────────────────────────────────────────

_DATE_FILENAME = re.compile(r'^\d{4}-\d{2}-\d{2}\.md$')


def _is_daily_file(path: Path) -> bool:
    return _DATE_FILENAME.match(path.name) is not None


def _entry_is_bound(block: str) -> tuple[bool, str]:
    """
    Returns (is_bound, reason).

    Binding rules (Memory Authority Contract v1.0.0):
      - Real commit hash (not "pending"/"UNCOMMITTED")  → bound
      - session_id field present                        → bound (valid fallback)
      - commit hash: pending, no session_id             → unbound (VIOLATION)
      - commit: UNCOMMITTED, no session_id              → unbound (VIOLATION)
      - no hash field, no session_id                    → unbound (VIOLATION)
    """
    has_real_hash = bool(_COMMIT_RESOLVED.search(block))
    has_session_id = bool(_SESSION_ID.search(block))
    has_pending = bool(_COMMIT_PENDING.search(block))
    has_uncommitted = bool(_COMMIT_UNCOMMITTED.search(block))

    # Real hash takes precedence
    if has_real_hash:
        return True, "ok"
    # session_id is a valid fallback binding regardless of commit state
    if has_session_id:
        return True, "ok"
    # Distinguish why there's no binding
    if has_pending:
        return False, "commit_hash_pending_no_session_id"
    if has_uncommitted:
        return False, "commit_uncommitted_no_session_id"
    return False, "no_anchor"


def _snippet(block: str, length: int = 80) -> str:
    first_line = block.strip().split('\n')[0]
    return first_line[:length]


# ── check functions ───────────────────────────────────────────────────────────

def check_daily_memory(
    memory_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """
    Check 1: unbound_memory
    Scan all daily memory files; report entries lacking commit_hash + session_id.

    Returns (violations, coverage_stats).
    coverage_stats: {"total_entries": N, "bound_entries": M}
    """
    violations: list[dict[str, Any]] = []
    total_entries = 0
    bound_entries = 0

    daily_files = sorted(
        p for p in memory_root.glob('*.md') if _is_daily_file(p)
    )
    for fpath in daily_files:
        try:
            text = fpath.read_text(encoding='utf-8')
        except Exception as exc:
            violations.append({
                'code': 'unbound_memory',
                'severity': 'warning',
                'file': str(fpath.name),
                'entry': None,
                'reason': f'read_error: {exc}',
            })
            continue

        entries = _ENTRY_SPLIT.split(text)
        for block in entries:
            stripped = block.strip()
            if not (
                stripped.startswith('- what changed:')
                or stripped.startswith('- what_changed:')
                or stripped.startswith('- memory_type:')
            ):
                continue
            total_entries += 1
            bound, reason = _entry_is_bound(block)
            if bound:
                bound_entries += 1
            else:
                violations.append({
                    'code': 'unbound_memory',
                    'severity': 'warning',
                    'file': str(fpath.name),
                    'entry': _snippet(block),
                    'reason': reason,
                })

            memory_type_match = _MEMORY_TYPE.search(block)
            memory_type = (memory_type_match.group(1).strip().lower() if memory_type_match else "")
            writer_match = _WRITER.search(block)
            writer = (writer_match.group(1).strip() if writer_match else "")
            has_format_version = bool(_RECORD_FORMAT_VERSION.search(block))

            if memory_type in {"session-derived", "session_derived"}:
                # Explicit canonical format: verify writer and version.
                if writer != _CANONICAL_MEMORY_WRITER or not has_format_version:
                    violations.append({
                        'code': 'non_canonical_writer',
                        'severity': 'warning',
                        'file': str(fpath.name),
                        'entry': _snippet(block),
                        'reason': 'session_derived_entry_not_written_by_memory_record',
                    })
            elif not memory_type and fpath.name >= _CANONICAL_WRITER_REQUIRED_FROM:
                # Old-format entry (- what changed:) in a file after the canonical writer
                # cutoff date. These bypass the canonical writer and evade non_canonical_writer
                # detection because they lack the memory_type header.
                # Grandfathered for files before _CANONICAL_WRITER_REQUIRED_FROM.
                violations.append({
                    'code': 'non_canonical_writer',
                    'severity': 'warning',
                    'file': str(fpath.name),
                    'entry': _snippet(block),
                    'reason': 'old_format_entry_after_canonical_writer_cutoff — use memory_record.append_session_derived_entry()',
                })

    coverage = {'total_entries': total_entries, 'bound_entries': bound_entries}
    return violations, coverage


def _parse_promotion_status(section_text: str) -> str:
    """
    Extract promotion_status from HTML comment markers.
    Returns one of: authoritative / candidate / stale / rejected / none
    See: governance/STRUCTURAL_PROMOTION_CONTRACT.md
    """
    m = _PROMOTION_STATUS.search(section_text)
    if not m:
        return 'none'
    return m.group(1).lower().strip()


def check_structural_memory(
    memory_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """
    Check 2: structural_memory_auto_write
    Scan 00_long_term.md for ## sections; classify by promotion_status marker.

    Violation severity per state (STRUCTURAL_PROMOTION_CONTRACT.md):
      none         → warning (missing_marker — section not yet reviewed)
      candidate    → info   (not_yet_authoritative — AI-proposed, awaiting human)
      stale        → warning (stale_section — needs update before use)
      rejected     → info   (rejected_section — do not cite)
      authoritative without promoted_by → warning (missing_promoted_by)
      authoritative with promoted_by    → CLEAR (counts toward coverage rate)

    Returns (violations, coverage_stats).
    coverage_stats: {"total_sections": N, "promoted_sections": M}
    """
    long_term = memory_root / '00_long_term.md'
    if not long_term.exists():
        return [], {'total_sections': 0, 'promoted_sections': 0}

    try:
        text = long_term.read_text(encoding='utf-8')
    except Exception as exc:
        return (
            [{'code': 'structural_memory_auto_write', 'severity': 'info',
              'file': '00_long_term.md', 'section': None,
              'reason': f'read_error: {exc}'}],
            {'total_sections': 0, 'promoted_sections': 0},
        )

    raw_sections = _SECTION_H2.split(text)
    violations: list[dict[str, Any]] = []
    total_sections = 0
    promoted_sections = 0

    for section in raw_sections:
        if not section.strip():
            continue
        # Skip preamble (content before first ## heading)
        first_line = section.split('\n')[0].strip()
        if first_line.startswith('#'):
            continue
        total_sections += 1
        heading_line = '## ' + first_line
        promotion_status = _parse_promotion_status(section)
        has_promoted_by = bool(_PROMOTED_BY.search(section))

        if promotion_status == 'authoritative' and has_promoted_by:
            promoted_sections += 1
            # CLEAR — no violation
        elif promotion_status == 'authoritative' and not has_promoted_by:
            violations.append({
                'code': 'structural_memory_auto_write',
                'severity': 'warning',
                'file': '00_long_term.md',
                'section': heading_line[:80],
                'promotion_status': promotion_status,
                'reason': 'missing_promoted_by',
            })
        elif promotion_status == 'candidate':
            violations.append({
                'code': 'structural_memory_auto_write',
                'severity': 'info',
                'file': '00_long_term.md',
                'section': heading_line[:80],
                'promotion_status': promotion_status,
                'reason': 'not_yet_authoritative',
            })
        elif promotion_status == 'stale':
            violations.append({
                'code': 'structural_memory_auto_write',
                'severity': 'warning',
                'file': '00_long_term.md',
                'section': heading_line[:80],
                'promotion_status': promotion_status,
                'reason': 'stale_section',
            })
        elif promotion_status == 'rejected':
            violations.append({
                'code': 'structural_memory_auto_write',
                'severity': 'info',
                'file': '00_long_term.md',
                'section': heading_line[:80],
                'promotion_status': promotion_status,
                'reason': 'rejected_section',
            })
        else:
            # promotion_status == 'none' — no marker at all
            violations.append({
                'code': 'structural_memory_auto_write',
                'severity': 'warning',
                'file': '00_long_term.md',
                'section': heading_line[:80],
                'promotion_status': 'none',
                'reason': 'missing_marker',
            })

    coverage = {
        'total_sections': total_sections,
        'promoted_sections': promoted_sections,
    }
    return violations, coverage


def check_private_memory_cited(project_root: Path) -> list[dict[str, Any]]:
    """
    Check 3: private_memory_cited
    Scan closeout artifacts for references to the private .claude memory path.
    """
    violations: list[dict[str, Any]] = []
    artifacts_root = project_root / 'artifacts'
    if not artifacts_root.exists():
        return violations

    for json_file in artifacts_root.rglob('*.json'):
        try:
            text = json_file.read_text(encoding='utf-8')
        except Exception:
            continue
        if _PRIVATE_MEMORY_PATH.search(text):
            violations.append({
                'code': 'private_memory_cited',
                'severity': 'warning',
                'file': str(json_file.relative_to(project_root)),
                'reason': 'closeout_artifact_cites_private_claude_memory_path',
            })
    return violations


def check_missing_canonical_memory(
    memory_root: Path, project_root: Path
) -> list[dict[str, Any]]:
    """
    Check 4: missing_canonical_memory
    Infer dates with git activity; report dates that lack a daily memory file.
    Heuristic — uses git log; may produce false positives on no-commit sessions.
    """
    violations: list[dict[str, Any]] = []
    try:
        result = subprocess.run(
            ['git', 'log', '--format=%as', '--since=30 days ago'],
            capture_output=True, text=True, cwd=str(project_root), timeout=10
        )
        if result.returncode != 0:
            return violations
        commit_dates = set(result.stdout.strip().splitlines())
    except Exception:
        return violations  # skip check if git not available

    existing_dates = {
        p.stem for p in memory_root.glob('*.md') if _is_daily_file(p)
    }
    for date_str in sorted(commit_dates):
        if date_str and date_str not in existing_dates:
            violations.append({
                'code': 'missing_canonical_memory',
                'severity': 'warning',
                'date': date_str,
                'reason': 'git_commits_exist_but_no_daily_memory_file',
            })
    return violations


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


# ── aggregate ─────────────────────────────────────────────────────────────────

def run_guard(
    memory_root: Path,
    project_root: Path,
    *,
    skip_git: bool = False,
) -> dict[str, Any]:
    """
    Run all four checks and return structured JSON result.
    Phase 1: always warning mode; all violations are non-blocking.
    """
    violations: list[dict[str, Any]] = []

    daily_violations, daily_coverage = check_daily_memory(memory_root)
    violations.extend(daily_violations)

    structural_violations, structural_coverage = check_structural_memory(memory_root)
    violations.extend(structural_violations)

    violations.extend(check_private_memory_cited(project_root))
    if not skip_git:
        violations.extend(check_missing_canonical_memory(memory_root, project_root))

    counts: dict[str, int] = {}
    for v in violations:
        counts[v['code']] = counts.get(v['code'], 0) + 1

    # Authority Coverage Rate — key metric: what fraction of memory is actually bound?
    session_total = daily_coverage['total_entries']
    session_bound = daily_coverage['bound_entries']
    struct_total = structural_coverage['total_sections']
    struct_promoted = structural_coverage['promoted_sections']

    authority_coverage_rate = {
        'session_derived': {
            'total_entries': session_total,
            'bound_entries': session_bound,
            'rate': _safe_rate(session_bound, session_total),
        },
        'structural': {
            'total_sections': struct_total,
            'promoted_sections': struct_promoted,
            'rate': _safe_rate(struct_promoted, struct_total),
        },
    }

    return {
        'guard': 'memory_authority_guard',
        'version': '1.2.0',
        'contract': 'governance/MEMORY_AUTHORITY_CONTRACT.md',
        'phase': 'phase1',
        'mode': 'warning',
        'ok': True,  # Phase 1: always ok (non-blocking)
        'violation_count': len(violations),
        'violation_counts_by_code': counts,
        'authority_coverage_rate': authority_coverage_rate,
        'violations': violations,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def _human_summary(result: dict[str, Any]) -> str:
    n = result['violation_count']
    counts = result['violation_counts_by_code']
    acr = result.get('authority_coverage_rate', {})
    sd = acr.get('session_derived', {})
    st = acr.get('structural', {})
    sd_rate = sd.get('rate')
    st_rate = st.get('rate')
    coverage_str = (
        f"session_authority_rate={sd_rate if sd_rate is not None else 'n/a'} "
        f"structural_authority_rate={st_rate if st_rate is not None else 'n/a'}"
    )
    if n == 0:
        return f'memory authority: ok (no violations) | {coverage_str}'
    parts = [f"{k}={v}" for k, v in sorted(counts.items())]
    return (
        f'memory authority: {n} warning(s) [{", ".join(parts)}] (phase1=non-blocking) '
        f'| {coverage_str}'
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description='Memory Authority Guard — Phase 1 warning mode'
    )
    parser.add_argument(
        '--memory-root',
        default='memory',
        help='Path to memory/ directory (default: memory)',
    )
    parser.add_argument(
        '--project-root',
        default='.',
        help='Path to project root (default: .)',
    )
    parser.add_argument(
        '--skip-git',
        action='store_true',
        help='Skip missing_canonical_memory check (no git required)',
    )
    parser.add_argument(
        '--format',
        choices=['json', 'text'],
        default='text',
        help='Output format (default: text)',
    )
    args = parser.parse_args(argv)

    memory_root = Path(args.memory_root)
    project_root = Path(args.project_root)

    if not memory_root.exists():
        print(f'error: memory root not found: {memory_root}', file=sys.stderr)
        sys.exit(1)

    result = run_guard(memory_root, project_root, skip_git=args.skip_git)

    if args.format == 'json':
        print(json.dumps(result, indent=2))
    else:
        summary = _human_summary(result)
        print(summary)
        if result['violations']:
            for v in result['violations']:
                code = v['code']
                sev = v.get('severity', 'warning')
                detail = v.get('entry') or v.get('section') or v.get('date') or v.get('file', '')
                reason = v.get('reason', '')
                print(f'  [{sev}] {code}: {detail!r} -- {reason}')

    # Phase 1: always exit 0 (warning mode)
    sys.exit(0)


if __name__ == '__main__':
    main()
