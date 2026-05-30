# Known Incidents

## GI-001 - Memory Authority Misresolution

- Severity: Low
- Scope: `E:\BackUp\Git_EE\usb-logic-trace-correlator`
- Status: Corrected, monitor for recurrence

Pattern:
- Agent resolved and wrote to an external memory path before applying repo-local governance memory authority.

Observed behavior:
- Operational record was first written outside repo-local `memory/`, then corrected after review.

Corrective action:
- Add structured `memory_authority` block near the top of governance instructions.
- Add adoption packet forbidden change preventing operational records outside declared `memory_root`.
- Do not introduce framework-level memory contract or receipt unless the pattern recurs across repos.

Escalation condition:
- If the same pattern appears in a second repo, escalate to framework-level memory authority validation.
