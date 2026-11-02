"""Extraction results: criteria plus diagnostics, traces and merge records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from radius_intent.domain import Criterion, SourceRef, Span


class DiagnosticKind(StrEnum):
    """Category of a diagnostic."""

    SKIPPED_REGION = "skipped_region"
    PARSE_ERROR = "parse_error"
    SUSPICIOUS = "suspicious"
    LIMIT = "limit"


class Severity(StrEnum):
    """How serious a diagnostic is."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Diagnostic:
    """Something extraction skipped, rejected or flagged, with its location.

    ``line`` is 1-based; ``start``/``end`` are character offsets into the
    source text (when known). ``code`` is a stable machine-readable reason.
    """

    kind: DiagnosticKind
    code: str
    message: str
    source_key: str
    severity: Severity = Severity.INFO
    line: int | None = None
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class CriterionTrace:
    """How a criterion was found (for metrics and UI explanations).

    ``checked`` is the task-list state (``None`` when not a task item).
    """

    criterion_id: str
    rule: str
    section: str | None = None
    checked: bool | None = None
    depth: int = 0


@dataclass(frozen=True)
class MergedOrigin:
    """A criterion that was merged into another as a near-duplicate."""

    criterion_id: str
    source: SourceRef
    span: Span
    text: str
    similarity: float


@dataclass(frozen=True)
class DuplicateGroup:
    """The kept criterion and the origins merged into it."""

    kept_id: str
    merged: tuple[MergedOrigin, ...]


@dataclass(frozen=True)
class ExtractionReport:
    """Everything one extraction run produced. Contains no timestamps."""

    extractor_version: str
    criteria: tuple[Criterion, ...]
    traces: tuple[CriterionTrace, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    duplicates: tuple[DuplicateGroup, ...] = ()

    @property
    def suspicious(self) -> bool:
        """Return whether any suspicious-content diagnostic was raised."""
        return any(d.kind is DiagnosticKind.SUSPICIOUS for d in self.diagnostics)

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        """Return the diagnostics of severity ERROR."""
        return tuple(
            d
            for d in self.diagnostics
            if d.kind is DiagnosticKind.PARSE_ERROR and d.severity is Severity.ERROR
        )

    def trace_for(self, criterion_id: str) -> CriterionTrace | None:
        """Return the trace of ``criterion_id`` if known."""
        for trace in self.traces:
            if trace.criterion_id == criterion_id:
                return trace
        return None
