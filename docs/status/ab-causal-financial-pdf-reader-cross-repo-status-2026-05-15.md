# AB Causal Cross-Repo Status: financial-pdf-reader (Repo B) (2026-05-15)

As-of: 2026-05-15
Repo type: product/feature-heavy
Baseline dataset: ab-causal-cross-repo-fpr-2026-05-15
Checkpoint: docs/status/ab-causal-financial-pdf-reader-cross-repo-checkpoint-2026-05-15.json

Locked controls: direction_tolerance=-1.5 (inherited from cross-repo protocol)

| arm_id | arm_type | changed_variable | changed_value | completed_seeds | pass_count | unsupported_count | no_guardrail_breach |
|---|---|---|---|---:|---:|---:|---|
| cr-fpr-arm-1 | baseline-strict | (none) | (none) | 3 | 0 | 3 | True |
| cr-fpr-arm-2 | one-cause-one-fix | narrative_density_threshold | 0.5 | 3 | 0 | 3 | True |

## Gate

- strict_gate: any arm must have pass_count=3/3 and unsupported_count=0
- unsupported_count > 0 in all arms → **inconclusive**
- decision: **inconclusive**

## Root Cause of Unsupported

financial-pdf-reader governance is deterministic claim-level enforcement (R1-R7, narrative density, forward-looking guard).
The AB causal framework requires an A/B rate comparison (governed vs. ungoverned baseline).
No controlled baseline measurement harness exists in this repo: all 42 governance tests are self-contained pass/fail checks, not rate comparison experiments.

## Guardrail Status

- All 6 cases: guardrail_status=pass (no governance breach)
- Governance tests: 42/42 passing under both arm configurations

## Claim Boundary (Per Protocol)

Allowed: "Current AI governance effect is observable but condition-dependent."
Disallowed: "Mechanism robustness confirmed" / "Generalized uplift proven"
