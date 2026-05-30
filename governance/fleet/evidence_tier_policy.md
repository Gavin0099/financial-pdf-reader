# Evidence Tier Policy

Reviewed: 2026-05-25
Authority: Gavin0099

## Problem

The governance framework's `gate_policy.yaml` defaults to `fail_mode: strict`,
which blocks session closeout when a test-result artifact is absent. This is
correct for software repos with CI pipelines, but firmware/kernel repos can
only validate on physical hardware — automated test artifacts are structurally
impossible to produce in a normal development session.

5 of 10 required repos are device-level. Without an evidence tier framework,
the scope-normalized verified ratio would hit a hard ceiling below 50%.

## Core Principle

fail-closed is preserved at every tier. The gate always runs; what changes
is WHAT the gate accepts as sufficient evidence. Evidence strength differences
are made visible in the per-repo snapshot table, not hidden.

## Evidence Tiers

### tier_1 — Automated CI Test
Repo produces a test-result artifact from an automated test runner (pytest,
junit, SDV, WDK analysis) in every session. gate_policy.yaml uses
`fail_mode: strict`. The gate blocks if no artifact is present.

Indicator: `fail_mode: strict` in gate_policy.yaml, no `skip_test_result_check`.
Examples: ai-governance-framework (pytest), cli (if CI tests exist)

### tier_2 — Build + Static Analysis Proxy
Repo cannot run an automated test suite in a normal session, but CAN produce
a build result (msbuild zero-warning, lint pass) as a proxy evidence signal.
gate_policy.yaml uses `fail_mode: audit` + `skip_type: structural`.
The gate runs in audit mode (never blocks), but the session still writes a
canonical-audit-log entry. The build result should be ingested via
`test_result_ingestor --kind msbuild-warning-text` when available.

Indicator: `evidence_tier: tier_2` in gate_policy.yaml.
Examples: gl_electron_tool, General_End_User_Tool

### tier_3 — Manual Hardware Test Log
Repo validates on physical hardware only. No automated build proxy is
available or sufficient. gate_policy.yaml uses `fail_mode: audit` +
`skip_type: structural`. Sessions close out in audit mode.
Hardware test evidence (if produced) should be documented in
`.governance/hardware_test_log.json` with tester, timestamp, and result.

Indicator: `evidence_tier: tier_3` in gate_policy.yaml.
Examples: hp-firmware-stresstest-tool, CFU, IsptoolRefine2018, lenoveo-isp-tool-avalonia, Kernel-Driver-Contract

## What stays the same

- A repo at tier_3 that has gate_blocked=True in its canonical-audit-log
  entry is NOT accepted as evidence (gate_blocked filter in PS1 is unconditional).
- Evidence must still be linked to the repo HEAD (head_commit_match).
- Evidence must still be within the matrix window (timestamp_in_window).
- Tier cannot be changed to escape the metric — only risk posture (what
  testing is structurally possible) determines tier.

## Fleet snapshot visibility

The per-repo classification table shows `ev_tier` for every repo. This makes
the evidence strength visible when reading the verified ratio:

- `tier_1` verified = backed by automated CI test
- `tier_2` verified = backed by build proxy only
- `tier_3` verified = backed by audit-mode closeout; hardware test not logged
- `unknown` = no gate_policy.yaml found; evidence tier undeclared

The scope-normalized verified ratio does NOT weight by tier. A tier_3 repo
counts the same as a tier_1 repo in the denominator. This is intentional:
tier reflects what testing is possible, not how much governance value the
verification provides. Review the `ev_tier` column to interpret the ratio.
