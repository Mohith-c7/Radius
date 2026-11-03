"""Pull-based pull request sync shared by the API route and the worker poller.

``sync_open_pull_requests`` takes the open pull requests GitHub returned for one
connected repository, records each one and starts an analysis for every head
commit that has none yet. It never talks to GitHub itself and has no web
framework dependency, so the ``sync-pull-requests`` API route and the worker's
opt-in poller (``RADIUS_GITHUB_POLL_INTERVAL_SECONDS``) run exactly the same code.

Idempotence: a head commit with a pending, running or completed analysis is not
analyzed again. ``retry_failed=False`` (the poller) also leaves failed and
cancelled analyses alone, so a head commit that cannot be analyzed is not retried
on every tick; the user re-runs it explicitly. A ``FailedRetryPolicy`` lets the
poller retry a failed head a bounded number of times with exponential spacing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from radius_analysis.dto import AnalysisListQuery, StartAnalysisCommand
from radius_repository.dto import UpsertPullRequestCommand
from radius_shared.errors import RadiusError, ValidationError

GITHUB_ERROR = "GITHUB_API_ERROR"


class _Ref(BaseModel):
    ref: str
    sha: str


class _User(BaseModel):
    login: str


class PullRequestFacts(BaseModel):
    """The fields of a GitHub REST pull request object that Radius stores."""

    number: int
    title: str
    state: str
    draft: bool = False
    merged: bool = False
    user: _User
    head: _Ref
    base: _Ref
    created_at: datetime
    merged_at: datetime | None = None


def parse_pull_request_facts(raw: dict[str, Any]) -> PullRequestFacts:
    """Validate a REST pull request object; the error names what is wrong."""

    try:
        return PullRequestFacts.model_validate(raw)
    except Exception as exc:
        msg = f"GitHub returned an unexpected shape for pull request {raw.get('number', '?')}."
        raise ValidationError(msg, code=GITHUB_ERROR) from exc


def pull_request_status(pull_request: Any) -> str:
    """Radius status (open, closed, merged) for a parsed GitHub pull request."""

    if pull_request.merged or pull_request.merged_at is not None:
        return "merged"
    if pull_request.state == "closed":
        return "closed"
    return "open"


def skip_reason(exc: Exception) -> str:
    """Short, secret-free reason a pull request was skipped during a sync."""

    if isinstance(exc, RadiusError):
        return f"{exc.detail.code}: {exc.detail.message}"[:200]
    return type(exc).__name__


@dataclass(frozen=True, slots=True)
class FailedRetryPolicy:
    """Bounded automatic retry of a head commit whose analysis failed (C-05).

    A head commit with failed analyses is analysed again by the poller only
    while fewer than ``max_failures`` of them exist, and only once the newest
    failure is older than ``base_delay_seconds * 2 ** (failures - 1)``. Cancelled
    analyses are never retried automatically.
    """

    max_failures: int
    base_delay_seconds: float = 900.0


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def already_analyzed(
    analysis_service: Any,
    repository_id: UUID,
    pull_request_id: UUID,
    commit_sha: str,
    *,
    retry_failed: bool = True,
    failed_retry: FailedRetryPolicy | None = None,
    now: datetime | None = None,
) -> bool:
    """True when this head commit has a live or finished analysis (repeat syncs are no-ops).

    With ``retry_failed=False`` failed and cancelled analyses count as analysed,
    except that ``failed_retry`` lets a failed head be tried again a bounded
    number of times with exponential spacing.
    """

    dead = ("failed", "cancelled") if retry_failed else ()
    same_head = [
        analysis
        for analysis in analysis_service.list_analyses(
            AnalysisListQuery(
                repository_id=repository_id, pull_request_id=pull_request_id
            )
        )
        if analysis.commit_sha.lower() == commit_sha.lower()
    ]
    if any(analysis.status not in dead for analysis in same_head):
        if (
            not retry_failed
            and failed_retry is not None
            and all(analysis.status == "failed" for analysis in same_head)
        ):
            failures = len(same_head)
            if failures >= failed_retry.max_failures:
                return True
            newest = max(
                _utc(a.completed_at or a.created_at) for a in same_head
            )
            wait = timedelta(
                seconds=failed_retry.base_delay_seconds * (2 ** (failures - 1))
            )
            return (now or datetime.now(UTC)) < newest + wait
        return True
    return False


def record_pull_request(
    *,
    repository_service: Any,
    analysis_service: Any,
    repository: Any,
    pull_request: Any,
    analyze: bool,
    skip_analyzed: bool = False,
    retry_failed: bool = True,
    failed_retry: FailedRetryPolicy | None = None,
):
    """Upsert one parsed pull request; start an analysis for its head commit.

    Returns ``(upserted pull request, analysis or None)``.
    """

    repository_id = UUID(str(repository.id))
    upserted = repository_service.upsert_pull_request(
        UpsertPullRequestCommand(
            repository_id=repository_id,
            github_pr_number=pull_request.number,
            title=pull_request.title,
            source_branch=pull_request.head.ref,
            target_branch=pull_request.base.ref,
            author=pull_request.user.login,
            status=pull_request_status(pull_request),
            opened_at=pull_request.created_at,
            merged_at=pull_request.merged_at,
        )
    )
    analysis = None
    sha = pull_request.head.sha
    if (
        analyze
        and sha
        and skip_analyzed
        and already_analyzed(
            analysis_service,
            repository_id,
            UUID(str(upserted.id)),
            sha,
            retry_failed=retry_failed,
            failed_retry=failed_retry,
        )
    ):
        analyze = False
    if analyze and sha:
        analysis = analysis_service.start_analysis(
            StartAnalysisCommand(
                repository_id=repository_id,
                pull_request_id=UUID(str(upserted.id)),
                commit_sha=sha,
            )
        )
    return upserted, analysis


@dataclass(slots=True)
class PullSyncOutcome:
    """Result of syncing one repository."""

    synced: list[Any] = field(default_factory=list)
    analysis_ids: list[str] = field(default_factory=list)
    skipped: list[dict[str, object]] = field(default_factory=list)
    #: Pull requests that needed an analysis but exceeded ``max_analyses``.
    deferred: list[int] = field(default_factory=list)


def sync_open_pull_requests(
    *,
    repository_service: Any,
    analysis_service: Any,
    repository: Any,
    raw_pull_requests: list[dict[str, Any]],
    auto_analyze: bool = True,
    retry_failed: bool = True,
    failed_retry: FailedRetryPolicy | None = None,
    max_analyses: int | None = None,
    parse: Callable[[dict[str, Any]], Any] = parse_pull_request_facts,
    on_analysis: Callable[[Any, Any], None] | None = None,
) -> PullSyncOutcome:
    """Record GitHub's open pull requests and analyze new head commits.

    Draft pull requests are stored but not analyzed. One bad pull request is
    reported in ``skipped`` and never stops the others. ``on_analysis(analysis,
    parsed_pull_request)`` runs after each started analysis (the API stores the
    PR text as intent there). ``max_analyses`` bounds how many analyses one call
    may start; the rest are recorded and listed in ``deferred`` for the next call.
    """

    outcome = PullSyncOutcome()
    for raw in raw_pull_requests:
        number = raw.get("number")
        analyze = bool(auto_analyze and not raw.get("draft"))
        over_budget = (
            analyze
            and max_analyses is not None
            and len(outcome.analysis_ids) >= max_analyses
        )
        try:
            parsed = parse(raw)
            upserted, analysis = record_pull_request(
                repository_service=repository_service,
                analysis_service=analysis_service,
                repository=repository,
                pull_request=parsed,
                analyze=analyze and not over_budget,
                skip_analyzed=True,
                retry_failed=retry_failed,
                failed_retry=failed_retry,
            )
            if analysis is not None and on_analysis is not None:
                on_analysis(analysis, parsed)
            if (
                over_budget
                and parsed.head.sha
                and not already_analyzed(
                    analysis_service,
                    UUID(str(repository.id)),
                    UUID(str(upserted.id)),
                    parsed.head.sha,
                    retry_failed=retry_failed,
                    failed_retry=failed_retry,
                )
            ):
                outcome.deferred.append(int(parsed.number))
        except Exception as exc:  # noqa: BLE001 - one bad PR must not stop the sync
            outcome.skipped.append({"number": number, "reason": skip_reason(exc)})
            continue
        outcome.synced.append(upserted)
        if analysis is not None:
            outcome.analysis_ids.append(str(analysis.id))
    return outcome
