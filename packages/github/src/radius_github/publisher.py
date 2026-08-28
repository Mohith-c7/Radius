"""Publish Radius analysis results back to GitHub."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from radius_github.client import GitHubAppClient

CHECK_RUN_NAME = "Radius confidence"
COMMENT_MARKER = "<!-- radius-confidence-report -->"


@dataclass(frozen=True, slots=True)
class GitHubAnalysisReport:
    """Data needed to publish one analysis result."""

    analysis_id: UUID
    owner: str
    repository_name: str
    pull_request_number: int
    head_sha: str
    confidence_score: float
    risk_level: str
    summary: str
    recommendations: tuple[str, ...]
    dashboard_url: str | None = None


class GitHubAnalysisPublisher:
    """Create GitHub Check Runs and PR comments for analysis reports."""

    def __init__(self, client: GitHubAppClient) -> None:
        self._client = client

    def publish(
        self,
        *,
        installation_id: int,
        report: GitHubAnalysisReport,
    ) -> None:
        """Publish a completed Check Run and PR comment."""

        token = self._client.create_installation_token(installation_id).token
        conclusion = _check_conclusion(report.risk_level)
        summary = (
            f"Radius confidence score: {report.confidence_score:.0f}/100 "
            f"({report.risk_level} risk)."
        )
        body = _markdown_report(report)
        check_run = _latest_check_run(
            self._client.list_check_runs_for_ref(
                token=token,
                owner=report.owner,
                repo=report.repository_name,
                ref=report.head_sha,
                check_name=CHECK_RUN_NAME,
            )
        )
        check_run_args = {
            "token": token,
            "owner": report.owner,
            "repo": report.repository_name,
            "name": CHECK_RUN_NAME,
            "head_sha": report.head_sha,
            "conclusion": conclusion,
            "title": f"Radius confidence: {report.confidence_score:.0f}/100",
            "summary": summary,
            "text": body,
            "details_url": report.dashboard_url,
        }
        if check_run is None:
            self._client.create_check_run(**check_run_args)
        else:
            self._client.update_check_run(
                **check_run_args,
                check_run_id=int(check_run["id"]),
            )

        existing_comment = _existing_radius_comment(
            self._client.list_issue_comments(
                token=token,
                owner=report.owner,
                repo=report.repository_name,
                issue_number=report.pull_request_number,
            )
        )
        comment_args = {
            "token": token,
            "owner": report.owner,
            "repo": report.repository_name,
            "body": body,
        }
        if existing_comment is None:
            self._client.create_issue_comment(
                **comment_args,
                issue_number=report.pull_request_number,
            )
        else:
            self._client.update_issue_comment(
                **comment_args,
                comment_id=int(existing_comment["id"]),
            )


def _check_conclusion(risk_level: str) -> str:
    normalized = risk_level.lower()
    if normalized in {"critical", "high"}:
        return "failure"
    if normalized == "medium":
        return "neutral"
    return "success"


def _markdown_report(report: GitHubAnalysisReport) -> str:
    recommendations = "\n".join(
        f"- {item}" for item in report.recommendations
    ) or "- No additional recommendations."
    details = (
        f"\n\n[Open Radius analysis]({report.dashboard_url})"
        if report.dashboard_url
        else ""
    )
    return (
        f"{COMMENT_MARKER}\n"
        "## Radius Confidence Report\n\n"
        f"**Score:** {report.confidence_score:.0f}/100\n\n"
        f"**Risk:** {report.risk_level}\n\n"
        f"{report.summary}\n\n"
        "### Recommendations\n"
        f"{recommendations}"
        f"{details}"
    )


def _latest_check_run(check_runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    matching = [item for item in check_runs if item.get("id") is not None]
    if not matching:
        return None
    return max(matching, key=lambda item: str(item.get("started_at") or item.get("id")))


def _existing_radius_comment(comments: list[dict[str, Any]]) -> dict[str, Any] | None:
    for comment in comments:
        if (
            COMMENT_MARKER in str(comment.get("body", ""))
            and comment.get("id") is not None
        ):
            return comment
    return None
