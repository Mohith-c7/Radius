"""Repository domain value object tests."""

from uuid import uuid4

import pytest
from radius_repository.domain import (
    BranchName,
    CommitHash,
    OrganizationId,
    RepositoryFullName,
    RepositoryId,
)


def test_repository_full_name_combines_owner_and_name() -> None:
    full_name = RepositoryFullName(owner="openai", name="radius")

    assert full_name.value == "openai/radius"


def test_branch_name_rejects_empty_value() -> None:
    with pytest.raises(ValueError, match="Branch name cannot be empty"):
        BranchName(" ")


def test_commit_hash_rejects_empty_and_oversized_values() -> None:
    with pytest.raises(ValueError, match="Commit hash cannot be empty"):
        CommitHash("")

    with pytest.raises(ValueError, match="Commit hash cannot exceed 40"):
        CommitHash("a" * 41)


def test_identifier_value_objects_hold_uuid_values() -> None:
    repository_id = uuid4()
    organization_id = uuid4()

    assert RepositoryId(repository_id).value == repository_id
    assert OrganizationId(organization_id).value == organization_id
