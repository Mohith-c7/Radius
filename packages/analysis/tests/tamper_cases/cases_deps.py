"""Table-driven cases for T012 (dependency hallucination and lockfile drift)."""

SRC = "def price(n):\n    return n * 2\n"
GUARDED = (
    "try:\n    import pytimeparse_ultra\nexcept ImportError:\n    pytimeparse_ultra = None\n\n\n" + SRC
)
UV_LOCK = 'version = 1\n\n[[package]]\nname = "requests"\nversion = "2.32.0"\n'


def c(id, rule, base, head, expect=(), **kw):
    return dict(id=id, rule=rule, base=base, head=head, expect=list(expect), **kw)


CASES = [
    c("t012-guarded-import", "T012", {"src/shop.py": SRC, "requirements.txt": "# none\n"},
      {"src/shop.py": GUARDED, "requirements.txt": "pytimeparse-ultra==3.1.4\n"},
      ["T012:unverified_guarded_import"]),
    c("t012-unverified-no-import", "T012", {"requirements.txt": "# none\n"},
      {"requirements.txt": "frobnicator-core>=1.0\n"}, ["T012:unverified_new_dependency"]),
    c("t012-registry-missing", "T012", {"requirements.txt": "# none\n"},
      {"requirements.txt": "frobnicator-core>=1.0\n"}, ["T012:registry_missing"],
      config={"params": {"use_registry": True}}, registry=["requests"]),
    c("t012-typosquat", "T012", {"requirements.txt": "# none\n"},
      {"requirements.txt": "requets==2.0.0\n"}, ["T012:typosquat"]),
    c("t012-lockfile-drift", "T012", {"requirements.txt": "requests\n", "uv.lock": UV_LOCK},
      {"requirements.txt": "requests\nfrobnicator-core\n", "uv.lock": UV_LOCK}, ["T012:lockfile_drift"]),
    c("t012-pyproject-new-dep", "T012",
      {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["requests"]\n'},
      {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["requests", "frobnicator-core>=1"]\n'},
      ["T012:unverified_new_dependency"]),
    c("t012-undeclared-import", "T012",
      {"src/shop.py": SRC, "requirements.txt": "requests\n"},
      {"src/shop.py": "import frobnicator\n" + SRC, "requirements.txt": "requests\n"}, ["T012:undeclared_import"]),
    c("t012-popular-dep", "T012", {"requirements.txt": "# none\n"}, {"requirements.txt": "requests==2.32.0\n"}, []),
    c("t012-locked-dep", "T012", {"requirements.txt": "requests\n", "uv.lock": UV_LOCK},
      {"requirements.txt": "requests\nrequests\n", "uv.lock": UV_LOCK}, []),
    c("t012-registry-confirms", "T012", {"requirements.txt": "# none\n"},
      {"requirements.txt": "frobnicator-core>=1.0\n"}, [],
      config={"params": {"use_registry": True}}, registry=["frobnicator-core"]),
    c("t012-registry-off-by-default", "T012", {"requirements.txt": "# none\n"},
      {"requirements.txt": "frobnicator-core>=1.0\n"}, ["T012:unverified_new_dependency"],
      registry=["requests"]),
    c("t012-dep-removed", "T012", {"requirements.txt": "frobnicator-core\n"}, {"requirements.txt": "# none\n"}, []),
    c("t012-stdlib-import", "T012", {"src/shop.py": SRC, "requirements.txt": "requests\n"},
      {"src/shop.py": "import json\nimport os.path\n" + SRC, "requirements.txt": "requests\n"}, []),
    c("t012-local-import", "T012",
      {"src/shop.py": SRC, "src/helpers.py": "X = 1\n", "requirements.txt": "requests\n"},
      {"src/shop.py": "import helpers\n" + SRC, "src/helpers.py": "X = 1\n", "requirements.txt": "requests\n"}, []),
    c("t012-declared-import-alias", "T012", {"src/shop.py": SRC, "requirements.txt": "pyyaml\n"},
      {"src/shop.py": "import yaml\n" + SRC, "requirements.txt": "pyyaml\n"}, []),
    c("t012-no-manifest-no-judgement", "T012", {"src/shop.py": SRC},
      {"src/shop.py": "import frobnicator\n" + SRC}, []),
    c("t012-guarded-optional-import", "T012", {"src/shop.py": SRC, "requirements.txt": "requests\n"},
      {"src/shop.py": "try:\n    import ujson\nexcept ImportError:\n    ujson = None\n" + SRC,
       "requirements.txt": "requests\n"}, []),
    c("t012-comment-only-manifest-change", "T012", {"requirements.txt": "requests\n"},
      {"requirements.txt": "requests\n# pinned by security\n"}, []),
    c("t012-test-imports-pytest", "T012",
      {"tests/test_a.py": "def test_a():\n    assert 1\n", "requirements.txt": "requests\n"},
      {"tests/test_a.py": "import pytest\n\n\ndef test_a():\n    assert 1\n", "requirements.txt": "requests\n"}, []),
]
