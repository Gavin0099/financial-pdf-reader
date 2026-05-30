# External Repo Onboarding SOP

Status: v1
Scope: onboard a consuming repository into `ai-governance-framework` with minimal ambiguity.

## Goals

- Establish a reproducible onboarding path for external repos.
- Keep governance adoption fail-closed without forcing schema expansion.
- Separate human decisions (domain/risk) from automation steps.

## Step 1: Add Framework as Submodule

In target repo root:

```bash
git submodule add https://gli-gitlab-ee.genesyslogic.com.tw/CRD/SW/ai-governance-framework/ai-governance-framework ai-governance-framework
git submodule update --init --recursive
```

Acceptance:
- `ai-governance-framework/` exists.
- Submodule pointer is tracked by the target repo.

## Step 2: Run External Onboarding Gap Scan

Run onboarding/readiness scan from framework against the target repo.

Minimum output required:
- machine-readable gap report
- human-readable summary

Typical gaps:
- hooks missing
- framework lock missing
- AGENTS.md still scaffold
- no admissible closeout evidence

Acceptance:
- Gap list is explicit and actionable.

## Step 3: Human Decision on `contract.yaml`

Human owner must decide and write:
- `domain`
- `risk tier` (or equivalent risk posture field)

Rules:
- Do not auto-guess domain/risk from code heuristics.
- No placeholder values.

Acceptance:
- Contract validation passes.
- Domain/risk rationale is reviewer-explainable.

## Step 4: Initialize Memory Skeleton

Create minimum memory files and keep project facts human-authored.

Required baseline:
- `memory/YYYY-MM-DD.md`
- `memory/02_tech_stack.md` (or local alias expected by current tooling)

Rules:
- Agent may scaffold structure.
- Project facts content must be filled/confirmed by humans.

Acceptance:
- Memory schema check passes.
- Project facts are non-empty and repo-specific.

## Step 5: Install Hooks and Verify Real Trigger

Install `pre-commit` and `pre-push` hooks and framework-root config.

Then run a real commit/push trial (not file-existence only).

Acceptance:
- Hook validator reports `valid=true`.
- Push path shows runtime governance hook execution.

## Step 6: Run Runtime Smoke

Run runtime smoke checks (session_start / pre_task / post_task).

Acceptance:
- Smoke passes (or bounded advisories only).
- Required runtime artifacts are produced.

## Step 7: Produce Reviewer Handoff

Handoff report must include:
- onboarding gaps and remediations
- contract domain/risk decisions
- hook install and push-trigger evidence
- runtime smoke evidence
- remaining blockers and next-step recommendation

Acceptance:
- Reviewer can decide go/no-go without re-running discovery.

## Non-Goals

- No schema expansion during onboarding unless failure-driven and approved.
- No evidence-contract weakening to “make ratio green”.
- No bulk multi-repo onboarding in one stream.

## Recommended Minimal Verified Path

For required repos with known pattern:
- `hooks + framework.lock + fresh closeout (+ dirty explained)`

This path is preferred when it satisfies existing contract semantics without introducing new governance concepts.

