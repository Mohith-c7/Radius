"""Accumulating, revision-bound CI result uploads."""

from uuid import uuid4

import pytest
from radius_shared.database.base import Base
from radius_shared.errors import ValidationError
from radius_testing.application import TestingApplicationService
from radius_testing.domain import CaseOutcome, ReportedTestCase
from radius_testing.infrastructure import (
    InMemoryTestStore,
    JUnitReportParser,
    PathBasedTestSelector,
    SqlAlchemyTestStore,
    StaticTestCommandPlanner,
)
from radius_testing.infrastructure.result_matching import (
    attribute_selected_tests,
    merge_cases,
    report_cases,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

TestingApplicationService.__test__ = False

SHA = "c" * 40
FAILING = """<testsuite tests="1" failures="1">
  <testcase classname="tests.test_pay" name="test_charge"><failure>boom</failure></testcase>
</testsuite>"""
PASSING = """<testsuite tests="2">
  <testcase classname="tests.test_pay" name="test_charge"/>
  <testcase classname="tests.test_cart" name="test_add"/>
</testsuite>"""


class _NoDiscovery:
    def discover(self, repository_path):
        return ()


def _service(store) -> TestingApplicationService:
    return TestingApplicationService(
        discoverer=_NoDiscovery(),
        selector=PathBasedTestSelector(),
        store=store,
        planner=StaticTestCommandPlanner(),
    )


def _sql_store() -> SqlAlchemyTestStore:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return SqlAlchemyTestStore(Session(engine))


@pytest.mark.parametrize("make_store", [InMemoryTestStore, _sql_store])
def test_failure_is_sticky_across_uploads_and_replays_are_idempotent(make_store) -> None:
    store = make_store()
    service = _service(store)
    analysis_id = uuid4()

    service.ingest_test_report(analysis_id, FAILING, SHA)
    later = service.ingest_test_report(analysis_id, PASSING, SHA)
    replay = service.ingest_test_report(analysis_id, PASSING, SHA)

    assert later.status == "failed"
    assert later.failed == 1
    assert later.total_tests == 3
    assert later.contradictory_cases == ("tests.test_pay::test_charge",)
    assert replay.upload.duplicate is True
    assert replay.upload_count == 2
    assert replay.total_tests == 3
    assert store.get_run_result(analysis_id).failed == 1
    uploads = store.list_result_uploads(analysis_id)
    assert [upload.commit_sha for upload in uploads] == [SHA, SHA]
    assert {case.outcome for case in uploads[0].cases} == {CaseOutcome.FAILED}


@pytest.mark.parametrize("make_store", [InMemoryTestStore, _sql_store])
def test_malformed_report_stores_nothing(make_store) -> None:
    store = make_store()
    service = _service(store)
    analysis_id = uuid4()

    with pytest.raises(ValidationError):
        service.ingest_test_report(analysis_id, "<testsuite><testcase", SHA)

    assert store.list_result_uploads(analysis_id) == ()
    assert store.get_run_result(analysis_id) is None


def test_sql_store_returns_existing_upload_for_same_body_hash() -> None:
    store = _sql_store()
    service = _service(store)
    analysis_id = uuid4()
    first = service.ingest_test_report(analysis_id, PASSING, SHA)

    stored = store.get_result_upload(analysis_id, first.upload.body_sha256)

    assert stored is not None
    assert stored.id == first.upload.id
    assert store.save_result_upload(stored).id == stored.id
    assert len(store.list_result_uploads(analysis_id)) == 1


@pytest.mark.parametrize(
    "body",
    [
        "",
        "  \n ",
        "<testsuite><testcase",
        "<html/>",
        '{"total": "many"}',
        '{"total": 3, "failed": -1}',
        "[]",
        '["x"]',
        "plain text",
    ],
)
def test_parser_rejects_malformed_reports(body: str) -> None:
    with pytest.raises(ValidationError):
        JUnitReportParser().parse(body, uuid4())


def test_parser_accepts_empty_but_well_formed_suite() -> None:
    result = JUnitReportParser().parse('<testsuite name="x" tests="0"/>', uuid4())

    assert result.total_tests == 0


def test_merge_cases_failure_beats_pass_beats_skip() -> None:
    cases = (
        ReportedTestCase(classname="tests.test_a", name="t", outcome=CaseOutcome.SKIPPED),
        ReportedTestCase(classname="tests.test_a", name="t", outcome=CaseOutcome.FAILED),
        ReportedTestCase(classname="tests.test_a", name="t", outcome=CaseOutcome.PASSED),
        ReportedTestCase(classname="tests.test_b", name="t", outcome=CaseOutcome.SKIPPED),
        ReportedTestCase(classname="tests.test_b", name="t", outcome=CaseOutcome.PASSED),
    )

    merged = {case.classname: case.outcome for case in merge_cases(cases)}

    assert merged == {"tests.test_a": CaseOutcome.FAILED, "tests.test_b": CaseOutcome.PASSED}


def test_attribution_never_counts_planned_or_skipped_files_as_executed() -> None:
    cases = report_cases(
        """<testsuite>
          <testcase classname="tests.test_a" name="t1"/>
          <testcase classname="tests.test_b" name="t2"><error/></testcase>
          <testcase classname="tests.test_c" name="t3"><skipped/></testcase>
        </testsuite>"""
    )

    attribution = attribute_selected_tests(
        ("tests/test_a.py", "tests/test_b.py", "tests/test_c.py", "tests/test_d.py"),
        cases,
    )

    assert attribution.passed == ("tests/test_a.py",)
    assert attribution.failed == ("tests/test_b.py",)
    assert attribution.executed == ("tests/test_a.py", "tests/test_b.py")
    assert attribution.skipped == ("tests/test_c.py",)
    assert attribution.not_reported == ("tests/test_d.py",)
    assert attribution.missing == ("tests/test_c.py", "tests/test_d.py")


def test_json_case_statuses_are_classified() -> None:
    cases = report_cases(
        '{"total": 3, "testcases": ['
        '{"file": "a.test.ts", "name": "x", "status": "failed"},'
        '{"file": "b.test.ts", "name": "y", "status": "pending"},'
        '{"file": "c.test.ts", "name": "z", "status": "passed"}]}'
    )

    assert [case.outcome for case in cases] == [
        CaseOutcome.FAILED,
        CaseOutcome.SKIPPED,
        CaseOutcome.PASSED,
    ]
