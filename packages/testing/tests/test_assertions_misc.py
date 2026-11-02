"""LK-04: resolver port, TS/JS (partial), robustness, determinism, performance, sanity runs."""

from __future__ import annotations

import importlib.util
import json
import random
import sys
import time
from pathlib import Path

import pytest
from radius_testing.assertions import (
    AssertionKind,
    AssertionRecord,
    LinkTargetResolver,
    assertion_extraction_enabled,
    discover_test_files,
    extract_assertions,
    log_counts,
)
from radius_testing.assertions.model import Expected, Location, StrengthFeatures
from radius_testing.linking.model import LinkKind, LinkSet, LinkTarget, SymbolTestLink

ROOT = Path(__file__).resolve().parents[3]
PRE = "from pkg.mod import f, g\n\n"


# --------------------------------------------------------------------------- resolver port and links


def _target(name: str = "f", path: str = "src/pkg/mod.py", sid: str = "sym:f") -> LinkTarget:
    return LinkTarget(symbol_id=sid, path=path, qualified_name=name)


def _link(sid: str, test_id: str) -> SymbolTestLink:
    return SymbolTestLink(sid, test_id, "static", 0.9, LinkKind.DIRECT_CALL)


SRC = PRE + "def test_a():\n    assert f(1) == 2\n"
TID = "tests/test_a.py::test_a"


def _run(resolver=None, links=None):  # noqa: ANN001, ANN202
    return extract_assertions(["tests/test_a.py"], {"tests/test_a.py": SRC}, links, resolver=resolver)


def test_without_resolver_dependence_is_unknown_and_refs_unresolved() -> None:
    (rec,) = _run().assertions
    assert rec.strength_features.depends_on_changed == "unknown"
    assert rec.subject_refs[0].symbol_ids == ()
    assert rec.subject_refs[0].qualified == "pkg.mod.f"


def test_resolver_without_links_resolves_ids_but_dependence_unknown() -> None:
    (rec,) = _run(LinkTargetResolver([_target()])).assertions
    assert rec.subject_refs[0].symbol_ids == ("sym:f",)
    assert rec.strength_features.depends_on_changed == "unknown"


def test_links_with_matching_symbol_gives_yes() -> None:
    (rec,) = _run(LinkTargetResolver([_target()]), [_link("sym:f", TID)]).assertions
    assert rec.strength_features.depends_on_changed == "yes"


def test_links_accepts_a_linkset() -> None:
    ls = LinkSet.of([_link("sym:f", TID)], algo_version="x")
    (rec,) = _run(LinkTargetResolver([_target()]), ls).assertions
    assert rec.strength_features.depends_on_changed == "yes"


def test_links_for_other_symbol_gives_no() -> None:
    res = LinkTargetResolver([_target(), _target("g", sid="sym:g")])
    (rec,) = _run(res, [_link("sym:g", TID)]).assertions
    assert rec.strength_features.depends_on_changed == "no"


def test_links_but_unresolvable_ref_gives_unknown() -> None:
    (rec,) = _run(LinkTargetResolver([]), [_link("sym:f", TID)]).assertions
    assert rec.strength_features.depends_on_changed == "unknown"


def test_links_without_resolver_gives_unknown() -> None:
    (rec,) = _run(None, [_link("sym:f", TID)]).assertions
    assert rec.strength_features.depends_on_changed == "unknown"


def test_custom_resolver_and_failing_resolver() -> None:
    class Custom:
        def resolve(self, test_id: str, name: str, qualified: str | None, path: str) -> tuple[str, ...]:
            return ("custom:" + name,)

    class Broken:
        def resolve(self, *a: object) -> tuple[str, ...]:
            raise RuntimeError("boom")

    (rec,) = _run(Custom()).assertions
    assert rec.subject_refs[0].symbol_ids == ("custom:f",)
    (rec,) = _run(Broken()).assertions
    assert rec.subject_refs[0].symbol_ids == ()


def test_link_target_resolver_matches_method_and_suffix() -> None:
    r = LinkTargetResolver([_target("Calc.add", sid="sym:add")])
    assert r.resolve("t", "c.add", "pkg.mod.Calc.add", "tests/x.py") == ("sym:add",)
    assert r.resolve("t", "c.add", "mod.Calc.add", "tests/x.py") == ("sym:add",)
    assert r.resolve("t", "c.add", "other.Calc.add", "tests/x.py") == ()
    assert r.resolve("t", "x", None, "tests/x.py") == ()


def test_snapshot_adapter_with_read_method() -> None:
    class Snap:
        def read(self, path: str) -> bytes | None:
            return SRC.encode() if path == "tests/test_a.py" else None

    res = extract_assertions(["tests/test_a.py", "tests/missing.py"], Snap())
    assert len(res.assertions) == 1
    assert any("not found" in n for n in res.notes)


def test_snapshot_adapter_that_raises_is_treated_as_missing() -> None:
    class Bad:
        def read(self, path: str) -> bytes:
            raise OSError("nope")

    res = extract_assertions(["tests/test_a.py"], Bad())
    assert res.assertions == () and res.notes


# --------------------------------------------------------------------------- robustness


@pytest.mark.parametrize(
    ("path", "source", "note"),
    [
        ("tests/test_bad.py", "def test_x(:\n    pass\n", "unparseable"),
        ("tests/test_nul.py", "def test_x():\n    assert 1\x00\n", "unparseable"),
        ("tests/test_deep.py", "x = " + "(" * 1000 + "1" + ")" * 1000 + "\ndef test_a():\n    assert x\n", None),
        ("tests/test_huge.py", "# " + "x" * 1_100_000, "larger than"),
        ("tests/test_empty.py", "", "empty"),
        ("notes.txt", "hello", "unsupported"),
    ],
)
def test_bad_inputs_never_raise(path: str, source: str, note: str | None) -> None:
    res = extract_assertions([path], {path: source})
    if note:
        assert any(note in n for n in res.notes), res.notes
    json.loads(res.to_json())


def test_missing_file_and_backslash_paths() -> None:
    res = extract_assertions(["tests\\test_a.py", "tests/none.py"], {"tests/test_a.py": SRC})
    assert len(res.assertions) == 1
    assert res.assertions[0].test_id == TID


def test_bytes_source_and_replacement_chars() -> None:
    res = extract_assertions(["tests/test_a.py"], {"tests/test_a.py": SRC.encode() + b"\n# \xff\xfe\n"})
    assert len(res.assertions) == 1


def test_file_truncation_note_for_too_many_files() -> None:
    paths = [f"tests/test_{i}.py" for i in range(5001)]
    res = extract_assertions(paths, {})
    assert any("truncated" in n for n in res.notes)


def test_record_cap_per_test() -> None:
    body = "".join("    assert f(1) == 1\n" for _ in range(3)) + "".join(f"    assert f({i}) == {i}\n" for i in range(600))
    res = extract_assertions(["tests/test_a.py"], {"tests/test_a.py": PRE + "def test_a():\n" + body})
    assert len(res.assertions) <= 500
    assert any("truncated" in n for n in res.notes)


def test_confidence_validation() -> None:
    with pytest.raises(ValueError, match="confidence"):
        AssertionRecord("t", AssertionKind.EQUALITY, "", (), Expected(), "==", StrengthFeatures(), Location("p", 1, 1), "pytest", 1.5)


# --------------------------------------------------------------------------- determinism / serialization


def _bigger_sources() -> dict[str, str]:
    one = PRE + (
        "import pytest\n"
        "@pytest.mark.parametrize('a', [0, 1])\n"
        "def test_a(a):\n    assert f(a) == 1\n    with pytest.raises(ValueError):\n        g(a)\n\n"
        "class TestX:\n    def test_b(self):\n        assert f(1) in (1, 2)\n"
    )
    return {"tests/test_one.py": one, "tests/test_two.py": one.replace("test_a", "test_c")}


def test_deterministic_regardless_of_input_order() -> None:
    files = _bigger_sources()
    a = extract_assertions(sorted(files), files).to_json()
    b = extract_assertions(sorted(files, reverse=True), files).to_json()
    c = extract_assertions(sorted(files) * 2, files).to_json()
    assert a == b == c


def test_ids_are_unique_stable_and_roundtrip_json() -> None:
    files = _bigger_sources()
    res = extract_assertions(sorted(files), files)
    ids = [a.assertion_id for a in res.assertions]
    assert len(ids) == len(set(ids)) and all(i.startswith("as_") for i in ids)
    data = json.loads(res.to_json())
    assert [a["assertion_id"] for a in data["assertions"]] == ids
    assert data["algo_version"] == "assertion-extract-v1"
    assert data["counts"]["assertions"] == len(ids)
    first = data["assertions"][0]
    assert {"test_id", "kind", "subject", "expected", "comparator", "strength_features", "location", "framework", "confidence"} <= set(first)
    assert {"text", "refs"} == set(first["subject"])


def test_id_depends_on_location() -> None:
    a = extract_assertions(["tests/test_a.py"], {"tests/test_a.py": SRC}).assertions[0]
    b = extract_assertions(["tests/test_a.py"], {"tests/test_a.py": "\n" + SRC}).assertions[0]
    assert a.assertion_id != b.assertion_id


def test_feature_flag_helper_and_log_counts() -> None:
    assert assertion_extraction_enabled({}) is False
    assert assertion_extraction_enabled({"RADIUS_FEATURE_ASSERTION_EXTRACTION": "true"}) is True
    assert assertion_extraction_enabled({"RADIUS_FEATURE_ASSERTION_EXTRACTION": "0"}) is False
    counts = log_counts(_run())
    assert counts["assertions"] == 1 and counts["algo_version"] == "assertion-extract-v1"


def test_discover_test_files(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "tests" / "test_a.py").write_text("x", encoding="utf-8")
    (tmp_path / "tests" / "b.test.ts").write_text("x", encoding="utf-8")
    (tmp_path / "tests" / "helper.py").write_text("x", encoding="utf-8")
    (tmp_path / "node_modules" / "x" / "test_z.py").write_text("x", encoding="utf-8")
    assert discover_test_files(tmp_path) == ["tests/b.test.ts", "tests/test_a.py"]
    assert discover_test_files(tmp_path, limit=1) == ["tests/b.test.ts"]


# --------------------------------------------------------------------------- performance


def test_performance_on_five_thousand_line_test_file() -> None:
    chunk = (
        "@pytest.mark.parametrize('a', [0, 1, 2])\n"
        "def test_{i}(a):\n"
        "    r = f(a)\n"
        "    assert r == {i}\n"
        "    assert isinstance(r, int) and len(str(r)) > 0\n"
        "    with pytest.raises(ValueError, match='x'):\n"
        "        g(None)\n"
        "    m = mock.Mock()\n"
        "    m()\n"
        "    m.assert_called_once()\n"
        "    for k in range(2):\n"
        "        assert f(k) >= 0\n"
        "\n"
    )
    src = PRE.replace("from pkg", "import pytest\nfrom unittest import mock\nfrom pkg") + "".join(chunk.format(i=i) for i in range(400))
    assert src.count("\n") >= 5000
    start = time.perf_counter()
    res = extract_assertions(["tests/test_big.py"], {"tests/test_big.py": src})
    elapsed = time.perf_counter() - start
    assert len(res.tests) == 400
    assert len(res.assertions) == 400 * 6
    assert elapsed < 10, f"5k-line file took {elapsed:.2f}s"


# --------------------------------------------------------------------------- property-style fuzzing


_STMTS = [
    "assert f({a}) == {b}",
    "assert not f({a})",
    "assert f({a}) in [{a}, {b}]",
    "assert all(x > {a} for x in g({b}))",
    "assert isinstance(f({a}), int) and len(g({b})) == {a}",
    "assert f({a}) == pytest.approx({b}, rel=0.1)",
    "with pytest.raises(ValueError):\n    f({a})",
    "m = mock.Mock()\nm({a})\nm.assert_called_with({a})",
    "for i in range({a}):\n    assert f(i)",
    "try:\n    assert f({a})\nexcept AssertionError:\n    pass",
    "assert True",
    "x = f({a})\nassert x == x",
    "self_check({a})",
    "if f({a}):\n    assert g({b}) is None",
    "assert (yield)",
    "assert f(*args, **kw)",
    "assert [i for i in f({a})] == [{b}]",
    "assert f({a}) if g({b}) else None",
    "assert lambda: {a}",
    "async_thing = (await f({a}))",
]


def _random_module(rng: random.Random) -> str:
    out = ["import pytest", "from unittest import mock", "from pkg.mod import f, g", "def self_check(x):", "    assert x", ""]
    for i in range(rng.randint(1, 6)):
        if rng.random() < 0.3:
            out.append(f"@pytest.mark.parametrize('a', [{rng.choice(['0', '1', 'None', '[]', '-1', 'X'])}, 2])")
        out.append(f"def test_{i}(a=1):")
        for _ in range(rng.randint(0, 6)):
            stmt = rng.choice(_STMTS).format(a=rng.randint(-1, 5), b=rng.randint(0, 9))
            out.extend("    " + line for line in stmt.splitlines())
        out.append("    pass")
        out.append("")
    return "\n".join(out)


def test_random_generated_test_bodies_never_crash() -> None:
    rng = random.Random(1234)
    parsed = 0
    for _ in range(300):
        src = _random_module(rng)
        res = extract_assertions(["tests/test_r.py"], {"tests/test_r.py": src})
        if not any("unparseable" in n for n in res.notes):
            parsed += 1
        again = extract_assertions(["tests/test_r.py"], {"tests/test_r.py": src})
        assert res.to_json() == again.to_json()
    assert parsed > 200  # most generated modules are valid, the rest must only be reported


def test_truncated_real_files_never_crash() -> None:
    rng = random.Random(7)
    text = (ROOT / "packages/testing/tests/test_assertions_python.py").read_text(encoding="utf-8")
    for _ in range(40):
        cut = rng.randint(0, len(text))
        extract_assertions(["tests/test_cut.py"], {"tests/test_cut.py": text[:cut]})


# --------------------------------------------------------------------------- TS/JS (partial)

needs_ts = pytest.mark.skipif(importlib.util.find_spec("tree_sitter_typescript") is None, reason="TS grammar not installed")

JS_SRC = """
import { add, Calc } from '../src/calc';
import * as util from '../src/util';

describe('calc', () => {
  it('adds', () => {
    expect(add(1, 2)).toBe(3);
    expect(add(1, 2)).not.toEqual(4);
    expect(add(0, 0)).toBeTruthy();
    expect(add(1, 2)).toBeGreaterThan(0);
    expect(add(0.1, 0.2)).toBeCloseTo(0.3, 5);
    expect(util.fmt(1)).toContain('1');
    expect([1,2]).toHaveLength(2);
    expect(add(1, 2)).toBeNull();
    expect('abc').toMatch(/a/);
    expect(add(1, 2)).toBeInstanceOf(Number);
  });
  it('throws', () => {
    expect(() => add(null)).toThrow(TypeError);
    expect(() => add(null)).toThrow('bad');
    expect(() => add(null)).toThrow();
  });
  it('mocks', () => {
    const fn = jest.fn();
    fn(1);
    expect(fn).toHaveBeenCalled();
    expect(fn).toHaveBeenCalledWith(1);
    const spy = jest.spyOn(util, 'fmt');
    add(1, 2);
    expect(spy).toHaveBeenCalledTimes(0);
  });
  it('snapshots', () => {
    expect(add(1, 2)).toMatchSnapshot();
  });
  it('dead', () => {
    expect(true).toBe(true);
  });
  it('circular', () => {
    expect(add(1, 2)).toBe(add(1, 2));
  });
  it('loops', () => {
    for (const x of [1, 2]) {
      expect(add(x, 1)).toBe(x + 1);
    }
    [1, 2].forEach((x) => expect(add(x, 1)).toBeTruthy());
  });
  it('swallowed', () => {
    try {
      expect(add(1, 2)).toBe(3);
    } catch (e) {
      console.log(e);
    }
  });
  it('rethrown', () => {
    try {
      expect(add(1, 2)).toBe(3);
    } catch (e) {
      throw e;
    }
  });
  it('no assertions', () => {
    add(1, 2);
  });
  it('rejects', async () => {
    await expect(add(1)).rejects.toThrow(RangeError);
  });
  it.each([[0, 1], [2, 3]])('each %i', (a, b) => {
    expect(add(a, b)).toBe(b);
  });
  test.each([[5, 6]])('each no edge %i', (a, b) => {
    expect(add(a, b)).toBe(b);
  });
});
"""


def _js(path: str = "tests/calc.test.ts", src: str = JS_SRC, extra: dict[str, str] | None = None):  # noqa: ANN202
    files = {path: src, "src/calc.ts": "export function add(a,b){return a+b}", "src/util.ts": "export const fmt = (x) => x", **(extra or {})}
    return extract_assertions([path], files)


def _by(res, title: str):  # noqa: ANN001, ANN202
    return [a for a in res.assertions if a.test_id.endswith("::" + title)]


@needs_ts
def test_ts_matchers_and_notes() -> None:
    res = _js()
    assert any("partial" in n for n in res.notes)
    adds = _by(res, "adds")
    kinds = [(a.kind.value, a.comparator) for a in sorted(adds, key=lambda a: a.location.line)]
    assert kinds == [
        ("equality", "toBe"),
        ("equality", "toEqual"),
        ("truthiness", "toBeTruthy"),
        ("comparison", "toBeGreaterThan"),
        ("approx", "toBeCloseTo"),
        ("membership", "toContain"),
        ("length", "toHaveLength"),
        ("none_check", "toBeNull"),
        ("regex", "toMatch"),
        ("type_check", "toBeInstanceOf"),
    ]
    first, second = sorted(adds, key=lambda a: a.location.line)[:2]
    assert first.strength_features.negated is False and second.strength_features.negated is True
    assert first.expected.text == "3" and first.expected.complexity == 2
    assert first.strength_features.exactness == "exact"
    assert all(a.confidence <= 0.7 for a in res.assertions)
    approx = next(a for a in adds if a.kind is AssertionKind.APPROX)
    assert approx.strength_features.tolerance_abs == pytest.approx(5e-6)


@needs_ts
def test_ts_refs_qualified_by_import() -> None:
    res = _js()
    (first, *_rest) = sorted(_by(res, "adds"), key=lambda a: a.location.line)
    assert [r.qualified for r in first.subject_refs] == ["src/calc.ts#add"]
    contain = next(a for a in _by(res, "adds") if a.comparator == "toContain")
    assert [r.qualified for r in contain.subject_refs] == ["src/util.ts#fmt"]


@needs_ts
def test_ts_resolver_and_links() -> None:
    resolver = LinkTargetResolver([LinkTarget("sym:add", "src/calc.ts", "add", language="typescript")])
    files = {"tests/calc.test.ts": JS_SRC, "src/calc.ts": "x", "src/util.ts": "y"}
    tid = "tests/calc.test.ts::calc::adds"
    res = extract_assertions(["tests/calc.test.ts"], files, [_link("sym:add", tid)], resolver=resolver)
    first = sorted(_by(res, "adds"), key=lambda a: a.location.line)[0]
    assert first.subject_refs[0].symbol_ids == ("sym:add",)
    assert first.strength_features.depends_on_changed == "yes"


@needs_ts
def test_ts_exceptions() -> None:
    specs = [(a.strength_features.exception_specificity.value, a.strength_features.exception_match) for a in sorted(_by(_js(), "throws"), key=lambda a: a.location.line)]
    assert specs == [("specific", False), ("specific_match", True), ("broad", False)]
    (rej,) = _by(_js(), "rejects")
    assert rej.kind is AssertionKind.EXCEPTION and rej.strength_features.exception_specificity == "specific"


@needs_ts
def test_ts_mock_snapshot_dead_circular_loop_swallow() -> None:
    res = _js()
    calls = sorted(_by(res, "mocks"), key=lambda a: a.location.line)
    assert [(a.exactness if hasattr(a, "exactness") else a.strength_features.exactness.value) for a in calls] == ["call_only", "call_args", "call_only"]
    assert calls[0].strength_features.mock_only is True and calls[0].strength_features.mock_origin == "created"
    assert calls[2].strength_features.mock_only is False and calls[2].strength_features.mock_origin == "patched"
    (snap,) = _by(res, "snapshots")
    assert snap.kind is AssertionKind.SNAPSHOT and snap.strength_features.snapshot_library == "jest"
    (dead,) = _by(res, "dead")
    assert dead.strength_features.dead is True
    (circ,) = _by(res, "circular")
    assert circ.strength_features.circular is True
    assert all(a.strength_features.in_loop for a in _by(res, "loops"))
    assert _by(res, "swallowed")[0].strength_features.swallowed is True
    assert _by(res, "rethrown")[0].strength_features.swallowed is False


@needs_ts
def test_ts_no_assertions_and_each() -> None:
    res = _js()
    assert "tests/calc.test.ts::calc::no assertions" in res.tests_without_assertions
    (a,) = _by(res, "each %i")
    assert a.strength_features.in_parametrized is True and a.strength_features.edge_inputs is True
    assert a.strength_features.edge_input_source == "parametrize"
    (b,) = _by(res, "each no edge %i")
    assert b.strength_features.edge_inputs is False


@needs_ts
def test_node_assert_and_plain_assert() -> None:
    src = """
const assert = require('assert');
import { add } from './calc';
it('node', () => {
  assert.strictEqual(add(1, 2), 3);
  assert.notStrictEqual(add(1, 2), 4);
  assert.ok(add(1, 2));
  assert(add(1, 2));
  assert.throws(() => add(null), TypeError);
  assert.ok(true);
});
"""
    res = _js("tests/node.test.ts", src, {"tests/calc.ts": "x"})
    recs = sorted(res.assertions, key=lambda a: a.location.line)
    assert [r.kind.value for r in recs] == ["equality", "equality", "truthiness", "truthiness", "exception", "truthiness"]
    assert recs[1].strength_features.negated is True
    assert recs[-1].strength_features.dead is True
    assert all(r.framework == "node-assert" for r in recs)


@needs_ts
def test_ts_unparseable_and_non_test_blocks_are_safe() -> None:
    res = _js("tests/bad.test.ts", "it('x', () => { expect(", None)
    assert isinstance(res.assertions, tuple)
    res = _js("tests/weird.test.ts", "foo(); describe(); it(); expect(1).toBe(1);")
    assert res.assertions == ()
    res = _js("tests/unknown.test.ts", "it('x', () => { expect(a).toCustomMatcher(1); foo.bar.toBe(1); expect(a).weird.toBe(1); });")
    assert res.assertions == ()


@needs_ts
def test_ts_oversized_file_skipped() -> None:
    res = extract_assertions(["tests/big.test.ts"], {"tests/big.test.ts": "x" * 1_100_000})
    assert any("larger than" in n for n in res.notes)


def test_js_file_when_grammar_available() -> None:
    pytest.importorskip("tree_sitter_javascript", reason="JS grammar not installed")
    res = extract_assertions(
        ["tests/a.test.js"], {"tests/a.test.js": "test('x', () => { expect(1 + 1).toBe(2); });", "src/x.js": ""}
    )
    assert len(res.assertions) == 1 and res.tests[0].language == "javascript"


# --------------------------------------------------------------------------- CLI and sanity runs


def _load_cli():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("assertion_dump", ROOT / "scripts" / "assertion_dump.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("assertion_dump", mod)
    spec.loader.exec_module(mod)
    return mod


def test_cli_prints_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(SRC, encoding="utf-8")
    (tmp_path / "tests" / "conftest.py").write_text("def h(x):\n    assert x\n", encoding="utf-8")
    cli = _load_cli()
    assert cli.main(["--root", str(tmp_path), "tests"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["counts"]["assertions"] == 1
    assert cli.main(["--root", str(tmp_path), "--summary", "tests/test_a.py"]) == 0
    assert set(json.loads(capsys.readouterr().out)) == {"counts", "notes"}
    assert cli.main(["--root", str(tmp_path), "--test-id", TID, "tests"]) == 0
    assert len(json.loads(capsys.readouterr().out)["assertions"]) == 1


def _tree(rel: str) -> dict[str, str]:
    base = ROOT / rel
    files = {}
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        files[p.relative_to(ROOT).as_posix()] = p.read_text(encoding="utf-8", errors="replace")
    return files


def test_sanity_on_f14_fixture_tests() -> None:
    """Fixture sanity (not a research result): every F-14 fixture's tests yield assertions."""

    fixtures = sorted(p for p in (ROOT / "benchmarks/fixtures/intent").iterdir() if p.is_dir())
    assert fixtures
    totals = {"tests": 0, "assertions": 0, "no_assert": 0}
    for fx in fixtures:
        files = {p.relative_to(fx).as_posix(): p.read_text(encoding="utf-8", errors="replace") for p in fx.rglob("*.py") if "__pycache__" not in p.parts}
        test_files = [p for p in files if p.rsplit("/", 1)[-1].startswith("test_") or p.endswith("_test.py")]
        if not test_files:
            continue
        res = extract_assertions(test_files, files)
        assert not any("unparseable" in n for n in res.notes), (fx.name, res.notes)
        totals["tests"] += len(res.tests)
        totals["assertions"] += len(res.assertions)
        totals["no_assert"] += len(res.tests_without_assertions)
    assert totals["tests"] > 0 and totals["assertions"] > 0


def test_sanity_on_this_repos_own_tests() -> None:
    files = _tree("packages/testing/tests")
    test_files = [p for p in files if p.rsplit("/", 1)[-1].startswith("test_")]
    start = time.perf_counter()
    res = extract_assertions(test_files, files)
    assert time.perf_counter() - start < 60
    assert len(res.tests) > 100 and len(res.assertions) > 500
    assert not any("unparseable" in n for n in res.notes)
    assert res.assertions == extract_assertions(test_files, files).assertions
