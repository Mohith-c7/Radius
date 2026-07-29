"""Module resolver tests."""

from pathlib import Path

from radius_graph.infrastructure import ModuleResolver
from radius_parser.domain import (
    FileChecksum,
    ParsedSourceFile,
    SourceFile,
    SourceLanguage,
    SourcePath,
)


def test_module_resolver_resolves_python_dotted_and_relative_imports() -> None:
    resolver = ModuleResolver(
        (
            _parsed("src/core.py"),
            _parsed("src/package/__init__.py"),
            _parsed("src/package/service.py"),
        )
    )

    assert resolver.resolve("src/api.py", "src.core").value == "file:src/core.py"
    assert (
        resolver.resolve("src/package/service.py", ".").value
        == "file:src/package/__init__.py"
    )
    assert (
        resolver.resolve("src/package/service.py", ".service").value
        == "file:src/package/service.py"
    )


def test_module_resolver_resolves_javascript_relative_index_imports() -> None:
    resolver = ModuleResolver(
        (
            _parsed("web/core/index.ts"),
            _parsed("web/components/button.tsx"),
        )
    )

    assert (
        resolver.resolve("web/components/button.tsx", "../core").value
        == "file:web/core/index.ts"
    )


def test_module_resolver_ignores_external_modules() -> None:
    resolver = ModuleResolver((_parsed("src/core.py"),))

    assert resolver.resolve("src/core.py", "fastapi") is None


def _parsed(path: str) -> ParsedSourceFile:
    return ParsedSourceFile(
        source_file=SourceFile(
            path=SourcePath(path),
            language=SourceLanguage.PYTHON,
            checksum=FileChecksum("a" * 64),
            absolute_path=Path(path),
        )
    )
