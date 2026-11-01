"""Attribution of CI results to selected tests."""

from radius_testing.infrastructure.result_matching import (
    ExecutedCase,
    executed_cases,
    unmatched_selected_tests,
)

PYTEST_XML = """<?xml version="1.0"?>
<testsuites><testsuite name="pytest" tests="3">
  <testcase classname="tests.test_checkout" name="test_ok"/>
  <testcase classname="tests.test_cart.TestCart" name="test_total"/>
  <testcase classname="tests.test_skip" name="test_s"><skipped/></testcase>
</testsuite></testsuites>"""

VITEST_XML = """<testsuites><testsuite name="vitest">
  <testcase classname="src/app/calc.test.ts" name="adds"/>
</testsuite></testsuites>"""


def test_pytest_dotted_classnames_match_selected_files() -> None:
    missing = unmatched_selected_tests(
        ("tests/test_checkout.py", "tests/test_cart.py"),
        executed_cases(PYTEST_XML),
    )

    assert missing == ()


def test_skipped_cases_and_absent_files_are_not_evidence() -> None:
    missing = unmatched_selected_tests(
        ("tests/test_skip.py", "tests/test_pricing.py"),
        executed_cases(PYTEST_XML),
    )

    assert missing == ("tests/test_skip.py", "tests/test_pricing.py")


def test_path_style_classnames_and_file_attributes_match() -> None:
    assert unmatched_selected_tests(("src/app/calc.test.ts",), executed_cases(VITEST_XML)) == ()
    assert unmatched_selected_tests(
        ("lib/a.test.js",),
        (ExecutedCase(file="/home/runner/work/repo/lib/a.test.js"),),
    ) == ()


def test_unattributable_reports_prove_nothing() -> None:
    aggregate_json = '{"total_tests": 10, "passed": 10, "failed": 0}'

    assert executed_cases(aggregate_json) == ()
    assert executed_cases("not xml at all") == ()
    assert unmatched_selected_tests(("tests/test_a.py",), executed_cases(aggregate_json)) == (
        "tests/test_a.py",
    )


def test_prefix_module_names_do_not_false_match() -> None:
    # "tests.test_cart_extra" must not count as evidence for tests/test_cart.py
    cases = (ExecutedCase(classname="tests.test_cart_extra"),)

    assert unmatched_selected_tests(("tests/test_cart.py",), cases) == ("tests/test_cart.py",)
