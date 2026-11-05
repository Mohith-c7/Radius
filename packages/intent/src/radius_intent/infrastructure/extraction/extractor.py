"""DeterministicCriterionExtractor: the LLM-free ``CriterionExtractor``."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable

from radius_intent.domain import (
    Criterion,
    ExtractionMethod,
    IntentDomainError,
    IntentSource,
    IntentSourceKind,
    Span,
)

from .candidates import Candidate, Collector
from .config import (
    DETERMINISTIC_EXTRACTOR_VERSION,
    ExtractionConfig,
    source_priority,
)
from .dedupe import Entry, merge_duplicates
from .markdown import MarkdownScanner
from .report import (
    CriterionTrace,
    Diagnostic,
    DiagnosticKind,
    ExtractionReport,
    Severity,
)
from .spec_file import extract_spec
from .summary import extract_summary
from .text import (
    comment_is_suspicious,
    has_invisible_characters,
    mask_html_comments,
    split_lines,
)

MAX_DIAGNOSTICS = 1000


class DeterministicCriterionExtractor:
    """Extract proposed criteria with fixed rules (no LLM, network or clock).

    Implements the :class:`~radius_intent.interfaces.CriterionExtractor` port.
    Output is a pure function of ``(source, config)``: same input gives
    byte-identical criteria, ids and diagnostics.
    """

    def __init__(self, config: ExtractionConfig | None = None) -> None:
        self.config = config or ExtractionConfig()
        self._compiled = self.config.compiled()

    # -- port ---------------------------------------------------------------

    def extract(self, source: IntentSource) -> tuple[Criterion, ...]:
        """Return the PROPOSED criteria of one source (port method)."""
        return self.extract_report(source).criteria

    # -- reports ------------------------------------------------------------

    def extract_report(self, source: IntentSource) -> ExtractionReport:
        """Extract one source, merging duplicates inside it."""
        entries, diags = self._entries(source)
        return self._finish(entries, diags)

    def extract_sources(self, sources: Iterable[IntentSource]) -> ExtractionReport:
        """Extract several sources and merge near-duplicates across them.

        The result does not depend on the order of ``sources``. If two sources
        share a ``kind:id`` key only the one with the smallest raw hash is read.
        """
        chosen: dict[str, IntentSource] = {}
        diags: list[Diagnostic] = []
        for src in sorted(sources, key=lambda s: (s.ref.key, s.raw_text_hash)):
            if src.ref.key in chosen:
                diags.append(
                    Diagnostic(
                        DiagnosticKind.SKIPPED_REGION,
                        "duplicate_source",
                        "A source with the same kind and id was already read.",
                        src.ref.key,
                        Severity.WARNING,
                    )
                )
            else:
                chosen[src.ref.key] = src
        entries: list[Entry] = []
        for src in sorted(
            chosen.values(), key=lambda s: (-source_priority(s.kind), s.ref.key)
        ):
            found, more = self._entries(src)
            entries += found
            diags += more
        return self._finish(entries, diags)

    # -- internals ----------------------------------------------------------

    def _finish(
        self, entries: list[Entry], diags: list[Diagnostic]
    ) -> ExtractionReport:
        kept, groups = merge_duplicates(entries, self.config.similarity_threshold)
        return ExtractionReport(
            extractor_version=DETERMINISTIC_EXTRACTOR_VERSION,
            criteria=tuple(e.criterion for e in kept),
            traces=tuple(e.trace for e in kept),
            diagnostics=tuple(diags),
            duplicates=tuple(groups),
        )

    def _entries(self, source: IntentSource) -> tuple[list[Entry], list[Diagnostic]]:
        key = source.ref.key
        is_spec = source.kind is IntentSourceKind.SPEC_FILE
        collector = Collector(key, max_diagnostics=MAX_DIAGNOSTICS)
        if is_spec:
            masked = source.text
            lines = split_lines(masked)
        else:
            masked, comments = mask_html_comments(source.text)
            lines = split_lines(masked)
            self._comment_diagnostics(collector, lines, comments)
        if has_invisible_characters(source.text):
            collector.note(
                DiagnosticKind.SUSPICIOUS,
                "invisible_characters",
                "Text contains zero-width or bidirectional control characters.",
                severity=Severity.WARNING,
            )
        if source.suspicious_content_removed:
            collector.note(
                DiagnosticKind.SUSPICIOUS,
                "suspicious_removed_upstream",
                "Ingestion removed hidden or suspicious content from this source.",
                severity=Severity.WARNING,
            )
        if source.truncated:
            collector.note(
                DiagnosticKind.LIMIT,
                "truncated",
                "Source was truncated at ingestion; later criteria may be missing.",
                severity=Severity.WARNING,
            )
        if is_spec:
            extract_spec(lines, source.source_id, collector)
        else:
            MarkdownScanner(lines, self.config, self._compiled, collector).scan(masked)
            if self.config.mode in ("summary", "llm") and source.kind in (
                IntentSourceKind.PR_BODY,
                IntentSourceKind.PR_TITLE,
            ):
                extract_summary(
                    lines,
                    source.kind is IntentSourceKind.PR_TITLE,
                    self.config,
                    collector,
                )

        entries: list[Entry] = []
        for cand in sorted(
            collector.candidates, key=lambda c: (c.start, c.end, c.rule)
        ):
            entry = self._build(source, cand, collector)
            if entry is not None:
                entries.append(entry)
        return entries, collector.finish()

    def _build(
        self, source: IntentSource, cand: Candidate, collector: Collector
    ) -> Entry | None:
        try:
            criterion = Criterion.create(
                source,
                Span(source.source_id, cand.start, cand.end),
                extraction_method=ExtractionMethod.DETERMINISTIC,
                extractor_version=cand.extractor_version
                or DETERMINISTIC_EXTRACTOR_VERSION,
                text=cand.text,
                weight=cand.weight,
                hints=cand.hints,
            )
        except IntentDomainError as exc:
            collector.note(
                DiagnosticKind.PARSE_ERROR,
                "invalid_candidate",
                str(exc),
                severity=Severity.ERROR,
                start=cand.start,
                end=cand.end,
            )
            return None
        trace = CriterionTrace(
            criterion.id, cand.rule, cand.section, cand.checked, cand.depth
        )
        return Entry(criterion, trace)

    @staticmethod
    def _comment_diagnostics(collector: Collector, lines: list, comments: list) -> None:
        starts = [ln.start for ln in lines]
        for comment in comments:
            line = lines[bisect_right(starts, comment.start) - 1].number
            if not comment.terminated:
                collector.note(
                    DiagnosticKind.SUSPICIOUS,
                    "unterminated_html_comment",
                    "An HTML comment is never closed; the rest of the text is hidden.",
                    severity=Severity.WARNING,
                    line=line,
                    start=comment.start,
                    end=comment.end,
                )
            elif comment_is_suspicious(comment):
                collector.note(
                    DiagnosticKind.SUSPICIOUS,
                    "hidden_comment_content",
                    "An HTML comment hides criteria-like or instruction-like text.",
                    severity=Severity.WARNING,
                    line=line,
                    start=comment.start,
                    end=comment.end,
                )
            else:
                collector.skip(
                    "html_comment",
                    "HTML comment ignored.",
                    line=line,
                    start=comment.start,
                    end=comment.end,
                )
