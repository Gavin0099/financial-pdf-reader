# Review Projection Contract v0.1

Status: advisory-only projection contract  
Layer: runtime artifact -> semantic projection -> reviewer surface

## 1) Scope

This contract defines how review projection artifacts are generated for reviewer use.

Projection layer may:
- normalize structure
- collapse or group sections
- assign display severity
- surface epistemic status
- link to raw evidence

Projection layer may not:
- infer engineering correctness
- auto-approve rollout/merge safety
- mutate runtime source artifacts
- convert advisory state into enforcement state
- reinterpret semantic meaning of source artifacts
- downgrade uncertainty visibility
- replace canonical terminology with stronger claims
- introduce inferred safety language
- aggregate independent states into stronger epistemic claims

## 2) Output Artifacts

Required outputs:
- `review-summary.json`
- `review-sections.json`

Both outputs must include:
- `schema_version`
- `generated_at_utc`
- `advisory_only=true`
- `source_artifacts[]`
- `projection_non_canonical=true`
- projection coverage disclosure fields (`coverage_complete`, `omitted_sections_count`, `omitted_section_categories[]`)

## 2.1) Projection Integrity Rules

Projection layer may:
- reorganize
- collapse
- group
- visually emphasize

Projection layer may not:
- reinterpret semantic meaning
- downgrade uncertainty visibility
- replace canonical terminology
- introduce inferred safety wording
- aggregate states into stronger epistemic claims

## 2.2) Cross-Artifact Interpretation Rules

Projection layer may display multiple artifacts together.

Projection layer may not:
- derive overall system correctness
- derive deployment readiness
- derive operational safety
- synthesize independent advisory signals into stronger conclusions

## 3) Epistemic Status Rules

Allowed statuses:
- `VERIFIED`
- `OBSERVED`
- `INFERRED`
- `UNVERIFIED`
- `MISSING`

Rules:
- Every summary signal must declare one epistemic status.
- Any `INFERRED`, `UNVERIFIED`, or `MISSING` signal must include a reviewer attention note.
- Any `INFERRED`, `UNVERIFIED`, or `MISSING` signal must not be rendered as low-risk informational certainty.

## 4) Traceability Rules

Every summary field that could influence reviewer judgment must include raw evidence trace metadata:
- `source_artifact`
- `source_path`
- `evidence_snippet` (short, non-authoritative excerpt)

Evidence snippet requirements:
- preserve uncertainty wording
- preserve negation wording
- avoid truncation that changes interpretation

If trace metadata is unavailable, field must be marked:
- `epistemic_status: MISSING`
- `severity: high`

## 5) Severity Rules

Allowed severities:
- `high`
- `medium`
- `low`
- `info`

Attention routing:
- High-severity items must appear in `high_attention_items` of `review-summary.json`.
- `review-sections.json` must default high-severity sections to `collapsed=false`.

Severity authority rules:
- Severity assignment must originate from canonical projection mapping rules.
- Severity assignment must remain traceable to source evidence conditions.
- Severity is routing only; it does not imply correctness, safety, or enforcement readiness.

## 5.1) Projection Coverage Rules

Projection outputs must disclose:
- whether projection is complete or partial
- omitted section count
- omitted section categories

If projection is partial:
- `coverage_complete=false` must be declared
- omitted categories must be listed

## 6) Non-Decision Clause

Projection output is reviewer support material only.
It must not be interpreted as:
- correctness proof
- merge safety certification
- autonomous governance decision

## 7) Canonical Authority Boundary

Projection artifacts are non-canonical reviewer assistance surfaces.

Canonical authority remains:
- runtime artifacts
- governance contracts
- enforcement records
- raw evidence artifacts

## 8) Renderer Isolation Rule

Renderer layer must not:
- introduce semantic labels
- modify epistemic status
- suppress high-severity visibility
- visually imply enforcement authority
