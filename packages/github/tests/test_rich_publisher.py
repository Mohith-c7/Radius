"""Unit tests for rich GitHub check runs and PR comments."""

from uuid import uuid4

import pytest
from radius_github.client import _check_run_payload
from radius_github.publisher import (
    COMMENT_MARKER,
    GitHubAnalysisPublisher,
    GitHubAnalysisReport,
)


class FakeToken:
    token = "installation-token"


class FakeGitHubClient:
    def __init__(
        self,
        *,
        check_runs: list[dict] | None = None,
        comments: list[dict] | None = None,
    ) -> None:
        self.existing_check_runs = check_runs or []
        self.existing_comments = comments or []
        self.installation_ids: list[int] = []
        self.check_runs: list[dict] = []
        self.updated_check_runs: list[dict] = []
        self.comments: list[dict] = []
        self.updated_comments: list[dict] = []

    def create_installation_token(self, installation_id: int):
        self.installation_ids.append(installation_id)
        return FakeToken()

    def list_check_runs_for_ref(self, **kwargs):
        return self.existing_check_runs

    def create_check_run(self, **kwargs):
        self.check_runs.append(kwargs)
        return {"id": 1}

    def update_check_run(self, **kwargs):
        self.updated_check_runs.append(kwargs)
        return {"id": kwargs["check_run_id"]}

    def list_issue_comments(self, **kwargs):
        return self.existing_comments

    def create_issue_comment(self, **kwargs):
        self.comments.append(kwargs)
        return {"id": 2}

    def update_issue_comment(self, **kwargs):
        self.updated_comments.append(kwargs)
        return {"id": kwargs["comment_id"]}


def test_publish_in_progress_creates_check_run() -> None:
    client = FakeGitHubClient()
    publisher = GitHubAnalysisPublisher(client)

    publisher.publish_in_progress(
        installation_id=999,
        owner="acme",
        repository_name="radius",
        head_sha="c" * 40,
        dashboard_url="https://radius.example/analyses/in-progress",
    )

    assert client.installation_ids == [999]
    assert len(client.check_runs) == 1
    run = client.check_runs[0]
    assert run["name"] == "Radius confidence"
    assert run["head_sha"] == "c" * 40
    assert run["status"] == "in_progress"
    assert "Analysis in progress" in run["title"]
    assert run["details_url"] == "https://radius.example/analyses/in-progress"
    assert client.updated_check_runs == []


def test_publish_in_progress_updates_existing_check_run() -> None:
    client = FakeGitHubClient(
        check_runs=[{"id": 101, "started_at": "2026-09-28T10:00:00Z"}]
    )
    publisher = GitHubAnalysisPublisher(client)

    publisher.publish_in_progress(
        installation_id=999,
        owner="acme",
        repository_name="radius",
        head_sha="c" * 40,
    )

    assert client.check_runs == []
    assert len(client.updated_check_runs) == 1
    assert client.updated_check_runs[0]["check_run_id"] == 101
    assert client.updated_check_runs[0]["status"] == "in_progress"


def test_update_in_progress_check_run_to_completed() -> None:
    client = FakeGitHubClient(
        check_runs=[{"id": 42, "started_at": "2026-09-28T10:00:00Z"}]
    )
    publisher = GitHubAnalysisPublisher(client)
    report = GitHubAnalysisReport(
        analysis_id=uuid4(),
        owner="acme",
        repository_name="radius",
        pull_request_number=10,
        head_sha="d" * 40,
        confidence_score=92.0,
        risk_level="low",
        summary="High confidence run.",
        recommendations=("All clear.",),
    )

    publisher.publish(installation_id=123, report=report)

    assert client.check_runs == []
    assert len(client.updated_check_runs) == 1
    updated = client.updated_check_runs[0]
    assert updated["check_run_id"] == 42
    assert updated["status"] == "completed"
    assert updated["conclusion"] == "success"
    assert "92/100" in updated["title"]


@pytest.mark.parametrize(
    ("risk_level", "expected_badge"),
    [
        ("low", "🟢"),
        ("medium", "🟡"),
        ("high", "🟠"),
        ("critical", "🔴"),
    ],
)
def test_publish_creates_rich_comment_badges(risk_level: str, expected_badge: str) -> None:
    client = FakeGitHubClient()
    publisher = GitHubAnalysisPublisher(client)
    report = GitHubAnalysisReport(
        analysis_id=uuid4(),
        owner="acme",
        repository_name="radius",
        pull_request_number=5,
        head_sha="e" * 40,
        confidence_score=75.0,
        risk_level=risk_level,
        summary="Risk level evaluation.",
        recommendations=("Check edge cases.",),
    )

    publisher.publish(installation_id=123, report=report)

    body = client.comments[0]["body"]
    assert expected_badge in body
    assert f"**Risk:** {risk_level}" in body
    assert body.startswith(COMMENT_MARKER)


def test_publish_creates_rich_comment_with_metrics_and_blast_radius() -> None:
    client = FakeGitHubClient()
    publisher = GitHubAnalysisPublisher(client)
    report = GitHubAnalysisReport(
        analysis_id=uuid4(),
        owner="acme",
        repository_name="radius",
        pull_request_number=8,
        head_sha="f" * 40,
        confidence_score=85.0,
        risk_level="low",
        summary="Tests and impact look solid.",
        recommendations=("Keep test coverage high.",),
        dashboard_url="https://radius.example/analyses/8",
        selected_tests_count=6,
        skipped_tests_count=18,
        time_saved_percent=75.0,
        affected_files=("src/auth.py", "src/tokens.py"),
        ai_pruned_count=3,
        ai_pruning_notes=("Pruned 3 callers without side effects.",),
    )

    publisher.publish(installation_id=123, report=report)

    assert len(client.comments) == 1
    body = client.comments[0]["body"]

    # Verify score badge
    assert "🟢" in body
    assert "85/100" in body

    # Verify test selection savings
    assert "75.0% time saved" in body
    assert "6 selected" in body
    assert "18 skipped" in body

    # Verify AI impact pruning
    assert "3 pruned" in body
    assert "### AI Pruning Insights" in body
    assert "Pruned 3 callers without side effects." in body

    # Verify collapsible Blast Radius affected files table
    assert "<details>" in body
    assert "</details>" in body
    assert "Blast Radius Affected Files (2)" in body
    assert "| Affected File |" in body
    assert "| `src/auth.py` |" in body
    assert "| `src/tokens.py` |" in body

    # Verify recommendations and dashboard link
    assert "### Recommendations" in body
    assert "- Keep test coverage high." in body
    assert "[Open Radius analysis](https://radius.example/analyses/8)" in body


def test_check_run_payload_in_progress() -> None:
    payload = _check_run_payload(
        name="Radius confidence",
        head_sha="123456",
        title="In progress",
        summary="Running...",
        text="Detail text",
        status="in_progress",
    )
    assert payload["status"] == "in_progress"
    assert "started_at" in payload
    assert "completed_at" not in payload
    assert "conclusion" not in payload


def test_check_run_payload_completed() -> None:
    payload = _check_run_payload(
        name="Radius confidence",
        head_sha="123456",
        title="Completed",
        summary="Done",
        text="Detail text",
        status="completed",
        conclusion="success",
        details_url="https://example.com",
    )
    assert payload["status"] == "completed"
    assert payload["conclusion"] == "success"
    assert "completed_at" in payload
    assert payload["details_url"] == "https://example.com"
