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

## Next Required Step (Per Protocol)

Before global claim upgrade:
- Run replication in a third repo (different from gl-electron-tool and financial-pdf-reader)
- Candidate: ai-governance-framework repo itself

## Claim Boundary (Unchanged)

Allowed:
- "Current AI governance effect is observable but condition-dependent."
- "Strict-regime mechanism stability is not yet established across repos."

STILL disallowed (until 3rd-repo replication):
- "Mechanism robustness confirmed"
- "Generalized uplift proven"
