#!/usr/bin/env python
"""Lightweight OpenAPI breaking-change guard (a stand-in for ``oasdiff``).

Compares an old and a new ``openapi.json`` structurally and reports changes that
break clients of ``stable`` operations (``x-stability`` of the OLD document;
``beta`` changes are reported as warnings, ``alpha``/``internal`` are ignored):

* operation removed, or its ``operationId`` renamed;
* a new required parameter, or an optional one that became required;
* a request body that became required, a new required request property, a
  request property whose type narrowed or whose enum lost a value;
* a 2xx response removed, a response property removed or its type widened.

It is deliberately small: no ``oneOf`` reasoning, no media-type negotiation, JSON
bodies only. For richer checks run ``oasdiff breaking old.json new.json``
(https://github.com/oasdiff/oasdiff).

    python scripts/openapi_diff.py --base origin/develop        # git ref
    python scripts/openapi_diff.py --old old.json --new new.json

Intentional breaks are acknowledged in ``docs/api/breaking-changes-ack.txt``
(one ``METHOD /path`` per line), together with a major version bump and a
CHANGELOG entry as described in ``docs/api/STABILITY.md``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPEC_REL = "docs/api/openapi.json"
ACK_PATH = ROOT / "docs" / "api" / "breaking-changes-ack.txt"
METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_MAX_DEPTH = 6


@dataclass(frozen=True)
class Finding:
    """One detected change."""

    level: str  # "breaking" | "warning"
    key: str  # "METHOD /path" of the operation
    message: str

    def render(self) -> str:
        return f"[{self.level}] {self.key}: {self.message}"


def _resolve(doc: dict[str, Any], schema: Any) -> Any:
    hops = 0
    while isinstance(schema, dict) and "$ref" in schema and hops < 20:
        node: Any = doc
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        schema = node
        hops += 1
    return schema


def _flatten(doc: dict[str, Any], schema: Any, depth: int = 0) -> Any:
    """Resolve ``$ref`` and merge ``allOf`` branches into one schema object."""

    schema = _resolve(doc, schema)
    if not isinstance(schema, dict) or "allOf" not in schema or depth > _MAX_DEPTH:
        return schema
    merged: dict[str, Any] = {k: v for k, v in schema.items() if k != "allOf"}
    for branch in schema["allOf"]:
        part = _flatten(doc, branch, depth + 1)
        if not isinstance(part, dict):
            continue
        merged.setdefault("properties", {}).update(part.get("properties", {}))
        merged["required"] = [*merged.get("required", []), *part.get("required", [])]
        for key in ("type", "items", "enum"):
            if key in part:
                merged.setdefault(key, part[key])
    return merged


def _types(schema: Any) -> frozenset[str]:
    if not isinstance(schema, dict):
        return frozenset()
    if "type" in schema:
        declared = schema["type"]
        return frozenset(declared if isinstance(declared, list) else [declared])
    found: set[str] = set()
    for branch in [*schema.get("anyOf", []), *schema.get("oneOf", [])]:
        found |= _types(_resolve({}, branch))
    return frozenset(found)


def _compare_schema(  # noqa: PLR0913
    old_doc: dict[str, Any],
    new_doc: dict[str, Any],
    old: Any,
    new: Any,
    *,
    request: bool,
    path: str,
    out: list[str],
    depth: int = 0,
) -> None:
    """Append breaking differences between two schemas to ``out``."""

    old, new = _flatten(old_doc, old), _flatten(new_doc, new)
    if depth > _MAX_DEPTH or not isinstance(old, dict) or not isinstance(new, dict):
        return
    old_types, new_types = _types(old), _types(new)
    if old_types and new_types:
        # Requests may only widen what they accept; responses may only narrow.
        compatible = old_types <= new_types if request else new_types <= old_types
        if not compatible:
            out.append(f"{path or 'body'}: type {sorted(old_types)} -> {sorted(new_types)}")
            return
    old_props, new_props = old.get("properties", {}), new.get("properties", {})
    if request:
        for name in sorted(set(new.get("required", [])) - set(old.get("required", []))):
            out.append(f"{path}.{name}: new required request property")
        if "enum" in old and "enum" in new:
            for value in sorted(set(old["enum"]) - set(new["enum"]), key=str):
                out.append(f"{path or 'body'}: enum value {value!r} no longer accepted")
    else:
        for name in sorted(set(old_props) - set(new_props)):
            out.append(f"{path}.{name}: response property removed")
    for name in sorted(set(old_props) & set(new_props)):
        _compare_schema(
            old_doc,
            new_doc,
            old_props[name],
            new_props[name],
            request=request,
            path=f"{path}.{name}",
            out=out,
            depth=depth + 1,
        )
    if "items" in old and "items" in new:
        _compare_schema(
            old_doc,
            new_doc,
            old["items"],
            new["items"],
            request=request,
            path=f"{path}[]",
            out=out,
            depth=depth + 1,
        )


def _params(doc: dict[str, Any], op: dict[str, Any], item: dict[str, Any]) -> dict:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for param in [*item.get("parameters", []), *op.get("parameters", [])]:
        param = _resolve(doc, param)
        merged[(param["in"], param["name"].lower())] = param
    return merged


def _json_schema(doc: dict[str, Any], container: dict[str, Any] | None) -> Any:
    resolved = _resolve(doc, container or {})
    media = (resolved.get("content") or {}).get("application/json")
    return None if media is None else media.get("schema")


def _diff_operation(
    old: dict[str, Any],
    new: dict[str, Any],
    old_item: dict[str, Any],
    new_item: dict[str, Any],
    method: str,
    key: str,
    level: str,
) -> list[Finding]:
    old_op, new_op = old_item[method], new_item[method]
    found: list[Finding] = []

    def add(message: str, as_level: str = level) -> None:
        found.append(Finding(as_level, key, message))

    if old_op.get("operationId") != new_op.get("operationId"):
        add(f"operationId {old_op.get('operationId')!r} -> {new_op.get('operationId')!r}")
    old_p, new_p = _params(old, old_op, old_item), _params(new, new_op, new_item)
    for pkey, param in sorted(new_p.items()):
        before = old_p.get(pkey)
        if param.get("required") and (before is None or not before.get("required")):
            verb = "new required" if before is None else "now required"
            add(f"{verb} parameter {pkey[0]}:{param['name']}")
    for pkey in sorted(set(old_p) - set(new_p)):
        add(f"parameter {pkey[1]} removed", "warning")
    old_body, new_body = old_op.get("requestBody"), new_op.get("requestBody")
    if (
        new_body
        and _resolve(new, new_body).get("required")
        and not (old_body and _resolve(old, old_body).get("required"))
    ):
        add("request body is now required")
    if old_body and new_body:
        diffs: list[str] = []
        _compare_schema(
            old,
            new,
            _json_schema(old, old_body),
            _json_schema(new, new_body),
            request=True,
            path="",
            out=diffs,
        )
        for message in diffs:
            add(f"request {message}")
    for status, response in sorted(old_op.get("responses", {}).items()):
        if not status.startswith("2"):
            continue
        new_response = new_op.get("responses", {}).get(status)
        if new_response is None:
            add(f"success response {status} removed")
            continue
        diffs = []
        _compare_schema(
            old,
            new,
            _json_schema(old, response),
            _json_schema(new, new_response),
            request=False,
            path="",
            out=diffs,
        )
        for message in diffs:
            add(f"response {status} {message}")
    return found


def diff_specs(old: dict[str, Any], new: dict[str, Any]) -> list[Finding]:
    """Return findings for changes from ``old`` to ``new`` (deterministic order)."""

    findings: list[Finding] = []
    new_by_id = {
        op.get("operationId"): (method, path)
        for path, item in new.get("paths", {}).items()
        for method, op in item.items()
        if method in METHODS
    }
    for path, old_item in sorted(old.get("paths", {}).items()):
        for method in METHODS:
            old_op = old_item.get(method)
            if old_op is None:
                continue
            stability = old_op.get("x-stability", "stable")
            if stability not in {"stable", "beta"}:
                continue
            level = "breaking" if stability == "stable" else "warning"
            key = f"{method.upper()} {path}"
            new_item = new.get("paths", {}).get(path, {})
            if method not in new_item:
                moved = new_by_id.get(old_op.get("operationId"))
                where = f" (now {moved[0].upper()} {moved[1]})" if moved else ""
                findings.append(Finding(level, key, f"operation removed or renamed{where}"))
                continue
            findings.extend(
                _diff_operation(old, new, old_item, new_item, method, key, level)
            )
    return findings


def load_acknowledged(path: Path = ACK_PATH) -> set[str]:
    """Return the acknowledged ``METHOD /path`` keys (``#`` starts a comment)."""

    if not path.exists():
        return set()
    lines = (line.split("#", 1)[0].strip() for line in path.read_text("utf-8").splitlines())
    return {line for line in lines if line}


def unacknowledged_breaking(findings: list[Finding], acknowledged: set[str]) -> list[Finding]:
    """Breaking findings whose operation is not in the acknowledgement file."""

    return [f for f in findings if f.level == "breaking" and f.key not in acknowledged]


def git_show(ref: str, rel: str = SPEC_REL) -> dict[str, Any] | None:
    """Return the spec committed at ``ref``, or ``None`` when unavailable."""

    result = subprocess.run(  # noqa: S603
        ["git", "show", f"{ref}:{rel}"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout.decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="git ref holding the previous docs/api/openapi.json")
    parser.add_argument("--old", type=Path)
    parser.add_argument("--new", type=Path, default=ROOT / SPEC_REL)
    args = parser.parse_args(argv)

    if args.old:
        old = json.loads(args.old.read_text(encoding="utf-8"))
    elif args.base:
        old = git_show(args.base)
        if old is None:
            print(f"No {SPEC_REL} at {args.base}; nothing to compare.")
            return 0
    else:
        parser.error("pass --base <git ref> or --old <file>")
    new = json.loads(args.new.read_text(encoding="utf-8"))

    findings = diff_specs(old, new)
    for finding in findings:
        print(finding.render())
    blocking = unacknowledged_breaking(findings, load_acknowledged())
    if blocking:
        print(
            f"{len(blocking)} unacknowledged breaking change(s). Bump the major version, "
            f"add a CHANGELOG entry and list the operation(s) in {ACK_PATH.name}.",
            file=sys.stderr,
        )
        return 1
    print("No unacknowledged breaking changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
