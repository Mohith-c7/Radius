"""Unit tests for the intent management service internals (IN-08)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from radius_api.intent_management import IntentManagementService, _translate
from radius_intent.application import IntentSnapshotService, SnapshotBuildConflictError
from radius_intent.domain import CriterionState, IntentSourceKind
from radius_intent.infrastructure import (
    InMemoryIntentRepository,
    ManualCriterionExtractor,
)
from radius_intent.infrastructure.extraction import DeterministicCriterionExtractor
from radius_intent.interfaces import (
    AnalysisNotFoundError,
    CriterionNotFoundError,
    InvalidIdentifierError,
    SnapshotConflictError,
    SnapshotNotFoundError,
    SourceTooLargeError,
)
from radius_shared.errors import ConflictError, NotFoundError, ValidationError

NOW = datetime(2026, 11, 2, tzinfo=UTC)


def _service(snapshots=None, repo=None) -> IntentManagementService:
    repo = repo or InMemoryIntentRepository()
    snapshots = snapshots or IntentSnapshotService(
        repo, (ManualCriterionExtractor(), DeterministicCriterionExtractor())
    )
    return IntentManagementService(repo, snapshots, clock=lambda: NOW)


@pytest.mark.parametrize(
    ("error", "expected", "code"),
    [
        (AnalysisNotFoundError("x"), NotFoundError, "ANALYSIS_NOT_FOUND"),
        (SnapshotNotFoundError("x"), NotFoundError, "INTENT_SNAPSHOT_NOT_FOUND"),
        (CriterionNotFoundError("x"), NotFoundError, "CRITERION_NOT_FOUND"),
        (SourceTooLargeError("x"), ValidationError, "INTENT_SOURCE_TOO_LARGE"),
        (InvalidIdentifierError("x"), ValidationError, "INTENT_INVALID"),
        (SnapshotConflictError("x"), ConflictError, "INTENT_CONFLICT"),
    ],
)
def test_persistence_errors_map_to_api_errors(error, expected, code) -> None:
    translated = _translate(error)

    assert isinstance(translated, expected)
    assert translated.detail.code == code


class _Conflicting(IntentSnapshotService):
    def __init__(self, error: Exception) -> None:
        self._error = error

    def latest(self, organization_id, analysis_id):
        return None

    def on_sources_changed(self, *args, **kwargs):
        raise self._error


def test_build_conflicts_surface_as_409() -> None:
    service = _service(_Conflicting(SnapshotBuildConflictError("busy")))

    with pytest.raises(ConflictError) as raised:
        service.submit_source(
            uuid4(),
            uuid4(),
            kind=IntentSourceKind.PR_BODY,
            text="- Users must log in",
            source_id=None,
            if_match=None,
        )

    assert raised.value.detail.code == "INTENT_BUILD_CONFLICT"


def test_persistence_failures_during_a_build_are_translated() -> None:
    service = _service(_Conflicting(AnalysisNotFoundError("gone")))

    with pytest.raises(NotFoundError):
        service.submit_source(
            uuid4(),
            uuid4(),
            kind=IntentSourceKind.PR_BODY,
            text="- Users must log in",
            source_id=None,
            if_match=None,
        )


def test_comment_kind_cannot_be_submitted_directly() -> None:
    with pytest.raises(ValidationError) as raised:
        _service().submit_source(
            uuid4(),
            uuid4(),
            kind=IntentSourceKind.COMMENT,
            text="x",
            source_id=None,
            if_match=None,
        )

    assert raised.value.detail.code == "INTENT_SOURCE_KIND_NOT_ALLOWED"


def test_spec_errors_are_capped_and_counted() -> None:
    bad = "version: 1\ncriteria:\n" + "".join(
        f"  - id: C{i}\n    weight: 9\n" for i in range(15)
    )

    with pytest.raises(ValidationError) as raised:
        _service().submit_source(
            uuid4(),
            uuid4(),
            kind=IntentSourceKind.SPEC_FILE,
            text=bad,
            source_id=None,
            if_match=None,
        )

    message = raised.value.detail.message
    assert raised.value.detail.code == "INTENT_SPEC_INVALID"
    assert "line" in message
    assert "more)" in message


def test_spec_is_revalidated_after_sanitization() -> None:
    spec = 'version: 1\ncriteria:\n  - text: "Users can​ log in"\n'

    outcome = _service().submit_source(
        uuid4(),
        uuid4(),
        kind=IntentSourceKind.SPEC_FILE,
        text=spec,
        source_id=None,
        if_match=None,
    )

    assert outcome.bundle.snapshot.criteria[0].text == "Users can log in"
    assert "zero_width" in outcome.sanitization.removed


def test_unknown_criterion_during_state_change_is_not_found() -> None:
    org, analysis = uuid4(), uuid4()
    service = _service()
    service.submit_source(
        org,
        analysis,
        kind=IntentSourceKind.PR_BODY,
        text="- Users must log in",
        source_id=None,
        if_match=None,
    )

    with pytest.raises(NotFoundError):
        service.apply_action(
            org,
            analysis,
            "crit_missing",
            "confirm",
            text=None,
            reason=None,
            actor="org:x",
            if_match=None,
        )


def test_reopen_after_reject_and_orphan_rules_use_the_state_machine() -> None:
    org, analysis = uuid4(), uuid4()
    service = _service()
    built = service.submit_source(
        org,
        analysis,
        kind=IntentSourceKind.PR_BODY,
        text="- Users must log in",
        source_id=None,
        if_match=None,
    )
    criterion = built.bundle.snapshot.criteria[0]

    service.apply_action(
        org, analysis, criterion.id, "reject", text=None, reason="x" * 900,
        actor="org:x", if_match=None,
    )
    with pytest.raises(ConflictError) as raised:
        service.apply_action(
            org, analysis, criterion.id, "edit", text="Users must log out",
            reason=None, actor="org:x", if_match=None,
        )

    assert raised.value.detail.code == "ILLEGAL_STATE_TRANSITION"
    history = service.criterion_history(org, analysis, criterion.id)
    assert history[0].change.new_state is CriterionState.REJECTED
    assert len(history[0].change.reason or "") == 500
