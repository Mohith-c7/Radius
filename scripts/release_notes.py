"""Release helpers: notes from changelog fragments and a version-consistency check.

Usage:
    python scripts/release_notes.py notes [--version 0.1.0] [--dir changelog.d]
    python scripts/release_notes.py check-versions [--tag v0.1.0]

``notes`` prints Markdown grouped by Keep-a-Changelog category from
``changelog.d/<slug>.<category>.md`` fragments (README.md is ignored). It reads
local files only. ``check-versions`` fails when the version declared in
``pyproject.toml``, the ``package.json`` files, ``clients/python/pyproject.toml``
and the ``ARG RADIUS_VERSION`` default of each Dockerfile disagree, or differ
from the release tag. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = ("added", "changed", "deprecated", "removed", "fixed", "security")
TAG = re.compile(r"^v(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$")
TOML_VERSION = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
DOCKER_ARG = re.compile(r"^ARG RADIUS_VERSION=(\S+)", re.MULTILINE)


def parse_tag(tag: str) -> str:
    """Return the version for a ``vX.Y.Z[-pre]`` tag; raise ValueError otherwise."""

    match = TAG.match(tag.strip())
    if not match:
        msg = f"tag {tag!r} is not of the form vX.Y.Z or vX.Y.Z-prerelease"
        raise ValueError(msg)
    return match.group(1)


def collect_fragments(directory: Path) -> dict[str, list[str]]:
    """Map category -> fragment texts (sorted by file name). Unknown categories raise."""

    found: dict[str, list[str]] = {}
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        parts = path.name.split(".")
        category = parts[-2] if len(parts) >= 3 else ""
        if category not in CATEGORIES:
            msg = f"{path.name}: category {category!r} is not one of {', '.join(CATEGORIES)}"
            raise ValueError(msg)
        text = " ".join(path.read_text(encoding="utf-8").split())
        if text:
            found.setdefault(category, []).append(text)
    return found


def render_notes(fragments: dict[str, list[str]], version: str | None = None) -> str:
    lines = [f"## Radius {version}" if version else "## Release notes", ""]
    if not fragments:
        lines += ["No changelog fragments were found.", ""]
    for category in CATEGORIES:
        items = fragments.get(category)
        if not items:
            continue
        lines += [f"### {category.capitalize()}", ""]
        lines += [f"- {item}" for item in items]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def declared_versions(root: Path) -> dict[str, str]:
    """Version string per source file (relative path -> version)."""

    versions: dict[str, str] = {}
    for rel in ("pyproject.toml", "clients/python/pyproject.toml"):
        path = root / rel
        if path.exists():
            match = TOML_VERSION.search(path.read_text(encoding="utf-8"))
            if match:
                versions[rel] = match.group(1)
    for path in sorted(root.glob("package.json")) + sorted(root.glob("apps/*/package.json")) + sorted(
        root.glob("packages/*/package.json")
    ):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "version" in data:
            versions[path.relative_to(root).as_posix()] = str(data["version"])
    for path in sorted(root.glob("apps/*/Dockerfile")):
        match = DOCKER_ARG.search(path.read_text(encoding="utf-8"))
        if match:
            versions[path.relative_to(root).as_posix()] = match.group(1)
    return versions


def version_problems(versions: dict[str, str], tag: str | None = None) -> list[str]:
    problems: list[str] = []
    if not versions:
        return ["no versions found"]
    expected = parse_tag(tag) if tag else versions.get("pyproject.toml") or next(iter(versions.values()))
    for name, value in sorted(versions.items()):
        if value != expected:
            problems.append(f"{name}: {value} != {expected}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    notes = sub.add_parser("notes")
    notes.add_argument("--version")
    notes.add_argument("--dir", type=Path, default=ROOT / "changelog.d")
    check = sub.add_parser("check-versions")
    check.add_argument("--tag")
    check.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        if args.command == "notes":
            sys.stdout.write(render_notes(collect_fragments(args.dir), args.version))
            return 0
        problems = version_problems(declared_versions(args.root), args.tag)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    print("version check:", "FAILED" if problems else "ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
