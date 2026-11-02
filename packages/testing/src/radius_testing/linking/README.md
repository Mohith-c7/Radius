# Symbol-to-test linking (LK-03)

Answers "which tests could detect a defect in this changed symbol?" with three
independent linkers and a monotone combiner. Deterministic, no network, no LLM.
The fourth part of LK-03, a **semantic/embedding linker, is deferred** (see
Follow-ups).

## Placement (DEC-003)

`radius_testing.linking`, a sub-package of `packages/testing`, not a new package.
DEC-003 only allows packages a documented phase requires, and DEC-007 lists the
approved research packages (`intent`, `evidence`, ...); `linking` is not one of
them. The task is "symbol to *test*" evidence: it consumes test discovery
conventions, the F-07 sandbox runner and F-11 flaky data that already live in
`packages/testing`, and its dynamic half must call `ContainerSandboxRunner`
directly. `packages/analysis` was the alternative (it owns LK-01 and F-08's
bridge) but would then depend on the test runner. New dependencies of
`radius_testing`: `radius_graph` (F-08 `PythonSymbolGraph`, reused, not forked)
and, duck-typed with no import, LK-01's `ChangedSymbol`. LK-05/06 will unify the
link types with the criterion-to-symbol side (LK-02, `packages/linking` on another
branch); until then `SymbolTestLink` lives here.

## Model (`model.py`)

`SymbolTestLink(symbol_id, test_id, linker, score in [0,1], kind, evidence[],
depth, algo_version, components, low_confidence)`

* `kind` in `direct_call`, `indirect_call` (with `depth`), `import_reference`,
  `name_convention`, `dynamic_coverage`, `fixture_dependency` (`depth` = fixture
  hops).
* `test_id` = `path::Class::function` (pytest node id without the parametrisation
  suffix; `normalize_test_id` strips `[...]` and `|run`). Parametrised cases are
  one function-level link; the case count is evidence.
* Inputs are `LinkTarget`s (`LinkTarget.from_changed_symbol(lk01_symbol)`), outputs
  are `LinkSet`s with sorted, canonical JSON (`to_json`), so equal inputs give
  byte-equal output.
* `algo_version`: `static-link-v1`, `naming-link-v1`, `dynamic-cov-link-v1`,
  `link-combine-v1`.

## Static linker (`static.py`, `pyindex.py`, `ecmascript.py`)

Python (stdlib `ast`; pytest and unittest):

* resolves `from x import y as z`, `import a.b as m`, module attribute access
  (`pkg.mod.f`), re-exports through `__init__`, star imports, relative imports,
  `self.x`, local aliases (`h = mod.f`), shadowing by parameters/locals;
* `mock.patch("pkg.mod.f")`, `patch.object(mod, "f")`, `mocker.patch`,
  `monkeypatch.setattr("pkg.mod.f", ...)` / `setattr(mod, "f", ...)`, constant
  `getattr(mod, "f")` -> `import_reference` (the symbol is replaced, not run);
* fixtures: parameters, `usefixtures`, `getfixturevalue`, autouse, class/module/
  `conftest.py` scoping (closest wins, a same-name fixture may request its parent),
  fixture chains, fixtures imported into a module, `name=` renames, parametrised
  names that shadow fixtures; `setUp`/`setUpClass`/`setup_method`/module hooks and
  module-level code count as hop-1 `fixture_dependency`;
* inheritance from base test classes in the same or another module; unittest
  `TestCase` subclasses; classes with `__init__` are not collected (as in pytest);
* calls through project functions up to `max_depth` (default 3) with decay;
* dynamic code (`getattr` with a non-constant name, `importlib`, `eval`, ...) in a
  test yields **low-confidence** candidates (score 0.10) for symbols in packages the
  test imports, like F-08's dynamic fallback;
* a **name layer** reuses F-08 (`radius_graph.symbol_impact.PythonSymbolGraph.impact`,
  imported, not forked) for references the resolver cannot type (`obj.m()`):
  `0.25 * 0.7**(d-1)`, `low_confidence`, skipped when the test resolves that name
  to a different definition (name collisions).

| Evidence | Score |
| --- | --- |
| test body calls the symbol | 0.90 |
| class instantiated and `.method` accessed | 0.70 |
| symbol referenced (not called) / patched | 0.55 / 0.50 |
| each fixture / setup hop | x 0.85 |
| through project helpers, depth d | 0.75 x 0.7^(d-1) |
| only the class of a changed method is used | x 0.5 |
| imported by the test module, unused | 0.20 |

TypeScript/JavaScript (**partial, best effort**): F-09 tree-sitter parse of
jest/vitest files; relative `import { a as b }`, default and namespace imports and
`describe`/`it`/`test` titles (`path::describe::it`). A link means "the file imports
the symbol's module and the `it` body names it" (0.65, or 0.20 when imported only),
always `low_confidence`. No `require`, path aliases, barrel re-exports, types or
call depth.

## Naming linker (`naming.py`)

`test_<module>.py`, `<module>_test.py`, `<module>.test|spec.ts`, mirror paths
under `tests/`, `test_<function>[_suffix]`, `Test<Class>.test_<method>`, unittest
camelCase `testApplyDiscount`. Function name plus matching file 0.60 (also the
cap), name only 0.30 (0.15 for names shorter than 5), class convention 0.30-0.55,
test in the mirror file only 0.25, same-basename file 0.15. Ties: a test name that
matches several changed symbols keeps the longest symbol name; equal names rank by
file-match strength. It needs no call graph, so it still works when static linking
finds nothing.

## Dynamic coverage-context linker (`dynamic.py`, `coveragedb.py`)

1. Gate: `RADIUS_FEATURE_COVERAGE_CONTEXTS` (default off) or `enabled=True`.
2. `DynamicCoverageLinker(runner)` accepts **only** a `ContainerSandboxRunner`
   (`SandboxRequiredError` otherwise); there is no host fallback. Test paths are
   validated (`UnsafeTestPathError`): repo-relative `.py`, no `..`/absolute/option-like
   names/symlink escapes.
3. A constant driver script (`DRIVER_SCRIPT`) runs `pytest` under `coverage.py` with
   one context per test item (the node id, as `pytest-cov --cov-context=test`) and
   writes `.coverage` and `junit.xml` to the sandbox results mount. Files are run
   in batches (`batch_size` 25, `max_batches` 20), so a timeout loses one batch.
   `ContainerSandboxRunner.run_collecting` (new, additive) returns those files; only
   plain, size-capped files are read.
4. `coveragedb` parses the SQLite file offline with the standard library (numbits
   decoding, `arc` fallback, `/workspace/` prefix stripped, size/row/context caps).
5. Executed lines per test context are intersected with each target's `new_range`
   (`use_old_ranges=True` for a base run) -> `dynamic_coverage` links, strength
   `0.6 + 0.1 * hit_lines` (max 1.0), line numbers as evidence.
6. Missing/corrupt coverage, timeouts, sandbox errors: notes and `status`
   (`ok`/`partial`/`no_data`), never an exception. A failed test keeps its
   (partial) coverage with x0.85 and an evidence note; an F-11 flaky test (pass
   `flaky_tests`) gets x0.7.

The sandbox image must contain `pytest` and `coverage`:
`printf 'FROM radius-sandbox-test:latest\nRUN pip install coverage' | docker build -t radius-sandbox-cov:latest -`
(`RADIUS_SANDBOX_COV_IMAGE` selects it for the integration test and the eval script).

## Combiner (`combine.py`)

Per `(symbol, test)`: `sn` = static alone `min(s, .90)`; naming alone `min(n, .50)`;
both `max(1-(1-s)(1-.5n'), min(n,.5))` capped at `.90`, where `n' = n` only when
`n >= .30`. With dynamic evidence `d`: `max(sn, .92 + .07 d)` plus an agreement boost
`1-(1-x)(1-.3 sn)`, capped at `.99`. Every step is a `max` or noisy-or, so
**adding evidence never lowers a score** (grid-tested), a measured execution always
outranks static/naming guesses, and the absence of a dynamic link never lowers
anything (the run may have been partial). Per-linker scores, kinds and versions are
kept in `components`, evidence is concatenated (dynamic first). `LinkSet.for_symbol`
and `for_test` give the per-symbol / per-test rankings.

## Evaluation (`evaluation.py`, `scripts/test_link_eval.py`)

`prf`, `select_tests`, `evaluate_linksets`, `ablation` (single linker, leave-one-out).
The script runs the F-14 intent fixtures: LK-01 targets, all linkers, and an
**independent ground truth** (per-test `sys.settrace` inside the sandbox, not
coverage.py), reporting precision/recall against that truth and against the labelled
`expected.json` links. **Fixture sanity, not a research result** (eight tiny
fixtures with mostly direct calls). Changed test-file symbols are excluded from
targets.

## Limits

* Static: no type inference (`obj.m()` falls to the low-confidence name layer),
  no metaclass/descriptor/decorator-generated calls, no `conftest` plugins loaded via
  `pytest_plugins`, no `parametrize` ids, no async-framework specifics, nested
  functions inside project (non-test) functions are not separate entities.
* Dynamic: needs execution (cost recorded in `DynamicResult.duration_ms`); Python only
  (coverage.py); lines at import time run outside any test context and are not
  attributed; module-scoped fixtures are attributed to the first test that uses
  them; coverage saved only at process end (a killed container loses its batch).
* Symbol ranges are line-based; an edit that only changes `def` lines is hit at import.
* Everything is per function, not per parametrised case.

## Follow-ups

* Semantic/embedding linker (last resort, low weight, cached by symbol hash).
* TypeScript depth: `require`, tsconfig paths, barrel files, call depth, jest
  `moduleNameMapper`; a JS coverage-context path (c8/istanbul `--coverage` per test).
* Cache by `(symbol hash, test hash)` (LK-09); persist links (LK-05); wire the
  flag into the worker once LK-05 stores them.
* Unify with LK-02's link types (LK-05/06); use the combiner inside LK-06's
  noisy-or confidence.
* Optional per-case parametrised links and rerun-based flaky coverage.
