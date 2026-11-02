"""Pure snapshot diff producing a stable, serializable result."""

from __future__ import annotations

from radius_intent.application.models import (
    CriterionDelta,
    CriterionSummary,
    SnapshotDiffResult,
)
from radius_intent.domain import Criterion, IntentSnapshot


def _fields_changed(old: Criterion, new: Criterion) -> tuple[str, ...]:
    pairs = (
        ("text", old.text, new.text),
        ("weight", old.weight, new.weight),
        ("testability", old.testability, new.testability),
        ("rationale", old.testability_rationale, new.testability_rationale),
        (
            "extraction_method",
            old.origin.extraction_method,
            new.origin.extraction_method,
        ),
        (
            "extractor_version",
            old.origin.extractor_version,
            new.origin.extractor_version,
        ),
        ("source", old.origin.source.key, new.origin.source.key),
    )
    return tuple(name for name, a, b in pairs if a != b)


def diff_snapshot_pair(old: IntentSnapshot, new: IntentSnapshot) -> SnapshotDiffResult:
    """Diff ``old`` against ``new`` matching criteria by stable id."""
    before = {c.id: c for c in old.criteria}
    after = {c.id: c for c in new.criteria}
    added = tuple(
        CriterionSummary.of(after[i]) for i in sorted(after.keys() - before.keys())
    )
    removed = tuple(
        CriterionSummary.of(before[i]) for i in sorted(before.keys() - after.keys())
    )
    changed: list[CriterionDelta] = []
    state_changed: list[CriterionDelta] = []
    moved: list[str] = []
    for cid in sorted(before.keys() & after.keys()):
        a, b = before[cid], after[cid]
        fields = _fields_changed(a, b)
        if fields:
            changed.append(
                CriterionDelta(
                    cid, fields, a.text, b.text, a.state.value, b.state.value
                )
            )
        if a.state != b.state:
            state_changed.append(
                CriterionDelta(
                    cid, ("state",), a.text, b.text, a.state.value, b.state.value
                )
            )
        if not fields and a.span != b.span:
            moved.append(cid)
    old_refs = {r.key: r for r in old.sources}
    new_refs = {r.key: r for r in new.sources}
    return SnapshotDiffResult(
        from_snapshot_id=old.snapshot_id,
        to_snapshot_id=new.snapshot_id,
        from_version=old.version,
        to_version=new.version,
        added=added,
        removed=removed,
        changed=tuple(changed),
        state_changed=tuple(state_changed),
        moved=tuple(moved),
        sources_added=tuple(sorted(new_refs.keys() - old_refs.keys())),
        sources_removed=tuple(sorted(old_refs.keys() - new_refs.keys())),
        sources_changed=tuple(
            sorted(
                k
                for k in old_refs.keys() & new_refs.keys()
                if old_refs[k] != new_refs[k]
            )
        ),
    )
