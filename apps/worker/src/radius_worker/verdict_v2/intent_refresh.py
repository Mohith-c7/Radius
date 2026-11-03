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

Separation of duties (B-07): the confirming actor is recorded on the criterion
(``confirmed_by``, shown in the verdict). When a ``ConfirmPolicy`` says the actor is the
PR author, the confirmation is NOT counted: the criterion stays unconfirmed (the
``unconfirmed_inferred_intent`` block and the author-hint cap stay) and a reason says why.
Actor labels come from the unverified ``X-Radius-Actor`` header, so this is a best-effort
guard against the honest mistake and the lazy bypass, not against a determined author
(see the threat model).

Limits: no re-linking (hints or text edited after the analysis do not create new
edges until a new analysis), criteria that were not in Stage A are not scored (B-09: the
blocking marker ``intent_not_in_analysis:<n>`` says so until a new analysis), and a
criterion rejected at analysis time is not brought back by reopening it.
Provenance is never taken from a request: it is derived here from the stored state.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from types import SimpleNamespace
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


#: ``(actor label, PR author login) -> True`` when the confirmation must not count.
ConfirmPolicy = Callable[[str, str | None], bool]

_LABEL_PREFIX = re.compile(r"^(?:github|gh|user):", re.IGNORECASE)
NOT_IN_ANALYSIS_PREFIX = "intent_not_in_analysis:"


def actor_label(actor: str) -> str:
    """The human label of an audit actor ``org:<id>[/<label>]`` (empty when none)."""

    _, _, label = actor.partition("/")
    return label.strip()


def default_confirm_policy(label: str, pr_author: str | None) -> bool:
    """True (reject) when the confirming label names the PR author. Unknown author: accept."""

    if not pr_author or not label:
        return False
    norm = _LABEL_PREFIX.sub("", label).strip().lower()
    return bool(norm) and norm == _LABEL_PREFIX.sub("", pr_author).strip().lower()


def confirming_actors(changes: Iterable[Any]) -> dict[str, str]:
    """``criterion_id -> actor`` of the latest transition into confirmed / edited."""

    out: dict[str, str] = {}
    for ch in changes:  # list_state_changes order: by time, then sequence
        cid = str(getattr(ch, "criterion_id", ""))
        new = adapters._enum_value(getattr(ch, "new_state", ""))
        if new in _CONFIRMED:
            out[cid] = str(getattr(ch, "actor", ""))
        else:
            out.pop(cid, None)
    return out


def refresh_stage_a_intent(
    stage_a: StageAInput,
    criteria: Iterable[Any],
    *,
    actors: Mapping[str, str] | None = None,
    pr_author: str | None = None,
    confirm_policy: ConfirmPolicy = default_confirm_policy,
) -> StageAInput:
    """Return ``stage_a`` with the current human decisions applied (identity if none).

    ``actors`` maps criterion id to the audit actor of its latest confirm / edit; with the
    PR author's login a self-confirmation is ignored (B-07)."""

    current = {str(getattr(c, "id", "")): c for c in criteria}
    labels = {cid: actor_label(a) for cid, a in (actors or {}).items()}
    # self-confirmed criteria are treated as not confirmed everywhere below
    self_confirmed = {
        cid
        for cid, c in current.items()
        if _state(c) in _CONFIRMED and confirm_policy(labels.get(cid, ""), pr_author)
    }
    for cid in self_confirmed:
        db = current[cid]
        current[cid] = SimpleNamespace(
            id=cid,
            state=SimpleNamespace(value="proposed"),
            origin=getattr(db, "origin", None),
            text=getattr(db, "text", None),
        )
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
                    confirmed_by=labels.get(item.criterion_id) or "org",
                )
            )
            continue
        updated.append(
            replace(
                item,
                lifecycle=life,
                confirmed_by=(
                    f"{labels.get(item.criterion_id) or 'org'} (the PR author: not counted)"
                    if item.criterion_id in self_confirmed
                    else None
                ),
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

    degraded = tuple(
        d
        for d in stage_a.degraded
        if d != adapters.UNCONFIRMED_INFERRED_MARKER and not d.startswith(NOT_IN_ANALYSIS_PREFIX)
    )
    if adapters.has_unconfirmed_inferred_intent(current.values()):
        degraded = (*degraded, adapters.UNCONFIRMED_INFERRED_MARKER)
    # B-09: live criteria the analysis never saw (a manual criterion added afterwards, a
    # reopened rejected one) cannot be scored without a new analysis; say so, block verified
    known = {c.criterion_id for c in stage_a.criteria}
    unseen = [cid for cid, c in current.items() if cid not in known and _state(c) not in _DROPPED]
    if unseen:
        degraded = (*degraded, f"{NOT_IN_ANALYSIS_PREFIX}{len(unseen)}")

    return replace(
        stage_a,
        criteria=tuple(updated),
        criterion_symbol=tuple(
            e for e in stage_a.criterion_symbol if e.criterion_id not in removed
        ),
        criterion_test=tuple(edges),
        degraded=degraded,
    )
