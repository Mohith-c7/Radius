"""TypeScript path alias resolution (tsconfig ``paths`` / ``baseUrl``)."""

from pathlib import Path

from radius_graph.infrastructure.module_resolver import (
    ModuleResolver,
    load_tsconfig_aliases,
)
from radius_parser.domain import (
    FileChecksum,
    ParsedSourceFile,
    SourceFile,
    SourceLanguage,
    SourcePath,
)


def _parsed(path: str) -> ParsedSourceFile:
    return ParsedSourceFile(
        source_file=SourceFile(
            path=SourcePath(path),
            language=SourceLanguage.TYPESCRIPT,
            checksum=FileChecksum("0" * 64),
            absolute_path=Path(path),
        )
    )


FILES = (_parsed("src/lib/math.ts"), _parsed("src/app/calc.ts"))


def test_paths_wildcard_alias_resolves(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").write_text(
        '{"compilerOptions": {"paths": {"@/*": ["src/*"]}}}', encoding="utf-8"
    )

    resolver = ModuleResolver(FILES, path_aliases=load_tsconfig_aliases(tmp_path))

    assert resolver.resolve("src/app/calc.ts", "@/lib/math").value == "file:src/lib/math.ts"
    assert resolver.resolve("src/app/calc.ts", "@/lib/missing") is None


def test_base_url_only_import_resolves(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").write_text(
        '{"compilerOptions": {"baseUrl": "src"}}', encoding="utf-8"
    )

    resolver = ModuleResolver(FILES, path_aliases=load_tsconfig_aliases(tmp_path))

    assert resolver.resolve("src/app/calc.ts", "lib/math").value == "file:src/lib/math.ts"


def test_jsonc_comments_trailing_commas_and_nested_config(tmp_path: Path) -> None:
    app = tmp_path / "apps" / "web"
    app.mkdir(parents=True)
    (app / "tsconfig.json").write_text(
        """{
  // editor comment
  "compilerOptions": {
    /* block comment with "quotes" */
    "baseUrl": ".",
    "paths": { "~/*": ["./src/*",], },
  },
}""",
        encoding="utf-8",
    )

    aliases = load_tsconfig_aliases(tmp_path)

    assert aliases["~/*"] == ("apps/web/src/*",)


def test_targets_escaping_repository_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").write_text(
        '{"compilerOptions": {"paths": {"x/*": ["../../etc/*"]}}}', encoding="utf-8"
    )

    assert "x/*" not in load_tsconfig_aliases(tmp_path)


def test_malformed_tsconfig_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").write_text("{not json", encoding="utf-8")

    assert load_tsconfig_aliases(tmp_path) == {}
