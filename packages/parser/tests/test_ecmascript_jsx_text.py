"""A bare ``&`` in JSX text is valid JSX and must not fail the file (prod: data-panels.tsx).

tree-sitter's JSX grammar reports an ERROR node for ``Tests & CI``; before the
repair every dashboard component with such a heading was a parse failure, which
kept every analysis touching it at ``insufficient_evidence``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from radius_parser.application import ParserApplicationService
from radius_parser.domain import FileChecksum, SourceFile, SourceLanguage, SourcePath
from radius_parser.dto import ParseRepositoryCommand
from radius_parser.infrastructure import (
    FilesystemSourceDiscovery,
    TypeScriptParser,
    default_language_parser_registry,
)
from radius_parser.infrastructure.ecmascript_parser import parse_syntax_tree

# Shaped like apps/dashboard/components/data-panels.tsx: explicit ``.ts`` import,
# JSX generics-free hooks, entities, ``&&`` in expressions and bare ``&`` in text.
DATA_PANELS_LIKE = """\
"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { getAccountRows, type AccountRow } from "../lib/account-model.ts";
import { fetchAnalyses } from "../lib/api";

export function TestsPanel({ rows }: { rows: AccountRow[] }) {
  const [open, setOpen] = useState<boolean>(false);
  const visible = useMemo(() => rows.filter((row) => row.ok && !row.hidden), [rows]);
  return (
    <section>
      <h2>Branches & Verification Targets</h2>
      <a href="#tests">Tests & CI</a>
      <p>R&D &amp; QA &#123; ok</p>
      <th>Pull Request & IDs</th>
      {open && <span>Execution Trace && Failure Details</span>}
      <>Blast Radius & Dependency Slice</>
      <Link href="/help">Help & support</Link>
      <button onClick={() => setOpen(!open)}>{visible.length}</button>
    </section>
  );
}

export default function Page() {
  return <TestsPanel rows={getAccountRows(fetchAnalyses)} />;
}
"""


def _parse(tmp_path: Path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return TypeScriptParser().parse(
        SourceFile(
            path=SourcePath(name),
            language=SourceLanguage.TYPESCRIPT,
            checksum=FileChecksum("a" * 64),
            absolute_path=path,
        )
    )


def test_data_panels_like_tsx_parses_with_imports_symbols_and_exports(tmp_path: Path) -> None:
    parsed = _parse(tmp_path, "data-panels.tsx", DATA_PANELS_LIKE)

    assert [item.source for item in parsed.imports] == [
        "next/link",
        "react",
        "../lib/account-model.ts",
        "../lib/api",
    ]
    assert {symbol.name.value for symbol in parsed.symbols} == {"TestsPanel", "Page"}
    assert {item.name for item in parsed.exports} == {"TestsPanel", "Page"}


@pytest.mark.parametrize("suffix", [".tsx", ".jsx", ".js"])
@pytest.mark.parametrize(
    "snippet",
    [
        "const a = <p>Tests & CI</p>;",
        "const a = <p>A && B</p>;",
        "const a = <p>R&D</p>;",
        "const a = <p>a & {b} & c</p>;",
        "const a = <>x & y</>;",
    ],
)
def test_bare_ampersand_in_jsx_text_is_not_a_syntax_error(snippet: str, suffix: str) -> None:
    _, error = parse_syntax_tree(snippet, suffix)
    assert error is None


@pytest.mark.parametrize(
    "snippet",
    [
        "const a = b & ;",
        "const a = <p>x</p> & ;",
        "function f( { return <p>a & b</p> }",
        "const a = <p>unclosed & tag;",
    ],
)
def test_real_syntax_errors_still_fail(snippet: str) -> None:
    _, error = parse_syntax_tree(snippet, ".tsx")
    assert error is not None


def test_repair_keeps_locations(tmp_path: Path) -> None:
    text = 'const a = <p>A & B</p>;\nimport x from "./x";\n'
    parsed = _parse(tmp_path, "loc.tsx", text)
    assert [(item.source, item.location.start_line) for item in parsed.imports] == [("./x", 2)]


def test_repository_parse_has_no_failure_for_jsx_ampersand(tmp_path: Path) -> None:
    components = tmp_path / "apps" / "dashboard" / "components"
    components.mkdir(parents=True)
    (components / "data-panels.tsx").write_text(DATA_PANELS_LIKE, encoding="utf-8")
    (components / "broken.tsx").write_text("export function oops( {\n", encoding="utf-8")

    result = ParserApplicationService(
        FilesystemSourceDiscovery(), default_language_parser_registry()
    ).parse_repository_result(ParseRepositoryCommand(repository_path=tmp_path))

    assert result.parse_failures == ("apps/dashboard/components/broken.tsx",)
