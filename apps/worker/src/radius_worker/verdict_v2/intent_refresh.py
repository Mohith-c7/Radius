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
The actor is written by the intent API from the authenticated principal (a signed-in
session user, or the API key), never from a request header (DEC-040). A session user linked
to a GitHub account is compared with the PR author's login; an unlinked confirmer is handled
by the ``confirm_policy`` (default: counted but labelled "unverified confirmer";
``require_second_person``: not counted). Residual risk: see the threat model.

Limits: no re-linking (hints or text edited after the analysis do not create new
edges until a new analysis), criteria that were not in Stage A are not scored (B-09: the
blocking marker ``intent_not_in_analysis:<n>`` says so until a new analysis), and a
criterion rejected at analysis time is not brought back by reopening it.
Provenance is never taken from a request: it is derived here from the stored state.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
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


_LABEL_PREFIX = re.compile(r"^(?:github|gh|user):", re.IGNORECASE)
NOT_IN_ANALYSIS_PREFIX = "intent_not_in_analysis:"

#: ``confirm_policy`` values (setting ``RADIUS_VERDICT_V2_CONFIRM_POLICY``).
POLICY_ALLOW_UNVERIFIED = "allow_unverified"
POLICY_REQUIRE_SECOND_PERSON = "require_second_person"
CONFIRM_POLICIES = (POLICY_ALLOW_UNVERIFIED, POLICY_REQUIRE_SECOND_PERSON)

UNVERIFIED_NOTE = "unverified confirmer"
SELF_NOTE = "the PR author: not counted"
SECOND_PERSON_NOTE = "not counted: not verified as a different person than the PR author"


@dataclass(frozen=True, slots=True)
class Confirmer:
    """Who confirmed, as recorded by the API from the authenticated principal (B-07).

    ``kind``: ``user`` (a signed-in session), ``api_key`` / ``legacy_key`` / ``dev`` (an
    organisation credential, no person) or ``label`` (an old row written before DEC-040,
    whose label was an unverified request header). ``github_login`` is set only when the
    signed-in user is linked to a GitHub account (OAuth), never from a header."""

    kind: str
    subject: str = ""
    github_login: str | None = None

    @property
    def display(self) -> str:
        if self.github_login:
            return self.github_login
        if self.kind == "user":
            return f"user {self.subject[:8]}" if self.subject else "user"
        if self.kind == "api_key":
            return f"api key {self.subject}" if self.subject else "api key"
        return self.subject or self.kind

    @property
    def declared_label(self) -> bool:
        """True when the name was chosen by the caller (old rows, development mode)."""

        return self.kind in {"label", "dev"}


@dataclass(frozen=True, slots=True)
class ConfirmDecision:
    counted: bool
    shown: str


#: ``(confirmer, PR author login) -> decision``; replaceable (see ``confirm_policy_for``).
ConfirmPolicy = Callable[[Confirmer, "str | None"], ConfirmDecision]


def parse_actor(actor: str) -> Confirmer:
    """Parse the audit actor ``org:<id>[/<principal>...]`` written by the intent API."""

    _, _, rest = actor.partition("/")
    rest = rest.strip()
    if not rest:
        return Confirmer(kind="org")
    kind, subject, login = "label", rest, None
    for part in rest.split("/"):
        if part.startswith("user="):
            kind, subject = "user", part[5:]
        elif part.startswith("key="):
            kind, subject = "api_key", part[4:]
        elif part.startswith("dev="):
            kind, subject = "dev", part[4:]
        elif part.startswith("gh="):
            login = part[3:] or None
        elif part == "legacy-env-key":
            kind, subject = "legacy_key", part
    if login is not None and kind != "user":
        login = None  # only a signed-in session can vouch for a GitHub link
    return Confirmer(kind=kind, subject=subject, github_login=login)


def actor_label(actor: str) -> str:
    """Display label of an audit actor (empty when none)."""

    who = parse_actor(actor)
    return "" if who.kind == "org" else who.display


def _norm_login(value: str) -> str:
    return _LABEL_PREFIX.sub("", value).strip().lower()


def _is_author(who: Confirmer, pr_author: str | None) -> bool:
    if not pr_author:
        return False
    author = _norm_login(pr_author)
    if not author:
        return False
    if who.github_login and _norm_login(who.github_login) == author:
        return True
    # a name the caller chose (old rows, development) equal to the author is never counted
    return who.declared_label and _norm_login(who.subject) == author


def default_confirm_policy(who: Confirmer, pr_author: str | None) -> ConfirmDecision:
    """Default: a self-confirmation never counts; a confirmer whose GitHub link is unknown
    counts but is labelled as unverified (it may be the PR author under another identity)."""

    name = who.display if who.kind != "org" else "org"
    if _is_author(who, pr_author):
        return ConfirmDecision(False, f"{name} ({SELF_NOTE})")
    if who.github_login and pr_author:
        return ConfirmDecision(True, name)  # verified: a linked account that is not the author
    return ConfirmDecision(True, f"{name} ({UNVERIFIED_NOTE})")


def require_second_person_policy(who: Confirmer, pr_author: str | None) -> ConfirmDecision:
    """Strict: only a confirmer verifiably linked to a GitHub account other than the PR
    author's counts; an unknown link or an unknown author does not."""

    name = who.display if who.kind != "org" else "org"
    if _is_author(who, pr_author):
        return ConfirmDecision(False, f"{name} ({SELF_NOTE})")
    if who.github_login and pr_author:
        return ConfirmDecision(True, name)
    return ConfirmDecision(False, f"{name} ({SECOND_PERSON_NOTE})")


def confirm_policy_for(name: str | None) -> ConfirmPolicy:
    """The policy for a setting value; an unknown value is an error, not a silent default."""

    value = (name or POLICY_ALLOW_UNVERIFIED).strip().lower()
    if value in {POLICY_ALLOW_UNVERIFIED, "allow"}:
        return default_confirm_policy
    if value == POLICY_REQUIRE_SECOND_PERSON:
        return require_second_person_policy
    msg = f"confirm policy must be one of {', '.join(CONFIRM_POLICIES)}."
    raise ValueError(msg)


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
    PR author's login a self-confirmation is ignored; ``confirm_policy`` decides the rest (B-07)."""

    current = {str(getattr(c, "id", "")): c for c in criteria}
    # one decision per confirmed criterion; a row without a recorded actor is an anonymous
    # organisation confirmation (counts under the default policy, labelled unverified)
    decisions = {
        cid: confirm_policy(parse_actor((actors or {}).get(cid, "")), pr_author)
        for cid, c in current.items()
        if _state(c) in _CONFIRMED
    }
    # criteria whose confirmation the policy refuses are treated as not confirmed below
    self_confirmed = {
        cid
        for cid, c in current.items()
        if _state(c) in _CONFIRMED and cid in decisions and not decisions[cid].counted
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
                    confirmed_by=decisions[item.criterion_id].shown[:160],
                )
            )
            continue
        updated.append(
            replace(
                item,
                lifecycle=life,
                confirmed_by=(
                    decisions[item.criterion_id].shown[:160]
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
