"""Container healthcheck for the worker (C-09).

Healthy means: the database answers AND, when ``WORKER_HEALTH_FILE`` is set, the
worker loop (or the lease heartbeat of a running job) touched that file within
``WORKER_HEALTH_MAX_AGE_SECONDS``. A wedged loop therefore turns unhealthy even
though the database is reachable.
"""

from __future__ import annotations

import os
import sys
import time


def file_is_fresh(path: str, max_age_seconds: float, *, now: float | None = None) -> bool:
    """True when ``path`` exists and was modified at most ``max_age_seconds`` ago."""

    try:
        modified = os.stat(path).st_mtime
    except OSError:
        return False
    current = time.time() if now is None else now
    return (current - modified) <= max_age_seconds


def main() -> int:
    health_file = os.environ.get("WORKER_HEALTH_FILE", "")
    if health_file:
        try:
            max_age = float(os.environ.get("WORKER_HEALTH_MAX_AGE_SECONDS", "300"))
        except ValueError:
            max_age = 300.0
        if not file_is_fresh(health_file, max_age):
            print("worker loop heartbeat is stale or missing", file=sys.stderr)
            return 1
    try:
        from radius_shared.database.session import normalize_database_url
        from sqlalchemy import create_engine, text

        engine = create_engine(normalize_database_url(os.environ["DATABASE_URL"]))
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except Exception as exc:
        print(f"database check failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
