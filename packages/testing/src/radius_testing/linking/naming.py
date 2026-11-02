"""Naming/convention symbol-to-test linker (LK-03, part 2).

Needs no call graph, so it still produces candidates when static linking finds
nothing (dynamic imports, decorators that hide calls, heavy mocking).

Priors (``naming-link-v1``; a link is capped at ``NAMING_CAP`` because a name is
only a convention):

====================================================  =====
``test_<function>`` in the matching test file          0.60
``Test<Class>.test_<method>`` in the matching file     0.60
``test_<function>`` / ``Test<Class>`` elsewhere        0.30-0.40
any test in the mirror-path test file                  0.25
any test in a same-basename test file                  0.15
====================================================  =====

Tie-breaking: when one test name matches several changed symbols (``test_apply_
discount_negative`` matches both ``apply_discount`` and ``apply``) only the
longest matching name is kept; equal names are ranked by file-match strength.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from posixpath import basename, dirname

from radius_testing.linking.ecmascript import discover_js_tests
from radius_testing.linking.model import (
    NAMING_ALGO_VERSION,
    LinkKind,
    LinkSet,
    LinkTarget,
    SymbolTestLink,
    is_test_path,
    make_test_id,
)
from radius_testing.linking.pyindex import ProjectIndex

NAMING_CAP = 0.60
_SRC_ROOTS = frozenset({"src", "lib", "app", "source", "python"})
_TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec", "specs"})
_MIN_NAME_LEN_FOR_LOOSE = 5

FILE_MIRROR = 2
FILE_BASENAME = 1
FILE_NONE = 0


@dataclass(frozen=True, slots=True)
class TestRecord:
    test_id: str
    path: str
    class_name: str | None
    name: str


def _stem(path: str) -> str:
    base = basename(path)
    if base in ("__init__.py", "index.ts", "index.js", "index.tsx", "index.jsx"):
        return basename(dirname(path)) or base
    return re.sub(r"\.(?:py|[cm]?[jt]sx?)$", "", base)


def _strip_roots(parts: list[str]) -> list[str]:
    while parts and (parts[0] in _SRC_ROOTS or parts[0] in _TEST_DIRS):
        parts = parts[1:]
    return [p for p in parts if p not in _TEST_DIRS]


def file_match(target_path: str, test_path: str) -> int:
    """How strongly the test file's name/location says it tests the target file."""

    stem = _stem(target_path)
    tbase = basename(test_path)
    names = {
        f"test_{stem}.py", f"{stem}_test.py",
        *(f"{stem}.{kind}.{ext}" for kind in ("test", "spec") for ext in ("ts", "tsx", "js", "jsx", "mjs", "cjs")),
    }  # fmt: skip
    if tbase not in names:
        prefixed = tbase.startswith(f"test_{stem}_") or tbase.startswith(f"{stem}.")
        return FILE_BASENAME if prefixed and is_test_path(test_path) and len(stem) >= 3 else FILE_NONE
    t_dirs = _strip_roots(dirname(target_path).split("/")) if dirname(target_path) else []
    s_dirs = _strip_roots(dirname(test_path).split("/")) if dirname(test_path) else []
    if t_dirs == s_dirs or (t_dirs[-len(s_dirs) :] == s_dirs if s_dirs else True):
        return FILE_MIRROR
    return FILE_BASENAME


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _name_match(test_name: str, symbol: str) -> bool:
    """``test_<symbol>`` or ``test_<symbol>_suffix`` (snake) / camel variants."""

    low = test_name.lower()
    sym = symbol.lower().lstrip("_")
    if not sym:
        return False
    if low == f"test_{sym}" or low.startswith(f"test_{sym}_"):
        return True
    return _norm(test_name) == "test" + _norm(sym)  # unittest camelCase: testApplyDiscount


def python_test_records(sources: Mapping[str, str]) -> list[TestRecord]:
    index = ProjectIndex({p: s for p, s in sources.items() if p.endswith(".py")})
    return [TestRecord(i.test_id, i.path, i.class_qual, i.name) for i in index.discover_tests()]


class NamingLinker:
    """Conventional-name matching between changed symbols and tests."""

    algo_version = NAMING_ALGO_VERSION

    def link(
        self,
        sources: Mapping[str, str],
        targets: Sequence[LinkTarget],
        *,
        tests: Sequence[TestRecord] | None = None,
    ) -> LinkSet:
        if tests is None:
            records = python_test_records(sources)
            for js in discover_js_tests(sources):
                parts = js.test_id.split("::")
                records.append(TestRecord(js.test_id, js.path, parts[-2] if len(parts) > 2 else None, js.name))
        else:
            records = list(tests)
        candidates: dict[str, list[tuple[float, LinkTarget, str]]] = {}
        for tgt in sorted(targets, key=lambda t: t.symbol_id):
            if tgt.qualified_name == "<module>" or tgt.kind == "module":
                self._module_level(tgt, records, candidates)
                continue
            for rec in records:
                match = self._match(tgt, rec)
                if match is not None:
                    candidates.setdefault(rec.test_id, []).append((match[0], tgt, match[1]))
        links: list[SymbolTestLink] = []
        for test_id, found in sorted(candidates.items()):
            named = [c for c in found if c[2].startswith("name:")]
            keep = []
            for score, tgt, why in found:
                if why.startswith("name:") and any(
                    o[1] is not tgt and o[1].simple_name != tgt.simple_name
                    and o[1].simple_name.startswith(tgt.simple_name) and o[2].startswith("name:")
                    for o in named
                ):
                    continue  # a longer symbol name also matches this test name
                keep.append((score, tgt, why))
            for score, tgt, why in keep:
                links.append(
                    SymbolTestLink(
                        symbol_id=tgt.symbol_id,
                        test_id=test_id,
                        linker="naming",
                        score=min(score, NAMING_CAP),
                        kind=LinkKind.NAME_CONVENTION,
                        evidence=(why.split(":", 1)[1].strip(),),
                        algo_version=self.algo_version,
                    )
                )
        return LinkSet.of(links, algo_version=self.algo_version, config={"cap": NAMING_CAP})

    @staticmethod
    def _module_level(tgt: LinkTarget, records: Sequence[TestRecord], out: dict) -> None:
        for rec in records:
            fm = file_match(tgt.path, rec.path)
            if fm:
                score = 0.25 if fm == FILE_MIRROR else 0.15
                out.setdefault(rec.test_id, []).append(
                    (score, tgt, f"file: {rec.path} follows the naming convention for {tgt.path}")
                )

    @staticmethod
    def _match(tgt: LinkTarget, rec: TestRecord) -> tuple[float, str] | None:
        fm = file_match(tgt.path, rec.path)
        cls = tgt.class_name
        simple = tgt.simple_name
        loose_ok = len(simple) >= _MIN_NAME_LEN_FOR_LOOSE
        if cls is not None:  # method target `Class.method`
            in_test_class = rec.class_name is not None and _norm(rec.class_name) in (
                _norm("Test" + cls), _norm(cls + "Test"), _norm("Test" + cls + "s"), _norm("Tests" + cls)
            )  # fmt: skip
            if in_test_class and _name_match(rec.name, simple):
                return (0.60 if fm else 0.40, f"name: {rec.test_id} matches Test{cls}.test_{simple} convention")
            if _name_match(rec.name, simple) and rec.class_name is None and fm:
                return 0.40, f"name: {rec.name} matches method {simple} in conventional file {rec.path}"
            if in_test_class:
                return (0.35 if fm else 0.30), f"name: class {rec.class_name} follows Test{cls} convention"
            if fm:
                return (0.25 if fm == FILE_MIRROR else 0.15), f"file: {rec.path} follows the naming convention for {tgt.path}"
            return None
        if tgt.kind == "class":
            if rec.class_name is not None and _norm(rec.class_name) in (_norm("Test" + simple), _norm(simple + "Test")):
                return (0.55 if fm else 0.40), f"name: class {rec.class_name} follows Test{simple} convention"
        elif _name_match(rec.name, simple):
            if fm:
                return 0.60, f"name: {rec.name} matches function {simple} in conventional file {rec.path}"
            if loose_ok:
                return 0.30, f"name: {rec.name} matches function {simple} (file name does not follow convention)"
            return 0.15, f"name: {rec.name} matches short function name {simple}"
        if fm:
            return (0.25 if fm == FILE_MIRROR else 0.15), f"file: {rec.path} follows the naming convention for {tgt.path}"
        return None


def make_record(path: str, class_name: str | None, name: str) -> TestRecord:
    return TestRecord(make_test_id(path, class_name, name), path, class_name, name)
