# Test assertion extraction (LK-04)

For each test function: which assertions it contains, what each one asserts about
which symbols, and raw **strength features** for EV-06. Static (AST / tree-sitter),
deterministic, no LLM, no network, nothing is executed. **This package computes no
`a_static` score**; EV-06 turns the features into one.

## Placement (DEC-003)

`radius_testing.assertions`, a sub-package of `packages/testing` next to
`radius_testing.linking` (LK-03), not a new package: DEC-003/DEC-007 list no
`assertions` package, it shares the test-file conventions (`is_test_path`, test id
format `path::Class::function`) with LK-03 and has no dependency the testing
package does not already have. It imports LK-03's `LinkTarget`/`SymbolTestLink`
types and the F-09 parser (`radius_parser`, TS/JS only).

## Entry point

```python
extract_assertions(test_files, repo_snapshot, links=None, *, resolver=None) -> AssertionSet
```

* `test_files`: repo-relative paths (`/`); order and duplicates do not matter.
* `repo_snapshot`: `{path: text}` or any object with `read(path) -> bytes | None`
  (LK-01's `DictSnapshot` / `DirectorySnapshot` / `GitSnapshot` qualify). Also used
  to find `conftest.py` helpers.
* `links`: LK-03 `SymbolTestLink`s or a `LinkSet`. With a `resolver` they turn
  `depends_on_changed` into `yes` / `no`; otherwise it stays `unknown`.
* `resolver`: the `SymbolResolver` port,
  `resolve(test_id, name, qualified, path) -> tuple[symbol_id, ...]`. LK-05 / EV-06
  plug in the real resolution; `LinkTargetResolver(targets)` is a ready adapter
  over LK-01/LK-03 `LinkTarget`s (matches the import-qualified name against the
  target's dotted module path + qualified name). A failing resolver is ignored.
* Never raises on bad input: unparseable / oversized / missing / unsupported files
  are reported in `AssertionSet.notes`.

Debugging: `python scripts/assertion_dump.py [--root DIR] [--summary] [--test-id ID] PATH...`.
Worker: flag `RADIUS_FEATURE_ASSERTION_EXTRACTION` (default off) logs the counts
("Test assertions extracted"); nothing is stored (LK-05), failures never fail an analysis.

## Model (`model.py`, `algo_version` = `assertion-extract-v1`)

`AssertionRecord(test_id, kind, subject, expected, comparator, strength_features,
location, framework, confidence, via, algo_version)`

* `assertion_id` = `as_` + sha256 prefix of test id, file, line, column, helper
  chain, kind, comparator, subject and expected text: deterministic, unique per
  call site (a helper called twice gives two records).
* `kind`: `equality`, `comparison`, `approx`, `membership`, `identity`,
  `none_check`, `truthiness`, `type_check`, `length`, `regex`, `quantified`
  (`all`/`any`), `disjunction`, `exception`, `warning`, `mock_call`, `snapshot`,
  `unknown_assert` (an `assert_*` helper that could not be followed).
* `subject`: expression text plus `SymbolRef(name, qualified, symbol_ids, role)`.
  Refs are import-qualified calls/attributes found in the subject, followed through
  local assignments (depth 3) and helper arguments; stdlib/builtins/pytest are not
  symbols; `obj = Cls(); obj.m()` becomes `pkg.Cls.m`.
* `expected`: text, `form` (`literal` / `expression` / `pattern` / `snapshot` /
  `exception_type`), literal kind and complexity (0 not a literal, 1 trivial
  `None/True/0/1/-1/""/[]`, 2 simple literal, 3 rich: >2 elements, nested, long
  string). A local name bound once to a literal counts as that literal.
* `comparator`: `==`, `!=`, `<`, `is`, `in`, `chain < <`, `raises`, `isclose`,
  `assert_called_with`, `toBe`, ...
* `framework`: `pytest`, `unittest`, `mock`, `hypothesis`, `snapshot`, `jest`,
  `node-assert`. `confidence`: 0.95 direct, minus 0.1 per helper hop, 0.4
  unresolved `assert_*`, at most 0.7 for TS/JS.
* `TestSummary` per test: assertion count, `has_assertions`, parametrize case
  count, property-based, `has_dynamic_assertions`. `AssertionSet.tests_without_assertions`
  lists tests with no assertion (the "no assertion" case).

## Strength features (inputs for EV-06)

| Feature | Meaning |
| --- | --- |
| `exactness` | `exact` (equality), `approx`, `membership`, `ordering`, `pattern`, `truthiness`, `none_only`, `type_only`, `length_only`, `identity`, `exception`, `call_only`, `call_args`, `snapshot`, `disjunction`, `none` (dead) |
| `value_specificity` | literal complexity of the expected value, 0..3 |
| `distinct_subject_symbols` | number of distinct symbol refs in the subject |
| `edge_inputs` / `edge_input_source` | `parametrize` values (or, without parametrize, literal call arguments) include `None`, `0`, `""`, empty container, negative number, `inf/nan`, `maxsize`-like names; `null` when unknown |
| `exception_specificity` | `broad` (`Exception`/`BaseException`), `specific`, `specific_match` (type and `match=`), `none` |
| `exception_match`, `exception_inspected`, `exception_block_size` | `match=`/regex variant; the `as` object asserted later; statements inside the `raises` block |
| `tolerance_rel`, `tolerance_abs` | `pytest.approx` (defaults 1e-6 / 1e-12), `isclose`, `assertAlmostEqual(places/delta)`, `toBeCloseTo` |
| `depends_on_changed` | `yes` / `no` / `unknown` from LK-03 links through the resolver |
| `circular` | expected is computed by the same project callee as the subject (`f(x) == f(x)`, `e = f(x); assert f(x) == e`) |
| `mock_only`, `mock_origin` | subject derives only from a `Mock()` created in the test and never leaves it (passed on, stored, aliased); `patched` mocks are not mock-only |
| `in_loop` | inside `for`/`while` (also inherited by helpers called there): assertion count per case unknown |
| `in_parametrized`, `property_based` | `parametrize`/`parameterized.expand`; hypothesis `@given` |
| `swallowed` | inside `try` whose handler catches `AssertionError`/`Exception`/bare and does not re-raise |
| `dead`, `dead_reason` | `assert True`, constants, non-empty tuple, `x or True`, `1 == 1`, `x == x`, `isinstance(x, object)` |
| `negated`, `quantifier`, `snapshot_library`, `helper_depth` | `not` / `!=`; `all`/`any`; syrupy, pytest-snapshot, approvaltests, pytest-regressions, jest; 0..2 |

## Python coverage

pytest `assert` (compare, chains, `in`, `is`, `isinstance`, `len(...)`, `all/any`,
`and` split into one record each, `or`, `not`, walrus), `pytest.raises` /
`warns` / `deprecated_call` (context and call form), `pytest.approx`,
`math.isclose`, numpy/pandas testing helpers, unittest `assert*` including
`assertRaises*`/`assertWarns*`/`assertAlmostEqual`, mock `assert_*` / `called` /
`call_count` / `call_args`, snapshot libraries, hypothesis, `parametrize`,
decorator/context/`mocker` patches.

Helpers: calls to module functions, nested functions, `self.method()` of the test
class (and in-module bases) and `conftest.py` functions (nearest first) are
followed to depth 2; their assertions are attributed to the calling test with
`via=("name@line",)`, `helper_depth`, and parameters bound to the call arguments.

Test discovery follows pytest/unittest: `test*` functions, `Test*` classes without
`__init__`, `TestCase` subclasses, nested classes, in-module inherited tests.

## TS/JS (PARTIAL)

Via the F-09 tree-sitter parser: jest/vitest `expect(x).matcher(...)` with `.not` /
`.resolves` / `.rejects`, `it.each` / `test.each`, `toBe/toEqual/toStrictEqual/
toBeTruthy/toBeNull/toThrow/toHaveBeenCalledWith/toMatchSnapshot/...`, a few chai
call matchers, node `assert.*`. `jest.fn()` / `spyOn` give mock origins. Not
modelled: custom matchers, chai property chains, helper following, `require`,
path aliases, types, data flow through reassignment. Refs are `path#member` from
relative imports. Confidence is at most 0.7 and the set carries a note.

## Limits (by design)

* Data flow is flow-insensitive and local (assignments inside the test, depth 3).
  Reassigned names expand to every assigned value (first four).
* `circular` and `mock_only` are heuristics; fixtures, `monkeypatch` and mocks
  created in fixtures are not tracked. `circular` only sees import-qualified
  callees, so `client.get(...)` style fixture calls are never circular.
* Helpers from other modules (`from tests.helpers import check`) are not followed;
  only the test module and `conftest.py`.
* Assertion count per case is unknown for loops, `parametrize` and `all/any`.
* Inline `try/except` swallow detection ignores handler logic beyond `raise`.
* Bounds: 1 MB per file, 5000 files, 500 records per test, 200 helper calls per test.

## Contract for EV-06 / LK-05

Consume `AssertionSet.assertions` (`AssertionRecord.strength_features`) and
`AssertionSet.tests`; key on `test_id` (same format as LK-03 `SymbolTestLink.test_id`,
function level, no parametrisation suffix). Dead, swallowed, `mock_only` and
`circular` records should carry no credit; `unknown_assert` means "unknown", not
zero. LK-05 persists `AssertionRecord.to_dict()` as `test_assertion` rows keyed
by `assertion_id` and re-resolves `subject_refs` with its own resolver.

## Follow-ups

Helpers from imported test-utility modules; fixture-return data flow; `monkeypatch`
and fixture-created mocks; chai property chains and custom jest matchers; Go/Java
test frameworks; learning the weights (EV-06 / EP-08).
