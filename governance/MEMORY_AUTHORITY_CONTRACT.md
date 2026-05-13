# Memory Authority Contract

> Version: 1.0.0
> Written: 2026-04-30
> Status: ACTIVE — Phase 1 (warning mode, non-blocking)
> Authority: Memory Authority Enforcement Plan v0.3 (session 2026-04-30)

---

## Purpose

This contract defines what makes a memory entry a **binding authority** versus an
unverifiable claim. Presence in `repo/memory/` is **necessary but not sufficient**.

A memory entry that lacks a traceable anchor can be contradicted without audit
trail, silently drift from reality, or be cited in governance decisions without
verifiable origin.

---

## 1. Two Memory Types

### 1.1 Session-Derived Memory

**Definition**: Daily files — `memory/YYYY-MM-DD.md` — recording what changed
in a specific session.

**Binding requirement**: Each entry (bullet block starting with `- what changed:`)
MUST contain at least one of:
- `commit hash: <resolved-hash>` — a real 5–40 hex character git hash,
  NOT the string `pending`
- `session_id: <id>` — an explicit session identifier

**Why**: Session-derived memory claims specific changes happened. Without a
commit hash or session ID, the claim cannot be independently verified. An
unresolved `commit hash: pending` means the memory record diverged from reality
at write time and was never closed.

**Violation code**: `unbound_memory`
**Scope**: every bullet entry in every daily memory file

### 1.2 Structural Long-Term Memory

**Definition**: `memory/00_long_term.md` — persistent facts, conventions, and
governance state that span sessions.

**Binding requirement**: Each `##`-level section SHOULD carry a
`promoted_by:` marker indicating who (human reviewer or promotion artifact)
authorized the entry.

Acceptable forms:
```
<!-- promoted_by: Gavin0099 / 2026-04-28 -->
<!-- promoted_by: phase_d_closeout / artifacts/governance/phase-d-reviewer-closeout.json -->
```

**Why**: Structural memory is cited as authority across sessions and by multiple
agents. Entries written without promotion authority are `structural_memory_auto_write` —
AI-inserted facts treated as governance authority without human review.

**Violation code**: `structural_memory_auto_write`
**Scope**: ##-level sections in `memory/00_long_term.md`
**Phase 1 mode**: reported as debt count, not per-section blocking

---

## 2. Presence vs. Binding

> Presence in `repo/memory/` = necessary for cross-agent visibility.
> Binding = traceable to a commit, session, or human reviewer.
> Presence alone does NOT grant authority.

A file in `repo/memory/` that lacks binding markers is **unanchored memory**.
It may be accurate, but it cannot be cited in a governance decision or used
to override a human-authored artifact without manual verification.

Private tool memory (e.g. `C:\Users\..\.claude\projects\..\memory\MEMORY.md`)
is **not cross-agent canonical** under any conditions. Closeouts or governance
artifacts that cite the private tool memory path as authoritative are invalid.

**Violation code**: `private_memory_cited`

---

## 3. Missing Canonical Memory

If session-level work is performed (commits exist, artifacts written) but no
corresponding daily memory file exists for that date, the session record is
incomplete.

**Violation code**: `missing_canonical_memory`
**Detection**: guard checks whether a daily memory file exists for dates where
git log shows recent commits. Heuristic — false positives possible on no-commit
sessions.

---

## 4. Violation Semantics (Phase 1)

| Code | Severity | Blocks | Meaning |
|------|----------|--------|---------|
| `unbound_memory` | warning | no | Daily entry lacks commit_hash + session_id |
| `structural_memory_auto_write` | info | no | 00_long_term.md section lacks promoted_by |
| `private_memory_cited` | warning | no | Closeout cites private .claude memory path |
| `missing_canonical_memory` | warning | no | Commits exist but no daily memory file |

**Phase 1 = warning + structured JSON output. Does NOT block any operation.**

Phase 2 upgrade path: switch `unbound_memory` to blocking gate on promotion
decisions (memory_janitor, session_end promotion step).

---

## 5. Amendment

To change this contract: create a new version (1.1.0, 2.0.0) with:
- Name of what changed
- Rationale
- Evidence (why the change is needed)
- Updated violation semantics table

Silent modification = authority contract violation.

---

## 6. Tool Reference

- Guard implementation: `governance_tools/memory_authority_guard.py`
- Invocation: `python governance_tools/memory_authority_guard.py --memory-root memory/`
- Output: structured JSON to stdout; human summary to stderr
- Phase 1 exit codes: always 0 (warning mode)
