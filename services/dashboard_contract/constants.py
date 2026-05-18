from __future__ import annotations

DASHBOARD_CONTRACT_VERSION = "dashboard_contract_v1"

METRIC_TYPE = {
    "revenue": "growth",
    "gross_margin": "profitability",
    "operating_income": "profitability",
    "eps": "profitability",
    "cash": "liquidity",
    "debt": "liquidity",
    "fx": "risk_exposure",
    "customer_concentration": "risk_exposure",
}

RELATION_ENUM = {"derived_from", "compared_with", "inverse_driver", "positive_driver", "contextual_factor"}
SEVERITY_ENUM = {"low", "medium", "high", "critical", "unknown"}
TREND_ENUM = {"up", "down", "flat"}
