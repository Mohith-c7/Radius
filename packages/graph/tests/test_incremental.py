"""An incremental graph build equals a full build of the head, or refuses to run."""

from __future__ import annotations

import random
from pathlib import Path
from uuid import uuid4

import pytest
from radius_graph.application import GraphApplicationService
from radius_graph.domain import DependencyGraph
from radius_graph.dto import BuildGraphCommand
from radius_graph.incremental import (
    IncrementalUnavailable,
    ParsedBatch,
    build_fingerprint,
)
from radius_graph.infrastructure import InMemoryGraphStore
from radius_parser.application import ParserApplicationService
from radius_parser.dto import ParseRepositoryCommand
from radius_parser.infrastructure import (
    FilesystemSourceDiscovery,
    default_language_parser_registry,
)

pytest.importorskip("tree_sitter_typescript")

PARSER = ParserApplicationService(FilesystemSourceDiscovery(), default_language_parser_registry())

BASE_TREE = {
    "pyproject.toml": "[project]\nname = 'shop'\n",
    "README.md": "# shop\n",
    "packages/billing/src/billing/__init__.py": "from billing.tax import rate\n",
    "packages/billing/src/billing/tax.py": "def rate():\n    return 0.2\n",
    "packages/billing/src/billing/invoice.py": (
        "from . import tax\nfrom .tax import rate\nfrom billing import discount\n\n"
        "def total(x):\n    return x * (1 + rate())\n"
    ),
    "packages/billing/tests/test_invoice.py": (
        "from billing.invoice import total\n\ndef test_total():\n    assert total(1)\n"
    ),
    "shop/__init__.py": "",
    "shop/cart.py": "import shop.pricing\nfrom shop import pricing, coupons\n",
    "shop/pricing.py": "from .util import clamp\n\ndef price():\n    return clamp(1)\n",
    "shop/util.py": "def clamp(x):\n    return x\n",
    "shop/sub/__init__.py": "",
    "shop/sub/deep.py": "from .. import util\nfrom ..cart import *\n",
    "tests/test_cart.py": "from shop.cart import pricing\n\ndef test_cart():\n    assert pricing\n",
    "broken.py": "def broken(:\n",
    "web/tsconfig.json": (
        '{"extends": "./base", "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}'
    ),
    "web/base.json": '{"compilerOptions": {"strict": true}}',
    "web/src/lib/api.ts": "export function get() { return 1 }\n",
    "web/src/lib/format.ts": "import { get } from './api'\nexport const f = () => get()\n",
    "web/src/components/index.ts": "export * from './button'\n",
    "web/src/components/button.tsx": (
        "import { f } from '@/lib/format'\nexport const Button = () => f()\n"
    ),
    "web/src/app.ts": (
        "import { Button } from './components'\nimport { get } from './lib/api.js'\n"
        "import { widget } from '@/widgets/widget'\nexport const app = [Button, get, widget]\n"
    ),
    "web/tests/app.test.ts": "import { app } from '../src/app'\ntest('app', () => app)\n",
}


def _write(root: Path, files: dict[str, str | None]) -> set[str]:
    for path, content in files.items():
        target = root / path
        if content is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    return set(files)


def _full(root: Path) -> tuple[DependencyGraph, frozenset[str]]:
    store = InMemoryGraphStore()
    analysis_id = uuid4()
    parse_result = PARSER.parse_repository_result(ParseRepositoryCommand(repository_path=root))
    GraphApplicationService(store).build_graph(
        BuildGraphCommand(repository_id=uuid4(), analysis_id=analysis_id, parse_result=parse_result)
    )
    return store.get_snapshot(analysis_id).graph, frozenset(parse_result.parse_failures)


def _incremental(root: Path, base: DependencyGraph, changed: set[str]):
    def parse(files):
        result = PARSER.parse_source_files(root, list(files))
        return ParsedBatch(result.parsed_files, result.parse_failures)

    snapshot, build = GraphApplicationService().build_graph_incremental(
        repository_id=uuid4(),
        analysis_id=uuid4(),
        base=base,
        head_files=PARSER.discover_parseable(root),
        changed_paths=changed,
        parse=parse,
        repository_path=root,
        graph_version=build_fingerprint(),
    )
    return snapshot.graph, frozenset(build.parse_failures), build


def _assert_same(root: Path, base: DependencyGraph, changed: set[str]):
    full_graph, full_failures = _full(root)
    graph, failures, build = _incremental(root, base, changed)
    assert set(graph.nodes) == set(full_graph.nodes)
    assert set(graph.edges) == set(full_graph.edges)
    assert len(graph.nodes) == len(full_graph.nodes)
    assert failures == full_failures
    # Sorted like a stored snapshot, so consumers see the same order.
    assert list(graph.nodes) == sorted(graph.nodes, key=lambda node: node.id.value)
    return full_graph, build


STEPS: list[tuple[str, dict[str, str | None]]] = [
    ("modify a leaf module", {"shop/util.py": "def clamp(x):\n    return max(x, 0)\n"}),
    ("an import of a missing module starts to resolve", {"shop/coupons.py": "CODE = 1\n"}),
    (
        "a from-package import of a submodule starts to resolve",
        {"packages/billing/src/billing/discount.py": "def apply():\n    return 0\n"},
    ),
    ("delete a module others import", {"shop/pricing.py": None}),
    ("re-add it as a package", {"shop/pricing/__init__.py": "def price():\n    return 2\n"}),
    (
        "rename (delete + add) with importers rewritten",
        {
            "shop/util.py": None,
            "shop/helpers.py": "def clamp(x):\n    return x\n",
            "shop/sub/deep.py": "from .. import helpers\n",
        },
    ),
    ("a relative package import (no name in the text)", {"shop/sub/__init__.py": None}),
    ("TS: a wildcard-alias target appears", {"web/src/widgets/widget.ts": "export const widget = 1\n"}),
    ("TS: a directory index disappears", {"web/src/components/index.ts": None}),
    ("TS: the ESM .js import's source moves", {"web/src/lib/api.ts": None, "web/src/lib/api.tsx": "export function get() { return 2 }\n"}),
    ("a file stops parsing", {"shop/cart.py": "import shop.pricing\ndef (:\n"}),
    ("an unparseable file is fixed", {"broken.py": "def broken():\n    return 1\n"}),
    ("docs only", {"README.md": "# shop!\n", "docs/x.md": "x\n"}),
    ("a new test file", {"tests/test_helpers.py": "from shop.helpers import clamp\n"}),
]


def test_each_change_patches_to_the_full_build(tmp_path: Path) -> None:
    _write(tmp_path, BASE_TREE)
    base, _ = _full(tmp_path)
    for label, files in STEPS:
        changed = _write(tmp_path, files)
        try:
            base, _ = _assert_same(tmp_path, base, changed)
        except AssertionError as exc:  # pragma: no cover - names the failing step
            raise AssertionError(f"step {label!r}: {exc}") from exc


def test_unchanged_importers_are_re_resolved_only_when_needed(tmp_path: Path) -> None:
    _write(tmp_path, BASE_TREE)
    base, _ = _full(tmp_path)
    changed = _write(tmp_path, {"shop/util.py": "def clamp(x):\n    return -x\n"})
    _, build = _assert_same(tmp_path, base, changed)
    assert build.reresolved_importers == 0  # same file set: nothing to re-resolve
    assert build.reparsed_files == 2  # the change plus the file the base could not parse

    base, _ = _full(tmp_path)
    changed = _write(tmp_path, {"shop/coupons.py": "CODE = 1\n"})
    _, build = _assert_same(tmp_path, base, changed)
    assert 0 < build.reresolved_importers < 5  # shop/cart.py names "coupons"


def test_randomised_changes_always_match_the_full_build(tmp_path: Path) -> None:
    """Seeded random edits over modules that import each other in every style."""

    rng = random.Random(20261120)
    names = ["alpha", "beta", "gamma", "delta"]
    packages = ["pkg", "pkg/inner", "lib"]

    def module_text() -> str:
        lines = []
        for _ in range(rng.randint(0, 4)):
            name, package = rng.choice(names), rng.choice(packages)
            dotted = package.replace("/", ".")
            lines.append(
                rng.choice(
                    [
                        f"import {dotted}.{name}",
                        f"from {dotted} import {name}",
                        f"from . import {name}",
                        f"from .. import {name}",
                        f"from .{name} import thing",
                        f"from {dotted}.{name} import thing",
                    ]
                )
            )
        if rng.random() < 0.1:
            lines.append("def broken(:")
        return "\n".join(lines) + "\nthing = 1\n"

    def random_path() -> str:
        package = rng.choice(packages)
        leaf = rng.choice([*names, "__init__"])
        return f"{package}/{leaf}.py"

    _write(tmp_path, {random_path(): module_text() for _ in range(12)})
    base, _ = _full(tmp_path)
    for step in range(40):
        edits: dict[str, str | None] = {}
        for _ in range(rng.randint(1, 3)):
            path = random_path()
            edits[path] = None if rng.random() < 0.3 else module_text()
        changed = _write(tmp_path, edits)
        try:
            base, _ = _assert_same(tmp_path, base, changed)
        except AssertionError as exc:  # pragma: no cover - names the failing step
            raise AssertionError(f"random step {step} {sorted(edits)}: {exc}") from exc


@pytest.mark.parametrize(
    ("files", "reason"),
    [
        ({"web/tsconfig.json": '{"compilerOptions": {}}'}, "configuration changed"),
        ({"web/tsconfig.base.json": "{}"}, "configuration changed"),
        ({"web/base.json": "{}"}, "configuration changed"),  # read through ``extends``
    ],
)
def test_configuration_changes_fall_back(tmp_path: Path, files, reason) -> None:
    _write(tmp_path, BASE_TREE)
    base, _ = _full(tmp_path)
    changed = _write(tmp_path, files)
    with pytest.raises(IncrementalUnavailable, match=reason):
        _incremental(tmp_path, base, changed)


def test_unrelated_json_changes_do_not_force_a_full_build(tmp_path: Path) -> None:
    _write(tmp_path, BASE_TREE)
    base, _ = _full(tmp_path)
    changed = _write(tmp_path, {"package.json": '{"name": "x"}', "turbo.json": "{}"})
    _assert_same(tmp_path, base, changed)


def test_exact_ts_alias_with_a_changed_file_set_falls_back(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            **BASE_TREE,
            "web/tsconfig.json": '{"compilerOptions": {"baseUrl": ".", "paths": {"@ui": ["src/x"]}}}',
        },
    )
    base, _ = _full(tmp_path)
    changed = _write(tmp_path, {"web/src/x.ts": "export const x = 1\n"})
    with pytest.raises(IncrementalUnavailable, match="exact tsconfig"):
        _incremental(tmp_path, base, changed)
    # Editing an existing file keeps the file set, so the alias is harmless.
    changed = _write(tmp_path, {"web/src/lib/api.ts": "export function get() { return 3 }\n"})
    base, _ = _full(tmp_path)
    _write(tmp_path, {"web/src/lib/api.ts": "export function get() { return 4 }\n"})
    _assert_same(tmp_path, base, changed)


def test_a_base_that_does_not_match_the_head_tree_falls_back(tmp_path: Path) -> None:
    _write(tmp_path, BASE_TREE)
    base, _ = _full(tmp_path)
    (tmp_path / "shop/util.py").unlink()  # gone, but not reported as changed
    with pytest.raises(IncrementalUnavailable, match="files the head does not"):
        _incremental(tmp_path, base, {"README.md"})
    _write(tmp_path, {"shop/util.py": "def clamp(x):\n    return x\n", "extra.py": "x = 1\n"})
    with pytest.raises(IncrementalUnavailable, match="missing a parseable unchanged file"):
        _incremental(tmp_path, base, {"README.md"})


def test_fingerprint_is_stable_and_versioned() -> None:
    assert build_fingerprint() == build_fingerprint()
    assert build_fingerprint().startswith("v1+")
    assert len(build_fingerprint()) <= 50  # graph_snapshots.graph_version is String(50)


def test_source_reached_through_a_symlink_falls_back(tmp_path: Path) -> None:
    _write(tmp_path, BASE_TREE)
    try:
        (tmp_path / "shop" / "alias.py").symlink_to(tmp_path / "shop" / "util.py")
    except OSError:  # pragma: no cover - Windows without the symlink privilege
        pytest.skip("cannot create symlinks here")
    base, _ = _full(tmp_path)
    changed = _write(tmp_path, {"shop/util.py": "def clamp(x):\n    return 0\n"})
    with pytest.raises(IncrementalUnavailable, match="symlink"):
        _incremental(tmp_path, base, changed)
