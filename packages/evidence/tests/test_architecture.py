"""Architecture rules: pure domain and application, docstring-only inits.

Also enforced by ``packages/evidence/.importlinter`` (``lint-imports``).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import radius_evidence

PKG = Path(radius_evidence.__file__).parent
STDLIB = set(sys.stdlib_module_names)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            out.append("<relative>" if node.level else (node.module or ""))
    return out


def test_domain_and_application_import_only_stdlib_and_domain() -> None:
    for layer in ("domain", "application"):
        for path in (PKG / layer).glob("*.py"):
            for mod in _imports(path):
                root = mod.split(".")[0]
                assert (
                    root in STDLIB or root == "radius_evidence"
                ), f"{layer}/{path.name} imports {mod}"
                if root == "radius_evidence":
                    assert mod.startswith(
                        ("radius_evidence.domain", "radius_evidence.application")
                    ), f"{layer}/{path.name} imports {mod}"


def test_domain_never_imports_application() -> None:
    for path in (PKG / "domain").glob("*.py"):
        for mod in _imports(path):
            assert not mod.startswith("radius_evidence.application"), path.name


def test_init_files_are_docstring_only() -> None:
    for path in PKG.rglob("__init__.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert len(tree.body) == 1, f"{path} must contain only a docstring"
        node = tree.body[0]
        assert isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
