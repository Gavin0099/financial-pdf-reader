import json
import sys
from pathlib import Path

from services.dashboard_contract import validate_dashboard_contract_v1


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/validate_dashboard_contract.py <dashboard.json>")
        return 2
    p = Path(sys.argv[1])
    payload = json.loads(p.read_text(encoding="utf-8"))
    errors = validate_dashboard_contract_v1(payload)
    if errors:
        print("INVALID")
        for e in errors:
            print(f"- {e}")
        return 1
    print("VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
