"""Make the test helper module importable by bare name (pytest importlib mode)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
