"""Word lists for the testability rules: loaded from a data file, schema-checked."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

#: Schema marker the data file must carry.
WORDLIST_SCHEMA = "testability-wordlists-v1"

#: Every list the rules read. A data file must define all of them.
REQUIRED_LISTS: tuple[str, ...] = (
    "modal_verbs",
    "observable_verbs",
    "error_words",
    "comparators",
    "negations",
    "condition_words",
    "result_words",
    "structural_verbs",
    "structural_nouns",
    "non_functional_terms",
    "measure_tools",
    "quantity_units",
    "vague_adjectives",
    "weasel_words",
    "placeholders",
    "external_judgment",
    "live_system_terms",
    "file_extensions",
    "non_english_markers",
)

MAX_ENTRIES_PER_LIST = 2000
MAX_ENTRY_CHARS = 64
_ENTRY = re.compile(r"[^\s\x00-\x1f]+(?: [^\s\x00-\x1f]+)*")


class WordListError(ValueError):
    """The word-list data file violates the schema."""


@dataclass(frozen=True)
class WordLists:
    """Validated, immutable word lists keyed by list name."""

    lists: dict[str, tuple[str, ...]]

    def get(self, name: str) -> tuple[str, ...]:
        """Return one list (always present after validation)."""
        return self.lists[name]


def validate_wordlists(data: Any) -> WordLists:
    """Check ``data`` against the schema and return normalized lists.

    Entries are lowercased, de-duplicated and sorted so that the loaded
    lists do not depend on file order. Raises :class:`WordListError`.
    """
    if not isinstance(data, dict):
        raise WordListError("Word-list file must be a JSON object.")
    if data.get("schema") != WORDLIST_SCHEMA:
        msg = f"Word-list file must declare schema {WORDLIST_SCHEMA!r}."
        raise WordListError(msg)
    raw = data.get("lists")
    if not isinstance(raw, dict):
        raise WordListError("'lists' must be an object.")
    unknown = sorted(set(raw) - set(REQUIRED_LISTS))
    if unknown:
        raise WordListError(f"Unknown lists: {', '.join(unknown)}.")
    missing = [name for name in REQUIRED_LISTS if name not in raw]
    if missing:
        raise WordListError(f"Missing lists: {', '.join(missing)}.")
    out: dict[str, tuple[str, ...]] = {}
    for name in REQUIRED_LISTS:
        entries = raw[name]
        if not isinstance(entries, list) or not entries:
            raise WordListError(f"List {name!r} must be a non-empty array.")
        if len(entries) > MAX_ENTRIES_PER_LIST:
            raise WordListError(f"List {name!r} has too many entries.")
        cleaned: set[str] = set()
        for entry in entries:
            if not isinstance(entry, str):
                raise WordListError(f"List {name!r} entries must be strings.")
            word = entry.strip().casefold()
            if not word or len(word) > MAX_ENTRY_CHARS:
                raise WordListError(f"List {name!r} has an empty or long entry.")
            if _ENTRY.fullmatch(word) is None:
                raise WordListError(f"List {name!r} has a malformed entry.")
            cleaned.add(word)
        out[name] = tuple(sorted(cleaned))
    return WordLists(out)


def load_wordlists(path: str | Path | None = None) -> WordLists:
    """Load word lists from ``path``, or the packaged default file."""
    try:
        if path is None:
            text = (
                resources.files("radius_intent.infrastructure.testability")
                .joinpath("wordlists.json")
                .read_text(encoding="utf-8")
            )
        else:
            text = Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WordListError(f"Cannot read word lists: {exc}") from exc
    return validate_wordlists(data)
