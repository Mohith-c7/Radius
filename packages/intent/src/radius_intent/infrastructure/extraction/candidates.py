"""Candidate criteria found by the parsers, and the diagnostics collector."""

from __future__ import annotations

from dataclasses import dataclass, field

from radius_intent.domain import CriterionHints

from .report import Diagnostic, DiagnosticKind, Severity
from .text import Line


@dataclass(frozen=True)
class Candidate:
    """A statement found in a source, before it becomes a Criterion.

    ``start``/``end`` is the span into the source text; ``text`` is the
    statement (comments removed, whitespace collapsed).
    """

    start: int
    end: int
    text: str
    rule: str
    section: str | None = None
    checked: bool | None = None
    depth: int = 0
    weight: float = 1.0
    hints: CriterionHints = CriterionHints()


@dataclass
class Collector:
    """Accumulates candidates and diagnostics for one source."""

    source_key: str
    lines: list[Line] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    max_diagnostics: int = 1000
    dropped: int = 0

    def add(self, candidate: Candidate) -> None:
        """Record a candidate."""
        self.candidates.append(candidate)

    def note(
        self,
        kind: DiagnosticKind,
        code: str,
        message: str,
        *,
        severity: Severity = Severity.INFO,
        line: int | None = None,
        start: int | None = None,
        end: int | None = None,
    ) -> None:
        """Record a diagnostic (bounded; overflow is counted, see finish)."""
        if len(self.diagnostics) >= self.max_diagnostics:
            self.dropped += 1
            return
        self.diagnostics.append(
            Diagnostic(kind, code, message, self.source_key, severity, line, start, end)
        )

    def skip(
        self,
        code: str,
        message: str,
        *,
        line: int | None = None,
        start: int | None = None,
        end: int | None = None,
    ) -> None:
        """Record a skipped region."""
        self.note(
            DiagnosticKind.SKIPPED_REGION,
            code,
            message,
            line=line,
            start=start,
            end=end,
        )

    def finish(self) -> list[Diagnostic]:
        """Return the diagnostics, plus a LIMIT note if some were dropped."""
        out = list(self.diagnostics)
        if self.dropped:
            out.append(
                Diagnostic(
                    DiagnosticKind.LIMIT,
                    "diagnostics_truncated",
                    f"{self.dropped} further diagnostics were not recorded.",
                    self.source_key,
                    Severity.WARNING,
                )
            )
        return out
