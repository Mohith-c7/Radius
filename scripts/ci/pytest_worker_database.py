"""Pytest plugin: one SQLite database file per pytest-xdist worker (radius-evidence.yml).

The API's auth engine (apps/api/src/app/database.py) is built from DATABASE_URL when
it is imported, and the app's lifespan runs ``create_all`` on it. Its default,
``sqlite:///./radius.db``, is one file shared by every process, so parallel workers
would race on table creation. Loaded with ``-p pytest_worker_database`` (with
scripts/ci on PYTHONPATH), this sets DATABASE_URL to a file of the worker's own
under RADIUS_TEST_DB_DIR before any test module or conftest is imported.

Without RADIUS_TEST_DB_DIR it does nothing, so a DATABASE_URL set by the caller wins.
"""

from __future__ import annotations

import os
from pathlib import Path


def _configure() -> None:
    directory = os.environ.get("RADIUS_TEST_DB_DIR")
    if not directory:
        return
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    path = Path(directory) / f"radius-{worker}.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["DATABASE_URL"] = f"sqlite:///{path.as_posix()}"


# At import, not in pytest_configure: conftest.py files import the settings first.
_configure()
