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

## Next Required Step (Per Protocol)

Before global claim upgrade:
- Run replication in a third repo (different from gl-electron-tool and financial-pdf-reader)
- Candidate: ai-governance-framework repo itself
- AND: matched real-task gate must pass (not just synthetic harness)

## Claim Boundary (Unchanged)

Allowed:
- "Current AI governance effect is observable but condition-dependent."
- "Strict-regime mechanism stability is not yet established across repos."

STILL disallowed (harness-local result is insufficient):
- "Mechanism robustness confirmed"
- "Generalized uplift proven"
