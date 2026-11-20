"""Attribution of real CI report shapes (pytest, node:test) to selected test files.

The XML below is what the runners emit on this repository (pytest 8 run from
the repository root; ``node --test --test-reporter=junit`` on Node 22). Node's
JUnit reporter writes ``classname="test"`` and no ``file``, so a raw report
cannot prove which selected file ran; CI must label each file's report (a
``<testsuite file=...>`` wrapper or a ``file`` attribute), which is accepted.
"""

from __future__ import annotations

from radius_testing.infrastructure.result_matching import (
    attribute_selected_tests,
    report_cases,
)

PYTEST_REPO_ROOT = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" \
errors="0" failures="1" skipped="0" tests="3" time="0.2">\
<testcase classname="packages.graph.tests.test_ts_resolution" name="test_specifier_resolves[a]" time="0.1" />\
<testcase classname="apps.api.tests.test_analyses.TestList" name="test_paginates" time="0.1" />\
<testcase classname="apps.api.tests.test_tests" name="test_upload" time="0.1"><failure message="boom"/></testcase>\
</testsuite></testsuites>"""

NODE_TEST_RAW = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
\t<testcase name="profile rows come from the signed-in user" time="0.005" classname="test"/>
\t<testcase name="initials use up to two name parts" time="0.001" classname="test"/>
\t<!-- tests 2 -->
</testsuites>"""

NODE_TEST_LABELLED = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="apps/dashboard/tests/account-model.test.mjs" file="apps/dashboard/tests/account-model.test.mjs">
    <testcase name="profile rows come from the signed-in user" time="0.005" classname="test"/>
  </testsuite>
  <testsuite name="api" file="apps/dashboard/tests/api.test.mjs">
    <testsuite name="nested describe">
      <testcase name="fetches" classname="test"><failure message="x"/></testcase>
    </testsuite>
  </testsuite>
  <testsuite name="proxy" file="apps/dashboard/tests/ignored.test.mjs">
    <testcase name="own file wins" classname="test" file="apps/dashboard/tests/proxy.test.mjs"/>
  </testsuite>
</testsuites>"""


def test_pytest_report_from_repository_root_attributes_by_dotted_module() -> None:
    attribution = attribute_selected_tests(
        (
            "packages/graph/tests/test_ts_resolution.py",
            "apps/api/tests/test_analyses.py",
            "apps/api/tests/test_tests.py",
            "apps/api/tests/test_missing.py",
        ),
        report_cases(PYTEST_REPO_ROOT),
    )

    assert attribution.passed == (
        "packages/graph/tests/test_ts_resolution.py",
        "apps/api/tests/test_analyses.py",
    )
    assert attribution.failed == ("apps/api/tests/test_tests.py",)
    assert attribution.not_reported == ("apps/api/tests/test_missing.py",)


def test_raw_node_test_junit_cannot_be_attributed_to_a_file() -> None:
    cases = report_cases(NODE_TEST_RAW)

    attribution = attribute_selected_tests(
        ("apps/dashboard/tests/account-model.test.mjs",), cases
    )

    assert len(cases) == 2
    assert attribution.not_reported == ("apps/dashboard/tests/account-model.test.mjs",)
    assert attribution.passed == ()


def test_testsuite_file_labels_every_case_inside_it() -> None:
    cases = report_cases(NODE_TEST_LABELLED)

    attribution = attribute_selected_tests(
        (
            "apps/dashboard/tests/account-model.test.mjs",
            "apps/dashboard/tests/api.test.mjs",
            "apps/dashboard/tests/proxy.test.mjs",
            "apps/dashboard/tests/ignored.test.mjs",
        ),
        cases,
    )

    assert [case.file for case in cases] == [
        "apps/dashboard/tests/account-model.test.mjs",
        "apps/dashboard/tests/api.test.mjs",
        "apps/dashboard/tests/proxy.test.mjs",
    ]
    assert attribution.passed == (
        "apps/dashboard/tests/account-model.test.mjs",
        "apps/dashboard/tests/proxy.test.mjs",
    )
    assert attribution.failed == ("apps/dashboard/tests/api.test.mjs",)
    assert attribution.not_reported == ("apps/dashboard/tests/ignored.test.mjs",)


def test_single_testsuite_root_with_file_is_attributed() -> None:
    xml = (
        '<testsuite name="x" file="web/src/calc.test.ts">'
        '<testcase name="adds" classname="calc"/></testsuite>'
    )

    attribution = attribute_selected_tests(("web/src/calc.test.ts",), report_cases(xml))

    assert attribution.passed == ("web/src/calc.test.ts",)
