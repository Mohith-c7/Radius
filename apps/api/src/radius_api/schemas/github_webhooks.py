"""GitHub webhook request and response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class GitHubUserPayload(BaseModel):
    """Minimal GitHub user payload."""

    login: str


class GitHubRepositoryPayload(BaseModel):
    """Minimal GitHub repository payload used by Phase 1."""

    id: int
    name: str
    private: bool = False
    #: ``None`` when the payload does not carry it (installation payloads list
    #: only id/name/full_name/private). Never defaulted to a guess here, so the
    #: handler can tell "unknown" from "explicitly main".
    default_branch: str | None = None
    clone_url: str
    owner: GitHubUserPayload


class GitHubRepositoryDefaultBranchPayload(BaseModel):
    """The only field read from a PR branch's embedded repository object."""

    id: int | None = None
    default_branch: str | None = None


class GitHubPullRequestBranchPayload(BaseModel):
    """Minimal pull request branch payload."""

    ref: str
    sha: str
    #: The repository this branch belongs to (full repository object in real
    #: deliveries); used as a default-branch source for a PR's base repo.
    repo: GitHubRepositoryDefaultBranchPayload | None = None


class GitHubPullRequestPayload(BaseModel):
    """Minimal GitHub pull request payload used by Phase 1."""

    number: int
    title: str
    state: str
    draft: bool = False
    merged: bool = False
    user: GitHubUserPayload
    head: GitHubPullRequestBranchPayload
    base: GitHubPullRequestBranchPayload
    created_at: datetime
    merged_at: datetime | None = None


class GitHubWebhookResult(BaseModel):
    """Response payload for GitHub webhook handling."""

    delivery_id: str = Field(alias="deliveryId")
    event: str
    action: str | None = None
    ignored: bool = False
    repository_id: str | None = Field(default=None, alias="repositoryId")
    pull_request_id: str | None = Field(default=None, alias="pullRequestId")
    analysis_id: str | None = Field(default=None, alias="analysisId")
    #: Queued-not-started analyses cancelled by this delivery (PR closed, repo removed).
    cancelled_analysis_ids: list[str] = Field(
        default_factory=list, alias="cancelledAnalysisIds"
    )

    model_config = {"populate_by_name": True}
