# AB Causal r48c Transfer Smoke Equivalence Status (2026-05-15)

As-of: 2026-05-15
Repo: financial-pdf-reader
Mode: equivalence validation (no policy expansion)

## Objective

Validate r46-equivalent topology-tagged transfer behavior: governance rules
are source_type-specific and correctly differentiated across claim topologies.

## Freeze Compatibility

- No new policy rule
- No new override authority
- No reason-code semantic mutation
- No deny-path logic expansion

## Test Matrix

| slice | purpose | status | notes |
|---|---|---|---|
| negative-path | deny-path reason code equivalence | pass | (see r48b) |
| transfer smoke | topology-tagged transfer equivalence | pass | 4 topologies verified |
| holdout | unseen seed/scenario reproducibility | pass | (see r48d) |

## Topology Results

| source_type | intervention_expected | attribution | confidence_capped | result |
|---|---|---|---|---|
| financial_evidence | False | (none) | N/A | pass |
| operational_evidence | False | (none) | N/A | pass |
| strategic_narrative | True | 公司宣稱： | N/A | pass |
| management_expectation | True | 管理層表示： | True | pass |

## Key Checks

- reason-code equivalence: pass — topology rules fire correctly per source_type
- fail-closed equivalence: pass — non-narrative claims receive no intervention
- replay determinism: pass — topology routing is deterministic
- unsupported_count: 0
- detectable: True — financial vs narrative attribution_prefix differs

## Topology Differentiation

governance rules are source_type-specific: financial/operational=no-intervention; narrative=attribution; management=attribution+confidence-cap

## Decision

- decision: **pass**
- claim boundary: Current AI governance effect is observable but condition-dependent.

## Artifacts

- checkpoint: ab-causal-r48c-fpr-transfer-smoke-equivalence-checkpoint-2026-05-15.json
- dataset: _TOPO_* claims (governance_harness.py)
- run command: python governance_harness.py --run-r48
