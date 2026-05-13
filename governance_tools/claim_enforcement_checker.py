#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


DISALLOWED_PHRASES = (
    "proven",
    "production-ready",
)

POSTURE_ORDER = {
    "none": 0,
    "bounded_support": 1,
    "partial_falsification": 2,
}

CLAIM_LEVEL_ORDER = {
    "bounded": 0,
    "parity": 1,
    "strong": 2,
    "unbounded": 3,
}

# Backward compatibility mapping for older artifacts.
LEGACY_CLAIM_LEVEL_MAP = {
    "bounded_support": "bounded",
    "stronger_than_allowed": "strong",
}


def _load_input(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _is_posture_stronger(current: str, previous: str) -> bool:
    return POSTURE_ORDER.get(current, -1) > POSTURE_ORDER.get(previous, -1)


def _normalize_claim_level(value: str) -> str:
    raw = (value or "").strip()
    mapped = LEGACY_CLAIM_LEVEL_MAP.get(raw, raw)
    return mapped if mapped in CLAIM_LEVEL_ORDER else "bounded"


def evaluate(payload: dict) -> dict:
    reasons = []
    preconditions = payload.get("preconditions", True)
    scenario_result = payload.get("scenario_result")
    observed = payload.get("observed", "__missing__")

    # Hard rule: precondition failed flow must be not_executed + observed=null
    if preconditions is False:
        hard_rule_ok = scenario_result == "not_executed" and observed is None
        return {
            "result": "pass" if hard_rule_ok else "fail",
            "checker_status": "pass" if hard_rule_ok else "fail",
            "semantic_drift_risk": False,
            "claim_level": _normalize_claim_level(str(payload.get("claim_level", "bounded"))),
            "enforcement_action": "allow" if hard_rule_ok else "block",
            "reviewer_override_required": False if hard_rule_ok else True,
            "publication_scope": str(payload.get("publication_scope", "public")),
            "reasons": [] if hard_rule_ok else [
                "precondition_failed_contract_violation: expected not_executed + observed=null"
            ],
        }

    final_claim = str(payload.get("final_claim", ""))
    claim_level = _normalize_claim_level(str(payload.get("claim_level", "bounded")))
    same_evidence = bool(payload.get("same_evidence_as_previous", False))
    posture = str(payload.get("posture", "none"))
    previous_posture = str(payload.get("previous_posture", "none"))
    publication_scope = str(payload.get("publication_scope", "public"))

    semantic_drift_risk = False

    lowered = final_claim.lower()
    if any(p in lowered for p in DISALLOWED_PHRASES):
        semantic_drift_risk = True
        reasons.append("disallowed_strong_claim_phrase")

    if same_evidence and _is_posture_stronger(posture, previous_posture):
        semantic_drift_risk = True
        reasons.append("same_evidence_strengthening")

    expected_flag = payload.get("semantic_drift_risk")
    if expected_flag is not None and bool(expected_flag) != semantic_drift_risk:
        reasons.append("input_semantic_drift_risk_mismatch")

    # Local-only scope cannot claim above bounded.
    if publication_scope == "local_only" and claim_level != "bounded":
        semantic_drift_risk = True
        reasons.append("local_only_claim_level_exceeds_bounded")

    if semantic_drift_risk:
        if claim_level in ("strong", "unbounded"):
            enforcement_action = "block"
        else:
            enforcement_action = "downgrade"
    else:
        enforcement_action = "allow"

    result = "fail" if enforcement_action == "block" else "pass"
    return {
        "result": result,
        "checker_status": "fail" if enforcement_action == "block" else "pass",
        "semantic_drift_risk": semantic_drift_risk,
        "claim_level": claim_level,
        "enforcement_action": enforcement_action,
        "reviewer_override_required": enforcement_action in ("downgrade", "block"),
        "publication_scope": publication_scope,
        "reasons": reasons,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--format", choices=("json",), default="json")
    args = parser.parse_args()

    payload = _load_input(Path(args.input))
    out = evaluate(payload)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
