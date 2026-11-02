# Tamper rule engine (EV-02)

Deterministic, explainable detection of diff-level changes that **weaken or fake
verification** in (AI-generated) pull requests: deleted or weakened assertions, skipped
tests, tautologies, swallowed exceptions, mocked-away code under test, CI/coverage
weakening, suppression markers, stubbed implementations and hallucinated dependencies.
No LLM, no network, no database. Catalog version: `tamper-rules-v1`.

The catalog table, per-rule rationale, examples and limitations live in
[`docs/evidence/TAMPER_RULES.md`](../../../../../docs/evidence/TAMPER_RULES.md).

## Placement (DEC-003 / DEC-007)

A sub-package of `radius_analysis` (`radius_analysis.tamper`), **not** the `packages/tamper`
package that DEC-007 allows. Reasons: the engine consumes LK-01's `SymbolChangeSet`, snapshot
readers and diff parser directly (a separate package would depend on `radius_analysis` and
create a cycle with the worker wiring), it owns no persistence yet, and DEC-003 prefers fewer
packages until a task needs one. If persistence (EV-01 / LK-05) or a second consumer makes a
standalone package worthwhile, the public surface (`radius_analysis.tamper.__init__`) is the
seam to lift out. The test-file convention mirrors
`radius_testing.infrastructure.discovery`; analysis must not import another domain's
implementation, so `classify.py` restates it and `test_tamper_catalog.py` checks parity.

## Usage

```python
from radius_analysis.symbol_changes import GitSnapshot, RefRange, extract_symbol_changes
from radius_analysis.tamper import TamperConfig, analyze_tampering

changes = extract_symbol_changes(base, head, diff_text)          # LK-01
report = analyze_tampering(changes, base, head, TamperConfig(), diff_text=diff_text)
for f in report.findings:
    print(f.rule_id, f.check, f.severity.label, f.path, f.reason)
print(report.to_json(indent=2))
```

`analyze_tampering(changeset, repo_base, repo_head, config)` never raises: unreadable,
oversized, binary or unparseable files are listed in `report.unanalyzable`, a rule that
throws is listed in `report.rule_errors` and the others still run, time and finding limits
set `report.truncated`. `repo_base` may be `None` when `diff_text` is given (the base is
rebuilt as in LK-01). Debug CLI: `python -m radius_analysis.tamper rules|catalog-md|analyze`.
Fixture runner: `python scripts/tamper_eval.py [DIR] [--config rules.json] [--json] [--check]`.

## Architecture

```
SymbolChangeSet + base/head SnapshotReader + (diff text)
        -> TamperContext   (context.py: per-file FileView with roles, base/head text,
                            added/removed lines, lazily parsed Python via pyast.py)
        -> rules/*         (TamperRule protocol: id, family, languages, checks, doc,
                            evaluate(context) -> list[Finding])
        -> service.py      (config switches, ids made unique, waivers, limits)
        -> TamperReport    (model.py; to_dict/to_json, deterministic)
```

Rules never parse diffs: changed lines come from the context (the diff text when given,
else LK-01 hunk ranges, else a bounded `difflib` fallback for files LK-01 does not hunk,
such as lockfiles). Python rules compare base and head ASTs per test function
(`pyast.py` classifies assertions: exact, approx, membership, ordering, isinstance,
not-None, truthy, tautology, raises) and use `ast.unparse` text for snippets and ids, so
formatting-only edits never produce findings.

## Finding contract

`finding_id` (stable: sha256 of catalog version, rule, check, path, symbol/test, and
whitespace-normalised old/new snippet, never line numbers; repeated identical findings get
an occurrence index), `rule_id`, `check`, `family`, `severity`, `confidence`, `path`,
`symbol`, `test_id` (`path::Class::method`), `old_range` / `new_range`, `old_snippet` /
`new_snippet`, `reason`, `evidence`, `catalog_version`, `waiver_key` (= `finding_id`).
`confidence` is the rule's certainty that this is tampering; `severity` is how bad it is if
so. They are separate on purpose.

## Configuration (JSON)

```json
{
  "catalog_version": "tamper-rules-v1",
  "disable": ["T016"],
  "enable_only": ["T001", "T002"],
  "rules": {
    "T002": {"severity": "medium"},
    "T012:unverified_new_dependency": {"severity": "low", "enabled": true}
  },
  "params": {"min_added_suppressions": 1, "use_registry": false, "max_findings": 500,
             "max_files": 2000, "max_file_bytes": 1000000, "time_budget_seconds": 30,
             "typosquat_max_distance": 1},
  "waivers": [
    {"finding_id": "tf_0123456789abcdef", "reason": "ISSUE-123", "approved_by": "lead"},
    {"rule": "T013", "path": "legacy/*", "reason": "owner agreed"}
  ]
}
```

Precedence: `rule:check` override, then `rule` override, then the built-in default.
Waived findings are moved to `report.waived` with their reason (never silently dropped).
**There is deliberately no inline suppression comment** (`# radius: ignore`): the PR author
controls the diff, so an in-diff waiver would defeat the rules.

## Severities are assumptions (pending EV-02 owner decision)

The default severities (T001, T002, T004, T005, T012 high; T006, T009 medium; T011, T013
and T016 low; ...) are the `assumed_severity` values used by the F-14 fixtures'
`expected.json` plus judgment for the rules the fixtures do not cover. They are **configuration, not
findings of the research**, and stay assumptions until the EV-02 owner fixes them.
`DESIGN.md` 6.3 severity penalties and the 6.5 verdict rules are applied by the consumer
(EV-06/EV-07), not here.

## Rule ids and mapping to T001-T016

Every id `T001`-`T016` in `docs/research/tasks/EV-evidence-quality.md` / `DESIGN.md` is
implemented under the same id (the F-14 fixtures use these ids). `T017` is an EV-02
extension. Items from the task brief that have no id of their own are checks of the closest
rule.

| Brief item | Rule : check |
|---|---|
| test deleted | T001 : `test_deleted` |
| parametrize cases removed | T001 : `parametrize_case_removed` |
| commented-out tests | T001 : `commented_out_test` |
| skip / xfail / skipif / `unittest.skip` / `if False` / module or class marks | T002 : `skip`, `skipif`, `xfail`, `runtime_skip`, `module_skip` |
| assert deleted / count reduced | T003 : `assertion_removed` |
| test body emptied (`pass`, `...`) | T003 : `body_emptied` |
| commented-out assertion | T003 : `commented_out_assertion` |
| `==` to `in` / `>=` / `is not None` / truthiness, exact to isinstance | T004 : `strength_reduced` |
| `pytest.approx` / `assertAlmostEqual` tolerance widened | T004 : `tolerance_widened` |
| one clause of an `and` assertion dropped | T004 : `conjunct_dropped` |
| `assert True`, `assert x == x`, `assert not False`, `assertTrue(True)` | T005 : `always_true`, `self_comparison` |
| expected literal changed together with the code under test | T006 : `expected_literal_changed` |
| snapshot / golden update without rationale | T006 : `snapshot_updated` |
| `try/except: pass` in tests, swallowed `AssertionError` | T007 : `test_swallow`, `swallows_assertion` |
| `pytest.raises(Exception)` broadened or added | T007 : `raises_broadened`, `raises_broad` |
| patching the unit under test, autospec removed, assert on own MagicMock | T008 : `patches_unit_under_test`, `autospec_removed`, `asserts_on_mock` |
| `# pragma: no cover`, `fail_under` lowered, `omit` additions, `--no-cov` | T009 |
| `continue-on-error`, `\|\| true`, `if: false`, removed test step, deselect, addopts flags removed, timeouts, lint relaxed, `-p no:`, `-x`/`--maxfail` | T010 |
| retries, `@flaky`, `sleep` in tests | T011 |
| hallucinated dependency, typosquat, lockfile/manifest drift, undeclared import | T012 |
| `# noqa`, `# type: ignore`, `# nosec`, `# pylint: disable`, `@ts-ignore` | T013 (`# pragma: no cover` is T009) |
| stubbed implementation | T014 |
| TLS verify off, hard-coded secret, SQL interpolation | T015 |
| debug artifacts | T016 |
| autouse fixture that patches core functions, conftest hooks / `collect_ignore`, conftest changed with source | T017 (extension) |

## T012 and the registry port

Offline checks (always on): manifest diff (`requirements*.txt`, `pyproject.toml`), lockfile
names (`uv.lock`, `poetry.lock`, `pdm.lock`, `Pipfile.lock`), the Python stdlib list, a
small bundled known-package list (typosquat reference, **not** a registry snapshot), local
module detection and try/except-ImportError detection. A registry lookup goes through the
injectable `PackageRegistry` port (`exists(name) -> bool | None`) and runs only when
`params.use_registry` is true **and** a port is passed to `analyze_tampering`. EV-02 ships
`StaticPackageRegistry` for tests; a PyPI adapter is a follow-up.
On F-14 fixture 06 the package is reported as `unverified_guarded_import` (offline), not as
`registry_missing`: offline we can say "unverified and imported behind `try/except
ImportError`", not "does not exist".

## Adding a rule

Subclass `BaseRule` (`rules/base.py`), set `id`, `family`, `languages`, `checks`
(`CheckSpec(default severity, description)`) and `doc` (`RuleDoc`), implement
`evaluate(context)` using `context.finding(...)`, register it in `registry.py`, add cases in
`packages/analysis/tests/tamper_cases/`, regenerate the docs table
(`python -m radius_analysis.tamper catalog-md`) and document it in `TAMPER_RULES.md`.
`test_tamper_catalog.py` fails if docs, a positive case, a negative case or a per-check
positive case is missing.

## Known limits (read before trusting a finding)

* Syntactic, name-based reasoning; no type resolution or import resolution. Patched-name vs
  called-name matching (T008) and code-under-test inference (T001) can false-positive on
  same-named functions.
* A rewritten test whose assertions are unrelated to the old ones is paired by position and
  reported with confidence 0.6.
* T006 cannot know whether a new expected value is the intended one; it flags the
  co-occurrence. Justification must come from intent (LK-02 / EV-03) or a waiver.
* Config rules (T009-T011) are textual (YAML/TOML/INI/Make). Unusual layouts are missed.
* T012 offline cannot prove non-existence. Unknown but real packages are reported with
  confidence 0.4 (`unverified_new_dependency`, medium) unless a lockfile covers them.
* Python is analysed deeply; TypeScript / JavaScript get only the line-based rules
  (T013 `ts_ignore`, T010 etc. on config files). Deeper JS/TS rules are a follow-up.
* Not a SAST tool: T015 is deliberately narrow.

## Follow-ups

PyPI/npm registry adapters behind the port; JS/TS test rules (`it.skip`, `.only`,
`expect(...).toBeTruthy`); persistence of reports with EV-01 / LK-05; consuming findings in
the verdict (EV-06/EV-07) and EV-03 independence; owner decision on severities; precision /
recall measurement on labelled real PRs (EP-07, RQ2); `radius rules` CLI integration;
rename-aware pairing for tests moved across files; lockfile parsing for npm / pnpm.
