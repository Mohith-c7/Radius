"""Symbol-level impact analysis (F-08): mapping, reachability, safe fallbacks."""

from __future__ import annotations

from radius_graph.symbol_impact import PythonSymbolGraph, SymbolImpact

LIB = """\
def helper():
    return 1


def other():
    return 2


class Box:
    size = 3

    def get(self):
        return helper()

    def __len__(self):
        return 0
"""


def _impact(
    sources: dict[str, str],
    path: str,
    added: set[int] = frozenset(),  # type: ignore[assignment]
    deleted_at: set[int] = frozenset(),  # type: ignore[assignment]
    deleted_text: tuple[str, ...] = (),
) -> SymbolImpact:
    graph = PythonSymbolGraph(sources)
    mapping = graph.map_changes(path, added, deleted_at, deleted_text)
    return graph.impact(path, mapping, dependents_of=lambda p: frozenset({p}))


def test_line_in_function_maps_to_that_function_only() -> None:
    graph = PythonSymbolGraph({"lib.py": LIB})
    mapping = graph.map_changes("lib.py", {2}, (), ())
    assert mapping.symbols == ("lib.py::helper",)
    assert mapping.fallback_reason is None


def test_decorator_line_belongs_to_the_decorated_function() -> None:
    src = "import functools\n\n@functools.cache\ndef f():\n    return 1\n"
    graph = PythonSymbolGraph({"d.py": src})
    assert graph.map_changes("d.py", {3}, (), ()).symbols == ("d.py::f",)


def test_module_level_edit_is_a_fallback() -> None:
    graph = PythonSymbolGraph({"lib.py": "LIMIT = 1\n\n\ndef f():\n    return LIMIT\n"})
    assert graph.map_changes("lib.py", {1}, (), ()).fallback_reason


def test_blank_or_comment_outside_definitions_is_not_code() -> None:
    graph = PythonSymbolGraph({"lib.py": "# note\n\n\ndef f():\n    return 1\n"})
    mapping = graph.map_changes("lib.py", {1, 2}, (), ())
    assert "only blank or comment" in (mapping.fallback_reason or "")


def test_deleted_definition_falls_back() -> None:
    graph = PythonSymbolGraph({"lib.py": "def f():\n    return 1\n"})
    mapping = graph.map_changes("lib.py", (), {2}, ("def gone():", "    pass"))
    assert "deleted" in (mapping.fallback_reason or "")


def test_deletion_inside_function_body_maps_to_function() -> None:
    graph = PythonSymbolGraph({"lib.py": "def f():\n    a = 1\n    return a\n"})
    mapping = graph.map_changes("lib.py", (), {3}, ("    b = 2",))
    assert mapping.symbols == ("lib.py::f",)


def test_implicit_protocol_method_change_falls_back() -> None:
    graph = PythonSymbolGraph({"lib.py": LIB})
    assert "implicit protocol" in (graph.map_changes("lib.py", {15}, (), ()).fallback_reason or "")


def test_class_attribute_change_seeds_class_members_and_attribute_name() -> None:
    sources = {"lib.py": LIB, "use.py": "def uses(b):\n    return b.size\n"}
    impact = _impact(sources, "lib.py", {10})
    assert "lib.py::Box.get" in impact.changed_symbols
    assert "use.py::uses" in impact.impacted_symbols


def test_callers_are_found_by_name_across_files_and_methods() -> None:
    sources = {
        "lib.py": LIB,
        "app.py": "from lib import helper\n\n\ndef run():\n    return helper()\n",
        "unrelated.py": "def nothing():\n    return 0\n",
    }
    impact = _impact(sources, "lib.py", {2})
    assert {"app.py::run", "lib.py::Box.get"} <= impact.impacted_symbols
    assert "unrelated.py" not in impact.impacted_files
    assert impact.chain("app.py::run") == ("app.py::run", "lib.py::helper")


def test_import_alias_and_reexport_are_followed() -> None:
    sources = {
        "impl.py": "def real():\n    return 1\n",
        "pkg.py": "from impl import real as exported\n",
        "user.py": "from pkg import exported as e\n\n\ndef go():\n    return e()\n",
    }
    assert "user.py::go" in _impact(sources, "impl.py", {2}).impacted_symbols


def test_assignment_alias_is_followed() -> None:
    sources = {
        "impl.py": "def real():\n    return 1\n\n\nfast = real\n",
        "user.py": "from impl import fast\n\n\ndef go():\n    return fast()\n",
    }
    assert "user.py::go" in _impact(sources, "impl.py", {2}).impacted_symbols


def test_decorator_and_callback_use_are_references() -> None:
    sources = {
        "impl.py": "def deco(fn):\n    return fn\n\n\ndef cb():\n    return 1\n",
        "user.py": (
            "from impl import deco, cb\n\n\n@deco\ndef decorated():\n    return 2\n\n\n"
            "def registers():\n    return sorted([], key=cb)\n"
        ),
    }
    assert "user.py::decorated" in _impact(sources, "impl.py", {2}).impacted_symbols
    assert "user.py::registers" in _impact(sources, "impl.py", {6}).impacted_symbols


def test_mock_patch_string_target_is_a_reference() -> None:
    sources = {
        "impl.py": "def real():\n    return 1\n",
        "test_x.py": "def test_it(mocker):\n    mocker.patch('impl.real')\n",
    }
    assert "test_x.py::test_it" in _impact(sources, "impl.py", {2}).impacted_symbols


def test_pytest_fixture_is_reached_through_parameter_name() -> None:
    sources = {
        "impl.py": "def real():\n    return 1\n",
        "test_x.py": (
            "import pytest\nfrom impl import real\n\n\n@pytest.fixture\n"
            "def thing():\n    return real()\n\n\ndef test_it(thing):\n    assert thing\n"
        ),
    }
    assert "test_x.py::test_it" in _impact(sources, "impl.py", {2}).impacted_symbols


def test_autouse_fixture_impacts_whole_scope() -> None:
    sources = {
        "impl.py": "def real():\n    return 1\n",
        "tests/conftest.py": (
            "import pytest\nfrom impl import real\n\n\n@pytest.fixture(autouse=True)\n"
            "def setup():\n    real()\n"
        ),
    }
    assert "tests" in _impact(sources, "impl.py", {2}).broad_scopes


def test_import_time_use_reaches_the_module() -> None:
    sources = {
        "impl.py": "def real():\n    return 1\n",
        "user.py": "from impl import real\n\nVALUE = real()\n",
    }
    impact = _impact(sources, "impl.py", {2})
    assert "user.py::<module>" in impact.impacted_symbols
    assert "user.py" in impact.module_reached_files


def test_impact_reaching_a_dunder_falls_back() -> None:
    sources = {
        "impl.py": "def real():\n    return 1\n",
        "user.py": "from impl import real\n\n\nclass C:\n    def __enter__(self):\n        return real()\n",
    }
    assert "protocol" in (_impact(sources, "impl.py", {2}).fallback_reason or "")


def test_init_change_reaches_class_users() -> None:
    sources = {
        "impl.py": "class C:\n    def __init__(self):\n        self.x = 1\n",
        "user.py": "from impl import C\n\n\ndef make():\n    return C()\n",
    }
    assert "user.py::make" in _impact(sources, "impl.py", {3}).impacted_symbols


def test_unparseable_file_falls_back_and_dynamic_calls_are_listed() -> None:
    graph = PythonSymbolGraph(
        {"bad.py": "def (:\n", "dyn.py": "import importlib\n\n\ndef f(n):\n    return importlib.import_module(n)\n"}
    )
    assert graph.map_changes("bad.py", {1}, (), ()).fallback_reason
    assert "import_module" in graph.dynamic_files()["dyn.py"][0]


def test_result_is_deterministic() -> None:
    sources = {"lib.py": LIB, "a.py": "from lib import helper\n\n\ndef a():\n    helper()\n"}
    first = _impact(sources, "lib.py", {2})
    second = _impact(dict(reversed(list(sources.items()))), "lib.py", {2})
    assert first.impacted_symbols == second.impacted_symbols
    assert first.parents == second.parents
