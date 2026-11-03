"""Refresh the stored Stage A bundle with the current human decisions (DEC-033).

Stage A is frozen at analysis time, so a criterion confirmed, edited or rejected in
the intent panel afterwards is not in it. ``refresh_stage_a_intent`` re-applies the
*current criterion states* (read from the database, which only the authenticated
intent API writes) onto the stored Stage A without a clone:

* ``confirmed`` / ``edited``: lifecycle updated, provenance of the criterion and of its
  ``tests:`` hint edges becomes ``human_confirmed`` (the author-hint cap is lifted);
  an edit also updates the text;
* ``rejected`` / ``orphaned``: the criterion and its edges are removed;
* back to ``proposed`` / ``needs_reconfirmation``: lifecycle updated and human_confirmed
  provenance is demoted to ``author_pr_body`` (capped, conservative);
* the blocking marker ``unconfirmed_inferred_intent`` is recomputed from the current
  criteria with the same rule as Stage A collection.

Limits: no re-linking (hints or text edited after the analysis do not create new
edges until a new analysis), criteria that were not in Stage A are ignored, and a
criterion rejected at analysis time is not brought back by reopening it.
Provenance is never taken from a request: it is derived here from the stored state.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from radius_evidence.domain.enums import TRUSTED_HINT_PROVENANCE, Provenance
from radius_evidence.domain.inputs import StageAInput

from radius_worker.verdict_v2 import adapters
from radius_worker.verdict_v2.scoring import HINT_METHOD

_CONFIRMED = adapters._CONFIRMED_LIFECYCLE
_DROPPED = adapters.DROPPED_LIFECYCLE
_HUMAN = Provenance.HUMAN_CONFIRMED.value
_DEMOTED = Provenance.AUTHOR_PR_BODY.value


def _state(criterion: Any) -> str:
    return adapters._enum_value(getattr(criterion, "state", "proposed"))


def refresh_stage_a_intent(stage_a: StageAInput, criteria: Iterable[Any]) -> StageAInput:
    """Return ``stage_a`` with the current human decisions applied (identity if none)."""

    current = {str(getattr(c, "id", "")): c for c in criteria}
    removed: set[str] = set()
    confirmed: set[str] = set()
    updated = []
    for item in stage_a.criteria:
        db = current.get(item.criterion_id)
        if db is None:
            updated.append(item)
            continue
        life = _state(db)
        if life in _DROPPED:
            removed.add(item.criterion_id)
            continue
        if life in _CONFIRMED:
            confirmed.add(item.criterion_id)
            text = adapters._str(getattr(db, "text", None))
            updated.append(
                replace(
                    item,
                    lifecycle=life,
                    text=text if life == "edited" and text else item.text,
                    provenance=_HUMAN,
                    hints_provenance=_HUMAN,
                )
            )
            continue
        updated.append(
            replace(
                item,
                lifecycle=life,
                provenance=_DEMOTED if item.provenance == _HUMAN else item.provenance,
                hints_provenance=(
                    _DEMOTED if item.hints_provenance == _HUMAN else item.hints_provenance
                ),
            )
        )

    edges = []
    for e in stage_a.criterion_test:
        if e.criterion_id in removed:
            continue
        if e.method == HINT_METHOD:
            if e.criterion_id in confirmed and e.provenance not in TRUSTED_HINT_PROVENANCE:
                e = replace(e, provenance=_HUMAN)
            elif e.criterion_id in current and e.criterion_id not in confirmed:
                if e.provenance == _HUMAN:
                    e = replace(e, provenance=_DEMOTED)
        edges.append(e)

    degraded = tuple(d for d in stage_a.degraded if d != adapters.UNCONFIRMED_INFERRED_MARKER)
    if adapters.has_unconfirmed_inferred_intent(current.values()):
        degraded = (*degraded, adapters.UNCONFIRMED_INFERRED_MARKER)

    return replace(
        stage_a,
        criteria=tuple(updated),
        criterion_symbol=tuple(
            e for e in stage_a.criterion_symbol if e.criterion_id not in removed
        ),
        criterion_test=tuple(edges),
        degraded=degraded,
    )
