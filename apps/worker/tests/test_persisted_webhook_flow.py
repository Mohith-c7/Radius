"""Persisted webhook-to-confidence worker flow tests."""

import hashlib
import hmac
import json
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from radius_api.config import get_api_settings
from radius_api.main import create_app
from radius_shared.database.base import Base
from radius_shared.database.models import ConfidenceReport, Organization
from radius_worker.config import WorkerSettings
from radius_worker.runner import create_sql_worker_runtime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_signed_webhook_runs_through_sql_worker_to_confidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_repo = _create_git_repository(tmp_path / "source")
    head_sha = _git(("rev-parse", "HEAD"), cwd=source_repo)
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'radius.db').as_posix()}"
    organization_id = uuid4()
    _create_database(database_url, organization_id)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORAGE_BACKEND", "sql")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("GITHUB_DEFAULT_ORGANIZATION_ID", str(organization_id))
    monkeypatch.setenv("REPOSITORY_CACHE_DIR", str(tmp_path / "cache"))
    get_api_settings.cache_clear()

    app = create_app()
    client = TestClient(app)
    body = _webhook_body(source_repo, head_sha)
    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers=_github_headers(body, "delivery-e2e", "secret"),
    )

    assert response.status_code == 202
    analysis_id = response.json()["data"]["analysisId"]

    runtime = create_sql_worker_runtime(WorkerSettings())
    assert runtime.run_once() is True

    engine = create_engine(database_url)
    with Session(engine) as session:
        confidence = (
            session.query(ConfidenceReport)
            .filter_by(analysis_id=UUID(analysis_id))
            .one()
        )
        assert confidence.confidence_score > 0
        assert confidence.evidence_items


def _create_database(database_url: str, organization_id) -> None:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Organization(id=organization_id, name="Acme"))
        session.commit()


def _webhook_body(source_repo: Path, head_sha: str) -> bytes:
    payload = {
        "action": "synchronize",
        "repository": {
            "id": 12345,
            "name": "radius",
            "private": True,
            "default_branch": "main",
            "clone_url": str(source_repo),
            "owner": {"login": "acme"},
        },
        "pull_request": {
            "number": 5,
            "title": "Change core",
            "state": "open",
            "draft": False,
            "merged": False,
            "user": {"login": "octocat"},
            "head": {"ref": "feature", "sha": head_sha},
            "base": {"ref": "main", "sha": "0" * 40},
            "created_at": "2026-07-29T10:00:00Z",
            "merged_at": None,
        },
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def _github_headers(body: bytes, delivery_id: str, secret: str) -> dict[str, str]:
    signature = (
        "sha256="
        + hmac.new(
            secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
    )
    return {
        "X-GitHub-Event": "pull_request",
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": signature,
    }


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
