"""Escaping of untrusted text for the verdict v2 renderer (risk R5)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from radius_github.verdict_v2 import escape

ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "docs" / "research" / "design").is_dir()
)
CORPUS = ROOT / "tests" / "security" / "prompt_injection" / "corpus" / "corpus_v1.jsonl"

#: Characters that must never survive (zero-width, bidi, controls, BOM).
INVISIBLE = re.compile(
    "[\u0000-\u0008\u000b-\u001f\u007f-\u009f­​-‏ -‮⁠-⁩﻿]"
)


def corpus_payloads() -> list[str]:
    values = {
        "{{NONCE}}": "N0nce1234567890",
        "{{NONCE_LOWER}}": "n0nce1234567890",
        "{{FAKE_SECRET}}": "fake" + "-" + "secret" + "-1",
        "{{FAKE_SECRET2}}": "fake" + "-" + "secret" + "-2",
    }
    out = []
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if "payload" not in row:
            continue
        text = row["payload"]
        for key, value in values.items():
            text = text.replace(key, value)
        out.append(text)
    return out


PAYLOADS = corpus_payloads()


def strip_code(text: str) -> str:
    return re.sub(r"`[^`]*`", "", text)


def test_corpus_is_loaded() -> None:
    assert len(PAYLOADS) >= 90


# ------------------------------------------------------------------------ clean


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain text", "plain text"),
        ("  padded   spaces  ", "padded spaces"),
        ("line1\nline2\r\nline3\tx", "line1 line2 line3 x"),
        ("zero​width‍join", "zerowidthjoin"),
        ("bidi‮evil‬", "bidievil"),
        ("bom﻿here", "bomhere"),
        ("soft­hyphen", "softhyphen"),
        ("nul\x00ctl\x1b[31mred", "nulctl[31mred"),
        ("hangulㅤfiller", "hangulfiller"),
        ("sep para end", "sep para end"),
        ("", ""),
    ],
)
def test_clean_strips_and_flattens(raw: str, expected: str) -> None:
    assert escape.clean(raw) == expected


@pytest.mark.parametrize("value", [None, 5, 1.5, b"x", ["a"], {"a": 1}])
def test_clean_non_strings_are_empty(value: object) -> None:
    assert escape.clean(value) == ""


def test_clean_caps_length_with_marker() -> None:
    out = escape.clean("x" * 500, 50)
    assert len(out) == 50
    assert out.endswith("...")
    assert escape.clean("x" * 50, 50) == "x" * 50


# ------------------------------------------------------------------------- code


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("simple", "`simple`"),
        ("has `tick` inside", "`has 'tick' inside`"),
        ("a | b", "`a \\| b`"),
        ("", "`(empty)`"),
        ("​", "`(empty)`"),
        ("multi\nline", "`multi line`"),
    ],
)
def test_code(raw: str, expected: str) -> None:
    assert escape.code(raw) == expected


def test_code_never_contains_inner_backticks_or_newlines() -> None:
    for text in PAYLOADS:
        out = escape.code(text)
        assert out.startswith("`") and out.endswith("`")
        assert "`" not in out[1:-1]
        assert "\n" not in out
        assert len(out) <= escape.DEFAULT_MAX_LEN + 12


# ------------------------------------------------------------------------ plain


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("hello world", "hello world"),
        ("ping @everyone now", "ping `@everyone` now"),
        ("cc @org/team and @user", "cc `@org/team` and `@user`"),
        ("see #123 and GH-45", "see `#123` and `GH-45`"),
        ("fixes owner/repo#9", "fixes `owner/repo#9`"),
        ("[click](http://evil.example/x)", "\\[click\\](`http://evil.example/x)`"),
        ("![img](https://evil.example/i.png)", "\\!\\[img\\](`https://evil.example/i.png)`"),
        ("mail me@example.com", "mail `me@example.com`"),
        ("visit www.evil.example", "visit `www.evil.example`"),
        ("<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"),
        ("**bold** _em_ ~~del~~", "\\*\\*bold\\*\\* \\_em\\_ \\~\\~del\\~\\~"),
        ("snake_case_name stays", "snake_case_name stays"),
        ("a | b", "a \\| b"),
        ("back\\slash", "back\\\\slash"),
        ("a & b", "a &amp; b"),
        ("tick ` here", "tick \\` here"),
    ],
)
def test_plain(raw: str, expected: str) -> None:
    assert escape.plain(raw) == expected


def test_plain_mention_spam_is_fully_neutralised() -> None:
    spam = " ".join(f"@user{n}" for n in range(60))
    out = escape.plain(spam, max_len=2000)
    assert not re.search(r"(?<!`)@\w", strip_code(out))


# ----------------------------------------------------------------------- corpus


@pytest.mark.parametrize("which", [escape.code, escape.plain])
def test_corpus_output_is_inert(which) -> None:  # noqa: ANN001
    for text in PAYLOADS:
        out = which(text, 400)
        assert "\n" not in out and "\r" not in out
        assert not INVISIBLE.search(out)
        bare = strip_code(out)
        assert "<" not in bare.replace("\\<", "")
        assert ">" not in bare.replace("\\>", "")
        assert not re.search(r"(?<![\\`])@\w", bare)
        assert "](" not in bare.replace("\\](", "")
        assert "![" not in bare.replace("\\![", "")
        assert "://" not in bare


# ------------------------------------------------------------------ token / url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("verdict-v2-alpha-1", "verdict-v2-alpha-1"),
        ("T012", "T012"),
        ("a b<c>", "a?b?c?"),
        ("", "unknown"),
        (None, "unknown"),
        ("@evil", "?evil"),
        ("http://evil.example/x", "http:??evil?example?x"),
        ("www.evil.example", "www?evil?example"),
    ],
)
def test_token(raw: object, expected: str) -> None:
    assert escape.token(raw) == expected


def test_token_fallback_and_cap() -> None:
    assert escape.token("", fallback="") == ""
    assert len(escape.token("a" * 200, 10)) == 10


@pytest.mark.parametrize(
    ("raw", "ok"),
    [
        ("https://dashboard.example/analyses/5b0b9c6e", True),
        ("http://localhost:3000/a?b=c#d", True),
        ("javascript:alert(1)", False),
        ("data:text/html;base64,AAAA", False),
        ("https://x.example/a b", False),
        ("https://x.example/a)b", False),
        ("https://x.example/a(b", False),
        ("https://x.example/<s>", False),
        ("https://x.example/`", False),
        ("ftp://x.example", False),
        ("//x.example", False),
        ("", False),
        (None, False),
        ("https://x.example/" + "a" * 400, False),
    ],
)
def test_safe_url(raw: object, ok: bool) -> None:
    assert (escape.safe_url(raw) is not None) is ok


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3", "4f2a9d1"),
        ("abcdef1", "abcdef1"),
        ("XYZ", "unknown"),
        ("4F2A9D1", "unknown"),
        (None, "unknown"),
        ("abc", "unknown"),
    ],
)
def test_short_sha(raw: object, expected: str) -> None:
    assert escape.short_sha(raw) == expected
