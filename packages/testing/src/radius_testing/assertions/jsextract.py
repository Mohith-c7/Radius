"""TypeScript/JavaScript assertion extraction (LK-04). PARTIAL, best effort.

Uses the F-09 tree-sitter grammars (through ``radius_parser``). Models jest/vitest
``expect(x).matcher(...)`` (with ``.not``/``.resolves``/``.rejects``), a few
chai-style call matchers, and node ``assert.*``. NOT modelled: custom matchers,
chai property assertions (``.to.be.true``), ``expect.assertions``, helper
following, ``require()``, path aliases, type information, data flow through
reassignments. Every record from this module has confidence <= 0.7.
"""

from __future__ import annotations

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
from radius_testing.linking.ecmascript import (
    _block_call,
    _text,
    _unquote,
    _walk,
    parse_js_test_file,
)

MAX_TEXT = 200
CONFIDENCE = 0.7
_MAX_FILE_BYTES = 1_000_000
_MODIFIERS = {"not", "resolves", "rejects", "to", "be", "been", "have", "deep", "that", "which", "is", "does"}
_BUILTIN_CALLEES = {"Math", "JSON", "Object", "Array", "String", "Number", "Date", "parseInt", "parseFloat", "expect", "jest", "vi"}

# matcher -> (kind, exactness)
_MATCHERS: dict[str, tuple[K, Exactness]] = {
    "toBe": (K.EQUALITY, Exactness.EXACT),
    "toEqual": (K.EQUALITY, Exactness.EXACT),
    "toStrictEqual": (K.EQUALITY, Exactness.EXACT),
    "equal": (K.EQUALITY, Exactness.EXACT),
    "eql": (K.EQUALITY, Exactness.EXACT),
    "toMatchObject": (K.EQUALITY, Exactness.MEMBERSHIP),
    "toBeTruthy": (K.TRUTHINESS, Exactness.TRUTHINESS),
    "toBeFalsy": (K.TRUTHINESS, Exactness.TRUTHINESS),
    "toBeNull": (K.NONE_CHECK, Exactness.NONE_ONLY),
    "toBeUndefined": (K.NONE_CHECK, Exactness.NONE_ONLY),
    "toBeDefined": (K.NONE_CHECK, Exactness.NONE_ONLY),
    "toBeNaN": (K.NONE_CHECK, Exactness.NONE_ONLY),
    "toBeGreaterThan": (K.COMPARISON, Exactness.ORDERING),
    "toBeGreaterThanOrEqual": (K.COMPARISON, Exactness.ORDERING),
    "toBeLessThan": (K.COMPARISON, Exactness.ORDERING),
    "toBeLessThanOrEqual": (K.COMPARISON, Exactness.ORDERING),
    "above": (K.COMPARISON, Exactness.ORDERING),
    "below": (K.COMPARISON, Exactness.ORDERING),
    "toBeCloseTo": (K.APPROX, Exactness.APPROX),
    "closeTo": (K.APPROX, Exactness.APPROX),
    "toContain": (K.MEMBERSHIP, Exactness.MEMBERSHIP),
    "toContainEqual": (K.MEMBERSHIP, Exactness.MEMBERSHIP),
    "toHaveProperty": (K.MEMBERSHIP, Exactness.MEMBERSHIP),
    "include": (K.MEMBERSHIP, Exactness.MEMBERSHIP),
    "toHaveLength": (K.LENGTH, Exactness.LENGTH_ONLY),
    "lengthOf": (K.LENGTH, Exactness.LENGTH_ONLY),
    "toMatch": (K.REGEX, Exactness.PATTERN),
    "match": (K.REGEX, Exactness.PATTERN),
    "toBeInstanceOf": (K.TYPE_CHECK, Exactness.TYPE_ONLY),
    "instanceOf": (K.TYPE_CHECK, Exactness.TYPE_ONLY),
    "toThrow": (K.EXCEPTION, Exactness.EXCEPTION),
    "toThrowError": (K.EXCEPTION, Exactness.EXCEPTION),
    "throw": (K.EXCEPTION, Exactness.EXCEPTION),
    "toHaveBeenCalled": (K.MOCK_CALL, Exactness.CALL_ONLY),
    "toBeCalled": (K.MOCK_CALL, Exactness.CALL_ONLY),
    "toHaveBeenCalledTimes": (K.MOCK_CALL, Exactness.CALL_ONLY),
    "toHaveBeenCalledWith": (K.MOCK_CALL, Exactness.CALL_ARGS),
    "toHaveBeenLastCalledWith": (K.MOCK_CALL, Exactness.CALL_ARGS),
    "toHaveBeenNthCalledWith": (K.MOCK_CALL, Exactness.CALL_ARGS),
    "toHaveReturnedWith": (K.MOCK_CALL, Exactness.CALL_ARGS),
    "toMatchSnapshot": (K.SNAPSHOT, Exactness.SNAPSHOT),
    "toMatchInlineSnapshot": (K.SNAPSHOT, Exactness.SNAPSHOT),
    "toThrowErrorMatchingSnapshot": (K.SNAPSHOT, Exactness.SNAPSHOT),
    "toThrowErrorMatchingInlineSnapshot": (K.SNAPSHOT, Exactness.SNAPSHOT),
}
_NODE_ASSERT: dict[str, tuple[K, Exactness, bool]] = {
    "ok": (K.TRUTHINESS, Exactness.TRUTHINESS, False),
    "equal": (K.EQUALITY, Exactness.EXACT, False),
    "strictEqual": (K.EQUALITY, Exactness.EXACT, False),
    "deepEqual": (K.EQUALITY, Exactness.EXACT, False),
    "deepStrictEqual": (K.EQUALITY, Exactness.EXACT, False),
    "notEqual": (K.EQUALITY, Exactness.EXACT, True),
    "notStrictEqual": (K.EQUALITY, Exactness.EXACT, True),
    "notDeepEqual": (K.EQUALITY, Exactness.EXACT, True),
    "notDeepStrictEqual": (K.EQUALITY, Exactness.EXACT, True),
    "throws": (K.EXCEPTION, Exactness.EXCEPTION, False),
    "rejects": (K.EXCEPTION, Exactness.EXCEPTION, False),
    "match": (K.REGEX, Exactness.PATTERN, False),
}


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 3] + "..."


def _args(call) -> list:  # noqa: ANN001, ANN202
    a = call.child_by_field_name("arguments")
    return [c for c in a.children if c.is_named and c.type != "comment"] if a is not None else []


def _js_literal(node) -> tuple[str, int] | None:  # noqa: ANN001
    t = node.type
    txt = _text(node)
    if t in ("true", "false"):
        return ("bool", 1)
    if t in ("null", "undefined") or txt == "undefined":
        return ("none", 1)
    if t == "number":
        return ("int" if txt.lstrip("-").isdigit() else "float", 1 if txt in ("0", "1") else 2)
    if t == "string":
        inner = _unquote(txt)
        return ("str", 1 if inner == "" else (3 if len(inner) > 24 else 2))
    if t == "template_string" and "${" not in txt:
        return ("str", 2)
    if t == "unary_expression" and node.children and _text(node.children[0]) == "-":
        inner = _js_literal(node.children[-1])
        return (inner[0], 2) if inner and inner[0] in ("int", "float") else None
    if t in ("array", "object"):
        elems = [c for c in node.children if c.is_named]
        if not elems:
            return ("collection", 1)
        parts = []
        for e in elems:
            if e.type in ("pair",):
                v = e.child_by_field_name("value")
                lit = _js_literal(v) if v is not None else None
                parts.append(lit)
            else:
                parts.append(_js_literal(e))
        if any(p is None for p in parts):
            return None
        nested = any(e.type in ("array", "object") for e in elems) or any(
            c.type in ("array", "object") for e in elems for c in e.children
        )
        return ("collection", 3 if nested or len(elems) > 2 else 2)
    return None


def _is_edge(node) -> bool:  # noqa: ANN001
    t = node.type
    txt = _text(node)
    if t in ("null", "undefined") or txt == "undefined":
        return True
    if t == "number":
        return txt in ("0", "0.0") or txt.startswith("-")
    if t == "unary_expression":
        return bool(node.children) and _text(node.children[0]) == "-"
    if t == "string":
        return _unquote(txt) == ""
    if t in ("array", "object"):
        return not [c for c in node.children if c.is_named]
    return txt in ("NaN", "Infinity")


def _dotted(node) -> str | None:  # noqa: ANN001
    if node is None:
        return None
    if node.type in ("identifier", "this"):
        return _text(node)
    if node.type == "member_expression":
        obj = _dotted(node.child_by_field_name("object"))
        prop = node.child_by_field_name("property")
        return None if obj is None or prop is None else f"{obj}.{_text(prop)}"
    return None


class JsExtractor:
    def __init__(self, path: str, source: str, files: object, resolver: SymbolResolver | None, linked: dict[str, frozenset[str]] | None) -> None:
        self.path = path
        self.resolver = resolver
        self.linked = linked
        self.records: list[AssertionRecord] = []
        self.summaries: list[TestSummary] = []
        self.notes: list[str] = []
        self.ok = False
        parsed = parse_js_test_file(path, source, files)  # type: ignore[arg-type]
        self.imports = parsed.imports if parsed is not None else {}
        from radius_parser.infrastructure.ecmascript_parser import parse_syntax_tree

        try:
            self.root, _err = parse_syntax_tree(source, "." + path.rsplit(".", 1)[-1])
        except Exception as exc:  # noqa: BLE001
            self.notes.append(f"could not parse {path}: {type(exc).__name__}")
            return
        self.ok = True

    def run(self) -> None:
        if self.ok:
            self._blocks(self.root, [])

    def _blocks(self, node, stack: list[str]) -> None:  # noqa: ANN001
        for child in node.children:
            block = _block_call(child)
            if block is None:
                self._blocks(child, stack)
                continue
            kind, title, body = block
            if kind in ("describe", "suite"):
                self._blocks(body, [*stack, title])
            else:
                call = child.children[0] if child.type == "expression_statement" and child.children else child
                fn = call.child_by_field_name("function")
                each = fn is not None and ".each" in _text(fn)
                self._test("::".join([self.path, *stack, title]), call, body, each)

    def _test(self, test_id: str, call, body, each: bool) -> None:  # noqa: ANN001
        mocks = self._mocks(body)
        edge, source = self._edge(call, body, each)
        count_before = len(self.records)
        self._visit(body, test_id, mocks, each, edge, source, False, False)
        count = len(self.records) - count_before
        self.summaries.append(
            TestSummary(
                test_id=test_id,
                path=self.path,
                line=call.start_point[0] + 1,
                language="typescript" if self.path.endswith((".ts", ".tsx", ".mts", ".cts")) else "javascript",
                assertion_count=count,
                has_assertions=count > 0,
                parametrized=each,
            )
        )

    def _mocks(self, body) -> dict[str, str]:  # noqa: ANN001
        out: dict[str, str] = {}
        for n in _walk(body):
            if n.type == "variable_declarator":
                name, value = n.child_by_field_name("name"), n.child_by_field_name("value")
                if name is None or value is None or value.type != "call_expression":
                    continue
                d = _dotted(value.child_by_field_name("function")) or ""
                if d in ("jest.fn", "vi.fn"):
                    out[_text(name)] = "created"
                elif d in ("jest.spyOn", "vi.spyOn"):
                    out[_text(name)] = "patched"
        return out

    def _edge(self, call, body, each: bool) -> tuple[bool | None, str | None]:  # noqa: ANN001
        if each:
            fn = call.child_by_field_name("function")
            table_call = fn if fn is not None and fn.type == "call_expression" else None
            args = _args(table_call) if table_call is not None else []
            if args and args[0].type == "array":
                leaves = [n for n in _walk(args[0]) if n.type not in ("array", "pair", "object", ",")]
                return (any(_is_edge(n) for n in leaves), "parametrize")
            return (None, None)
        seen = False
        for n in _walk(body):
            if n.type == "call_expression":
                for a in _args(n):
                    if _js_literal(a) is not None:
                        seen = True
                        if _is_edge(a):
                            return (True, "call_args")
        return (False, "call_args") if seen else (None, None)

    def _visit(self, node, test_id, mocks, each, edge, src, in_loop, swallowed) -> None:  # noqa: ANN001
        t = node.type
        if t in ("for_statement", "for_in_statement", "while_statement", "do_statement"):
            in_loop = True
        if t == "try_statement":
            handler = node.child_by_field_name("handler")
            swallow = handler is not None and not any(n.type == "throw_statement" for n in _walk(handler))
            for c in node.children:
                if c is handler:
                    self._visit(c, test_id, mocks, each, edge, src, in_loop, swallowed)
                else:
                    self._visit(c, test_id, mocks, each, edge, src, in_loop, swallowed or swallow)
            return
        if t == "call_expression":
            fn = node.child_by_field_name("function")
            if fn is not None and fn.type == "member_expression":
                prop = fn.child_by_field_name("property")
                if prop is not None and _text(prop) in ("forEach", "map", "every", "some", "filter"):
                    in_loop = True
            self._call(node, test_id, mocks, each, edge, src, in_loop, swallowed)
        for c in node.children:
            self._visit(c, test_id, mocks, each, edge, src, in_loop, swallowed)

    def _call(self, call, test_id, mocks, each, edge, src, in_loop, swallowed) -> None:  # noqa: ANN001, C901
        fn = call.child_by_field_name("function")
        if fn is None:
            return
        args = _args(call)
        # assert(x) / assert.ok(x) / assert.equal(a, b)
        d = _dotted(fn) or ""
        if d == "assert" and args:
            self._emit(call, test_id, K.TRUTHINESS, "truthy", Exactness.TRUTHINESS, args[0], None, [], mocks, each, edge, src, in_loop, swallowed, "node-assert")
            return
        if d.startswith(("assert.", "assert.strict.")):
            name = d.split(".")[-1]
            spec = _NODE_ASSERT.get(name)
            if spec is not None and args:
                kind, exact, neg = spec
                exp = args[1] if len(args) > 1 and kind is not K.EXCEPTION else (args[1] if kind is K.EXCEPTION and len(args) > 1 else None)
                self._emit(call, test_id, kind, name, exact, args[0], exp, [], mocks, each, edge, src, in_loop, swallowed, "node-assert", negated=neg)
            return
        if fn.type != "member_expression":
            return
        matcher = _text(fn.child_by_field_name("property"))
        if matcher not in _MATCHERS:
            return
        obj = fn.child_by_field_name("object")
        negated = False
        mods: list[str] = []
        while obj is not None and obj.type == "member_expression":
            prop = _text(obj.child_by_field_name("property"))
            if prop not in _MODIFIERS:
                return
            mods.append(prop)
            negated = negated or prop == "not"
            obj = obj.child_by_field_name("object")
        if obj is None or obj.type != "call_expression" or _dotted(obj.child_by_field_name("function")) != "expect":
            return
        subj_args = _args(obj)
        subject = subj_args[0] if subj_args else None
        kind, exact = _MATCHERS[matcher]
        extra: dict = {}
        if matcher == "toBeCloseTo" or matcher == "closeTo":
            digits = 2
            if len(args) > 1 and args[1].type == "number":
                try:
                    digits = float(_text(args[1]))
                except ValueError:
                    digits = 2
            extra["tol_abs"] = 10 ** (-digits) / 2
        if kind is K.EXCEPTION:
            spec_e = ExceptionSpecificity.BROAD
            if args:
                spec_e = ExceptionSpecificity.SPECIFIC if args[0].type in ("identifier", "member_expression") else ExceptionSpecificity.SPECIFIC_MATCH
            extra["exc"] = spec_e
            extra["exc_match"] = bool(args) and args[0].type in ("string", "regex", "template_string")
        if kind is K.SNAPSHOT:
            extra["snapshot_library"] = "jest"
        exp_nodes = args[:1] if args else []
        if matcher in {"toHaveBeenCalledWith", "toHaveBeenLastCalledWith", "toHaveBeenNthCalledWith", "toHaveBeenCalledTimes"}:
            exp_nodes = args
        self._emit(call, test_id, kind, matcher, exact, subject, exp_nodes[0] if exp_nodes and kind is not K.MOCK_CALL else None, exp_nodes if kind is K.MOCK_CALL else [], mocks, each, edge, src, in_loop, swallowed, "jest", negated=negated, **extra)

    def _emit(self, call, test_id, kind, comparator, exact, subject, expected, expected_many, mocks, each, edge, src, in_loop, swallowed, framework, *, negated=False, tol_abs=None, exc=ExceptionSpecificity.NONE, exc_match=False, snapshot_library=None) -> None:  # noqa: ANN001
        subject_text = _clip(_text(subject)) if subject is not None else ""
        refs = self._refs(subject, test_id)
        exp_nodes = [expected] if expected is not None else list(expected_many)
        exp_text = _clip(", ".join(_text(e) for e in exp_nodes))
        lit = _js_literal(expected) if expected is not None else None
        comp = max((_js_literal(e) or ("", 0))[1] for e in exp_nodes) if exp_nodes else 0
        if kind is K.SNAPSHOT:
            exp = Expected(exp_text or "<snapshot>", "snapshot", None, 0)
        elif kind is K.EXCEPTION:
            exp = Expected(exp_text, "exception_type" if exc is ExceptionSpecificity.SPECIFIC else "pattern" if exp_text else "none", None, 2 if exp_text else 1)
        elif not exp_nodes:
            exp = Expected()
        elif lit is not None or kind is K.MOCK_CALL:
            exp = Expected(exp_text, "literal" if comp else "expression", lit[0] if lit else None, comp)
        else:
            exp = Expected(exp_text, "expression", None, 0)
        dead = None
        if subject is not None and expected is not None and kind in (K.EQUALITY,) and _js_literal(subject) and lit:
            dead = "literal_comparison"
        if subject is not None and kind is K.TRUTHINESS and _js_literal(subject) is not None:
            dead = "constant_true"
        circular = False
        if subject is not None and expected is not None and kind not in (K.EXCEPTION, K.MOCK_CALL, K.SNAPSHOT):
            circular = bool(self._callees(subject) & self._callees(expected))
        idents = (
            {_text(n) for n in _walk(subject) if n.type == "identifier"} - _BUILTIN_CALLEES if subject is not None else set()
        )
        mock_only = bool(idents) and all(mocks.get(i) == "created" for i in idents)
        origins = {mocks[i] for i in idents if i in mocks}
        dep = Dependence.UNKNOWN
        if self.linked is not None:
            ids = {sid for r in refs for sid in r.symbol_ids}
            if ids:
                dep = Dependence.YES if ids & self.linked.get(test_id, frozenset()) else Dependence.NO
        feats = StrengthFeatures(
            exactness=exact if dead is None else Exactness.NONE,
            value_specificity=exp.complexity,
            distinct_subject_symbols=len({r.qualified or r.name for r in refs}),
            edge_inputs=edge,
            edge_input_source=src,
            exception_specificity=exc,
            exception_match=exc_match,
            tolerance_abs=tol_abs,
            depends_on_changed=dep,
            circular=circular,
            mock_only=mock_only,
            mock_origin=("created" if "created" in origins else ("patched" if origins else None)),
            in_loop=in_loop,
            in_parametrized=each,
            swallowed=swallowed,
            dead=dead is not None,
            dead_reason=dead,
            negated=negated,
            snapshot_library=snapshot_library,
        )
        self.records.append(
            AssertionRecord(
                test_id=test_id,
                kind=kind,
                subject_text=subject_text,
                subject_refs=refs,
                expected=exp,
                comparator=comparator,
                strength_features=feats,
                location=Location(self.path, call.start_point[0] + 1, call.end_point[0] + 1),
                framework=framework,
                confidence=CONFIDENCE,
                col=call.start_point[1],
            )
        )

    def _callees(self, node) -> set[str]:  # noqa: ANN001
        out: set[str] = set()
        for n in _walk(node):
            if n.type == "call_expression":
                d = _dotted(n.child_by_field_name("function"))
                if d and d.split(".")[0] not in _BUILTIN_CALLEES:
                    out.add(d)
        return out

    def _refs(self, subject, test_id: str) -> tuple[SymbolRef, ...]:  # noqa: ANN001
        if subject is None:
            return ()
        found: dict[str, SymbolRef] = {}
        for n in _walk(subject):
            if n.type != "call_expression":
                continue
            d = _dotted(n.child_by_field_name("function"))
            if not d:
                continue
            root, _, rest = d.partition(".")
            if root not in self.imports:
                continue
            resolved, member = self.imports[root]
            if not resolved:
                continue
            m = rest.split(".")[0] if member == "*" and rest else member
            qualified = f"{resolved}#{m}"
            ids: tuple[str, ...] = ()
            if self.resolver is not None:
                try:
                    ids = tuple(sorted(self.resolver.resolve(test_id, d, qualified, self.path)))
                except Exception:  # noqa: BLE001
                    ids = ()
            found.setdefault(d, SymbolRef(d, qualified, ids, "call"))
        return tuple(sorted(found.values(), key=lambda r: r.name))


def extract_js_file(
    path: str,
    source: str,
    files: object,
    resolver: SymbolResolver | None,
    linked: dict[str, frozenset[str]] | None,
) -> tuple[list[AssertionRecord], list[TestSummary], list[str]]:
    if len(source) > _MAX_FILE_BYTES:
        return [], [], [f"{path}: skipped, larger than {_MAX_FILE_BYTES} bytes"]
    ex = JsExtractor(path, source, files, resolver, linked)
    ex.run()
    return ex.records, ex.summaries, ex.notes
