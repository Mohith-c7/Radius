"""Deterministic criterion -> symbol linkers."""

from radius_linking.infrastructure.linkers.change_prior import ChangePriorLinker
from radius_linking.infrastructure.linkers.explicit import ExplicitLinker, match_hints
from radius_linking.infrastructure.linkers.identifier import (
    Anchor,
    IdentifierLinker,
    extract_anchors,
)
from radius_linking.infrastructure.linkers.lexical import LexicalConfig, LexicalLinker
from radius_linking.infrastructure.linkers.structural import (
    StructuralConfig,
    StructuralLinker,
)


def default_linkers() -> (
    list[ExplicitLinker | LexicalLinker | IdentifierLinker | StructuralLinker]
):
    """The four evidence linkers, in a fixed order."""

    return [ExplicitLinker(), LexicalLinker(), IdentifierLinker(), StructuralLinker()]


__all__ = [
    "Anchor",
    "ChangePriorLinker",
    "ExplicitLinker",
    "IdentifierLinker",
    "LexicalConfig",
    "LexicalLinker",
    "StructuralConfig",
    "StructuralLinker",
    "default_linkers",
    "extract_anchors",
    "match_hints",
]
