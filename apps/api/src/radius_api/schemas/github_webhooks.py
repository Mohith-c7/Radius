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
    default_branch: str = Field(default="main")
    clone_url: str
    owner: GitHubUserPayload


class GitHubPullRequestBranchPayload(BaseModel):
    """Minimal pull request branch payload."""

    ref: str
    sha: str


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

    model_config = {"populate_by_name": True}
