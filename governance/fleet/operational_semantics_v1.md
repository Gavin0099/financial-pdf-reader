# Operational Semantic Stabilization v1

Status: draft-v1 (semantics freeze target)
Scope: terminology stabilization only
Non-goals: schema change, ratio optimization, repo state mutation, metric expansion

## Core Rule

No operational semantic may imply more authority than its verifier can prove.

## Terms

### hooks_ready

Definition:
- `hooks_ready=true` means hook installation and framework-root provenance are executable for this repo context.
- It does not mean hooks cover every governance behavior.

Must prove:
- `pre_commit_installed=true`
- `pre_push_installed=true`
- hook files are spawnable/executable (no encoding/shebang corruption)
- framework root resolution is explicit and valid for the evaluated context

Must not imply:
- full governance compliance
- evidence-chain admissibility by itself

### repo_native_verified

Definition:
- `repo_native_verified=true` means the required evidence chain is admissible under current contract and policy gates.
- It does not mean the repo is production-safe.

Must prove:
- required gates passed under fail-closed semantics
- evidence artifacts are admissible for the current head/time window

Must not imply:
- runtime quality/safety guarantees
- release readiness

### clean_admissibility

Definition:
- `clean_admissibility=true` means current dirty set is safe to clean according to admissibility policy.
- It does not mean the repo should be cleaned now.

Must prove:
- dirty paths are within `generated_safe_to_clean`
- no `never_auto_clean` hit
- no `requires_manual_review` condition triggered

Must not imply:
- cleanup is mandatory
- cleanup has zero workflow impact

### expected_dirty_ttl

Definition:
- `expected_dirty_ttl_valid=true` means the dirty explanation is currently within approved validity window.
- It does not make dirty state permanently acceptable.

Must prove:
- expected-dirty declaration exists
- TTL is unexpired at evaluation time
- reason is explicit and tied to current operational context

Must not imply:
- indefinite dirty-state legitimacy
- exemption from re-evaluation

### self_hosting_gap_closed

Definition:
- `self_hosting_gap_closed=true` means framework repo can run normal commit flow without `--no-verify`, through its own hook path, with explicit framework-root provenance.

Closing condition:
- `pre_commit_valid=true`
- `pre_push_valid=true`
- `framework_root_config_present=true`
- last normal commit path did not require `--no-verify`

Must not imply:
- no remaining governance debt
- external repo onboarding maturity

### closeout_maintenance_mode

Definition:
- `closeout_maintenance_mode=event-driven+stale-warning` means closeout evidence is primarily refreshed by real workflow events (commit/push/session-end), with stale-state warning surfaced by matrix/runtime checks.
- It is not a daily unconditional auto-stamp policy.

Must prove:
- hooks or wrappers can trigger closeout on real workflow boundaries
- stale evidence is observable as warning/blocker in reporting surfaces

Must not imply:
- cron-only refresh is acceptable replacement for workflow evidence
- freshness can be maintained without real session boundaries

## Interpretation Guardrails

- If verifier output is partial, semantic claims must remain partial.
- If provenance is fallback-based rather than explicit, claim level must be downgraded.
- Semantic wording in reports must match what the underlying verifier can actually prove.
