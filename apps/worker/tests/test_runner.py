import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import radius_worker.runner as worker_runner
from radius_analysis.domain import AnalysisStatus
from radius_analysis.infrastructure import SqlAlchemyAnalysisJobQueue
from radius_shared.database import enums as db_enums
from radius_shared.database.base import Base
from radius_shared.database.models import (
    Analysis,
    ConfidenceReport,
    GraphSnapshot,
    Organization,
    PullRequest,
    Repository,
)
from radius_shared.database.models import (
    TestRunPlan as DbTestRunPlan,
)
from radius_worker.runner import (
    SqlAlchemyWorkerRuntime,
    load_persisted_analysis_command,
    run_worker,
    run_worker_once,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def test_run_worker_reports_ready(capsys, monkeypatch) -> None:
    fake_runtime = FakeRuntime()
    monkeypatch.setattr(
        worker_runner,
        "create_sql_worker_runtime",
        lambda settings: fake_runtime,
    )

    run_worker()

    captured = capsys.readouterr()
    assert "Radius worker ready" in captured.out
    assert fake_runtime.ran is True


def test_run_worker_once_claims_executes_and_completes_job() -> None:
    queue = FakeQueue()
    orchestrator = FakeOrchestrator()

    processed = run_worker_once(
        queue=queue,
        orchestrator=orchestrator,
        command_loader=lambda job: job.analysis_id,
    )

    assert processed is True
    assert orchestrator.executed == [queue.analysis_id]
    assert queue.completed == [queue.analysis_id]


def test_run_worker_once_marks_job_failed_on_error() -> None:
    queue = FakeQueue()
    orchestrator = FakeOrchestrator(should_fail=True)

    with pytest.raises(RuntimeError):
        run_worker_once(
            queue=queue,
            orchestrator=orchestrator,
            command_loader=lambda job: job.analysis_id,
        )

    assert queue.failed == [queue.analysis_id]


def test_load_persisted_analysis_command_prepares_repository_checkout(
    tmp_path: Path,
) -> None:
    with _session_factory()() as session:
        analysis, repository, pull_request = _persist_analysis_context(session)
        git_client = FakeGitClient()

        command = load_persisted_analysis_command(
            session=session,
            analysis_id=analysis.id,
            repository_cache_dir=tmp_path / "cache",
            git_client=git_client,
        )

        assert command.analysis_id == analysis.id
        assert command.repository_id == repository.id
        assert command.base_ref == f"origin/{pull_request.target_branch}"
        assert command.head_ref == analysis.commit_sha
        assert command.repository_path == git_client.destination
        assert git_client.checked_out == analysis.commit_sha
        assert git_client.extra_headers == ()


def test_load_persisted_analysis_command_passes_clone_headers(
    tmp_path: Path,
) -> None:
    with _session_factory()() as session:
        analysis, _, _ = _persist_analysis_context(session)
        git_client = FakeGitClient()

        load_persisted_analysis_command(
            session=session,
            analysis_id=analysis.id,
            repository_cache_dir=tmp_path / "cache",
            git_client=git_client,
            extra_headers=("Authorization: Bearer token",),
        )

        assert git_client.extra_headers == ("Authorization: Bearer token",)


def test_github_clone_headers_use_stored_installation_id() -> None:
    with _session_factory()() as session:
        analysis, _, _ = _persist_analysis_context(
            session,
            github_installation_id=12345,
        )
        github_client = TokenGitHubClient("clone-token")

        headers = worker_runner._github_clone_headers(
            session=session,
            analysis_id=analysis.id,
            settings=worker_runner.WorkerSettings(
                GITHUB_APP_ID="app-id",
                GITHUB_APP_PRIVATE_KEY="private-key",
            ),
            github_client=github_client,
        )

        assert headers == ("Authorization: Bearer clone-token",)
        assert github_client.installation_ids == [12345]


def test_publish_github_result_builds_report_from_persisted_confidence() -> None:
    with _session_factory()() as session:
        analysis, _, _ = _persist_analysis_context(
            session,
            github_installation_id=12345,
        )
        session.add(
            ConfidenceReport(
                analysis_id=analysis.id,
                confidence_score=81,
                risk_level=db_enums.RiskLevel.LOW,
                summary="Relevant tests passed.",
                recommendations=["Keep coverage close to changed modules."],
                generated_at=datetime.now(UTC),
            )
        )
        session.flush()
        github_client = PublishingGitHubClient()

        worker_runner._publish_github_result(
            session=session,
            analysis_id=analysis.id,
            settings=worker_runner.WorkerSettings(
                GITHUB_APP_ID="app-id",
                GITHUB_APP_PRIVATE_KEY="private-key",
                DASHBOARD_BASE_URL="https://radius.example",
            ),
            github_client=github_client,
        )

        assert github_client.installation_ids == [12345]
        assert github_client.check_runs[0]["owner"] == "acme"
        assert github_client.check_runs[0]["repo"] == "radius"
        assert github_client.check_runs[0]["head_sha"] == analysis.commit_sha
        assert github_client.comments[0]["issue_number"] == 42
        assert "81/100" in github_client.comments[0]["body"]


def test_sqlalchemy_worker_runtime_executes_persisted_job(tmp_path: Path) -> None:
    source_repo = _create_git_repository(tmp_path / "source")
    head_sha = _git(("rev-parse", "HEAD"), cwd=source_repo)
    session_factory = _session_factory()
    with session_factory() as session:
        analysis, _, _ = _persist_analysis_context(
            session,
            clone_url=str(source_repo),
            commit_sha=head_sha,
        )
        SqlAlchemyAnalysisJobQueue(session).enqueue(analysis.id)
        session.commit()

    runtime = SqlAlchemyWorkerRuntime(
        session_factory=session_factory,
        repository_cache_dir=tmp_path / "cache",
        git_client=RealGitClient(),
        settings=worker_runner.WorkerSettings(GITHUB_PUBLISH_RESULTS=False),
        github_client=DisabledGitHubClient(),
    )

    assert runtime.run_once() is True

    with session_factory() as session:
        saved_analysis = session.get(Analysis, analysis.id)
        job = SqlAlchemyAnalysisJobQueue(session).get_by_analysis_id(analysis.id)
        graph = session.query(GraphSnapshot).filter_by(analysis_id=analysis.id).one()
        plan = session.query(DbTestRunPlan).filter_by(analysis_id=analysis.id).one()
        confidence = (
            session.query(ConfidenceReport).filter_by(analysis_id=analysis.id).one()
        )

        assert saved_analysis.status.value == AnalysisStatus.COMPLETED.value
        assert job.status == "completed"
        assert graph.node_count > 0
        assert plan.selected_test_paths
        assert confidence.confidence_score > 0


class FakeJob:
    def __init__(self, analysis_id):
        self.analysis_id = analysis_id


class FakeQueue:
    def __init__(self) -> None:
        self.analysis_id = uuid4()
        self.claimed = False
        self.completed = []
        self.failed = []

    def claim_next(self):
        if self.claimed:
            return None
        self.claimed = True
        return FakeJob(self.analysis_id)

    def complete(self, analysis_id) -> None:
        self.completed.append(analysis_id)

    def fail(self, analysis_id, error: str) -> None:
        self.failed.append(analysis_id)


class FakeOrchestrator:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.executed = []

    def execute(self, command) -> None:
        if self.should_fail:
            raise RuntimeError("failed")
        self.executed.append(command)


class FakeRuntime:
    def __init__(self) -> None:
        self.ran = False

    def run_loop(self, *, poll_interval_seconds: float) -> None:
        self.ran = poll_interval_seconds > 0


class FakeGitClient:
    def __init__(self) -> None:
        self.destination = None
        self.checked_out = None
        self.extra_headers = ()

    def clone_or_fetch(
        self,
        clone_url: str,
        destination: Path,
        *,
        extra_headers: tuple[str, ...] = (),
    ) -> Path:
        self.destination = destination
        self.extra_headers = extra_headers
        return destination

    def checkout(self, repository_path: Path, branch_name: str) -> None:
        self.checked_out = branch_name


class RealGitClient:
    def clone_or_fetch(
        self,
        clone_url: str,
        destination: Path,
        *,
        extra_headers: tuple[str, ...] = (),
    ) -> Path:
        from radius_repository.infrastructure import LocalGitRepositoryClient

        return LocalGitRepositoryClient().clone_or_fetch(
            clone_url,
            destination,
            extra_headers=extra_headers,
        )

    def checkout(self, repository_path: Path, branch_name: str) -> None:
        from radius_repository.infrastructure import LocalGitRepositoryClient

        LocalGitRepositoryClient().checkout(repository_path, branch_name)


class DisabledGitHubClient:
    def create_installation_token(self, installation_id: int):
        raise AssertionError("GitHub publishing should be disabled in this test")


class Token:
    def __init__(self, token: str) -> None:
        self.token = token


class TokenGitHubClient:
    def __init__(self, token: str) -> None:
        self.token = token
        self.installation_ids = []

    def create_installation_token(self, installation_id: int):
        self.installation_ids.append(installation_id)
        return Token(self.token)


class PublishingGitHubClient(TokenGitHubClient):
    def __init__(self) -> None:
        super().__init__("publish-token")
        self.check_runs = []
        self.comments = []

    def list_check_runs_for_ref(self, **kwargs):
        return []

    def create_check_run(self, **kwargs):
        self.check_runs.append(kwargs)
        return {"id": 1}

    def list_issue_comments(self, **kwargs):
        return []

    def create_issue_comment(self, **kwargs):
        self.comments.append(kwargs)
        return {"id": 2}


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _persist_analysis_context(
    session: Session,
    *,
    clone_url: str = "https://github.com/acme/radius.git",
    commit_sha: str = "a" * 40,
    github_installation_id: int | None = None,
):
    organization = Organization(
        name="Acme",
        github_installation_id=github_installation_id,
    )
    repository = Repository(
        organization=organization,
        github_repository_id=999,
        name="radius",
        owner="acme",
        default_branch="main",
        clone_url=clone_url,
        visibility=db_enums.RepositoryVisibility.PRIVATE,
        status=db_enums.RepositoryStatus.CONNECTED,
    )
    pull_request = PullRequest(
        repository=repository,
        github_pr_number=42,
        title="Feature",
        source_branch="feature",
        target_branch="main",
        author="octocat",
        status=db_enums.PullRequestStatus.OPEN,
        opened_at=datetime.now(UTC),
    )
    analysis = Analysis(
        repository=repository,
        pull_request=pull_request,
        commit_sha=commit_sha,
        status=db_enums.AnalysisStatus.PENDING,
        started_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    session.add_all([organization, repository, pull_request, analysis])
    session.flush()
    return analysis, repository, pull_request


def _create_git_repository(path: Path) -> Path:
    path.mkdir()
    _git(("init", "-b", "main"), cwd=path)
    _git(("config", "user.email", "radius@example.com"), cwd=path)
    _git(("config", "user.name", "Radius"), cwd=path)
    _write_repository(path, return_value=1)
    _git(("add", "."), cwd=path)
    _git(("commit", "-m", "initial"), cwd=path)
    _git(("checkout", "-b", "feature"), cwd=path)
    _write_repository(path, return_value=2)
    _git(("add", "."), cwd=path)
    _git(("commit", "-m", "feature"), cwd=path)
    return path


def _write_repository(root: Path, *, return_value: int) -> None:
    (root / "src").mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / "src" / "core.py").write_text(
        f"def calculate():\n    return {return_value}\n",
        encoding="utf-8",
    )
    (root / "src" / "service.py").write_text(
        "from src.core import calculate\n\ndef handle():\n    return calculate()\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_core.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )


def _git(args: tuple[str, ...], *, cwd: Path) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
