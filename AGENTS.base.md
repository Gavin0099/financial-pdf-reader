# AGENTS.base.md
<!-- governance-baseline: protected -->
<!-- baseline_version: 1.0.0 -->
<!-- DO NOT EDIT — managed by ai-governance-framework -->
<!-- To add repo-specific rules, create AGENTS.md and extend this file's sections. -->
<!-- Hash is recorded in .governance/baseline.yaml and verified on every drift check. -->

## Level Alignment

- Declared L0 but involves domain logic, boundary crossing, or behavior change → upgrade to L1
- Declared L1 but involves core domain, security, data integrity, or irreversible state → upgrade to L2
- Uncertain classification → upgrade, do not downgrade

## Execution Pipeline

For L1+, the default workflow is:

1. **Analyze** — understand behavior and constraints before touching code
2. **Define** — contracts, boundaries, failure paths
3. **Verify Plan** — what evidence will prove the change is safe
4. **Implement** — minimum compliant change
5. **Refactor** — only under evidence protection

Do not skip a step when the omission would hide risk.

## Forbidden Behaviors

- Expand scope beyond what was explicitly instructed
- Refactor unrelated areas for cleanliness or taste
- Add speculative abstractions for hypothetical future requirements
- Fake, inflate, or omit evidence
- Assume intent when the instruction is ambiguous — ask instead

## Secret Handling

- Never commit tokens, API keys, credentials, or secrets to the repo
- Never write tokens or credentials into memory/ files or logs
- If a secret appears in conversation context, do not persist it anywhere
- `.env` files and credentials must be in `.gitignore` and never staged

## Memory Update Triggers

The following events require updating PLAN.md and/or the relevant memory/ file:

| Event | Required update |
|-------|----------------|
| Milestone reached | PLAN.md phase/sprint + memory/active_task |
| Architecture decision made | PLAN.md decision log + memory/knowledge_base |
| Bug fixed with root cause identified | memory/knowledge_base |
| Risk or incident encountered | PLAN.md risk section + memory/active_task |
| Session end | memory/active_task (current status) + session_end hook |

## Session Closeout Obligation

Writing `artifacts/session-closeout.txt` before session end is a **governance
obligation**, not a suggestion.

The stop hook always calls `session_end` at session end. If the closeout artifact
is missing or insufficient, the runtime records `closeout_missing` or
`closeout_insufficient` in the verdict. Memory will not update. The gap is
auditable and visible to reviewers.

### Required fields

All fields must be present. Vague values are flagged as insufficient.

```
TASK_INTENT: <one sentence — declared goal of this session>
WORK_COMPLETED: <what was actually done — verifiable claims only>
FILES_TOUCHED: <comma-separated file list, or NONE>
CHECKS_RUN: <specific commands or checks run, or NONE>
OPEN_RISKS: <what might be wrong or incomplete, or NONE>
NOT_DONE: <what was not completed this session, or NONE>
RECOMMENDED_MEMORY_UPDATE: <what memory/ file should change and why, or NO_UPDATE>
```

### Rules

- `WORK_COMPLETED` must contain verifiable claims. Do not write "made improvements"
  or "worked on things" — these are vague and will be rejected as insufficient.
- `CHECKS_RUN` must name specific commands if non-`NONE`.
- If there was no material progress, write `WORK_COMPLETED: NONE` — do not
  fabricate completions.
- `NOT_DONE` and `OPEN_RISKS` are the most important fields. AI agents tend to
  omit failures. Do not.

### If you cannot write the closeout

Write it anyway with `WORK_COMPLETED: NONE` and explain in `OPEN_RISKS` why
the session produced no verifiable output. This is a valid closeout.

See `docs/session-closeout-schema.md` for examples and field constraints.

## Definition of Done

A task is done when:

- Behavior is explicit and observable
- Failure paths are guarded
- Architecture boundaries remain intact
- Evidence matches the declared risk level
- PLAN.md and memory/ reflect the new state
