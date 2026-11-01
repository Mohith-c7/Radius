"""Tree-sitter based JS/TS import extraction."""

from radius_parser.infrastructure.ecmascript_parser import TypeScriptLikeParser

SOURCE = """\
import {
  alpha,
  beta,
} from "./multi";
import type { Shape } from "./types";
export * from "./reexport";
export { gamma } from "./named-reexport";
import legacy = require("./legacy");
const lazy = await import("./dynamic");
const cjs = require('./cjs');
// import { fake } from "./commented";
const text = "import x from './in-string'";
const tpl = `${require("./template-part")}`;
const dyn = import(`./templated/${name}`);
"""


def _sources(source: str, suffix: str = ".ts") -> list[str]:
    return [item.source for item in TypeScriptLikeParser._imports(source, suffix)]


def test_tree_sitter_extracts_static_dynamic_and_reexports() -> None:
    sources = _sources(SOURCE)

    for expected in (
        "./multi",
        "./types",
        "./reexport",
        "./named-reexport",
        "./legacy",
        "./dynamic",
        "./cjs",
        "./template-part",
    ):
        assert expected in sources


def test_comments_strings_and_template_specifiers_are_not_imports() -> None:
    sources = _sources(SOURCE)

    assert "./commented" not in sources
    assert "./in-string" not in sources
    assert not any(item.startswith("./templated") for item in sources)


def test_multiline_import_line_is_the_specifier_line() -> None:
    refs = TypeScriptLikeParser._imports(SOURCE, ".ts")
    by_source = {ref.source: ref.location.start_line for ref in refs}

    assert by_source["./multi"] == 4


def test_tsx_grammar_handles_jsx() -> None:
    source = 'import React from "react";\nexport const A = () => <div>{"import x from \'./no\'"}</div>;\n'

    assert _sources(source, ".tsx") == ["react"]


def test_falls_back_to_regex_when_tree_sitter_fails(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("grammar unavailable")

    monkeypatch.setattr(TypeScriptLikeParser, "_tree_sitter_imports", staticmethod(boom))

    assert "./multi" in _sources(SOURCE)
