# AB Causal Cross-Repo Status (Harness): financial-pdf-reader (Repo B) (2026-05-15)

As-of: 2026-05-15
Repo type: product/feature-heavy
Harness: governance_harness.py (governed vs ungoverned synthetic claim comparison)
Checkpoint: docs/status/ab-causal-financial-pdf-reader-cross-repo-harness-checkpoint-2026-05-15.json

Metric: unblocked_narrative_claim_rate (ungoverned=A, governed=B)
Locked controls: direction_tolerance=-1.5

| arm_id | arm_type | seed | A_rate | B_rate | abs_delta | result |
|---|---|---:|---:|---:|---:|---|
| cr-fpr-harness-arm-1 | baseline-strict | 350101 | 16.0 | 8.0 | -8.0 | pass |
| cr-fpr-harness-arm-1 | baseline-strict | 350102 | 16.0 | 8.0 | -8.0 | pass |
| cr-fpr-harness-arm-1 | baseline-strict | 350103 | 16.0 | 8.0 | -8.0 | pass |
| cr-fpr-harness-arm-2 | one-cause-one-fix | 350101 | 16.0 | 8.0 | -8.0 | pass |
| cr-fpr-harness-arm-2 | one-cause-one-fix | 350102 | 16.0 | 8.0 | -8.0 | pass |
| cr-fpr-harness-arm-2 | one-cause-one-fix | 350103 | 16.0 | 8.0 | -8.0 | pass |

## Arm Summary

| arm_id | changed_variable | changed_value | completed_seeds | pass_count | unsupported_count |
|---|---|---|---:|---:|---:|
| cr-fpr-harness-arm-1 | (none) | (none) | 3 | 3 | 0 |
| cr-fpr-harness-arm-2 | narrative_density_threshold | 0.5 | 3 | 3 | 0 |

## Gate

- strict_gate: any arm must have pass_count=3/3 and unsupported_count=0
- decision: **mechanism_stable_candidate**

## Claim Boundary (Per Protocol)

Allowed: "Current AI governance effect is observable but condition-dependent."
Disallowed: "Mechanism robustness confirmed" / "Generalized uplift proven"
