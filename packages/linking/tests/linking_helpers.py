"""Shared builders for the linking tests."""

from __future__ import annotations

from radius_linking.domain import CriterionInput, SymbolDoc


def sym(
    path: str = "src/pricing.py",
    name: str = "apply_discount",
    *,
    kind: str = "function",
    change: str = "modified_body",
    behavioral: bool = True,
    signature: str = "",
    docstring: str = "",
    comments: tuple[str, ...] = (),
    identifiers: tuple[str, ...] = (),
    literals: tuple[str, ...] = (),
    decorators: tuple[str, ...] = (),
    is_test: bool = False,
    language: str = "python",
) -> SymbolDoc:
    return SymbolDoc(
        symbol_id=f"{language}:{path}::{name}#{kind}@abc",
        path=path,
        qualified_name=name,
        kind=kind,
        language=language,
        change_kind=change,
        is_behavioral=behavioral,
        signature=signature,
        docstring=docstring,
        comments=comments,
        identifiers=identifiers,
        literals=literals,
        decorators=decorators,
        is_test=is_test,
    )


def crit(
    text: str,
    cid: str = "C1",
    *,
    paths: tuple[str, ...] = (),
    tests: tuple[str, ...] = (),
    rationale: str | None = None,
) -> CriterionInput:
    return CriterionInput(cid, text, rationale, paths, tests)


def by_symbol(links):
    return {x.symbol_id: x for x in links}
