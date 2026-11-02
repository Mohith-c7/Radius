"""OPT-IN DEMO DATA seeder for local development. NOT real analyses.

What it does
    Runs the API's own start-up seeding path once against the configured
    database, so a freshly started local stack has something to look at.

What it creates
    * Hand-written illustrative fixtures for two open-source targets (Bottle,
      Emittery). They are labelled "DEMO FIXTURE" and are not real analyses.
    * A demo login: demo@radius.dev with a publicly documented password.
      Never run this against anything but a disposable local database.

Safety
    * Does nothing unless you pass --yes (or set RADIUS_SEED_DEMO_DATA=true).
    * Refuses to run when RADIUS_ENV=production (the API ignores it there too).
    * Seeding is idempotent: an existing demo user is left unchanged.

Usage (from the repo root, after ``uv sync --extra dev``)
    STORAGE_BACKEND=sql uv run python scripts/seed_demo.py --yes

With the default STORAGE_BACKEND=memory the data would vanish when this process
exits; use RADIUS_SEED_DEMO_DATA=true on the API process instead (``make
dev-local-demo``), or point DATABASE_URL at a SQL database as above.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for rel in (
    "apps/api/src",
    "apps/worker/src",
    "packages/analysis/src",
    "packages/confidence/src",
    "packages/github/src",
    "packages/graph/src",
    "packages/parser/src",
    "packages/repository/src",
    "packages/shared/src",
    "packages/testing/src",
):
    sys.path.insert(0, str(REPO / rel))

BANNER = """
=====================================================================
 RADIUS DEMO DATA SEEDER  -  illustrative fixtures, NOT real analyses
 Creates demo@radius.dev with a publicly documented password.
 For disposable local databases only.
=====================================================================
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed opt-in demo data (local dev only).")
    parser.add_argument("--yes", action="store_true", help="confirm you want demo data")
    args = parser.parse_args(argv)

    print(BANNER)
    opted_in = args.yes or os.environ.get("RADIUS_SEED_DEMO_DATA", "").lower() == "true"
    if not opted_in:
        print("Not seeding: pass --yes (or set RADIUS_SEED_DEMO_DATA=true) to opt in.")
        return 2
    if os.environ.get("RADIUS_ENV", "development").lower() == "production":
        print("Refusing to seed demo data when RADIUS_ENV=production.")
        return 3

    os.environ["RADIUS_SEED_DEMO_DATA"] = "true"
    os.environ.setdefault("RADIUS_ENV", "development")
    if os.environ.get("STORAGE_BACKEND", "memory") == "memory":
        print(
            "NOTE: STORAGE_BACKEND=memory, so seeded data lives only in this process.\n"
            "      Set STORAGE_BACKEND=sql (and DATABASE_URL) to persist it.\n"
        )

    from fastapi.testclient import TestClient
    from radius_api.main import create_app

    with TestClient(create_app()):  # entering the context runs the lifespan seed
        pass
    print("Done. Demo login: demo@radius.dev (see docs/DEPLOYMENT.md for the password note).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
