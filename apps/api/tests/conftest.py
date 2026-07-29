"""API test fixtures."""

import pytest
from radius_api.config import get_api_settings


@pytest.fixture(autouse=True)
def clear_api_settings_cache():
    """Keep environment-driven settings isolated between tests."""

    get_api_settings.cache_clear()
    yield
    get_api_settings.cache_clear()
