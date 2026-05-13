#!/usr/bin/env python3
"""
Thin provider bridge for governed_prompt.py.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


PROVIDER_ALIASES = {
    "chatgpt": "chatgpt",
    "chatgot": "chatgpt",   # common typo alias
    "claude": "claude",
    "gemini": "gemini",
    "gemnin": "gemini",     # common typo alias
}


def normalize_provider(name: str) -> str:
    key = (name or "").strip().lower()
    if key not in PROVIDER_ALIASES:
        raise ValueError(f"unsupported provider alias: {name}")
    return PROVIDER_ALIASES[key]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Provider bridge for governed prompt generation."
    )
    parser.add_argument("--provider", required=True, help="chatgpt|claude|gemini (aliases: chatgot, gemnin)")
    parser.add_argument("--lang", required=True)
    parser.add_argument("--level", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--loaded", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--pressure", required=True)
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file")
    parser.add_argument("--format", choices=("text", "json"), default="json")
    parser.add_argument("--artifact-root", default="artifacts/runtime/injection")
    parser.add_argument("--no-artifact", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    provider = normalize_provider(args.provider)
    runner = Path(__file__).resolve().with_name("governed_prompt.py")

    command = [
        sys.executable,
        str(runner),
        "--provider",
        provider,
        "--lang",
        args.lang,
        "--level",
        args.level,
        "--scope",
        args.scope,
        "--plan",
        args.plan,
        "--loaded",
        args.loaded,
        "--context",
        args.context,
        "--pressure",
        args.pressure,
        "--format",
        args.format,
        "--artifact-root",
        args.artifact_root,
    ]
    if args.prompt:
        command.extend(["--prompt", args.prompt])
    if args.prompt_file:
        command.extend(["--prompt-file", args.prompt_file])
    if args.no_artifact:
        command.append("--no-artifact")

    proc = subprocess.run(command, capture_output=True, text=True)
    if args.format != "json" and proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    if proc.returncode != 0:
        return proc.returncode

    if args.format == "json":
        try:
            payload = json.loads(proc.stdout)
            payload["provider_alias"] = args.provider
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
