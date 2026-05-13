#!/usr/bin/env python3
"""
Assess the current example set for onboarding readiness.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.domain_contract_loader import load_domain_contract
from governance_tools.domain_validator_loader import preflight_domain_validators


EXAMPLE_SPECS = [
    {
        "name": "todo-app-demo",
        "kind": "runnable-demo",
        "required_paths": ["README.md", "PLAN.md", "src/main.py"],
        "required_modules": ["fastapi"],
        "optional_modules": ["uvicorn"],
        "run_command": "python examples/todo-app-demo/src/main.py",
    },
    {
        "name": "chaos-demo",
        "kind": "walkthrough",
        "required_paths": ["README.md"],
    },
    {
        "name": "starter-pack",
        "kind": "scaffold",
        "required_paths": ["README.md", "PLAN.md", "SYSTEM_PROMPT.md", "memory/01_active_task.md"],
    },
    {
        "name": "usb-hub-contract",
        "kind": "domain-contract",
        "required_paths": [
            "README.md",
            "contract.yaml",
            "AGENTS.md",
            "USB_HUB_FW_CHECKLIST.md",
            "USB_HUB_ARCHITECTURE.md",
            "rules/hub-firmware/safety.md",
            "validators/interrupt_safety_validator.py",
        ],
        "run_command": "python governance_tools/domain_contract_loader.py --contract examples/usb-hub-contract/contract.yaml --format human",
    },
]


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _load_python_module(module_path: Path, module_name: str) -> None:
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inspect_demo_module(module: Any) -> dict[str, Any]:
    app = getattr(module, "app", None)
    if app is None:
        raise AttributeError("Example module does not expose 'app'")

    route_paths = sorted(
        {
            getattr(route, "path")
            for route in getattr(app, "routes", [])
            if getattr(route, "path", None)
        }
    )
    return {
        "app_object_present": True,
        "app_title": getattr(app, "title", None),
        "route_paths": route_paths,
        "health_route_present": "/health" in route_paths,
    }


def assess_example(
    project_root: Path,
    spec: dict[str, Any],
    *,
    strict_runtime: bool = False,
) -> dict[str, Any]:
    example_root = project_root / "examples" / spec["name"]
    errors: list[str] = []
    warnings: list[str] = []

    required_paths = []
    for relative in spec.get("required_paths", []):
        path = example_root / relative
        required_paths.append({"path": str(path), "exists": path.exists()})
        if not path.exists():
            errors.append(f"Required path missing: {relative}")

    runtime_ready = True
    runtime_details: dict[str, Any] = {}

    if spec["kind"] == "runnable-demo":
        missing_modules = [name for name in spec.get("required_modules", []) if not _module_available(name)]
        optional_missing = [name for name in spec.get("optional_modules", []) if not _module_available(name)]

        runtime_details["required_modules"] = spec.get("required_modules", [])
        runtime_details["optional_modules"] = spec.get("optional_modules", [])
        runtime_details["missing_required_modules"] = missing_modules
        runtime_details["missing_optional_modules"] = optional_missing

        if missing_modules:
            runtime_ready = False
            message = "Missing runtime dependency modules: " + ", ".join(missing_modules)
            if strict_runtime:
                errors.append(message)
            else:
                warnings.append(message)

        if optional_missing:
            warnings.append("Missing optional demo modules: " + ", ".join(optional_missing))

        main_file = example_root / "src" / "main.py"
        if main_file.exists() and not missing_modules:
            try:
                module = _load_python_module(main_file, f"example_{spec['name']}_main")
                runtime_details["module_import_ok"] = True
                runtime_details.update(_inspect_demo_module(module))
                if not runtime_details.get("health_route_present"):
                    runtime_ready = False
                    message = "Runnable demo is missing the /health route"
                    if strict_runtime:
                        errors.append(message)
                    else:
                        warnings.append(message)
            except Exception as exc:  # pragma: no cover
                runtime_ready = False
                runtime_details["module_import_ok"] = False
                message = f"Example module import failed: {exc}"
                if strict_runtime:
                    errors.append(message)
                else:
                    warnings.append(message)

    elif spec["kind"] == "domain-contract":
        contract_file = example_root / "contract.yaml"
        if contract_file.exists():
            contract = load_domain_contract(contract_file)
            runtime_details["contract_loaded"] = contract is not None
            validator_preflight = preflight_domain_validators(contract_file)
            runtime_details["validator_preflight"] = validator_preflight
            if contract is None:
                runtime_ready = False
                errors.append("Domain contract failed to load")
            elif validator_preflight and not validator_preflight.get("ok", False):
                runtime_ready = False
                errors.append("Domain validator preflight failed")
        else:
            runtime_ready = False

    else:
        runtime_ready = False
        runtime_details["not_applicable"] = True

    return {
        "name": spec["name"],
        "kind": spec["kind"],
        "path": str(example_root),
        "ok": len(errors) == 0,
        "runtime_ready": runtime_ready,
        "required_paths": required_paths,
        "run_command": spec.get("run_command"),
        "warnings": warnings,
        "errors": errors,
        "runtime_details": runtime_details,
    }


def assess_examples(project_root: Path, *, strict_runtime: bool = False) -> dict[str, Any]:
    examples = [assess_example(project_root, spec, strict_runtime=strict_runtime) for spec in EXAMPLE_SPECS]
    return {
        "ok": all(item["ok"] for item in examples),
        "project_root": str(project_root),
        "strict_runtime": strict_runtime,
        "examples": examples,
    }


def format_human_result(result: dict[str, Any]) -> str:
    lines = ["[example_readiness]", f"ok={result['ok']}"]
    runnable = sum(1 for item in result["examples"] if item["kind"] in {"runnable-demo", "domain-contract"})
    lines.append(f"examples={len(result['examples'])}")
    lines.append(f"runnable_examples={runnable}")

    for item in result["examples"]:
        summary_parts = [
            f"name={item['name']}",
            f"kind={item['kind']}",
            f"ok={item['ok']}",
            f"runtime_ready={item['runtime_ready']}",
        ]
        lines.append(f"summary={' | '.join(summary_parts)}")
        if item.get("run_command"):
            lines.append(f"run_command[{item['name']}]={item['run_command']}")
        if item["name"] == "starter-pack":
            lines.append(
                "note[starter-pack]=Use governance_tools/upgrade_starter_pack.py for opt-in scaffold refresh; this does not equal full framework adoption."
            )
        for warning in item.get("warnings", []):
            lines.append(f"warning[{item['name']}]: {warning}")
        for error in item.get("errors", []):
            lines.append(f"error[{item['name']}]: {error}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess onboarding readiness for bundled examples.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--strict-runtime", action="store_true")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    result = assess_examples(Path(args.project_root).resolve(), strict_runtime=args.strict_runtime)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human_result(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
