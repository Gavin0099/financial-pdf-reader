# AB Causal r48b Negative-Path Equivalence Status (2026-05-15)

As-of: 2026-05-15
Repo: financial-pdf-reader
Mode: equivalence validation (no policy expansion)

## Objective

Validate r45.4b-equivalent negative-path (deny-path reason-code) behavior in
financial-pdf-reader without changing governance policy semantics.

## Freeze Compatibility

- No new policy rule
- No new override authority
- No reason-code semantic mutation
- No deny-path logic expansion

## Test Matrix

| violation | purpose | status | notes |
|---|---|---|---|
| negative-path V1-V5 | deny-path reason code equivalence | pass | all 5 types caught |
| fail-closed | ungoverned preserves violations | pass | 5/5 violations present when ungoverned |
| replay determinism | same input → same output | pass | attribution_prefix identical across runs |

## Violation-Level Checks

| check | reason_code | governed_value | result |
|---|---|---|---|
| V1_observed_fact_downgrade | source_type=narrative cannot assert observed_fact → downgraded | interpretation | pass |
| V2_confidence_cap | management_expectation confidence capped to medium | medium | pass |
| V3_forward_looking_detect | forward_looking keyword auto-detected ('預計') | True | pass |
| V4_rhetorical_flag | rhetorical phrase '明顯' detected → rhetorical_risk_flag=True | review=False,flag=True | pass |
| V5_attribution_required | strategic_narrative → attribution_prefix='公司宣稱：' applied | 公司宣稱： | pass |

## Key Checks

- reason-code equivalence: pass — all V1-V5 reason codes fire correctly
- fail-closed equivalence: pass — ungoverned_count=5/5
- replay determinism: pass — attribution stable across runs
- unsupported_count: 0

## Decision

- decision: **pass**
- claim boundary: Current AI governance effect is observable but condition-dependent.

## Artifacts

- checkpoint: ab-causal-r48b-fpr-negative-path-equivalence-checkpoint-2026-05-15.json
- dataset: _V1_TEST/_V2_TEST/_V3_TEST/_V4_TEST/_V5_TEST (governance_harness.py)
- run command: python governance_harness.py --run-r48
