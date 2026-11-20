"""SQLAlchemy testing store tests."""

from dataclasses import replace
from uuid import uuid4

from radius_shared.database import models as db_models
from radius_shared.database.base import Base
from radius_testing.domain import (
    ReportedTestCase as RadiusReportedTestCase,
)
from radius_testing.domain import (
    SelectedTest,
)
from radius_testing.domain import (
    TestCase as RadiusTestCase,
)
from radius_testing.domain import (
    TestFramework as RadiusTestFramework,
)
from radius_testing.domain import (
    TestName as RadiusTestName,
)
from radius_testing.domain import (
    TestPath as RadiusTestPath,
)
from radius_testing.domain import (
    TestResultUpload as RadiusTestResultUpload,
)
from radius_testing.domain import (
    TestRunPlan as RadiusTestRunPlan,
)
from radius_testing.domain import (
    TestRunResult as RadiusTestRunResult,
)
from radius_testing.domain import (
    TestRunStatus as RadiusTestRunStatus,
)
from radius_testing.domain import (
    TestSelection as RadiusTestSelection,
)
from radius_testing.domain import (
    TestSelectionReason as RadiusTestSelectionReason,
)
from radius_testing.infrastructure import SqlAlchemyTestStore
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_sqlalchemy_test_store_persists_selection_plan_and_result() -> None:
    with _session() as session:
        store = SqlAlchemyTestStore(session)
        analysis_id = uuid4()
        test_case = RadiusTestCase(
            id=uuid4(),
            name=RadiusTestName("test_core"),
            path=RadiusTestPath("tests/test_core.py"),
            framework=RadiusTestFramework.PYTEST,
        )

        store.save_test_cases((test_case,))
        selection = store.save_selection(
            RadiusTestSelection(
                analysis_id=analysis_id,
                selected_tests=(
                    SelectedTest(test_case, RadiusTestSelectionReason.AFFECTED_FILE),
                ),
            )
        )
        plan = store.save_run_plan(
            RadiusTestRunPlan.pending(
                analysis_id,
                selected_tests=(test_case,),
                command_plan=(("python", ("-m", "pytest", "tests/test_core.py")),),
            )
        )
        result = store.save_run_result(
            RadiusTestRunResult(
                id=uuid4(),
                analysis_id=analysis_id,
                status=RadiusTestRunStatus.PASSED,
                total_tests=1,
                passed=1,
                failed=0,
                skipped=0,
                duration_ms=10,
            )
        )

        assert selection.selected_tests[0].test_case.path.value == "tests/test_core.py"
        assert store.get_selection(analysis_id).selected_tests[0].reason.value == (
            "affected_file"
        )
        assert store.get_run_plan(analysis_id).command_plan == plan.command_plan
        assert store.get_run_result(analysis_id).passed == result.passed


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _provenance_upload(*, slot: str, digest: str, attempt: int = 1):
    analysis_id, repository_id = uuid4(), uuid4()
    return RadiusTestResultUpload(
        id=uuid4(),
        analysis_id=analysis_id,
        commit_sha="a" * 40,
        body_sha256=digest,
        result=RadiusTestRunResult(
            id=uuid4(), analysis_id=analysis_id, status=RadiusTestRunStatus.PASSED,
            total_tests=1, passed=1, failed=0, skipped=0, duration_ms=1,
        ),
        cases=(RadiusReportedTestCase("tests/test_a.py", None, "test_a"),),
        repository_id=repository_id,
        report_slot_id=slot,
        run_id="9001",
        run_attempt=attempt,
        manifest_digest="b" * 64,
        artifact_bytes=b"<testsuite/>",
        attestation_bundle=b"bundle-" + slot.encode(),
        attestation_digest=("c" * 63) + digest[-1],
        provenance_status="unverifiable",
    )


def test_sql_report_slot_replay_is_exact_and_slot_specific():
    with _session() as session:
        store = SqlAlchemyTestStore(session)
        first = _provenance_upload(slot="a" * 24, digest="1" * 64)
        saved = store.save_result_upload(first)
        replay = store.save_result_upload(first)
        assert replay.id == saved.id

        different_slot = _provenance_upload(slot="b" * 24, digest="2" * 64)
        different_slot = replace(
            different_slot, analysis_id=first.analysis_id,
            repository_id=first.repository_id, run_id=first.run_id,
        )
        store.save_result_upload(different_slot)

        different_attempt = _provenance_upload(
            slot="a" * 24, digest="3" * 64, attempt=2
        )
        different_attempt = replace(
            different_attempt, analysis_id=first.analysis_id,
            repository_id=first.repository_id, run_id=first.run_id,
        )
        store.save_result_upload(different_attempt)

        conflict = _provenance_upload(slot="a" * 24, digest="4" * 64)
        conflict = replace(
            conflict, analysis_id=first.analysis_id,
            repository_id=first.repository_id, run_id=first.run_id,
        )
        try:
            store.save_result_upload(conflict)
        except ValueError as exc:
            assert str(exc) == "REPLAY_CONFLICT"
        else:
            raise AssertionError("same run slot accepted different artifact bytes")


def test_sql_manifest_and_verification_history_are_immutable_and_append_only():
    with _session() as session:
        store = SqlAlchemyTestStore(session)
        upload = _provenance_upload(slot="d" * 24, digest="5" * 64)
        initial = replace(upload, attestation_bundle=None, attestation_digest=None)
        saved_upload = store.save_result_upload(initial)
        valid_retry = store.save_result_upload(upload)
        assert valid_retry.id == saved_upload.id
        assert valid_retry.attestation_digest is None
        manifest = {
            "schema_version": 1,
            "analysis_id": str(upload.analysis_id),
            "tests": [],
            "slots": [],
        }
        digest = "6" * 64
        saved = store.get_or_create_evidence_manifest(
            upload.analysis_id, upload.repository_id, upload.commit_sha, manifest, digest
        )
        replay = store.get_or_create_evidence_manifest(
            upload.analysis_id, upload.repository_id, upload.commit_sha, manifest, digest
        )
        assert replay["id"] == saved["id"]
        try:
            store.get_or_create_evidence_manifest(
                upload.analysis_id, upload.repository_id, upload.commit_sha,
                {**manifest, "tests": ["different"]}, "7" * 64,
            )
        except ValueError as exc:
            assert str(exc) == "MANIFEST_IMMUTABLE"
        else:
            raise AssertionError("manifest mutation was accepted")

        store.append_verification_event(
            upload.id, "unverifiable", "VERIFIER_UNAVAILABLE", "test-verifier-v1",
            "test-policy-v1", {"attestation_digest": "8" * 64},
        )
        store.append_verification_event(
            upload.id, "verified_provenance", None, "test-verifier-v2",
            "test-policy-v2", {"attestation_digest": upload.attestation_digest},
            upload.attestation_digest, upload.attestation_bundle,
        )
        store.append_verification_event(
            upload.id, "verified_provenance", None, "test-verifier-v2",
            "test-policy-v2", {"attestation_digest": upload.attestation_digest},
            upload.attestation_digest, upload.attestation_bundle,
        )
        assert store.list_result_uploads(upload.analysis_id)[0].provenance_status == (
            "verified_provenance"
        )
        assert session.query(db_models.TestEvidenceVerificationEvent).count() == 2
        event = session.query(db_models.TestEvidenceVerificationEvent).filter_by(
            attestation_digest=upload.attestation_digest
        ).one()
        assert event.attestation_bundle == upload.attestation_bundle


def test_same_test_path_in_two_repositories_is_stored_independently(tmp_path) -> None:
    from radius_testing.application import TestingApplicationService
    from radius_testing.dto import DiscoverTestsCommand
    from radius_testing.infrastructure import (
        ConventionalTestDiscoverer,
        PathBasedTestSelector,
        StaticTestCommandPlanner,
    )

    repo_a, repo_b = uuid4(), uuid4()
    for name, body in (("a", "def test_a():\n    pass\n"), ("b", "def test_b():\n    pass\n")):
        tests_dir = tmp_path / name / "tests"
        tests_dir.mkdir(parents=True)
        (tests_dir / "test_app.py").write_text(body, encoding="utf-8")

    with _session() as session:
        store = SqlAlchemyTestStore(session)
        service = TestingApplicationService(
            discoverer=ConventionalTestDiscoverer(),
            selector=PathBasedTestSelector(),
            store=store,
            planner=StaticTestCommandPlanner(),
        )
        found_a = service.discover_test_cases(DiscoverTestsCommand(tmp_path / "a", repo_a))
        found_b = service.discover_test_cases(DiscoverTestsCommand(tmp_path / "b", repo_b))

        assert found_a[0].path.value == found_b[0].path.value == "tests/test_app.py"
        assert found_a[0].id != found_b[0].id
        assert [t.id for t in store.list_test_cases(repo_a)] == [found_a[0].id]
        assert [t.id for t in store.list_test_cases(repo_b)] == [found_b[0].id]
        assert len(store.list_test_cases()) == 2
