"""Test discovery reads frameworks from imports and targets from the graph.

Shapes come from production analyses of this repository: node:test files in
``apps/dashboard/tests`` were ``framework=unknown`` with a name-based target
(``apps/dashboard/tests/account-model.mjs``) that does not exist, while the
test really imports ``"../lib/account-model.ts"``. Helper modules under
``tests/`` and ``scripts/load_test.py`` were discovered as tests although CI
running them reports nothing.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from radius_testing.application import TestingApplicationService
from radius_testing.domain import TestCase, TestFramework, TestName, TestPath, TestType
from radius_testing.domain.value_objects import SourcePath
from radius_testing.dto import DiscoverTestsCommand
from radius_testing.infrastructure import (
    ConventionalTestDiscoverer,
    InMemoryTestStore,
    PathBasedTestSelector,
    StaticTestCommandPlanner,
)
from radius_testing.infrastructure.test_targets import (
    refine_test_targets,
    subject_name_of_test,
    target_from_imports,
)

NODE_TEST = """\
import assert from "node:assert/strict";
import test from "node:test";

import { profileRows } from "../lib/account-model.ts";

test("profile rows come from the signed-in user", () => {
  assert.equal(profileRows({ name: "A" }).length, 1);
});
"""


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _by_path(tests: tuple[TestCase, ...]) -> dict[str, TestCase]:
    return {test.path.value: test for test in tests}


def test_framework_comes_from_the_runner_the_file_imports(tmp_path: Path) -> None:
    _write(tmp_path, "apps/dashboard/tests/account-model.test.mjs", NODE_TEST)
    _write(
        tmp_path,
        "web/src/calc.test.ts",
        'import { expect, it } from "vitest";\nit("adds", () => expect(1).toBe(1));\n',
    )
    _write(
        tmp_path,
        "e2e/tests/dashboard.spec.mjs",
        'import { test } from "@playwright/test";\ntest("home", async () => {});\n',
    )
    _write(
        tmp_path,
        "web/src/legacy.test.js",
        "const { test } = require('node:test');\ntest('x', () => {});\n",
    )
    _write(tmp_path, "web/src/plain.test.ts", "test('suffix fallback', () => {});\n")
    _write(tmp_path, "apps/api/tests/test_routes.py", "def test_ok():\n    assert True\n")

    tests = _by_path(ConventionalTestDiscoverer().discover(tmp_path))

    assert tests["apps/dashboard/tests/account-model.test.mjs"].framework == TestFramework.NODE_TEST
    assert tests["web/src/calc.test.ts"].framework == TestFramework.VITEST
    assert tests["e2e/tests/dashboard.spec.mjs"].framework == TestFramework.PLAYWRIGHT
    assert tests["e2e/tests/dashboard.spec.mjs"].test_type == TestType.E2E
    assert tests["web/src/legacy.test.js"].framework == TestFramework.NODE_TEST
    assert tests["web/src/plain.test.ts"].framework == TestFramework.VITEST
    assert tests["apps/api/tests/test_routes.py"].framework == TestFramework.PYTEST


def test_files_that_define_no_tests_are_not_discovered(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/load_test.py", "def main():\n    print('load')\n")
    _write(tmp_path, "packages/linking/tests/linking_helpers.py", "def make_link():\n    return 1\n")
    _write(
        tmp_path,
        "packages/linking/tests/test_links.py",
        "class TestLinks:\n    def test_one(self):\n        assert True\n",
    )
    _write(tmp_path, "packages/x/tests/test_async.py", "async def test_runs():\n    pass\n")
    _write(tmp_path, "apps/dashboard/tests/helpers.mjs", "export const x = 1;\n")
    _write(tmp_path, "apps/dashboard/tests/api.test.mjs", NODE_TEST)

    paths = [test.path.value for test in ConventionalTestDiscoverer().discover(tmp_path)]

    assert paths == [
        "apps/dashboard/tests/api.test.mjs",
        "packages/linking/tests/test_links.py",
        "packages/x/tests/test_async.py",
    ]


def test_subject_name_strips_test_markers() -> None:
    assert subject_name_of_test("apps/dashboard/tests/account-model.test.mjs") == "account-model"
    assert subject_name_of_test("web/src/calc.spec.tsx") == "calc"
    assert subject_name_of_test("apps/api/tests/test_analyses.py") == "analyses"
    assert subject_name_of_test("pkg/core_test.py") == "core"


def _case(path: str, target: str | None = None) -> TestCase:
    return TestCase(
        id=uuid4(),
        name=TestName(Path(path).stem),
        path=TestPath(path),
        framework=TestFramework.UNKNOWN,
        test_type=TestType.UNIT,
        target_path=SourcePath(target) if target else None,
    )


def test_target_comes_from_the_test_imports_not_its_file_name() -> None:
    tests = (
        _case("apps/dashboard/tests/account-model.test.mjs", "apps/dashboard/tests/account-model.mjs"),
        _case("apps/api/tests/test_analyses.py", "apps/api/analyses.py"),
        _case("apps/dashboard/tests/intent-api.test.mjs", "apps/dashboard/tests/intent-api.mjs"),
        _case("apps/dashboard/tests/verdict-refresh.test.mjs", "apps/dashboard/tests/verdict-refresh.mjs"),
        _case("pkg/tests/test_core.py", "pkg/core.py"),
        _case("pkg/tests/test_nothing.py", "pkg/nothing.py"),
    )
    imports = {
        "apps/dashboard/tests/account-model.test.mjs": (
            "apps/dashboard/lib/account-model.ts",
            "apps/dashboard/lib/api.ts",
        ),
        "apps/api/tests/test_analyses.py": (
            "apps/api/src/radius_api/main.py",
            "apps/api/src/radius_api/routes/analyses.py",
            "pkg/tests/test_core.py",
        ),
        "apps/dashboard/tests/intent-api.test.mjs": (
            "apps/dashboard/lib/api.ts",
            "apps/dashboard/lib/intent-model.ts",
        ),
        "apps/dashboard/tests/verdict-refresh.test.mjs": ("apps/dashboard/lib/refresh/index.ts",),
        "pkg/tests/test_core.py": ("pkg/util.py", "pkg/other.py"),
    }
    files = frozenset({"pkg/core.py", *(p for v in imports.values() for p in v)})

    refined = _by_path(refine_test_targets(tests, imports, files))

    def target(path: str) -> str | None:
        value = refined[path].target_path
        return value.value if value is not None else None

    assert target("apps/dashboard/tests/account-model.test.mjs") == "apps/dashboard/lib/account-model.ts"
    assert target("apps/api/tests/test_analyses.py") == "apps/api/src/radius_api/routes/analyses.py"
    # Several unrelated imports and no name match: nothing is guessed.
    assert target("apps/dashboard/tests/intent-api.test.mjs") is None
    # The only import is the target even when names differ.
    assert target("apps/dashboard/tests/verdict-refresh.test.mjs") == "apps/dashboard/lib/refresh/index.ts"
    # The name-based guess survives only when that file exists.
    assert target("pkg/tests/test_core.py") == "pkg/core.py"
    assert target("pkg/tests/test_nothing.py") is None
    # Import-derived targets are marked so name-convention selection skips them.
    assert target_from_imports(refined["apps/dashboard/tests/account-model.test.mjs"])
    assert not target_from_imports(refined["pkg/tests/test_core.py"])


def test_convention_selection_ignores_import_derived_targets() -> None:
    """The graph already follows imports; re-adding them by "target" defeats symbol pruning."""

    imported = _case("tests/test_b.py", "src/b.py")
    (refined,) = refine_test_targets((imported,), {"tests/test_b.py": ("src/lib.py",)}, frozenset({"src/lib.py"}))
    named = _case("tests/test_lib.py", "src/lib.py")

    selection = PathBasedTestSelector().select(
        uuid4(), (refined, named), changed_file_paths=("src/lib.py",)
    )

    assert refined.target_path is not None and refined.target_path.value == "src/lib.py"
    assert [item.test_case.path.value for item in selection.selected_tests] == ["tests/test_lib.py"]
    assert PathBasedTestSelector().conventional_matches("src/lib.py", (refined, named)) == (
        "tests/test_lib.py",
    )


def test_discovery_persists_import_based_targets(tmp_path: Path) -> None:
    _write(tmp_path, "apps/dashboard/tests/account-model.test.mjs", NODE_TEST)
    _write(tmp_path, "apps/dashboard/lib/account-model.ts", "export const profileRows = () => [];\n")
    store = InMemoryTestStore()
    service = TestingApplicationService(
        discoverer=ConventionalTestDiscoverer(),
        selector=PathBasedTestSelector(),
        store=store,
        planner=StaticTestCommandPlanner(),
    )

    discovered = service.discover_test_cases(
        DiscoverTestsCommand(
            tmp_path,
            file_imports={
                "apps/dashboard/tests/account-model.test.mjs": (
                    "apps/dashboard/lib/account-model.ts",
                )
            },
            repository_files=frozenset({"apps/dashboard/lib/account-model.ts"}),
        )
    )

    (test,) = discovered
    assert test.target_path is not None
    assert test.target_path.value == "apps/dashboard/lib/account-model.ts"
    assert test.framework == TestFramework.NODE_TEST
    (stored,) = store.list_test_cases()
    assert stored.target_path == test.target_path
