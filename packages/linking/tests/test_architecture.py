"""Architecture rules: pure domain, offline deterministic linkers, no tenant data.

Enforced by this AST test (always runs) and by ``packages/linking/.importlinter``
(``lint-imports``).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import radius_linking
from radius_linking.domain import COMBINED, LinkerPort, Reranker

PKG = Path(radius_linking.__file__).parent
STDLIB = set(sys.stdlib_module_names)


def imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            out.append("<relative>" if node.level else (node.module or ""))
    return out


def test_domain_imports_only_stdlib_and_itself():
    for path in (PKG / "domain").glob("*.py"):
        for mod in imports(path):
            root = mod.split(".")[0]
            assert (
                root in STDLIB or root == "radius_linking"
            ), f"{path.name} imports {mod}"
            if root == "radius_linking":
                assert mod.startswith(
                    "radius_linking.domain"
                ), f"{path.name} imports {mod}"


def test_application_depends_on_domain_only():
    for path in (PKG / "application").glob("*.py"):
        for mod in imports(path):
            root = mod.split(".")[0]
            assert root in STDLIB or mod.startswith(
                ("radius_linking.domain", "radius_linking.application")
            ), f"{path.name} imports {mod}"


def test_deterministic_linkers_have_no_network_db_llm_or_clock_imports():
    banned = {
        "httpx",
        "requests",
        "sqlalchemy",
        "anthropic",
        "openai",
        "socket",
        "random",
        "time",
        "datetime",
        "radius_intent",
        "radius_shared",
        "urllib",
        "subprocess",
    }
    for path in (PKG / "infrastructure" / "linkers").glob("*.py"):
        assert not {m.split(".")[0] for m in imports(path)} & banned, path.name


def test_no_tenant_or_organization_identifiers_in_domain_and_linkers():
    for folder in ("domain", "application", "infrastructure/linkers"):
        for path in (PKG / folder).glob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            assert "organization_id" not in text and "tenant" not in text, path.name


def test_ports_exist_and_combined_name_is_stable():
    assert COMBINED == "combined"
    assert hasattr(LinkerPort, "link") and hasattr(Reranker, "rerank")


def test_llm_reranker_module_has_no_sdk_import():
    for mod in imports(PKG / "infrastructure" / "rerank" / "llm.py"):
        assert mod.split(".")[0] not in {
            "anthropic",
            "openai",
            "httpx",
            "requests",
            "google",
        }
