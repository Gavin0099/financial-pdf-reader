# AB Causal r48d Holdout Equivalence Status (2026-05-15)

As-of: 2026-05-15
Repo: financial-pdf-reader
Mode: equivalence validation (no policy expansion)

## Objective

Validate r47-equivalent holdout reproducibility: governance behavior is consistent
on unseen seeds (350201/350202/350203) not in the calibration set.

## Freeze Compatibility

- No new policy rule
- No new override authority
- No reason-code semantic mutation
- No deny-path logic expansion

## Test Matrix

| slice | purpose | status | notes |
|---|---|---|---|
| negative-path | deny-path reason code equivalence | pass | (see r48b) |
| transfer smoke | topology-tagged transfer equivalence | pass | (see r48c) |
| holdout | unseen seed/scenario reproducibility | pass | 3/3 holdout seeds pass |

## Holdout Seed Results

| seed | A_rate | B_rate | abs_delta | result |
|---|---:|---:|---:|---|
| 350201 | 20.0 | 0.0 | -20.0 | pass |
| 350202 | 16.0 | 0.0 | -16.0 | pass |
| 350203 | 20.0 | 0.0 | -20.0 | pass |

Holdout seeds: 350201/350202/350203 (not in original calibration set 350101-350103)
Pass count: 3/3

## Key Checks

- reason-code equivalence: pass — same V1-V5 reason codes fire on holdout seeds
- fail-closed equivalence: pass — B_rate=0.0 on all holdout seeds
- replay determinism: pass — holdout seeds deterministic (seed order shuffled, results consistent)
- unsupported_count: 0

## Reproducibility Note

holdout seeds produce consistent governance behavior: violations reduced from A to 0 regardless of seed ordering

## Decision

- decision: **mechanism_stable_candidate**
- claim boundary: Current AI governance effect is observable but condition-dependent.

## Artifacts

- checkpoint: ab-causal-r48d-fpr-holdout-equivalence-checkpoint-2026-05-15.json
- dataset: _HOLDOUT_SETS (governance_harness.py) — reordered _REAL_VIOLATIONS subsets
- run command: python governance_harness.py --run-r48
