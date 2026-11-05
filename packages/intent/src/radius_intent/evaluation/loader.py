"""Gold loading with explicit adapters (the only place gold files are read).

Adapters turn a path into the harness's native gold document (a dict in the
``radius.intent.gold/1`` format, see ``gold.py``); :func:`load_gold` then
validates it. Built-in adapters:

``native``         a ``.json`` file in the native format, or a directory of
                   ``.json`` files each holding either a whole document or one
                   case (``{"case_id": ...}``); all share the ``dataset``
                   header found in ``dataset.json`` if present.
``f14-fixtures``   the F-14 golden fixtures under ``benchmarks/fixtures/intent``
                   (``<id>/intent.md`` + ``expected.json``). Fixture criteria
                   have no character spans, so spans are DERIVED by token
                   overlap with the best list item or paragraph of
                   ``intent.md``; this is an approximation, labelled
                   ``synthetic``, and never a research result.

A custom adapter is selected with ``module.path:function``; it receives the
path (``pathlib.Path``) and returns the native dict. This is how the real
IN-09 gold plugs in (see docs/research/evaluation/INTENT_EVAL.md).
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .gold import GOLD_SCHEMA_ID, GoldDataset, GoldFormatError, parse_gold

Adapter = Callable[[Path], dict[str, Any]]


class GoldLoadError(ValueError):
    """The gold files could not be read or adapted."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GoldLoadError(f"cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise GoldLoadError(f"invalid JSON in {path}: {exc}") from exc


def adapt_native(path: Path) -> dict[str, Any]:
    """Native format: one document, or a directory of case files."""
    if path.is_file():
        doc = _read_json(path)
        if not isinstance(doc, dict):
            raise GoldLoadError(f"{path}: expected a JSON object")
        return doc
    if not path.is_dir():
        raise GoldLoadError(f"gold path does not exist: {path}")
    header_file = path / "dataset.json"
    header: dict[str, Any] = _read_json(header_file) if header_file.exists() else {}
    cases: list[Any] = list(header.pop("cases", []))
    for file in sorted(path.glob("*.json")):
        if file.name == "dataset.json":
            continue
        doc = _read_json(file)
        if isinstance(doc, dict) and "cases" in doc:
            cases.extend(doc["cases"])
        else:
            cases.append(doc)
    return {"schema": GOLD_SCHEMA_ID, **header, "cases": cases}


_TOKEN = re.compile(r"\w+", re.UNICODE)
_LIST_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+")
_STOP = frozenset(
    "a an the is are of to in for and or it its be as at on by with that this "
    "than then from".split()
)


def _blocks(text: str) -> list[tuple[int, int]]:
    """Candidate gold regions of a markdown text: list items and paragraphs.

    A list item runs from after its marker through its indented continuation
    lines; a paragraph runs through consecutive non-blank lines. Headings are
    skipped. Offsets are code points, trimmed of surrounding whitespace.
    """
    out: list[tuple[int, int]] = []
    pos = 0
    current: list[int] | None = None  # [start, end] of the open block
    kind = ""
    for line in text.split("\n"):
        start, end = pos, pos + len(line)
        pos = end + 1
        stripped = line.strip()
        item = _LIST_ITEM.match(line)
        if not stripped or stripped.startswith("#"):
            if current:
                out.append((current[0], current[1]))
            current, kind = None, ""
        elif item:
            if current:
                out.append((current[0], current[1]))
            current, kind = [start + item.end(), end], "item"
        elif current and (kind == "para" or line[:1].isspace()):
            current[1] = end
        else:
            if current:
                out.append((current[0], current[1]))
            current, kind = [start + len(line) - len(line.lstrip()), end], "para"
    if current:
        out.append((current[0], current[1]))
    return [(s, e) for s, e in out if e > s]


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.casefold()) if t not in _STOP}


def _read_fixture_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def adapt_f14_fixtures(path: Path, *, min_overlap: float = 0.5) -> dict[str, Any]:
    """Derive a (synthetic) gold document from the F-14 golden fixtures."""
    if not path.is_dir():
        raise GoldLoadError(f"fixtures directory not found: {path}")
    cases: list[dict[str, Any]] = []
    notes = [
        "Derived from F-14 golden fixtures; criterion spans are auto-aligned to the "
        "best list item or paragraph of intent.md by token overlap (not annotated "
        "by humans).",
    ]
    for fx in sorted(p for p in path.iterdir() if (p / "expected.json").is_file()):
        expected = _read_json(fx / "expected.json")
        intent = fx / "intent.md"
        if not intent.is_file():
            raise GoldLoadError(f"{fx}: intent.md missing")
        text = _read_fixture_text(intent)
        blocks = _blocks(text)
        block_tokens = [_tokens(text[s:e]) for s, e in blocks]
        criteria: list[dict[str, Any]] = []
        for crit in expected.get("criteria", []):
            ctoks = _tokens(str(crit["text"]))
            best, best_score = None, 0.0
            for idx, btoks in enumerate(block_tokens):
                score = len(ctoks & btoks) / len(ctoks) if ctoks else 0.0
                if score > best_score:  # first best block wins ties
                    best, best_score = idx, score
            if best is None or best_score < min_overlap:
                notes.append(
                    f"{fx.name}/{crit['id']}: no span found (best overlap "
                    f"{best_score:.2f}); criterion dropped"
                )
                continue
            start, end = blocks[best]
            criteria.append(
                {
                    "id": str(crit["id"]),
                    "span": {"source_id": "pr_body", "start": start, "end": end},
                    "testability": crit.get("testability"),
                    "text": str(crit["text"]),
                }
            )
        cases.append(
            {
                "case_id": str(expected.get("id", fx.name)),
                "well_specified": None,
                "sources": [{"source_id": "pr_body", "kind": "pr_body", "text": text}],
                "criteria": criteria,
            }
        )
    if not cases:
        raise GoldLoadError(f"no fixtures found under {path}")
    return {
        "schema": GOLD_SCHEMA_ID,
        "name": "f14-fixtures-derived",
        "version": "1",
        "split": "synthetic",
        "synthetic": True,
        "notes": notes,
        "cases": cases,
    }


ADAPTERS: dict[str, Adapter] = {
    "native": adapt_native,
    "f14-fixtures": adapt_f14_fixtures,
}


def register_adapter(name: str, adapter: Adapter) -> None:
    """Make ``adapter`` selectable by ``name`` in this process."""
    ADAPTERS[name] = adapter


def resolve_adapter(name: str) -> Adapter:
    """Look up a built-in adapter or import ``module:function``."""
    if name in ADAPTERS:
        return ADAPTERS[name]
    if ":" in name:
        module_name, _, func_name = name.partition(":")
        try:
            func = getattr(importlib.import_module(module_name), func_name)
        except (ImportError, AttributeError) as exc:
            raise GoldLoadError(f"cannot import adapter {name!r}: {exc}") from exc
        if not callable(func):
            raise GoldLoadError(f"adapter {name!r} is not callable")
        return func
    raise GoldLoadError(
        f"unknown adapter {name!r}; built-in: {sorted(ADAPTERS)} or 'module:function'"
    )


def load_gold(path: str | Path, adapter: str = "native") -> GoldDataset:
    """Read, adapt and validate a gold set."""
    doc = resolve_adapter(adapter)(Path(path))
    try:
        return parse_gold(doc)
    except GoldFormatError as exc:
        raise GoldLoadError(f"{path}: {exc}") from exc
