# AGENTS.md Minimum Standard for repo_specific Classification

Reviewed: 2026-05-25
Authority: Gavin0099

## Purpose

Defines the minimum bar that an AGENTS.md must clear to be classified as
`repo_specific_minimal` (or better) by `agents_calibration_maturity.py`.
This standard governs what counts as a structural fix versus a mechanical fix.

## Pre-condition (not counted in pass/fail)

AGENTS.md must contain a repo purpose description. This is not a judgment
criterion — it is a readability baseline that any non-scaffold file should have.

## Judgment Conditions (ALL must pass)

### 1. Observable trigger condition in `when_to_use` (or risk_levels / escalation_triggers)

At least one governance section must contain a line that includes a
**concretely observable trigger**: a file path, directory name, file extension,
operation verb, or commit message pattern.

**Accepted** (triggers `_PATHLIKE_RE`, `_FILELIKE_RE`, `_COMMAND_RE`, or `_SEQUENCE_RE`):
- `GLISPDockingBCGEndUser/` (path with slash)
- `GLHubUpdateTool.cpp` (file with recognized extension)
- `` `Build.bat` `` (backtick-wrapped command)
- `ISP write → device memory` (sequence boundary)

**Not accepted** (generic, no observable anchor):
- "when working on this repo"
- "important code paths"
- "run tests before merge"

Implementation note: the code checks `_line_signal()` which runs four regex
patterns. Any one match on any non-placeholder line is sufficient.

### 2. Scope boundary in `must_test_paths` or `risk_levels`

At least one governance section must define a **scope boundary**: a specific
directory, file type, or domain range that limits where an agent applies.

Scope is mandatory (not optional). A file list alone without scope context
is insufficient — the boundary must be implied or explicit (e.g., "only
changes to `CommonDLL/` require cross-tool regression").

### 3. Anti-copy-paste: content must be repo-unique

AGENTS.md content in the governance key sections must be **demonstrably
specific to this repo**. Content that could apply unchanged to any other
repo in the fleet fails this condition.

Enforcement: before accepting a structural fix, manually compare the filled
sections against at least one other repo's AGENTS.md. If the content is
interchangeable, reject it and require repo-local specifics.

This is the primary defense against mechanical batch-generation of AGENTS.md
files that pass the signal test but carry no real governance information.

## Status mapping

| `agents_calibration_maturity.py` status | `agents_repo_specific` in matrix |
|---|---|
| `scaffold_only` | N |
| `generic_filled` | N |
| `repo_specific_minimal` | Y (passes all 3 conditions above) |
| `reviewer_verified` | Y (passes + explicit reviewer marker) |

## Relationship to matrix classification

`agents_repo_specific = Y` is one of three candidate signals. A repo needs
all three (hooks_ready + framework_version_known + agents_repo_specific) to
reach candidate status, and candidate + dirty_explainable + evidence + head +
timestamp to reach verified status.
