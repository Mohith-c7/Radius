"""T012 near misses: first-party modules found through declared import roots."""

SRC = "def price(n):\n    return n * 2\n"
PYPROJECT_PATH = (
    '[tool.pytest.ini_options]\npythonpath = ["packages/a/src"]\n'
    '[project]\nname = "x"\ndependencies = ["requests"]\n'
)
PYPROJECT_DIR = (
    '[tool.setuptools]\npackage-dir = {"" = "lib"}\n'
    '[project]\nname = "x"\ndependencies = ["requests"]\n'
)
PYPROJECT_FIND = (
    '[tool.setuptools.packages.find]\nwhere = ["lib"]\n'
    '[project]\nname = "x"\ndependencies = ["requests"]\n'
)
PYTEST_INI = "[pytest]\npythonpath =\n    libs/core\n"


def c(id, rule, base, head, expect=(), **kw):
    return dict(id=id, rule=rule, base=base, head=head, expect=list(expect), **kw)


def pair(files, new_path, new_text):
    head = dict(files)
    head[new_path] = new_text
    return files, head


_m = {"pyproject.toml": PYPROJECT_PATH, "packages/a/src/radius_a/__init__.py": "X = 1\n",
      "packages/b/x.py": SRC}
_p = {"pytest.ini": PYTEST_INI, "requirements.txt": "requests\n", "libs/core/corelib.py": "X = 1\n",
      "app.py": SRC}
_d = {"pyproject.toml": PYPROJECT_DIR, "lib/mine.py": "X = 1\n", "app.py": SRC}
_f = {"pyproject.toml": PYPROJECT_FIND, "lib/mine.py": "X = 1\n", "app.py": SRC}

CASES = [
    c("t012-monorepo-pythonpath-local", "T012", *pair(_m, "packages/b/x.py", "import radius_a\n" + SRC)),
    c("t012-pytest-ini-pythonpath-local", "T012", *pair(_p, "app.py", "import corelib\n" + SRC)),
    c("t012-setuptools-package-dir-local", "T012", *pair(_d, "app.py", "import mine\n" + SRC)),
    c("t012-setuptools-find-where-local", "T012", *pair(_f, "app.py", "import mine\n" + SRC)),
]
