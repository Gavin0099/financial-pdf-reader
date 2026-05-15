# AB Causal Cross-Repo Summary (2026-05-15) — Updated with Harness

As-of: 2026-05-15
Strict gate: unchanged (pass_count=3/3, unsupported_count=0 required)

## Repo Results

### Original first pass (no harness — inconclusive for Repo B)

| repo_id | repo_type | decision |
|---|---|---|
| gl-electron-tool | tooling/infrastructure-heavy | threshold_dependent_persists |
| financial-pdf-reader | product/feature-heavy | inconclusive (no_baseline_harness) |

### Updated: with governance_harness.py (governed vs ungoverned)

| repo_id | repo_type | arm_count | seeds | pass_count_best | unsupported_count | decision |
|---|---|---:|---:|---:|---:|---|
| gl-electron-tool | tooling/infrastructure-heavy | 2 | 3 | 0 | 0 | threshold_dependent_persists |
| financial-pdf-reader | product/feature-heavy | 2 | 3 | 3 | 0 | **mechanism_stable_candidate** |

Metric (financial-pdf-reader): unblocked_narrative_claim_rate
- A_rate (ungoverned) = 16.0 (8 narrative claims × scale_factor 2.0)
- B_rate (governed) = 8.0 (4 financial_evidence claims × scale_factor 2.0)
- abs_delta = -8.0 (>> direction_tolerance -1.5)

## Cross-Repo Decision

At least one repo (financial-pdf-reader) has an arm with 3/3 pass and unsupported_count=0.

Per cross-repo decision rules:
→ **Mark repo-conditional mechanism viability**
→ Run replication in a third repo before any global claim upgrade

financial-pdf-reader: mechanism_stable_candidate (governance creates clear directional effect)
gl-electron-tool: threshold_dependent_persists (mechanism effect marginal at strict boundary)

**Interpretation:**
The AI governance mechanism is **not uniformly transferable** across repo types.
Product/feature repos (evidence-bound claim enforcement) show stronger governance signal
than tooling/infra repos (task acceptance rate governance).

## Interpretation Boundary (REQUIRED — Do Not Overclaim)

**mechanism_stable_candidate is harness-local and metric-bound.**

The financial-pdf-reader result was determined using a synthetic harness metric
(unblocked_narrative_claim_rate: deterministic ungoverned vs governed code path on
synthetic claim sets). This is NOT equivalent to:
- Cross-repo global mechanism robustness
- Real-task AI session evidence
- Multi-repo replication evidence

Additional observation: arm-1 and arm-2 produced identical values across all seeds,
meaning narrative_density_threshold=0.5 is not a detectable causal variable in the
current harness. The arm-2 "pass" is mechanistically uninformative about the
one-cause-one-fix probe; it reflects the same governed-vs-ungoverned delta.

**External claim remains unchanged until real-task matched gate also passes:**
→ "Current AI governance effect is observable but condition-dependent."

## 3rd Repo Replication: ai-governance-framework ✅ (2026-05-15)

Domain: external_observation_contract enforcement (forbidden fields: verdict, gate_verdict, closure_verified, promote_eligible)
Metric: governance_violation_rate

| arm_id | arm_type | A_rates | B_rates | deltas | decision |
|---|---|---|---|---|---|
| cr-agf-arm-1 | baseline-strict | 16/12/20 | 0/0/0 | -16/-12/-20 | mechanism_stable_candidate |
| cr-agf-arm-2 | one-cause-one-fix | 16/12/20 | 8/6/10 | -8/-6/-10 | mechanism_stable_candidate |

arm-2 differentiation: `confidence_strict_mode=False` → V4 violations (high-confidence without evidence) survive governance → B_rate measurably differs from arm-1. **detectable: true**

### Updated Cross-Repo Table (3 Repos)

| repo_id | repo_type | decision | arm2_detectable |
|---|---|---|---|
| gl-electron-tool | tooling/infrastructure-heavy | threshold_dependent_persists | N/A |
| financial-pdf-reader | product/feature-heavy | **mechanism_stable_candidate** | false (parameter not causal in metric) |
| ai-governance-framework | governance-meta | **mechanism_stable_candidate** | **true** |

### Global Cross-Repo Conclusion

- 2/3 repos: mechanism_stable_candidate (arm-1 strict baseline, 3/3 pass, unsupported=0)
- 1/3 repos: threshold_dependent_persists (gl-electron-tool)
- Cross-repo pattern confirms: AI governance effect is **condition-dependent** (repo-type-specific)
- 3rd-repo replication requirement: **satisfied**
- Global claim upgrade to "robustness confirmed": still disallowed (heterogeneity remains)

## Claim Boundary (Final — 3-Repo Analysis Complete)

Allowed (confirmed by 3-repo data):
- "Current AI governance effect is observable but condition-dependent."
- "Mechanism stability is repo-type-dependent: stronger in product/governance repos than tooling/infra repos."

Still disallowed:
- "Mechanism robustness confirmed"
- "Generalized uplift proven"
- "Uniform cross-repo transferability established"
