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
    selected_tests_count: int = 0
    skipped_tests_count: int = 0
    time_saved_percent: float = 0.0
    affected_files: tuple[str, ...] = ()
    affected_symbols: tuple[str, ...] = ()
    ai_pruned_count: int = 0
    ai_pruning_notes: tuple[str, ...] = ()
    change_risk: str | None = None
    verification_status: str | None = None
    analysis_completeness: float | None = None


_RISK_BADGES: dict[str, str] = {
    "low": "🟢",
    "medium": "🟡",
    "high": "🟠",
    "critical": "🔴",
}


def _risk_badge(risk_level: str) -> str:
    return _RISK_BADGES.get(risk_level.strip().lower(), "⚪")


class GitHubAnalysisPublisher:
    """Create GitHub Check Runs and PR comments for analysis reports."""

    def __init__(self, client: GitHubAppClient) -> None:
        self._client = client

    def publish_in_progress(
        self,
        *,
        installation_id: int,
        owner: str,
        repository_name: str,
        head_sha: str,
        dashboard_url: str | None = None,
    ) -> None:
        """Publish an in-progress Check Run."""

        token = self._client.create_installation_token(installation_id).token
        check_run = _latest_check_run(
            self._client.list_check_runs_for_ref(
                token=token,
                owner=owner,
                repo=repository_name,
                ref=head_sha,
                check_name=CHECK_RUN_NAME,
            )
        )
        check_run_args = {
            "token": token,
            "owner": owner,
            "repo": repository_name,
            "name": CHECK_RUN_NAME,
            "head_sha": head_sha,
            "status": "in_progress",
            "title": "Radius confidence: Analysis in progress...",
            "summary": "Radius analysis is currently running for this commit.",
            "text": "Radius is analyzing changed files, dependencies, and selecting tests.",
            "details_url": dashboard_url,
        }
        if check_run is None:
            self._client.create_check_run(**check_run_args)
        else:
            self._client.update_check_run(
                **check_run_args,
                check_run_id=int(check_run["id"]),
            )

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
            "status": "completed",
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
    badge = _risk_badge(report.risk_level)
    
    rows = [
        f"| **Confidence Score** | {badge} {report.confidence_score:.0f}/100 |",
    ]
    if report.verification_status:
        status_icon = "🟢" if report.verification_status.upper() == "VERIFIED" else "🔴" if report.verification_status.upper() == "FAILED" else "🟡"
        rows.append(f"| **Verification Status** | {status_icon} {report.verification_status.upper()} |")
    if report.change_risk:
        risk_icon = _risk_badge(report.change_risk)
        rows.append(f"| **Change Risk** | {risk_icon} {report.change_risk.capitalize()} |")
    if report.analysis_completeness is not None:
        pct = float(report.analysis_completeness)
        if pct <= 1.0:
            pct *= 100.0
        rows.append(f"| **Analysis Completeness** | {round(pct)}% |")
    rows.append(
        f"| **Predictive Test Selection** | {report.time_saved_percent}% time saved "
        f"({report.selected_tests_count} selected, {report.skipped_tests_count} skipped) |"
    )
    rows.append(f"| **AI Impact Pruning** | {report.ai_pruned_count} pruned |")

    metrics_table = (
        "| Metric | Result |\n"
        "| --- | --- |\n"
        + "\n".join(rows)
    )

    blast_radius_section = ""
    if report.affected_files:
        files_rows = "\n".join(f"| `{path}` |" for path in report.affected_files)
        blast_radius_section = (
            "\n\n<details>\n"
            f"<summary><strong>Blast Radius Affected Files ({len(report.affected_files)})</strong></summary>\n\n"
            "| Affected File |\n"
            "| --- |\n"
            f"{files_rows}\n"
            "</details>"
        )

    ai_pruning_section = ""
    if report.ai_pruned_count > 0 or report.ai_pruning_notes:
        notes_lines = []
        if report.ai_pruned_count > 0:
            notes_lines.append(
                f"- **Pruned Callers:** {report.ai_pruned_count} unaffected caller(s) pruned by semantic analysis."
            )
        for note in report.ai_pruning_notes:
            notes_lines.append(f"- {note}")
        ai_pruning_section = (
            "\n\n### AI Pruning Insights\n\n"
            + "\n".join(notes_lines)
        )

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
        f"## {badge} Radius Confidence Report\n\n"
        f"**Score:** {report.confidence_score:.0f}/100\n\n"
        f"**Risk:** {report.risk_level}\n\n"
        f"{report.summary}\n\n"
        "### Verification Metrics\n\n"
        f"{metrics_table}"
        f"{blast_radius_section}"
        f"{ai_pruning_section}\n\n"
        "### Recommendations\n\n"
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
