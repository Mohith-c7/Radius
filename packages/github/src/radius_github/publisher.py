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
    discovered_tests_count: int = 0
    verification_gaps: tuple[str, ...] = ()
    unmapped_files: tuple[str, ...] = ()
    score_kind: str = "heuristic_uncalibrated"


_RISK_BADGES: dict[str, str] = {
    "low": "🟢",
    "medium": "🟡",
    "high": "🟠",
    "critical": "🔴",
}


_SCORE_LABELS: dict[str, str] = {
    "heuristic_uncalibrated": "uncalibrated heuristic, not a probability",
    "calibrated": "calibrated",
}


def _score_label(score_kind: str) -> str:
    """Human label for the score kind; unknown kinds fall back to the safe one."""

    return _SCORE_LABELS.get(score_kind, _SCORE_LABELS["heuristic_uncalibrated"])


def _score_title_label(score_kind: str) -> str:
    if score_kind == "calibrated":
        return "calibrated score"
    return "uncalibrated heuristic score"


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

    def publish_failure(
        self,
        *,
        installation_id: int,
        owner: str,
        repository_name: str,
        head_sha: str,
        error_summary: str,
        dashboard_url: str | None = None,
    ) -> None:
        """Complete the Check Run when an analysis crashed.

        A failed analysis must never leave the check stuck ``in_progress`` and
        must never look like a pass: the conclusion is ``neutral`` and the
        summary states that no verification was performed.
        """

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
            "status": "completed",
            "conclusion": "neutral",
            "title": "Radius: analysis failed",
            "summary": (
                "Radius analysis failed before producing a result. "
                "No verification was performed for this commit; do not treat it as verified."
            ),
            "text": f"Error: {error_summary[:1000]}",
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
        conclusion = _check_conclusion(report.risk_level, report.verification_status)
        title = (
            f"{_verdict_title(report.verification_status)} "
            f"({_score_title_label(report.score_kind)} "
            f"{report.confidence_score:.0f}/100)"
        )
        summary = (
            f"{_verdict_title(report.verification_status)}. "
            f"Confidence {report.confidence_score:.0f}/100 "
            f"({_score_label(report.score_kind)}); {report.risk_level} risk."
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
            "title": title,
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


def _check_conclusion(risk_level: str, verification_status: str | None = None) -> str:
    """Map the evidence-gated verdict (not the heuristic score) to a conclusion.

    Only a ``verified`` analysis with low/medium heuristic risk can produce a
    green check. Missing or unknown evidence is ``neutral``, never ``success``.
    """

    status = (verification_status or "").strip().lower()
    if status == "failed":
        return "failure"
    if status == "verified":
        if risk_level.strip().lower() in {"low", "medium"}:
            return "success"
        return "neutral"
    return "neutral"


_VERDICT_TITLES: dict[str, str] = {
    "verified": "Radius: Verified",
    "failed": "Radius: Failed",
    "insufficient_evidence": "Radius: Not verified (insufficient evidence)",
    "unverified": "Radius: Not verified",
}


def _verdict_title(verification_status: str | None) -> str:
    status = (verification_status or "").strip().lower()
    return _VERDICT_TITLES.get(status, "Radius: Not verified (verdict unavailable)")


def _markdown_report(report: GitHubAnalysisReport) -> str:
    badge = _risk_badge(report.risk_level)
    
    rows = [
        f"| **Confidence Score** | {badge} {report.confidence_score:.0f}/100 "
        f"({_score_label(report.score_kind)}) |",
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
    if report.discovered_tests_count:
        selection_text = (
            f"{report.selected_tests_count} of {report.discovered_tests_count} "
            "discovered test files selected"
        )
    else:
        selection_text = f"{report.selected_tests_count} test files selected"
    rows.append(f"| **Test Selection** | {selection_text} |")
    if report.ai_pruned_count > 0:
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

    gaps_section = ""
    if report.verification_gaps:
        gaps_section = "\n\n### Why this is not verified\n\n" + "\n".join(
            f"- {gap}" for gap in report.verification_gaps
        )

    unmapped_section = ""
    if report.unmapped_files:
        unmapped_rows = "\n".join(f"- `{path}`" for path in report.unmapped_files)
        unmapped_section = (
            "\n\n<details>\n"
            "<summary><strong>Changed files with no test evidence "
            f"({len(report.unmapped_files)})</strong></summary>\n\n"
            f"{unmapped_rows}\n"
            "</details>"
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
        f"**Verdict:** {_verdict_title(report.verification_status)}\n\n"
        f"**Score:** Confidence {report.confidence_score:.0f}/100 "
        f"({_score_label(report.score_kind)})\n\n"
        f"**Risk:** {report.risk_level}\n\n"
        "_The score is an uncalibrated heuristic computed from fixed penalties, not a "
        "calibrated probability that this change is correct._\n\n"
        f"{report.summary}\n\n"
        "### Verification Metrics\n\n"
        f"{metrics_table}"
        f"{gaps_section}"
        f"{unmapped_section}"
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
            and _is_bot_comment(comment)
        ):
            return comment
    return None


def _is_bot_comment(comment: dict[str, Any]) -> bool:
    """Return whether a comment was authored by a bot (e.g. the Radius App).

    A human comment that merely quotes the marker must not be edited. Comments
    without author data are accepted for backward compatibility.
    """

    user = comment.get("user")
    if user is None:
        return True
    if not isinstance(user, dict):
        return False
    return str(user.get("type", "")).lower() == "bot"
