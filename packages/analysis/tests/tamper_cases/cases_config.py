"""Table-driven cases for config and code rules T009-T011, T013-T017 (EV-02)."""

from textwrap import dedent as D

SRC = "def price(n):\n    return n * 2\n"
SRC_CHANGED = "def price(n):\n    return n * 3\n"
TEST = "from shop import price\n\n\ndef test_price():\n    assert price(2) == 4\n"
WF = D(
    """
    name: ci
    on: [pull_request]
    jobs:
      test:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - name: Test
            run: pytest -q
    """
)
PYPROJECT_COV = '[tool.coverage.report]\nfail_under = 90\n'


def c(id, rule, base, head, expect=(), **kw):
    return dict(id=id, rule=rule, base=base, head=head, expect=list(expect), **kw)


CASES = [
    # ------------------------------------------------------------------ T009
    c("t009-pragma", "T009", {"src/shop.py": SRC},
      {"src/shop.py": SRC + "\n\ndef rare():  # pragma: no cover\n    return 1\n"}, ["T009:pragma_no_cover"]),
    c("t009-fail-under-lowered", "T009", {"pyproject.toml": PYPROJECT_COV},
      {"pyproject.toml": PYPROJECT_COV.replace("90", "60")}, ["T009:fail_under_lowered"]),
    c("t009-fail-under-removed", "T009", {"pyproject.toml": PYPROJECT_COV + "x = 1\n"},
      {"pyproject.toml": "[tool.coverage.report]\nshow_missing = true\nx = 1\n"}, ["T009:fail_under_lowered"]),
    c("t009-cov-flag-lowered", "T009", {".github/workflows/ci.yml": WF.replace("pytest -q", "pytest --cov --cov-fail-under=90")},
      {".github/workflows/ci.yml": WF.replace("pytest -q", "pytest --cov --cov-fail-under=50")}, ["T009:fail_under_lowered"]),
    c("t009-omit-added", "T009", {".coveragerc": "[run]\nsource = src\n"},
      {".coveragerc": "[run]\nsource = src\nomit =\n    src/legacy/*\n"}, ["T009:omit_added"]),
    c("t009-toml-omit-added", "T009", {"pyproject.toml": "[tool.coverage.run]\nsource = ['src']\n"},
      {"pyproject.toml": "[tool.coverage.run]\nsource = ['src']\nomit = ['src/legacy/*']\n"}, ["T009:omit_added"]),
    c("t009-no-cov", "T009", {"tox.ini": "[testenv]\ncommands = pytest --cov\n"},
      {"tox.ini": "[testenv]\ncommands = pytest --no-cov\n"}, ["T009:coverage_disabled"]),
    c("t009-fail-under-raised", "T009", {"pyproject.toml": PYPROJECT_COV},
      {"pyproject.toml": PYPROJECT_COV.replace("90", "95")}, []),
    c("t009-omit-unchanged", "T009", {".coveragerc": "[run]\nomit =\n    src/legacy/*\n"},
      {".coveragerc": "[run]\nomit =\n    src/legacy/*\n# note\n"}, []),
    c("t009-pragma-line-unchanged", "T009", {"src/shop.py": SRC + "\n\ndef rare():  # pragma: no cover\n    return 1\n"},
      {"src/shop.py": SRC.replace("n * 2", "n * 2  ") + "\n\ndef rare():  # pragma: no cover\n    return 1\n"}, []),
    c("t009-omit-in-other-section", "T009", {"setup.cfg": "[metadata]\nname = x\n"},
      {"setup.cfg": "[metadata]\nname = x\nomit = y\n"}, []),
    # ------------------------------------------------------------------ T010
    c("t010-continue-on-error", "T010", {".github/workflows/ci.yml": WF},
      {".github/workflows/ci.yml": WF.replace("      - name: Test\n", "      - name: Test\n        continue-on-error: true\n")},
      ["T010:continue_on_error"]),
    c("t010-or-true", "T010", {".github/workflows/ci.yml": WF},
      {".github/workflows/ci.yml": WF.replace("pytest -q", "pytest -q || true")}, ["T010:or_true"]),
    c("t010-makefile-or-true", "T010", {"Makefile": "test:\n\tpytest -q\n"},
      {"Makefile": "test:\n\tpytest -q || true\n"}, ["T010:or_true"]),
    c("t010-if-false", "T010", {".github/workflows/ci.yml": WF},
      {".github/workflows/ci.yml": WF.replace("      - name: Test\n", "      - name: Test\n        if: false\n")},
      ["T010:step_disabled"]),
    c("t010-test-step-removed", "T010", {".github/workflows/ci.yml": WF},
      {".github/workflows/ci.yml": WF.replace("      - name: Test\n        run: pytest -q\n", "      - run: echo hi\n")},
      ["T010:test_step_removed"]),
    c("t010-workflow-deleted", "T010", {".github/workflows/ci.yml": WF}, {"README.md": "x\n"},
      ["T010:test_step_removed"]),
    c("t010-deselect", "T010", {"pytest.ini": "[pytest]\naddopts = -q\n"},
      {"pytest.ini": '[pytest]\naddopts = -q -k "not slow"\n'}, ["T010:tests_deselected"]),
    c("t010-strict-removed", "T010", {"pytest.ini": "[pytest]\naddopts = -q --strict-markers\n"},
      {"pytest.ini": "[pytest]\naddopts = -q\n"}, ["T010:pytest_flag_removed"]),
    c("t010-timeout", "T010", {".github/workflows/ci.yml": WF.replace("    runs-on", "    timeout-minutes: 10\n    runs-on")},
      {".github/workflows/ci.yml": WF.replace("    runs-on", "    timeout-minutes: 120\n    runs-on")}, ["T010:timeout_increased"]),
    c("t010-mypy-relaxed", "T010", {"mypy.ini": "[mypy]\nstrict = true\n"},
      {"mypy.ini": "[mypy]\nstrict = true\nignore_errors = true\n"}, ["T010:lint_weakened"]),
    c("t010-plugin-disabled", "T010", {"pytest.ini": "[pytest]\naddopts = -q\n"},
      {"pytest.ini": "[pytest]\naddopts = -q -p no:randomly\n"}, ["T010:plugin_disabled"]),
    c("t010-fail-fast", "T010", {"pytest.ini": "[pytest]\naddopts = -q\n"},
      {"pytest.ini": "[pytest]\naddopts = -q -x\n"}, ["T010:fail_fast_added"]),
    c("t010-unrelated-workflow-edit", "T010", {".github/workflows/ci.yml": WF},
      {".github/workflows/ci.yml": WF.replace("name: ci", "name: ci-main")}, []),
    c("t010-or-true-non-test", "T010", {"Makefile": "clean:\n\trm -rf build\n"},
      {"Makefile": "clean:\n\trm -rf build || true\n"}, []),
    c("t010-step-moved", "T010", {".github/workflows/ci.yml": WF},
      {".github/workflows/ci.yml": WF.replace("      - uses: actions/checkout@v4\n", "      - uses: actions/checkout@v4\n          - run: echo setup\n")}, []),
    c("t010-continue-on-error-false", "T010", {".github/workflows/ci.yml": WF},
      {".github/workflows/ci.yml": WF.replace("      - name: Test\n", "      - name: Test\n        continue-on-error: false\n")}, []),
    c("t010-strict-flag-kept", "T010", {"pytest.ini": "[pytest]\naddopts = -q --strict-markers\n"},
      {"pytest.ini": "[pytest]\naddopts = --strict-markers -q\n"}, []),
    # ------------------------------------------------------------------ T011
    c("t011-test-sleep", "T011", {"src/shop.py": SRC, "tests/test_shop.py": TEST},
      {"src/shop.py": SRC, "tests/test_shop.py": "import time\n" + TEST.replace("    assert", "    time.sleep(2)\n    assert")}, ["T011:test_sleep"]),
    c("t011-flaky-marker", "T011", {"src/shop.py": SRC, "tests/test_shop.py": TEST},
      {"src/shop.py": SRC, "tests/test_shop.py": TEST.replace("def test_price", "@pytest.mark.flaky(reruns=5)\ndef test_price")},
      ["T011:test_retry_marker"]),
    c("t011-ci-reruns", "T011", {"pytest.ini": "[pytest]\naddopts = -q\n"},
      {"pytest.ini": "[pytest]\naddopts = -q --reruns 3\n"}, ["T011:ci_retry"]),
    c("t011-action-retry", "T011", {".github/workflows/ci.yml": WF},
      {".github/workflows/ci.yml": WF.replace("        run: pytest -q", "        uses: nick-fields/retry@v3\n        with:\n          max_attempts: 3")},
      ["T010:test_step_removed", "T011:ci_retry"]),
    c("t011-sleep-in-source", "T011", {"src/shop.py": SRC},
      {"src/shop.py": "import time\n" + SRC.replace("    return", "    time.sleep(1)\n    return")}, []),
    c("t011-comment-mentions-flaky", "T011", {"src/shop.py": SRC, "tests/test_shop.py": TEST},
      {"src/shop.py": SRC, "tests/test_shop.py": TEST.replace("def test_price", "# this used to be flaky\ndef test_price")}, []),
    c("t011-skip-reason-flaky", "T011", {"src/shop.py": SRC, "tests/test_shop.py": TEST},
      {"src/shop.py": SRC, "tests/test_shop.py": "import pytest\n" + TEST.replace("def test_price", '@pytest.mark.skip(reason="flaky")\ndef test_price')},
      ["T002:skip"]),
    # ------------------------------------------------------------------ T013
    c("t013-noqa", "T013", {"src/shop.py": SRC},
      {"src/shop.py": SRC.replace("n * 2", "n * 2  # noqa: B008")}, ["T013:noqa"]),
    c("t013-type-ignore", "T013", {"src/shop.py": SRC},
      {"src/shop.py": SRC.replace("n * 2", "n * 2  # type: ignore")}, ["T013:type_ignore"]),
    c("t013-nosec", "T013", {"src/shop.py": SRC},
      {"src/shop.py": SRC.replace("n * 2", "n * 2  # nosec")}, ["T013:nosec"]),
    c("t013-pylint", "T013", {"src/shop.py": SRC},
      {"src/shop.py": SRC.replace("n * 2", "n * 2  # pylint: disable=invalid-name")}, ["T013:lint_disable"]),
    c("t013-ts-ignore", "T013", {"src/a.ts": "export const a = 1;\n"},
      {"src/a.ts": "// @ts-ignore\nexport const a: string = 1;\n"}, ["T013:ts_ignore"]),
    c("t013-bare-noqa", "T013", {"src/shop.py": SRC},
      {"src/shop.py": SRC.replace("n * 2", "n * 2  # noqa")}, ["T013:noqa"]),
    c("t013-noqa-f401", "T013", {"src/shop.py": SRC},
      {"src/shop.py": "import os  # noqa: F401\n" + SRC}, []),
    c("t013-type-ignore-import", "T013", {"src/shop.py": SRC},
      {"src/shop.py": "import foo  # type: ignore[import-untyped]\n" + SRC}, []),
    c("t013-suppression-preexisting", "T013", {"src/shop.py": SRC.replace("n * 2", "n * 2  # nosec")},
      {"src/shop.py": SRC.replace("n * 2", "n * 2  # nosec") + "\n\ndef other():\n    return 1\n"}, []),
    c("t013-below-threshold", "T013", {"src/shop.py": SRC},
      {"src/shop.py": SRC.replace("n * 2", "n * 2  # type: ignore")}, [],
      config={"params": {"min_added_suppressions": 2}}),
    c("t013-at-threshold", "T013", {"src/shop.py": SRC},
      {"src/shop.py": "def price(n):\n    x = n  # type: ignore\n    return x * 2  # nosec\n"},
      ["T013:nosec", "T013:type_ignore"], config={"params": {"min_added_suppressions": 2}}),
    c("t013-many-noqa-in-one-file-collapse", "T013", {"src/shop.py": SRC},
      {"src/shop.py": "def price(n):\n    a = n  # noqa: B008\n    b = a  # noqa: B009\n    return b * 2  # noqa: B010\n"},
      ["T013:noqa"]),
    c("t013-noqa-in-two-files-stay-two", "T013", {"src/shop.py": SRC, "src/cart.py": SRC},
      {"src/shop.py": SRC.replace("n * 2", "n * 2  # noqa: B008"),
       "src/cart.py": SRC.replace("n * 2", "n * 2  # noqa: B008")},
      ["T013:noqa", "T013:noqa"]),
    c("t013-mixed-kinds-in-one-file-one-per-kind", "T013", {"src/shop.py": SRC},
      {"src/shop.py": "def price(n):\n    a = n  # noqa: B008\n    b = a  # noqa: B009\n    return b * 2  # nosec\n"},
      ["T013:noqa", "T013:nosec"]),
    # ------------------------------------------------------------------ T014
    c("t014-body-stubbed", "T014", {"src/shop.py": SRC},
      {"src/shop.py": "def price(n):\n    raise NotImplementedError\n"}, ["T014:body_stubbed"]),
    c("t014-body-pass", "T014", {"src/shop.py": SRC}, {"src/shop.py": "def price(n):\n    pass\n"}, ["T014:body_stubbed"]),
    c("t014-return-none", "T014", {"src/shop.py": SRC}, {"src/shop.py": "def price(n):\n    return None\n"}, ["T014:body_stubbed"]),
    c("t014-new-stub", "T014", {"src/shop.py": SRC},
      {"src/shop.py": SRC + "\n\ndef later(n):\n    raise NotImplementedError\n"}, ["T014:new_stub"]),
    c("t014-abstract", "T014", {"src/shop.py": "from abc import ABC, abstractmethod\n\n\nclass A(ABC):\n    @abstractmethod\n    def f(self):\n        return 1\n"},
      {"src/shop.py": "from abc import ABC, abstractmethod\n\n\nclass A(ABC):\n    @abstractmethod\n    def f(self):\n        raise NotImplementedError\n"}, []),
    c("t014-stub-unchanged", "T014", {"src/shop.py": SRC + "\n\ndef later(n):\n    pass\n"},
      {"src/shop.py": SRC.replace("n * 2", "n * 3") + "\n\ndef later(n):\n    pass\n"}, []),
    c("t014-new-real-body", "T014", {"src/shop.py": SRC}, {"src/shop.py": SRC + "\n\ndef more(n):\n    return n + 1\n"}, []),
    c("t014-annotated-none-return", "T014", {"src/shop.py": "def hook(n) -> None:\n    print(n)\n"},
      {"src/shop.py": "def hook(n) -> None:\n    return None\n"}, []),
    c("t014-protocol", "T014", {"src/shop.py": "from typing import Protocol\n\n\nclass P(Protocol):\n    def f(self) -> int: ...\n"},
      {"src/shop.py": "from typing import Protocol\n\n\nclass P(Protocol):\n    def f(self) -> int: ...\n    def g(self) -> int: ...\n"}, []),
    # ------------------------------------------------------------------ T015
    c("t015-verify-false", "T015", {"src/shop.py": "import requests\n\n\ndef get(u):\n    return requests.get(u)\n"},
      {"src/shop.py": "import requests\n\n\ndef get(u):\n    return requests.get(u, verify=False)\n"}, ["T015:tls_verify_disabled"]),
    c("t015-secret", "T015", {"src/shop.py": SRC},
      {"src/shop.py": SRC + '\nAPI_KEY = "sk_live_9f8a7b6c5d4e"\n'}, ["T015:hardcoded_secret"]),
    c("t015-env-var-name", "T015", {"src/shop.py": SRC},
      {"src/shop.py": SRC + '\nGEMINI_API_KEY_ENV = "GEMINI_API_KEY"\n'}, []),
    c("t015-sql-fstring", "T015", {"src/shop.py": "def q(db, n):\n    return db.execute('select 1')\n"},
      {"src/shop.py": "def q(db, n):\n    return db.execute(f'select {n}')\n"}, ["T015:sql_interpolation"]),
    c("t015-verify-true", "T015", {"src/shop.py": "import requests\n\n\ndef get(u):\n    return requests.get(u)\n"},
      {"src/shop.py": "import requests\n\n\ndef get(u):\n    return requests.get(u, verify=True)\n"}, []),
    c("t015-in-test-file", "T015", {"src/shop.py": SRC, "tests/test_shop.py": TEST},
      {"src/shop.py": SRC, "tests/test_shop.py": TEST + '\n\ndef test_t():\n    token = "abcdefghijkl"\n    assert token\n'}, []),
    c("t015-placeholder-secret", "T015", {"src/shop.py": SRC},
      {"src/shop.py": SRC + '\nPASSWORD = "changeme-please"\n'}, []),
    c("t015-parametrized-sql", "T015", {"src/shop.py": "def q(db, n):\n    return db.execute('select 1')\n"},
      {"src/shop.py": "def q(db, n):\n    return db.execute('select ?', (n,))\n"}, []),
    # ------------------------------------------------------------------ T016
    c("t016-print", "T016", {"src/shop.py": SRC},
      {"src/shop.py": SRC.replace("    return", "    print(n)\n    return")}, ["T016:debug_call"]),
    c("t016-breakpoint", "T016", {"src/shop.py": SRC},
      {"src/shop.py": SRC.replace("    return", "    breakpoint()\n    return")}, ["T016:debug_call"]),
    c("t016-pdb", "T016", {"src/shop.py": SRC},
      {"src/shop.py": "import pdb\n" + SRC.replace("    return", "    pdb.set_trace()\n    return")}, ["T016:debug_call"]),
    c("t016-main-block", "T016", {"src/shop.py": SRC},
      {"src/shop.py": SRC + '\n\nif __name__ == "__main__":\n    print(price(2))\n'}, []),
    c("t016-cli-file", "T016", {"src/cli.py": "def run():\n    return 1\n"},
      {"src/cli.py": "def run():\n    print('hi')\n    return 1\n"}, []),
    c("t016-logger", "T016", {"src/shop.py": SRC},
      {"src/shop.py": "import logging\n\nlog = logging.getLogger(__name__)\n" + SRC.replace("    return", "    log.info(n)\n    return")}, []),
    c("t016-print-in-test", "T016", {"src/shop.py": SRC, "tests/test_shop.py": TEST},
      {"src/shop.py": SRC, "tests/test_shop.py": TEST.replace("    assert", "    print('x')\n    assert")}, []),
    # ------------------------------------------------------------------ T017
    c("t017-autouse-patch", "T017",
      {"src/shop.py": SRC, "tests/test_shop.py": TEST, "tests/conftest.py": "import pytest\n"},
      {"src/shop.py": SRC, "tests/test_shop.py": TEST, "tests/conftest.py": D(
          """
          import pytest


          @pytest.fixture(autouse=True)
          def _fast(monkeypatch):
              monkeypatch.setattr("shop.price", lambda n: 4)
          """)},
      ["T017:autouse_patch"]),
    c("t017-collect-ignore", "T017",
      {"src/shop.py": SRC, "tests/test_shop.py": TEST, "conftest.py": "import pytest\n"},
      {"src/shop.py": SRC, "tests/test_shop.py": TEST, "conftest.py": 'import pytest\n\ncollect_ignore = ["tests/test_shop.py"]\n'},
      ["T017:collection_hook"]),
    c("t017-hook-skips", "T017",
      {"src/shop.py": SRC, "tests/test_shop.py": TEST, "conftest.py": "import pytest\n"},
      {"src/shop.py": SRC, "tests/test_shop.py": TEST, "conftest.py": D(
          """
          import pytest


          def pytest_collection_modifyitems(items):
              for item in items:
                  item.add_marker(pytest.mark.skip)
          """)},
      ["T017:collection_hook"]),
    c("t017-conftest-with-source", "T017",
      {"src/shop.py": SRC, "tests/test_shop.py": TEST, "tests/conftest.py": "import pytest\n"},
      {"src/shop.py": SRC_CHANGED, "tests/test_shop.py": TEST, "tests/conftest.py": "import pytest\n\nDEFAULT = 3\n"},
      ["T017:conftest_changed_with_source"]),
    c("t017-autouse-env-only", "T017",
      {"src/shop.py": SRC, "tests/test_shop.py": TEST, "tests/conftest.py": "import pytest\n"},
      {"src/shop.py": SRC, "tests/test_shop.py": TEST, "tests/conftest.py": D(
          """
          import os
          import pytest


          @pytest.fixture(autouse=True)
          def _env():
              os.environ["TZ"] = "UTC"
          """)}, []),
    c("t017-non-autouse-patch", "T017",
      {"src/shop.py": SRC, "tests/test_shop.py": TEST, "tests/conftest.py": "import pytest\n"},
      {"src/shop.py": SRC, "tests/test_shop.py": TEST, "tests/conftest.py": D(
          """
          import pytest


          @pytest.fixture
          def fast(monkeypatch):
              monkeypatch.setattr("shop.price", lambda n: 4)
          """)}, []),
    c("t017-conftest-comment-only", "T017",
      {"src/shop.py": SRC, "tests/test_shop.py": TEST, "tests/conftest.py": "import pytest\n"},
      {"src/shop.py": SRC_CHANGED, "tests/test_shop.py": TEST, "tests/conftest.py": "import pytest\n# note\n"}, []),
]
