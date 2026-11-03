"""Repository API schemas."""

from uuid import UUID

from pydantic import BaseModel, Field


class ConnectRepositoryRequest(BaseModel):
    """Request to connect a repository."""

    organization_id: UUID = Field(alias="organizationId")
    github_repository_id: int = Field(alias="repositoryId")
    name: str
    owner: str
    default_branch: str = Field(default="main", alias="defaultBranch")
    clone_url: str = Field(alias="cloneUrl")
    visibility: str = "private"

    model_config = {"populate_by_name": True}


class ConnectGitHubRepositoryRequest(BaseModel):
    """Request to connect a repository by name through the GitHub App."""

    repository: str = Field(
        min_length=3,
        max_length=300,
        description="owner/name (a github.com URL is accepted too).",
    )

    model_config = {"populate_by_name": True}


class UpdateRepositoryRequest(BaseModel):
    """Request to update a repository configuration."""

    default_branch: str = Field(min_length=1, max_length=255, alias="defaultBranch")

    model_config = {"populate_by_name": True}
