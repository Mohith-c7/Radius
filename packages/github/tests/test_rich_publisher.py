"""Unit tests for rich GitHub check runs and PR comments."""

from uuid import uuid4

import pytest
from radius_github.client import _check_run_payload
from radius_github.publisher import (
    COMMENT_MARKER,
    GitHubAnalysisPublisher,
    GitHubAnalysisReport,
    _check_conclusion,
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
        verification_status="verified",
    )

    publisher.publish(installation_id=123, report=report)

    assert client.check_runs == []
    assert len(client.updated_check_runs) == 1
    updated = client.updated_check_runs[0]
    assert updated["check_run_id"] == 42
    assert updated["status"] == "completed"
    assert updated["conclusion"] == "success"
    assert "92/100" in updated["title"]
    assert updated["title"].startswith("Radius: Verified")


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
        verification_status="verified",
        selected_tests_count=6,
        discovered_tests_count=24,
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

    # Test selection is reported factually; no unmeasured "time saved" claim
    assert "6 of 24 discovered test files selected" in body
    assert "time saved" not in body
    assert "not a calibrated probability" in body

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


@pytest.mark.parametrize(
    ("risk_level", "verification_status", "expected"),
    [
        ("low", "verified", "success"),
        ("medium", "verified", "success"),
        ("high", "verified", "neutral"),
        ("critical", "verified", "neutral"),
        ("low", "failed", "failure"),
        ("low", "insufficient_evidence", "neutral"),
        ("low", "unverified", "neutral"),
        ("low", None, "neutral"),
        ("low", "something-new", "neutral"),
    ],
)
def test_check_conclusion_is_driven_by_verdict(
    risk_level: str, verification_status: str | None, expected: str
) -> None:
    assert _check_conclusion(risk_level, verification_status) == expected


def test_high_score_without_evidence_is_never_a_green_check() -> None:
    client = FakeGitHubClient()
    report = GitHubAnalysisReport(
        analysis_id=uuid4(),
        owner="acme",
        repository_name="radius",
        pull_request_number=11,
        head_sha="1" * 40,
        confidence_score=95.0,
        risk_level="low",
        summary="Score high but no mapping evidence.",
        recommendations=("Do not treat this pull request as verified.",),
        verification_status="insufficient_evidence",
        verification_gaps=("1 changed file(s) are not reached by any discovered test",),
        unmapped_files=("src/billing.py",),
    )

    GitHubAnalysisPublisher(client).publish(installation_id=1, report=report)

    run = client.check_runs[0]
    assert run["conclusion"] == "neutral"
    assert run["title"].startswith("Radius: Not verified (insufficient evidence)")
    assert "heuristic score 95/100" in run["title"]
    body = client.comments[0]["body"]
    assert "### Why this is not verified" in body
    assert "- 1 changed file(s) are not reached by any discovered test" in body
    assert "Changed files with no test evidence (1)" in body
    assert "- `src/billing.py`" in body
    assert "AI Impact Pruning" not in body


def test_publish_failure_completes_check_as_neutral_not_pass() -> None:
    client = FakeGitHubClient(check_runs=[{"id": 77, "started_at": "2026-10-01T00:00:00Z"}])

    GitHubAnalysisPublisher(client).publish_failure(
        installation_id=5,
        owner="acme",
        repository_name="radius",
        head_sha="2" * 40,
        error_summary="clone failed",
        dashboard_url="https://radius.example/analyses/9",
    )

    assert client.check_runs == []
    updated = client.updated_check_runs[0]
    assert updated["check_run_id"] == 77
    assert updated["status"] == "completed"
    assert updated["conclusion"] == "neutral"
    assert updated["title"] == "Radius: analysis failed"
    assert "No verification was performed" in updated["summary"]
    assert "clone failed" in updated["text"]


def test_publish_failure_creates_check_when_none_exists() -> None:
    client = FakeGitHubClient()

    GitHubAnalysisPublisher(client).publish_failure(
        installation_id=5,
        owner="acme",
        repository_name="radius",
        head_sha="3" * 40,
        error_summary="boom",
    )

    assert client.check_runs[0]["conclusion"] == "neutral"
    assert client.updated_check_runs == []


def test_human_comment_quoting_marker_is_not_edited() -> None:
    client = FakeGitHubClient(
        comments=[
            {"id": 30, "body": f"quoting {COMMENT_MARKER}", "user": {"type": "User"}},
            {"id": 31, "body": f"{COMMENT_MARKER}\nold", "user": {"type": "Bot"}},
        ]
    )
    report = GitHubAnalysisReport(
        analysis_id=uuid4(),
        owner="acme",
        repository_name="radius",
        pull_request_number=12,
        head_sha="4" * 40,
        confidence_score=50.0,
        risk_level="high",
        summary="s",
        recommendations=(),
        verification_status="insufficient_evidence",
    )

    GitHubAnalysisPublisher(client).publish(installation_id=1, report=report)

    assert client.comments == []
    assert [item["comment_id"] for item in client.updated_comments] == [31]


def test_only_human_comments_with_marker_creates_new_comment() -> None:
    client = FakeGitHubClient(
        comments=[{"id": 30, "body": f"quoting {COMMENT_MARKER}", "user": {"type": "User"}}]
    )
    report = GitHubAnalysisReport(
        analysis_id=uuid4(),
        owner="acme",
        repository_name="radius",
        pull_request_number=12,
        head_sha="5" * 40,
        confidence_score=50.0,
        risk_level="high",
        summary="s",
        recommendations=(),
    )

    GitHubAnalysisPublisher(client).publish(installation_id=1, report=report)

    assert len(client.comments) == 1
    assert client.updated_comments == []


def test_score_is_labelled_uncalibrated_heuristic_everywhere() -> None:
    """F-12: Check Run title/summary and PR comment never show a bare score."""

    client = FakeGitHubClient()
    publisher = GitHubAnalysisPublisher(client)
    report = GitHubAnalysisReport(
        analysis_id=uuid4(),
        owner="acme",
        repository_name="repo",
        pull_request_number=7,
        head_sha="abc123",
        confidence_score=82.0,
        risk_level="low",
        summary="Summary.",
        recommendations=(),
        verification_status="verified",
    )

    publisher.publish(installation_id=1, report=report)

    label = "Confidence 82/100 (uncalibrated heuristic, not a probability)"
    run = client.check_runs[0]
    assert "uncalibrated heuristic score 82/100" in run["title"]
    assert label in run["summary"]
    assert label in client.comments[0]["body"]
    assert "uncalibrated heuristic" in client.comments[0]["body"].split("### Verification Metrics")[1]
