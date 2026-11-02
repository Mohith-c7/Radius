"""Opt-in ``summary`` extraction mode: ordinary PR text as PROPOSED criteria.

``sections`` (the default) reads only acceptance-style sections. ``summary`` adds,
for PR titles and PR bodies only, a conservative reading of what authors usually
write: a conventional-commit title and bullets under Summary / Changes / What /
Why / Description headings. Everything it finds is author-written text, so it is
a low-weight PROPOSED criterion; the downstream provenance rules still cap it
(``author_pr_body``). A bullet is kept only if it reads as behaviour (a leading
verb such as "adds" or "rejects", a modal such as "must", or a marker such as
"now" or "no longer"); boilerplate, links-only lines, headings, over-long lines,
duplicates and everything beyond the cap are skipped with a diagnostic.

Linear, regex-light, no LLM, no clock, no network.
"""

from __future__ import annotations

import re

from .candidates import Candidate, Collector
from .config import ExtractionConfig
from .markdown import PLACEHOLDERS, clean_heading, is_boilerplate
from .report import DiagnosticKind, Severity
from .text import Line, collapse

#: Extractor version stamped on criteria produced by this mode.
SUMMARY_EXTRACTOR_VERSION = "det-extract-summary-v1"
#: Low extraction confidence, expressed as the criterion weight.
SUMMARY_WEIGHT = 0.5

RULE_TITLE = "summary_title"
RULE_LEAD_VERB = "summary_lead_verb"
RULE_MODAL = "summary_modal"
RULE_MARKER = "summary_marker"
RULE_TESTPLAN_REQUIREMENT = "summary_testplan_requirement"

_TITLE = re.compile(
    r"^(?:feat|fix|perf|revert|security)(?:\([^)]{1,60}\))?!?:\s+(?P<subject>\S.*)$",
    re.IGNORECASE,
)
_ITEM = re.compile(r"^(?P<indent> {0,3})(?:[-*+]|\d{1,3}[.)])[ \t]+(?P<text>\S.*)$")
_CHECKBOX = re.compile(r"^\[[ xX]\][ \t]+")
_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(?P<title>.*?)[ \t#]*$")
_FENCE = re.compile(r"^ {0,3}(?:```|~~~)")
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_EMPHASIS = re.compile(r"\*\*|__")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*")

SUMMARY_HEADINGS = frozenset(
    {
        "summary",
        "changes",
        "changes made",
        "what",
        "what changed",
        "what changes",
        "what this does",
        "what s changed",
        "whats changed",
        "what does this pr do",
        "why",
        "description",
        "overview",
        "motivation",
        "summary of changes",
        "key changes",
    }
)
#: Evidence-not-intent: kept out unless the item is phrased as a requirement.
TESTPLAN_HEADINGS = frozenset(
    {
        "test plan",
        "testing",
        "tests",
        "test",
        "how tested",
        "how has this been tested",
        "how to test",
        "verification",
        "validation",
    }
)

_MODALS = ("must", "should", "shall", "needs to", "need to", "has to", "have to")
_MARKERS = (
    "now",
    "no longer",
    "never",
    "instead of",
    "only when",
    "only if",
    "otherwise",
    "by default",
    "always",
    # finite third-person verbs that are rarely nouns, valid anywhere in the sentence
    "adds",
    "accepts",
    "allows",
    "blocks",
    "denies",
    "drops",
    "emits",
    "enforces",
    "ensures",
    "fails",
    "fixes",
    "prevents",
    "raises",
    "rejects",
    "removes",
    "requires",
    "returns",
    "skips",
    "throws",
)
_VERBS = frozenset(
    """accept add allow apply avoid block break change clamp compute create deny derive detect disable drop emit enable enforce ensure
    escape expose extract fail fix guard handle ignore implement
    include introduce keep limit make move normalise normalize parse
    permit prevent propagate raise redact reject remove rename replace
    require resolve restrict retry return revoke sanitise
    sanitize send skip split store support throw truncate update use validate verify warn wrap write""".split()
)


def _stems(word: str) -> tuple[str, ...]:
    """Candidate verb stems of an inflected word (adds, added, adding)."""
    out = [word]
    if word.endswith("ies") and len(word) > 4:
        out.append(word[:-3] + "y")
    if word.endswith("es"):
        out.append(word[:-2])
    if word.endswith("s"):
        out.append(word[:-1])
    if word.endswith("ed"):
        out += [word[:-2], word[:-1]]
        if len(word) > 4 and word[-3] == word[-4]:
            out.append(word[:-3])
    if word.endswith("ing") and len(word) > 5:
        out += [word[:-3], word[:-3] + "e"]
        if word[-4] == word[-5]:
            out.append(word[:-4])
    return tuple(out)


def _is_verb(word: str) -> bool:
    return any(s in _VERBS for s in _stems(word.lower()))


def _has_phrase(lower: str, phrases: tuple[str, ...]) -> bool:
    padded = f" {' '.join(_WORD.findall(lower))} "
    return any(f" {p} " in padded for p in phrases)


def behaviour_rule(text: str) -> str | None:
    """Return the name of the phrasing rule that makes ``text`` behavioural, or None."""
    words = _WORD.findall(text)
    if not words:
        return None
    lower = text.lower()
    if _has_phrase(lower, _MODALS):
        return RULE_MODAL
    if _is_verb(words[0]):
        return RULE_LEAD_VERB
    if _has_phrase(lower, _MARKERS):
        return RULE_MARKER
    return None


def _clean_item(raw: str) -> str:
    text = _LINK.sub(lambda m: m.group(1), raw)
    text = _EMPHASIS.sub("", text)
    return collapse(text)


def _skip_reason(text: str, cfg: ExtractionConfig) -> str | None:
    lower = text.lower()
    if "generated with" in lower or "co-authored-by" in lower:
        return "boilerplate_attribution"
    if lower.strip("_*. ") in PLACEHOLDERS:
        return "placeholder"
    if len(_WORD.findall(_URL.sub("", text))) < 3:
        return "links_or_too_few_words"
    if len(text) > cfg.summary_max_chars:
        return "too_long"
    if is_boilerplate(text):
        return "boilerplate"
    return None


def extract_summary(
    lines: list[Line], is_title: bool, cfg: ExtractionConfig, collector: Collector
) -> None:
    """Add summary-mode candidates for one PR title or PR body to ``collector``."""
    if is_title:
        _title(lines, cfg, collector)
    else:
        _body(lines, cfg, collector)


def _add(
    collector: Collector,
    seen: set[str],
    start: int,
    end: int,
    text: str,
    rule: str,
    section: str | None,
    checked: bool | None,
    depth: int,
) -> bool:
    key = " ".join(_WORD.findall(text.lower()))
    if key in seen:
        collector.skip("summary_duplicate", "Duplicate of an earlier summary item.")
        return False
    seen.add(key)
    collector.add(
        Candidate(
            start,
            end,
            text,
            rule,
            section,
            checked,
            depth,
            weight=SUMMARY_WEIGHT,
            extractor_version=SUMMARY_EXTRACTOR_VERSION,
        )
    )
    return True


def _title(lines: list[Line], cfg: ExtractionConfig, collector: Collector) -> None:
    for line in lines:
        m = _TITLE.match(line.text.strip())
        if m is None:
            continue
        subject = _clean_item(m["subject"])
        reason = _skip_reason(subject, cfg)
        if reason is not None:
            collector.skip(
                f"summary_skip_{reason}", "Title not used.", line=line.number
            )
            return
        start = line.start + line.text.find(m["subject"])
        _add(
            collector,
            set(),
            start,
            start + len(m["subject"]),
            subject,
            RULE_TITLE,
            "title",
            None,
            0,
        )
        return


def _body(lines: list[Line], cfg: ExtractionConfig, collector: Collector) -> None:
    seen: set[str] = set()
    kept = 0
    kind = "neutral"  # "summary" | "testplan" | "neutral"
    section: str | None = None
    fenced = False
    capped = False
    for line in lines:
        text = line.text
        if _FENCE.match(text):
            fenced = not fenced
            continue
        if fenced:
            continue
        h = _HEADING.match(text)
        if h is not None:
            section = clean_heading(h["title"])
            if section in SUMMARY_HEADINGS:
                kind = "summary"
            elif section in TESTPLAN_HEADINGS:
                kind = "testplan"
            else:
                kind = "neutral"
            continue
        if kind == "neutral":
            continue
        m = _ITEM.match(text)
        if m is None:
            continue
        raw = m["text"]
        checked: bool | None = None
        box = _CHECKBOX.match(raw)
        if box is not None:
            checked = raw[1] in "xX"
            raw = raw[box.end() :]
        item = _clean_item(raw)
        reason = _skip_reason(item, cfg)
        rule = None if reason else behaviour_rule(item)
        if reason is None and rule is None:
            reason = "not_behavioural"
        if reason is None and kind == "testplan":
            if _has_phrase(item.lower(), _MODALS):
                rule = RULE_TESTPLAN_REQUIREMENT
            else:
                reason = "testplan_not_requirement"
        if reason is not None or rule is None:
            collector.skip(
                f"summary_skip_{reason}",
                "Item not used in summary mode.",
                line=line.number,
            )
            continue
        if kept >= cfg.summary_max_criteria:
            if not capped:
                capped = True
                collector.note(
                    DiagnosticKind.LIMIT,
                    "summary_max_criteria",
                    f"Summary mode stopped after {cfg.summary_max_criteria} criteria.",
                    severity=Severity.WARNING,
                    line=line.number,
                )
            continue
        start = line.start + text.find(m["text"])
        if _add(
            collector,
            seen,
            start,
            line.end,
            item,
            rule,
            section,
            checked,
            len(m["indent"]) // 2,
        ):
            kept += 1
