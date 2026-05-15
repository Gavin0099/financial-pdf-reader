# AB Causal Cross-Repo Summary (2026-05-15)

As-of: 2026-05-15
Scope: external observation after r35-r39 closeout (threshold_dependent_persists)
Strict gate: unchanged (pass_count=3/3, unsupported_count=0 required)

## Repo Results

| repo_id | repo_type | arm_count | seeds | pass_count_best | unsupported_count | decision |
|---|---|---:|---:|---:|---:|---|
| gl-electron-tool | tooling/infrastructure-heavy | 2 | 3 | 0 | 0 | threshold_dependent_persists |
| financial-pdf-reader | product/feature-heavy | 2 | 3 | 0 | 6 | inconclusive |

## Cross-Repo Decision

Neither repo achieved mechanism_stable_candidate (3/3 pass, unsupported=0).

- Repo A (gl-electron-tool): threshold_dependent_persists — consistent with r35-r39 lineage
- Repo B (financial-pdf-reader): inconclusive — missing baseline measurement harness (no_baseline_harness)

**Cross-repo comparison is incomplete** because Repo B returned inconclusive.
Cannot conclude "low transferability" (which requires both repos at threshold_dependent_persists).
Cannot conclude "repo-conditional mechanism viability" (no arm reached 3/3 pass).

## Blocking Issue for Repo B

financial-pdf-reader does not have a controlled baseline measurement harness:
- Governance is deterministic claim-level enforcement (R1-R7, narrative density, forward-looking)
- 42/42 unit tests pass, confirming governance enforces correctly
- But directional lift (A_rate vs B_rate) cannot be computed without governed vs. ungoverned experiment

## Required Action to Resolve Inconclusive

Option 1: Build governance measurement harness in financial-pdf-reader
  - Define A condition: AI output without governance enforcement
  - Define B condition: AI output with governance enforcement
  - Measure claim acceptance rate / violation rate per condition
  - Estimated: Phase 10E-infra or standalone governance harness task

Option 2: Accept inconclusive for Repo B and conclude on Repo A alone
  - Repo A alone: threshold_dependent_persists → current mechanism family has low transferability potential
  - This is a weaker conclusion (single-repo) but within protocol bounds

## Claim Boundary (Unchanged)

Allowed:
- "Current AI governance effect is observable but condition-dependent."
- "Strict-regime mechanism stability is not yet established across repos."

Disallowed:
- "Mechanism robustness confirmed"
- "Generalized uplift proven"
