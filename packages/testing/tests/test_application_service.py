"""Testing application service tests."""

from pathlib import Path
from uuid import uuid4

import pytest
from radius_shared.errors import NotFoundError
from radius_testing.application import TestingApplicationService as RadiusTestingService
from radius_testing.dto import (
    DiscoverTestsCommand,
    PlanTestRunCommand,
    SelectTestsCommand,
)
from radius_testing.infrastructure import (
    ConventionalTestDiscoverer,
    InMemoryTestStore,
    PathBasedTestSelector,
    StaticTestCommandPlanner,
)


def test_testing_service_discovers_selects_and_plans_tests(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_app(): pass\n")
    service = _service()
    analysis_id = uuid4()

    discovery = service.discover_tests(DiscoverTestsCommand(tmp_path))
    selection = service.select_tests(
        SelectTestsCommand(
            analysis_id=analysis_id,
            changed_file_paths=("src/app.py",),
        )
    )
    plan = service.plan_test_run(PlanTestRunCommand(analysis_id))

    assert discovery.test_count == 1
    assert selection.selected_count == 1
    assert plan.command_plan == (("python", ("-m", "pytest", "tests/test_app.py")),)


def test_testing_service_raises_when_selection_missing() -> None:
    service = _service()

    with pytest.raises(NotFoundError):
        service.get_selection(uuid4())


def _service() -> RadiusTestingService:
    return RadiusTestingService(
        discoverer=ConventionalTestDiscoverer(),
        selector=PathBasedTestSelector(),
        store=InMemoryTestStore(),
        planner=StaticTestCommandPlanner(),
    )
