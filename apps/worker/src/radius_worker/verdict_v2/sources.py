"""Data sources for Verdict v2: checkout files, intent, CI outcomes (VS-05).

Everything that touches the filesystem, git or the database is here, behind small
protocols so Stage A/B are testable with fakes. SQL implementations import their
libraries lazily and use read-only queries scoped by organization.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from radius_evidence.domain.factories import normalize_test_id
from radius_evidence.domain.freshness import is_valid_sha
from radius_evidence.domain.inputs import CaseOutcomeInput, StageAInput

from radius_worker.verdict_v2 import adapters

SKIP_DIRS = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".tox"}
)
MAX_FILE_BYTES = 1_000_000
MAX_FILES = 5_000
_SHA = re.compile(r"^[0-9a-f]{40}$")


# ------------------------------------------------------------------ checkout


def read_python_sources(
    root: Path, *, max_files: int = MAX_FILES, max_bytes: int = MAX_FILE_BYTES
) -> tuple[dict[str, str], bool]:
    """Read ``.py`` files under ``root`` keyed by posix path; second value: truncated.

    Symlinks and anything resolving outside ``root`` are skipped; oversize and
    undecodable files are skipped. Re-implemented here because the orchestrator's
    reader is private (design 5.2).
    """

    sources: dict[str, str] = {}
    truncated = False
    resolved_root = root.resolve()
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts) or path.is_symlink():
            continue
        if len(sources) >= max_files:
            truncated = True
            break
        try:
            if resolved_root not in path.resolve().parents:
                continue
            if path.stat().st_size > max_bytes:
                continue
            sources[rel.as_posix()] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return sources, truncated


def resolve_head_sha(command: Any, *, timeout_s: float = 10.0) -> str | None:
    """A 40-hex head sha from ``command.head_ref`` or ``git rev-parse`` (None if unknown)."""

    ref = getattr(command, "head_ref", None)
    if isinstance(ref, str) and _SHA.match(ref.lower()):
        return ref.lower()
    repo = getattr(command, "repository_path", None)
    if repo is None:
        return None
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(repo), "rev-parse", "--verify", f"{ref or 'HEAD'}^{{commit}}"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip().lower()
    return sha if out.returncode == 0 and _SHA.match(sha) else None


# ------------------------------------------------------------------ intent


@dataclass(frozen=True, slots=True)
class IntentFacts:
    """Criteria (IN-01 objects or look-alikes) and commit messages of an analysis."""

    criteria: tuple[Any, ...] = ()
    commit_messages: tuple[str, ...] = ()
    snapshot_id: str | None = None


class IntentPort(Protocol):
    def load(self, analysis_id: UUID) -> IntentFacts: ...


class HeadShaPort(Protocol):
    def head_sha(self, analysis_id: UUID, command: Any) -> str | None: ...


@dataclass(frozen=True, slots=True)
class StaticIntent:
    """Fixed intent facts (tests, the demo script)."""

    facts: IntentFacts = field(default_factory=IntentFacts)

    def load(self, analysis_id: UUID) -> IntentFacts:  # noqa: ARG002
        return self.facts


# ------------------------------------------------------------------ outcomes


@dataclass(frozen=True, slots=True)
class OutcomeFacts:
    """Stage B inputs that come from CI uploads."""

    cases: tuple[CaseOutcomeInput, ...] = ()
    uploads: int = 0
    flaky_test_ids: frozenset[str] = frozenset()
    flaky_scores: dict[str, float] = field(default_factory=dict)


class OutcomePort(Protocol):
    def load(self, analysis_id: UUID, stage_a: StageAInput) -> OutcomeFacts: ...


@dataclass(frozen=True, slots=True)
class NoOutcomes:
    """No CI results (before the first upload)."""

    def load(self, analysis_id: UUID, stage_a: StageAInput) -> OutcomeFacts:  # noqa: ARG002
        return OutcomeFacts()


def known_test_ids(stage_a: StageAInput) -> set[str]:
    out = {a.test_id for a in stage_a.assertions}
    out |= {e.test_id for e in stage_a.symbol_test}
    out |= {e.test_id for e in stage_a.criterion_test}
    out |= set(stage_a.changed_test_ids)
    return {normalize_test_id(t) for t in out}


def outcomes_from_uploads(
    uploads: Sequence[Any], stage_a: StageAInput
) -> OutcomeFacts:
    """Merge per-case outcomes of the uploads bound to the head commit.

    Uploads for another commit are ignored (SHA binding, design 3.3). Cases are
    merged across uploads with the CI rule failed > passed > skipped.
    """

    from radius_testing.infrastructure.result_matching import merge_cases

    bound = [u for u in uploads if getattr(u, "commit_sha", "").lower() == stage_a.head_sha]
    cases = merge_cases(c for u in bound for c in getattr(u, "cases", ()))
    adapted = adapters.case_inputs(cases)
    identities: list[str] = []
    for u in bound:
        identities.extend(getattr(getattr(u, "result", None), "flaky_tests", ()) or ())
    return OutcomeFacts(
        cases=adapted.items,
        uploads=len(bound),
        flaky_test_ids=adapters.flaky_test_ids(identities, known_test_ids(stage_a)),
    )


@dataclass(slots=True)
class SqlOutcomeSource:
    """Read stored CI uploads of an analysis (``test_result_uploads``)."""

    session_factory: Callable[[], Any]

    def load(self, analysis_id: UUID, stage_a: StageAInput) -> OutcomeFacts:
        from radius_testing.infrastructure.sqlalchemy_store import SqlAlchemyTestStore

        with self.session_factory() as session:
            uploads = SqlAlchemyTestStore(session).list_result_uploads(analysis_id)
        return outcomes_from_uploads(uploads, stage_a)


@dataclass(slots=True)
class SqlIntentSource:
    """Latest intent snapshot and commit messages of an analysis (read-only)."""

    session_factory: Callable[[], Any]

    def _organization_id(self, session: Any, analysis_id: UUID) -> UUID | None:
        from radius_shared.database import models as db_models

        analysis = session.get(db_models.Analysis, analysis_id)
        repository = (
            session.get(db_models.Repository, analysis.repository_id) if analysis else None
        )
        return repository.organization_id if repository else None

    def organization_id(self, analysis_id: UUID) -> UUID | None:
        with self.session_factory() as session:
            return self._organization_id(session, analysis_id)

    def head_sha(self, analysis_id: UUID, command: Any) -> str | None:  # noqa: ARG002
        from radius_shared.database import models as db_models

        with self.session_factory() as session:
            analysis = session.get(db_models.Analysis, analysis_id)
            sha = (analysis.commit_sha or "").lower() if analysis else ""
        return sha if is_valid_sha(sha) else None

    def load(self, analysis_id: UUID) -> IntentFacts:
        from radius_intent.infrastructure.sqlalchemy_repository import (
            SqlAlchemyIntentRepository,
        )

        with self.session_factory() as session:
            org = self._organization_id(session, analysis_id)
            if org is None:
                return IntentFacts()
            repo = SqlAlchemyIntentRepository(session)
            snapshot = repo.get_latest_snapshot(org, str(analysis_id))
            sources = repo.get_sources(org, str(analysis_id))
        messages = tuple(
            s.text for s in sources if getattr(s.kind, "value", s.kind) == "commit_message"
        )
        return IntentFacts(
            criteria=tuple(snapshot.criteria) if snapshot else (),
            commit_messages=messages,
            snapshot_id=snapshot.snapshot_id if snapshot else None,
        )
