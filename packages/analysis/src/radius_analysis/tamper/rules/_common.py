"""Helpers shared by several rules (test pairing and assertion alignment)."""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterator
from dataclasses import dataclass

from radius_analysis.symbol_changes.model import ChangeKind
from radius_analysis.tamper.classify import Role
from radius_analysis.tamper.context import FileView, TamperContext
from radius_analysis.tamper.pyast import Assertion, TestFn, TestModule

COMMENT_PREFIX = re.compile(r"^\s*#")


def test_id(path: str, qualname: str) -> str:
    return f"{path}::{qualname.replace('.', '::')}"


@dataclass(slots=True)
class PairedTest:
    __test__ = False
    view: FileView
    qualname: str
    base: TestFn | None
    head: TestFn | None


def rename_map(ctx: TamperContext, path: str) -> dict[str, str]:
    """``new qualified name -> old qualified name`` for renamed symbols of one file."""
    out: dict[str, str] = {}
    for s in ctx.changeset.symbols:
        if s.path == path and s.change_kind is ChangeKind.RENAMED and s.old_qualified_name:
            out[s.qualified_name] = s.old_qualified_name
    return out


def test_views(ctx: TamperContext) -> list[FileView]:
    return [v for v in ctx.views(Role.TEST, python_only=True)]


def pairs(ctx: TamperContext, view: FileView) -> Iterator[PairedTest]:
    """Base/head test functions of one test file, matched by qualified name (and renames)."""
    base_mod: TestModule | None = ctx.tests_of(view, "base")
    head_mod: TestModule | None = ctx.tests_of(view, "head")
    base_tests = base_mod.tests if base_mod else {}
    head_tests = head_mod.tests if head_mod else {}
    renames = rename_map(ctx, view.path)
    matched_base: set[str] = set()
    for qual in sorted(head_tests):
        old = qual if qual in base_tests else renames.get(qual)
        b = base_tests.get(old) if old else None
        if b is not None and old is not None:
            matched_base.add(old)
        yield PairedTest(view, qual, b, head_tests[qual])
    for qual in sorted(base_tests):
        if qual not in matched_base:
            yield PairedTest(view, qual, base_tests[qual], None)


def align(
    base: tuple[Assertion, ...], head: tuple[Assertion, ...]
) -> list[tuple[Assertion | None, Assertion | None]]:
    """Align assertion lists; replaced blocks are paired in order."""
    sm = difflib.SequenceMatcher(None, [a.key for a in base], [a.key for a in head], autojunk=False)
    out: list[tuple[Assertion | None, Assertion | None]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.extend((base[i1 + k], head[j1 + k]) for k in range(i2 - i1))
        elif tag == "replace":
            n = min(i2 - i1, j2 - j1)
            out.extend((base[i1 + k], head[j1 + k]) for k in range(n))
            out.extend((base[i], None) for i in range(i1 + n, i2))
            out.extend((None, head[j]) for j in range(j1 + n, j2))
        elif tag == "delete":
            out.extend((base[i], None) for i in range(i1, i2))
        else:
            out.extend((None, head[j]) for j in range(j1, j2))
    return out


def enclosing_test(module: TestModule | None, line: int) -> TestFn | None:
    if module is None:
        return None
    for fn in module.tests.values():
        if fn.start <= line <= fn.end:
            return fn
    return None
