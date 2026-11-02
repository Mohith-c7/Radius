"""IN-02: closing-keyword parser, table-driven."""

from __future__ import annotations

import time

import pytest
from radius_github.intent_links import (
    MAX_LINKED_ISSUES,
    IssueRef,
    collect_linked_issues,
    parse_closing_references,
    strip_ignored_regions,
)

OWN, REPO = "acme", "widgets"


def refs(text: str) -> list[tuple[str, str, int]]:
    return [
        (ref.owner, ref.repo, ref.number)
        for ref in parse_closing_references(text, default_owner=OWN, default_repo=REPO)
    ]


def local(*numbers: int) -> list[tuple[str, str, int]]:
    return [(OWN, REPO, n) for n in numbers]


FENCE = "```"

CASES: list[tuple[str, str, list[tuple[str, str, int]]]] = [
    # --- keywords, all nine forms, any case ---------------------------------
    ("fixes", "Fixes #1", local(1)),
    ("fix", "fix #2", local(2)),
    ("fixed", "Fixed #3", local(3)),
    ("closes", "closes #4", local(4)),
    ("close", "CLOSE #5", local(5)),
    ("closed", "Closed #6", local(6)),
    ("resolves", "RESOLVES #7", local(7)),
    ("resolve", "resolve #8", local(8)),
    ("resolved", "Resolved #9", local(9)),
    ("mixed case", "fIxEs #10", local(10)),
    # --- colon variants --------------------------------------------------------
    ("colon", "Fixes: #11", local(11)),
    ("colon no space before", "Closes:   #12", local(12)),
    ("colon directly attached", "Resolves:#13", local(13)),
    # --- reference forms ---------------------------------------------------------
    ("cross repo", "Fixes other/lib#14", [("other", "lib", 14)]),
    ("cross repo colon", "closes: Other-Org/some.repo_x#15", [("Other-Org", "some.repo_x", 15)]),
    (
        "issue url",
        "Resolves https://github.com/other/lib/issues/16",
        [("other", "lib", 16)],
    ),
    (
        "issue url www and http",
        "fixes http://www.github.com/other/lib/issues/17",
        [("other", "lib", 17)],
    ),
    ("issue url with colon", "Fixes: https://github.com/a/b/issues/18", [("a", "b", 18)]),
    ("same repo via owner/repo", "Fixes acme/widgets#19", local(19)),
    # --- punctuation and layout ---------------------------------------------------
    ("sentence end", "This fixes #20.", local(20)),
    ("comma after", "Closes #21, thanks", local(21)),
    ("in parens", "(fixes #22)", local(22)),
    ("in a list item", "- Resolves #23", local(23)),
    ("heading", "## Fixes #24", local(24)),
    ("after tab", "fixes\t#25", local(25)),
    ("crlf", "intro\r\nFixes #26\r\n", local(26)),
    ("bold", "**Fixes** #27", []),
    ("bold whole", "**Fixes #28**", local(28)),
    ("multiple lines", "Fixes #29\nCloses #30\nResolves other/x#31", local(29, 30) + [("other", "x", 31)]),
    ("same line twice", "fixes #32 and fixes #33", local(32, 33)),
    ("one keyword one ref", "Fixes #34, #35, #36", local(34)),
    ("repeated keyword list", "Fixes #37, fixes #38", local(37, 38)),
    # --- dedupe ----------------------------------------------------------------
    ("dedupe plain", "Fixes #40\nCloses #40", local(40)),
    ("dedupe case", "Fixes Other/Lib#41\nfixes other/lib#41", [("Other", "Lib", 41)]),
    ("dedupe local forms", "Fixes #42\nFixes acme/widgets#42\nfixes ACME/WIDGETS#42", local(42)),
    # --- not links -----------------------------------------------------------
    ("no keyword", "See #50 for context", []),
    ("keyword inside word", "prefixes #51", []),
    ("keyword suffix", "fixesx #52", []),
    ("hyphenated", "bug-fix #53", []),
    ("keyword then word", "fixes the bug #54", []),
    ("bare number", "fixes 55", []),
    ("number then letters", "fixes #56abc", []),
    ("zero", "fixes #0", []),
    ("huge number", "fixes #99999999999", []),
    ("no space", "fixes#57", []),
    ("pull url", "Fixes https://github.com/a/b/pull/58", []),
    ("other host", "Fixes https://gitlab.com/a/b/issues/59", []),
    ("url without keyword", "see https://github.com/a/b/issues/60", []),
    ("empty", "", []),
    # --- ignored regions: code, comments, quotes --------------------------------
    ("backtick fence", f"{FENCE}\nfixes #61\n{FENCE}\n", []),
    ("fence with language", f"{FENCE}python\nCloses #62\n{FENCE}\nFixes #63", local(63)),
    ("tilde fence", "~~~\nfixes #64\n~~~\nfixes #65", local(65)),
    ("long fence closes only on long fence", "````\n```\nfixes #66\n```\n````\nfixes #67", local(67)),
    ("unterminated fence", f"Fixes #68\n{FENCE}\nfixes #69\n", local(68)),
    ("indented fence", f"  {FENCE}\n  fixes #70\n  {FENCE}\nfixes #71", local(71)),
    ("inline code", "run `fixes #72` later, fixes #73", local(73)),
    ("double backtick span", "``fixes #74`` and fixes #75", local(75)),
    ("html comment", "<!-- fixes #76 -->\nFixes #77", local(77)),
    ("multiline html comment", "<!--\nfixes #78\n-->\nfixes #79", local(79)),
    ("unterminated html comment", "fixes #80\n<!-- fixes #81", local(80)),
    ("blockquote", "> Fixes #82\nFixes #83", local(83)),
    ("nested blockquote", ">> closes #84\ncloses #85", local(85)),
    ("indented blockquote", "  > fixes #86", []),
    ("code element", "<code>fixes #87</code> fixes #88", local(88)),
    ("pre element", "<pre>\nfixes #89\n</pre>\nfixes #90", local(90)),
    ("fence info with backtick is not a fence", "```a`b\nfixes #91\n", local(91)),
    # --- order and mixture ------------------------------------------------------
    (
        "order of appearance",
        "Closes other/b#2\nFixes #1\nResolves https://github.com/c/d/issues/3",
        [("other", "b", 2), (OWN, REPO, 1), ("c", "d", 3)],
    ),
    (
        "realistic pr body",
        "## Summary\nAdds greet().\n\n<!-- template: link issues -->\nFixes #12\n\n"
        f"{FENCE}\nCloses #999\n{FENCE}\n\n> Resolves #998\n",
        local(12),
    ),
]


@pytest.mark.parametrize(("name", "text", "expected"), CASES, ids=[c[0] for c in CASES])
def test_closing_keyword_table(name: str, text: str, expected: list[tuple[str, str, int]]) -> None:
    assert refs(text) == expected, name


def test_table_has_at_least_forty_cases() -> None:
    assert len(CASES) >= 40


def test_collect_dedupes_across_texts_and_caps() -> None:
    body = "\n".join(f"Fixes #{n}" for n in range(1, 8))
    commit = "\n".join(f"closes #{n}" for n in range(5, 16))
    issues, dropped = collect_linked_issues(
        [body, commit], default_owner=OWN, default_repo=REPO
    )
    assert [i.number for i in issues] == list(range(1, 11))
    assert len(issues) == MAX_LINKED_ISSUES
    assert dropped == 5  # 11..15


def test_collect_with_custom_limit_and_no_drop() -> None:
    issues, dropped = collect_linked_issues(
        ["fixes #1", "fixes #1", "fixes #2"], default_owner=OWN, default_repo=REPO, limit=5
    )
    assert [i.number for i in issues] == [1, 2]
    assert dropped == 0


def test_issue_ref_label_and_key() -> None:
    ref = IssueRef("Acme", "Widgets", 4)
    assert ref.label() == "Acme/Widgets#4"
    assert ref.key == ("acme", "widgets", 4)


def test_none_like_text_is_safe() -> None:
    assert parse_closing_references(None, default_owner=OWN, default_repo=REPO) == []  # type: ignore[arg-type]


def test_blanking_preserves_line_structure() -> None:
    text = f"a\n{FENCE}\nfixes #1\n{FENCE}\nb `x` c <!-- z -->"
    out = strip_ignored_regions(text)
    assert out.count("\n") == text.count("\n")
    assert len(out) == len(text)


@pytest.mark.parametrize(
    "hostile",
    [
        "`" * 60_000,
        "`a" * 30_000,
        "<!--" * 20_000,
        "<code " * 10_000,
        "fixes " * 20_000,
        "fixes " + " " * 60_000 + "#1",
        "~~~\n" * 15_000,
        "> " * 30_000,
    ],
)
def test_hostile_inputs_finish_quickly(hostile: str) -> None:
    started = time.perf_counter()
    parse_closing_references(hostile, default_owner=OWN, default_repo=REPO)
    assert time.perf_counter() - started < 3.0


def test_name_length_is_bounded() -> None:
    long_owner = "a" * 200
    assert refs(f"fixes {long_owner}/repo#1") == []
