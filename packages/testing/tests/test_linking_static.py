"""Table-driven tests for the static symbol-to-test linker (LK-03)."""

from __future__ import annotations

import textwrap
import time

import pytest
from radius_testing.linking import LinkTarget, StaticLinker
from radius_testing.linking.model import LinkKind, normalize_test_id

MOD = "pkg/mod.py"
FUNC_SRC = "def f(x):\n    return x + 1\n\n\ndef g(x):\n    return x\n"
PKG = {"pkg/__init__.py": "", MOD: FUNC_SRC}


def d(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def project(*extra: dict[str, str], base: dict[str, str] | None = None) -> dict[str, str]:
    out = dict(PKG if base is None else base)
    for part in extra:
        out.update({k: d(v) for k, v in part.items()})
    return out


def target(path: str = MOD, qual: str = "f", kind: str = "function") -> LinkTarget:
    return LinkTarget(f"python:{path}::{qual}#{kind}@h", path, qual, kind)


def run(files: dict[str, str], tgt: LinkTarget, **kwargs):
    return StaticLinker(**kwargs).link(files, [tgt])


def check(result, expect: dict[str, str]) -> None:
    by_test = {link.test_id: link for link in result.links}
    for test_id, want in expect.items():
        link = by_test.get(test_id)
        if want == "absent":
            assert link is None or link.score < 0.3, f"{test_id}: unexpected {link}"
        elif want == "low":
            assert link is not None and link.low_confidence and link.score < 0.35, f"{test_id}: {link}"
        elif want == "weak":
            assert link is not None and link.score <= 0.5, f"{test_id}: {link}"
        else:
            assert link is not None, f"{test_id}: no link; have {sorted(by_test)}"
            kind, _, depth = want.partition(":")
            assert link.kind.value == kind, f"{test_id}: {link.kind} != {kind} ({link.evidence})"
            if depth:
                assert link.depth == int(depth), f"{test_id}: depth {link.depth}"
            assert link.score >= 0.2


T = "tests/test_a.py"
CASES: list[tuple[str, dict[str, str], LinkTarget, dict[str, str], dict]] = []


def case(name, files, tgt=None, expect=None, **kw):
    CASES.append((name, files, tgt or target(), expect or {}, kw))


# ---- direct references, imports and aliases ---------------------------------
case("from_import_call", project({T: "from pkg.mod import f\n\ndef test_x():\n    assert f(1) == 2\n"}), expect={f"{T}::test_x": "direct_call"})
case("from_import_alias", project({T: "from pkg.mod import f as ff\n\ndef test_x():\n    ff(1)\n"}), expect={f"{T}::test_x": "direct_call"})
case("import_module_attr", project({T: "import pkg.mod\n\ndef test_x():\n    pkg.mod.f(1)\n"}), expect={f"{T}::test_x": "direct_call"})
case("import_module_alias", project({T: "import pkg.mod as m\n\ndef test_x():\n    m.f(1)\n"}), expect={f"{T}::test_x": "direct_call"})
case("from_pkg_import_module", project({T: "from pkg import mod\n\ndef test_x():\n    mod.f(1)\n"}), expect={f"{T}::test_x": "direct_call"})
case("from_pkg_import_module_alias", project({T: "from pkg import mod as mm\n\ndef test_x():\n    mm.f(1)\n"}), expect={f"{T}::test_x": "direct_call"})
case("relative_import_in_package", project({"pkg/test_mod.py": "from .mod import f\n\ndef test_x():\n    f(1)\n"}), expect={"pkg/test_mod.py::test_x": "direct_call"})
case("relative_module_import", project({"pkg/test_mod.py": "from . import mod\n\ndef test_x():\n    mod.f(1)\n"}), expect={"pkg/test_mod.py::test_x": "direct_call"})
case("reference_not_called", project({T: "from pkg.mod import f\n\ndef test_x():\n    cb = [f]\n    assert cb\n"}), expect={f"{T}::test_x": "import_reference"})
case("local_alias", project({T: "from pkg.mod import f\n\ndef test_x():\n    h = f\n    h(1)\n"}), expect={f"{T}::test_x": "direct_call"})
case("module_attr_alias", project({T: "import pkg.mod as m\n\ndef test_x():\n    h = m.f\n    h(1)\n"}), expect={f"{T}::test_x": "direct_call"})
case("deep_package_chain", {"pkg/__init__.py": "", "pkg/sub/__init__.py": "", "pkg/sub/mod.py": FUNC_SRC, T: d("import pkg.sub.mod\n\ndef test_x():\n    pkg.sub.mod.f(1)\n")}, target("pkg/sub/mod.py"), {f"{T}::test_x": "direct_call"})
case("deep_from_import_alias", {"pkg/__init__.py": "", "pkg/sub/__init__.py": "", "pkg/sub/mod.py": FUNC_SRC, T: d("from pkg.sub import mod as m\n\ndef test_x():\n    m.f(1)\n")}, target("pkg/sub/mod.py"), {f"{T}::test_x": "direct_call"})
case("star_import", project({T: "from pkg.mod import *\n\ndef test_x():\n    f(1)\n"}), expect={f"{T}::test_x": "direct_call"})
case("reexport_via_init", {"pkg/__init__.py": "from .mod import f\n", MOD: FUNC_SRC, T: d("from pkg import f\n\ndef test_x():\n    f(1)\n")}, expect={f"{T}::test_x": "direct_call"})
case("src_layout", {"src/pkg/__init__.py": "", "src/pkg/mod.py": FUNC_SRC, T: d("from pkg.mod import f\n\ndef test_x():\n    f(1)\n")}, target("src/pkg/mod.py"), {f"{T}::test_x": "direct_call"})
case("flat_module_pythonpath", {"src/pricing.py": FUNC_SRC, T: d("from pricing import f\n\ndef test_x():\n    f(1)\n")}, target("src/pricing.py"), {f"{T}::test_x": "direct_call"})
case("test_file_suffix_test_py", project({"tests/a_test.py": "from pkg.mod import f\n\ndef test_x():\n    f(1)\n"}), expect={"tests/a_test.py::test_x": "direct_call"})
case("nested_function_in_test", project({T: "from pkg.mod import f\n\ndef test_x():\n    def inner():\n        return f(1)\n    inner()\n"}), expect={f"{T}::test_x": "direct_call"})
case("lambda_in_test", project({T: "from pkg.mod import f\n\ndef test_x():\n    run = lambda: f(1)\n    run()\n"}), expect={f"{T}::test_x": "direct_call"})
case("async_function", {"pkg/__init__.py": "", MOD: "async def f(x):\n    return x\n", T: d("from pkg.mod import f\n\nasync def test_x():\n    await f(1)\n")}, expect={f"{T}::test_x": "direct_call"})
case("import_only_unused", project({T: "from pkg.mod import f\n\ndef test_x():\n    assert True\n"}), expect={f"{T}::test_x": "weak"})
case("module_level_call_in_test_file", project({T: "from pkg.mod import f\nRESULT = f(1)\n\ndef test_x():\n    assert RESULT\n"}), expect={f"{T}::test_x": "fixture_dependency"})
case("local_name_shadows_import", project({T: "from pkg.mod import f\n\ndef test_x():\n    f = lambda v: v\n    f(1)\n"}), expect={f"{T}::test_x": "absent"})
case("parameter_shadows_import", project({T: "from pkg.mod import f\n\ndef test_x(f=None):\n    f and f(1)\n"}), expect={f"{T}::test_x": "absent"})
case("unrelated_test", project({T: "def test_x():\n    assert 1 + 1 == 2\n"}), expect={f"{T}::test_x": "absent"})

# ---- classes and methods ----------------------------------------------------
CLS = "class C:\n    def m(self):\n        return 1\n\n    @classmethod\n    def make(cls):\n        return cls()\n\n    @staticmethod\n    def util():\n        return 2\n\n\nclass D:\n    def m(self):\n        return 2\n"
CPKG = {"pkg/__init__.py": "", MOD: CLS}
case("class_instantiation_target_class", project({T: "from pkg.mod import C\n\ndef test_x():\n    C()\n"}, base=CPKG), target(qual="C", kind="class"), {f"{T}::test_x": "direct_call"})
case("method_after_instantiation", project({T: "from pkg.mod import C\n\ndef test_x():\n    C().m()\n"}, base=CPKG), target(qual="C.m", kind="method"), {f"{T}::test_x": "direct_call"})
case("method_via_variable", project({T: "from pkg.mod import C\n\ndef test_x():\n    obj = C()\n    obj.m()\n"}, base=CPKG), target(qual="C.m", kind="method"), {f"{T}::test_x": "direct_call"})
case("class_only_method_unresolved", project({T: "from pkg.mod import C\n\ndef test_x():\n    C()\n"}, base=CPKG), target(qual="C.m", kind="method"), {f"{T}::test_x": "weak"})
case("classmethod_call", project({T: "from pkg.mod import C\n\ndef test_x():\n    C.make()\n"}, base=CPKG), target(qual="C.make", kind="method"), {f"{T}::test_x": "direct_call"})
case("staticmethod_call", project({T: "from pkg.mod import C\n\ndef test_x():\n    C.util()\n"}, base=CPKG), target(qual="C.util", kind="method"), {f"{T}::test_x": "direct_call"})
case("same_method_name_other_class", project({T: "from pkg.mod import D\n\ndef test_x():\n    D().m()\n"}, base=CPKG), target(qual="C.m", kind="method"), {f"{T}::test_x": "absent"})
case("changed_class_hit_by_method_call", project({T: "from pkg.mod import C\n\ndef test_x():\n    C().m()\n"}, base=CPKG), target(qual="C", kind="class"), {f"{T}::test_x": "direct_call"})
case("inherited_method_via_subclass", {"pkg/__init__.py": "", MOD: "class Base:\n    def m(self):\n        return 1\n\n\nclass Sub(Base):\n    pass\n", T: d("from pkg.mod import Sub\n\ndef test_x():\n    Sub().m()\n")}, target(qual="Base.m", kind="method"), {f"{T}::test_x": "direct_call"})
case("self_method_helper_in_test_class", project({T: "from pkg.mod import f\n\nclass TestA:\n    def helper(self):\n        return f(1)\n\n    def test_x(self):\n        self.helper()\n"}), expect={f"{T}::TestA::test_x": "indirect_call:1"})
case("unresolved_receiver_is_low", project({T: "def test_x(obj):\n    obj.m()\n"}, base=CPKG), target(qual="C.m", kind="method"), {f"{T}::test_x": "low"})
case("module_symbol_target", project({T: "from pkg.mod import f\n\ndef test_x():\n    f(1)\n"}), target(qual="<module>", kind="module"), {f"{T}::test_x": "direct_call"})
case("locals_target_maps_to_outer", {"pkg/__init__.py": "", MOD: "def outer():\n    def inner():\n        return 1\n    return inner()\n", T: d("from pkg.mod import outer\n\ndef test_x():\n    outer()\n")}, target(qual="outer.<locals>.inner"), {f"{T}::test_x": "direct_call"})

# ---- indirect calls and depth limits ----------------------------------------
CHAIN = {"pkg/__init__.py": "", MOD: "def f(x):\n    return x\n", "pkg/a.py": "from pkg.mod import f\n\ndef a1(x):\n    return f(x)\n\ndef a2(x):\n    return a1(x)\n\ndef a3(x):\n    return a2(x)\n\ndef a4(x):\n    return a3(x)\n"}
case("indirect_depth1", project({T: "from pkg.a import a1\n\ndef test_x():\n    a1(1)\n"}, base=CHAIN), expect={f"{T}::test_x": "indirect_call:1"})
case("indirect_depth2", project({T: "from pkg.a import a2\n\ndef test_x():\n    a2(1)\n"}, base=CHAIN), expect={f"{T}::test_x": "indirect_call:2"})
case("indirect_depth3_default_limit", project({T: "from pkg.a import a3\n\ndef test_x():\n    a3(1)\n"}, base=CHAIN), expect={f"{T}::test_x": "indirect_call:3"})
case("indirect_depth4_beyond_limit", project({T: "from pkg.a import a4\n\ndef test_x():\n    a4(1)\n"}, base=CHAIN), expect={f"{T}::test_x": "absent"})
case("custom_depth_limit_1", project({T: "from pkg.a import a2\n\ndef test_x():\n    a2(1)\n"}, base=CHAIN), expect={f"{T}::test_x": "absent"}, max_depth=1)
case("custom_depth_limit_4", project({T: "from pkg.a import a4\n\ndef test_x():\n    a4(1)\n"}, base=CHAIN), expect={f"{T}::test_x": "indirect_call:4"}, max_depth=4)
case("depth_zero_only_direct", project({T: "from pkg.a import a1\nfrom pkg.mod import f\n\ndef test_x():\n    a1(1)\n\ndef test_y():\n    f(1)\n"}, base=CHAIN), expect={f"{T}::test_x": "absent", f"{T}::test_y": "direct_call"}, max_depth=0)
case("helper_in_test_file", project({T: "from pkg.mod import f\n\ndef _helper():\n    return f(1)\n\ndef test_x():\n    _helper()\n"}), expect={f"{T}::test_x": "indirect_call:1"})
case("helper_in_tests_module", project({"tests/helpers.py": "from pkg.mod import f\n\ndef build():\n    return f(1)\n", T: "from tests.helpers import build\n\ndef test_x():\n    build()\n"}), expect={f"{T}::test_x": "indirect_call:1"})
case("direct_beats_indirect", project({T: "from pkg.a import a1\nfrom pkg.mod import f\n\ndef test_x():\n    a1(1)\n    f(1)\n"}, base=CHAIN), expect={f"{T}::test_x": "direct_call"})
case("cycle_does_not_hang", {"pkg/__init__.py": "", MOD: "def f(x):\n    return h(x)\n\ndef h(x):\n    return f(x)\n", T: d("from pkg.mod import h\n\ndef test_x():\n    h(1)\n")}, expect={f"{T}::test_x": "indirect_call:1"})

# ---- name collisions ---------------------------------------------------------
COLL = {"pkg/__init__.py": "", "pkg/a.py": "def helper():\n    return 1\n", "pkg/b.py": "def helper():\n    return 2\n"}
case("collision_other_module_not_linked", project({T: "from pkg.a import helper\n\ndef test_x():\n    helper()\n"}, base=COLL), target("pkg/b.py", "helper"), {f"{T}::test_x": "absent"})
case("collision_right_module_linked", project({T: "from pkg.a import helper\n\ndef test_x():\n    helper()\n"}, base=COLL), target("pkg/a.py", "helper"), {f"{T}::test_x": "direct_call"})
case("collision_module_alias", project({T: "import pkg.a as a\nimport pkg.b as b\n\ndef test_x():\n    a.helper()\n\ndef test_y():\n    b.helper()\n"}, base=COLL), target("pkg/b.py", "helper"), {f"{T}::test_x": "absent", f"{T}::test_y": "direct_call"})
case("stdlib_name_not_shadowing", {"pkg/__init__.py": "", "tests/json.py": "def f():\n    pass\n", T: d("import json\n\ndef test_x():\n    json.dumps(1)\n")}, target("tests/json.py", "f"), {f"{T}::test_x": "absent"})

# ---- patching and string targets ---------------------------------------------
case("patch_decorator", project({T: "from unittest import mock\n\n@mock.patch('pkg.mod.f')\ndef test_x(m):\n    pass\n"}), expect={f"{T}::test_x": "import_reference"})
case("patch_context_manager", project({T: "from unittest.mock import patch\n\ndef test_x():\n    with patch('pkg.mod.f') as m:\n        pass\n"}), expect={f"{T}::test_x": "import_reference"})
case("mocker_patch", project({T: "def test_x(mocker):\n    mocker.patch('pkg.mod.f')\n"}), expect={f"{T}::test_x": "import_reference"})
case("monkeypatch_setattr_string", project({T: "def test_x(monkeypatch):\n    monkeypatch.setattr('pkg.mod.f', lambda x: 0)\n"}), expect={f"{T}::test_x": "import_reference"})
case("monkeypatch_setattr_obj", project({T: "import pkg.mod as m\n\ndef test_x(monkeypatch):\n    monkeypatch.setattr(m, 'f', lambda x: 0)\n"}), expect={f"{T}::test_x": "import_reference"})
case("patch_object", project({T: "from unittest import mock\nimport pkg.mod as m\n\ndef test_x():\n    with mock.patch.object(m, 'f'):\n        pass\n"}), expect={f"{T}::test_x": "import_reference"})
case("patch_method_string", project({T: "from unittest import mock\n\ndef test_x():\n    with mock.patch('pkg.mod.C.m'):\n        pass\n"}, base=CPKG), target(qual="C.m", kind="method"), {f"{T}::test_x": "import_reference"})
case("patch_reexport_target", {"pkg/__init__.py": "from .mod import f\n", MOD: FUNC_SRC, "pkg/user.py": "from pkg import f\n\ndef use():\n    return f(1)\n", T: d("from unittest import mock\n\ndef test_x():\n    with mock.patch('pkg.user.f'):\n        pass\n")}, expect={f"{T}::test_x": "import_reference"})
case("getattr_constant", project({T: "import pkg.mod as m\n\ndef test_x():\n    getattr(m, 'f')(1)\n"}), expect={f"{T}::test_x": "import_reference"})
case("getattr_dynamic_low_confidence", project({T: "import pkg.mod as m\n\ndef test_x(name):\n    getattr(m, name)(1)\n"}), expect={f"{T}::test_x": "low"})
case("importlib_dynamic_low_confidence", project({T: "import importlib\nimport pkg.mod\n\ndef test_x():\n    importlib.import_module('pkg.' + 'mod').f(1)\n"}), expect={f"{T}::test_x": "low"})
case("patch_string_other_module", project({T: "from unittest import mock\n\ndef test_x():\n    with mock.patch('pkg.mod.g'):\n        pass\n"}), expect={f"{T}::test_x": "absent"})

# ---- fixtures and conftest ---------------------------------------------------
FX = "import pytest\nfrom pkg.mod import f\n\n@pytest.fixture\ndef val():\n    return f(1)\n"
case("fixture_in_test_file", project({T: FX + "\ndef test_x(val):\n    assert val\n"}), expect={f"{T}::test_x": "fixture_dependency:1"})
case("fixture_chain_two_levels", project({T: FX + "\n@pytest.fixture\ndef wrapped(val):\n    return val\n\ndef test_x(wrapped):\n    assert wrapped\n"}), expect={f"{T}::test_x": "fixture_dependency:2"})
case("fixture_not_requested", project({T: FX + "\ndef test_x():\n    assert True\n"}), expect={f"{T}::test_x": "weak"})
case("conftest_same_dir", project({"tests/conftest.py": FX, T: "def test_x(val):\n    assert val\n"}), expect={f"{T}::test_x": "fixture_dependency:1"})
case("conftest_parent_dir", project({"tests/conftest.py": FX, "tests/sub/test_b.py": "def test_x(val):\n    assert val\n"}), expect={"tests/sub/test_b.py::test_x": "fixture_dependency:1"})
case("conftest_sibling_not_visible", project({"tests/other/conftest.py": FX, "tests/sub/test_b.py": "def test_x(val):\n    assert val\n"}), expect={"tests/sub/test_b.py::test_x": "absent"})
case("fixture_override_closest_wins", project({"tests/conftest.py": FX, T: "import pytest\n\n@pytest.fixture\ndef val():\n    return 0\n\ndef test_x(val):\n    assert not val\n"}), expect={f"{T}::test_x": "absent"})
case("fixture_override_requests_parent", project({"tests/conftest.py": FX, T: "import pytest\n\n@pytest.fixture\ndef val(val):\n    return val + 1\n\ndef test_x(val):\n    assert val\n"}), expect={f"{T}::test_x": "fixture_dependency:2"})
case("autouse_conftest", project({"tests/conftest.py": FX.replace("@pytest.fixture", "@pytest.fixture(autouse=True)"), T: "def test_x():\n    assert True\n"}), expect={f"{T}::test_x": "fixture_dependency:1"})
case("autouse_module", project({T: FX.replace("@pytest.fixture", "@pytest.fixture(autouse=True)") + "\ndef test_x():\n    assert True\n"}), expect={f"{T}::test_x": "fixture_dependency:1"})
case("usefixtures_mark", project({T: FX + "\n@pytest.mark.usefixtures('val')\ndef test_x():\n    assert True\n"}), expect={f"{T}::test_x": "fixture_dependency:1"})
case("getfixturevalue", project({T: FX + "\ndef test_x(request):\n    request.getfixturevalue('val')\n"}), expect={f"{T}::test_x": "fixture_dependency:1"})
case("class_scoped_fixture", project({T: "import pytest\nfrom pkg.mod import f\n\nclass TestA:\n    @pytest.fixture\n    def val(self):\n        return f(1)\n\n    def test_x(self, val):\n        assert val\n"}), expect={f"{T}::TestA::test_x": "fixture_dependency:1"})
case("class_fixture_not_visible_to_module_test", project({T: "import pytest\nfrom pkg.mod import f\n\nclass TestA:\n    @pytest.fixture\n    def val(self):\n        return f(1)\n\ndef test_x(val):\n    pass\n"}), expect={f"{T}::test_x": "absent"})
case("fixture_renamed", project({T: "import pytest\nfrom pkg.mod import f\n\n@pytest.fixture(name='thing')\ndef _impl():\n    return f(1)\n\ndef test_x(thing):\n    assert thing\n"}), expect={f"{T}::test_x": "fixture_dependency:1"})
case("fixture_imported_into_module", project({"tests/fixtures.py": FX, T: "from tests.fixtures import val\n\ndef test_x(val):\n    assert val\n"}), expect={f"{T}::test_x": "fixture_dependency:1"})
case("fixture_indirect_via_helper", project({"pkg/a.py": "from pkg.mod import f\n\ndef a1():\n    return f(1)\n", T: "import pytest\nfrom pkg.a import a1\n\n@pytest.fixture\ndef val():\n    return a1()\n\ndef test_x(val):\n    assert val\n"}), expect={f"{T}::test_x": "fixture_dependency:1"})

# ---- parametrisation, classes, inheritance, unittest -------------------------
case("parametrize_callable", project({T: "import pytest\nfrom pkg.mod import f, g\n\n@pytest.mark.parametrize('fn', [f, g])\ndef test_x(fn):\n    assert fn(1)\n"}), expect={f"{T}::test_x": "import_reference"})
case("parametrize_direct_arg_shadows_fixture", project({T: FX + "\n@pytest.mark.parametrize('val', [1, 2])\ndef test_x(val):\n    assert val\n"}), expect={f"{T}::test_x": "absent"})
case("parametrize_calls_target_id_is_function", project({T: "import pytest\nfrom pkg.mod import f\n\n@pytest.mark.parametrize('v', [1, 2, 3])\ndef test_x(v):\n    assert f(v)\n"}), expect={f"{T}::test_x": "direct_call"})
case("test_class_method_id", project({T: "from pkg.mod import f\n\nclass TestA:\n    def test_x(self):\n        f(1)\n"}), expect={f"{T}::TestA::test_x": "direct_call"})
case("class_with_init_not_collected", project({T: "from pkg.mod import f\n\nclass TestA:\n    def __init__(self):\n        pass\n\n    def test_x(self):\n        f(1)\n"}), expect={f"{T}::TestA::test_x": "absent"})
case("non_test_helper_not_a_test", project({T: "from pkg.mod import f\n\ndef check_x():\n    f(1)\n"}), expect={f"{T}::check_x": "absent"})
case("unittest_method", project({T: "import unittest\nfrom pkg.mod import f\n\nclass CaseA(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(f(1), 2)\n"}), expect={f"{T}::CaseA::test_x": "direct_call"})
case("unittest_setup_applies_to_all", project({T: "import unittest\nfrom pkg.mod import f\n\nclass CaseA(unittest.TestCase):\n    def setUp(self):\n        self.v = f(1)\n\n    def test_x(self):\n        self.assertTrue(self.v)\n"}), expect={f"{T}::CaseA::test_x": "fixture_dependency:1"})
case("unittest_setupclass", project({T: "import unittest\nfrom pkg.mod import f\n\nclass CaseA(unittest.TestCase):\n    @classmethod\n    def setUpClass(cls):\n        cls.v = f(1)\n\n    def test_x(self):\n        pass\n"}), expect={f"{T}::CaseA::test_x": "fixture_dependency:1"})
case("inherit_base_in_same_file", project({T: "from pkg.mod import f\n\nclass TestBase:\n    def test_shared(self):\n        f(1)\n\nclass TestChild(TestBase):\n    def test_own(self):\n        pass\n"}), expect={f"{T}::TestChild::test_shared": "direct_call", f"{T}::TestBase::test_shared": "direct_call", f"{T}::TestChild::test_own": "absent"})
case("inherit_base_in_other_module", project({"tests/base.py": "from pkg.mod import f\n\nclass TestBase:\n    def test_shared(self):\n        f(1)\n", T: "from tests.base import TestBase\n\nclass TestChild(TestBase):\n    pass\n"}), expect={f"{T}::TestChild::test_shared": "direct_call"})
case("inherit_unittest_base_setup", project({"tests/base.py": "import unittest\nfrom pkg.mod import f\n\nclass Base(unittest.TestCase):\n    def setUp(self):\n        f(1)\n", T: "from tests.base import Base\n\nclass CaseA(Base):\n    def test_x(self):\n        pass\n"}), expect={f"{T}::CaseA::test_x": "fixture_dependency:1"})
case("override_base_test_method", project({T: "from pkg.mod import f, g\n\nclass TestBase:\n    def test_shared(self):\n        f(1)\n\nclass TestChild(TestBase):\n    def test_shared(self):\n        g(1)\n"}), expect={f"{T}::TestChild::test_shared": "absent", f"{T}::TestBase::test_shared": "direct_call"})
case("unparseable_file_skipped", project({T: "from pkg.mod import f\n\ndef test_x():\n    f(1)\n", "tests/test_bad.py": "def test_y(:\n"}), expect={f"{T}::test_x": "direct_call", "tests/test_bad.py::test_y": "absent"})


@pytest.mark.parametrize(("name", "files", "tgt", "expect", "kwargs"), CASES, ids=[c[0] for c in CASES])
def test_static_linker_cases(name, files, tgt, expect, kwargs):
    result = run(files, tgt, **kwargs)
    check(result, expect)


def test_case_table_is_large_enough():
    assert len(CASES) >= 60


def test_unparseable_file_is_reported_in_notes():
    result = run(project({"tests/test_bad.py": "def test_y(:\n"}), target())
    assert any("test_bad.py" in n for n in result.notes)


def test_scores_are_documented_priors():
    files = project({T: "from pkg.mod import f\n\ndef test_x():\n    f(1)\n"})
    link = run(files, target()).links[0]
    assert link.score == pytest.approx(0.9)
    assert link.algo_version == "static-link-v1"
    assert link.linker == "static"


def test_indirect_scores_decay():
    files = project({T: "from pkg.a import a1, a2, a3\n\ndef test_1():\n    a1(1)\n\ndef test_2():\n    a2(1)\n\ndef test_3():\n    a3(1)\n"}, base=CHAIN)
    scores = {link.test_id.rsplit("::", 1)[-1]: link.score for link in run(files, target()).links if link.kind == LinkKind.INDIRECT_CALL}
    assert scores["test_1"] > scores["test_2"] > scores["test_3"] > 0.3


def test_fixture_hops_decay():
    files = project({T: FX + "\n@pytest.fixture\ndef w(val):\n    return val\n\ndef test_1(val):\n    pass\n\ndef test_2(w):\n    pass\n"})
    scores = {link.test_id.rsplit("::", 1)[-1]: link.score for link in run(files, target()).links}
    assert scores["test_1"] > scores["test_2"]


def test_parametrized_evidence_mentions_case_count():
    files = project({T: "import pytest\nfrom pkg.mod import f\n\n@pytest.mark.parametrize('v', [1, 2, 3])\ndef test_x(v):\n    f(v)\n"})
    link = run(files, target()).links[0]
    assert any("3 cases" in e for e in link.evidence)
    assert normalize_test_id(f"{T}::test_x[2]") == link.test_id


def test_name_layer_links_what_resolver_cannot_type():
    files = project({T: "def test_x(obj):\n    obj.m()\n"}, base=CPKG)
    tgt = target(qual="C.m", kind="method")
    with_layer = run(files, tgt).links
    without = StaticLinker(name_layer=False).link(files, [tgt]).links
    assert with_layer and not without
    assert all(link.low_confidence and "F-08" in link.evidence[0] for link in with_layer)


def test_name_layer_reuses_f08_graph():
    import radius_testing.linking.static as static_module
    from radius_graph.symbol_impact import PythonSymbolGraph

    assert static_module.PythonSymbolGraph is PythonSymbolGraph


def test_typescript_targets_are_best_effort_and_partial():
    files = {
        "src/util.ts": "export function slug(s: string) { return s }\n",
        "src/util.test.ts": "import { slug } from './util'\ndescribe('util', () => {\n  it('slugifies', () => {\n    expect(slug('a')).toBe('a')\n  })\n  it('other', () => {\n    expect(1).toBe(1)\n  })\n})\n",
    }
    tgt = LinkTarget("typescript:src/util.ts::slug", "src/util.ts", "slug", "function", "typescript")
    result = StaticLinker().link(files, [tgt])
    by_test = {link.test_id: link for link in result.links}
    assert by_test["src/util.test.ts::util::slugifies"].kind == LinkKind.DIRECT_CALL
    assert by_test["src/util.test.ts::util::other"].kind == LinkKind.IMPORT_REFERENCE
    assert all(link.low_confidence and any("partial" in e for e in link.evidence) for link in result.links)
    assert by_test["src/util.test.ts::util::slugifies"].score > by_test["src/util.test.ts::util::other"].score


def test_typescript_unresolvable_import_yields_no_link():
    files = {"src/util.ts": "export const a = 1\n", "src/util.test.ts": "import { a } from 'some-package'\nit('x', () => { a })\n"}
    tgt = LinkTarget("typescript:src/util.ts::a", "src/util.ts", "a", "function", "typescript")
    assert StaticLinker().link(files, [tgt]).links == ()


def test_time_budget_truncates_with_note():
    files = project({T: "from pkg.mod import f\n\ndef test_x():\n    f(1)\n\ndef test_y():\n    f(2)\n"})
    ticks = iter(range(0, 1000, 100))
    linker = StaticLinker(time_budget_seconds=150, clock=lambda: next(ticks))
    result = linker.link(files, [target()])
    assert any("time budget" in n for n in result.notes)


def test_performance_bound_on_large_synthetic_project():
    files = {"pkg/__init__.py": "", MOD: FUNC_SRC}
    for i in range(300):
        files[f"tests/test_{i}.py"] = f"from pkg.mod import f, g\n\ndef test_a_{i}():\n    f({i})\n\ndef test_b_{i}():\n    g({i})\n"
    started = time.perf_counter()
    result = run(files, target())
    elapsed = time.perf_counter() - started
    assert elapsed < 20
    assert sum(1 for link in result.links if link.kind == LinkKind.DIRECT_CALL) == 300


def test_determinism_same_inputs_same_bytes():
    files = project({T: FX + "\ndef test_x(val):\n    f(1)\n", "tests/conftest.py": FX})
    first = run(files, target()).to_json()
    for _ in range(3):
        assert run(dict(reversed(list(files.items()))), target()).to_json() == first


def test_links_serialise_round_trip():
    from radius_testing.linking import LinkSet

    files = project({T: FX + "\ndef test_x(val):\n    f(1)\n"})
    ls = run(files, target())
    assert LinkSet.from_dict(ls.to_dict()).to_json() == ls.to_json()


TS_SRC = "export default function slug(s: string) { return s }\nexport function other() { return 1 }\n"
TS_CASES = [
    ("default_import", "import slug from './util'\ntest('a', () => { slug('x') })\n", "src/util.test.ts::a", "direct_call"),
    ("namespace_import", "import * as u from './util'\nit('a', () => { u.slug('x') })\n", "src/util.test.ts::a", "direct_call"),
    ("alias_import", "import { slug as s } from './util'\nit('a', () => { s('x') })\n", "src/util.test.ts::a", "direct_call"),
    ("nested_describe", "import { slug } from './util'\ndescribe('o', () => { describe('i', () => { it('a', () => { slug('x') }) }) })\n", "src/util.test.ts::o::i::a", "direct_call"),
    ("test_each", "import { slug } from './util'\ndescribe('o', () => { it.each([1])('a', () => { slug('x') }) })\n", "src/util.test.ts::o::a", "direct_call"),
    ("no_blocks_file_level", "import { slug } from './util'\nslug('x')\n", "src/util.test.ts", "import_reference"),
    ("extension_in_specifier", "import { slug } from './util.js'\nit('a', () => { slug('x') })\n", "src/util.test.ts::a", "direct_call"),
]


@pytest.mark.parametrize(("name", "test_src", "test_id", "kind"), TS_CASES, ids=[c[0] for c in TS_CASES])
def test_typescript_import_forms(name, test_src, test_id, kind):
    files = {"src/util.ts": TS_SRC, "src/util.test.ts": test_src}
    tgt = LinkTarget("typescript:src/util.ts::slug", "src/util.ts", "slug", "function", "typescript")
    by_test = {link.test_id: link for link in StaticLinker().link(files, [tgt]).links}
    assert by_test[test_id].kind.value == kind


def test_typescript_oversize_file_is_skipped_with_note():
    big = "import { slug } from './util'\n" + "// pad\n" * 200_000
    files = {"src/util.ts": TS_SRC, "src/util.test.ts": big}
    tgt = LinkTarget("typescript:src/util.ts::slug", "src/util.ts", "slug", "function", "typescript")
    result = StaticLinker().link(files, [tgt])
    assert result.links == () and result.notes
