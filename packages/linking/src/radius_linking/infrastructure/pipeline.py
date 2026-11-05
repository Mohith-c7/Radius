"""Convenience wiring: LK-01 change set + IN-01 criteria -> :class:`LinkSet`."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence

from radius_analysis.symbol_changes import SymbolChangeSet
from radius_intent.domain import Criterion

from radius_linking.application import LinkingConfig, link_criteria
from radius_linking.domain import (
    CriterionInput,
    LinkerPort,
    LinkSet,
    NeighborPort,
    Reranker,
    SymbolDoc,
)
from radius_linking.infrastructure.linkers import ChangePriorLinker, default_linkers
from radius_linking.infrastructure.neighbors import CallGraphNeighbors
from radius_linking.infrastructure.symbol_docs import SnapshotLike, build_symbol_docs

#: Criterion states that are linked (rejected and orphaned criteria are not).
LINKABLE_STATES = frozenset({"confirmed", "proposed", "edited", "needs_reconfirmation"})


def criterion_input(criterion: Criterion) -> CriterionInput:
    """Adapt an IN-01 ``Criterion`` (text, testability rationale, path/test hints)."""

    return CriterionInput(
        criterion_id=criterion.id,
        text=criterion.text,
        rationale=criterion.testability_rationale,
        paths=tuple(criterion.hints.paths),
        tests=tuple(criterion.hints.tests),
        weight=criterion.weight,
        state=criterion.state.value,
    )


def criteria_inputs(criteria: Iterable[Criterion]) -> list[CriterionInput]:
    """Inputs for linkable criteria (rejected and orphaned ones are skipped)."""

    return [criterion_input(c) for c in criteria if c.state.value in LINKABLE_STATES]


def changeset_ref(changeset: SymbolChangeSet) -> str:
    """Stable reference to a change set: algorithm version plus a content hash."""

    digest = hashlib.sha256(changeset.to_json().encode("utf-8")).hexdigest()[:16]
    return f"{changeset.algo_version}:{digest}"


def link_changeset(
    criteria: Sequence[CriterionInput],
    changeset: SymbolChangeSet,
    head: SnapshotLike,
    base: SnapshotLike | None = None,
    *,
    snapshot_id: str = "",
    config: LinkingConfig | None = None,
    linkers: Sequence[LinkerPort] | None = None,
    reranker: Reranker | None = None,
    neighbors: NeighborPort | None = None,
    python_sources: Mapping[str, str] | None = None,
) -> tuple[LinkSet, list[SymbolDoc]]:
    """Link ``criteria`` to the symbols of ``changeset``; returns the link set and the documents.

    ``python_sources`` (path -> head text) enables call-graph neighbours for the
    structural linker when ``neighbors`` is not given.
    """

    docs = build_symbol_docs(changeset, head, base)
    if neighbors is None and python_sources:
        neighbors = CallGraphNeighbors(python_sources, [d.ref for d in docs])
    linkset = link_criteria(
        criteria,
        docs,
        linkers=list(linkers) if linkers is not None else default_linkers(),
        prior=ChangePriorLinker(),
        config=config,
        neighbors=neighbors,
        reranker=reranker,
        snapshot_id=snapshot_id,
        changeset_ref=changeset_ref(changeset),
    )
    return linkset, docs
