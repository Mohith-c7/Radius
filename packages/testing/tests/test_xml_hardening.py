"""A-17: report XML is parsed by defusedxml only; no stdlib fallback."""

from __future__ import annotations

import importlib
import os
import sys
from uuid import uuid4

import pytest
from radius_shared.errors import ValidationError
from radius_testing.infrastructure import junit_parser, result_matching
from radius_testing.infrastructure.sandbox_runner import _private_scratch_root

BILLION_LAUGHS = (
    '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
    '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
    '<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>'
    '<testsuite tests="1"><testcase classname="a" name="&lol3;"/></testsuite>'
)


def test_entity_declarations_are_refused_by_the_junit_parser() -> None:
    with pytest.raises(ValidationError):
        junit_parser.JUnitReportParser().parse(BILLION_LAUGHS, uuid4())


def test_entity_declarations_yield_no_cases_in_result_matching() -> None:
    assert result_matching._xml_cases(BILLION_LAUGHS) == ()


@pytest.mark.parametrize("module", ["radius_testing.infrastructure.junit_parser", "radius_testing.infrastructure.result_matching"])
def test_missing_defusedxml_fails_loudly_instead_of_falling_back(monkeypatch, module) -> None:
    for name in [n for n in sys.modules if n.startswith("defusedxml")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "defusedxml", None)
    monkeypatch.setitem(sys.modules, "defusedxml.ElementTree", None)
    saved = sys.modules.pop(module)
    try:
        with pytest.raises(ImportError):
            importlib.import_module(module)
    finally:
        sys.modules[module] = saved


def test_no_stdlib_xml_parser_is_imported_by_the_parsers() -> None:
    for module in (junit_parser, result_matching):
        source = open(module.__file__, encoding="utf-8").read()
        assert "xml.etree" not in source


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_sandbox_scratch_root_is_owner_only() -> None:
    root = _private_scratch_root()
    try:
        assert root.stat().st_mode & 0o777 == 0o700
    finally:
        root.rmdir()
