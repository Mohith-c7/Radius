"""Analysis API schemas."""

from uuid import UUID

from pydantic import BaseModel, Field


class StartAnalysisRequest(BaseModel):
    """Request to start an analysis."""

    repository_id: UUID = Field(alias="repositoryId")
    pull_request_id: UUID = Field(alias="pullRequestId")
    commit_sha: str = Field(alias="commitSha", pattern=r"^[0-9a-fA-F]{7,40}$")

    model_config = {"populate_by_name": True}
