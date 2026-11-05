"""Gold-set contract for the extraction metrics harness (IN-10).

This is the harness's own input contract, written before the real gold set
(IN-09) exists. The real files plug in through a small adapter that emits the
dict form parsed here (see ``docs/research/evaluation/INTENT_EVAL.md``).

Pure: :func:`parse_gold` takes already-decoded JSON values and never touches
files or the clock. All offsets are stored as Python code-point indices into
the source text (half-open ``[start, end)``), the same unit as
``radius_intent.domain.Span``; :func:`convert_offsets` translates UTF-16 or
UTF-8 byte offsets on load.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from radius_intent.domain import IntentSourceKind, Testability

GOLD_SCHEMA_ID = "radius.intent.gold/1"
OFFSET_UNITS = ("codepoint", "utf16", "utf8")


class GoldFormatError(ValueError):
    """The gold document violates the contract; ``errors`` lists every problem."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        shown = "; ".join(self.errors[:10])
        more = f" (+{len(self.errors) - 10} more)" if len(self.errors) > 10 else ""
        super().__init__(f"{len(self.errors)} gold format error(s): {shown}{more}")


@dataclass(frozen=True)
class EvalSource:
    """One piece of intent text of a PR."""

    source_id: str
    kind: IntentSourceKind
    text: str


@dataclass(frozen=True)
class EvalSpan:
    """Half-open code-point range in a named source."""

    source_id: str
    start: int
    end: int


@dataclass(frozen=True)
class GoldCriterion:
    """One gold criterion.

    ``span`` is the primary annotation. ``alt_spans`` are other acceptable
    annotations of the same criterion (a split of a compound statement, or the
    same requirement restated in another source); a prediction matches the
    best-overlapping one. ``text`` is the annotator's atomic restatement.
    """

    criterion_id: str
    span: EvalSpan
    alt_spans: tuple[EvalSpan, ...] = ()
    testability: Testability | None = None
    text: str | None = None

    @property
    def all_spans(self) -> tuple[EvalSpan, ...]:
        return (self.span, *self.alt_spans)


@dataclass(frozen=True)
class EvalCase:
    """One PR: its sources and its gold criteria (possibly none)."""

    case_id: str
    sources: tuple[EvalSource, ...]
    criteria: tuple[GoldCriterion, ...] = ()
    well_specified: bool | None = None
    group: str | None = None
    author_type: str | None = None

    def source(self, source_id: str) -> EvalSource | None:
        for src in self.sources:
            if src.source_id == source_id:
                return src
        return None

    def kind_of(self, source_id: str) -> IntentSourceKind | None:
        src = self.source(source_id)
        return src.kind if src else None

    def slice(self, span: EvalSpan) -> str:
        src = self.source(span.source_id)
        return src.text[span.start : span.end] if src else ""


@dataclass(frozen=True)
class GoldDataset:
    """A loaded gold set. ``synthetic`` datasets are never research results."""

    name: str
    version: str
    split: str
    synthetic: bool
    cases: tuple[EvalCase, ...]
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default=(), compare=False)

    def canonical(self) -> dict[str, Any]:
        """Normalized plain-data form (code-point offsets) used for hashing."""
        return {
            "schema": GOLD_SCHEMA_ID,
            "name": self.name,
            "version": self.version,
            "split": self.split,
            "synthetic": self.synthetic,
            "cases": [_case_dict(c) for c in sorted(self.cases, key=_case_key)],
        }

    @property
    def sha256(self) -> str:
        """Content hash of :meth:`canonical` (the dataset manifest hash)."""
        blob = json.dumps(
            self.canonical(), sort_keys=True, ensure_ascii=True, separators=(",", ":")
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _case_key(case: EvalCase) -> str:
    return case.case_id


def _span_dict(s: EvalSpan) -> dict[str, Any]:
    return {"source_id": s.source_id, "start": s.start, "end": s.end}


def _case_dict(case: EvalCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "well_specified": case.well_specified,
        "group": case.group,
        "author_type": case.author_type,
        "sources": [
            {"source_id": s.source_id, "kind": s.kind.value, "text": s.text}
            for s in case.sources
        ],
        "criteria": [
            {
                "id": c.criterion_id,
                "span": _span_dict(c.span),
                "alt_spans": [_span_dict(a) for a in c.alt_spans],
                "testability": c.testability.value if c.testability else None,
                "text": c.text,
            }
            for c in case.criteria
        ],
    }


def convert_offsets(text: str, start: int, end: int, unit: str) -> tuple[int, int]:
    """Translate ``[start, end)`` in ``unit`` to code-point offsets in ``text``.

    ``unit`` is ``codepoint`` (identity), ``utf16`` (code units, as JavaScript
    strings index) or ``utf8`` (byte offsets). Raises ``ValueError`` when an
    offset is out of range or splits a character (inside a surrogate pair or a
    multi-byte sequence).
    """
    if unit == "codepoint":
        return start, end
    if unit not in OFFSET_UNITS:
        raise ValueError(f"unknown offset_unit {unit!r}")
    width = _utf16_width if unit == "utf16" else _utf8_width
    index_of: dict[int, int] = {}
    pos = 0
    for i, ch in enumerate(text):
        index_of[pos] = i
        pos += width(ch)
    index_of[pos] = len(text)
    try:
        return index_of[start], index_of[end]
    except KeyError:
        raise ValueError(
            f"{unit} offset {start}..{end} is out of range or splits a character"
        ) from None


def _utf16_width(ch: str) -> int:
    return 2 if ord(ch) > 0xFFFF else 1


def _utf8_width(ch: str) -> int:
    return len(ch.encode("utf-8", "surrogatepass"))


class _Collector:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def add(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_span(
    raw: object,
    path: str,
    texts: Mapping[str, str],
    unit: str,
    default_source: str | None,
    err: _Collector,
) -> EvalSpan | None:
    if not isinstance(raw, Mapping):
        err.add(path, "span must be an object")
        return None
    sid = raw.get("source_id", default_source)
    start, end = raw.get("start"), raw.get("end")
    if not isinstance(sid, str) or sid not in texts:
        err.add(path, f"unknown source_id {sid!r}")
        return None
    if not (_is_int(start) and _is_int(end)):
        err.add(path, "start and end must be integers")
        return None
    text = texts[sid]
    try:
        start, end = convert_offsets(text, start, end, unit)  # type: ignore[arg-type]
    except ValueError as exc:
        err.add(path, str(exc))
        return None
    if not 0 <= start < end <= len(text):
        err.add(path, f"span [{start},{end}) must satisfy 0 <= start < end <= {len(text)}")
        return None
    return EvalSpan(sid, start, end)


def _parse_testability(raw: object, path: str, err: _Collector) -> Testability | None:
    if raw is None:
        return None
    try:
        label = Testability(raw)
    except ValueError:
        err.add(path, f"unknown testability {raw!r}")
        return None
    if label is Testability.UNRATED:
        err.add(path, "testability 'unrated' is not a valid gold label")
        return None
    return label


def _parse_case(
    raw: object, path: str, default_unit: str, err: _Collector, warnings: list[str]
) -> EvalCase | None:
    if not isinstance(raw, Mapping):
        err.add(path, "case must be an object")
        return None
    case_id = raw.get("case_id")
    if not isinstance(case_id, str) or not case_id.strip():
        err.add(path, "case_id must be a non-empty string")
        return None
    path = f"{path}[{case_id}]"
    unit = raw.get("offset_unit", default_unit)
    if unit not in OFFSET_UNITS:
        err.add(path, f"offset_unit must be one of {OFFSET_UNITS}")
        unit = "codepoint"

    sources: list[EvalSource] = []
    texts: dict[str, str] = {}
    raw_sources = raw.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        err.add(path, "sources must be a non-empty list")
        raw_sources = []
    for i, s in enumerate(raw_sources):
        sp = f"{path}.sources[{i}]"
        if not isinstance(s, Mapping):
            err.add(sp, "source must be an object")
            continue
        sid, text = s.get("source_id"), s.get("text")
        if not isinstance(sid, str) or not sid.strip():
            err.add(sp, "source_id must be a non-empty string")
            continue
        if sid in texts:
            err.add(sp, f"duplicate source_id {sid!r}")
            continue
        if not isinstance(text, str):
            err.add(sp, "text must be a string")
            continue
        try:
            kind = IntentSourceKind(s.get("kind"))
        except ValueError:
            err.add(sp, f"unknown source kind {s.get('kind')!r}")
            continue
        texts[sid] = text
        sources.append(EvalSource(sid, kind, text))

    ws = raw.get("well_specified")
    if ws is not None and not isinstance(ws, bool):
        err.add(path, "well_specified must be true, false or null")
        ws = None
    for key in ("group", "author_type"):
        if raw.get(key) is not None and not isinstance(raw.get(key), str):
            err.add(path, f"{key} must be a string or null")

    criteria: list[GoldCriterion] = []
    seen_ids: set[str] = set()
    seen_spans: dict[tuple[str, int, int], str] = {}
    raw_criteria = raw.get("criteria", [])
    if not isinstance(raw_criteria, list):
        err.add(path, "criteria must be a list")
        raw_criteria = []
    for i, c in enumerate(raw_criteria):
        cp = f"{path}.criteria[{i}]"
        if not isinstance(c, Mapping):
            err.add(cp, "criterion must be an object")
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid.strip():
            err.add(cp, "id must be a non-empty string")
            continue
        if cid in seen_ids:
            err.add(cp, f"duplicate criterion id {cid!r}")
            continue
        seen_ids.add(cid)
        span = _parse_span(c.get("span", c), f"{cp}.span", texts, unit, None, err)
        alts_raw = c.get("alt_spans", [])
        if not isinstance(alts_raw, list):
            err.add(cp, "alt_spans must be a list")
            alts_raw = []
        alts = [
            a
            for j, raw_alt in enumerate(alts_raw)
            if (a := _parse_span(raw_alt, f"{cp}.alt_spans[{j}]", texts, unit, None, err))
        ]
        tx = _parse_testability(c.get("testability"), f"{cp}.testability", err)
        text = c.get("text")
        if text is not None and not isinstance(text, str):
            err.add(cp, "text must be a string or null")
            text = None
        if span is None:
            continue
        key = (span.source_id, span.start, span.end)
        if key in seen_spans:
            warnings.append(
                f"{path}: criteria {seen_spans[key]!r} and {cid!r} share a span "
                "(compound/duplicate gold; one-to-one matching needs two predictions)"
            )
        else:
            seen_spans[key] = cid
        criteria.append(GoldCriterion(cid, span, tuple(alts), tx, text))
    return EvalCase(
        case_id=case_id,
        sources=tuple(sources),
        criteria=tuple(criteria),
        well_specified=ws,
        group=raw.get("group") if isinstance(raw.get("group"), str) else None,
        author_type=(
            raw.get("author_type") if isinstance(raw.get("author_type"), str) else None
        ),
    )


def parse_gold(doc: object) -> GoldDataset:
    """Validate a decoded gold document and return the dataset.

    Raises :class:`GoldFormatError` listing every problem found.
    """
    err = _Collector()
    warnings: list[str] = []
    if not isinstance(doc, Mapping):
        raise GoldFormatError(["$: document must be an object"])
    if doc.get("schema") != GOLD_SCHEMA_ID:
        err.add("$.schema", f"must be {GOLD_SCHEMA_ID!r}, got {doc.get('schema')!r}")
    for key in ("name", "version", "split"):
        if not isinstance(doc.get(key), str) or not doc.get(key):
            err.add(f"$.{key}", "must be a non-empty string")
    synthetic = doc.get("synthetic", False)
    if not isinstance(synthetic, bool):
        err.add("$.synthetic", "must be a boolean")
        synthetic = False
    unit = doc.get("offset_unit", "codepoint")
    if unit not in OFFSET_UNITS:
        err.add("$.offset_unit", f"must be one of {OFFSET_UNITS}")
        unit = "codepoint"
    notes = doc.get("notes", [])
    if not isinstance(notes, list) or not all(isinstance(n, str) for n in notes):
        err.add("$.notes", "must be a list of strings")
        notes = []
    raw_cases = doc.get("cases")
    cases: list[EvalCase] = []
    if not isinstance(raw_cases, list) or not raw_cases:
        err.add("$.cases", "must be a non-empty list")
        raw_cases = []
    seen: set[str] = set()
    for i, rc in enumerate(raw_cases):
        case = _parse_case(rc, f"$.cases[{i}]", unit, err, warnings)
        if case is None:
            continue
        if case.case_id in seen:
            err.add(f"$.cases[{i}]", f"duplicate case_id {case.case_id!r}")
            continue
        seen.add(case.case_id)
        cases.append(case)
    if err.errors:
        raise GoldFormatError(err.errors)
    return GoldDataset(
        name=str(doc["name"]),
        version=str(doc["version"]),
        split=str(doc["split"]),
        synthetic=synthetic,
        cases=tuple(cases),
        notes=tuple(notes),
        warnings=tuple(warnings),
    )
