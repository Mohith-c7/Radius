"""Worker-level proof: an incremental analysis produces exactly the full analysis."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
import radius_worker.runner as worker_runner
from radius_graph.infrastructure import SqlAlchemyGraphStore
from radius_shared.database import enums as db_enums
from radius_shared.database import models as m
from radius_shared.database.base import Base
from radius_worker.orchestrator import ExecuteAnalysisCommand
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

BASE_FILES = {
    "README.md": "# shop\n",
    "shop/__init__.py": "",
    "shop/pricing.py": "from .util import clamp\n\ndef price(x):\n    return clamp(x)\n",
    "shop/util.py": "def clamp(x):\n    return max(x, 0)\n",
    "shop/cart.py": "from shop import pricing, coupons\n\ndef total(x):\n    return pricing.price(x)\n",
    "shop/report.py": "def report():\n    return 'ok'\n",
    "tests/test_pricing.py": "from shop.pricing import price\n\ndef test_price():\n    assert price(1) == 1\n",
    "tests/test_cart.py": "from shop.cart import total\n\ndef test_total():\n    assert total(1) == 1\n",
    "tests/test_report.py": "from shop.report import report\n\ndef test_report():\n    assert report()\n",
}
HEAD_CHANGES: dict[str, str | None] = {
    # modified, added (an import in an unchanged file starts to resolve), deleted
    "shop/util.py": "def clamp(x):\n    return min(max(x, 0), 10)\n",
    "shop/coupons.py": "def code():\n    return 'X'\n",
    "shop/report.py": None,
    "tests/test_report.py": None,
    "docker-compose.yml": "services: {}\n",
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str | None], message: str) -> str:
    for path, content in files.items():
        target = repo / path
        if content is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str, str]:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "radius@example.com")
    _git(path, "config", "user.name", "Radius")
    base = _commit(path, BASE_FILES, "base")
    head = _commit(path, HEAD_CHANGES, "head")
    return path, base, head


def _factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'radius.db').as_posix()}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _analyse(factory, repo: Path, base: str, head: str, *, incremental: bool, explode=None):
    _git(repo, "checkout", "-q", head)
    with factory() as session:
        repository = session.scalar(select(m.Repository))
        if repository is None:
            organization = m.Organization(name="Acme", github_installation_id=1)
            repository = m.Repository(
                organization=organization,
                github_repository_id=1,
                name="shop",
                owner="acme",
                default_branch="main",
                clone_url="https://github.com/acme/shop.git",
                visibility=db_enums.RepositoryVisibility.PRIVATE,
                status=db_enums.RepositoryStatus.CONNECTED,
            )
            session.add_all([organization, repository])
            session.flush()
        analysis = m.Analysis(
            repository_id=repository.id,
            commit_sha=head,
            status=db_enums.AnalysisStatus.PENDING,
            started_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        session.add(analysis)
        session.commit()
        orchestrator = worker_runner._create_sql_orchestrator(
            session,
            worker_runner.WorkerSettings(RADIUS_INCREMENTAL_GRAPH=incremental),
        )
        if explode is not None:
            explode(orchestrator)
        orchestrator.execute(
            ExecuteAnalysisCommand(
                analysis_id=analysis.id,
                repository_id=repository.id,
                repository_path=repo,
                base_ref=base,
                head_ref=head,
            )
        )
        session.commit()
        return analysis.id


def _outputs(factory, analysis_id) -> dict:
    with factory() as session:
        graph = SqlAlchemyGraphStore(session).get_snapshot(analysis_id).graph
        selection = session.scalar(
            select(m.TestSelection).where(m.TestSelection.analysis_id == analysis_id)
        )
        blast = session.scalar(select(m.BlastRadius).where(m.BlastRadius.analysis_id == analysis_id))
        report = session.scalar(
            select(m.ConfidenceReport).where(m.ConfidenceReport.analysis_id == analysis_id)
        )
        return {
            "nodes": set(graph.nodes),
            "edges": set(graph.edges),
            "selected": sorted(
                (session.get(m.TestCase, item.test_case_id).path, item.reason)
                for item in selection.selected_tests
            ),
            "blast": (
                blast.affected_files,
                blast.affected_symbols,
                blast.affected_modules,
                blast.affected_tests,
                blast.dependency_depth,
            ),
            "verdict": (report.verification_status, float(report.confidence_score), report.summary),
            "evidence": sorted(
                (str(item.category), item.label, item.message) for item in report.evidence_items
            ),
        }


def _no_full_parse(orchestrator) -> None:
    def explode(*_args, **_kwargs):  # pragma: no cover - must not run
        raise AssertionError("the incremental analysis must not parse the whole repository")

    orchestrator._parser.parse_repository_result = explode


def test_incremental_analysis_equals_the_full_analysis(tmp_path: Path, repo) -> None:
    path, base, head = repo
    factory = _factory(tmp_path)
    _analyse(factory, path, f"{base}~0", base, incremental=False)  # stores the base graph

    incremental = _analyse(factory, path, base, head, incremental=True, explode=_no_full_parse)
    full = _analyse(factory, path, base, head, incremental=False)

    got, expected = _outputs(factory, incremental), _outputs(factory, full)
    assert got == expected
    # The unchanged cart.py now resolves "coupons" (added): its test must be selected.
    assert {"tests/test_cart.py", "tests/test_pricing.py"} <= {path for path, _ in got["selected"]}
    assert len(got["nodes"]) > 10


def test_no_analysed_ancestor_means_a_full_build(tmp_path: Path, repo) -> None:
    path, base, head = repo
    factory = _factory(tmp_path)
    analysis_id = _analyse(factory, path, base, head, incremental=True)
    assert len(_outputs(factory, analysis_id)["nodes"]) > 10


def test_too_many_changed_files_means_a_full_build(tmp_path: Path, repo, monkeypatch) -> None:
    path, base, head = repo
    factory = _factory(tmp_path)
    _analyse(factory, path, f"{base}~0", base, incremental=False)
    monkeypatch.setenv("RADIUS_INCREMENTAL_MAX_CHANGED_FILES", "2")
    calls = []

    def spy(orchestrator) -> None:
        real = orchestrator._parser.parse_repository_result
        orchestrator._parser.parse_repository_result = lambda *a, **k: calls.append(1) or real(
            *a, **k
        )

    analysis_id = _analyse(factory, path, base, head, incremental=True, explode=spy)
    assert calls == [1]  # five files changed > 2: the whole repository was parsed
    full = _analyse(factory, path, base, head, incremental=False)
    assert _outputs(factory, analysis_id) == _outputs(factory, full)
