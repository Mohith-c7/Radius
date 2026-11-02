"""Architecture rules: the domain layer imports only stdlib + itself.

Enforced two ways: this AST test (always runs under pytest) and the
import-linter contract in ``packages/intent/.importlinter`` (run by
``lint-imports``; see the package README).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
import radius_intent
from radius_intent.interfaces import (
    CriterionExtractor,
    IntentSourceFetcher,
    TestabilityRater,
)

PKG = Path(radius_intent.__file__).parent
DOMAIN = PKG / "domain"
ALLOWED_INTERNAL = "radius_intent.domain"


def imported_modules(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.append(("<relative>", node.lineno))
            else:
                found.append((node.module or "", node.lineno))
    return found


def is_allowed(module: str) -> bool:
    top = module.split(".")[0]
    if top == "radius_intent":
        return module == ALLOWED_INTERNAL or module.startswith(ALLOWED_INTERNAL + ".")
    return top in sys.stdlib_module_names or top == "__future__"


def test_domain_has_modules():
    assert len(list(DOMAIN.glob("*.py"))) >= 7


@pytest.mark.parametrize("path", sorted(DOMAIN.glob("*.py")), ids=lambda p: p.name)
def test_domain_imports_only_stdlib_and_domain(path):
    bad = [
        f"{path.name}:{line} imports {mod}"
        for mod, line in imported_modules(path)
        if not is_allowed(mod)
    ]
    assert not bad, bad


@pytest.mark.parametrize(
    ("module", "allowed"),
    [
        ("dataclasses", True),
        ("__future__", True),
        ("radius_intent.domain.enums", True),
        ("radius_intent.domain", True),
        ("radius_intent.interfaces", False),
        ("radius_intent.infrastructure.x", False),
        ("radius_intent_evil", False),
        ("sqlalchemy", False),
        ("httpx", False),
        ("<relative>", False),
    ],
)
def test_is_allowed_rule_itself(module, allowed):
    assert is_allowed(module) is allowed


def test_detector_catches_a_violation(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("import os\nfrom sqlalchemy import text\nfrom . import x\n")
    mods = [m for m, _ in imported_modules(bad)]
    assert [m for m in mods if not is_allowed(m)] == ["sqlalchemy", "<relative>"]


def test_ports_are_importable_protocols():
    for port in (IntentSourceFetcher, CriterionExtractor, TestabilityRater):
        assert getattr(port, "_is_protocol", False)
