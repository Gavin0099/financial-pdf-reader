#!/usr/bin/env python3
"""
High-signal public API manifest extraction and diff checks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


C_SHARP_API_RE = re.compile(
    r"\b(?:public|protected\s+internal|public\s+partial)\b.*?(?:(?:=>[^;\n]+;)|(?:\{)|;)",
    re.MULTILINE | re.DOTALL,
)
CPP_API_RE = re.compile(
    r"^\s*(?:class|struct)\s+\w+|^\s*(?:virtual\s+)?(?:[\w:<>*&]+\s+)+\w+\s*\([^;{]*\)\s*(?:const)?\s*;",
    re.MULTILINE,
)
SWIFT_API_RE = re.compile(
    r"^\s*(?:public|open)\s+(?:class|struct|enum|protocol|func|var|let|actor)\b.*$",
    re.MULTILINE,
)
CSHARP_NAMESPACE_RE = re.compile(
    r"\bnamespace\s+(?P<name>[A-Za-z_][A-Za-z0-9_\.]*)\s*(?P<terminator>[{;])"
)
CSHARP_TYPE_RE = re.compile(
    r"\b(public|protected\s+internal|public\s+partial)\s+(?:partial\s+)?"
    r"(class|struct|interface|record)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<type_params>\s*<[^>{;\r\n]+>)?"
)
CSHARP_METHOD_RE = re.compile(
    r"\b(public|protected\s+internal)\s+"
    r"(?:(?:static|virtual|abstract|override|sealed|partial|async|extern|new)\s+)*"
    r"(?P<return>[A-Za-z_][A-Za-z0-9_<>,\.\?\[\]\s]*)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?P<method_type_params><[^>(\r\n]+>)?\s*"
    r"\((?P<params>[^)]*)\)"
)
CSHARP_PROPERTY_HEADER_RE = re.compile(
    r"\b(public|protected\s+internal)\s+"
    r"(?:(?:static|virtual|abstract|override|sealed|new|required)\s+)*"
    r"(?P<type>[A-Za-z_][A-Za-z0-9_<>,\.\?\[\]\s]*)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\{",
    re.MULTILINE,
)


def _extract_matches(text: str, pattern: re.Pattern[str]) -> list[str]:
    return [match.group(0).strip() for match in pattern.finditer(text)]


def _normalize_csharp_type(type_name: str) -> str:
    normalized = " ".join(type_name.split())
    normalized = re.sub(r"\s*\.\s*", ".", normalized)
    normalized = re.sub(r"\s*([<>\[\],\?])\s*", r"\1", normalized)
    normalized = re.sub(r"\s*&\s*", "&", normalized)
    return normalized


def _canonicalize_csharp_type(type_name: str, generic_mapping: dict[str, str] | None = None) -> str:
    normalized = _normalize_csharp_type(type_name)
    if not generic_mapping:
        return normalized
    return re.sub(
        r"\b[A-Za-z_][A-Za-z0-9_]*\b",
        lambda match: generic_mapping.get(match.group(0), match.group(0)),
        normalized,
    )


def _split_top_level_commas(text: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    angle_depth = 0
    square_depth = 0
    paren_depth = 0

    for character in text:
        if character == "," and angle_depth == 0 and square_depth == 0 and paren_depth == 0:
            items.append("".join(current))
            current = []
            continue

        current.append(character)
        if character == "<":
            angle_depth += 1
        elif character == ">" and angle_depth > 0:
            angle_depth -= 1
        elif character == "[":
            square_depth += 1
        elif character == "]" and square_depth > 0:
            square_depth -= 1
        elif character == "(":
            paren_depth += 1
        elif character == ")" and paren_depth > 0:
            paren_depth -= 1

    if current:
        items.append("".join(current))
    return items


def _normalize_csharp_generic_params(
    generic_params: str | None,
    *,
    placeholder_prefix: str,
    start_index: int = 0,
) -> tuple[str, dict[str, str]]:
    if not generic_params:
        return "", {}

    inner = generic_params.strip()
    if inner.startswith("<") and inner.endswith(">"):
        inner = inner[1:-1]

    mapping: dict[str, str] = {}
    canonical_names: list[str] = []
    for index, item in enumerate(_split_top_level_commas(inner)):
        raw = item.strip()
        if not raw:
            continue
        raw = re.sub(r"^(?:in|out)\s+", "", raw)
        name = raw.split()[-1]
        canonical_name = f"{placeholder_prefix}{start_index + index}"
        mapping[name] = canonical_name
        canonical_names.append(canonical_name)

    if not canonical_names:
        return "", {}
    return f"<{','.join(canonical_names)}>", mapping


def _normalize_csharp_params(
    params: str,
    *,
    generic_mapping: dict[str, str] | None = None,
) -> list[str]:
    normalized = []
    for item in _split_top_level_commas(params):
        raw = item.strip()
        if not raw:
            continue
        raw = raw.split("=")[0].strip()
        raw = re.sub(r"^(?:\[[^\]]+\]\s*)+", "", raw)
        parts = raw.split()
        if len(parts) >= 2:
            if parts[0] in {"ref", "out", "in", "params"} and len(parts) >= 3:
                param_type = " ".join(parts[:-1])
            else:
                param_type = " ".join(parts[:-1])
        else:
            param_type = parts[0]
        normalized.append(_canonicalize_csharp_type(param_type, generic_mapping))
    return normalized


def _find_matching_brace(text: str, open_brace_index: int) -> int:
    depth = 0
    for index in range(open_brace_index, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _find_declaration_open_brace(text: str, declaration_end: int) -> int:
    brace_index = text.find("{", declaration_end)
    if brace_index == -1:
        return -1
    terminator_index = text.find(";", declaration_end)
    if terminator_index != -1 and terminator_index < brace_index:
        return -1
    return brace_index


def _extract_csharp_namespace_scopes(text: str) -> list[dict]:
    scopes: list[dict] = []
    for match in CSHARP_NAMESPACE_RE.finditer(text):
        name = match.group("name")
        terminator = match.group("terminator")
        if terminator == "{":
            open_brace_index = match.end() - 1
            close_brace_index = _find_matching_brace(text, open_brace_index)
            body_end = close_brace_index if close_brace_index != -1 else len(text)
            body_start = open_brace_index + 1
        else:
            body_start = match.end()
            body_end = len(text)
        scopes.append(
            {
                "name": name,
                "body_start": body_start,
                "body_end": body_end,
            }
        )
    return scopes


def _find_scope_name(position: int, scopes: list[dict], *, key: str) -> str | None:
    matches = [
        scope[key]
        for scope in scopes
        if scope["body_start"] <= position < scope["body_end"]
    ]
    if not matches:
        return None
    return matches[-1]


def _extract_csharp_property_entries(text: str, find_container) -> list[dict]:
    entries: list[dict] = []

    for match in CSHARP_PROPERTY_HEADER_RE.finditer(text):
        property_type = _normalize_csharp_type(match.group("type"))
        if property_type in {"class", "struct", "interface", "record", "enum"}:
            continue

        open_brace_index = match.end() - 1
        close_brace_index = _find_matching_brace(text, open_brace_index)
        if close_brace_index == -1:
            continue

        body = text[open_brace_index + 1 : close_brace_index]
        accessors = []
        if re.search(r"\bget\b", body):
            accessors.append("get")
        if re.search(r"\binit\b", body):
            accessors.append("init")
        if re.search(r"\bset\b", body):
            accessors.append("set")
        if not accessors:
            continue

        property_name = match.group("name")
        container = find_container(match.start())
        normalized_signature = f"{property_type} {property_name} [{' '.join(accessors)}]"
        entries.append(
            {
                "kind": "property",
                "identity": f"property:{container}.{property_name}",
                "display": match.group(0).strip(),
                "signature": normalized_signature,
                "container": container,
                "property_name": property_name,
                "property_type": property_type,
                "accessors": accessors,
                "position": match.start(),
            }
        )

    return entries


def _extract_csharp_semantic_entries(text: str) -> list[dict]:
    entries: list[dict] = []
    namespace_scopes = _extract_csharp_namespace_scopes(text)
    type_matches = list(CSHARP_TYPE_RE.finditer(text))
    type_scopes: list[dict] = []
    type_metadata: list[dict] = []

    def _find_namespace(position: int) -> str | None:
        return _find_scope_name(position, namespace_scopes, key="name")

    def _find_type_scope(position: int) -> dict | None:
        matches = [
            scope
            for scope in type_scopes
            if scope["body_start"] <= position < scope["body_end"]
        ]
        if not matches:
            return None
        return matches[-1]

    def _find_container(position: int) -> str:
        scope = _find_type_scope(position)
        return scope["full_name"] if scope else "<global>"

    def _find_generic_mapping(position: int) -> dict[str, str]:
        scope = _find_type_scope(position)
        if not scope:
            return {}
        return scope["generic_mapping"]

    for match in type_matches:
        name = match.group("name")
        parent_scope = _find_type_scope(match.start())
        namespace_name = _find_namespace(match.start())
        container_name = parent_scope["full_name"] if parent_scope else namespace_name
        type_param_offset = parent_scope["type_generic_count"] if parent_scope else 0
        canonical_type_params, type_generic_mapping = _normalize_csharp_generic_params(
            match.group("type_params"),
            placeholder_prefix="T",
            start_index=type_param_offset,
        )
        qualified_name = f"{container_name}.{name}{canonical_type_params}" if container_name else f"{name}{canonical_type_params}"
        combined_generic_mapping = dict(parent_scope["generic_mapping"]) if parent_scope else {}
        combined_generic_mapping.update(type_generic_mapping)
        signature = f"{match.group(1)} {match.group(2)} {name}{canonical_type_params}".strip()
        entries.append(
            {
                "kind": "type",
                "identity": f"type:{qualified_name}",
                "display": match.group(0).strip(),
                "signature": signature,
                "container": qualified_name,
                "qualified_name": qualified_name,
                "namespace": namespace_name,
            }
        )

        open_brace_index = _find_declaration_open_brace(text, match.end())
        if open_brace_index != -1:
            close_brace_index = _find_matching_brace(text, open_brace_index)
            scope_entry = {
                "base_name": name,
                "full_name": qualified_name,
                "generic_mapping": combined_generic_mapping,
                "type_generic_count": type_param_offset + len(type_generic_mapping),
                "body_start": open_brace_index + 1,
                "body_end": close_brace_index if close_brace_index != -1 else len(text),
                "open_brace_index": open_brace_index,
                "close_brace_index": close_brace_index if close_brace_index != -1 else len(text),
            }
            type_scopes.append(scope_entry)
            type_metadata.append(
                {
                    "match_start": match.start(),
                    **scope_entry,
                }
            )
        else:
            type_metadata.append(
                {
                    "match_start": match.start(),
                    "base_name": name,
                    "full_name": qualified_name,
                    "generic_mapping": combined_generic_mapping,
                    "type_generic_count": type_param_offset + len(type_generic_mapping),
                    "open_brace_index": -1,
                    "close_brace_index": len(text),
                }
            )

    for match in CSHARP_METHOD_RE.finditer(text):
        method_name = match.group("name")
        container = _find_container(match.start())
        base_generic_mapping = _find_generic_mapping(match.start())
        canonical_method_params, method_generic_mapping = _normalize_csharp_generic_params(
            match.group("method_type_params"),
            placeholder_prefix="M",
        )
        combined_generic_mapping = dict(base_generic_mapping)
        combined_generic_mapping.update(method_generic_mapping)
        return_type = _canonicalize_csharp_type(match.group("return"), combined_generic_mapping)
        params = _normalize_csharp_params(
            match.group("params"),
            generic_mapping=combined_generic_mapping,
        )
        normalized_signature = f"{return_type} {method_name}{canonical_method_params}({', '.join(params)})"
        entries.append(
            {
                "kind": "method",
                "identity": f"method:{container}.{method_name}",
                "display": match.group(0).strip(),
                "signature": normalized_signature,
                "container": container,
                "return_type": return_type,
                "params": params,
                "method_type_params": canonical_method_params,
            }
        )

    property_entries = _extract_csharp_property_entries(text, _find_container)
    for property_entry in property_entries:
        generic_mapping = _find_generic_mapping(property_entry["position"])
        property_entry["property_type"] = _canonicalize_csharp_type(
            property_entry["property_type"],
            generic_mapping,
        )
        property_entry["signature"] = (
            f"{property_entry['property_type']} "
            f"{property_entry['property_name']} "
            f"[{' '.join(property_entry['accessors'])}]"
        )
    entries.extend(property_entries)

    for metadata in type_metadata:
        type_name = metadata["base_name"]
        container = metadata["full_name"]
        ctor_re = re.compile(
            rf"\b(public|protected\s+internal)\s+{re.escape(type_name)}\s*\((?P<params>[^)]*)\)"
        )
        open_brace_index = metadata["open_brace_index"]
        if open_brace_index == -1:
            continue
        search_end = metadata["close_brace_index"]
        type_body = text[open_brace_index + 1 : search_end]
        for match in ctor_re.finditer(type_body):
            params = _normalize_csharp_params(
                match.group("params"),
                generic_mapping=metadata["generic_mapping"],
            )
            normalized_signature = f"{type_name}({', '.join(params)})"
            entries.append(
                {
                    "kind": "constructor",
                    "identity": f"constructor:{container}",
                    "display": match.group(0).strip(),
                    "signature": normalized_signature,
                    "container": container,
                    "params": params,
                }
            )

    return entries


def extract_public_api_manifest(file_paths: list[Path]) -> dict:
    entries: list[dict] = []

    for path in sorted(file_paths):
        suffix = path.suffix.lower()
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel_path = str(path).replace("\\", "/")

        if suffix == ".cs":
            signatures = _extract_matches(text, C_SHARP_API_RE)
            semantic_entries = _extract_csharp_semantic_entries(text)
        elif suffix in {".h", ".hpp", ".hh", ".hxx", ".cpp", ".cc", ".cxx"}:
            signatures = _extract_matches(text, CPP_API_RE)
            semantic_entries = []
        elif suffix == ".swift":
            signatures = _extract_matches(text, SWIFT_API_RE)
            semantic_entries = []
        else:
            continue

        if signatures:
            entry = {"path": rel_path, "signatures": signatures}
            if semantic_entries:
                entry["semantic_entries"] = semantic_entries
            entries.append(entry)

    return {"entries": entries}


def _collect_semantic_entries(manifest: dict) -> dict[str, list[dict]]:
    collected: dict[str, list[dict]] = {}
    for entry in manifest.get("entries", []):
        for semantic in entry.get("semantic_entries", []):
            collected.setdefault(semantic["identity"], []).append(semantic)
    return collected


def _property_write_capability(accessors: list[str]) -> int:
    if "set" in accessors:
        return 2
    if "init" in accessors:
        return 1
    return 0


def _assess_property_compatibility(identity: str, before_entry: dict, after_entry: dict) -> dict:
    breaking_changes: list[str] = []
    non_breaking_changes: list[str] = []

    before_type = before_entry.get("property_type")
    after_type = after_entry.get("property_type")
    if before_type != after_type:
        breaking_changes.append(
            f"Public API signature changed for {identity}: property type changed from {before_type} to {after_type}"
        )

    before_accessors = before_entry.get("accessors", [])
    after_accessors = after_entry.get("accessors", [])
    removed_accessors: list[str] = []
    added_accessors: list[str] = []

    if "get" in before_accessors and "get" not in after_accessors:
        removed_accessors.append("get")
    elif "get" not in before_accessors and "get" in after_accessors:
        added_accessors.append("get")

    before_write = _property_write_capability(before_accessors)
    after_write = _property_write_capability(after_accessors)
    if after_write < before_write:
        if before_write == 2:
            removed_accessors.append("set")
        elif before_write == 1:
            removed_accessors.append("init")
    elif after_write > before_write:
        if after_write == 2:
            added_accessors.append("set")
        elif after_write == 1:
            added_accessors.append("init")

    if removed_accessors:
        breaking_changes.append(
            f"Public API accessor removed for {identity}: removed {sorted(set(removed_accessors))}"
        )
    if added_accessors:
        non_breaking_changes.append(
            f"Public API property expanded for {identity}: added {sorted(set(added_accessors))}"
        )

    return {
        "breaking_changes": breaking_changes,
        "non_breaking_changes": non_breaking_changes,
    }


def _assess_semantic_compatibility(before: dict, after: dict) -> dict:
    before_map = _collect_semantic_entries(before)
    after_map = _collect_semantic_entries(after)

    if not before_map and not after_map:
        return {
            "compatibility_risk": "unknown",
            "breaking_changes": [],
            "non_breaking_changes": [],
        }

    breaking_changes: list[str] = []
    non_breaking_changes: list[str] = []

    identities = sorted(set(before_map) | set(after_map))
    for identity in identities:
        before_entries = before_map.get(identity, [])
        after_entries = after_map.get(identity, [])

        if identity not in before_map:
            non_breaking_changes.append(f"New public API introduced: {identity}")
            continue
        if identity not in after_map:
            breaking_changes.append(f"Public API removed: {identity}")
            continue
        sample_entry = after_entries[0] if after_entries else before_entries[0]
        if (
            sample_entry.get("kind") == "property"
            and len(before_entries) == 1
            and len(after_entries) == 1
        ):
            property_result = _assess_property_compatibility(identity, before_entries[0], after_entries[0])
            breaking_changes.extend(property_result["breaking_changes"])
            non_breaking_changes.extend(property_result["non_breaking_changes"])
            continue

        before_signatures = {entry["signature"] for entry in before_entries}
        after_signatures = {entry["signature"] for entry in after_entries}
        if before_signatures == after_signatures:
            continue

        removed = before_signatures - after_signatures
        added = after_signatures - before_signatures
        if removed:
            breaking_changes.append(
                f"Public API signature changed for {identity}: removed {sorted(removed)}"
            )
        elif added:
            non_breaking_changes.append(
                f"Public API overload or expansion for {identity}: added {sorted(added)}"
            )

    risk = "high" if breaking_changes else "low"
    return {
        "compatibility_risk": risk,
        "breaking_changes": breaking_changes,
        "non_breaking_changes": non_breaking_changes,
    }


def _signature_records(manifest: dict) -> set[tuple[str, bool]]:
    records: set[tuple[str, bool]] = set()
    for entry in manifest.get("entries", []):
        semantic_displays = [item["display"] for item in entry.get("semantic_entries", [])]
        for signature in entry.get("signatures", []):
            covered = any(
                signature == display or signature.startswith(display)
                for display in semantic_displays
            )
            records.add((signature, covered))
    return records


def diff_public_api_manifests(before: dict, after: dict) -> dict:
    before_signatures = _signature_records(before)
    after_signatures = _signature_records(after)

    removed_records = sorted(before_signatures - after_signatures)
    added_records = sorted(after_signatures - before_signatures)
    removed = sorted({signature for signature, _ in removed_records})
    added = sorted({signature for signature, _ in added_records})
    uncovered_removed = [signature for signature, covered in removed_records if not covered]
    uncovered_added = [signature for signature, covered in added_records if not covered]

    warnings: list[str] = []
    errors: list[str] = []

    compatibility = _assess_semantic_compatibility(before, after)
    if uncovered_removed or compatibility["breaking_changes"]:
        errors.append("Public API surface removed or changed.")
    if uncovered_added:
        warnings.append("Public API surface added or changed.")
    for item in compatibility["breaking_changes"]:
        errors.append(item)
    for item in compatibility["non_breaking_changes"]:
        warnings.append(item)

    return {
        "ok": len(errors) == 0,
        "removed": removed,
        "added": added,
        "compatibility_risk": compatibility["compatibility_risk"],
        "breaking_changes": compatibility["breaking_changes"],
        "non_breaking_changes": compatibility["non_breaking_changes"],
        "warnings": warnings,
        "errors": errors,
    }


def check_public_api_diff(before_files: list[Path], after_files: list[Path]) -> dict:
    before_manifest = extract_public_api_manifest(before_files)
    after_manifest = extract_public_api_manifest(after_files)
    diff = diff_public_api_manifests(before_manifest, after_manifest)
    return {
        "ok": diff["ok"],
        "before_manifest": before_manifest,
        "after_manifest": after_manifest,
        "removed": diff["removed"],
        "added": diff["added"],
        "compatibility_risk": diff["compatibility_risk"],
        "breaking_changes": diff["breaking_changes"],
        "non_breaking_changes": diff["non_breaking_changes"],
        "warnings": diff["warnings"],
        "errors": diff["errors"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract and diff public API manifests.")
    parser.add_argument("--before", action="append", default=[], help="Path to a pre-change source file")
    parser.add_argument("--after", action="append", default=[], help="Path to a post-change source file")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    result = check_public_api_diff(
        [Path(path) for path in args.before],
        [Path(path) for path in args.after],
    )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"ok={result['ok']}")
        print(f"removed={len(result['removed'])}")
        print(f"added={len(result['added'])}")
        print(f"compatibility_risk={result['compatibility_risk']}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
        for error in result["errors"]:
            print(f"error: {error}")

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
