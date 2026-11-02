"""Gherkin scenario extraction (fenced or plain text). One criterion per scenario."""

from __future__ import annotations

from dataclasses import dataclass, field

from .candidates import Candidate
from .text import Line, collapse

SCENARIO_KEYWORDS = ("Scenario Outline:", "Scenario Template:", "Scenario:")
CONTEXT_KEYWORDS = ("Feature:", "Background:", "Rule:")
STEP_KEYWORDS = ("Given ", "When ", "Then ", "And ", "But ", "* ")
_OPENING_STEPS = ("Given ", "When ", "Then ")
GHERKIN_FENCE_LANGS = frozenset({"gherkin", "feature", "cucumber"})


def starts_gherkin(stripped: str) -> bool:
    """Return whether a stripped line begins a Gherkin construct."""
    return stripped.startswith(SCENARIO_KEYWORDS + CONTEXT_KEYWORDS)


def is_step(stripped: str) -> bool:
    """Return whether a stripped line is a Gherkin step."""
    return stripped.startswith(STEP_KEYWORDS)


@dataclass
class _Scenario:
    title: str
    start: int
    end: int
    steps: list[str] = field(default_factory=list)
    has_then: bool = False
    in_examples: bool = False


def _finish(scn: _Scenario | None, out: list[Candidate], section: str | None) -> None:
    if scn is None or not scn.steps:
        return
    if len(scn.steps) < 2 and not scn.has_then:
        return
    head = f"Scenario: {scn.title}" if scn.title else "Scenario"
    out.append(
        Candidate(
            scn.start, scn.end, f"{head}: {'; '.join(scn.steps)}", "gherkin", section
        )
    )


def extract_gherkin(
    lines: list[Line], *, plain: bool, section: str | None = None
) -> list[Candidate]:
    """Extract scenarios from ``lines``.

    In ``plain`` mode (prose) a blank or non-step line ends the scenario; in
    fenced mode blank lines, tables, tags and comments are tolerated. Steps
    under ``Background:`` are ignored. ``Examples:`` tables are not part of
    the criterion text.
    """
    out: list[Candidate] = []
    current: _Scenario | None = None
    in_background = False
    for line in lines:
        stripped = line.text.strip()
        offset = line.start + (len(line.text) - len(line.text.lstrip()))
        end = offset + len(stripped)
        if not stripped:
            if plain:
                _finish(current, out, section)
                current = None
            continue
        if stripped.startswith(SCENARIO_KEYWORDS):
            _finish(current, out, section)
            in_background = False
            title = collapse(stripped.split(":", 1)[1])
            current = _Scenario(title, offset, end)
        elif stripped.startswith(CONTEXT_KEYWORDS):
            _finish(current, out, section)
            current = None
            in_background = stripped.startswith("Background:")
        elif is_step(stripped):
            if in_background:
                continue
            if current is None:
                if not stripped.startswith(_OPENING_STEPS):
                    continue
                current = _Scenario("", offset, end)
            if current.in_examples:
                continue
            current.steps.append(collapse(stripped))
            current.has_then = current.has_then or stripped.startswith("Then ")
            current.end = end
        elif stripped.startswith(("Examples:", "Scenarios:")):
            if current is not None:
                current.in_examples = True
        elif stripped.startswith(("|", '"""', "@", "#")) or not plain:
            continue
        else:
            _finish(current, out, section)
            current = None
    _finish(current, out, section)
    return out
