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
