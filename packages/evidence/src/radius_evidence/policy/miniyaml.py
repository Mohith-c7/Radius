"""Strict parser for a small YAML subset (``.radius/policy.yml``, ``.radius/waivers.yml``).

PyYAML is not a dependency of Radius, and the repository config files are
written by humans but read by a security-relevant engine, so this module
implements only what the schemas need and rejects the rest with a line-numbered
error (same approach as the intent spec parser, but free of its collector).

Supported: ``key: value`` mappings, ``- item`` sequences of scalars or
mappings, plain / ``'single'`` / ``"double"`` quoted scalars, single-line
``[a, b]`` lists, ``#`` comments. Not supported (error, never evaluated): tabs,
anchors, aliases, tags, merge keys, flow mappings, block scalars, multi-document
streams, nested sequences, multi-line scalars. Linear time, bounded size.

``parse`` never raises: it returns the root node (or ``None`` after a fatal
error) and the list of diagnostics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_BYTES = 64 * 1024
MAX_LINES = 2000
MAX_DEPTH = 8

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_.:*-]*")
_INT = re.compile(r"[-+]?\d+")
_FLOAT = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "/": "/"}
_QUOTES = "\"'"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    line: int  # 1-based; 0 = whole file
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}" if self.line else self.message


@dataclass(frozen=True, slots=True)
class Scalar:
    value: object  # str | int | float | bool | None
    line: int


@dataclass(frozen=True, slots=True)
class Seq:
    items: tuple[Node, ...]
    line: int


@dataclass(frozen=True, slots=True)
class Map:
    entries: tuple[tuple[str, int, Node], ...]  # key, key line, value
    line: int

    def get(self, key: str) -> tuple[int, Node] | None:
        for k, line, node in self.entries:
            if k == key:
                return line, node
        return None


Node = Scalar | Seq | Map | None


@dataclass(slots=True)
class ParseResult:
    root: Node
    errors: list[Diagnostic] = field(default_factory=list)
    fatal: bool = False


class _Fatal(Exception):
    def __init__(self, line: int, message: str) -> None:
        super().__init__(message)
        self.diag = Diagnostic(line, message)


def _resolve(text: str) -> object:
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "~", ""):
        return None
    if _INT.fullmatch(text):
        return int(text)
    if _FLOAT.fullmatch(text):
        return float(text)
    return text


def _strip_comment(text: str) -> str:
    """Remove a trailing `` #`` comment that is outside quotes."""

    quote = ""
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in _QUOTES:
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] in " \t"):
            return text[:i].rstrip()
    return text.rstrip()


class _Parser:
    def __init__(self, text: str) -> None:
        self.lines = text.split("\n")
        self.errors: list[Diagnostic] = []

    # -- line helpers -----------------------------------------------------

    def _clean(self, idx: int) -> str:
        return _strip_comment(self.lines[idx].rstrip("\r"))

    def _skip(self, idx: int) -> int:
        while idx < len(self.lines) and not self._clean(idx).strip():
            idx += 1
        return idx

    def _indent(self, idx: int) -> int:
        raw = self._clean(idx)
        n = len(raw) - len(raw.lstrip(" "))
        if raw[n : n + 1] == "\t":
            raise _Fatal(idx + 1, "Tabs are not allowed for indentation.")
        return n

    # -- document ---------------------------------------------------------

    def parse(self) -> Node:
        idx = self._skip(0)
        if idx < len(self.lines) and self._clean(idx).strip() == "---":
            idx = self._skip(idx + 1)
        if idx >= len(self.lines):
            return None
        node, idx = self._node(idx, self._indent(idx), 1)
        idx = self._skip(idx)
        if idx < len(self.lines):
            text = self._clean(idx).strip()
            if text == "---":
                raise _Fatal(idx + 1, "Multiple YAML documents are not supported.")
            raise _Fatal(idx + 1, "Unexpected content after the document.")
        return node

    def _node(self, idx: int, indent: int, depth: int) -> tuple[Node, int]:
        if depth > MAX_DEPTH:
            raise _Fatal(idx + 1, f"Nesting deeper than {MAX_DEPTH} levels.")
        body = self._clean(idx)[indent:]
        if body == "-" or body.startswith("- "):
            return self._seq(idx, indent, depth)
        return self._map(idx, indent, depth)

    # -- mappings ---------------------------------------------------------

    def _map(self, idx: int, indent: int, depth: int) -> tuple[Map, int]:
        first = idx + 1
        entries: list[tuple[str, int, Node]] = []
        seen: set[str] = set()
        while True:
            idx = self._skip(idx)
            if idx >= len(self.lines):
                break
            cur = self._indent(idx)
            if cur < indent:
                break
            if cur > indent:
                raise _Fatal(idx + 1, "Unexpected indentation.")
            body = self._clean(idx)[indent:]
            if body == "-" or body.startswith("- "):
                break
            if body == "---":
                raise _Fatal(idx + 1, "Multiple YAML documents are not supported.")
            key, rest = self._split_key(idx, body)
            number = idx + 1
            value, idx = self._value(idx, indent, rest, depth)
            if key in seen:
                self.errors.append(
                    Diagnostic(number, f"Duplicate key '{key}'; the first value is kept.")
                )
            else:
                seen.add(key)
                entries.append((key, number, value))
        return Map(tuple(entries), first), idx

    def _split_key(self, idx: int, body: str) -> tuple[str, str]:
        colon = body.find(":")
        while colon >= 0 and not (colon + 1 == len(body) or body[colon + 1] == " "):
            colon = body.find(":", colon + 1)
        key = body[:colon].strip() if colon >= 0 else ""
        if colon < 0 or not _KEY.fullmatch(key):
            raise _Fatal(idx + 1, "Expected 'key: value' with a plain key.")
        return key, body[colon + 1 :].strip()

    def _value(self, idx: int, indent: int, rest: str, depth: int) -> tuple[Node, int]:
        if rest:
            return self._inline(idx + 1, rest), idx + 1
        nxt = self._skip(idx + 1)
        if nxt < len(self.lines):
            ind = self._indent(nxt)
            body = self._clean(nxt)[ind:]
            if ind > indent:
                return self._node(nxt, ind, depth + 1)
            if ind == indent and (body == "-" or body.startswith("- ")):
                return self._seq(nxt, indent, depth + 1)
        return None, idx + 1

    # -- sequences --------------------------------------------------------

    def _seq(self, idx: int, indent: int, depth: int) -> tuple[Seq, int]:
        first = idx + 1
        items: list[Node] = []
        while True:
            idx = self._skip(idx)
            if idx >= len(self.lines):
                break
            cur = self._indent(idx)
            if cur < indent:
                break
            if cur > indent:
                raise _Fatal(idx + 1, "Unexpected indentation.")
            body = self._clean(idx)[indent:]
            if not (body == "-" or body.startswith("- ")):
                break
            after = body[1:]
            lead = len(after) - len(after.lstrip())
            rest = after.strip()
            col = indent + 1 + lead
            if not rest:
                nxt = self._skip(idx + 1)
                if nxt < len(self.lines) and self._indent(nxt) > indent:
                    node, idx = self._node(nxt, self._indent(nxt), depth + 1)
                    items.append(node)
                else:
                    items.append(None)
                    idx += 1
            elif rest == "-" or rest.startswith("- "):
                raise _Fatal(idx + 1, "Nested sequences are not supported.")
            elif rest[0] not in _QUOTES + "[" and self._looks_like_entry(rest):
                raw = self._clean(idx)
                self.lines[idx] = " " * col + raw[col:]
                node, idx = self._map(idx, col, depth + 1)
                items.append(node)
            else:
                items.append(self._inline(idx + 1, rest))
                idx += 1
        return Seq(tuple(items), first), idx

    @staticmethod
    def _looks_like_entry(rest: str) -> bool:
        colon = rest.find(":")
        while colon >= 0 and not (colon + 1 == len(rest) or rest[colon + 1] == " "):
            colon = rest.find(":", colon + 1)
        return colon > 0 and _KEY.fullmatch(rest[:colon].strip()) is not None

    # -- scalars ----------------------------------------------------------

    def _inline(self, number: int, text: str) -> Node:
        c = text[0]
        if c in "&*!%@`":
            kind = {"&": "anchors", "*": "aliases", "!": "tags"}.get(c, "this indicator")
            raise _Fatal(number, f"YAML {kind} are not supported.")
        if c == "{":
            raise _Fatal(number, "Flow mappings are not supported; use a block mapping.")
        if c in "|>":
            raise _Fatal(number, "Block scalars are not supported; use a quoted string.")
        if c == "[":
            return self._flow_seq(number, text)
        if c in _QUOTES:
            value, end = self._quoted(number, text, 0)
            if text[end:].strip():
                raise _Fatal(number, "Unexpected text after quoted value.")
            return Scalar(value, number)
        if text.endswith(":") or ": " in text:
            raise _Fatal(number, "Unquoted ':' in a value; wrap the value in quotes.")
        return Scalar(_resolve(text), number)

    def _quoted(self, number: int, text: str, start: int) -> tuple[str, int]:
        quote = text[start]
        pos = start + 1
        out: list[str] = []
        while pos < len(text):
            ch = text[pos]
            if quote == '"' and ch == "\\":
                nxt = text[pos + 1 : pos + 2]
                if nxt not in _ESCAPES:
                    raise _Fatal(number, f"Unsupported escape '\\{nxt}'.")
                out.append(_ESCAPES[nxt])
                pos += 2
                continue
            if ch == quote:
                if quote == "'" and text[pos + 1 : pos + 2] == "'":
                    out.append("'")
                    pos += 2
                    continue
                return "".join(out), pos + 1
            out.append(ch)
            pos += 1
        raise _Fatal(number, "Unterminated quoted value (multi-line scalars are not supported).")

    def _flow_seq(self, number: int, text: str) -> Seq:
        items: list[Node] = []
        pos, size = 1, len(text)
        while True:
            while pos < size and text[pos] == " ":
                pos += 1
            if pos >= size:
                raise _Fatal(number, "Unterminated '[' list (multi-line lists are not supported).")
            if text[pos] == "]":
                break
            if text[pos] in _QUOTES:
                value, pos = self._quoted(number, text, pos)
                items.append(Scalar(value, number))
            else:
                end = pos
                while end < size and text[end] not in ",]":
                    end += 1
                body = text[pos:end].strip()
                if not body or body[0] in "&*!{[|>":
                    raise _Fatal(number, "Unsupported or empty list item.")
                items.append(Scalar(_resolve(body), number))
                pos = end
            while pos < size and text[pos] == " ":
                pos += 1
            if pos < size and text[pos] == ",":
                pos += 1
            elif pos >= size or text[pos] != "]":
                raise _Fatal(number, "Expected ',' or ']' in list.")
        if text[pos + 1 :].strip():
            raise _Fatal(number, "Unexpected text after list.")
        return Seq(tuple(items), number)


def parse(text: str) -> ParseResult:
    """Parse ``text``; never raises."""

    if not isinstance(text, str):
        return ParseResult(None, [Diagnostic(0, "File is not text.")], True)
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        return ParseResult(
            None, [Diagnostic(0, f"File is larger than {MAX_BYTES // 1024} KiB.")], True
        )
    if text.startswith("﻿"):
        text = text[1:]
    if text.count("\n") + 1 > MAX_LINES:
        return ParseResult(None, [Diagnostic(0, f"File has more than {MAX_LINES} lines.")], True)
    parser = _Parser(text)
    try:
        root = parser.parse()
    except _Fatal as exc:
        return ParseResult(None, [*parser.errors, exc.diag], True)
    return ParseResult(root, parser.errors, False)


def to_python(node: Node) -> object:
    """Plain Python value of a node (for tests and diagnostics)."""

    if node is None:
        return None
    if isinstance(node, Scalar):
        return node.value
    if isinstance(node, Seq):
        return [to_python(i) for i in node.items]
    return {k: to_python(v) for k, _line, v in node.entries}
