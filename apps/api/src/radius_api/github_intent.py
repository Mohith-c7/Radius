"""Webhook-side intent capture (IN-02): payload text only, no GitHub calls.

The API never talks to GitHub for intent: it holds no App credentials. What a
delivery already carries is stored synchronously instead:

* a new analysis gets the PR title and body from the ``pull_request`` payload
  (the worker later adds linked issues, commits and the spec file);
* ``pull_request.edited`` refreshes title/body of the PR's latest analysis;
* ``issues.edited`` refreshes the stored text of that issue in the latest
  analysis of each recent pull request of the same repository that links it.

Every function is best-effort: it runs inside a savepoint, logs and swallows any
error, and returns ``None``. A failure here must never fail the webhook.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from radius_analysis.application import AnalysisApplicationService
from radius_analysis.dto import AnalysisListQuery
from radius_github.intent_ingestion import IngestionReport, IntentIngestionService
from radius_github.intent_links import IssueRef
from radius_github.intent_sources import (
    Collection,
    PullRequestHint,
    issue_outcome_from_payload,
    issue_source_id,
)
from radius_shared.logging import get_logger
from radius_shared.redaction import redact_secrets

from radius_api.dependencies import (
    build_ingestion_service,
    get_container,
    request_intent_repository,
)
from radius_api.schemas.github_webhooks import GitHubPullRequestPayload

LOGGER = get_logger(__name__)

#: How many recent pull requests of a repository an ``issues.edited`` considers.
MAX_PULLS_PER_ISSUE_EDIT = 20


def _enabled(request: Request) -> bool:
    return bool(getattr(request.app.state.settings, "intent_ingestion_enabled", False))


@contextmanager
def _savepoint(request: Request):
    """Isolate a failure from the webhook's own transaction (SQL mode)."""
    session = getattr(request.state, "radius_db_session", None)
    if session is None:
        yield
        return
    with session.begin_nested():
        yield


def _service(request: Request) -> IntentIngestionService:
    return build_ingestion_service(
        get_container(request), request_intent_repository(request)
    )


def hint_from_payload(payload: GitHubPullRequestPayload) -> PullRequestHint:
    """Map the webhook model to the ingestion hint."""
    return PullRequestHint(
        title=payload.title,
        body=payload.body,
        has_body="body" in payload.model_fields_set,
        author=payload.user.login,
        head_sha=payload.head.sha,
        base_ref=payload.base.ref,
        number=payload.number,
    )


def record_pull_request_intent(
    request: Request,
    *,
    analysis_id: UUID,
    payload: GitHubPullRequestPayload,
    owner: str,
    repo: str,
    trigger: str,
) -> IngestionReport | None:
    """Store the PR title/body of ``payload`` as the intent of ``analysis_id``."""
    org_id = getattr(request.state, "radius_webhook_org_id", None)
    if not _enabled(request) or org_id is None:
        return None
    hint = hint_from_payload(payload)
    if not hint.complete:
        # No body key: leave it to the worker, which falls back to the REST API.
        return None
    try:
        with _savepoint(request):
            return _service(request).apply_pull_request_payload(
                org_id,
                str(analysis_id),
                hint,
                reference=f"{owner}/{repo}#{payload.number}",
                trigger=trigger,
            )
    except Exception as exc:  # best-effort by contract
        _log_failure("pull_request", analysis_id, exc)
        return None


def latest_analysis_id(
    analysis_service: AnalysisApplicationService, pull_request_id: UUID
) -> UUID | None:
    """Return the most recently created analysis of a pull request, if any."""
    analyses = analysis_service.list_analyses(
        AnalysisListQuery(pull_request_id=pull_request_id)
    )
    analyses = [a for a in analyses if a.id is not None]
    if not analyses:
        return None
    return max(analyses, key=lambda a: (_aware(a.created_at), str(a.id))).id


def refresh_issue_intent(
    request: Request,
    *,
    analysis_service: AnalysisApplicationService,
    repository_id: UUID,
    owner: str,
    repo: str,
    issue: dict[str, Any],
    now: datetime,
) -> list[IngestionReport]:
    """Refresh a same-repository issue in the latest analysis of recent PRs linking it."""
    org_id = getattr(request.state, "radius_webhook_org_id", None)
    number = issue.get("number")
    if not _enabled(request) or org_id is None or not isinstance(number, int):
        return []
    ref = IssueRef(owner, repo, number)
    source_id = issue_source_id(ref, owner, repo)
    outcome = issue_outcome_from_payload(
        ref, issue, default_owner=owner, default_repo=repo, now=now
    )
    collection = Collection(outcomes=(outcome,), fetched_at=now)
    reports: list[IngestionReport] = []
    try:
        with _savepoint(request):
            service = _service(request)
            for analysis_id in _recent_analysis_ids(analysis_service, repository_id):
                stored = service.current_sources(org_id, str(analysis_id))
                if not any(s.source_id == source_id for s in stored):
                    continue
                reports.append(
                    service.apply(
                        org_id, str(analysis_id), collection, trigger="issues.edited"
                    )
                )
    except Exception as exc:  # best-effort by contract
        _log_failure("issues", repository_id, exc)
    return reports


def _recent_analysis_ids(
    analysis_service: AnalysisApplicationService, repository_id: UUID
) -> list[UUID]:
    """Latest analysis of each of the newest pull requests of the repository."""
    latest: dict[UUID, Any] = {}
    for analysis in analysis_service.list_analyses(
        AnalysisListQuery(repository_id=repository_id)
    ):
        if analysis.id is None:
            continue
        current = latest.get(analysis.pull_request_id)
        if current is None or _aware(analysis.created_at) > _aware(current.created_at):
            latest[analysis.pull_request_id] = analysis
    newest = sorted(latest.values(), key=lambda a: _aware(a.created_at), reverse=True)
    return [a.id for a in newest[:MAX_PULLS_PER_ISSUE_EDIT]]


def _aware(value: datetime) -> datetime:
    from datetime import UTC

    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _log_failure(event: str, subject: object, exc: Exception) -> None:
    LOGGER.warning(
        "Intent capture from webhook failed; delivery continues: %s",
        redact_secrets(f"{type(exc).__name__}: {exc}"),
        extra={"github_event": event, "subject": str(subject)},
    )


__all__ = [
    "hint_from_payload",
    "latest_analysis_id",
    "record_pull_request_intent",
    "refresh_issue_intent",
]
