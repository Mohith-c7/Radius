"""Application services for test execution analysis."""

import importlib.util
from pathlib import Path

from radius_testing.application.services.flaky_detection_service import (
    FlakyDetectionService,
)

_services_py = Path(__file__).resolve().parent.parent / "services.py"
if _services_py.exists():
    _spec = importlib.util.spec_from_file_location(
        "radius_testing.application._services_impl", _services_py
    )
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        for _name in dir(_mod):
            if not _name.startswith("_"):
                globals()[_name] = getattr(_mod, _name)

__all__ = ["FlakyDetectionService", "TestingApplicationService"]
