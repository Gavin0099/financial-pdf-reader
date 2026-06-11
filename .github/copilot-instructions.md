# Copilot Workspace Instructions
<!-- AI Governance Framework: copilot-instructions v1.0 -->
<!-- Source: ai-governance-framework/governance/copilot-instructions-template.md -->
<!-- Deploy via: bash scripts/install-hooks.sh --target /path/to/repo -->

## DONE Boundary Rules (MANDATORY)

### Rule 1: Hard Stop After DONE

When the defined DONE condition is met, stop immediately.

Do NOT automatically continue into:
- full regression or broad smoke validation
- governance artifact chains (triage → decision → contract → gate → acceptance → freeze)
- commit, push, closeout, or status rollup
- inspection of unrelated dirty or untracked files

Report next options only. Wait for explicit instruction.

### Rule 2: Scope-Matched Validation

Run targeted validation first (the test file for the changed module only).

Do NOT upgrade to full regression or broader smoke unless:
- the DONE definition explicitly requires it, OR
- the user explicitly requests it

When broader validation fails: report the failure and classification in ONE message, then stop.
Do not build triage/decision/contract chains from a broader validation failure.

### Rule 3: Dirty Tree Allowlist

When the working tree is dirty, produce a concise `git status` summary only.

Stage only files explicitly listed by the user or required by the DONE scope.
Do not read, explain, stage, or modify unrelated dirty or untracked files.

### Rule 4: Structured Report Format

When reporting task completion, use this exact format. Fixed vocabulary only — no free-form narrative in these fields.

Event-driven response envelope:
- When using a `mode` field, follow `governance/RESPONSE_ENVELOPE_CONTRACT.md`.
- `mode` must be event-derived, not agent-selected.
- Keep `mode_source`, `task_authority`, `scope`, `done`, `not_claimed`, `evidence_refs`, and `risk` separate.
- `task_authority` distinguishes authorized work from autonomous expansion.
- `evidence_refs` records commands, artifacts, or reviewer sources supporting the DONE claim; it does not upgrade semantic authority.
- Do not replace claim ceiling or risk disclosure with confidence scores, effort estimates, or broad impact analysis.

Vocabulary definitions:
- `NOT PRESENT` = the mechanism, artifact, or enforcement does not exist
- `NOT CLAIMED` = the capability or conclusion is not being asserted this session
- `PASS` = must always include `— <command or source>` (never bare)

**Language rule:** Content language must match the session language. Sub-field labels (`structural`, `build`, `semantic`, `behavioral`, `ext evidence`, `scope drift`, `claim inflation`, `evidence maturity`) and fixed vocabulary tokens (`PASS`, `FAIL`, `NOT RUN`, `NOT CLAIMED`, `NOT PRESENT`) remain in English regardless of session language. Section headers may be translated.

English format:
```
Validation:
- structural:    PASS — <command> | FAIL — <command> | NOT RUN
- build:         PASS — <command> | FAIL — <command> | NOT RUN
- semantic:      NOT CLAIMED | PASS — human review: [reviewer/date]
- behavioral:    NOT PRESENT | verified — [how]
- ext evidence:  NOT PRESENT | [source and scope]

Risk:
- scope drift:        none | [description]
- claim inflation:    none | [description]
- evidence maturity:  [one line]

Incidental cleanup:   none | file=[path] reason=[why] semantic_change=no

Cannot claim this session:
- [list what was NOT validated, NOT verified, NOT proven]
```

Chinese format (when session language is Chinese):
```
驗證：
- structural:    PASS — <指令> | FAIL — <指令> | NOT RUN
- build:         PASS — <指令> | FAIL — <指令> | NOT RUN
- semantic:      NOT CLAIMED | PASS — 人工審查：[審查者/日期]
- behavioral:    NOT PRESENT | 已驗證 — [如何]
- ext evidence:  NOT PRESENT | [來源與範圍]

風險：
- scope drift:        none | [說明]
- claim inflation:    none | [說明]
- evidence maturity:  [一行說明]

附帶清理：   none | file=[路徑] reason=[原因] semantic_change=no

本次無法宣告：
- [列出未驗證、未確認、未證明的項目]
```

Do NOT omit `Cannot claim` / `本次無法宣告`. It is required in every completion report.

**Examples:**

Schema-only change (markdown, no runtime):
```
Validation:
- structural:    PASS — grep section_refs *.md
- build:         NOT RUN — markdown-only change
- semantic:      NOT CLAIMED
- behavioral:    NOT PRESENT
- ext evidence:  NOT PRESENT
Risk:
- scope drift:        none
- claim inflation:    none
- evidence maturity:  structural layer only; no semantic verification
Incidental cleanup:   none
Cannot claim this session:
- semantic correctness of section references
- PDF-level content verification
```

Pilot attachment change (build pass, no semantic verification):
```
Validation:
- structural:    PASS — validate_wiki_frontmatter
- build:         PASS — npm.cmd run build (exit 0)
- semantic:      NOT CLAIMED
- behavioral:    NOT PRESENT
- ext evidence:  NOT PRESENT
Risk:
- scope drift:        none — pilot limited to 4 existing entries
- claim inflation:    none — claim_level unchanged (inferred)
- evidence maturity:  build-verified only; high-risk coverage below original plan
Incidental cleanup:   none
Cannot claim this session:
- bit-level semantic verification of attached spec sections
- high-risk boundary condition coverage (PORT_OVER_CURRENT not in pilot)
- verified status upgrade
```

Failed / partial validation:
```
Validation:
- structural:    PASS — validate_wiki_frontmatter
- build:         FAIL — npm.cmd run build (exit 1, see error above)
- semantic:      NOT CLAIMED
- behavioral:    NOT PRESENT
- ext evidence:  NOT PRESENT
Risk:
- scope drift:        none
- claim inflation:    none — task not complete
- evidence maturity:  build failure; no completion evidence
Incidental cleanup:   none
Cannot claim this session:
- task complete
- any validation above build layer
```
