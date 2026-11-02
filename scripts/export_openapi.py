#!/usr/bin/env python
"""Export (or check) the committed OpenAPI contract ``docs/api/openapi.json``.

    python scripts/export_openapi.py            # write the file
    python scripts/export_openapi.py --check    # exit 1 when the file is stale
    python scripts/export_openapi.py --stdout   # print instead of writing

The document is generated from the app with the default flag state (verdict v2
off, so its alpha route stays hidden), sorted keys, LF endings and no
environment-specific values, so it is identical on Windows and Linux.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docs" / "api" / "openapi.json"
_SCRUBBED_PREFIXES = ("RADIUS_", "API_", "DATABASE_", "GITHUB_", "OTEL_")


def _prepare_environment() -> None:
    """Pin the environment so the export does not depend on the caller's shell."""

    for key in [k for k in os.environ if k.startswith(_SCRUBBED_PREFIXES)]:
        del os.environ[key]
    os.environ["RADIUS_ENV"] = "test"
    os.environ["RADIUS_ALLOW_INSECURE_DEV"] = "true"
    for src in sorted([*ROOT.glob("apps/*/src"), *ROOT.glob("packages/*/src")]):
        if str(src) not in sys.path:
            sys.path.append(str(src))


def generate_spec() -> dict:
    """Build the app with default settings and return its OpenAPI document."""

    _prepare_environment()
    from radius_api.config import get_api_settings
    from radius_api.main import create_app

    get_api_settings.cache_clear()
    return create_app().openapi()


def render(spec: dict) -> str:
    """Serialise deterministically (sorted keys, ASCII, trailing newline)."""

    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the file is stale")
    parser.add_argument("--stdout", action="store_true", help="print the document")
    parser.add_argument("--output", type=Path, default=SPEC_PATH)
    args = parser.parse_args(argv)

    text = render(generate_spec())
    if args.stdout:
        sys.stdout.write(text)
        return 0
    if args.check:
        current = args.output.read_bytes().decode("utf-8") if args.output.exists() else ""
        if current.replace("\r\n", "\n") != text:
            print(
                f"{args.output} is stale. Run: python scripts/export_openapi.py",
                file=sys.stderr,
            )
            return 1
        print(f"{args.output} is up to date.")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(text.encode("utf-8"))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
