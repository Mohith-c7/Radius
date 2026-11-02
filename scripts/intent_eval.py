#!/usr/bin/env python
"""CLI wrapper for the intent extraction metrics harness (IN-10).

Equivalent to ``python -m radius_intent.evaluation``; adds the package source
directories to ``sys.path`` so it runs from a plain checkout.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for src in ("packages/intent/src", "packages/shared/src"):
    path = str(ROOT / src)
    if path not in sys.path:
        sys.path.insert(0, path)

from radius_intent.evaluation.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
