"""Keep pytest from collecting the fixture repositories as part of Radius' suite.

The fixtures contain deliberately weak, skipped and failing tests. They are run
in isolation by ``loader.py`` / ``benchmarks/test_intent_fixtures.py``.
"""

collect_ignore_glob = ["*"]
