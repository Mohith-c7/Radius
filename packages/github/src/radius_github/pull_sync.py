"""Pull-based pull request sync shared by the API route and the worker poller.

``sync_open_pull_requests`` takes the open pull requests GitHub returned for one
connected repository, records each one and starts an analysis for every head
commit that has none yet. It never talks to GitHub itself and has no web
framework dependency, so the ``sync-pull-requests`` API route and the worker's
opt-in poller (``RADIUS_GITHUB_POLL_INTERVAL_SECONDS``) run exactly the same code.

Idempotence: a head commit with a pending, running or completed analysis is not
analyzed again. ``retry_failed=False`` (the poller) also leaves failed and
cancelled analyses alone, so a head commit that cannot be analyzed is not retried
on every tick; the user re-runs it explicitly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
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


def already_analyzed(
    analysis_service: Any,
    repository_id: UUID,
    pull_request_id: UUID,
    commit_sha: str,
    *,
    retry_failed: bool = True,
) -> bool:
    """True when this head commit has a live or finished analysis (repeat syncs are no-ops)."""

    dead = ("failed", "cancelled") if retry_failed else ()
    return any(
        analysis.commit_sha.lower() == commit_sha.lower()
        and analysis.status not in dead
        for analysis in analysis_service.list_analyses(
            AnalysisListQuery(
                repository_id=repository_id, pull_request_id=pull_request_id
            )
        )
    )


def record_pull_request(
    *,
    repository_service: Any,
    analysis_service: Any,
    repository: Any,
    pull_request: Any,
    analyze: bool,
    skip_analyzed: bool = False,
    retry_failed: bool = True,
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
