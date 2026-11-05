"""Vercel serverless entrypoint for the Radius API."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for source_dir in (
    "apps/api/src",
    "apps/worker/src",
    *(f"packages/{name}/src" for name in (
        "analysis",
        "confidence",
        "graph",
        "parser",
        "repository",
        "shared",
        "testing",
    )),
):
    sys.path.insert(0, str(ROOT / source_dir))

from radius_api.main import app  # noqa: E402,F401
