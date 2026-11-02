# Tamper rules (EV-02, catalog `tamper-rules-v1`)

Deterministic, explainable detection of diff-level changes that **weaken or fake verification**.
Implemented in `packages/analysis/src/radius_analysis/tamper/` (a sub-package of `radius_analysis`,
see its README for placement, API, configuration and the T-id mapping). No LLM, no network.

> Severities below are **assumed defaults**, the same values the F-14 fixtures carry as
> `assumed_severity`. They are configuration, pending the EV-02 owner decision. Nothing on this
> page is a measured research result: the only evaluation so far is a fixture sanity check
> (`scripts/tamper_eval.py`).

## How to read a finding

Every finding carries: `rule_id` + `check` (the variant), `family`, `severity`, `confidence`
(0 to 1, how sure the rule is that this is tampering, not how severe), `path`, `symbol` / `test_id`,
`old_range` / `new_range`, `old_snippet` / `new_snippet`, a human-readable `reason`, `evidence`
and a stable `finding_id` (hash of catalog version, rule, check, path, symbol and whitespace-
normalised snippets, so it survives rebases and reformatting). Waivers refer to that id or to a
`rule[:check]` + path glob and are applied by configuration only; a marker inside the PR (for
example a comment) never waives a finding, because the PR author controls the diff.

## Catalog

| Id | Family | Title | Checks (default severity) | Maps to |
|---|---|---|---|---|
| T001 | test_disabling | Test deleted without removing the code under test | `test_deleted` (high), `parametrize_case_removed` (high), `commented_out_test` (high) | T001 |
| T002 | test_disabling | Test newly skipped or xfailed | `skip` (high), `skipif` (medium), `xfail` (high), `runtime_skip` (high), `module_skip` (high) | T002 |
| T003 | assertion_weakening | Assertion removed | `assertion_removed` (high), `body_emptied` (high), `commented_out_assertion` (high) | T003 |
| T004 | assertion_weakening | Assertion weakened | `tolerance_widened` (high), `conjunct_dropped` (high), `strength_reduced` (high) | T004 |
| T005 | tautology | Tautological assertion | `always_true` (high), `self_comparison` (high) | T005 |
| T006 | expected_value_change | Expected value changed with the code under test | `expected_literal_changed` (medium), `snapshot_updated` (medium) | T006 |
| T007 | exception_swallowing | Broad exception swallow | `test_swallow` (high), `swallows_assertion` (high), `raises_broadened` (high), `raises_broad` (medium), `source_broad_swallow` (medium) | T007 |
| T008 | mock_abuse | Unit under test mocked in its own test | `patches_unit_under_test` (high), `asserts_on_mock` (high), `autospec_removed` (medium) | T008 |
| T009 | config_weakening | Coverage suppression | `pragma_no_cover` (medium), `fail_under_lowered` (high), `omit_added` (medium), `coverage_disabled` (high) | T009 |
| T010 | config_weakening | CI / test-config weakening | `continue_on_error` (high), `step_disabled` (high), `or_true` (high), `test_step_removed` (high), `timeout_increased` (medium), `pytest_flag_removed` (medium), `tests_deselected` (high), `lint_weakened` (medium), `plugin_disabled` (low), `fail_fast_added` (info) | T010 |
| T011 | config_weakening | Retries and sleeps added to force a pass | `test_sleep` (low), `test_retry_marker` (medium), `ci_retry` (medium) | T011 |
| T012 | dependency | Hallucinated or unverifiable dependency | `registry_missing` (high), `typosquat` (high), `unverified_guarded_import` (medium), `lockfile_drift` (medium), `unverified_new_dependency` (medium), `undeclared_import` (medium) | T012 |
| T013 | suppression | Lint / type suppression added | `noqa` (low), `type_ignore` (low), `lint_disable` (low), `nosec` (medium), `ts_ignore` (low) | T013 |
| T014 | code_quality | Stubbed implementation | `body_stubbed` (medium), `new_stub` (low) | T014 |
| T015 | code_quality | Security downgrade | `tls_verify_disabled` (high), `hardcoded_secret` (high), `sql_interpolation` (high) | T015 |
| T016 | code_quality | Debug artifacts left behind | `debug_call` (low) | T016 |
| T017 | fixture_tampering | Fixture / conftest tampering | `autouse_patch` (high), `collection_hook` (high), `conftest_changed_with_source` (low) | extension |

## Rules

### T001

**Test deleted without removing the code under test** (family `test_disabling`; maps to: T001)

Deleting a failing test (or a parametrized case, or commenting it out) removes the evidence while the behavior it pinned is still shipped.

| Check | Default severity | Meaning |
|---|---|---|
| `test_deleted` | high | test removed while the code under test remains |
| `parametrize_case_removed` | high | parametrize cases removed |
| `commented_out_test` | high | test function commented out |

Example, before:

```text
def test_rejects_zero():
    with pytest.raises(ValueError):
        reserve(1, 0)
```

Example, after:

```text
# (test removed, reserve() still exists)
```

Limitations: The code under test is inferred from the names the test calls; if every called name is a symbol removed in the same PR the deletion is treated as legitimate. Tests moved to another file with an identical body are not reported.

### T002

**Test newly skipped or xfailed** (family `test_disabling`; maps to: T002)

A skipped or expected-failure test reports green/neutral while verifying nothing; it is the cheapest way to make a failing suite pass.

| Check | Default severity | Meaning |
|---|---|---|
| `skip` | high | skip marker / unittest.skip added |
| `skipif` | medium | conditional skip added |
| `xfail` | high | xfail / expectedFailure added |
| `runtime_skip` | high | pytest.skip()/xfail() or `if False` in the body |
| `module_skip` | high | module-level pytestmark skip/xfail added |

Example, before:

```text
def test_rejects_non_positive():
```

Example, after:

```text
@pytest.mark.skip(reason="flaky")
def test_rejects_non_positive():
```

Limitations: `skipif` with a platform/version condition is often legitimate (severity medium, confidence 0.5). Skips that exist at base are not reported.

### T003

**Assertion removed** (family `assertion_weakening`; maps to: T003)

A test that asserts less proves less; removing assertions keeps the test green while the behavior it used to pin is no longer checked.

| Check | Default severity | Meaning |
|---|---|---|
| `assertion_removed` | high | fewer assertions in an existing test |
| `body_emptied` | high | test body reduced to pass / ... / docstring |
| `commented_out_assertion` | high | an assertion was commented out |

Example, before:

```text
def test_total():
    assert total([1, 2]) == 3
    assert total([]) == 0
```

Example, after:

```text
def test_total():
    assert total([1, 2]) == 3
```

Limitations: Assertions moved to another test of the same PR are not reported; legitimate consolidation of parametrized tests can look the same (confidence 0.7).

### T004

**Assertion weakened** (family `assertion_weakening`; maps to: T004)

Replacing an exact check by membership, ordering, `is not None` or plain truthiness (or widening a tolerance) lets wrong values pass.

| Check | Default severity | Meaning |
|---|---|---|
| `tolerance_widened` | high | approx/almost-equal tolerance increased |
| `conjunct_dropped` | high | one clause of an `and` assertion dropped |
| `strength_reduced` | high | assertion replaced by a weaker kind (exact -> is not None, ...) |

Example, before:

```text
assert reserve(10, 3) == 7
```

Example, after:

```text
assert reserve(10, 3) is not None
```

Limitations: Pairs assertions by position inside a test; a rewritten test with unrelated assertions is reported with lower confidence (0.6). Does not judge whether the new check is semantically equivalent.

### T005

**Tautological assertion** (family `tautology`; maps to: T005)

`assert True`, `assert x == x` and similar can never fail, so the test contributes no evidence while looking like a passing check.

| Check | Default severity | Meaning |
|---|---|---|
| `always_true` | high | assertion that can never fail (`assert True`) |
| `self_comparison` | high | an expression compared with itself |

Example, before:

```text
assert reserve(5, 5) == 0
```

Example, after:

```text
assert reserve(5, 5) == reserve(5, 5)
```

Limitations: Only assertions on added or changed lines are reported. Idempotence or determinism checks (`f(x) == f(x)`) are legitimate in rare cases; they carry confidence 0.8, plain constants 0.95.

### T006

**Expected value changed with the code under test** (family `expected_value_change`; maps to: T006)

When a test's expected value is edited in the same PR that changes the code it exercises, the test may have been bent to match new behavior instead of checking the intended behavior.

| Check | Default severity | Meaning |
|---|---|---|
| `expected_literal_changed` | medium | expected literal edited while the code under test also changed |
| `snapshot_updated` | medium | snapshot / golden file edited alongside source behavior changes |

Example, before:

```text
assert price(2) == 10   # price() also changes in this PR
```

Example, after:

```text
assert price(2) == 12
```

Limitations: Cannot know whether the new value is the intended one; justification must come from intent (EV-03/LK-02) or a waiver. Snapshot detection is path-convention based; unchanged-source PRs are never reported.

### T007

**Broad exception swallow** (family `exception_swallowing`; maps to: T007)

`try/except: pass` around a test body (or `pytest.raises(Exception)`) makes a test pass whatever happens; in production code a swallowed exception hides failures the tests no longer see.

| Check | Default severity | Meaning |
|---|---|---|
| `test_swallow` | high | test catches broad exceptions and ignores them |
| `swallows_assertion` | high | test catches AssertionError and ignores it |
| `raises_broadened` | high | pytest.raises(SpecificError) broadened to Exception |
| `raises_broad` | medium | new pytest.raises(Exception) in a test |
| `source_broad_swallow` | medium | new `except Exception: pass` in non-test code |

Example, before:

```text
with pytest.raises(ValueError):
    reserve(10, 0)
```

Example, after:

```text
with pytest.raises(Exception):
    reserve(10, 0)
```

Limitations: Handlers that log, re-raise or assign are not reported. In non-test code only broad handlers with an empty body are reported (confidence 0.5).

### T008

**Unit under test mocked in its own test** (family `mock_abuse`; maps to: T008)

If the test replaces the function it asserts on (or asserts on a mock it configured itself), the assertion checks the mock, not the code.

| Check | Default severity | Meaning |
|---|---|---|
| `patches_unit_under_test` | high | the function the test asserts on is patched in the same test |
| `asserts_on_mock` | high | assertion checks the return value of a Mock the test configured |
| `autospec_removed` | medium | autospec/spec removed from a patch |

Example, before:

```text
@patch("shop.pricing.helper")
def test_total(m):
    assert total(2) == 4
```

Example, after:

```text
@patch("shop.pricing.total")
def test_total(m):
    assert total(2) == 4
```

Limitations: Name-based: the patched attribute name is compared with the names the test calls; it does not resolve imports, so same-named unrelated functions can false-positive. Only patches/assertions that are new in this PR are reported.

### T009

**Coverage suppression** (family `config_weakening`; maps to: T009)

Coverage gates only protect when thresholds hold and code is measured; lowering `fail_under`, adding `omit` entries or `# pragma: no cover` hides untested code from the gate.

| Check | Default severity | Meaning |
|---|---|---|
| `pragma_no_cover` | medium | `# pragma: no cover` added |
| `fail_under_lowered` | high | coverage fail-under threshold lowered or removed |
| `omit_added` | medium | coverage omit / exclude entry added |
| `coverage_disabled` | high | --no-cov added or --cov removed |

Example, before:

```text
[tool.coverage.report]
fail_under = 90
```

Example, after:

```text
[tool.coverage.report]
fail_under = 60
```

Limitations: Section/key detection is textual (TOML/INI). Entries in `exclude_lines` are reported even when benign (e.g. `if TYPE_CHECKING:`), at medium severity.

### T010

**CI / test-config weakening** (family `config_weakening`; maps to: T010)

Checks only protect if they run and can fail: `continue-on-error`, `|| true`, `if: false`, removed test steps, deselected tests and relaxed strictness all let a broken PR stay green.

| Check | Default severity | Meaning |
|---|---|---|
| `continue_on_error` | high | `continue-on-error: true` added |
| `step_disabled` | high | `if: false` added to a step/job |
| `or_true` | high | `|| true` added to a test/lint command |
| `test_step_removed` | high | a test/lint command was removed from CI or Make |
| `timeout_increased` | medium | CI timeout increased |
| `pytest_flag_removed` | medium | strictness flag removed from test config |
| `tests_deselected` | high | --deselect/--ignore/-k "not" added |
| `lint_weakened` | medium | type/lint strictness relaxed in config |
| `plugin_disabled` | low | `-p no:<plugin>` added to pytest options |
| `fail_fast_added` | info | `-x`/`--maxfail` added (informational) |

Example, before:

```text
- run: pytest -q
```

Example, after:

```text
- run: pytest -q || true
```

Limitations: Textual and tool-name based. A test step moved to another file in the same PR is only recognised when the tool still appears in the changed file's head text. Hand-written wrappers around test commands are not understood.

### T011

**Retries and sleeps added to force a pass** (family `config_weakening`; maps to: T011)

Reruns, `@flaky` and sleeps turn a failing signal into a passing one without fixing the cause; they are common AI shortcuts for flaky or racy tests.

| Check | Default severity | Meaning |
|---|---|---|
| `test_sleep` | low | sleep added to a test |
| `test_retry_marker` | medium | flaky/retry marker added to a test |
| `ci_retry` | medium | retries/reruns added to CI or test config |

Example, before:

```text
def test_job():
    start(); assert done()
```

Example, after:

```text
@pytest.mark.flaky(reruns=5)
def test_job():
    start(); time.sleep(2); assert done()
```

Limitations: A `sleep` in a test is weak evidence (confidence 0.4): it is often a legitimate wait. Retry detection is keyword based.

### T012

**Hallucinated or unverifiable dependency** (family `dependency`; maps to: T012)

AI-generated code invents plausible package names. A new dependency that is not in the lockfile, not a well-known package, or imported only behind try/except ImportError may not exist (supply-chain risk) while the tests stay green.

| Check | Default severity | Meaning |
|---|---|---|
| `registry_missing` | high | registry port reports the package does not exist |
| `typosquat` | high | new dependency one edit away from a popular package |
| `unverified_guarded_import` | medium | new unlocked dependency whose import is wrapped in try/except ImportError; offline it cannot be verified, so it is medium (DEC-028). With a registry that reports the package missing the finding is `registry_missing` (high) |
| `lockfile_drift` | medium | new dependency missing from the lockfile |
| `unverified_new_dependency` | medium | new dependency that cannot be verified offline |
| `undeclared_import` | medium | new import of a third-party package declared nowhere |

Example, before:

```text
# runtime dependencies: none
```

Example, after:

```text
pytimeparse-ultra==3.1.4
```

Limitations: Offline mode cannot prove a package does not exist: unknown but real packages are reported with low confidence (0.4) unless a lockfile covers them. The popular-package list is small and bundled. A registry lookup runs only when `params.use_registry` is true AND a registry port is injected; no network adapter ships with EV-02.

### T013

**Lint / type suppression added** (family `suppression`; maps to: T013)

A suppression marker on a changed line silences the checker that would have flagged it. One is routine; a pattern of them is how type or lint gates get bypassed.

| Check | Default severity | Meaning |
|---|---|---|
| `noqa` | low | `# noqa` added |
| `type_ignore` | low | `# type: ignore` added |
| `lint_disable` | low | `# pylint: disable` added |
| `nosec` | medium | `# nosec` added (security linter silenced) |
| `ts_ignore` | low | `@ts-ignore` / `eslint-disable` added |

Example, before:

```text
value = parse(raw)
```

Example, after:

```text
value = parse(raw)  # type: ignore
```

Limitations: Benign idioms are skipped: `# noqa` limited to F401/E402/E501/I001 and `type: ignore[import...]`. Marker detection is textual and can match inside strings. Use `params.min_added_suppressions` to report only above a PR-wide count.

### T014

**Stubbed implementation** (family `code_quality`; maps to: T014)

Replacing a real body by `pass`, `...`, `raise NotImplementedError` or `return None` makes tests that only check 'no crash' pass while the feature is gone.

| Check | Default severity | Meaning |
|---|---|---|
| `body_stubbed` | medium | implemented function reduced to a stub |
| `new_stub` | low | new non-abstract function with a stub body |

Example, before:

```text
def total(xs):
    return sum(xs)
```

Example, after:

```text
def total(xs):
    raise NotImplementedError
```

Limitations: Abstract methods, overloads, Protocol/ABC/exception classes and dunder methods are exempt. New stubs are weak evidence (confidence 0.45): placeholders for later work are common.

### T015

**Security downgrade** (family `code_quality`; maps to: T015)

Turning off TLS verification, hard-coding credentials or interpolating SQL are classic shortcuts that make a failing integration test pass at the cost of safety.

| Check | Default severity | Meaning |
|---|---|---|
| `tls_verify_disabled` | high | TLS verification turned off |
| `hardcoded_secret` | high | credential-like literal assigned in code |
| `sql_interpolation` | high | SQL built by string interpolation |

Example, before:

```text
requests.get(url)
```

Example, after:

```text
requests.get(url, verify=False)
```

Limitations: Regex based and intentionally narrow, not a SAST replacement (use Semgrep/Bandit via SARIF, EV-01). Test files are skipped; placeholder-looking secrets are ignored.

### T016

**Debug artifacts left behind** (family `code_quality`; maps to: T016)

Leftover prints and breakpoints indicate unreviewed exploratory edits; `breakpoint()` can hang CI.

| Check | Default severity | Meaning |
|---|---|---|
| `debug_call` | low | print / breakpoint / pdb left in library code |

Example, before:

```text
def total(xs):
    return sum(xs)
```

Example, after:

```text
def total(xs):
    print(xs)
    return sum(xs)
```

Limitations: Low severity. CLI entry points (`__main__.py`, `cli.py`, `scripts/`) and `if __name__ == '__main__'` blocks are exempt from the `print` check.

### T017

**Fixture / conftest tampering** (family `fixture_tampering`; maps to: extension)

A shared fixture or conftest hook affects every test in scope: an autouse fixture that patches core functions, or a hook that skips items, disables checks far from the diff a reviewer reads.

| Check | Default severity | Meaning |
|---|---|---|
| `autouse_patch` | high | new autouse fixture that patches/mocks/skips for every test |
| `collection_hook` | high | conftest hook or collect_ignore that deselects/skips tests |
| `conftest_changed_with_source` | low | conftest code changed in a PR that also changes source behavior |

Example, before:

```text
# conftest.py (unchanged)
```

Example, after:

```text
@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr("app.core.validate", lambda *a: True)
```

Limitations: EV-02 extension: not part of the DESIGN T001-T016 catalog. Name-based and syntactic; autouse fixtures that only set env vars are not reported. The `conftest_changed_with_source` check is a weak signal (confidence 0.35).

## Configuration

```json
{
  "catalog_version": "tamper-rules-v1",
  "disable": ["T016"],
  "rules": {
    "T002": {"severity": "medium"},
    "T012:unverified_new_dependency": {"severity": "low"}
  },
  "params": {"min_added_suppressions": 1, "use_registry": false},
  "waivers": [
    {"finding_id": "tf_0123456789abcdef", "reason": "tracked in ISSUE-123", "approved_by": "lead"},
    {"rule": "T013", "path": "legacy/*", "reason": "legacy module, owner agreed"}
  ]
}
```

A `rule:check` override beats a `rule` override, which beats the default. Waived findings are not
dropped: the report lists them separately with the waiver reason.

## Verification status

* Rule behavior: table-driven cases under `packages/analysis/tests/tamper_cases/` (true positive,
  true negative and near miss per rule).
* F-14 fixtures: 04 yields exactly T001, T002, T004, T005; 06 yields T012; the other fixtures yield
  nothing. This is a **fixture sanity check** (the fixtures were written together with the rules'
  expectations), not a recall or precision measurement. Rule hit rates on real agent and human PRs
  are the job of EP-07 / RQ2.
