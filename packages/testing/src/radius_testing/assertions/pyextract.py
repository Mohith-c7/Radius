"""Python assertion extraction (LK-04): pytest, unittest, mock, hypothesis, snapshots.

Pure ``ast`` analysis; nothing is imported or executed. See ``README.md`` for the
model, the feature definitions and the (documented) limits of the data flow.
"""

from __future__ import annotations

import ast
import builtins
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from radius_testing.assertions.model import (
    AssertionKind as K,
)
from radius_testing.assertions.model import (
    AssertionRecord,
    Dependence,
    Exactness,
    ExceptionSpecificity,
    Expected,
    Location,
    StrengthFeatures,
    SymbolRef,
    TestSummary,
)
from radius_testing.assertions.resolve import SymbolResolver

MAX_HELPER_DEPTH = 2
MAX_RECORDS_PER_TEST = 500
MAX_HELPER_CALLS_PER_TEST = 200
MAX_DATAFLOW_DEPTH = 3
MAX_TEXT = 200

_BUILTINS = frozenset(dir(builtins))
_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ())) | {
    "pytest",
    "unittest",
    "hypothesis",
    "syrupy",
    "approvaltests",
    "mock",
    "_pytest",
}
_BROAD_EXC = frozenset({"Exception", "BaseException"})
_MOCK_CTORS = frozenset(
    {
        "Mock",
        "MagicMock",
        "AsyncMock",
        "NonCallableMock",
        "NonCallableMagicMock",
        "PropertyMock",
        "create_autospec",
    }
)
_PATCH_FUNCS = frozenset({"patch", "object", "multiple"})
_MOCK_ASSERTS = {
    "assert_called": Exactness.CALL_ONLY,
    "assert_called_once": Exactness.CALL_ONLY,
    "assert_not_called": Exactness.CALL_ONLY,
    "assert_called_with": Exactness.CALL_ARGS,
    "assert_called_once_with": Exactness.CALL_ARGS,
    "assert_any_call": Exactness.CALL_ARGS,
    "assert_has_calls": Exactness.CALL_ARGS,
    "assert_awaited": Exactness.CALL_ONLY,
    "assert_awaited_once": Exactness.CALL_ONLY,
    "assert_not_awaited": Exactness.CALL_ONLY,
    "assert_awaited_with": Exactness.CALL_ARGS,
    "assert_awaited_once_with": Exactness.CALL_ARGS,
    "assert_any_await": Exactness.CALL_ARGS,
    "assert_has_awaits": Exactness.CALL_ARGS,
}
_MOCK_ATTRS = {
    "called": Exactness.CALL_ONLY,
    "call_count": Exactness.CALL_ONLY,
    "await_count": Exactness.CALL_ONLY,
    "call_args": Exactness.CALL_ARGS,
    "call_args_list": Exactness.CALL_ARGS,
    "mock_calls": Exactness.CALL_ARGS,
    "method_calls": Exactness.CALL_ARGS,
    "await_args": Exactness.CALL_ARGS,
}

# unittest name -> (kind, comparator, exactness, negated)
_UNITTEST: dict[str, tuple[K, str, Exactness, bool]] = {
    "assertEqual": (K.EQUALITY, "==", Exactness.EXACT, False),
    "assertEquals": (K.EQUALITY, "==", Exactness.EXACT, False),
    "assertNotEqual": (K.EQUALITY, "!=", Exactness.EXACT, True),
    "assertListEqual": (K.EQUALITY, "==", Exactness.EXACT, False),
    "assertDictEqual": (K.EQUALITY, "==", Exactness.EXACT, False),
    "assertSetEqual": (K.EQUALITY, "==", Exactness.EXACT, False),
    "assertTupleEqual": (K.EQUALITY, "==", Exactness.EXACT, False),
    "assertSequenceEqual": (K.EQUALITY, "==", Exactness.EXACT, False),
    "assertMultiLineEqual": (K.EQUALITY, "==", Exactness.EXACT, False),
    "assertCountEqual": (K.EQUALITY, "count_equal", Exactness.EXACT, False),
    "assertTrue": (K.TRUTHINESS, "truthy", Exactness.TRUTHINESS, False),
    "assertFalse": (K.TRUTHINESS, "falsy", Exactness.TRUTHINESS, True),
    "assertIs": (K.IDENTITY, "is", Exactness.IDENTITY, False),
    "assertIsNot": (K.IDENTITY, "is not", Exactness.IDENTITY, True),
    "assertIsNone": (K.NONE_CHECK, "is None", Exactness.NONE_ONLY, False),
    "assertIsNotNone": (K.NONE_CHECK, "is not None", Exactness.NONE_ONLY, True),
    "assertIn": (K.MEMBERSHIP, "in", Exactness.MEMBERSHIP, False),
    "assertNotIn": (K.MEMBERSHIP, "not in", Exactness.MEMBERSHIP, True),
    "assertIsInstance": (K.TYPE_CHECK, "isinstance", Exactness.TYPE_ONLY, False),
    "assertNotIsInstance": (K.TYPE_CHECK, "not isinstance", Exactness.TYPE_ONLY, True),
    "assertGreater": (K.COMPARISON, ">", Exactness.ORDERING, False),
    "assertGreaterEqual": (K.COMPARISON, ">=", Exactness.ORDERING, False),
    "assertLess": (K.COMPARISON, "<", Exactness.ORDERING, False),
    "assertLessEqual": (K.COMPARISON, "<=", Exactness.ORDERING, False),
    "assertAlmostEqual": (K.APPROX, "almost_equal", Exactness.APPROX, False),
    "assertAlmostEquals": (K.APPROX, "almost_equal", Exactness.APPROX, False),
    "assertNotAlmostEqual": (K.APPROX, "not_almost_equal", Exactness.APPROX, True),
    "assertRegex": (K.REGEX, "regex", Exactness.PATTERN, False),
    "assertRegexpMatches": (K.REGEX, "regex", Exactness.PATTERN, False),
    "assertNotRegex": (K.REGEX, "not regex", Exactness.PATTERN, True),
}
_UNITTEST_RAISES = {"assertRaises": False, "assertRaisesRegex": True, "assertRaisesRegexp": True}
_UNITTEST_WARNS = {"assertWarns": False, "assertWarnsRegex": True}
_NUMPY_EQ = {"assert_array_equal", "assert_equal", "assert_frame_equal", "assert_series_equal", "assert_index_equal"}
_NUMPY_APPROX = {"assert_allclose", "assert_almost_equal", "assert_array_almost_equal", "assert_array_almost_equal_nulp"}
_APPROVAL_FUNCS = {"verify", "verify_as_json", "verify_all", "verify_file", "verify_xml", "verify_html"}
_REGRESSION_METHODS = {"check", "check_text", "check_json"}

SNAPSHOT_FIXTURE_HINT = "snapshot"


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 3] + "..."


def _unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return _clip(ast.unparse(node))
    except (RecursionError, ValueError):
        return "<unprintable>"


def dotted(node: ast.AST | None) -> str | None:
    """Dotted name of a Name/Attribute chain; calls inside the chain render as ``f()``."""

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return None if base is None else f"{base}.{node.attr}"
    if isinstance(node, ast.Call):
        base = dotted(node.func)
        return None if base is None else f"{base}()"
    return None


def _root(node: ast.AST | None) -> str | None:
    while isinstance(node, ast.Attribute | ast.Call | ast.Subscript):
        node = node.value if not isinstance(node, ast.Call) else node.func
    return node.id if isinstance(node, ast.Name) else None


# ---------------------------------------------------------------- literals


def literal_info(node: ast.AST | None) -> tuple[str, int] | None:
    """``(literal_kind, complexity)`` for literal expressions else ``None``."""

    if node is None:
        return None
    if isinstance(node, ast.Constant):
        v = node.value
        if v is None:
            return ("none", 1)
        if isinstance(v, bool):
            return ("bool", 1)
        if isinstance(v, int | float | complex):
            return ("int" if isinstance(v, int) else "float", 1 if v in (0, 1, -1) else 2)
        if isinstance(v, str):
            return ("str", 1 if v == "" else (3 if len(v) > 24 else 2))
        if isinstance(v, bytes):
            return ("bytes", 1 if v == b"" else 2)
        return ("other", 2)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd | ast.Not):
        inner = literal_info(node.operand)
        if inner and inner[0] in ("int", "float", "bool"):
            return (inner[0], 1 if isinstance(node.operand, ast.Constant) and node.operand.value in (0, 1) else 2)
        return None
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return _collection_info(node.elts)
    if isinstance(node, ast.Dict):
        if any(k is None for k in node.keys):
            return None
        return _collection_info([*node.keys, *node.values])  # type: ignore[list-item]
    if isinstance(node, ast.Call) and not node.args and not node.keywords:
        if dotted(node.func) in {"list", "dict", "set", "tuple", "frozenset", "str", "int", "float", "bool"}:
            return ("collection" if dotted(node.func) not in {"str", "int", "float", "bool"} else dotted(node.func), 1)  # type: ignore[return-value]
    return None


def _collection_info(elts: Sequence[ast.AST]) -> tuple[str, int] | None:
    if not elts:
        return ("collection", 1)
    infos = [literal_info(e) for e in elts]
    if any(i is None for i in infos):
        return None
    nested = any(isinstance(e, ast.List | ast.Tuple | ast.Set | ast.Dict) for e in elts)
    return ("collection", 3 if nested or len(elts) > 2 else 2)


def _is_edge_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        v = node.value
        if v is None or v == "" or v == b"":
            return True
        if isinstance(v, bool):
            return False
        if isinstance(v, int | float):
            return v == 0 or v < 0
        return False
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, int | float)
    if isinstance(node, ast.List | ast.Tuple | ast.Set | ast.Dict):
        return not (node.keys if isinstance(node, ast.Dict) else node.elts)
    if isinstance(node, ast.Call) and dotted(node.func) == "float" and node.args:
        arg = node.args[0]
        return isinstance(arg, ast.Constant) and str(arg.value).lower().lstrip("-+") in {"inf", "nan", "infinity"}
    d = dotted(node)
    return bool(d) and any(t in d.lower() for t in ("maxsize", "max_", "_max", "min_", "_min", "epsilon", "inf", "nan"))


# ---------------------------------------------------------------- module info


@dataclass(slots=True)
class ModuleInfo:
    path: str
    tree: ast.Module
    imports: dict[str, str] = field(default_factory=dict)
    funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(default_factory=dict)
    classes: dict[str, ast.ClassDef] = field(default_factory=dict)


def build_module(path: str, tree: ast.Module) -> ModuleInfo:
    mod = ModuleInfo(path, tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    mod.imports[a.asname] = a.name
                else:
                    top = a.name.split(".")[0]
                    mod.imports[top] = top
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            for a in node.names:
                if a.name == "*":
                    continue
                joiner = "" if base.endswith(".") or not base else "."
                mod.imports[a.asname or a.name] = f"{base}{joiner}{a.name}"
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            mod.funcs[stmt.name] = stmt
        elif isinstance(stmt, ast.ClassDef):
            mod.classes[stmt.name] = stmt
    return mod


def _methods(cls: ast.ClassDef) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}


def _class_mro(mod: ModuleInfo, cls: ast.ClassDef, seen: set[str] | None = None) -> list[ast.ClassDef]:
    """The class followed by its in-module bases (depth-first, no cycles)."""

    seen = seen if seen is not None else set()
    out = [cls]
    seen.add(cls.name)
    for base in cls.bases:
        name = dotted(base)
        if name and name in mod.classes and name not in seen:
            out.extend(_class_mro(mod, mod.classes[name], seen))
    return out


def _is_testcase(mod: ModuleInfo, cls: ast.ClassDef) -> bool:
    for c in _class_mro(mod, cls):
        for base in c.bases:
            name = dotted(base) or ""
            if name.split(".")[-1] in {"TestCase", "IsolatedAsyncioTestCase", "AsyncTestCase"}:
                return True
    return False


def _is_pytest_class(mod: ModuleInfo, cls: ast.ClassDef) -> bool:
    if _is_testcase(mod, cls):
        return True
    return cls.name.startswith("Test") and "__init__" not in _methods(cls)


# ---------------------------------------------------------------- frames


@dataclass(slots=True)
class Frame:
    mod: ModuleInfo
    func: ast.FunctionDef | ast.AsyncFunctionDef
    cls_mro: list[ast.ClassDef]
    assigns: dict[str, list[ast.expr]]
    mocks: dict[str, str]
    locals_defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef]
    params: dict[str, tuple[ast.expr, Frame]] = field(default_factory=dict)
    param_names: frozenset[str] = frozenset()
    escaped: set[str] | None = None


def _walk_body(stmts: Iterable[ast.stmt]) -> Iterable[ast.AST]:
    """Walk statements without descending into nested function/class definitions."""

    stack: list[ast.AST] = list(reversed(list(stmts)))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple | ast.List):
        return [n for e in target.elts for n in _target_names(e)]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return []


def _mock_origin_of_call(call: ast.Call) -> str | None:
    d = dotted(call.func) or ""
    last = d.split(".")[-1]
    if last in _MOCK_CTORS:
        return "created"
    parts = d.split(".")
    if "patch" in parts and last in _PATCH_FUNCS and last != "dict":
        return "patched"
    if last == "spy" and parts[0] in {"mocker", "mock"}:
        return "patched"
    return None


def build_frame(
    mod: ModuleInfo,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    cls_mro: list[ast.ClassDef],
) -> Frame:
    assigns: dict[str, list[ast.expr]] = {}
    mocks: dict[str, str] = {}
    local_defs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    def bind(names: list[str], value: ast.expr | None) -> None:
        for n in names:
            if value is not None:
                assigns.setdefault(n, []).append(value)
            if isinstance(value, ast.Call):
                origin = _mock_origin_of_call(value)
                if origin and (n not in mocks or origin == "created"):
                    mocks[n] = origin

    for node in _walk_body(func.body):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                bind(_target_names(t), node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            bind(_target_names(node.target), node.value)
        elif isinstance(node, ast.AugAssign):
            bind(_target_names(node.target), node.value)
        elif isinstance(node, ast.NamedExpr):
            bind(_target_names(node.target), node.value)
        elif isinstance(node, ast.For | ast.AsyncFor):
            bind(_target_names(node.target), node.iter)
        elif isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                if item.optional_vars is not None:
                    bind(_target_names(item.optional_vars), item.context_expr)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            local_defs[node.name] = node
    # nested defs directly in the body (the walk above yields them without descending)
    # decorator-injected mocks: @patch(...) args come first, bottom decorator first
    patch_decos = [d for d in func.decorator_list if _is_patch_decorator(d)]
    if patch_decos:
        names = [a.arg for a in func.args.args if a.arg not in {"self", "cls"}]
        for name in names[: len(patch_decos)]:
            mocks.setdefault(name, "patched")
    args = func.args
    pnames = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    return Frame(mod, func, cls_mro, assigns, mocks, local_defs, param_names=frozenset(pnames))


def _is_patch_decorator(deco: ast.expr) -> bool:
    if not isinstance(deco, ast.Call):
        return False
    d = dotted(deco.func) or ""
    parts = d.split(".")
    if parts[-1] not in _PATCH_FUNCS or "patch" not in parts or parts[-1] == "dict":
        return False
    return not any(k.arg == "new" for k in deco.keywords) and len(deco.args) < 2


# ---------------------------------------------------------------- parametrize / hypothesis


@dataclass(slots=True)
class ParamInfo:
    parametrized: bool = False
    case_count: int | None = None
    edge: bool | None = None
    leaves_known: bool = True


def _is_parametrize(deco: ast.expr) -> bool:
    if not isinstance(deco, ast.Call):
        return False
    d = dotted(deco.func) or ""
    return d.endswith("mark.parametrize") or d.endswith("parametrize") or d.endswith("parameterized.expand")


def _argname_count(names: ast.expr | None) -> int | None:
    if isinstance(names, ast.Constant) and isinstance(names.value, str):
        return len([n for n in names.value.split(",") if n.strip()])
    if isinstance(names, ast.List | ast.Tuple):
        return len(names.elts)
    return None


def _param_leaves(values: ast.expr, argc: int | None = None) -> tuple[list[ast.expr], int | None]:
    if not isinstance(values, ast.List | ast.Tuple | ast.Set):
        return [], None
    leaves: list[ast.expr] = []
    for el in values.elts:
        if isinstance(el, ast.Call) and (dotted(el.func) or "").endswith("param"):
            el = ast.Tuple(elts=list(el.args), ctx=ast.Load()) if argc != 1 else (el.args[0] if el.args else el)  # noqa: PLW2901
        if argc != 1 and isinstance(el, ast.Tuple | ast.List):
            leaves.extend(el.elts)
        else:
            leaves.append(el)
    return leaves, len(values.elts)


def param_info(func: ast.FunctionDef | ast.AsyncFunctionDef) -> ParamInfo:
    info = ParamInfo()
    total: int | None = 1
    any_edge = False
    for deco in func.decorator_list:
        if not _is_parametrize(deco):
            continue
        assert isinstance(deco, ast.Call)
        info.parametrized = True
        values = deco.args[1] if len(deco.args) >= 2 else (deco.args[0] if deco.args else None)
        if (dotted(deco.func) or "").endswith("expand") and deco.args:
            values = deco.args[0]
        if values is None:
            for kw in deco.keywords:
                if kw.arg == "argvalues":
                    values = kw.value
        argc = _argname_count(deco.args[0]) if deco.args else None
        leaves, n = _param_leaves(values, argc) if values is not None else ([], None)
        if n is None:
            total = None
            info.leaves_known = False
        elif total is not None:
            total *= max(n, 0)
        any_edge = any_edge or any(_is_edge_literal(leaf) for leaf in leaves)
    if info.parametrized:
        info.case_count = total
        if any_edge:
            info.edge = True
        elif info.leaves_known:
            info.edge = False
        else:
            info.edge = None
    return info


def _is_hypothesis(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for deco in func.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        d = dotted(target) or ""
        if d == "given" or d.endswith(".given"):
            return True
    return False


def _call_arg_edge(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool | None:
    seen_literal = False
    for node in _walk_body(func.body):
        if isinstance(node, ast.Call):
            for a in [*node.args, *(k.value for k in node.keywords)]:
                if literal_info(a) is not None:
                    seen_literal = True
                    if _is_edge_literal(a):
                        return True
    return False if seen_literal else None


# ---------------------------------------------------------------- drafts


@dataclass(slots=True)
class Draft:
    kind: K
    comparator: str
    exactness: Exactness
    subject: ast.AST | None = None
    expected: ast.AST | None = None
    expected_text: str | None = None
    expected_form: str | None = None
    negated: bool = False
    quantifier: str | None = None
    tol_rel: float | None = None
    tol_abs: float | None = None
    dead_reason: str | None = None
    snapshot_library: str | None = None
    framework: str = "pytest"
    node: ast.AST | None = None
    subjects_extra: list[ast.AST] = field(default_factory=list)
    exc: ExceptionSpecificity = ExceptionSpecificity.NONE
    exc_match: bool = False
    exc_block: int | None = None
    exc_var: str | None = None
    confidence: float = 0.95
    mock_receiver: ast.AST | None = None
    expected_complexity: int | None = None


def _num(node: ast.AST | None) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = _num(node.operand)
        return None if v is None else -v
    return None


def _kw(call: ast.Call, name: str) -> ast.expr | None:
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _has_call(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) for n in ast.walk(node))


def _is_len_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and dotted(node.func) == "len" and len(node.args) == 1


def _is_approx_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and (dotted(node.func) or "").split(".")[-1] == "approx"


def _mock_attr(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr in _MOCK_ATTRS:
        return node.attr
    if isinstance(node, ast.Subscript):
        return _mock_attr(node.value)
    if isinstance(node, ast.Call):
        return _mock_attr(node.func)
    return None


class Extractor:
    """Extract the assertions of one Python test module."""

    def __init__(
        self,
        mod: ModuleInfo,
        helpers_modules: Sequence[ModuleInfo],
        resolver: SymbolResolver | None,
        linked: dict[str, frozenset[str]] | None,
    ) -> None:
        self.mod = mod
        self.helper_mods = list(helpers_modules)  # nearest conftest first
        self.resolver = resolver
        self.linked = linked
        self.records: list[AssertionRecord] = []
        self.summaries: list[TestSummary] = []
        self.notes: list[str] = []

    # ------------------------------------------------------------ discovery

    def run(self) -> None:
        for name, fn in self.mod.funcs.items():
            if name.startswith("test"):
                self._test(fn, None, [])
        for cname, cls in self.mod.classes.items():
            self._class(cname, cls)

    def _class(self, cname: str, cls: ast.ClassDef) -> None:
        if not _is_pytest_class(self.mod, cls):
            return
        mro = _class_mro(self.mod, cls)
        methods: dict[str, tuple[ast.FunctionDef | ast.AsyncFunctionDef, ast.ClassDef]] = {}
        for c in reversed(mro):
            for n, f in _methods(c).items():
                methods[n] = (f, c)
        for n in sorted(methods, key=lambda k: methods[k][0].lineno):
            fn, owner = methods[n]
            if n.startswith("test") and not self._is_fixture(fn):
                self._test(fn, cname, mro, owner_is_self=owner is cls)
        for inner in cls.body:
            if isinstance(inner, ast.ClassDef) and _is_pytest_class(self.mod, inner):
                self._class(f"{cname}.{inner.name}", inner)

    @staticmethod
    def _is_fixture(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        return any("fixture" in (dotted(d.func if isinstance(d, ast.Call) else d) or "") for d in fn.decorator_list)

    # ------------------------------------------------------------ per test

    def _test(
        self,
        fn: ast.FunctionDef | ast.AsyncFunctionDef,
        cname: str | None,
        mro: list[ast.ClassDef],
        owner_is_self: bool = True,
    ) -> None:
        if self._is_fixture(fn):
            return
        test_id = "::".join(p for p in (self.mod.path, cname, fn.name) if p)
        frame = build_frame(self.mod, fn, mro)
        pinfo = param_info(fn)
        hyp = _is_hypothesis(fn)
        if pinfo.parametrized:
            edge, edge_src = pinfo.edge, "parametrize"
        elif hyp:
            edge, edge_src = None, None
        else:
            edge = _call_arg_edge(fn)
            edge_src = "call_args" if edge is not None else None
        ctx = _TestCtx(
            test_id=test_id,
            root=frame,
            parametrized=pinfo.parametrized,
            hypothesis=hyp,
            edge=edge,
            edge_source=edge_src,
            asserted_names=_names_in_assertions(fn),
        )
        before = len(self.records)
        self._visit_block(fn.body, frame, ctx, _Flags(), (), 0, ())
        count = len(self.records) - before
        if ctx.truncated:
            self.notes.append(f"{test_id}: truncated at {MAX_RECORDS_PER_TEST} assertions")
        self.summaries.append(
            TestSummary(
                test_id=test_id,
                path=self.mod.path,
                line=fn.lineno,
                language="python",
                assertion_count=count,
                has_assertions=count > 0,
                property_based=hyp,
                parametrized=pinfo.parametrized,
                case_count=pinfo.case_count,
                has_dynamic_assertions=ctx.dynamic,
            )
        )

    # ------------------------------------------------------------ statements

    def _visit_block(
        self,
        stmts: Sequence[ast.stmt],
        frame: Frame,
        ctx: _TestCtx,
        flags: _Flags,
        via: tuple[str, ...],
        depth: int,
        stack: tuple[tuple[str, str], ...],
    ) -> None:
        for stmt in stmts:
            if ctx.truncated:
                return
            self._visit_stmt(stmt, frame, ctx, flags, via, depth, stack)

    def _visit_stmt(self, stmt, frame, ctx, flags, via, depth, stack) -> None:  # noqa: ANN001, C901
        if isinstance(stmt, ast.Assert):
            for d in self._classify(stmt.test, frame):
                d.node = stmt
                self._emit(d, frame, ctx, flags, via, depth)
            return
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            return
        if isinstance(stmt, ast.With | ast.AsyncWith):
            for item in stmt.items:
                d = self._with_item(item, stmt, frame)
                if d is not None:
                    self._emit(d, frame, ctx, flags, via, depth)
                else:
                    self._follow_calls(item.context_expr, frame, ctx, flags, via, depth, stack)
            self._visit_block(stmt.body, frame, ctx, flags, via, depth, stack)
            return
        if isinstance(stmt, ast.For | ast.AsyncFor | ast.While):
            header = stmt.iter if not isinstance(stmt, ast.While) else stmt.test
            self._follow_calls(header, frame, ctx, flags, via, depth, stack)
            looped = flags.with_(in_loop=True)
            self._visit_block(stmt.body, frame, ctx, looped, via, depth, stack)
            self._visit_block(stmt.orelse, frame, ctx, flags, via, depth, stack)
            return
        if isinstance(stmt, ast.Try) or type(stmt).__name__ == "TryStar":
            swallow = any(self._swallows(h) for h in stmt.handlers)  # type: ignore[attr-defined]
            self._visit_block(stmt.body, frame, ctx, flags.with_(swallowed=flags.swallowed or swallow), via, depth, stack)
            for h in stmt.handlers:  # type: ignore[attr-defined]
                self._visit_block(h.body, frame, ctx, flags, via, depth, stack)
            self._visit_block(stmt.orelse, frame, ctx, flags, via, depth, stack)  # type: ignore[attr-defined]
            self._visit_block(stmt.finalbody, frame, ctx, flags, via, depth, stack)  # type: ignore[attr-defined]
            return
        if isinstance(stmt, ast.If):
            self._follow_calls(stmt.test, frame, ctx, flags, via, depth, stack)
            self._visit_block(stmt.body, frame, ctx, flags, via, depth, stack)
            self._visit_block(stmt.orelse, frame, ctx, flags, via, depth, stack)
            return
        if isinstance(stmt, ast.Match):
            for case in stmt.cases:
                self._visit_block(case.body, frame, ctx, flags, via, depth, stack)
            return
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            d = self._call_statement(stmt.value, frame)
            if d is not None:
                d.node = stmt
                self._emit(d, frame, ctx, flags, via, depth)
                return
        self._follow_calls(stmt, frame, ctx, flags, via, depth, stack)

    @staticmethod
    def _swallows(handler: ast.ExceptHandler) -> bool:
        if any(isinstance(n, ast.Raise) for n in ast.walk(handler)):
            return False
        if handler.type is None:
            return True
        names = [dotted(handler.type)] if not isinstance(handler.type, ast.Tuple) else [dotted(e) for e in handler.type.elts]
        return any((n or "").split(".")[-1] in {"Exception", "BaseException", "AssertionError"} for n in names)

    # ------------------------------------------------------------ helpers

    def _lookup_helper(self, call: ast.Call, frame: Frame):  # noqa: ANN202
        """``(FunctionDef, ModuleInfo, is_method, name)`` for a followable helper call."""

        f = call.func
        if isinstance(f, ast.Name):
            name = f.id
            if name in frame.locals_defs:
                return frame.locals_defs[name], frame.mod, False, name
            if name in frame.mod.funcs and not name.startswith("test"):
                return frame.mod.funcs[name], frame.mod, False, name
            for m in self.helper_mods:
                if name in m.funcs and not name.startswith("test"):
                    return m.funcs[name], m, False, name
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in {"self", "cls"}:
            for c in frame.cls_mro:
                meth = _methods(c).get(f.attr)
                if meth is not None and not f.attr.startswith("test") and not self._is_fixture(meth):
                    return meth, frame.mod, True, f.attr
        return None

    def _follow_calls(self, node, frame, ctx, flags, via, depth, stack) -> None:  # noqa: ANN001
        if depth >= MAX_HELPER_DEPTH:
            return
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            hit = self._lookup_helper(sub, frame)
            if hit is None:
                continue
            fn, hmod, is_method, name = hit
            key = (hmod.path, f"{name}:{fn.lineno}")
            if key in stack or ctx.helper_calls >= MAX_HELPER_CALLS_PER_TEST:
                continue
            ctx.helper_calls += 1
            hframe = build_frame(hmod, fn, frame.cls_mro if is_method or hmod is frame.mod else [])
            self._bind_params(hframe, fn, sub, frame, is_method)
            self._visit_block(
                fn.body, hframe, ctx, flags, (*via, f"{name}@{sub.lineno}"), depth + 1, (*stack, key)
            )

    @staticmethod
    def _bind_params(hframe: Frame, fn, call: ast.Call, caller: Frame, is_method: bool) -> None:  # noqa: ANN001
        names = [a.arg for a in [*fn.args.posonlyargs, *fn.args.args]]
        if is_method and names and names[0] in {"self", "cls"}:
            names = names[1:]
        for n, a in zip(names, call.args, strict=False):
            if not isinstance(a, ast.Starred):
                hframe.params[n] = (a, caller)
        for k in call.keywords:
            if k.arg:
                hframe.params[k.arg] = (k.value, caller)

    # ------------------------------------------------------------ classification

    def _classify(self, test: ast.expr, frame: Frame) -> list[Draft]:  # noqa: C901
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            if isinstance(test.operand, ast.Constant):
                return [Draft(K.TRUTHINESS, "constant", Exactness.NONE, test, dead_reason="constant_false" if test.operand.value else "constant_true")]
            drafts = self._classify(test.operand, frame)
            for d in drafts:
                d.negated = not d.negated
            return drafts
        if isinstance(test, ast.BoolOp):
            if isinstance(test.op, ast.And):
                out: list[Draft] = []
                for v in test.values:
                    out.extend(self._classify(v, frame))
                return out
            dead = "tautology" if any(_const_truthy(v) for v in test.values) else None
            return [Draft(K.DISJUNCTION, "or", Exactness.DISJUNCTION, test, dead_reason=dead)]
        if isinstance(test, ast.Constant):
            return [
                Draft(
                    K.TRUTHINESS,
                    "constant",
                    Exactness.NONE,
                    test,
                    dead_reason="constant_true" if test.value else "constant_false",
                )
            ]
        if isinstance(test, ast.Tuple | ast.List | ast.Dict | ast.Set | ast.JoinedStr) and (
            getattr(test, "elts", None) or getattr(test, "keys", None) or isinstance(test, ast.JoinedStr)
        ):
            return [Draft(K.TRUTHINESS, "constant", Exactness.NONE, test, dead_reason="constant_true")]
        if isinstance(test, ast.Compare):
            return [self._classify_compare(test, frame)]
        if isinstance(test, ast.Call):
            return [self._classify_call_test(test, frame)]
        if isinstance(test, ast.NamedExpr):
            return self._classify(test.value, frame)
        attr = _mock_attr(test)
        if attr is not None:
            return [Draft(K.MOCK_CALL, "truthy", _MOCK_ATTRS[attr], test, framework="mock", mock_receiver=_attr_receiver(test))]
        return [Draft(K.TRUTHINESS, "truthy", Exactness.TRUTHINESS, test)]

    def _classify_compare(self, test: ast.Compare, frame: Frame) -> Draft:  # noqa: C901
        left, ops, rights = test.left, test.ops, test.comparators
        if len(ops) > 1:
            all_eq = all(isinstance(o, ast.Eq | ast.NotEq) for o in ops)
            comp = " ".join(_OPS.get(type(o), "?") for o in ops)
            return Draft(
                K.EQUALITY if all_eq else K.COMPARISON,
                f"chain {comp}",
                Exactness.EXACT if all_eq else Exactness.ORDERING,
                left,
                rights[-1],
            )
        op, right = ops[0], rights[0]
        sym = _OPS.get(type(op), "?")
        lit_l, lit_r = literal_info(left), literal_info(right)
        if lit_l and lit_r and not _has_call(left) and not _has_call(right):
            return Draft(K.EQUALITY, sym, Exactness.NONE, left, right, dead_reason="literal_comparison")
        if isinstance(op, ast.Eq | ast.NotEq):
            neg = isinstance(op, ast.NotEq)
            for a, b in ((left, right), (right, left)):
                if self._is_snapshot_expr(b, frame):
                    return Draft(K.SNAPSHOT, sym, Exactness.SNAPSHOT, a, b, expected_form="snapshot", negated=neg, snapshot_library="syrupy", framework="snapshot")
            for a, b in ((left, right), (right, left)):
                if _is_approx_call(b):
                    assert isinstance(b, ast.Call)
                    rel, ab = _approx_tol(b)
                    return Draft(K.APPROX, sym, Exactness.APPROX, a, b.args[0] if b.args else None, negated=neg, tol_rel=rel, tol_abs=ab)
            for a, b in ((left, right), (right, left)):
                if _mock_attr(a) is not None:
                    return Draft(K.MOCK_CALL, sym, _MOCK_ATTRS[_mock_attr(a)], a, b, negated=neg, framework="mock", mock_receiver=_attr_receiver(a))  # type: ignore[index]
            for a, b in ((left, right), (right, left)):
                if _is_len_call(a):
                    return Draft(K.LENGTH, sym, Exactness.LENGTH_ONLY, a.args[0], b, negated=neg)  # type: ignore[attr-defined]
            for a, b in ((left, right), (right, left)):
                if isinstance(b, ast.Constant) and b.value is None:
                    return Draft(K.NONE_CHECK, sym, Exactness.NONE_ONLY, a, b, negated=neg)
            subj, exp = (right, left) if lit_l and not lit_r else (left, right)
            return Draft(K.EQUALITY, sym, Exactness.EXACT, subj, exp, negated=neg, dead_reason=_tautology(left, right))
        if isinstance(op, ast.Is | ast.IsNot):
            neg = isinstance(op, ast.IsNot)
            for a, b in ((left, right), (right, left)):
                if isinstance(b, ast.Constant) and b.value is None:
                    return Draft(K.NONE_CHECK, sym, Exactness.NONE_ONLY, a, b, negated=neg)
            return Draft(K.IDENTITY, sym, Exactness.IDENTITY, left, right, negated=neg, dead_reason=_tautology(left, right))
        if isinstance(op, ast.In | ast.NotIn):
            neg = isinstance(op, ast.NotIn)
            subj, exp = (right, left) if lit_l and not lit_r else (left, right)
            return Draft(K.MEMBERSHIP, sym, Exactness.MEMBERSHIP, subj, exp, negated=neg)
        # ordering
        for a, b in ((left, right), (right, left)):
            if _is_len_call(a):
                return Draft(K.LENGTH, sym, Exactness.LENGTH_ONLY, a.args[0], b)  # type: ignore[attr-defined]
        return Draft(K.COMPARISON, sym, Exactness.ORDERING, left, right)

    def _is_snapshot_expr(self, node: ast.AST, frame: Frame) -> bool:
        """``snapshot`` / ``snapshot(...)`` / ``snapshot_json`` that is a fixture parameter or import."""

        target = node.func if isinstance(node, ast.Call) else node
        while isinstance(target, ast.Attribute):
            target = target.value
        if not isinstance(target, ast.Name):
            return False
        name = target.id
        if not (name == SNAPSHOT_FIXTURE_HINT or name.startswith(SNAPSHOT_FIXTURE_HINT + "_")):
            return False
        return name in frame.param_names or name in frame.mod.imports or name in frame.params

    def _classify_call_test(self, call: ast.Call, frame: Frame) -> Draft:  # noqa: C901
        d = dotted(call.func) or ""
        last = d.split(".")[-1]
        args = call.args
        if last in {"isinstance", "issubclass"} and len(args) >= 2:
            exp = args[1]
            tname = dotted(exp)
            dead = "tautology" if tname in {"object"} else None
            return Draft(K.TYPE_CHECK, last, Exactness.TYPE_ONLY, args[0], exp, dead_reason=dead, expected_form="type")
        if d in {"all", "any"} and len(args) == 1:
            inner = args[0]
            sub: Draft | None = None
            if isinstance(inner, ast.GeneratorExp | ast.ListComp | ast.SetComp):
                got = self._classify(inner.elt, frame)
                sub = got[0] if len(got) == 1 else None
            if sub is not None and sub.dead_reason is None:
                return Draft(K.QUANTIFIED, f"{d}:{sub.comparator}", sub.exactness, inner, sub.expected, quantifier=d, negated=sub.negated, expected_form=sub.expected_form, tol_rel=sub.tol_rel, tol_abs=sub.tol_abs)
            return Draft(K.QUANTIFIED, d, Exactness.TRUTHINESS, inner, quantifier=d)
        if last == "isclose" and len(args) >= 2:
            rel = _num(_kw(call, "rel_tol"))
            ab = _num(_kw(call, "abs_tol"))
            return Draft(K.APPROX, "isclose", Exactness.APPROX, args[0], args[1], tol_rel=rel if rel is not None else 1e-9, tol_abs=ab if ab is not None else 0.0)
        if last == "allclose" and len(args) >= 2:
            rel = _num(_kw(call, "rtol"))
            ab = _num(_kw(call, "atol"))
            return Draft(K.APPROX, "allclose", Exactness.APPROX, args[0], args[1], tol_rel=rel if rel is not None else 1e-5, tol_abs=ab if ab is not None else 1e-8)
        if d in {"re.match", "re.search", "re.fullmatch"} or (last in {"match", "search", "fullmatch"} and (_root(call.func) in {"re", "pattern", "regex"})):
            return Draft(K.REGEX, last, Exactness.PATTERN, args[1] if len(args) > 1 else None, args[0] if args else None, expected_form="pattern")
        if _mock_attr(call) is not None:
            return Draft(K.MOCK_CALL, "truthy", _MOCK_ATTRS[_mock_attr(call)], call, framework="mock", mock_receiver=_attr_receiver(call))  # type: ignore[index]
        if _is_len_call(call):
            return Draft(K.LENGTH, "truthy", Exactness.LENGTH_ONLY, args[0])
        return Draft(K.TRUTHINESS, "truthy", Exactness.TRUTHINESS, call)

    # ------------------------------------------------------------ calls as statements

    def _call_statement(self, call: ast.Call, frame: Frame) -> Draft | None:  # noqa: C901
        f = call.func
        d = dotted(f) or ""
        last = d.split(".")[-1]
        recv = f.value if isinstance(f, ast.Attribute) else None
        recv_name = dotted(recv) if recv is not None else None
        args = call.args
        # pytest.raises / warns call forms: pytest.raises(Exc, func, *a)
        if last in {"raises", "warns", "deprecated_call"} and self._qual_is(d, "pytest"):
            return self._raises_draft(call, last != "raises", None, 1 if len(args) > 1 else 0)
        if recv_name in {"self", "cls"} and last in _UNITTEST_RAISES | _UNITTEST_WARNS:
            if len(args) >= 2:  # call form
                return self._raises_draft(call, last in _UNITTEST_WARNS, last, 1, framework="unittest")
            return None
        if recv_name in {"self", "cls"} and last in _UNITTEST:
            return self._unittest_draft(call, last)
        if recv_name in {"self", "cls"} and last in {"fail", "skipTest"}:
            return None
        # followable helper beats name heuristics below
        if self._lookup_helper(call, frame) is not None:
            return None
        if isinstance(f, ast.Attribute) and last in _MOCK_ASSERTS:
            exp = _args_expected(call)
            return Draft(
                K.MOCK_CALL, last, _MOCK_ASSERTS[last], recv, exp[0] if exp else None,
                expected_text=_unparse_args(call), framework="mock", mock_receiver=recv,
                expected_complexity=_args_complexity(call),
            )
        if isinstance(f, ast.Attribute) and last == "assert_match" and recv_name and "snapshot" in recv_name.lower():
            return Draft(K.SNAPSHOT, "assert_match", Exactness.SNAPSHOT, args[0] if args else None, expected_form="snapshot", snapshot_library="pytest-snapshot", framework="snapshot")
        if isinstance(f, ast.Attribute) and last in _REGRESSION_METHODS and recv_name and recv_name.endswith("_regression"):
            return Draft(K.SNAPSHOT, last, Exactness.SNAPSHOT, args[0] if args else None, expected_form="snapshot", snapshot_library="pytest-regressions", framework="snapshot")
        qual = self._qualify(d)
        if last in _APPROVAL_FUNCS and (qual or "").startswith("approvaltests"):
            return Draft(K.SNAPSHOT, last, Exactness.SNAPSHOT, args[0] if args else None, expected_form="snapshot", snapshot_library="approvaltests", framework="snapshot")
        if (qual or "").startswith(("numpy.testing", "pandas.testing", "numpy.testing.")) or (qual or "").split(".")[0] in {"numpy", "np", "pandas"} and last.startswith("assert_"):
            if last in _NUMPY_EQ and len(args) >= 2:
                return Draft(K.EQUALITY, last, Exactness.EXACT, args[0], args[1], framework="pytest")
            if last in _NUMPY_APPROX and len(args) >= 2:
                rel = _num(_kw(call, "rtol"))
                ab = _num(_kw(call, "atol"))
                return Draft(K.APPROX, last, Exactness.APPROX, args[0], args[1], tol_rel=rel if rel is not None else (1e-7 if last == "assert_allclose" else None), tol_abs=ab if ab is not None else (0.0 if last == "assert_allclose" else 1.5 * 10**-7), framework="pytest")
        if last.startswith("assert") and (isinstance(f, ast.Name) or recv_name in {"self", "cls"}):
            return Draft(K.UNKNOWN_ASSERT, last, Exactness.NONE, args[0] if args else None, args[1] if len(args) > 1 else None, confidence=0.4, framework="unittest" if recv_name else "pytest")
        return None

    def _qualify(self, d: str) -> str | None:
        root, _, rest = d.partition(".")
        base = self.mod.imports.get(root)
        if base is None:
            return None
        return base + ("." + rest if rest else "")

    def _qual_is(self, d: str, prefix: str) -> bool:
        q = self._qualify(d)
        return bool(q and q.split(".")[0] == prefix)

    def _unittest_draft(self, call: ast.Call, name: str) -> Draft:
        kind, comp, exact, neg = _UNITTEST[name]
        a = call.args
        subject = a[0] if a else None
        expected = a[1] if len(a) > 1 else None
        if kind is K.TRUTHINESS or kind is K.NONE_CHECK:
            expected = None
        if expected is not None and subject is not None:
            if kind in {K.EQUALITY, K.IDENTITY, K.COMPARISON, K.APPROX} and literal_info(subject) and not literal_info(expected):
                subject, expected = expected, subject
        if kind is K.MEMBERSHIP and len(a) > 1:
            # assertIn(member, container): the container is what was observed
            subject, expected = a[1], a[0]
        if kind is K.REGEX and len(a) > 1:
            expected = a[1]
        draft = Draft(kind, comp, exact, subject, expected, negated=neg, framework="unittest", expected_form="pattern" if kind is K.REGEX else None)
        if kind is K.APPROX:
            places = _kw(call, "places")
            delta = _num(_kw(call, "delta"))
            if delta is not None:
                draft.tol_abs = delta
            else:
                p = _num(places)
                draft.tol_abs = 0.5 * 10 ** (-(p if p is not None else 7))
        if kind is K.EQUALITY and name == "assertCountEqual":
            draft.exactness = Exactness.EXACT
        if (dead := _tautology(subject, expected)) and kind in {K.EQUALITY, K.IDENTITY}:
            draft.dead_reason = dead
        if kind is K.TRUTHINESS and isinstance(subject, ast.Constant):
            draft.dead_reason = "constant_true" if bool(subject.value) != neg else "constant_false"
        return draft

    def _raises_draft(
        self,
        call: ast.Call,
        warns: bool,
        unittest_name: str | None,
        callable_index: int,
        framework: str = "pytest",
        block_size: int | None = None,
        exc_var: str | None = None,
    ) -> Draft:
        args = call.args
        exc_node = args[0] if args else _kw(call, "expected_exception") or _kw(call, "expected_warning")
        match_present = _kw(call, "match") is not None or unittest_name in _UNITTEST_RAISES and _UNITTEST_RAISES.get(unittest_name, False) or unittest_name in _UNITTEST_WARNS and _UNITTEST_WARNS.get(unittest_name, False)
        spec = _exception_spec(exc_node, match_present)
        subject: ast.AST | None = None
        extra: list[ast.AST] = []
        if callable_index and len(args) > callable_index:
            subject = args[callable_index]
            extra = list(args[callable_index + 1 :])
        kind = K.WARNING if warns else K.EXCEPTION
        d = Draft(kind, "warns" if warns else "raises", Exactness.EXCEPTION, subject, exc_node, expected_form="exception_type", framework=framework if framework != "pytest" else "pytest", exc=spec, exc_match=bool(match_present), exc_block=block_size, exc_var=exc_var)
        d.subjects_extra = extra
        d.expected_text = _unparse(exc_node) + (f", match={_unparse(_kw(call, 'match'))}" if _kw(call, "match") is not None else "")
        d.expected_complexity = 1 if spec in {ExceptionSpecificity.BROAD, ExceptionSpecificity.NONE} else 2
        return d

    def _with_item(self, item: ast.withitem, stmt: ast.With | ast.AsyncWith, frame: Frame) -> Draft | None:
        expr = item.context_expr
        if not isinstance(expr, ast.Call):
            return None
        d = dotted(expr.func) or ""
        last = d.split(".")[-1]
        recv = dotted(expr.func.value) if isinstance(expr.func, ast.Attribute) else None
        var = item.optional_vars.id if isinstance(item.optional_vars, ast.Name) else None
        if last in {"raises", "warns", "deprecated_call"} and self._qual_is(d, "pytest"):
            draft = self._raises_draft(expr, last != "raises", None, 0, block_size=len(stmt.body), exc_var=var)
            draft.node = stmt
            draft.subjects_extra = list(stmt.body)
            return draft
        if recv in {"self", "cls"} and last in _UNITTEST_RAISES | _UNITTEST_WARNS:
            draft = self._raises_draft(expr, last in _UNITTEST_WARNS, last, 0, framework="unittest", block_size=len(stmt.body), exc_var=var)
            draft.node = stmt
            draft.subjects_extra = list(stmt.body)
            return draft
        return None

    # ------------------------------------------------------------ emit

    def _emit(self, d: Draft, frame: Frame, ctx: _TestCtx, flags: _Flags, via: tuple[str, ...], depth: int) -> None:
        if len(ctx.emitted) >= MAX_RECORDS_PER_TEST:
            ctx.truncated = True
            return
        node = d.node or d.subject
        lineno = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", lineno) or lineno
        # for ``with`` blocks only the header is the assertion
        if isinstance(node, ast.With | ast.AsyncWith) and node.items:
            end = getattr(node.items[0].context_expr, "end_lineno", lineno) or lineno
        col = getattr(node, "col_offset", 0)
        subject_nodes: list[ast.AST] = ([d.subject] if d.subject is not None else []) + list(d.subjects_extra)
        if d.subject is None and d.mock_receiver is not None:
            subject_nodes = [d.mock_receiver]
        subject_text = _unparse(subject_nodes[0]) if subject_nodes else ""
        if d.kind in {K.EXCEPTION, K.WARNING} and d.subjects_extra and isinstance(d.subjects_extra[0], ast.stmt):
            subject_text = _unparse(d.subjects_extra[0])
        refs = self._refs(subject_nodes, frame)
        refs = self._resolve_refs(refs, ctx.test_id)
        expected = self._expected(d, frame)
        circular = self._circular(d, frame)
        mock_only, mock_origin = self._mock_status(d, subject_nodes, frame)
        dead_reason = d.dead_reason
        edge_inputs, edge_source = ctx.edge, ctx.edge_source
        dependence = self._dependence(ctx.test_id, refs)
        inspected = bool(d.exc_var and d.exc_var in ctx.asserted_names)
        feats = StrengthFeatures(
            exactness=d.exactness if dead_reason is None else Exactness.NONE,
            value_specificity=expected.complexity,
            distinct_subject_symbols=len({r.qualified or r.name for r in refs}),
            edge_inputs=edge_inputs,
            edge_input_source=edge_source,
            exception_specificity=d.exc,
            exception_match=d.exc_match,
            exception_inspected=inspected,
            exception_block_size=d.exc_block,
            tolerance_rel=d.tol_rel,
            tolerance_abs=d.tol_abs,
            depends_on_changed=dependence,
            circular=circular,
            mock_only=mock_only,
            mock_origin=mock_origin,
            in_loop=flags.in_loop,
            in_parametrized=ctx.parametrized,
            property_based=ctx.hypothesis,
            swallowed=flags.swallowed,
            dead=dead_reason is not None,
            dead_reason=dead_reason,
            negated=d.negated,
            quantifier=d.quantifier,
            snapshot_library=d.snapshot_library,
            helper_depth=depth,
        )
        framework = "hypothesis" if ctx.hypothesis and d.framework == "pytest" else d.framework
        conf = d.confidence if depth == 0 else min(d.confidence, 0.95 - 0.1 * depth)
        if d.kind is K.UNKNOWN_ASSERT:
            ctx.dynamic = True
        rec = AssertionRecord(
            test_id=ctx.test_id,
            kind=d.kind,
            subject_text=subject_text,
            subject_refs=refs,
            expected=expected,
            comparator=d.comparator,
            strength_features=feats,
            location=Location(frame.mod.path, lineno, end),
            framework=framework,
            confidence=round(conf, 2),
            via=via,
            col=col,
        )
        ctx.emitted.append(rec)
        self.records.append(rec)

    # ------------------------------------------------------------ feature helpers

    def _expected(self, d: Draft, frame: Frame) -> Expected:
        if d.expected_form == "snapshot":
            return Expected(text=_unparse(d.expected) or "<snapshot>", form="snapshot", complexity=0)
        node = d.expected
        text = d.expected_text if d.expected_text is not None else _unparse(node)
        if node is None and d.expected_text is None:
            return Expected()
        if d.expected_form == "exception_type":
            return Expected(text, "exception_type", None, d.expected_complexity or 0)
        if d.expected_form == "pattern":
            lit = literal_info(node)
            return Expected(text, "pattern", lit[0] if lit else None, lit[1] if lit else 1)
        if d.expected_complexity is not None and node is None or d.kind is K.MOCK_CALL and d.expected_complexity is not None:
            return Expected(text, "literal" if d.expected_complexity else "expression", None, d.expected_complexity)
        info = literal_info(node)
        if info is None and isinstance(node, ast.Name):
            vals = frame.assigns.get(node.id, [])
            if len(vals) == 1:
                info = literal_info(vals[0])
        if info is None:
            return Expected(text, "expression", None, 0)
        return Expected(text, "literal", info[0], info[1])

    def _circular(self, d: Draft, frame: Frame) -> bool:
        """Expected computed by the same project callee as the subject (import-qualified calls only)."""

        if d.expected is None or d.subject is None or d.kind in {K.EXCEPTION, K.WARNING, K.MOCK_CALL, K.SNAPSHOT}:
            return False
        shared = frozenset(
            n.id for n in ast.walk(d.subject) if isinstance(n, ast.Name)
        ) & frozenset(n.id for n in ast.walk(d.expected) if isinstance(n, ast.Name))
        subj = {r.qualified for r in self._refs([d.subject], frame, 1, shared) if r.role == "call"}
        exp = {r.qualified for r in self._refs([d.expected], frame, 1, shared) if r.role == "call"}
        return bool(subj & exp)

    def _mock_status(self, d: Draft, subject_nodes: Sequence[ast.AST], frame: Frame) -> tuple[bool, str | None]:
        nodes = [d.mock_receiver] if d.mock_receiver is not None else list(subject_nodes)
        nodes = [n for n in nodes if n is not None and not isinstance(n, ast.stmt)]
        if not nodes:
            return False, None
        origins: set[str] = set()
        roots: list[str] = []
        for n in nodes:
            for sub in ast.walk(n):
                if isinstance(sub, ast.Name) and sub.id not in _BUILTINS:
                    roots.append(sub.id)
        if not roots:
            return False, None
        flags: list[bool] = []
        for r in dict.fromkeys(roots):
            created = self._mock_derived(r, frame, 0, frozenset())
            flags.append(created)
            o = _mock_origin_name(r, frame)
            if o:
                origins.add(o)
        origin = "created" if "created" in origins else ("patched" if origins else None)
        return all(flags), origin

    def _mock_derived(self, name: str, frame: Frame, depth: int, seen: frozenset[str]) -> bool:
        if frame.mocks.get(name) == "created":
            return name not in _escaped_mocks(frame)
        if depth >= MAX_DATAFLOW_DEPTH or name in seen:
            return False
        if name in frame.params:
            pnode, pframe = frame.params[name]
            names = [n.id for n in ast.walk(pnode) if isinstance(n, ast.Name) and n.id not in _BUILTINS]
            return bool(names) and all(self._mock_derived(n, pframe, depth + 1, seen | {name}) for n in names)
        vals = frame.assigns.get(name)
        if not vals or name in frame.mocks:
            return False
        for v in vals:
            names = [n.id for n in ast.walk(v) if isinstance(n, ast.Name) and n.id not in _BUILTINS]
            if not names or not all(self._mock_derived(n, frame, depth + 1, seen | {name}) for n in names):
                return False
        return True

    def _dependence(self, test_id: str, refs: tuple[SymbolRef, ...]) -> Dependence:
        if self.linked is None:
            return Dependence.UNKNOWN
        ids = {sid for r in refs for sid in r.symbol_ids}
        if not ids:
            return Dependence.UNKNOWN
        return Dependence.YES if ids & self.linked.get(test_id, frozenset()) else Dependence.NO

    # ------------------------------------------------------------ refs

    def _refs(self, nodes: Sequence[ast.AST], frame: Frame, max_depth: int = MAX_DATAFLOW_DEPTH, skip: frozenset[str] = frozenset()) -> tuple[SymbolRef, ...]:
        found: dict[tuple[str, str], SymbolRef] = {}

        def add(name: str, qualified: str | None, role: str) -> None:
            top = (qualified or name).split(".")[0].lstrip(".")
            if qualified is None or top in _STDLIB or top in _BUILTINS:
                return
            found.setdefault((name, role), SymbolRef(name, qualified, (), role))

        def qualify(d: str, fr: Frame) -> str | None:
            root, _, rest = d.partition(".")
            root = root.removesuffix("()")
            if root in fr.mod.imports:
                return fr.mod.imports[root] + (("." + rest) if rest else "")
            vals = fr.assigns.get(root, [])
            if len(vals) == 1 and isinstance(vals[0], ast.Call):  # obj = Cls(); obj.method()
                inner = dotted(vals[0].func)
                if inner:
                    iroot, _, irest = inner.partition(".")
                    base = fr.mod.imports.get(iroot)
                    base = base + (("." + irest) if irest else "") if base else None
                    if base:
                        return base + (("." + rest) if rest else "")
            return None

        def visit(n: ast.AST, fr: Frame, depth: int, seen: frozenset[str]) -> None:
            if isinstance(n, ast.Call):
                dn = dotted(n.func)
                if dn:
                    add(dn, qualify(dn, fr), "call")
                    root = dn.split(".")[0].removesuffix("()")
                    if root not in seen:
                        expand(root, fr, depth, seen)
                else:
                    visit(n.func, fr, depth, seen)
                for a in [*n.args, *(k.value for k in n.keywords)]:
                    visit(a, fr, depth, seen)
            elif isinstance(n, ast.Attribute):
                dn = dotted(n)
                if dn and "()" not in dn:
                    q = qualify(dn, fr)
                    if q is not None:
                        add(dn, q, "attribute")
                    else:
                        expand(dn.split(".")[0], fr, depth, seen)
                else:
                    visit(n.value, fr, depth, seen)
            elif isinstance(n, ast.Name):
                if n.id in fr.mod.imports and n.id not in fr.assigns:
                    add(n.id, qualify(n.id, fr), "attribute")
                else:
                    expand(n.id, fr, depth, seen)
            else:
                for c in ast.iter_child_nodes(n):
                    visit(c, fr, depth, seen)

        def expand(name: str, fr: Frame, depth: int, seen: frozenset[str]) -> None:
            if depth >= max_depth or name in seen or name in skip:
                return
            nxt = seen | {name}
            if name in fr.params:
                pnode, pframe = fr.params[name]
                visit(pnode, pframe, depth + 1, nxt)
            for v in fr.assigns.get(name, [])[:4]:
                visit(v, fr, depth + 1, nxt)

        for n in nodes:
            visit(n, frame, 0, frozenset())
        return tuple(sorted(found.values(), key=lambda r: (r.name, r.role)))

    def _resolve_refs(self, refs: tuple[SymbolRef, ...], test_id: str) -> tuple[SymbolRef, ...]:
        if self.resolver is None:
            return refs
        out = []
        for r in refs:
            try:
                ids = tuple(sorted(self.resolver.resolve(test_id, r.name, r.qualified, self.mod.path)))
            except Exception:  # noqa: BLE001 - a plugged-in resolver must never break extraction
                ids = ()
            out.append(SymbolRef(r.name, r.qualified, ids, r.role))
        return tuple(out)


@dataclass(slots=True)
class _Flags:
    in_loop: bool = False
    swallowed: bool = False

    def with_(self, **kw: bool) -> _Flags:
        return _Flags(kw.get("in_loop", self.in_loop), kw.get("swallowed", self.swallowed))


@dataclass(slots=True)
class _TestCtx:
    test_id: str
    root: Frame
    parametrized: bool
    hypothesis: bool
    edge: bool | None
    edge_source: str | None
    asserted_names: frozenset[str]
    emitted: list[AssertionRecord] = field(default_factory=list)
    helper_calls: int = 0
    truncated: bool = False
    dynamic: bool = False


_OPS: dict[type, str] = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Is: "is",
    ast.IsNot: "is not",
    ast.In: "in",
    ast.NotIn: "not in",
}


def _const_truthy(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and bool(node.value)


def _tautology(a: ast.AST | None, b: ast.AST | None) -> str | None:
    if a is None or b is None or _has_call(a) or _has_call(b):
        return None
    try:
        return "tautology" if ast.dump(a) == ast.dump(b) and not isinstance(a, ast.Constant) else None
    except RecursionError:
        return None


def _attr_receiver(node: ast.AST) -> ast.AST | None:
    if isinstance(node, ast.Attribute):
        return node.value
    if isinstance(node, ast.Subscript | ast.Call):
        return _attr_receiver(node.value if isinstance(node, ast.Subscript) else node.func)
    return None


def _approx_tol(call: ast.Call) -> tuple[float | None, float | None]:
    rel, ab = _num(_kw(call, "rel")), _num(_kw(call, "abs"))
    if rel is None and ab is None:
        return 1e-6, 1e-12  # pytest defaults
    return rel, ab


def _exception_spec(node: ast.AST | None, match: bool) -> ExceptionSpecificity:
    if node is None:
        return ExceptionSpecificity.NONE
    names = [dotted(e) for e in node.elts] if isinstance(node, ast.Tuple) else [dotted(node)]
    names = [n for n in names if n]
    if not names:
        return ExceptionSpecificity.NONE
    if all(n.split(".")[-1] in _BROAD_EXC for n in names):
        return ExceptionSpecificity.BROAD
    return ExceptionSpecificity.SPECIFIC_MATCH if match else ExceptionSpecificity.SPECIFIC


def _args_expected(call: ast.Call) -> list[ast.expr]:
    return [*call.args, *(k.value for k in call.keywords)]


def _unparse_args(call: ast.Call) -> str:
    parts = [_unparse(a) for a in call.args] + [f"{k.arg}={_unparse(k.value)}" for k in call.keywords if k.arg]
    return _clip(", ".join(parts))


def _args_complexity(call: ast.Call) -> int:
    best = 0
    for a in _args_expected(call):
        if (dotted(a) or "").split(".")[-1] == "ANY":
            continue
        info = literal_info(a)
        if info:
            best = max(best, info[1])
    return best


def _root_name(callee: str) -> str:
    return callee.split(".")[0].removesuffix("()")


def _mock_origin_name(name: str, frame: Frame) -> str | None:
    return frame.mocks.get(name)


def _escaped_mocks(frame: Frame) -> set[str]:
    """Created mocks that leave the test body (passed on, stored, aliased): then the code
    under test may call them, so asserting on them is not mock-only."""

    if frame.escaped is not None:
        return frame.escaped
    created = {n for n, o in frame.mocks.items() if o == "created"}
    out: set[str] = set()
    frame.escaped = out
    if not created:
        return out
    stack: list[tuple[ast.AST, ast.AST | None]] = [(st, None) for st in frame.func.body]
    parents: dict[int, ast.AST | None] = {}
    nodes: list[ast.AST] = []
    while stack:
        node, parent = stack.pop()
        parents[id(node)] = parent
        nodes.append(node)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        stack.extend((c, node) for c in ast.iter_child_nodes(node))
    for node in nodes:
        if not (isinstance(node, ast.Name) and node.id in created and isinstance(node.ctx, ast.Load)):
            continue
        cur: ast.AST = node
        called = False
        while True:
            p = parents.get(id(cur))
            if isinstance(p, ast.Attribute) and p.value is cur or isinstance(p, ast.Subscript) and p.value is cur:
                cur = p
            elif isinstance(p, ast.Call) and p.func is cur:
                called = True
                cur = p
            else:
                break
        p = parents.get(id(cur))
        if called:
            continue
        if isinstance(p, ast.Call | ast.keyword | ast.Dict | ast.List | ast.Tuple | ast.Set | ast.Starred | ast.Return | ast.Yield | ast.YieldFrom | ast.Await):
            out.add(node.id)
        elif isinstance(p, ast.Assign | ast.AnnAssign | ast.AugAssign | ast.NamedExpr) and getattr(p, "value", None) is cur:
            out.add(node.id)
        elif isinstance(p, ast.withitem) and p.context_expr is cur:
            out.add(node.id)
    return out


def _names_in_assertions(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    names: set[str] = set()
    for node in _walk_body(fn.body):
        if isinstance(node, ast.Assert):
            names.update(n.id for n in ast.walk(node) if isinstance(n, ast.Name))
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in {"self", "cls"} and f.attr in _UNITTEST:
                for a in node.args:
                    names.update(n.id for n in ast.walk(a) if isinstance(n, ast.Name))
    return frozenset(names)

