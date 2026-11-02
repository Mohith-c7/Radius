"""Make the shared test helpers importable under ``--import-mode=importlib``."""

import sys
from pathlib import Path

HERE = str(Path(__file__).parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
