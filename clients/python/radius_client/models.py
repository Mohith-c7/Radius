"""Response payload types.

These are ``TypedDict`` s over the plain JSON objects: the client does not validate or
drop fields, so fields added by newer servers stay available (see
``docs/api/STABILITY.md``, "Client rules for unknown fields"). Only the fields that are
part of the stable contract are declared.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict


class Analysis(TypedDict):
    """One verification run of a pull request head commit."""

    id: str
    repository_id: str
    pull_request_id: str
    commit_sha: str
    status: str  # pending, running, completed, failed, cancelled (may grow)
    created_at: str
    started_at: NotRequired[str]
    completed_at: NotRequired[str | None]
    changed_files: NotRequired[list[dict[str, Any]]]
    blast_radius: NotRequired[dict[str, Any] | None]


class ConfidenceEvidence(TypedDict):
    category: str
    label: str
    message: str
    impact: str
    value: NotRequired[float | None]


class ConfidenceReport(TypedDict):
    """Confidence report and evidence-gated verification status."""

    analysis_id: str
    confidence_score: float
    risk_level: str
    summary: str
    verification_status: str  # treat unknown values as "not verified"
    evidence: NotRequired[list[ConfidenceEvidence]]
    recommendations: NotRequired[list[str]]
    score_kind: NotRequired[str]
    generated_at: NotRequired[str]


class UploadResult(TypedDict):
    """Result of one CI test-report upload."""

    id: str
    analysis_id: str
    status: str
    total_tests: int
    passed: int
    failed: int
    skipped: int
    verification_status: NotRequired[str | None]


class Criterion(TypedDict):
    id: str
    text: str
    state: str  # proposed, confirmed, rejected, ... (may grow)
    weight: NotRequired[float]
    testability: NotRequired[str]
    origin: NotRequired[dict[str, Any]]
    span: NotRequired[dict[str, Any]]
    hints: NotRequired[dict[str, Any]]


class IntentSnapshot(TypedDict):
    id: str
    analysis_id: str
    version: int
    etag: str
    criteria: list[Criterion]
    criteria_count: NotRequired[int]
    state_counts: NotRequired[dict[str, int]]
    sources: NotRequired[list[dict[str, Any]]]


class CriterionResult(TypedDict):
    """Outcome of a criterion write."""

    criterion: Criterion
    snapshot_id: str
    snapshot_version: int
    etag: str
    created: NotRequired[bool]


@dataclass(frozen=True)
class Versioned[T]:
    """A payload together with the ``ETag`` it was served with."""

    data: T
    etag: str | None

    def if_match(self) -> str | None:
        """Value to pass as ``if_match`` on the next write."""

        return self.etag
