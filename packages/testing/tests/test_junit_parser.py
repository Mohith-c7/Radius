"""Unit tests for JUnitReportParser and test result ingestion."""

from pathlib import Path
from uuid import uuid4

from radius_testing.application import TestingApplicationService
from radius_testing.domain import (
    TestCase as RadiusTestCase,
)
from radius_testing.domain import (
    TestRunStatus as RadiusTestRunStatus,
)
from radius_testing.infrastructure import (
    InMemoryTestStore,
    JUnitReportParser,
    PathBasedTestSelector,
    StaticTestCommandPlanner,
)
from radius_testing.interfaces.discovery import TestDiscoverer

TestingApplicationService.__test__ = False
TestDiscoverer.__test__ = False



class _DummyDiscoverer:
    def discover(self, repository_path: Path) -> tuple[RadiusTestCase, ...]:
        return ()



def test_parse_single_testsuite_xml_pytest_style() -> None:
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="3" time="0.350">
    <testcase classname="tests.test_auth" name="test_login_success" time="0.100" />
    <testcase classname="tests.test_auth" name="test_token_refresh" time="0.150" />
    <testcase classname="tests.test_auth" name="test_logout" time="0.100" />
</testsuite>
"""
    parser = JUnitReportParser()
    analysis_id = uuid4()
    result = parser.parse(xml_content, analysis_id)

    assert result.analysis_id == analysis_id
    assert result.total_tests == 3
    assert result.passed == 3
    assert result.failed == 0
    assert result.skipped == 0
    assert result.duration_ms == 350
    assert result.status == RadiusTestRunStatus.PASSED
    assert result.output == ""


def test_parse_multi_testsuites_xml_jest_vitest_style() -> None:
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="jest-tests" tests="4" failures="0" errors="0" time="1.250">
    <testsuite name="Button Component" tests="2" failures="0" errors="0" time="0.500">
        <testcase classname="Button.test.tsx" name="renders correctly" time="0.200" />
        <testcase classname="Button.test.tsx" name="handles onClick" time="0.300" />
    </testsuite>
    <testsuite name="Modal Component" tests="2" failures="0" errors="0" time="0.750">
        <testcase classname="Modal.test.tsx" name="opens on trigger" time="0.350" />
        <testcase classname="Modal.test.tsx" name="closes on backdrop click" time="0.400" />
    </testsuite>
</testsuites>
"""
    parser = JUnitReportParser()
    analysis_id = uuid4()
    result = parser.parse(xml_content.encode("utf-8"), analysis_id)

    assert result.analysis_id == analysis_id
    assert result.total_tests == 4
    assert result.passed == 4
    assert result.failed == 0
    assert result.skipped == 0
    assert result.duration_ms == 1250
    assert result.status == RadiusTestRunStatus.PASSED


def test_parse_xml_with_failing_testcases() -> None:
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" errors="1" failures="1" skipped="1" tests="4" time="0.600">
    <testcase classname="tests.test_api" name="test_get_health" time="0.050" />
    <testcase classname="tests.test_api" name="test_post_invalid_payload" time="0.150">
        <failure message="AssertionError: 400 != 500">
Traceback (most recent call last):
  File "test_api.py", line 42, in test_post_invalid_payload
    assert response.status_code == 500
AssertionError: 400 != 500
        </failure>
    </testcase>
    <testcase classname="tests.test_api" name="test_database_timeout" time="0.300">
        <error message="TimeoutError: database connection timed out">
Traceback (most recent call last):
  File "test_api.py", line 85, in test_database_timeout
    raise TimeoutError("database connection timed out")
TimeoutError: database connection timed out
        </error>
    </testcase>
    <testcase classname="tests.test_api" name="test_external_service" time="0.100">
        <skipped message="requires LIVE_CREDENTIALS" />
    </testcase>
</testsuite>
"""
    parser = JUnitReportParser()
    analysis_id = uuid4()
    result = parser.parse(xml_content, analysis_id)

    assert result.analysis_id == analysis_id
    assert result.total_tests == 4
    assert result.passed == 1
    assert result.failed == 2
    assert result.skipped == 1
    assert result.status == RadiusTestRunStatus.FAILED
    assert "AssertionError: 400 != 500" in result.output
    assert "TimeoutError: database connection timed out" in result.output


def test_parse_json_test_report() -> None:
    json_content = """{
        "total_tests": 10,
        "passed": 8,
        "failed": 1,
        "skipped": 1,
        "duration_ms": 2400,
        "coverage_percent": 87.5,
        "output": "FAILED tests/test_billing.py::test_invoice_creation"
    }"""
    parser = JUnitReportParser()
    analysis_id = uuid4()
    result = parser.parse(json_content.encode("utf-8"), analysis_id)

    assert result.analysis_id == analysis_id
    assert result.total_tests == 10
    assert result.passed == 8
    assert result.failed == 1
    assert result.skipped == 1
    assert result.duration_ms == 2400
    assert result.coverage_percent == 87.5
    assert result.status == RadiusTestRunStatus.FAILED
    assert "FAILED tests/test_billing.py::test_invoice_creation" in result.output


def test_ingest_test_results_in_testing_service() -> None:
    store = InMemoryTestStore()
    service = TestingApplicationService(
        discoverer=_DummyDiscoverer(),
        selector=PathBasedTestSelector(),
        store=store,
        planner=StaticTestCommandPlanner(),
    )
    analysis_id = uuid4()
    xml_report = """<testsuite name="pytest" tests="2" failures="0" errors="0" skipped="0" time="0.180">
        <testcase classname="tests.test_unit" name="test_addition" time="0.080" />
        <testcase classname="tests.test_unit" name="test_subtraction" time="0.100" />
    </testsuite>"""

    response = service.ingest_test_results(analysis_id, xml_report)

    assert response.analysis_id == analysis_id
    assert response.total_tests == 2
    assert response.passed == 2
    assert response.failed == 0
    assert response.skipped == 0
    assert response.status == "passed"
    assert response.duration_ms == 180

    loaded = service.get_run_result(analysis_id)
    assert loaded.id == response.id
    assert loaded.status == "passed"
    assert loaded.total_tests == 2
