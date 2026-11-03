"""Every first-party package must be importable inside the API and worker images.

The images set PYTHONPATH by hand. A package missing from it only fails when the code that imports it
runs (for example the Verdict v2 worker crashed at start-up with ``No module named 'radius_evidence'``),
which no host-side test notices, so check the Dockerfiles statically.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = ("apps/api/Dockerfile", "apps/worker/Dockerfile")


def _pythonpath(dockerfile: str) -> set[str]:
    text = (ROOT / dockerfile).read_text(encoding="utf-8")
    match = re.search(r"PYTHONPATH=(\S+)", text)
    assert match, f"{dockerfile} sets no PYTHONPATH"
    return set(match.group(1).split(":"))


def test_every_package_is_on_the_image_pythonpath() -> None:
    packages = sorted(p.parent.name for p in (ROOT / "packages").glob("*/src"))
    assert packages, "no packages found"
    for dockerfile in DOCKERFILES:
        path = _pythonpath(dockerfile)
        missing = [name for name in packages if f"/app/packages/{name}/src" not in path]
        assert not missing, f"{dockerfile} PYTHONPATH misses packages: {missing}"
