# AGENTS.md — Taiwan Financial PDF Reader

This is the workspace contract for all AI agents working in this repository.

## Every Session Start

Before doing anything else:
1. Read `memory/00_long_term.md` — core principles and tech stack
2. Read `memory/01_active_task.md` — current phase and progress
3. Read `memory/YYYY-MM-DD.md` (today's date) if it exists — today's context

Do not ask permission. Just do it.

## Memory Update Protocol — MANDATORY

**Write It Down. No Mental Notes.**

After completing ANY of the following, you MUST update the memory files AND commit:

| Event | Files to update |
|-------|----------------|
| Phase completed | `01_active_task.md`, `00_long_term.md`, `02_workflow.md`, `03_knowledge_base.md` |
| New API endpoint added | `02_workflow.md` |
| New data model added | `03_knowledge_base.md` |
| New governance rule | `03_knowledge_base.md` |
| Design decision made | `00_long_term.md` |
| Bug or fix discovered | `memory/YYYY-MM-DD.md` (daily log) |

**Update sequence** (after each phase):
```
1. Update memory/01_active_task.md  — mark phase ✅, update next step
2. Update memory/00_long_term.md    — add design decisions / new phases
3. Update memory/02_workflow.md     — add new API endpoints
4. Update memory/03_knowledge_base.md — add new models / rules
5. Create memory/YYYY-MM-DD.md      — daily log entry
6. git commit + push
```

Failure to update memory = governance violation.

## Daily Log

Create `memory/YYYY-MM-DD.md` at the start of each session (or after first significant action).

Minimum content:
```markdown
# YYYY-MM-DD

## Done
- [what was completed]

## Decisions
- [key decisions made]

## Next
- [next action]
```

## Governance Reference

- Architecture gates: `governance/AGENT.md`
- Rules registry: `governance/RULE_REGISTRY.md`
- Memory tools: `governance_tools/memory_janitor.py --check`

## Project Identity

- **Repo**: Taiwan Financial PDF Reader
- **Goal**: Taiwan stock PDF financial report reader — every AI claim traceable to a PDF page
- **Stack**: FastAPI + MongoDB Atlas + Claude claude-sonnet-4-6 + pdfplumber
- **Current phase**: See `memory/01_active_task.md`

## Forbidden Actions

- Never generate investment advice (buy/sell/hold)
- Never make claims without PDF page evidence
- Never skip memory updates after phase completion
- Never commit without updating relevant memory files
