"""Python AST helpers shared by the tamper rules (assertions and test functions).

Everything is pure and deterministic. ``ast.unparse`` text is used for snippets and
equality keys so pure formatting changes never look like a change.
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field

# strength ranks: higher means the check can fail in more situations
STRENGTH = {
    "exact": 5,
    "approx": 5,
    "raises": 5,
    "membership": 3,
    "ordering": 3,
    "mock_assert": 2,
    "negative": 2,
    "isinstance": 2,
    "not_none": 1,
    "truthy": 1,
    "tautology": 0,
}

_UNITTEST_EXACT = {
    "assertEqual", "assertEquals", "assertIs", "assertIsNone", "assertDictEqual",
    "assertListEqual", "assertTupleEqual", "assertSetEqual", "assertCountEqual",
    "assertSequenceEqual", "assertMultiLineEqual",
}
_UNITTEST_ORDERING = {
    "assertGreater", "assertGreaterEqual", "assertLess", "assertLessEqual",
    "assertRegex", "assertRegexpMatches", "assertIn", "assertDictContainsSubset",
}
_UNITTEST_NEGATIVE = {"assertNotEqual", "assertNotEquals", "assertIsNot", "assertNotIn",
                      "assertNotRegex"}
_UNITTEST_RAISES = {"assertRaises", "assertRaisesRegex", "assertRaisesRegexp",
                    "assertWarns", "assertWarnsRegex"}
_CALL_NOISE = frozenset(dir(builtins)) | {
    "raises", "approx", "patch", "MagicMock", "Mock", "AsyncMock", "skip", "fixture",
    "mark", "setattr", "object", "parametrize", "param", "fail", "importorskip", "warns",
    "delattr", "setenv", "monkeypatch", "dict", "assert_called", "assert_called_once",
    "assert_called_with", "assert_called_once_with", "assert_not_called", "assert_any_call",
    "format", "join", "append", "get", "items", "keys", "values", "sleep",
}
_DEFAULT_REL = 1e-6
_DEFAULT_ABS = 1e-12


def parse_python(text: str) -> ast.Module:
    """Parse or raise ``SyntaxError``/``ValueError``/``RecursionError``/``MemoryError``."""
    return ast.parse(text)


def unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - defensive, ast.unparse is total on parsed trees
        return "<unprintable>"


def dump(node: ast.AST) -> str:
    return ast.dump(node, annotate_fields=False)


def node_span(node: ast.AST) -> tuple[int, int]:
    start = getattr(node, "lineno", 0)
    return start, getattr(node, "end_lineno", start) or start


def _number(node: ast.AST) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float) \
            and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _number(node.operand)
        return None if inner is None else -inner
    return None


def literal_text(node: ast.AST) -> str | None:
    """Unparse of ``node`` when it is a pure literal (numbers, strings, containers of them)."""
    try:
        ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None
    return unparse(node)


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _truthy_constant(node: ast.AST) -> bool | None:
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, ast.Tuple | ast.List | ast.Set | ast.Dict):
        elts = node.keys if isinstance(node, ast.Dict) else node.elts
        return bool(elts)
    return None


def _is_call_to(node: ast.AST, *names: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (isinstance(f, ast.Name) and f.id in names) or (
        isinstance(f, ast.Attribute) and f.attr in names
    )


def _approx_params(call: ast.Call) -> tuple[float, float]:
    rel: float = _DEFAULT_REL
    abs_: float = _DEFAULT_ABS
    explicit = False
    for kw in call.keywords:
        value = _number(kw.value)
        if kw.arg == "rel" and value is not None:
            rel, explicit = value, True
        elif kw.arg == "abs" and value is not None:
            abs_, explicit = value, True
    if explicit and not any(k.arg == "rel" for k in call.keywords):
        rel = 0.0  # pytest: only abs given means abs is the sole tolerance
    return rel, abs_


@dataclass(frozen=True, slots=True)
class Assertion:
    kind: str
    text: str
    key: str
    start: int
    end: int
    op: str = ""  # normalized operator: eq, ne, is, in, lt ... or unittest name
    expected: str | None = None  # unparse of the expected operand when a literal
    callee: str | None = None  # name of the called function on the left, when any
    conjuncts: int = 1
    tautology: str | None = None
    tolerance: tuple[float, float] | None = None  # (rel, abs) for approx / almost-equal
    raises: str | None = None
    mock_target: str | None = None

    @property
    def strength(self) -> int:
        return STRENGTH[self.kind]


def _callee(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name):
            return f.id
        if isinstance(f, ast.Attribute):
            return f.attr
    return None


_OPS = {
    ast.Eq: "eq", ast.NotEq: "ne", ast.Is: "is", ast.IsNot: "isnot", ast.In: "in",
    ast.NotIn: "notin", ast.Lt: "lt", ast.LtE: "le", ast.Gt: "gt", ast.GtE: "ge",
}


def _classify_compare(node: ast.Compare) -> tuple[str, str, str | None, str | None]:
    """Return (kind, op, expected, tautology_reason) for a comparison expression."""
    left = node.left
    if len(node.ops) != 1:
        return "ordering", "chain", None, None
    right = node.comparators[0]
    op = type(node.ops[0])
    name = _OPS.get(op, "?")
    expected = literal_text(right)
    if op in (ast.Eq, ast.Is, ast.LtE, ast.GtE) and dump(left) == dump(right):
        return "tautology", name, expected, f"`{unparse(left)}` is compared with itself"
    if _is_call_to(right, "approx") and op is ast.Eq:
        return "approx", name, None, None
    if _is_call_to(left, "approx") and op is ast.Eq:
        return "approx", name, None, None
    if op in (ast.Eq, ast.Is):
        return "exact", name, expected, None
    if op in (ast.NotEq, ast.IsNot):
        if _is_none(right) or _is_none(left):
            return "not_none", name, "None", None
        return "negative", name, expected, None
    if op in (ast.In,):
        return "membership", name, expected, None
    if op in (ast.NotIn,):
        return "negative", name, expected, None
    return "ordering", name, expected, None


def classify_expr(expr: ast.AST) -> Assertion:
    """Classify the truth-test expression of an ``assert`` (or ``assertTrue`` argument)."""
    text = unparse(expr)
    key = dump(expr)
    start, end = node_span(expr)

    def make(kind: str, **kw: object) -> Assertion:
        return Assertion(kind=kind, text=text, key=key, start=start, end=end, **kw)

    const = _truthy_constant(expr)
    if const is True:
        return make("tautology", tautology=f"`{text}` is a constant that is always true")
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
        inner = _truthy_constant(expr.operand)
        if inner is False:
            return make("tautology", tautology=f"`{text}` is always true")
        return make("truthy", op="not")
    if isinstance(expr, ast.BoolOp):
        parts = [classify_expr(v) for v in expr.values]
        if isinstance(expr.op, ast.Or) and any(_truthy_constant(v) is True for v in expr.values):
            return make("tautology", tautology=f"`{text}` contains an always-true alternative")
        weakest = min(parts, key=lambda a: a.strength)
        if isinstance(expr.op, ast.And):
            return Assertion(
                kind=weakest.kind, text=text, key=key, start=start, end=end, op=weakest.op,
                conjuncts=sum(p.conjuncts for p in parts), tautology=weakest.tautology
                if all(p.tautology for p in parts) else None,
            )
        return make(weakest.kind if weakest.kind != "exact" else "ordering", op="or")
    if isinstance(expr, ast.Compare):
        kind, op, expected, taut = _classify_compare(expr)
        tol = None
        if kind == "approx":
            call = expr.comparators[0] if _is_call_to(expr.comparators[0], "approx") else expr.left
            tol = _approx_params(call)
        left_call = _callee(expr.left)
        return make(kind, op=op, expected=expected, callee=left_call, tautology=taut,
                    tolerance=tol)
    if _is_call_to(expr, "isinstance"):
        args = getattr(expr, "args", [])
        if len(args) == 2 and unparse(args[1]) == "object":
            return make("tautology", tautology="every object is an instance of `object`")
        return make("isinstance")
    return make("truthy", callee=_callee(expr))


def _unittest_assertion(call: ast.Call, name: str) -> Assertion | None:
    args = call.args
    text = unparse(call)
    key = dump(call)
    start, end = node_span(call)

    def make(kind: str, **kw: object) -> Assertion:
        return Assertion(kind=kind, text=text, key=key, start=start, end=end, **kw)

    if name in _UNITTEST_EXACT:
        if name == "assertIsNone":
            return make("exact", op="is", callee=_callee(args[0]) if args else None,
                        expected="None")
        if len(args) >= 2:
            if dump(args[0]) == dump(args[1]):
                return make("tautology", tautology=f"`{unparse(args[0])}` is compared with itself")
            exp = literal_text(args[1])
            return make("exact", op="eq", expected=exp, callee=_callee(args[0]))
        return make("exact", op="eq")
    if name in ("assertAlmostEqual", "assertAlmostEquals"):
        places = 7
        delta: float | None = None
        for kw in call.keywords:
            v = _number(kw.value)
            if kw.arg == "places" and v is not None:
                places = int(v)
            if kw.arg == "delta" and v is not None:
                delta = v
        if len(args) >= 3 and (v3 := _number(args[2])) is not None:
            places = int(v3)
        absolute = delta if delta is not None else 0.5 * 10.0 ** (-places)
        return make("approx", op="almost", tolerance=(0.0, absolute),
                    callee=_callee(args[0]) if args else None)
    if name == "assertTrue":
        if not args:
            return make("truthy")
        inner = classify_expr(args[0])
        return Assertion(kind=inner.kind, text=text, key=key, start=start, end=end, op=inner.op,
                         expected=inner.expected, callee=inner.callee, tautology=inner.tautology,
                         tolerance=inner.tolerance, conjuncts=inner.conjuncts)
    if name == "assertFalse":
        if args and _truthy_constant(args[0]) is False:
            return make("tautology", tautology=f"`{text}` is always true")
        return make("truthy", op="not")
    if name == "assertIsNotNone":
        return make("not_none", op="isnot", expected="None", callee=_callee(args[0]) if args else None)
    if name == "assertIsInstance":
        return make("isinstance")
    if name in _UNITTEST_ORDERING:
        return make("membership" if name == "assertIn" else "ordering", op=name)
    if name in _UNITTEST_NEGATIVE:
        return make("negative", op=name)
    if name in _UNITTEST_RAISES:
        exc = unparse(args[0]) if args else None
        return make("raises", raises=exc, op=name)
    return None


def _raises_item(item: ast.withitem) -> Assertion | None:
    expr = item.context_expr
    if _is_call_to(expr, "raises", "warns", "assertRaises", "assertWarns", "assertRaisesRegex"):
        assert isinstance(expr, ast.Call)
        exc = unparse(expr.args[0]) if expr.args else None
        has_match = any(k.arg == "match" for k in expr.keywords) or (
            isinstance(expr.func, ast.Attribute) and expr.func.attr.endswith("Regex")
        )
        start, end = node_span(expr)
        return Assertion(
            kind="raises", text=unparse(expr), key=dump(expr), start=start, end=end,
            op="match" if has_match else "nomatch", raises=exc,
        )
    return None


def extract_assertions(fn: ast.AST) -> tuple[Assertion, ...]:
    """All assertions of a function body, in source order."""
    found: list[Assertion] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            a = classify_expr(node.test)
            found.append(Assertion(
                kind=a.kind, text=unparse(node.test), key=dump(node.test),
                start=node.lineno, end=node.end_lineno or node.lineno, op=a.op,
                expected=a.expected, callee=a.callee, conjuncts=a.conjuncts,
                tautology=a.tautology, tolerance=a.tolerance,
            ))
        elif isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                a = _raises_item(item)
                if a is not None:
                    found.append(a)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            f = call.func
            if isinstance(f, ast.Attribute):
                if f.attr.startswith("assert") and f.attr[6:7].isupper():
                    a = _unittest_assertion(call, f.attr)
                    if a is not None:
                        found.append(a)
                elif f.attr.startswith("assert_") or f.attr in ("assert_called",):
                    start, end = node_span(call)
                    found.append(Assertion(
                        kind="mock_assert", text=unparse(call), key=dump(call), start=start,
                        end=end, op=f.attr,
                    ))
    found.sort(key=lambda a: (a.start, a.end))
    return tuple(found)


def _is_stub_stmt(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return True  # docstring or `...`
    return False


def is_stub_body(body: list[ast.stmt]) -> bool:
    return all(_is_stub_stmt(s) for s in body)


@dataclass(slots=True)
class TestFn:
    __test__ = False
    qualname: str
    name: str
    class_name: str | None
    node: ast.FunctionDef | ast.AsyncFunctionDef
    start: int
    end: int
    decorators: tuple[str, ...]
    class_decorators: tuple[str, ...]
    assertions: tuple[Assertion, ...]
    called: frozenset[str]
    emptied: bool
    param_cases: tuple[str, ...] = ()
    text: str = ""

    @property
    def all_decorators(self) -> tuple[str, ...]:
        return self.class_decorators + self.decorators


@dataclass(slots=True)
class TestModule:
    __test__ = False
    tests: dict[str, TestFn] = field(default_factory=dict)
    module_marks: tuple[str, ...] = ()
    tree: ast.Module | None = None


def called_names(fn: ast.AST) -> frozenset[str]:
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            n = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if n and n not in _CALL_NOISE and not n.startswith(("assert", "_")):
                names.add(n)
    return frozenset(names)


def _param_cases(decorators: list[ast.expr]) -> tuple[str, ...]:
    cases: list[str] = []
    for d in decorators:
        if _is_call_to(d, "parametrize") and isinstance(d, ast.Call) and len(d.args) >= 2:
            values = d.args[1]
            if isinstance(values, ast.List | ast.Tuple):
                cases.extend(f"{unparse(d.args[0])}={unparse(e)}" for e in values.elts)
    return tuple(cases)


def _is_test_class(node: ast.ClassDef) -> bool:
    if node.name.startswith("Test"):
        return True
    return any("TestCase" in unparse(b) for b in node.bases)


def collect_tests(tree: ast.Module) -> TestModule:
    """Test functions of a module keyed by qualified name (``Class.method``)."""
    out = TestModule(tree=tree)
    marks: list[str] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
        ):
            marks.append(unparse(stmt.value))

    def add(fn: ast.FunctionDef | ast.AsyncFunctionDef, cls: ast.ClassDef | None) -> None:
        qual = f"{cls.name}.{fn.name}" if cls else fn.name
        start, end = node_span(fn)
        if fn.decorator_list:
            start = min(start, *(d.lineno for d in fn.decorator_list))
        body = fn.body
        emptied = is_stub_body(body)
        out.tests[qual] = TestFn(
            qualname=qual, name=fn.name, class_name=cls.name if cls else None, node=fn,
            start=start, end=end,
            decorators=tuple(unparse(d) for d in fn.decorator_list),
            class_decorators=tuple(unparse(d) for d in cls.decorator_list) if cls else (),
            assertions=extract_assertions(fn), called=called_names(fn), emptied=emptied,
            param_cases=_param_cases(fn.decorator_list), text=unparse(fn),
        )

    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef) and stmt.name.startswith("test"):
            add(stmt, None)
        elif isinstance(stmt, ast.ClassDef) and _is_test_class(stmt):
            for item in stmt.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.name.startswith("test"):
                    add(item, stmt)
    out.module_marks = tuple(marks)
    return out


def intersects(start: int, end: int, lines: set[int] | dict[int, str]) -> bool:
    """Whether any line of ``[start, end]`` is in ``lines`` (small loop; spans are short)."""
    if end - start > 2000:
        return any(start <= n <= end for n in lines)
    return any(n in lines for n in range(start, end + 1))
