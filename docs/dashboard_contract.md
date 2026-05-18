# Dashboard Contract v1

Version: `dashboard_contract_v1`

Hard rules:

1. If `dashboard_contract_valid=false`, UI must not render `What Changed`, `Why It Changed`, `Risk Surface`, `Adjustments`, `AI Transparency`.
2. No frontend fallback semantic generation is allowed when contract is invalid.
3. Dashboard main-layer semantics must be evidence-bound:
   - metric nodes must include `evidence_claim_ids`
   - causal edges must include `evidence_claim_ids`
   - risk rows must include `severity_reason` and `rule_id`

Core shape:

```json
{
  "contract_version": "dashboard_contract_v1",
  "metrics": [],
  "what_changed": [],
  "causal_edges": [],
  "risk_surface": [],
  "adjustments": [],
  "transparency": {}
}
```

Enums:

- relation: `derived_from | compared_with | inverse_driver | positive_driver | contextual_factor | direct_driver | associated_with`
- severity: `low | medium | high | critical | unknown`
- trend: `up | down | flat`
