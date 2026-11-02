"""Pure merge and carry-over rules for building a snapshot (IN-06).

No I/O, no clock. See ``packages/intent/README.md`` for the rule tables.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from radius_intent.application.models import CarryEvent, Diagnostic
from radius_intent.domain import (
    Criterion,
    CriterionState,
    ExtractionMethod,
    IntentSnapshot,
    IntentSourceKind,
    SourceRef,
)

#: Minimum similarity (difflib ratio of normalized texts, same source) for a
#: new criterion to count as the reworded successor of a vanished one.
REWORD_THRESHOLD = 0.6

_KIND_ORDER = {kind: index for index, kind in enumerate(IntentSourceKind)}
_METHOD_ORDER = {
    ExtractionMethod.HUMAN: 1,
    ExtractionMethod.DETERMINISTIC: 2,
    ExtractionMethod.LLM: 3,
}
#: States that carry a human decision worth protecting from silent loss.
_PROTECTED = frozenset(
    {
        CriterionState.CONFIRMED,
        CriterionState.EDITED,
        CriterionState.NEEDS_RECONFIRMATION,
        CriterionState.ORPHANED,
    }
)


def priority(criterion: Criterion) -> int:
    """Rank by extraction priority: spec_file(0) > human(1) > deterministic(2) > llm(3)."""
    if criterion.origin.source.kind is IntentSourceKind.SPEC_FILE:
        return 0
    return _METHOD_ORDER[criterion.origin.extraction_method]


def sort_key(criterion: Criterion) -> tuple[int, str, int, int, str]:
    """Total order used for snapshot criteria: source kind, source, span, id."""
    ref = criterion.origin.source
    return (
        _KIND_ORDER[ref.kind],
        ref.source_id,
        criterion.span.start,
        criterion.span.end,
        criterion.id,
    )


def signature(criterion: Criterion) -> tuple[object, ...]:
    """Content identity ignoring ``retrieved_at`` (changes on every re-fetch)."""
    return (
        criterion.id,
        criterion.text,
        criterion.normalized_text,
        criterion.origin.source,
        criterion.origin.extraction_method,
        criterion.origin.extractor_version,
        criterion.span,
        criterion.weight,
        criterion.testability,
        criterion.testability_rationale,
        criterion.state,
    )


@dataclass(frozen=True)
class Candidate:
    """An extracted criterion plus the registration index of its extractor."""

    criterion: Criterion
    extractor_index: int


def select_criteria(
    candidates: list[Candidate],
) -> tuple[tuple[Criterion, ...], tuple[Diagnostic, ...]]:
    """Merge extractor output into a deduplicated, deterministically ordered set.

    1. Same id (same source + normalized text): keep the best by
       ``(priority, extractor_index, extractor_version, span.start)``.
    2. Same normalized text in different sources: keep the best by
       ``(priority, source kind order, source_id, span.start, id)``; the
       others are reported as ``deduplicated``.
    Result order is :func:`sort_key`.
    """
    by_id: dict[str, Candidate] = {}
    for cand in candidates:
        key = (
            priority(cand.criterion),
            cand.extractor_index,
            cand.criterion.origin.extractor_version,
            cand.criterion.span.start,
        )
        best = by_id.get(cand.criterion.id)
        if best is None or key < (
            priority(best.criterion),
            best.extractor_index,
            best.criterion.origin.extractor_version,
            best.criterion.span.start,
        ):
            by_id[cand.criterion.id] = cand
    by_text: dict[str, Criterion] = {}
    diagnostics: list[Diagnostic] = []
    for crit in sorted((c.criterion for c in by_id.values()), key=sort_key):
        incumbent = by_text.get(crit.normalized_text)
        if incumbent is None:
            by_text[crit.normalized_text] = crit
            continue
        loser = crit
        if (priority(crit), sort_key(crit)) < (
            priority(incumbent),
            sort_key(incumbent),
        ):
            by_text[crit.normalized_text] = crit
            loser = incumbent
        diagnostics.append(
            Diagnostic(
                "deduplicated",
                f"{loser.id} merged into an identical criterion from another source.",
                loser.origin.source.key,
            )
        )
    return tuple(sorted(by_text.values(), key=sort_key)), tuple(diagnostics)


@dataclass(frozen=True)
class PlannedChange:
    """A state change to record through ``IntentRepository.record_state_change``."""

    criterion_id: str
    new_state: CriterionState
    new_text: str | None
    reason: str


@dataclass(frozen=True)
class MergePlan:
    """Seed criteria (saved as version N), then the changes replayed on top."""

    seeds: tuple[Criterion, ...]
    changes: tuple[PlannedChange, ...]
    events: tuple[CarryEvent, ...]

    @property
    def final(self) -> tuple[Criterion, ...]:
        """The criteria after replaying ``changes`` (mirrors the repository)."""
        by_id = {c.id: c for c in self.seeds}
        for change in self.changes:
            current = by_id[change.criterion_id]
            if change.new_state is CriterionState.EDITED:
                by_id[current.id] = current.edit(change.new_text or current.text)
            else:
                by_id[current.id] = current.transition_to(change.new_state)
        return tuple(by_id[c.id] for c in self.seeds)


def _repoint(criterion: Criterion, refs: dict[str, SourceRef]) -> Criterion:
    """Cite the current ref of the criterion's source when it still exists."""
    current = refs.get(criterion.origin.source.key)
    if current is None or current == criterion.origin.source:
        return criterion
    return replace(criterion, origin=replace(criterion.origin, source=current))


def _similarity(a: Criterion, b: Criterion) -> float:
    return SequenceMatcher(None, a.normalized_text, b.normalized_text).ratio()


class _Planner:
    def __init__(
        self,
        live: tuple[Criterion, ...],
        previous: IntentSnapshot,
        refs: dict[str, SourceRef],
        failed_keys: frozenset[str],
        failed_kinds: frozenset[IntentSourceKind],
        trigger: str,
    ) -> None:
        self.live = live
        self.previous = previous
        self.refs = refs
        self.failed_keys = failed_keys
        self.failed_kinds = failed_kinds
        self.trigger = trigger
        self.seeds: dict[str, Criterion] = {c.id: c for c in live}
        self.retained: list[Criterion] = []
        self.changes: list[PlannedChange] = []
        self.events: list[CarryEvent] = []

    # -- carrying a decision onto a freshly extracted criterion ----------
    def _carry(self, new: Criterion, old: Criterion, action: str) -> None:
        v = self.previous.version
        reason = f"{action} from v{v} ({self.trigger})"
        state = old.state
        if state is CriterionState.CONFIRMED:
            self._plan(new.id, CriterionState.CONFIRMED, None, reason)
        elif state is CriterionState.REJECTED:
            self._plan(new.id, CriterionState.REJECTED, None, reason)
        elif state is CriterionState.EDITED:
            self._plan(new.id, CriterionState.EDITED, old.text, reason)
        elif state in (CriterionState.NEEDS_RECONFIRMATION, CriterionState.ORPHANED):
            # System states: seeded directly. An orphan that reappeared must be
            # re-confirmed by a human.
            self.seeds[new.id] = replace(new, state=CriterionState.NEEDS_RECONFIRMATION)
            state = CriterionState.NEEDS_RECONFIRMATION
            if old.state is CriterionState.ORPHANED:
                action = "restored"
        else:  # PROPOSED: nothing to carry
            return
        self.events.append(CarryEvent(action, new.id, old.id, state))

    def _plan(
        self,
        criterion_id: str,
        state: CriterionState,
        text: str | None,
        reason: str,
    ) -> None:
        self.changes.append(PlannedChange(criterion_id, state, text, reason))

    def _is_failed(self, old: Criterion) -> bool:
        ref = old.origin.source
        return ref.key in self.failed_keys or ref.kind in self.failed_kinds

    # -- phases ----------------------------------------------------------
    def run(self) -> MergePlan:
        live_ids = {c.id for c in self.live}
        for old in self.previous.criteria:
            if old.id in live_ids:
                self._carry(self.seeds[old.id], old, "carried")
        gone = [c for c in self.previous.criteria if c.id not in live_ids]
        fresh = [c for c in self.live if self.previous.get(c.id) is None]
        gone = self._retain_failed(gone)
        gone, fresh = self._match_moved(gone, fresh)
        gone = self._match_reworded(gone, fresh)
        for old in gone:
            self._orphan_or_drop(old)
        return self._finish()

    def _retain_failed(self, gone: list[Criterion]) -> list[Criterion]:
        rest: list[Criterion] = []
        for old in gone:
            if self._is_failed(old) or old.origin.extraction_method is (
                ExtractionMethod.HUMAN
            ):
                self.retained.append(_repoint(old, self.refs))
                if old.state in _PROTECTED:
                    self.events.append(
                        CarryEvent("retained", old.id, old.id, old.state)
                    )
            else:
                rest.append(old)
        return rest

    def _match_moved(
        self, gone: list[Criterion], fresh: list[Criterion]
    ) -> tuple[list[Criterion], list[Criterion]]:
        """Identical normalized text under a new id (moved between sources)."""
        by_text: dict[str, Criterion] = {}
        for new in fresh:
            by_text.setdefault(new.normalized_text, new)
        rest: list[Criterion] = []
        taken: set[str] = set()
        for old in gone:
            new = by_text.get(old.normalized_text)
            if new is None or new.id in taken or old.state not in _PROTECTED:
                rest.append(old)
                continue
            taken.add(new.id)
            self._carry(new, old, "moved")
        return rest, [c for c in fresh if c.id not in taken]

    def _match_reworded(
        self, gone: list[Criterion], fresh: list[Criterion]
    ) -> list[Criterion]:
        """Same source, similar text, protected state: needs reconfirmation."""
        pairs = sorted(
            (-score, old.id, new.id)
            for old in gone
            if old.state in _PROTECTED
            for new in fresh
            if new.origin.source.key == old.origin.source.key
            and (score := _similarity(old, new)) >= REWORD_THRESHOLD
        )
        old_by_id = {c.id: c for c in gone}
        new_by_id = {c.id: c for c in fresh}
        used_old: set[str] = set()
        used_new: set[str] = set()
        for _, old_id, new_id in pairs:
            if old_id in used_old or new_id in used_new:
                continue
            used_old.add(old_id)
            used_new.add(new_id)
            old, new = old_by_id[old_id], new_by_id[new_id]
            seeded = replace(new, state=old.state)
            if old.state is CriterionState.ORPHANED:
                seeded = replace(new, state=CriterionState.NEEDS_RECONFIRMATION)
            self.seeds[new.id] = seeded
            if seeded.state is not CriterionState.NEEDS_RECONFIRMATION:
                self._plan(
                    new.id,
                    CriterionState.NEEDS_RECONFIRMATION,
                    None,
                    f"text changed since v{self.previous.version} "
                    f"(was {old.id}: {old.text!r}); {self.trigger}",
                )
            self.events.append(
                CarryEvent(
                    "needs_reconfirmation",
                    new.id,
                    old.id,
                    CriterionState.NEEDS_RECONFIRMATION,
                )
            )
        return [c for c in gone if c.id not in used_old]

    def _orphan_or_drop(self, old: Criterion) -> None:
        if old.state not in _PROTECTED:
            return  # proposed / rejected criteria may disappear with their text
        kept = _repoint(old, self.refs)
        if old.state is CriterionState.ORPHANED:
            self.retained.append(kept)
        else:
            # Seed with the prior state, then audit the move to ORPHANED.
            self.retained.append(kept)
            self._plan(
                old.id,
                CriterionState.ORPHANED,
                None,
                f"no longer present in sources since v{self.previous.version} "
                f"({self.trigger})",
            )
        self.events.append(
            CarryEvent("orphaned", old.id, old.id, CriterionState.ORPHANED)
        )

    def _finish(self) -> MergePlan:
        seeds = tuple(self.seeds[c.id] for c in self.live) + tuple(
            sorted(self.retained, key=sort_key)
        )
        return MergePlan(seeds, tuple(self.changes), tuple(self.events))


def plan_merge(
    live: tuple[Criterion, ...],
    previous: IntentSnapshot | None,
    refs: dict[str, SourceRef],
    *,
    failed_keys: frozenset[str] = frozenset(),
    failed_kinds: frozenset[IntentSourceKind] = frozenset(),
    trigger: str = "rebuild",
) -> MergePlan:
    """Combine freshly extracted ``live`` criteria with the previous snapshot.

    ``refs`` maps ``SourceRef.key`` to the current ref of every fetched source.
    Sources whose fetch or extraction failed are listed in ``failed_keys`` /
    ``failed_kinds``: their previous criteria are retained untouched.
    """
    if previous is None:
        return MergePlan(live, (), ())
    return _Planner(live, previous, refs, failed_keys, failed_kinds, trigger).run()
