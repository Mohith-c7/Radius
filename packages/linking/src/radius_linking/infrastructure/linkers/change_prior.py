"""Change-kind prior: behavioural changes outrank formatting / docstring-only ones.

This is a *modifier*, not evidence of a link by itself: every symbol gets a prior
from its LK-01 ``change_kind`` and ``is_behavioral`` flag, and the combiner uses
it to scale a symbol's evidence (``base * (1 - s + s * prior)``). The linker form
(``link``) exists so the prior also appears per linker in the output.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from radius_linking.domain import (
    LINKER_CHANGE_PRIOR,
    CriterionInput,
    Link,
    LinkContext,
    Reason,
    SymbolDoc,
)
from radius_linking.infrastructure.linkers.common import reason

VERSION = "change-prior-v1"

DEFAULT_PRIORS: Mapping[str, float] = {
    "added": 1.0,
    "modified_body": 0.95,
    "modified_signature": 0.95,
    "removed": 0.8,
    "renamed": 0.7,
    "decorator_or_annotation_changed": 0.8,
    "moved": 0.5,
    "moved_between_files": 0.5,
    "docstring_or_comment_only": 0.25,
    "formatting_only": 0.1,
}
NON_BEHAVIORAL_PRIOR = 0.2
UNKNOWN_BEHAVIORAL_PRIOR = 0.8


class ChangePriorLinker:
    name = LINKER_CHANGE_PRIOR
    version = VERSION

    def __init__(self, priors: Mapping[str, float] | None = None) -> None:
        self.priors = dict(DEFAULT_PRIORS if priors is None else priors)

    def prior(self, sym: SymbolDoc) -> tuple[float, Reason]:
        """Prior in [0, 1] and its explanation. Non-behavioural kinds are capped at 0.25."""

        value = self.priors.get(
            sym.change_kind,
            UNKNOWN_BEHAVIORAL_PRIOR if sym.is_behavioral else NON_BEHAVIORAL_PRIOR,
        )
        if not sym.is_behavioral:
            value = min(value, 0.25)
        value = min(1.0, max(0.0, value))
        text = "behavioural" if sym.is_behavioral else "non-behavioural"
        return value, reason(
            self.name, "change_kind", f"{sym.change_kind} ({text})", value
        )

    def link(
        self,
        criteria: Sequence[CriterionInput],
        symbols: Sequence[SymbolDoc],
        context: LinkContext,
    ) -> list[Link]:
        out: list[Link] = []
        for crit in criteria:
            for sym in symbols:
                value, why = self.prior(sym)
                if value > 0:
                    out.append(
                        Link(crit.criterion_id, sym.symbol_id, self.name, value, (why,))
                    )
        return out
