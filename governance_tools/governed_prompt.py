#!/usr/bin/env python3
"""
Provider-independent governed prompt wrapper.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.contract_renderer import (
    GovernanceContract,
    render_contract_block,
    contract_hash,
)


VALID_PROVIDERS = {"copilot", "chatgpt", "claude", "gemini"}


def build_governed_prompt(contract: GovernanceContract, user_prompt: str) -> str:
    block = render_contract_block(contract)
    return f"{block}\n\n{user_prompt.strip()}\n"


def write_injection_artifact(
    *,
    output_root: Path,
    provider: str,
    contract: GovernanceContract,
    governed_prompt: str,
) -> Path:
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = output_root / now.strftime("%Y-%m-%d")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    block = render_contract_block(contract)
    payload = {
        "provider": provider,
        "generated_at": now.isoformat(),
        "contract_injected": True,
        "contract_hash": contract_hash(block),
        "scope": contract.scope,
        "level": contract.level,
        "lang": contract.lang,
        "contract_fields": contract.as_fields(),
        "governed_prompt_preview": governed_prompt[:500],
    }
    out = artifact_dir / f"{stamp}-{provider}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _read_prompt(args: argparse.Namespace) -> str:
    if args.prompt and args.prompt_file:
        raise ValueError("use either --prompt or --prompt-file, not both")
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if args.prompt:
        return args.prompt
    raise ValueError("missing prompt input: use --prompt or --prompt-file")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a governed prompt with canonical contract injection.")
    parser.add_argument("--provider", required=True, choices=sorted(VALID_PROVIDERS))
    parser.add_argument("--lang", required=True)
    parser.add_argument("--level", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--loaded", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--pressure", required=True)
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--artifact-root",
        default="artifacts/runtime/injection",
        help="Path to injection artifact root.",
    )
    parser.add_argument(
        "--no-artifact",
        action="store_true",
        help="Do not write injection artifact.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    user_prompt = _read_prompt(args)
    contract = GovernanceContract(
        lang=args.lang,
        level=args.level,
        scope=args.scope,
        plan=args.plan,
        loaded=args.loaded,
        context=args.context,
        pressure=args.pressure,
    )

    final_prompt = build_governed_prompt(contract, user_prompt)
    block = render_contract_block(contract)
    rendered_hash = contract_hash(block)

    artifact_path = None
    if not args.no_artifact:
        artifact_path = write_injection_artifact(
            output_root=Path(args.artifact_root),
            provider=args.provider,
            contract=contract,
            governed_prompt=final_prompt,
        )

    if args.format == "json":
        payload = {
            "provider": args.provider,
            "contract_injected": True,
            "contract_hash": rendered_hash,
            "artifact_path": str(artifact_path) if artifact_path else None,
            "prompt": final_prompt,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(final_prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

