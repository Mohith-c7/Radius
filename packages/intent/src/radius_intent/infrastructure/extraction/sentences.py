"""Precision-first modal-sentence rules for prose outside criteria lists.

A sentence becomes a criterion only when it states an obligation about the
system in the third person (or "we/it") and carries no hedge. English only;
other languages yield no sentence criteria (documented limitation).
"""

from __future__ import annotations

import re

_BOUNDARY = re.compile(r"[.!?]+[\"')\]]*\s+(?=[A-Z0-9\"'(\[`*_])")
_TOKEN = re.compile(r"[a-z0-9']+")

STRONG_MODALS = frozenset({"must", "shall"})
_PHRASE_MODALS = (" needs to ", " need to ", " has to ", " have to ", " required to ")
HEDGES = frozenset(
    {"maybe", "perhaps", "probably", "might", "possibly", "ideally", "could", "tbd"}
)
_HEDGE_PHRASES = ("not sure", "i think", "i guess", "i suppose", "if possible")
_FIRST_PERSON = frozenset({"i", "i'm", "i've", "i'd", "i'll"})
_READER_START = ("you must", "you should", "you need", "please ", "make sure you")
_SO_THAT_VERBS = frozenset(
    {
        "can",
        "cannot",
        "can't",
        "will",
        "won't",
        "able",
        "allow",
        "allows",
        "enable",
        "enables",
        "ensure",
        "ensures",
        "never",
        "does",
        "doesn't",
    }
)
_USER_STORY_WANTS = (" i want ", " i need ", " i would like ", " i can ", " i'd like ")


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` offsets of sentences in ``text`` (linear)."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for match in _BOUNDARY.finditer(text):
        spans.append((pos, match.start() + len(match.group().rstrip())))
        pos = match.end()
    spans.append((pos, len(text)))
    return spans


def classify_sentence(sentence: str, max_chars: int) -> tuple[str | None, str | None]:
    """Return ``(rule, None)`` if the sentence is a criterion, else ``(None, reason)``.

    ``reason`` is a stable code for diagnostics (``None`` when the sentence is
    simply not a candidate, which is not worth reporting).
    """
    text = " ".join(sentence.split())
    if len(text) > max_chars:
        return None, "sentence_too_long"
    lower = text.lower()
    if lower.endswith("?"):
        return None, None
    tokens = _TOKEN.findall(lower)
    if len(tokens) < 4:
        return None, None
    padded = f" {' '.join(tokens)} "

    story = lower.startswith(("as a ", "as an ")) and any(
        w in f" {lower} " for w in _USER_STORY_WANTS
    )
    if story:
        return "user_story", None

    rule = _modal_rule(lower, tokens, padded)
    if rule is None:
        return None, None
    if tokens[0] in _FIRST_PERSON:
        return None, "first_person_narration"
    if any(t in HEDGES for t in tokens) or any(p in padded for p in _HEDGE_PHRASES):
        return None, "hedged"
    if lower.startswith(_READER_START):
        return None, "reader_directive"
    return rule, None


def _modal_rule(lower: str, tokens: list[str], padded: str) -> str | None:
    if lower.startswith(("when ", "if ")) and " then " in padded[3:]:
        return "when_then"
    if any(t in STRONG_MODALS for t in tokens) or any(
        p in padded for p in _PHRASE_MODALS
    ):
        return "modal"
    if "should" in tokens:
        idx = tokens.index("should")
        if tokens[0] in {"we", "you"} or (
            idx > 0 and tokens[idx - 1] in {"we", "you", "i"}
        ):
            return None
        return "modal"
    if (
        " so that " in padded
        and tokens[0] not in {"we"}
        and any(t in _SO_THAT_VERBS for t in tokens)
    ):
        return "so_that"
    return None
