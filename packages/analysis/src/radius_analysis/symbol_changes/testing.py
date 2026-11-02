"""Test-support helpers for LK-01: build git-style diffs from file maps and run extraction.

Shipped inside the package (not in tests/) so tests import it by absolute name regardless of
pytest import mode."""

from __future__ import annotations

import difflib
import textwrap
from collections.abc import Mapping

from radius_analysis.symbol_changes import (
    DictSnapshot,
    ExtractionOptions,
    SymbolChangeSet,
    extract_symbol_changes,
)


def dedent(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def _lines(text: str) -> list[str]:
    parts = text.split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return parts


def _body(old: str, new: str, old_name: str, new_name: str, context: int) -> list[str]:
    out = list(
        difflib.unified_diff(
            _lines(old), _lines(new), f"a/{old_name}", f"b/{new_name}", lineterm="", n=context
        )
    )
    return out


def make_diff(
    base: Mapping[str, str],
    head: Mapping[str, str],
    *,
    renames: Mapping[str, str] | None = None,
    context: int = 3,
) -> str:
    """Return a ``git diff``-like text for two file maps (``renames``: old -> new)."""

    renames = dict(renames or {})
    reverse = {v: k for k, v in renames.items()}
    out: list[str] = []
    for path in sorted(set(base) | set(head)):
        if path in renames:
            continue  # emitted under its new name
        if path in reverse:
            old = reverse[path]
            old_text, new_text = base[old], head[path]
            out += [
                f"diff --git a/{old} b/{path}",
                "similarity index 90%",
                f"rename from {old}",
                f"rename to {path}",
            ]
            if old_text != new_text:
                body = _body(old_text, new_text, old, path, context)
                out += body
            continue
        if path in base and path in head:
            if base[path] == head[path]:
                continue
            out.append(f"diff --git a/{path} b/{path}")
            out += _body(base[path], head[path], path, path, context)
        elif path in head:
            out += [f"diff --git a/{path} b/{path}", "new file mode 100644"]
            body = _body("", head[path], path, path, context)
            body[0] = "--- /dev/null"
            out += body
        else:
            out += [f"diff --git a/{path} b/{path}", "deleted file mode 100644"]
            body = _body(base[path], "", path, path, context)
            body[1] = "+++ /dev/null"
            out += body
    return "\n".join(out) + ("\n" if out else "")


def run(
    base: Mapping[str, str],
    head: Mapping[str, str],
    *,
    renames: Mapping[str, str] | None = None,
    context: int = 3,
    options: ExtractionOptions | None = None,
    diff: str | None = None,
) -> SymbolChangeSet:
    text = diff if diff is not None else make_diff(base, head, renames=renames, context=context)
    return extract_symbol_changes(DictSnapshot(base), DictSnapshot(head), text, options)


def summary(result: SymbolChangeSet) -> list[tuple[str, str, str]]:
    """Compact ``(qualified_name, kind, change_kind)`` triples in output order."""

    return [(s.qualified_name, s.kind, s.change_kind.value) for s in result.symbols]
