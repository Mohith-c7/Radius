"""Strict parser for ``.radius/intent.yml`` (a safe YAML subset).

PyYAML is not a declared dependency of Radius (it is only transitive), so this
module implements the small subset the schema needs and rejects everything
else with a line-numbered error: no tags, anchors, aliases, merge keys, flow
mappings, multi-document streams, tabs or multi-line flow scalars. It never
evaluates anything and runs in linear time.

Supported: ``key: value`` mappings, ``- item`` sequences, plain / ``'single'``
/ ``"double"`` quoted scalars, single-line ``[a, b]`` lists, ``|`` and ``>``
block scalars, ``#`` comments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Union

from radius_intent.domain import CriterionHints

from .candidates import Candidate, Collector
from .report import DiagnosticKind, Severity
from .text import Line, collapse

SPEC_VERSION = 1
KNOWN_TOP_KEYS = frozenset({"version", "criteria"})
KNOWN_CRITERION_KEYS = frozenset({"id", "text", "weight", "paths", "tests"})
MAX_SPEC_CRITERIA = 500
MAX_HINTS = 50
MAX_TEXT = 2000

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
_INT = re.compile(r"[-+]?\d+")
_FLOAT = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
_LABEL = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_BLOCK = re.compile(r"[|>][+-]?")
_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "/": "/", "0": "\0"}


@dataclass
class _Scalar:
    value: object
    kind: str  # str | int | float | bool | null | invalid
    line: int
    start: int
    end: int
    message: str = ""


@dataclass
class _Map:
    line: int
    entries: list[tuple[str, int, _Node]] = field(default_factory=list)


@dataclass
class _Seq:
    line: int
    items: list[_Node] = field(default_factory=list)


_Node = Union[_Scalar, _Map, _Seq, None]  # noqa: UP007  (forward-ref alias)


class _Fatal(Exception):
    def __init__(self, line: int, message: str) -> None:
        super().__init__(message)
        self.line = line
        self.message = message


class _Parser:
    def __init__(self, lines: list[Line], collector: Collector) -> None:
        self.lines = [[ln.number, ln.start, ln.text] for ln in lines]
        self.col = collector

    # -- line helpers -------------------------------------------------------

    def _blank(self, idx: int) -> bool:
        t = self.lines[idx][2].strip()
        return not t or t.startswith("#")

    def _is_marker(self, idx: int) -> bool:
        return self.lines[idx][2].rstrip() in ("---", "...")

    def _skip(self, idx: int) -> int:
        while idx < len(self.lines) and self._blank(idx):
            idx += 1
        return idx

    def _indent(self, idx: int) -> int:
        text = self.lines[idx][2]
        n = len(text) - len(text.lstrip(" "))
        if text[n : n + 1] == "\t":
            raise _Fatal(self.lines[idx][0], "Tabs are not allowed for indentation.")
        return n

    def _err(self, idx: int, message: str) -> _Fatal:
        return _Fatal(self.lines[idx][0], message)

    # -- document -----------------------------------------------------------

    def parse(self) -> _Node:
        idx = self._skip(0)
        if idx < len(self.lines) and self.lines[idx][2].rstrip() == "---":
            idx = self._skip(idx + 1)
        if idx >= len(self.lines):
            return None
        node, idx = self._node(idx, 0)
        idx = self._skip(idx)
        if idx < len(self.lines):
            text = self.lines[idx][2].strip()
            if text in ("---", "..."):
                if text == "---":
                    raise self._err(idx, "Multiple YAML documents are not supported.")
                return node
            raise self._err(idx, "Unexpected content after the document.")
        return node

    def _node(self, idx: int, min_indent: int) -> tuple[_Node, int]:
        idx = self._skip(idx)
        if idx >= len(self.lines):
            return None, idx
        indent = self._indent(idx)
        if indent < min_indent:
            return None, idx
        body = self.lines[idx][2][indent:]
        if body == "-" or body.startswith("- "):
            return self._seq(idx, indent)
        return self._map(idx, indent)

    # -- mappings -----------------------------------------------------------

    def _map(self, idx: int, indent: int) -> tuple[_Map, int]:
        result = _Map(self.lines[idx][0])
        seen: set[str] = set()
        while True:
            idx = self._skip(idx)
            if idx >= len(self.lines):
                break
            if self._is_marker(idx):
                break
            cur = self._indent(idx)
            if cur < indent:
                break
            number = self.lines[idx][0]
            if cur > indent:
                raise self._err(idx, "Unexpected indentation.")
            body = self.lines[idx][2][indent:]
            if body == "-" or body.startswith("- "):
                break
            key, rest, rest_col = self._split_key(idx, indent, body)
            if key in seen:
                self.col.note(
                    DiagnosticKind.PARSE_ERROR,
                    "spec_duplicate_key",
                    f"Duplicate key '{key}'; the first value is kept.",
                    severity=Severity.ERROR,
                    line=number,
                )
            value, idx = self._value(idx, indent, rest, rest_col)
            if key not in seen:
                seen.add(key)
                result.entries.append((key, number, value))
        return result, idx

    def _split_key(self, idx: int, indent: int, body: str) -> tuple[str, str, int]:
        colon = body.find(":")
        while colon >= 0 and not (colon + 1 == len(body) or body[colon + 1] in " \t"):
            colon = body.find(":", colon + 1)
        key = body[:colon].strip() if colon >= 0 else ""
        if colon < 0 or not _KEY.fullmatch(key):
            raise self._err(idx, "Expected 'key: value' with a plain key.")
        rest = body[colon + 1 :]
        lead = len(rest) - len(rest.lstrip())
        return key, rest.strip(), indent + colon + 1 + lead

    def _value(self, idx: int, indent: int, rest: str, col: int) -> tuple[_Node, int]:
        number, start, text = self.lines[idx]
        if not rest or rest.startswith("#"):
            nxt = self._skip(idx + 1)
            if nxt < len(self.lines):
                ind = self._indent(nxt)
                body = self.lines[nxt][2][ind:]
                if ind > indent:
                    return self._node(nxt, indent + 1)
                if ind == indent and (body == "-" or body.startswith("- ")):
                    return self._seq(nxt, indent)
            return None, idx + 1
        if _BLOCK.fullmatch(rest.split("#", 1)[0].strip()) and rest[0] in "|>":
            return self._block_scalar(idx, indent, rest[0])
        if rest[0] in "&*!%@`{":
            kind = {
                "&": "anchors",
                "*": "aliases",
                "!": "tags",
                "{": "flow mappings",
            }.get(rest[0], "this indicator")
            return _Scalar(
                None,
                "invalid",
                number,
                start + col,
                start + col + 1,
                f"YAML {kind} are not supported.",
            ), idx + 1
        if rest[0] == "[":
            return self._flow_seq(idx, col), idx + 1
        return self._scalar(number, start, text, col), idx + 1

    # -- sequences ----------------------------------------------------------

    def _seq(self, idx: int, indent: int) -> tuple[_Seq, int]:
        result = _Seq(self.lines[idx][0])
        while True:
            idx = self._skip(idx)
            if idx >= len(self.lines):
                break
            if self._is_marker(idx):
                break
            cur = self._indent(idx)
            if cur < indent:
                break
            if cur > indent:
                raise self._err(idx, "Unexpected indentation.")
            body = self.lines[idx][2][indent:]
            if not (body == "-" or body.startswith("- ")):
                break
            after = body[1:]
            lead = len(after) - len(after.lstrip())
            rest = after.strip()
            col = indent + 1 + lead
            if not rest or rest.startswith("#"):
                node, idx = self._node(idx + 1, indent + 1)
                result.items.append(node)
            elif rest[0] in "\"'[&*!{" or not self._looks_like_entry(rest):
                node, idx = self._value(idx, indent, rest, col)
                result.items.append(node)
            else:
                line = self.lines[idx]
                line[2] = " " * col + line[2][col:]
                node, idx = self._map(idx, col)
                result.items.append(node)
        return result, idx

    @staticmethod
    def _looks_like_entry(rest: str) -> bool:
        colon = rest.find(":")
        while colon >= 0 and not (colon + 1 == len(rest) or rest[colon + 1] in " \t"):
            colon = rest.find(":", colon + 1)
        return colon > 0 and _KEY.fullmatch(rest[:colon].strip()) is not None

    # -- scalars ------------------------------------------------------------

    def _scalar(self, number: int, start: int, text: str, col: int) -> _Scalar:
        c = text[col]
        if c in "\"'":
            return self._quoted(number, start, text, col)
        raw = text[col:]
        hash_at = raw.find(" #")
        body = (raw if hash_at < 0 else raw[:hash_at]).rstrip()
        a, b = start + col, start + col + len(body)
        if body.endswith(":") or ": " in body:
            return _Scalar(
                None,
                "invalid",
                number,
                a,
                b,
                "Unquoted ':' in a value; wrap the value in quotes.",
            )
        return _Scalar(*_resolve(body), number, a, b)

    def _quoted(self, number: int, start: int, text: str, col: int) -> _Scalar:
        quote = text[col]
        pos = col + 1
        out: list[str] = []
        while pos < len(text):
            ch = text[pos]
            if quote == '"' and ch == "\\":
                nxt = text[pos + 1 : pos + 2]
                if nxt in _ESCAPES:
                    out.append(_ESCAPES[nxt])
                    pos += 2
                    continue
                return _Scalar(
                    None,
                    "invalid",
                    number,
                    start + col,
                    start + pos,
                    f"Unsupported escape '\\{nxt}'.",
                )
            if ch == quote:
                if quote == "'" and text[pos + 1 : pos + 2] == "'":
                    out.append("'")
                    pos += 2
                    continue
                tail = text[pos + 1 :].strip()
                if tail and not tail.startswith("#"):
                    return _Scalar(
                        None,
                        "invalid",
                        number,
                        start + col,
                        start + pos,
                        "Unexpected text after quoted value.",
                    )
                return _Scalar(
                    "".join(out), "str", number, start + col + 1, start + pos
                )
            out.append(ch)
            pos += 1
        return _Scalar(
            None,
            "invalid",
            number,
            start + col,
            start + len(text),
            "Unterminated quoted value (multi-line scalars are not supported).",
        )

    def _flow_seq(self, idx: int, col: int) -> _Node:
        number, start, text = self.lines[idx]
        items: list[_Node] = []
        pos = col + 1
        size = len(text)
        while True:
            while pos < size and text[pos] in " \t":
                pos += 1
            if pos >= size:
                return _Scalar(
                    None,
                    "invalid",
                    number,
                    start + col,
                    start + size,
                    "Unterminated '[' list (multi-line lists are not supported).",
                )
            if text[pos] == "]":
                break
            if text[pos] in "\"'":
                scalar = self._quoted_prefix(number, start, text, pos)
                if scalar is None:
                    return _Scalar(
                        None,
                        "invalid",
                        number,
                        start + pos,
                        start + size,
                        "Bad quoted item in list.",
                    )
                item, pos = scalar
            else:
                end = pos
                while end < size and text[end] not in ",]":
                    end += 1
                body = text[pos:end].rstrip()
                if not body or body[0] in "&*!{[":
                    return _Scalar(
                        None,
                        "invalid",
                        number,
                        start + pos,
                        start + end,
                        "Unsupported or empty list item.",
                    )
                item = _Scalar(
                    *_resolve(body), number, start + pos, start + pos + len(body)
                )
                pos = end
            items.append(item)
            while pos < size and text[pos] in " \t":
                pos += 1
            if pos < size and text[pos] == ",":
                pos += 1
            elif pos >= size or text[pos] != "]":
                return _Scalar(
                    None,
                    "invalid",
                    number,
                    start + pos,
                    start + size,
                    "Expected ',' or ']' in list.",
                )
        tail = text[pos + 1 :].strip()
        if tail and not tail.startswith("#"):
            return _Scalar(
                None,
                "invalid",
                number,
                start + pos,
                start + size,
                "Unexpected text after list.",
            )
        return _Seq(number, items)

    def _quoted_prefix(
        self, number: int, start: int, text: str, pos: int
    ) -> tuple[_Scalar, int] | None:
        quote = text[pos]
        probe = pos + 1
        while probe < len(text):
            if quote == '"' and text[probe] == "\\":
                probe += 2
                continue
            if text[probe] == quote:
                if quote == "'" and text[probe + 1 : probe + 2] == "'":
                    probe += 2
                    continue
                piece = text[: probe + 1]
                scalar = self._quoted(number, start, piece, pos)
                if scalar.kind == "invalid":
                    return None
                return scalar, probe + 1
            probe += 1
        return None

    def _block_scalar(self, idx: int, indent: int, style: str) -> tuple[_Scalar, int]:
        number = self.lines[idx][0]
        body: list[tuple[int, int, str]] = []  # (start, indent, text)
        j = idx + 1
        content = -1
        while j < len(self.lines):
            text = self.lines[j][2]
            if not text.strip():
                body.append((self.lines[j][1], 0, ""))
                j += 1
                continue
            ind = len(text) - len(text.lstrip(" "))
            if text[ind : ind + 1] == "\t":
                raise self._err(j, "Tabs are not allowed for indentation.")
            if ind <= indent:
                break
            if content < 0:
                content = ind
            if ind < content:
                raise self._err(j, "Block scalar line is under-indented.")
            body.append((self.lines[j][1], ind, text))
            j += 1
        while body and not body[-1][2]:
            body.pop()
        if content < 0 or not body:
            return _Scalar(
                None,
                "invalid",
                number,
                self.lines[idx][1],
                self.lines[idx][1] + len(self.lines[idx][2]),
                "Empty block scalar.",
            ), j
        pieces = [t[content:] if t else "" for _, _, t in body]
        if style == "|":
            value = "\n".join(pieces)
        else:
            value = " ".join(p if p else "\n" for p in pieces)
        first = next(b for b in body if b[2])
        last = body[-1]
        return _Scalar(
            value.strip(),
            "str",
            number,
            first[0] + content,
            last[0] + len(last[2].rstrip()),
        ), j


def _resolve(body: str) -> tuple[object, str]:
    """Resolve a plain scalar to (value, kind)."""
    if body in ("true", "false"):
        return body == "true", "bool"
    if body in ("null", "~", ""):
        return None, "null"
    if _INT.fullmatch(body):
        return int(body), "int"
    if _FLOAT.fullmatch(body):
        return float(body), "float"
    return body, "str"


# -- validation ---------------------------------------------------------------


def _unsafe_path(path: str) -> bool:
    head = path.split("::", 1)[0]
    return (
        head.startswith(("/", "\\"))
        or "\\" in head
        or "\0" in path
        or ".." in head.split("/")
        or (len(head) > 1 and head[1] == ":")
    )


class _Validator:
    def __init__(self, source_id: str, col: Collector) -> None:
        self.col = col
        self.source_id = source_id

    def error(self, code: str, message: str, line: int | None) -> None:
        self.col.note(
            DiagnosticKind.PARSE_ERROR,
            code,
            message,
            severity=Severity.ERROR,
            line=line,
        )

    def warn(self, code: str, message: str, line: int | None) -> None:
        self.col.note(
            DiagnosticKind.PARSE_ERROR,
            code,
            message,
            severity=Severity.WARNING,
            line=line,
        )

    def run(self, root: _Node) -> None:
        if root is None:
            self.col.skip("spec_empty", "The spec file has no content.")
            return
        if not isinstance(root, _Map):
            self.error(
                "spec_not_mapping",
                "Spec must be a mapping with 'version' and 'criteria'.",
                1,
            )
            return
        entries = {k: (ln, v) for k, ln, v in root.entries}
        for key, line, _ in root.entries:
            if key not in KNOWN_TOP_KEYS:
                self.warn(
                    "spec_unknown_key",
                    f"Unknown top-level key '{key}' (ignored).",
                    line,
                )
        if "version" not in entries:
            self.error(
                "spec_missing_version", "Missing required key 'version'.", root.line
            )
            return
        vline, version = entries["version"]
        if (
            not isinstance(version, _Scalar)
            or version.kind != "int"
            or version.value != SPEC_VERSION
        ):
            self.error(
                "spec_unsupported_version", f"'version' must be {SPEC_VERSION}.", vline
            )
            return
        if "criteria" not in entries:
            self.error(
                "spec_missing_criteria", "Missing required key 'criteria'.", root.line
            )
            return
        cline, criteria = entries["criteria"]
        if criteria is None:
            return
        if not isinstance(criteria, _Seq):
            self.error("spec_criteria_not_list", "'criteria' must be a list.", cline)
            return
        seen_ids: set[str] = set()
        for item in criteria.items:
            if len(self.col.candidates) >= MAX_SPEC_CRITERIA:
                self.col.note(
                    DiagnosticKind.LIMIT,
                    "max_criteria",
                    f"Only the first {MAX_SPEC_CRITERIA} spec criteria are read.",
                    severity=Severity.WARNING,
                    line=cline,
                )
                break
            self._criterion(item, cline, seen_ids)

    def _criterion(self, item: _Node, fallback: int, seen_ids: set[str]) -> None:
        if not isinstance(item, _Map):
            line = item.line if isinstance(item, (_Scalar, _Seq)) else fallback
            self.error(
                "spec_criterion_not_mapping", "Each criterion must be a mapping.", line
            )
            return
        fields = {}
        for key, line, value in item.entries:
            if key not in KNOWN_CRITERION_KEYS:
                self.warn(
                    "spec_unknown_key",
                    f"Unknown criterion key '{key}' (ignored).",
                    line,
                )
            else:
                fields[key] = (line, value)
        errors_before = sum(
            1 for d in self.col.diagnostics if d.severity is Severity.ERROR
        )
        label = self._label(fields.get("id"), seen_ids)
        text = self._text(fields.get("text"), item.line)
        weight = self._weight(fields.get("weight"))
        paths = self._hints("paths", fields.get("paths"), False)
        tests = self._hints("tests", fields.get("tests"), True)
        errors_after = sum(
            1 for d in self.col.diagnostics if d.severity is Severity.ERROR
        )
        if errors_after != errors_before or text is None:
            return
        scalar, value = text
        hints = CriterionHints(paths=paths, tests=tests, label=label)
        self.col.add(
            Candidate(
                scalar.start,
                scalar.end,
                collapse(value),
                "spec_file",
                None,
                None,
                0,
                weight,
                hints,
            )
        )

    def _label(self, field_: tuple[int, _Node] | None, seen: set[str]) -> str | None:
        if field_ is None:
            return None
        line, node = field_
        if not isinstance(node, _Scalar) or node.kind not in ("str", "int"):
            self.error("spec_invalid_id", "'id' must be a short string.", line)
            return None
        label = str(node.value)
        if not _LABEL.fullmatch(label):
            self.error(
                "spec_invalid_id",
                "'id' may contain only letters, digits, '_', '.', '-' (max 64).",
                line,
            )
        elif label in seen:
            self.error("spec_duplicate_id", f"Duplicate criterion id '{label}'.", line)
        else:
            seen.add(label)
            return label
        return None

    def _text(
        self, field_: tuple[int, _Node] | None, fallback: int
    ) -> tuple[_Scalar, str] | None:
        if field_ is None:
            self.error(
                "spec_missing_text",
                "Criterion is missing required key 'text'.",
                fallback,
            )
            return None
        line, node = field_
        if isinstance(node, _Scalar) and node.kind == "invalid":
            self.error("spec_invalid_text", node.message, node.line)
            return None
        if (
            not isinstance(node, _Scalar)
            or node.kind != "str"
            or not str(node.value).strip()
        ):
            self.error("spec_invalid_text", "'text' must be a non-empty string.", line)
            return None
        value = str(node.value)
        if len(value) > MAX_TEXT or "\0" in value:
            self.error(
                "spec_invalid_text",
                f"'text' must be at most {MAX_TEXT} characters.",
                line,
            )
            return None
        if node.end <= node.start:
            self.error("spec_invalid_text", "'text' must be non-empty.", line)
            return None
        return node, value

    def _weight(self, field_: tuple[int, _Node] | None) -> float:
        if field_ is None:
            return 1.0
        line, node = field_
        if isinstance(node, _Scalar) and node.kind == "invalid":
            self.error("spec_invalid_weight", node.message, node.line)
        elif not isinstance(node, _Scalar) or node.kind not in ("int", "float"):
            self.error(
                "spec_invalid_weight", "'weight' must be a number in (0, 1].", line
            )
        else:
            weight = float(node.value)  # type: ignore[arg-type]
            if 0 < weight <= 1:
                return weight
            self.error("spec_invalid_weight", "'weight' must be in (0, 1].", line)
        return 1.0

    def _hints(
        self, name: str, field_: tuple[int, _Node] | None, is_test: bool
    ) -> tuple[str, ...]:
        if field_ is None:
            return ()
        line, node = field_
        code = f"spec_invalid_{name}"
        if isinstance(node, _Scalar) and node.kind == "invalid":
            self.error(code, node.message, node.line)
            return ()
        if node is None or (isinstance(node, _Scalar) and node.kind == "null"):
            return ()
        if not isinstance(node, _Seq) or len(node.items) > MAX_HINTS:
            self.error(
                code, f"'{name}' must be a list of at most {MAX_HINTS} strings.", line
            )
            return ()
        out: list[str] = []
        for entry in node.items:
            if (
                not isinstance(entry, _Scalar)
                or entry.kind != "str"
                or not str(entry.value).strip()
            ):
                self.error(
                    code,
                    f"'{name}' entries must be non-empty strings.",
                    getattr(entry, "line", line),
                )
                return ()
            value = str(entry.value).strip()
            if _unsafe_path(value):
                self.error(
                    code,
                    f"'{name}' entry '{value}' must be a relative path without '..'.",
                    entry.line,
                )
                return ()
            out.append(value)
        return tuple(out)


def extract_spec(lines: list[Line], source_id: str, collector: Collector) -> None:
    """Parse ``lines`` as an intent spec; fill ``collector`` (never raises)."""
    try:
        root = _Parser(lines, collector).parse()
    except _Fatal as exc:
        collector.note(
            DiagnosticKind.PARSE_ERROR,
            "spec_syntax",
            exc.message,
            severity=Severity.ERROR,
            line=exc.line,
        )
        return
    _Validator(source_id, collector).run(root)
