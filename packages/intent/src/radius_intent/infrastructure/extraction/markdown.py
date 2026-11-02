"""Single-pass, linear Markdown scanner producing criterion candidates.

No regex here can backtrack catastrophically: list markers, headings, fences
and tables are recognised with ``startswith``/index scans, and the few regexes
are single-class, non-nested. See the package README for the rule set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .candidates import Candidate, Collector
from .config import CompiledConfig, ExtractionConfig
from .gherkin import (
    GHERKIN_FENCE_LANGS,
    extract_gherkin,
    is_step,
    starts_gherkin,
)
from .report import DiagnosticKind, Severity
from .sentences import classify_sentence, split_sentences
from .text import Line, collapse

_NON_WORD = re.compile(r"[\W_]+")
_PAREN = re.compile(r"\([^)]*\)")
_LEADING_NUM = re.compile(r"\d+ ")
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)

PLACEHOLDERS = frozenset(
    {
        "n/a",
        "na",
        "none",
        "tbd",
        "tba",
        "todo",
        "nil",
        "nothing",
        "no response",
        "none yet",
        "to be defined",
        "to be decided",
        "not applicable",
        "...",
    }
)
_BOILERPLATE_START = (
    "i have",
    "i've",
    "i did",
    "i confirm",
    "i read",
    "i agree",
    "i checked",
    "i ran",
    "i updated",
    "i added",
    "i am",
    "i'm",
    "we have",
    "my code",
    "my changes",
    "this pr",
    "this pull request",
    "this change",
    "code follows",
    "code is",
    "tests added",
    "tests pass",
    "test added",
    "docs updated",
    "documentation",
    "no breaking",
    "breaking change",
    "bug fix",
    "new feature",
    "chore",
    "refactor",
    "self-review",
    "self review",
    "lint",
)
_BOILERPLATE_ANY = ("contributing", "code of conduct", "pre-commit", " cla ")
_SETEXT_CHARS = {"=": 1, "-": 2}
_HTML_BLOCK_TAGS = (
    "details",
    "summary",
    "div",
    "p",
    "br",
    "hr",
    "table",
    "thead",
    "tbody",
    "tr",
    "td",
    "th",
    "ul",
    "ol",
    "li",
    "blockquote",
    "section",
    "center",
    "img",
)
_QUOTE = "quote"
MAX_TABLE_CELLS = 256


def clean_heading(text: str) -> str:
    """Normalise a heading/column label: lowercase words only, no emoji."""
    text = _PAREN.sub(" ", text[:200].lower())
    text = _NON_WORD.sub(" ", text).strip()
    return _LEADING_NUM.sub("", text, count=1)


def reject_reason(text: str, max_chars: int) -> str | None:
    """Return a skip code if ``text`` is not worth being a criterion."""
    if len(text) > max_chars:
        return "too_long"
    if not any(ch.isalnum() for ch in text):
        return "no_text"
    if len(text) < 3:
        return "too_short"
    bare = text.lower().strip("_*. ")
    if bare in PLACEHOLDERS:
        return "placeholder"
    if text.startswith("![") or (text.startswith("http") and " " not in text):
        return "link_or_image_only"
    return None


def is_boilerplate(text: str) -> bool:
    """Return whether a task-list item is PR-template process boilerplate."""
    lower = text.lower()
    return lower.startswith(_BOILERPLATE_START) or any(
        p in f" {lower} " for p in _BOILERPLATE_ANY
    )


def _indent(text: str) -> tuple[int, int]:
    """Return (visual width with 4-wide tabs, index of first non-blank)."""
    width = 0
    for idx, ch in enumerate(text):
        if ch == " ":
            width += 1
        elif ch == "\t":
            width += 4 - width % 4
        else:
            return width, idx
    return width, len(text)


@dataclass
class _Section:
    kind: str = "neutral"  # neutral | criteria | excluded
    level: int = 0
    title: str | None = None


@dataclass
class _Item:
    marker_indent: int
    content_col: int
    start: int
    end: int
    parts: list[str]
    checked: bool | None
    depth: int
    line: int
    section: _Section
    prefix: str = ""
    children: int = 0
    lead: str | None = None


def _list_marker(text: str, idx: int) -> tuple[int, int] | None:
    """Return (marker length, index of item text) if ``text[idx:]`` is an item."""
    c = text[idx]
    size = len(text)
    if c in "-*+":
        mlen = 1
    elif c.isdigit() and c.isascii():
        j = idx
        while j < size and text[j].isdigit() and text[j].isascii():
            j += 1
        if j == idx or j - idx > 9 or j >= size or text[j] not in ".)":
            return None
        mlen = j + 1 - idx
    else:
        return None
    after = idx + mlen
    if after < size and text[after] not in " \t":
        return None
    rest = after
    while rest < size and text[rest] in " \t":
        rest += 1
    # "---", "***" thematic breaks have no space after the first char.
    return mlen, rest


def _is_fence_open(s: str) -> bool:
    if s.startswith("```"):
        return "`" not in s.lstrip("`")
    return s.startswith("~~~")


def _is_html_block_line(stripped: str) -> bool:
    """Return whether a line is a standalone block-level HTML tag line."""
    if not (stripped.startswith("<") and stripped.endswith(">")):
        return False
    name = stripped[2:] if stripped.startswith("</") else stripped[1:]
    word = ""
    for ch in name:
        if not ch.isalpha():
            break
        word += ch
    return word.lower() in _HTML_BLOCK_TAGS


def _split_row(line: Line) -> list[tuple[int, int, str]]:
    """Split a table row into (start, end, text) cells with absolute offsets."""
    text = line.text
    cells: list[tuple[int, int, str]] = []
    begin = 0
    size = len(text)
    first = text.lstrip()
    if first.startswith("|"):
        begin = len(text) - len(first) + 1
    pos = begin
    while pos <= size:
        bar = pos
        while True:
            bar = text.find("|", bar)
            if bar < 0 or text[bar - 1 : bar] != "\\":
                break
            bar += 1
        stop = size if bar < 0 else bar
        raw = text[begin:stop]
        lead = len(raw) - len(raw.lstrip())
        body = raw.strip()
        if bar >= 0 or body:
            cells.append(
                (line.start + begin + lead, line.start + begin + lead + len(body), body)
            )
        if bar < 0 or len(cells) >= MAX_TABLE_CELLS:
            break
        begin = pos = bar + 1
    return cells


def _is_delimiter_row(line: Line) -> bool:
    if "-" not in line.text or "|" not in line.text:
        return False
    cells = _split_row(line)
    if not cells:
        return False
    for _, _, body in cells:
        core = body.strip(":")
        if not core or core.strip("-"):
            return False
    return True


class MarkdownScanner:
    """Scan masked Markdown ``lines`` and fill a :class:`Collector`."""

    def __init__(
        self,
        lines: list[Line],
        config: ExtractionConfig,
        compiled: CompiledConfig,
        collector: Collector,
    ) -> None:
        self.lines = lines
        self.cfg = config
        self.rx = compiled
        self.col = collector
        self.sec = _Section()
        self.stack: list[_Item] = []
        self.para: list[Line] = []
        self.prev = "blank"
        self.depth_capped = False
        self.capped = False
        self._source = ""

    # -- candidate plumbing -------------------------------------------------

    def _add(self, cand: Candidate, line: int | None = None) -> None:
        reason = reject_reason(cand.text, self.cfg.max_item_chars)
        if reason is not None:
            self.col.skip(
                reason,
                f"Skipped {reason.replace('_', ' ')} statement.",
                line=line,
                start=cand.start,
                end=cand.end,
            )
            return
        if len(self.col.candidates) >= self.cfg.max_criteria_per_source:
            if not self.capped:
                self.capped = True
                self.col.note(
                    DiagnosticKind.LIMIT,
                    "max_criteria",
                    f"Stopped after {self.cfg.max_criteria_per_source} criteria.",
                    severity=Severity.WARNING,
                    line=line,
                )
            return
        self.col.add(cand)

    # -- sections -----------------------------------------------------------

    def _classify(self, title: str) -> str:
        cleaned = clean_heading(title)
        if self.rx.section.fullmatch(cleaned):
            return "criteria"
        if self.rx.excluded.fullmatch(cleaned):
            return "excluded"
        return "neutral"

    def _heading(self, level: int, title: str) -> None:
        self._flush_para()
        self._close_items(0)
        kind = self._classify(title)
        sec = self.sec
        if kind != "neutral":
            self.sec = _Section(kind, level, clean_heading(title))
        elif sec.kind != "neutral" and level > sec.level:
            return
        else:
            self.sec = _Section("neutral", level, None)

    # -- lists --------------------------------------------------------------

    def _close_items(self, keep: int) -> None:
        while len(self.stack) > keep:
            self._emit_item(self.stack.pop())

    def _emit_item(self, item: _Item) -> None:
        text = collapse(" ".join(item.parts))
        kind = item.section.kind
        if kind == "excluded":
            self.col.skip(
                "excluded_section",
                "Item under a non-criteria section.",
                line=item.line,
                start=item.start,
                end=item.end,
            )
            return
        if kind == "criteria":
            if item.children and text.endswith((":", "：")):
                return  # lead-in: children carry it as a prefix
            full = f"{item.prefix}: {text}" if item.prefix else text
            rule = "task_item" if item.checked is not None else "section_item"
            self._add(
                Candidate(
                    item.start,
                    item.end,
                    full,
                    rule,
                    item.section.title,
                    item.checked,
                    item.depth,
                ),
                item.line,
            )
            return
        if item.checked is not None:
            if is_boilerplate(text):
                self.col.skip(
                    "boilerplate_checklist",
                    "Process checklist item.",
                    line=item.line,
                    start=item.start,
                    end=item.end,
                )
                return
            self._add(
                Candidate(
                    item.start,
                    item.end,
                    text,
                    "task_item",
                    None,
                    item.checked,
                    item.depth,
                ),
                item.line,
            )
            return
        self._prose(item.start, item.end, item.line, item.depth)

    def _start_item(
        self, line: Line, width: int, idx: int, mlen: int, rest: int
    ) -> None:
        text = line.text
        while self.stack and self.stack[-1].marker_indent >= width:
            self._emit_item(self.stack.pop())
        if len(self.stack) >= self.cfg.max_list_depth:
            self._emit_item(self.stack.pop())
            if not self.depth_capped:
                self.depth_capped = True
                self.col.note(
                    DiagnosticKind.LIMIT,
                    "max_list_depth",
                    "List nesting deeper than the limit was flattened.",
                    severity=Severity.WARNING,
                    line=line.number,
                )
        checked: bool | None = None
        body = text[rest:]
        if body[:3] in ("[ ]", "[x]", "[X]") and (len(body) == 3 or body[3] in " \t"):
            checked = body[1] != " "
            skip = 3
            while skip < len(body) and body[skip] in " \t":
                skip += 1
            rest += skip
        parent = self.stack[-1] if self.stack else None
        prefix = ""
        if parent is not None:
            parent.children += 1
            if parent.lead is None:
                parent.lead = collapse(" ".join(parent.parts))
            lead = parent.lead
            if lead.endswith((":", "：")):
                head = f"{parent.prefix}: {lead[:-1]}" if parent.prefix else lead[:-1]
                prefix = head.strip()[:200]
        item = _Item(
            marker_indent=width,
            content_col=width + mlen + 1,
            start=line.start + rest,
            end=line.start + len(text.rstrip()),
            parts=[text[rest:].strip()],
            checked=checked,
            depth=len(self.stack),
            line=line.number,
            section=self.sec,
            prefix=prefix,
        )
        if item.end <= item.start:  # empty item such as a bare "-"
            item.start = item.end = line.start + len(text.rstrip())
        self.stack.append(item)

    def _continue_item(self, line: Line) -> None:
        item = self.stack[-1]
        item.parts.append(line.text.strip())
        item.end = line.start + len(line.text.rstrip())

    # -- prose --------------------------------------------------------------

    def _flush_para(self) -> None:
        if not self.para:
            return
        lines, self.para = self.para, []
        if self.sec.kind == "excluded":
            self.col.skip(
                "excluded_section",
                "Paragraph under a non-criteria section.",
                line=lines[0].number,
                start=lines[0].start,
                end=lines[-1].end,
            )
            return
        stripped = [ln.text.strip() for ln in lines]
        if all(is_step(s) for s in stripped) and stripped[0].startswith(
            ("Given ", "When ")
        ):
            found = extract_gherkin(lines, plain=True, section=self.sec.title)
            if found:
                for cand in found:
                    self._add(cand, lines[0].number)
                return
        self._prose(lines[0].start, lines[-1].end, lines[0].number, 0)

    def _prose(self, start: int, end: int, line: int, depth: int) -> None:
        raw = self._source[start:end]
        for a, b in split_sentences(raw):
            sentence = raw[a:b]
            if len(sentence) > 4 * self.cfg.max_sentence_chars:
                self.col.skip(
                    "sentence_too_long",
                    "Sentence too long to be a criterion.",
                    line=line,
                    start=start + a,
                    end=start + b,
                )
                continue
            rule, why = classify_sentence(sentence, self.cfg.max_sentence_chars)
            lead = len(sentence) - len(sentence.lstrip())
            s0 = start + a + lead
            e0 = start + a + len(sentence.rstrip())
            if rule is None:
                if why is not None:
                    self.col.skip(
                        why,
                        f"Skipped sentence: {why.replace('_', ' ')}.",
                        line=line,
                        start=s0,
                        end=e0,
                    )
                continue
            self._add(
                Candidate(
                    s0, e0, collapse(sentence), rule, self.sec.title, None, depth
                ),
                line,
            )

    # -- main loop ----------------------------------------------------------

    def scan(self, masked: str) -> None:
        """Scan ``masked`` (offset-preserving, comments blanked)."""
        self._source = masked
        lines = self.lines
        n = len(lines)
        i = 0
        while i < n:
            i = self._step(i, lines, n)
        self._flush_para()
        self._close_items(0)

    def _step(self, i: int, lines: list[Line], n: int) -> int:
        line = lines[i]
        text = line.text
        stripped = text.strip()
        if not stripped:
            self._flush_para()
            self.prev = "blank"
            return i + 1
        width, idx = _indent(text)
        s = text[idx:]

        if _is_fence_open(s):
            return self._fence(i, lines, n, idx)

        if width <= 3 and s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            if level <= 6 and (len(s) == level or s[level] in " \t"):
                title = s[level:].strip()
                trimmed = title.rstrip("#")
                if not trimmed or trimmed.endswith((" ", "\t")):
                    title = trimmed.strip()
                self._heading(level, title)
                self.prev = "other"
                return i + 1

        if (
            self.para
            and not self.stack
            and stripped[0] in _SETEXT_CHARS
            and (len(set(stripped)) == 1)
        ):
            title = collapse(" ".join(ln.text for ln in self.para))
            self.para = []
            self._heading(_SETEXT_CHARS[stripped[0]], title)
            self.prev = "other"
            return i + 1

        if (
            width <= 3
            and len(stripped) >= 3
            and len(set(stripped.replace(" ", ""))) == 1
            and stripped[0] in "-*_"
            and len(stripped.replace(" ", "")) >= 3
        ):
            self._flush_para()
            self._close_items(0)
            self.prev = "other"
            return i + 1

        if "|" in text and i + 1 < n and _is_delimiter_row(lines[i + 1]):
            self._flush_para()
            self._close_items(0)
            self.prev = "other"
            return self._table(i, lines, n)

        if _is_html_block_line(stripped):
            self._flush_para()
            self.prev = "other"
            return i + 1

        if s.startswith(">"):
            self._flush_para()
            if self.prev != _QUOTE:
                self.col.skip(
                    "blockquote",
                    "Quoted text is not extracted.",
                    line=line.number,
                    start=line.start,
                    end=line.end,
                )
            self.prev = _QUOTE
            return i + 1

        marker = _list_marker(text, idx)
        if marker is not None:
            self._flush_para()
            self._start_item(line, width, idx, marker[0], marker[1])
            self.prev = "item"
            return i + 1

        if starts_gherkin(s):
            self._flush_para()
            self._close_items(0)
            return self._plain_gherkin(i, lines, n)

        pseudo = self._pseudo_heading(stripped, width)
        if pseudo is not None:
            self._heading(7, pseudo)
            self.prev = "other"
            return i + 1

        # Plain text line: paragraph, or continuation of an open list item.
        if self.stack:
            if self.prev in ("para", "item"):
                self._continue_item(line)
                self.prev = "item"
                return i + 1
            while self.stack and width < self.stack[-1].content_col:
                self._emit_item(self.stack.pop())
            if self.stack:
                self._continue_item(line)
                self.prev = "item"
                return i + 1
        self.para.append(line)
        self.prev = "para"
        return i + 1

    def _pseudo_heading(self, stripped: str, width: int) -> str | None:
        if width > 3 or len(stripped) > 80:
            return None
        title: str | None = None
        for mark in ("**", "__"):
            if stripped.startswith(mark) and len(stripped) > 4:
                inner = stripped[2:]
                if inner.endswith(mark):
                    title = inner[:-2]
                elif inner.endswith(mark + ":") or inner.endswith(":" + mark):
                    title = inner[:-3]
        if title is None and stripped.endswith(":") and len(stripped) <= 60:
            title = stripped[:-1]
        if title is None:
            return None
        return title if self._classify(title) != "neutral" else None

    def _fence(self, i: int, lines: list[Line], n: int, idx: int) -> int:
        first = lines[i]
        opener = first.text[idx:]
        char = opener[0]
        size = len(opener) - len(opener.lstrip(char))
        info = opener[size:].strip()
        lang = info.split(None, 1)[0].lower().strip("{}") if info else ""
        self._flush_para()
        j = i + 1
        closed = False
        while j < n:
            cand = lines[j].text.strip()
            if cand.startswith(char * size) and not cand.strip(char):
                closed = True
                break
            j += 1
        body = lines[i + 1 : j]
        end = lines[j].end if closed else lines[n - 1].end
        if not closed:
            self.col.note(
                DiagnosticKind.SKIPPED_REGION,
                "unterminated_fence",
                "Code fence is never closed; it runs to the end of the text.",
                severity=Severity.WARNING,
                line=first.number,
                start=first.start,
                end=end,
            )
        gherkin = lang in GHERKIN_FENCE_LANGS or (
            not lang
            and next((b.text.strip() for b in body if b.text.strip()), "").startswith(
                ("Feature:", "Scenario", "Background:", "Given ", "Example:")
            )
        )
        if gherkin and self.sec.kind == "excluded":
            self.col.skip(
                "excluded_section",
                "Gherkin under a non-criteria section.",
                line=first.number,
                start=first.start,
                end=end,
            )
        elif gherkin:
            for cand_ in extract_gherkin(body, plain=False, section=self.sec.title):
                self._add(cand_, first.number)
        else:
            self.col.skip(
                "code_fence",
                "Content of a non-Gherkin code fence is never extracted.",
                line=first.number,
                start=first.start,
                end=end,
            )
        self.prev = "other"
        return j + 1

    def _plain_gherkin(self, i: int, lines: list[Line], n: int) -> int:
        j = i
        while j < n:
            s = lines[j].text.strip()
            if not s or not (
                starts_gherkin(s)
                or is_step(s)
                or s.startswith(("|", "@", "Examples:", "Scenarios:", '"""'))
            ):
                break
            j += 1
        if self.sec.kind == "excluded":
            self.col.skip(
                "excluded_section",
                "Gherkin under a non-criteria section.",
                line=lines[i].number,
                start=lines[i].start,
                end=lines[j - 1].end,
            )
        else:
            for cand in extract_gherkin(lines[i:j], plain=True, section=self.sec.title):
                self._add(cand, lines[i].number)
        self.prev = "other"
        return j

    def _table(self, i: int, lines: list[Line], n: int) -> int:
        header = _split_row(lines[i])
        cols = [
            k
            for k, (_, _, t) in enumerate(header)
            if self.rx.table_column.fullmatch(clean_heading(t))
        ]
        j = i + 2
        while j < n and lines[j].text.strip() and "|" in lines[j].text:
            j += 1
        region = (lines[i].start, lines[j - 1].end)
        if self.sec.kind == "excluded":
            self.col.skip(
                "excluded_section",
                "Table under a non-criteria section.",
                line=lines[i].number,
                start=region[0],
                end=region[1],
            )
        elif not cols:
            self.col.skip(
                "table_no_criteria_column",
                "Table has no criteria column.",
                line=lines[i].number,
                start=region[0],
                end=region[1],
            )
        else:
            for row in lines[i + 2 : j]:
                cells = _split_row(row)
                for k in cols:
                    if k < len(cells):
                        a, b, body = cells[k]
                        text = collapse(_BR.sub(" ", body))
                        self._add(
                            Candidate(a, b, text, "table_row", self.sec.title),
                            row.number,
                        )
        return j
