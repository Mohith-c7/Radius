"""Publish the stored verdict v2 to GitHub (VS-07/VS-08).

One Check Run (same name as v1) and ONE PR comment per pull request (design
D10). The body comes from the real renderer (``radius_github.verdict_v2.markdown``);
nothing here builds markdown from untrusted text. The renderer emits the v1
marker on line 1 and a v2 marker (``rev`` and content digest) on line 2, so the
v1 and v2 comments are the same comment: ``plan_upsert`` finds it (a v1 comment
is adopted) and creates, updates in place or skips by content digest.

Rules, in order, for ``publish_latest``:

1. flag ``off`` or ``shadow``: never publish v2 (``shadow`` keeps v1);
2. ``GITHUB_PUBLISH_RESULTS`` false or no App credentials: skip;
3. unknown analysis, or analysis of another organization: skip;
4. organization installation not active: skip;
5. latest stored row not ``ok``: skip (v1 is the fallback);
6. stale head: the stored head differs from the analysis commit, a newer
   analysis exists for the pull request, or GitHub reports another head;
7. same rendered digest as the last publish: no GitHub write;
8. otherwise write the Check Run and the comment (create or update in place).

Transport failures raise ``PublishError`` after recording ``publish_error``;
the outbox consumer retries with backoff.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from radius_github.client import GitHubAppClient
from radius_github.publisher import CHECK_RUN_NAME
from radius_github.verdict_v2 import markdown as v2_markdown
from radius_github.verdict_v2.ports import VerdictRenderer
from radius_github.verdict_v2.view import VerdictV2View
from radius_shared.database import enums as db_enums
from radius_shared.database import models as db_models
from radius_shared.redaction import redact_secrets
from radius_shared.verdict_v2_flag import VerdictV2Mode
from radius_shared.verdict_v2_payload import StoredVerdict, build_payload
from radius_shared.verdict_v2_repository import SqlVerdictV2Repository
from sqlalchemy import select
from sqlalchemy.orm import Session

from radius_worker.config import WorkerSettings

LOGGER = logging.getLogger(__name__)

Status = Literal["published", "unchanged", "skipped"]


class PublishError(RuntimeError):
    """A GitHub write failed; the outbox should retry.

    Carries the row so the consumer can record ``publish_error`` in its own
    transaction (the publishing session is rolled back on failure).
    """

    def __init__(self, message: str, *, organization_id: UUID, row_id: UUID) -> None:
        super().__init__(message)
        self.organization_id = organization_id
        self.row_id = row_id


@dataclass(frozen=True, slots=True)
class PublishOutcome:
    status: Status
    reason: str
    digest: str | None = None


def check_run_fields(view: VerdictV2View, conclusions: str = "advisory") -> tuple[str, str]:
    """Return ``(title, conclusion)`` from the renderer; pending is completed neutral.

    ``conclusions`` is ``RADIUS_VERDICT_V2_CHECK_CONCLUSIONS`` (``advisory`` default,
    ``strict``); see ``radius_github.verdict_v2.markdown.check_conclusion``.
    """

    return v2_markdown.check_title(view), v2_markdown.check_conclusion(view, mode=conclusions)


def rendered_digest(title: str, conclusion: str, summary: str, body: str) -> str:
    """Digest of what is published; the comment part ignores the revision number."""

    blob = json.dumps(
        [title, conclusion, summary, v2_markdown.comment_digest(body)], ensure_ascii=False
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _latest_check_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    matching = [r for r in runs if r.get("id") is not None]
    if not matching:
        return None
    return max(matching, key=lambda r: str(r.get("started_at") or r.get("id")))


class VerdictV2Publisher:
    """Writes the Check Run and the comment through the existing GitHub client."""

    def __init__(
        self,
        client: GitHubAppClient,
        renderer: VerdictRenderer | None = None,
        conclusions: str = "advisory",
    ) -> None:
        self._conclusions = conclusions
        self._client = client
        self._renderer = renderer if renderer is not None else v2_markdown.MarkdownRenderer()

    def render(self, view: VerdictV2View) -> tuple[str, str, str, str, str]:
        """Return ``(title, conclusion, summary, body, digest)``."""

        title, conclusion = check_run_fields(view, self._conclusions)
        summary = self._renderer.render_check_summary(view)
        body = self._renderer.render_comment(view)
        return title, conclusion, summary, body, rendered_digest(title, conclusion, summary, body)

    def publish(
        self,
        *,
        token: str,
        owner: str,
        repo: str,
        pull_request_number: int,
        head_sha: str,
        view: VerdictV2View,
        dashboard_url: str | None,
        digest_known: str | None = None,
    ) -> tuple[str, bool]:
        """Create or update in place; returns ``(digest, wrote)``."""

        title, conclusion, summary, body, digest = self.render(view)
        if digest_known is not None and digest_known == digest:
            return digest, False
        check = _latest_check_run(
            self._client.list_check_runs_for_ref(
                token=token, owner=owner, repo=repo, ref=head_sha, check_name=CHECK_RUN_NAME
            )
        )
        args = {
            "token": token,
            "owner": owner,
            "repo": repo,
            "name": CHECK_RUN_NAME,
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": conclusion,
            "title": title,
            "summary": summary,
            "text": body,
            "details_url": dashboard_url,
        }
        if check is None:
            self._client.create_check_run(**args)
        else:
            self._client.update_check_run(**args, check_run_id=int(check["id"]))
        comments = self._client.list_issue_comments(
            token=token, owner=owner, repo=repo, issue_number=pull_request_number
        )
        plan = v2_markdown.plan_upsert(comments, body)
        if plan.action == "create":
            self._client.create_issue_comment(
                token=token, owner=owner, repo=repo, issue_number=pull_request_number, body=body
            )
        elif plan.action == "update" and plan.comment_id is not None:
            self._client.update_issue_comment(
                token=token, owner=owner, repo=repo, comment_id=plan.comment_id, body=body
            )
        return digest, True


# --------------------------------------------------------------------------
# renderer loading
# --------------------------------------------------------------------------


def load_renderer() -> VerdictRenderer:
    """The real renderer (VD-06): ``MarkdownRenderer`` over the pure functions."""

    return v2_markdown.MarkdownRenderer()


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------


def v1_block(session: Session, analysis_id: UUID) -> dict[str, Any] | None:
    """The labelled v1 result for the comparison section (never a v2 number)."""

    from radius_confidence.domain.enums import CURRENT_SCORE_KIND

    report = session.scalars(
        select(db_models.ConfidenceReport).where(
            db_models.ConfidenceReport.analysis_id == analysis_id
        )
    ).first()
    if report is None:
        return None
    return {
        "verification_status": report.verification_status or "unknown",
        "confidence_score": float(report.confidence_score),
        "score_kind": CURRENT_SCORE_KIND.value,
        "risk_level": getattr(report.risk_level, "value", str(report.risk_level)),
    }


def _installation_id(
    session: Session, repository: db_models.Repository, settings: WorkerSettings
) -> int | None:
    if settings.github_installation_id:
        return settings.github_installation_id
    organization = session.get(db_models.Organization, repository.organization_id)
    return organization.github_installation_id if organization else None


def _latest_analysis_id(session: Session, analysis: db_models.Analysis) -> UUID:
    siblings = session.scalars(
        select(db_models.Analysis).where(
            db_models.Analysis.pull_request_id == analysis.pull_request_id
        )
    ).all()
    return max(siblings, key=lambda a: (a.created_at, str(a.id))).id


def _stale_reason(
    session: Session,
    analysis: db_models.Analysis,
    stored: StoredVerdict,
) -> str | None:
    if stored.head_sha.lower() != analysis.commit_sha.lower():
        return "stale_head"
    latest = _latest_analysis_id(session, analysis)
    if latest != analysis.id:
        newest = session.get(db_models.Analysis, latest)
        if newest is not None and newest.commit_sha.lower() != analysis.commit_sha.lower():
            return "superseded_analysis"
    return None


def publish_latest(
    session: Session,
    *,
    organization_id: UUID,
    analysis_id: UUID,
    settings: WorkerSettings,
    github_client: GitHubAppClient,
    renderer: VerdictRenderer | None,
) -> PublishOutcome:
    """Publish the newest stored v2 verdict of one analysis (see module docstring).

    The caller commits the session (``published_digest`` is written on it).
    """

    if settings.verdict_v2_mode != VerdictV2Mode.ON:
        return PublishOutcome("skipped", f"flag_{settings.verdict_v2_mode.value}")
    if not settings.github_publish_results or not (
        settings.github_app_id and settings.github_app_private_key
    ):
        return PublishOutcome("skipped", "publishing_disabled")
    if renderer is None:
        return PublishOutcome("skipped", "renderer_unavailable")
    analysis = session.get(db_models.Analysis, analysis_id)
    repository = (
        session.get(db_models.Repository, analysis.repository_id) if analysis else None
    )
    if analysis is None or repository is None or repository.organization_id != organization_id:
        return PublishOutcome("skipped", "analysis_not_found")
    organization = session.get(db_models.Organization, organization_id)
    if (
        organization is not None
        and organization.github_installation_status
        != db_enums.GitHubInstallationStatus.ACTIVE.value
    ):
        return PublishOutcome("skipped", "installation_inactive")
    repo_store = SqlVerdictV2Repository(session)
    stored = repo_store.latest(organization_id, analysis_id)
    if stored is None:
        return PublishOutcome("skipped", "not_computed")
    if stored.status != "ok":
        return PublishOutcome("skipped", "v2_not_ok")
    stale = _stale_reason(session, analysis, stored)
    if stale is not None:
        return PublishOutcome("skipped", stale)
    installation_id = _installation_id(session, repository, settings)
    if installation_id is None:
        return PublishOutcome("skipped", "no_installation")
    pull_request = session.get(db_models.PullRequest, analysis.pull_request_id)
    if pull_request is None:
        return PublishOutcome("skipped", "analysis_not_found")
    dashboard_url = (
        f"{settings.dashboard_base_url.rstrip('/')}/analyses/{analysis_id}"
        if settings.dashboard_base_url
        else None
    )
    payload = build_payload(
        stored, v1=v1_block(session, analysis_id), dashboard_url=dashboard_url
    )
    view = VerdictV2View.from_payload(payload)
    publisher = VerdictV2Publisher(
        github_client, renderer, getattr(settings, "verdict_v2_check_conclusions", "advisory")
    )
    try:
        token = github_client.create_installation_token(installation_id).token
        live = _live_head(
            github_client, token, repository.owner, repository.name,
            pull_request.github_pr_number,
        )
        if live is not None and live.lower() != stored.head_sha.lower():
            return PublishOutcome("skipped", "stale_head_on_github")
        digest, wrote = publisher.publish(
            token=token,
            owner=repository.owner,
            repo=repository.name,
            pull_request_number=pull_request.github_pr_number,
            head_sha=stored.head_sha,
            view=view,
            dashboard_url=dashboard_url,
            digest_known=stored.published_digest,
        )
    except Exception as exc:
        raise PublishError(
            redact_secrets(exc, max_length=300),
            organization_id=organization_id,
            row_id=UUID(stored.row_id),
        ) from exc
    if not wrote:
        return PublishOutcome("unchanged", "same_digest", digest)
    repo_store.mark_published(organization_id, UUID(stored.row_id), digest)
    return PublishOutcome("published", "ok", digest)


def _live_head(
    client: GitHubAppClient, token: str, owner: str, repo: str, number: int
) -> str | None:
    """Current head SHA of the PR per GitHub, or None when it is not in the open list."""

    for pull in client.list_pull_requests(token=token, owner=owner, repo=repo):
        if pull.get("number") == number:
            head = pull.get("head")
            sha = head.get("sha") if isinstance(head, dict) else None
            return sha if isinstance(sha, str) else None
    return None


def v2_replaces_v1(session: Session, settings: WorkerSettings, analysis_id: UUID) -> bool:
    """True when mode is ``on`` and a v2 verdict with status ``ok`` exists to publish.

    Used by the runner's v1 publish step: ``on`` + ok publishes v2 instead of
    v1; ``shadow``, ``off`` or a v2 error/skip leave v1 as the published result.
    """

    if settings.verdict_v2_mode != VerdictV2Mode.ON:
        return False
    analysis = session.get(db_models.Analysis, analysis_id)
    repository = (
        session.get(db_models.Repository, analysis.repository_id) if analysis else None
    )
    if analysis is None or repository is None:
        return False
    stored = SqlVerdictV2Repository(session).latest(repository.organization_id, analysis_id)
    return (
        stored is not None
        and stored.status == "ok"
        and stored.head_sha.lower() == analysis.commit_sha.lower()
    )


def publish_in_job(
    session: Session,
    *,
    analysis_id: UUID,
    settings: WorkerSettings,
    github_client: GitHubAppClient,
    renderer: VerdictRenderer | None = None,
) -> bool:
    """Publish v2 at the end of an analysis job; True when v2 replaced v1.

    Any problem (renderer missing, GitHub error, stale head, v2 not ok) returns
    False so the caller publishes v1 as before. Never raises.
    """

    try:
        analysis = session.get(db_models.Analysis, analysis_id)
        repository = (
            session.get(db_models.Repository, analysis.repository_id) if analysis else None
        )
        if analysis is None or repository is None:
            return False
        outcome = publish_latest(
            session,
            organization_id=repository.organization_id,
            analysis_id=analysis_id,
            settings=settings,
            github_client=github_client,
            renderer=renderer if renderer is not None else load_renderer(),
        )
    except Exception as exc:
        LOGGER.warning(
            "Verdict v2 publish failed; falling back to v1: %s",
            redact_secrets(exc),
            extra={"analysis_id": str(analysis_id), "outcome": "publish_error"},
        )
        return False
    return outcome.status in ("published", "unchanged")
