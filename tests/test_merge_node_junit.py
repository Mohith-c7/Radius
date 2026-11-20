"""scripts/ci/merge_node_junit.py: Node JUnit reports gain repository-relative file paths."""

from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "merge_node_junit", ROOT / "scripts" / "ci" / "merge_node_junit.py"
)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

# What Node 22's built-in junit reporter writes: classname "test", no file attribute.
NODE_REPORT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
\t<testcase name="passes" time="0.004" classname="test"/>
\t<testsuite name="group">
\t\t<testcase name="fails" time="0.001" classname="test">
\t\t\t<failure type="testCodeFailure" message="boom">stack with source</failure>
\t\t</testcase>
\t</testsuite>
\t<testcase name="skips" time="0" classname="test">
\t\t<skipped type="skipped" message="later"/>
\t</testcase>
</testsuites>
"""


def test_cases_get_the_repository_relative_file_and_counts(tmp_path: Path) -> None:
    (tmp_path / "api.test.mjs.xml").write_text(NODE_REPORT, encoding="utf-8")
    (tmp_path / "b.test.mjs.xml").write_text(
        '<testsuites><testcase name="ok" classname="test"/></testsuites>', encoding="utf-8"
    )
    out = tmp_path / "out" / "junit.xml"

    assert module.main(
        ["--prefix", "apps/dashboard/tests/", "--out", str(out), *map(str, tmp_path.glob("*.xml"))]
    ) == 0

    root = ET.parse(out).getroot()
    assert (root.get("tests"), root.get("failures"), root.get("skipped")) == ("4", "1", "1")
    suites = root.findall("testsuite")
    assert [s.get("file") for s in suites] == [
        "apps/dashboard/tests/api.test.mjs",
        "apps/dashboard/tests/b.test.mjs",
    ]
    cases = root.findall("testsuite/testcase")
    assert [(c.get("file"), c.get("classname"), c.get("name")) for c in cases[:3]] == [
        ("apps/dashboard/tests/api.test.mjs", "apps/dashboard/tests/api.test.mjs", "passes"),
        ("apps/dashboard/tests/api.test.mjs", "apps/dashboard/tests/api.test.mjs", "fails"),
        ("apps/dashboard/tests/api.test.mjs", "apps/dashboard/tests/api.test.mjs", "skips"),
    ]
    failure = cases[1].find("failure")
    assert failure is not None and failure.text is None  # no stack text is copied
    assert cases[2].find("skipped") is not None


def test_no_reports_is_an_error(tmp_path: Path) -> None:
    assert module.main(["--prefix", "x", "--out", str(tmp_path / "o.xml"), str(tmp_path / "none.xml")]) == 1
