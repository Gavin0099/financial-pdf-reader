# AB Causal Cross-Repo — Real-Task Gate: financial-pdf-reader (2026-05-15)

As-of: 2026-05-15
Mode: real-task violation_rate (derived from actual test-file claim examples)
decision: **mechanism_stable_candidate**
Checkpoint: see ab-causal-cross-repo-fpr-real-task-arm-* files

| arm_id | arm_type | seed | A_rate | B_rate | abs_delta | result |
|---|---|---:|---:|---:|---:|---|
| cr-fpr-real-arm-1 | baseline-strict | 350101 | 16.0 | 0.0 | -16.0 | pass |
| cr-fpr-real-arm-2 | one-cause-one-fix | 350101 | 16.0 | 0.0 | -16.0 | pass |
| cr-fpr-real-arm-1 | baseline-strict | 350102 | 12.0 | 0.0 | -12.0 | pass |
| cr-fpr-real-arm-2 | one-cause-one-fix | 350102 | 12.0 | 0.0 | -12.0 | pass |
| cr-fpr-real-arm-1 | baseline-strict | 350103 | 20.0 | 0.0 | -20.0 | pass |
| cr-fpr-real-arm-2 | one-cause-one-fix | 350103 | 20.0 | 0.0 | -20.0 | pass |

## Metric

- A_rate = ungoverned_violation_count × scale_factor (violations present in raw input)
- B_rate = governed_remaining_violations × scale_factor (violations not caught by governance)
- Governed violations include: V1=observed_fact downgrade, V2=confidence cap, V3=fwd-looking auto-detect, V4=rhetorical flag, V5=attribution_prefix

## Layer 3 Note

Real-task gate uses claims derived from actual test file scenarios (not purely synthetic).
Arm-2 (narrative_density_threshold=0.5) still produces identical values: the violation_rate
metric is not sensitive to this parameter either. This confirms the one-cause-one-fix
arm needs a different variable to show causal differentiation.

## Claim Boundary (Per Protocol)

Allowed: "Current AI governance effect is observable but condition-dependent."
Disallowed: "Mechanism robustness confirmed" / "Generalized uplift proven"

Even with Layer 3 pass, global claim upgrade requires cross-repo replication (3rd repo).
