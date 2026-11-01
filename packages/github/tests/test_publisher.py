from uuid import uuid4

from radius_github.publisher import GitHubAnalysisPublisher, GitHubAnalysisReport


def test_publisher_creates_check_run_and_pr_comment() -> None:
    client = FakeGitHubClient()
    publisher = GitHubAnalysisPublisher(client)
    report = GitHubAnalysisReport(
        analysis_id=uuid4(),
        owner="acme",
        repository_name="radius",
        pull_request_number=7,
        head_sha="a" * 40,
        confidence_score=88,
        risk_level="low",
        summary="Relevant tests passed.",
        recommendations=("Keep coverage close to changed modules.",),
        dashboard_url="https://radius.example/analyses/1",
        verification_status="verified",
    )

    publisher.publish(installation_id=123, report=report)

    assert client.installation_ids == [123]
    assert client.check_runs[0]["conclusion"] == "success"
    assert client.check_runs[0]["details_url"] == report.dashboard_url
    assert "88/100" in client.comments[0]["body"]
    assert client.updated_check_runs == []
    assert client.updated_comments == []


def test_publisher_updates_existing_check_run_and_pr_comment() -> None:
    client = FakeGitHubClient(
        check_runs=[{"id": 10, "started_at": "2026-07-31T10:00:00Z"}],
        comments=[{"id": 20, "body": "<!-- radius-confidence-report -->\nold"}],
    )
    publisher = GitHubAnalysisPublisher(client)
    report = GitHubAnalysisReport(
        analysis_id=uuid4(),
        owner="acme",
        repository_name="radius",
        pull_request_number=7,
        head_sha="b" * 40,
        confidence_score=62,
        risk_level="medium",
        summary="Some affected files do not have direct coverage.",
        recommendations=("Review affected modules.",),
        verification_status="insufficient_evidence",
    )

    publisher.publish(installation_id=123, report=report)

    assert client.check_runs == []
    assert client.comments == []
    assert client.updated_check_runs[0]["check_run_id"] == 10
    assert client.updated_check_runs[0]["conclusion"] == "neutral"
    assert client.updated_comments[0]["comment_id"] == 20
    assert "62/100" in client.updated_comments[0]["body"]


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
        self.installation_ids = []
        self.check_runs = []
        self.updated_check_runs = []
        self.comments = []
        self.updated_comments = []

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
