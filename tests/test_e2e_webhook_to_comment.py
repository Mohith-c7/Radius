"""End-to-End Adversarial Verification Test: Webhook to Runner to PR Bot Comment.

Tests the full lifecycle from an incoming GitHub pull_request webhook,
through database persistence, multi-tenant organization resolution,
worker job claiming, AST/CPG slicing, confidence scoring, and GitHub bot PR comment publishing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from radius_analysis.infrastructure import SqlAlchemyAnalysisJobQueue
from radius_api.main import create_app
from radius_shared.database import enums as db_enums
from radius_shared.database.base import Base as DomainBase
from radius_shared.database.models import (
    Analysis,
    ConfidenceReport,
    Organization,
    PullRequest,
    Repository,
)
from radius_worker.runner import SqlAlchemyWorkerRuntime, WorkerSettings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class Token:
    def __init__(self, token: str) -> None:
        self.token = token


class CapturingGitHubClient:
    """Captures Check Run and PR comment interactions for verification."""

    def __init__(self) -> None:
        self.installation_tokens: list[int] = []
        self.check_runs_created: list[dict[str, Any]] = []
        self.check_runs_updated: list[dict[str, Any]] = []
        self.comments_created: list[dict[str, Any]] = []

    def create_installation_token(self, installation_id: int) -> Token:
        self.installation_tokens.append(installation_id)
        return Token("mock-installation-token")

    def list_check_runs_for_ref(self, **kwargs) -> list[dict[str, Any]]:
        return []

    def create_check_run(
        self,
        *,
        owner: str,
        repo: str,
        name: str,
        head_sha: str,
        status: str,
        started_at: datetime | None = None,
        installation_id: int | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        data = {
            "id": 1001,
            "owner": owner,
            "repo": repo,
            "name": name,
            "head_sha": head_sha,
            "status": status,
            "started_at": started_at,
            "installation_id": installation_id,
            **kwargs,
        }
        self.check_runs_created.append(data)
        return data

    def update_check_run(
        self,
        *,
        owner: str,
        repo: str,
        check_run_id: int,
        status: str,
        conclusion: str | None = None,
        completed_at: datetime | None = None,
        output: dict[str, Any] | None = None,
        installation_id: int | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        data = {
            "check_run_id": check_run_id,
            "owner": owner,
            "repo": repo,
            "status": status,
            "conclusion": conclusion,
            "completed_at": completed_at,
            "output": output,
            "installation_id": installation_id,
            **kwargs,
        }
        self.check_runs_updated.append(data)
        return data

    def list_issue_comments(self, **kwargs) -> list[dict[str, Any]]:
        return []

    def create_issue_comment(
        self,
        *,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
        installation_id: int | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        data = {
            "id": 2001,
            "owner": owner,
            "repo": repo,
            "issue_number": issue_number,
            "body": body,
            "installation_id": installation_id,
            **kwargs,
        }
        self.comments_created.append(data)
        return data


def _git(args: tuple[str, ...], *, cwd: Path) -> str:
    res = subprocess.run(
        ("git", *args),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return res.stdout.strip()


def _init_test_git_repo(path: Path) -> tuple[Path, str, str]:
    """Create a git repository with main and feature branches.

    Returns (repo_path, main_commit_sha, feature_commit_sha).
    """
    path.mkdir(parents=True, exist_ok=True)
    _git(("init", "-b", "main"), cwd=path)
    _git(("config", "user.email", "radius-test@example.com"), cwd=path)
    _git(("config", "user.name", "Radius Test"), cwd=path)

    src_dir = path / "src"
    tests_dir = path / "tests"
    src_dir.mkdir(exist_ok=True)
    tests_dir.mkdir(exist_ok=True)

    (src_dir / "payment.py").write_text(
        "def process_payment(amount: float) -> bool:\n"
        "    if amount <= 0:\n"
        "        return False\n"
        "    return True\n",
        encoding="utf-8",
    )
    (tests_dir / "test_payment.py").write_text(
        "from src.payment import process_payment\n\n"
        "def test_valid_payment():\n"
        "    assert process_payment(100.0) is True\n",
        encoding="utf-8",
    )

    _git(("add", "."), cwd=path)
    _git(("commit", "-m", "Initial commit on main"), cwd=path)
    main_sha = _git(("rev-parse", "HEAD"), cwd=path)

    # Create feature branch with a modification
    _git(("checkout", "-b", "feature/fee"), cwd=path)
    (src_dir / "payment.py").write_text(
        "def process_payment(amount: float) -> bool:\n"
        "    if amount <= 0:\n"
        "        return False\n"
        "    fee = amount * 0.02\n"
        "    return True\n",
        encoding="utf-8",
    )
    _git(("add", "."), cwd=path)
    _git(("commit", "-m", "Add transaction fee calculation"), cwd=path)
    feature_sha = _git(("rev-parse", "HEAD"), cwd=path)

    # Return to main
    _git(("checkout", "main"), cwd=path)
    return path, main_sha, feature_sha


def _build_signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_e2e_webhook_to_worker_to_pr_comment(tmp_path: Path) -> None:
    """Verify that a pull request webhook triggers analysis and publishes bot comment."""
    db_file = tmp_path / "test_e2e.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", echo=False)
    DomainBase.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    # 1. Seed two organizations to test multi-tenancy
    org_alpha_id = uuid4()
    org_beta_id = uuid4()
    with session_factory() as session:
        org_alpha = Organization(
            id=org_alpha_id,
            name="Org Alpha",
            github_installation_id=11111,
            created_at=datetime.now(UTC),
        )
        org_beta = Organization(
            id=org_beta_id,
            name="Org Beta",
            github_installation_id=22222,
            created_at=datetime.now(UTC),
        )
        session.add_all([org_alpha, org_beta])
        session.commit()

    # 2. Setup git repository
    repo_path, main_sha, feature_sha = _init_test_git_repo(tmp_path / "source_repo")

    # 3. Pre-register a repository under Org Beta to test multi-tenant resolution
    beta_github_id = 99999
    with session_factory() as session:
        beta_repo = Repository(
            id=uuid4(),
            organization_id=org_beta_id,
            github_repository_id=beta_github_id,
            name="beta-service",
            owner="beta-org",
            default_branch="main",
            clone_url=str(repo_path),
            visibility=db_enums.RepositoryVisibility.PRIVATE,
            status=db_enums.RepositoryStatus.CONNECTED,
            created_at=datetime.now(UTC),
        )
        session.add(beta_repo)
        session.commit()

    # 4. Configure FastAPI app
    app = create_app()
    webhook_secret = "radius-e2e-secret"
    app.state.settings.github_webhook_secret = webhook_secret
    # Set DEFAULT organization to Alpha
    app.state.settings.github_default_organization_id = org_alpha_id
    app.state.settings.github_single_tenant = True
    app.state.container.session_factory = session_factory

    client = TestClient(app)

    # 5. TEST GAP 1: Webhook for repo connected to Org Beta must NOT fail with 403
    # even though default org is Org Alpha!
    beta_webhook_payload = {
        "action": "opened",
        "repository": {
            "id": beta_github_id,
            "name": "beta-service",
            "private": True,
            "default_branch": "main",
            "clone_url": str(repo_path),
            "owner": {"login": "beta-org"},
        },
        "pull_request": {
            "number": 1,
            "title": "Beta PR",
            "state": "open",
            "draft": False,
            "merged": False,
            "user": {"login": "developer-beta"},
            "head": {"ref": "feature/fee", "sha": feature_sha},
            "base": {"ref": "main", "sha": main_sha},
            "created_at": "2026-10-02T10:00:00Z",
            "merged_at": None,
        },
        "installation": {"id": 22222},
    }
    beta_body = json.dumps(beta_webhook_payload).encode()
    beta_resp = client.post(
        "/api/v1/webhooks/github",
        content=beta_body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-beta-001",
            "X-Hub-Signature-256": _build_signature(beta_body, webhook_secret),
        },
    )
    assert beta_resp.status_code == 202, f"Expected 202, got: {beta_resp.text}"
    beta_result = beta_resp.json()
    assert beta_result["data"]["analysisId"] is not None

    # Verify that the created analysis belongs to Org Beta, not Org Alpha!
    with session_factory() as session:
        beta_analysis_id = UUID(beta_result["data"]["analysisId"])
        db_analysis = session.get(Analysis, beta_analysis_id)
        assert db_analysis is not None
        assert db_analysis.repository.organization_id == org_beta_id

    # 6. TEST GAP 2 & FULL FLOW: Webhook for new repo under default Org Alpha
    alpha_github_id = 77777
    alpha_webhook_payload = {
        "action": "opened",
        "repository": {
            "id": alpha_github_id,
            "name": "payment-api",
            "private": False,
            "default_branch": "main",
            "clone_url": str(repo_path),
            "owner": {"login": "alpha-org"},
        },
        "pull_request": {
            "number": 42,
            "title": "Add transaction fee calculation",
            "state": "open",
            "draft": False,
            "merged": False,
            "user": {"login": "developer-alpha"},
            "head": {"ref": "feature/fee", "sha": feature_sha},
            "base": {"ref": "main", "sha": main_sha},
            "created_at": "2026-10-02T10:05:00Z",
            "merged_at": None,
        },
        "installation": {"id": 11111},
    }
    alpha_body = json.dumps(alpha_webhook_payload).encode()
    alpha_resp = client.post(
        "/api/v1/webhooks/github",
        content=alpha_body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-alpha-001",
            "X-Hub-Signature-256": _build_signature(alpha_body, webhook_secret),
        },
    )
    assert alpha_resp.status_code == 202
    alpha_analysis_id = UUID(alpha_resp.json()["data"]["analysisId"])

    # Verify that queue job was created in SQLite
    with session_factory() as session:
        queue = SqlAlchemyAnalysisJobQueue(session)
        job = queue.get_by_analysis_id(alpha_analysis_id)
        assert job is not None
        assert job.status == "pending"

        # Verify PR was stored
        pr = session.query(PullRequest).filter_by(github_pr_number=42).one()
        assert pr.title == "Add transaction fee calculation"
        assert pr.target_branch == "main"
        assert pr.source_branch == "feature/fee"

    # 7. EXECUTE WORKER RUNTIME
    capturing_github = CapturingGitHubClient()
    worker_settings = WorkerSettings(
        GITHUB_APP_ID="app-id-test",
        GITHUB_APP_PRIVATE_KEY="key-test",
        GITHUB_PUBLISH_RESULTS=True,
        DASHBOARD_BASE_URL="https://radius.preview",
    )

    class CustomGitClient:
        """Git client that works against local file repos."""
        def clone_or_fetch(self, clone_url: str, destination: Path, *, extra_headers=()):
            if destination.exists():
                return destination
            destination.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", clone_url, str(destination)], check=True, capture_output=True)
            return destination

        def fetch_pull_request(self, repository_path: Path, pr_number: int, *, extra_headers=()):
            pass

        def checkout(self, repository_path: Path, branch_name: str) -> None:
            subprocess.run(["git", "checkout", branch_name], cwd=repository_path, check=True, capture_output=True)

    runtime = SqlAlchemyWorkerRuntime(
        session_factory=session_factory,
        repository_cache_dir=tmp_path / "worker_cache",
        git_client=CustomGitClient(),
        settings=worker_settings,
        github_client=capturing_github,
    )

    # Process Beta job first
    processed_beta = runtime.run_once()
    assert processed_beta is True

    # Process Alpha job
    processed_alpha = runtime.run_once()
    assert processed_alpha is True

    # 8. VERIFY COMPLETE PIPELINE OUTPUT IN DATABASE & GITHUB BOT
    with session_factory() as session:
        completed_analysis = session.get(Analysis, alpha_analysis_id)
        assert completed_analysis.status == db_enums.AnalysisStatus.COMPLETED

        confidence_report = (
            session.query(ConfidenceReport)
            .filter_by(analysis_id=alpha_analysis_id)
            .one()
        )
        assert confidence_report.confidence_score is not None
        assert confidence_report.change_risk is not None
        assert confidence_report.verification_status is not None

    # 9. VERIFY GITHUB BOT CHECK RUN & PR COMMENT
    # Check Run must have been created and completed
    assert len(capturing_github.check_runs_created) >= 1
    last_run = capturing_github.check_runs_created[-1]
    assert last_run["status"] == "completed"
    assert last_run["conclusion"] in ("success", "neutral", "failure")
    assert "Radius confidence" in last_run["name"]

    # PR Comment must have been published to PR #42
    assert len(capturing_github.comments_created) >= 1
    comment = capturing_github.comments_created[-1]
    assert comment["issue_number"] == 42
    comment_body = comment["body"]

    # Verify content of the bot comment
    assert "Radius Confidence Report" in comment_body
    assert "Score:" in comment_body and "/100" in comment_body
    assert "Risk:" in comment_body
    assert "https://radius.preview" in comment_body
