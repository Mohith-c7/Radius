"""The LLM/Gemini SDKs are optional extras: app packages must import without them."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

_BLOCKED = ("google.genai", "google.generativeai", "anthropic")

_SCRIPT = textwrap.dedent(
    r"""
    import importlib.abc, sys

    BLOCKED = {blocked!r}

    class Blocker(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name in BLOCKED or name.split(".")[0] == "anthropic":
                raise ImportError("blocked for test: " + name)
            return None

    sys.meta_path.insert(0, Blocker())
    for mod in list(sys.modules):
        if mod in BLOCKED or mod.startswith(("google.genai", "google.generativeai", "anthropic")):
            del sys.modules[mod]

    import radius_analysis.ai.pruner as pruner
    import radius_worker.orchestrator
    import radius_api.dependencies
    import app.main

    assert pruner.genai is None, "SDK should be unavailable in this probe"
    p = pruner.SemanticPruner(api_key="dummy")  # must not raise
    assert p.evaluate_impact("def a(): pass", "- x+ y") is True  # conservative
    assert pruner.SemanticPruner(api_key="").evaluate_impact("a", "b") is True
    print("ok")
    """
).format(blocked=_BLOCKED)


def test_app_packages_import_without_llm_sdks():
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().endswith("ok")
