#!/usr/bin/env python
"""Generate the Stage-A/Stage-B input bundles of the Verdict v2 vertical slice (VS-01).

For each of the 8 F-14 fixtures (``benchmarks/fixtures/intent/*``) this writes
``benchmarks/fixtures/verdict_v2/<fixture>/inputs.json``: plain JSON that conforms to the
frozen input contracts ``radius_evidence.domain.inputs`` (design 3.7). Two modes per fixture:

* ``gold``  - links come from ``expected.json`` (normative inputs of the VS-02 acceptance test);
* ``auto``  - links produced by the real LK-02 (criterion->symbol) and LK-03 (symbol->test) code.

Every part of each file is labelled in ``provenance`` as ``real`` (produced by repository code
at generation time), ``derived`` (computed from fixture data by this script) or ``hand_built``
(authored from ``expected.json`` / test bodies because no library produces it yet).

Usage (needs PYTHONPATH like CI, or just run it: ``packages/*/src`` are added automatically)::

    python scripts/verdict_v2_make_fixtures.py            # (re)write the bundles
    python scripts/verdict_v2_make_fixtures.py --check    # regenerate in memory, diff, exit 1 on drift

The tamper findings come from EV-02 (``radius_analysis.tamper``). When that package is not
importable (branch without EV-02) ``--check`` skips the tamper section with a notice and
compares everything else; writing requires it. ``RADIUS_VS01_EXTRA_SRC`` (``os.pathsep``-
separated source roots) is prepended to ``sys.path`` for generating against another checkout.

Offline and deterministic: no network, no clock, no randomness; ids are derived by hashing.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "benchmarks" / "fixtures" / "verdict_v2"
INTENT_DIR = ROOT / "benchmarks" / "fixtures" / "intent"
SCHEMA = "verdict-v2-fixture-inputs-1"
GENERATOR = "scripts/verdict_v2_make_fixtures.py"

for _extra in reversed([p for p in os.environ.get("RADIUS_VS01_EXTRA_SRC", "").split(os.pathsep) if p]):
    sys.path.insert(0, _extra)
for _src in sorted((ROOT / "packages").glob("*/src")):
    if str(_src) not in sys.path:
        sys.path.append(str(_src))

from radius_evidence.domain.enums import AssertKind, Outcome  # noqa: E402
from radius_evidence.domain.inputs import (  # noqa: E402
    CaseOutcomeInput,
    CriterionInput,
    CriterionSymbolEdgeInput,
    CriterionTestEdgeInput,
    StageAInput,
    SymbolInput,
    SymbolTestEdgeInput,
    TamperFindingInput,
)
from radius_evidence.domain.model import AssertionFact, AssertionFeatures, Reason  # noqa: E402
from radius_evidence.domain.serialization import encode  # noqa: E402
from radius_evidence.domain.versions import (  # noqa: E402
    ASSERTIONS_VERSION,
    CRITERION_SYMBOL_LINKS_VERSION,
    SYMBOL_CHANGES_VERSION,
    SYMBOL_TEST_LINKS_VERSION,
    TAMPER_VERSION,
)

try:  # EV-02 is on develop but not on every branch
    from radius_analysis.tamper import (  # noqa: E402
        StaticPackageRegistry,
        TamperConfig,
        analyze_tampering,
    )
    from radius_analysis.tamper.config import Params  # noqa: E402

    HAVE_TAMPER = True
except ImportError:  # pragma: no cover - depends on the checkout
    HAVE_TAMPER = False

# --- fixed, documented knobs -------------------------------------------------------------
GOLD_LINK_SCORE = 1.0  # design 7.3: l_cs = 1 for confirmed gold links
GOLD_SYMBOL_TEST_SCORE = 0.9  # design 7.3: l_st = 0.9
GOLD_CRITERION_TEST_WEIGHT = 1.0
GOLD_VERSION = "verdict-v2-fixture-gold-1"
HANDBUILT_ASSERTION_NOTE = "fixture-ast-v1"
#: Packages the offline registry knows; ``pytimeparse-ultra`` (fixture 06) is deliberately absent.
OFFLINE_REGISTRY_KNOWN = frozenset({"pytest", "requests", "pytimeparse"})
TESTABILITY = {
    "testable": "behavioral_testable",
    "vague": "subjective_or_vague",
    "non_functional": "non_functional_measurable",
}
_NS = uuid.UUID("5b0b9c6e-5a1d-4c1e-9a77-0000000000a1")
ALL_FIXTURES = (
    "01_correct_strong_tests",
    "02_correct_weak_tests",
    "03_incorrect_passes_weak_tests",
    "04_test_tampering",
    "05_scope_creep",
    "06_hallucinated_dependency",
    "07_vague_intent",
    "08_multi_criterion_partial_evidence",
)


def _load_intent_loader() -> Any:
    path = INTENT_DIR / "loader.py"
    spec = importlib.util.spec_from_file_location("verdict_v2_intent_fixture_loader", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- identifiers -----------------------------------------------------------------------


def fixture_ids(fixture_id: str) -> dict[str, str]:
    """Placeholder identifiers; deterministic functions of the fixture name."""
    return {
        "analysis_id": str(uuid.uuid5(_NS, f"{fixture_id}/analysis")),
        "repository_id": str(uuid.uuid5(_NS, f"{fixture_id}/repository")),
        "head_sha": hashlib.sha1(f"radius-verdict-v2-fixture/{fixture_id}/head".encode()).hexdigest(),  # noqa: S324
    }


# --- symbols -----------------------------------------------------------------------------


def _is_pseudo(sym: Any) -> bool:
    return sym.qualified_name in ("<module>", "<file>") or sym.kind in ("module", "file")


def symbol_inputs(changeset: Any, is_test_path: Any) -> list[SymbolInput]:
    return [
        SymbolInput(
            symbol_id=s.symbol_id,
            path=s.path,
            qualified_name=s.qualified_name,
            kind=s.kind,
            language=s.language,
            change_kind=s.change_kind.value,
            is_behavioral=bool(s.is_behavioral),
            is_test=bool(is_test_path(s.path)),
            is_pseudo=_is_pseudo(s),
        )
        for s in changeset.symbols
    ]


def _symbol_lookup(symbols: list[SymbolInput]) -> dict[tuple[str, str], str]:
    return {(s.path, s.qualified_name): s.symbol_id for s in symbols}


def resolve_gold_symbol(ref: str, lookup: dict[tuple[str, str], str]) -> str:
    """``path::name`` -> LK-01 symbol id. Module constants map to ``<module>`` (design 7.3 item 5)."""
    path, _, name = ref.partition("::")
    sid = lookup.get((path, name)) or lookup.get((path, "<module>"))
    if sid is None:
        raise KeyError(f"gold symbol {ref!r} is not a changed symbol of the fixture")
    return sid


# --- assertion features (hand-built from the test bodies) ------------------------------------

_COMPARE_BOUND = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)
_UNITTEST_KIND = {
    "assertEqual": AssertKind.VALUE_EQUALITY,
    "assertEquals": AssertKind.VALUE_EQUALITY,
    "assertAlmostEqual": AssertKind.APPROX_EQUALITY,
    "assertTrue": AssertKind.TRUTHINESS,
    "assertFalse": AssertKind.TRUTHINESS,
    "assertIsNone": AssertKind.NONE_CHECK,
    "assertIsNotNone": AssertKind.NONE_CHECK,
    "assertIn": AssertKind.MEMBERSHIP,
    "assertNotIn": AssertKind.MEMBERSHIP,
    "assertIsInstance": AssertKind.TYPE_CHECK,
    "assertGreater": AssertKind.COMPARISON_BOUND,
    "assertLess": AssertKind.COMPARISON_BOUND,
    "assertGreaterEqual": AssertKind.COMPARISON_BOUND,
    "assertLessEqual": AssertKind.COMPARISON_BOUND,
}


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _is_literal(node: ast.AST) -> bool:
    try:
        ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False
    return True


def _is_call_to(node: ast.AST, *names: str) -> bool:
    return isinstance(node, ast.Call) and _dotted(node.func) in names


def classify_assert(expr: ast.expr) -> list[tuple[AssertKind, bool]]:
    """Map one asserted expression to ``(kind, compares_computed_value)`` facts."""
    if isinstance(expr, ast.BoolOp):
        return [f for v in expr.values for f in classify_assert(v)]
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.op, ast.Not):
        inner = expr.operand
        if isinstance(inner, ast.Compare):
            return classify_assert(inner)
        return [(AssertKind.TRUTHINESS, not _is_literal(inner))]
    if isinstance(expr, ast.Compare) and len(expr.ops) == 1:
        op, left, right = expr.ops[0], expr.left, expr.comparators[0]
        if isinstance(op, (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)):
            if ast.dump(left) == ast.dump(right):
                return [(AssertKind.TAUTOLOGY, False)]
            if _is_call_to(left, "pytest.approx") or _is_call_to(right, "pytest.approx"):
                return [(AssertKind.APPROX_EQUALITY, True)]
            if any(isinstance(s, ast.Constant) and s.value is None for s in (left, right)):
                return [(AssertKind.NONE_CHECK, not _is_literal(left) or not _is_literal(right))]
            if _is_call_to(left, "len") and isinstance(op, (ast.Eq, ast.NotEq)):
                return [(AssertKind.LENGTH_CHECK, True)]
            return [(AssertKind.VALUE_EQUALITY, not (_is_literal(left) and _is_literal(right)))]
        if isinstance(op, _COMPARE_BOUND):
            return [(AssertKind.COMPARISON_BOUND, True)]
        if isinstance(op, (ast.In, ast.NotIn)):
            return [(AssertKind.MEMBERSHIP, True)]
        return [(AssertKind.OTHER, True)]
    if isinstance(expr, ast.Constant):
        return [(AssertKind.TAUTOLOGY, False)] if expr.value else [(AssertKind.OTHER, False)]
    if _is_call_to(expr, "isinstance"):
        return [(AssertKind.TYPE_CHECK, False)]
    if isinstance(expr, (ast.Name, ast.Call, ast.Attribute, ast.Subscript)):
        return [(AssertKind.TRUTHINESS, True)]
    return [(AssertKind.OTHER, True)]


class _ModuleView:
    """Per-file info needed to resolve called project functions."""

    def __init__(self, path: str, tree: ast.Module, sources: dict[str, str]) -> None:
        self.path = path
        self.imported: dict[str, tuple[str, str]] = {}  # local name -> (module path, name)
        by_stem: dict[str, str] = {}
        for p in sorted(sources):
            if p.endswith(".py") and not _is_test_file(p):
                by_stem.setdefault(PurePosixPath(p).stem, p)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                target = by_stem.get(node.module.split(".")[-1])
                if target is None:
                    continue
                defined = _top_level_names(sources[target])
                for alias in node.names:
                    if alias.name in defined:
                        self.imported[alias.asname or alias.name] = (target, alias.name)

    def refs_in(self, nodes: list[ast.AST]) -> list[tuple[str, str]]:
        out: set[tuple[str, str]] = set()
        for root in nodes:
            for n in ast.walk(root):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in self.imported:
                    out.add(self.imported[n.func.id])
        return sorted(out)


def _is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return name.startswith("test_") or "/tests/" in f"/{path}"


def _top_level_names(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def _decorator_text(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [ast.unparse(d) for d in node.decorator_list]


def _terms_helpers() -> tuple[Any, Any]:
    from radius_linking.domain.text import name_terms, terms  # noqa: PLC0415

    return name_terms, terms


def extract_features(
    path: str, source: str, sources: dict[str, str], symbol_ids: dict[tuple[str, str], str]
) -> list[AssertionFeatures]:
    """Hand-built stand-in for LK-04: one :class:`AssertionFeatures` per test function."""
    name_terms, terms = _terms_helpers()
    tree = ast.parse(source)
    view = _ModuleView(path, tree, sources)
    out: list[AssertionFeatures] = []

    def target_ids(nodes: list[ast.AST]) -> tuple[str, ...]:
        found = {symbol_ids.get((p, n)) for p, n in view.refs_in(nodes)}
        return tuple(sorted(s for s in found if s))

    def visit(fn: ast.FunctionDef | ast.AsyncFunctionDef, cls: str | None) -> None:
        if not fn.name.startswith("test"):
            return
        facts: list[AssertionFact] = []
        expects_exception = False
        for node in ast.walk(fn):
            if isinstance(node, ast.Assert):
                for kind, computed in classify_assert(node.test):
                    facts.append(AssertionFact(kind, node.lineno, target_ids([node.test]), computed))
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    ctx = item.context_expr
                    if _is_call_to(ctx, "pytest.raises", "self.assertRaises"):
                        expects_exception = True
                        has_match = any(k.arg == "match" for k in ctx.keywords)  # type: ignore[attr-defined]
                        kind = AssertKind.EXCEPTION_TYPE_MESSAGE if has_match else AssertKind.EXCEPTION_TYPE
                        facts.append(AssertionFact(kind, node.lineno, target_ids(list(node.body)), True))
            elif isinstance(node, ast.Call):
                attr = node.func.attr if isinstance(node.func, ast.Attribute) else ""
                if attr in _UNITTEST_KIND and _dotted(node.func).startswith("self."):
                    facts.append(AssertionFact(_UNITTEST_KIND[attr], node.lineno, target_ids([node]), True))
                elif attr.startswith("assert_called") or attr == "assert_any_call":
                    facts.append(AssertionFact(AssertKind.MOCK_CALLED, node.lineno, (), False))
        facts.sort(key=lambda f: (f.line, f.kind.value))
        decorators = _decorator_text(fn)
        param = next((d for d in fn.decorator_list if "parametrize" in ast.unparse(d)), None)
        n_cases = None
        if isinstance(param, ast.Call) and len(param.args) >= 2 and isinstance(param.args[1], (ast.List, ast.Tuple)):
            n_cases = len(param.args[1].elts)
        literal_terms: list[str] = []
        for node in ast.walk(fn):
            if isinstance(node, ast.Constant) and not isinstance(node.value, (bytes, type(None), type(...))):
                raw = node.value
                toks = terms(raw) if isinstance(raw, str) else [str(raw).lower()]
                literal_terms.extend(toks)
        refs = sorted({f"{p}::{n}" for p, n in view.refs_in([fn])})
        line_start = min([fn.lineno, *[d.lineno for d in fn.decorator_list]])
        out.append(
            AssertionFeatures(
                test_id="::".join(p for p in (path, cls, fn.name) if p),
                path=path,
                line_start=line_start,
                line_end=fn.end_lineno or fn.lineno,
                assertions=tuple(facts),
                n_assertions=len(facts),
                expects_exception=expects_exception,
                is_parametrized=param is not None,
                n_param_cases=n_cases,
                has_skip_marker=any(
                    m in d for d in decorators for m in ("mark.skip", "mark.xfail", "unittest.skip")
                ),
                name_terms=tuple(t for t in name_terms(fn.name) if t != "test"),
                literal_terms=tuple(dict.fromkeys(literal_terms)),
                called_symbol_refs=tuple(refs),
            )
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit(node, None)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit(sub, node.name)
    return out


# --- stage B outcomes -------------------------------------------------------------------


def case_inputs(outcomes: dict[str, str]) -> list[CaseOutcomeInput]:
    cases = []
    for test_id in sorted(outcomes):
        path, *rest = test_id.split("::")
        classname = ".".join([path.removesuffix(".py").replace("/", "."), *rest[:-1]])
        cases.append(
            CaseOutcomeInput(
                test_id=test_id,
                raw_file=path,
                raw_classname=classname,
                raw_name=rest[-1],
                outcome=Outcome(outcomes[test_id]),
            )
        )
    return cases


def stage_b_block(outcomes: dict[str, str]) -> dict[str, Any]:
    cases = case_inputs(outcomes)
    return {
        "cases": [c.to_dict() for c in cases],
        "uploads": 1,
        "flaky_test_ids": [],
        "flaky_scores": {},
        "results_received": True,
        "ci_failed_cases": sum(1 for c in cases if c.outcome in (Outcome.FAILED, Outcome.ERROR)),
    }


# --- tamper -----------------------------------------------------------------------------


def _tamper_dicts(report: Any) -> list[dict[str, Any]]:
    return [
        TamperFindingInput(
            finding_id=f.finding_id,
            rule_id=f.rule_id,
            check=f.check,
            severity=f.severity.label,
            confidence=f.confidence,
            path=f.path,
            symbol=f.symbol,
            test_id=f.test_id,
            reason=f.reason,
            old_snippet=f.old_snippet,
            new_snippet=f.new_snippet,
        ).to_dict()
        for f in report.findings
    ]


def run_tamper(changeset: Any, base: Any, head: Any, diff: str, *, offline_registry: bool) -> dict[str, Any]:
    if offline_registry:
        config = TamperConfig(params=Params(use_registry=True))
        registry = StaticPackageRegistry(set(OFFLINE_REGISTRY_KNOWN))
    else:
        config, registry = TamperConfig(), None
    report = analyze_tampering(changeset, base, head, config, diff_text=diff, package_registry=registry)
    return {
        "findings": _tamper_dicts(report),
        "waived": len(report.waived),
        "unanalyzable": sorted(f"{u.path}:{u.side}:{u.reason}" for u in report.unanalyzable),
        "rule_errors": list(report.rule_errors),
        "catalog_version": report.catalog_version,
    }


# --- bundle -----------------------------------------------------------------------------


def _prov(origin: str, producer: str, note: str = "") -> dict[str, str]:
    return {"origin": origin, "producer": producer, **({"note": note} if note else {})}


def build_fixture(fx: Any, committed: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the full ``inputs.json`` content of one fixture (a JSON-ready dict)."""
    from radius_analysis.symbol_changes import DictSnapshot, extract_symbol_changes  # noqa: PLC0415
    from radius_linking.domain import CriterionInput as LinkCriterion  # noqa: PLC0415
    from radius_linking.infrastructure.pipeline import changeset_ref, link_changeset  # noqa: PLC0415
    from radius_testing.linking import (  # noqa: PLC0415
        LinkTarget,
        NamingLinker,
        StaticLinker,
        combine_links,
        normalize_test_id,
    )
    from radius_testing.linking.model import is_test_path  # noqa: PLC0415

    expected = fx.expected
    ids = fixture_ids(fx.id)
    base, head, diff = fx.base, fx.head, fx.patch_text()
    changeset = extract_symbol_changes(DictSnapshot(base), DictSnapshot(head), diff)
    symbols = symbol_inputs(changeset, is_test_path)
    lookup = _symbol_lookup(symbols)
    cref = changeset_ref(changeset)

    # criteria (derived from expected.json)
    criteria = [
        CriterionInput(
            criterion_id=c["id"],
            text=c["text"],
            weight=1.0,
            testability=TESTABILITY.get(c["testability"], c["testability"]),
            lifecycle="confirmed",
        )
        for c in expected["criteria"]
    ]

    # assertion features (hand-built from the head test bodies; whole test corpus at head)
    head_py = {p: t for p, t in head.items() if p.endswith(".py")}
    features: list[AssertionFeatures] = []
    for p in sorted(head_py):
        if is_test_path(p):
            features.extend(extract_features(p, head_py[p], head_py, lookup))
    features.sort(key=lambda f: f.test_id)
    head_test_ids = {f.test_id for f in features}
    changed_tests = sorted(
        f"{s.path}::{s.qualified_name}"
        for s in changeset.symbols
        if is_test_path(s.path) and f"{s.path}::{s.qualified_name}" in head_test_ids
    )

    # --- gold links (hand-built from expected.json)
    gold_cs: list[CriterionSymbolEdgeInput] = []
    gold_st: dict[tuple[str, str], SymbolTestEdgeInput] = {}
    gold_ct: list[CriterionTestEdgeInput] = []
    for link in expected["links"]:
        sid = resolve_gold_symbol(link["symbol"], lookup)
        gold_cs.append(
            CriterionSymbolEdgeInput(
                criterion_id=link["criterion"], symbol_id=sid, score=GOLD_LINK_SCORE, rank=1,
                by_linker={"gold": GOLD_LINK_SCORE},
                reasons=(Reason("gold_label", "expected.json links[]", link["symbol"]),),
            )
        )
        for t in link["tests"]:
            tid = normalize_test_id(t)
            gold_st.setdefault((sid, tid), SymbolTestEdgeInput(sid, tid, GOLD_SYMBOL_TEST_SCORE, "gold"))
            gold_ct.append(
                CriterionTestEdgeInput(link["criterion"], tid, GOLD_CRITERION_TEST_WEIGHT, "gold_expected_json")
            )
    gold_ct = sorted(
        {(e.criterion_id, e.test_id): e for e in gold_ct}.values(), key=lambda e: (e.criterion_id, e.test_id)
    )

    # --- auto links (real LK-02 and LK-03)
    link_inputs = [LinkCriterion(c.criterion_id, c.text, None, (), (), 1.0, "confirmed") for c in criteria]
    linkset, _docs = link_changeset(
        link_inputs, changeset, DictSnapshot(head), DictSnapshot(base), snapshot_id=fx.id,
        python_sources=head_py,
    )
    auto_cs: list[CriterionSymbolEdgeInput] = []
    by_linker: dict[tuple[str, str], dict[str, float]] = {}
    for lk in linkset.by_linker:
        by_linker.setdefault((lk.criterion_id, lk.symbol_id), {})[lk.linker] = lk.score
    for lk in linkset.links:
        auto_cs.append(
            CriterionSymbolEdgeInput(
                criterion_id=lk.criterion_id, symbol_id=lk.symbol_id, score=lk.score, rank=lk.rank,
                by_linker=dict(sorted(by_linker.get((lk.criterion_id, lk.symbol_id), {}).items())),
                reasons=tuple(Reason(r.kind, f"{r.linker}: {r.detail}", None) for r in lk.evidence),
            )
        )
    auto_cs.sort(key=lambda e: (e.criterion_id, e.rank or 10**9, e.symbol_id))
    targets = [
        LinkTarget.from_changed_symbol(s)
        for s in changeset.symbols
        if not is_test_path(s.path) and s.qualified_name != "<file>" and s.language == "python"
    ]
    st_set = combine_links(StaticLinker().link(head_py, targets), NamingLinker().link(head_py, targets))
    auto_st = sorted(
        (
            SymbolTestEdgeInput(l.symbol_id, l.test_id, l.score, l.kind.value, l.depth)
            for l in st_set.links
        ),
        key=lambda e: (e.symbol_id, -e.score, e.test_id),
    )

    # --- tamper (real EV-02) or the committed section when EV-02 is not importable
    if HAVE_TAMPER:
        snap_b, snap_h = DictSnapshot(base), DictSnapshot(head)
        tamper = run_tamper(changeset, snap_b, snap_h, diff, offline_registry=True)
        tamper_plain = run_tamper(changeset, snap_b, snap_h, diff, offline_registry=False)
    elif committed is not None:
        tamper = committed["tamper"]
        tamper_plain = committed.get("tamper_variants", {}).get("no_registry", tamper)
    else:  # pragma: no cover
        raise RuntimeError("radius_analysis.tamper (EV-02) is not importable; set RADIUS_VS01_EXTRA_SRC")

    notes = sorted({*changeset.notes, *(["truncated"] if changeset.truncated else [])})
    common = {
        **ids,
        "changeset_ref": cref,
        "criteria": criteria,
        "symbols": symbols,
        "assertions": features,
        "tamper": tuple(TamperFindingInput.from_dict(d) for d in tamper["findings"]),
        "tamper_waived": tamper["waived"],
        "tamper_unanalyzable": tuple(tamper["unanalyzable"]),
        "changed_test_ids": frozenset(changed_tests),
        "agent_signal": False,
        "degraded": tuple(notes),
    }
    versions_common = {
        "symbol_changes": SYMBOL_CHANGES_VERSION if changeset.algo_version == SYMBOL_CHANGES_VERSION else changeset.algo_version,
        "assertions": ASSERTIONS_VERSION,
        "assertions_producer": HANDBUILT_ASSERTION_NOTE,
        "tamper": tamper["catalog_version"] if tamper["catalog_version"] else TAMPER_VERSION,
    }
    gold_a = StageAInput(
        **common,
        criterion_symbol=tuple(gold_cs),
        symbol_test=tuple(sorted(gold_st.values(), key=lambda e: (e.symbol_id, e.test_id))),
        criterion_test=tuple(gold_ct),
        algo_versions={**versions_common, "links": GOLD_VERSION},
    )
    auto_a = StageAInput(
        **common,
        criterion_symbol=tuple(auto_cs),
        symbol_test=tuple(auto_st),
        criterion_test=(),
        algo_versions={
            **versions_common,
            "criterion_symbol_links": linkset.algo_version or CRITERION_SYMBOL_LINKS_VERSION,
            "symbol_test_links": st_set.algo_version or SYMBOL_TEST_LINKS_VERSION,
            "criterion_test": "pending-vs04",
        },
    )

    shared_prov = {
        "ids": _prov("derived", GENERATOR, "uuid5/sha1 of the fixture name; head_sha is a PLACEHOLDER, not a git sha"),
        "criteria": _prov("derived", "expected.json criteria[]", "weight 1.0, lifecycle confirmed"),
        "symbols": _prov("real", "radius_analysis.symbol_changes.extract_symbol_changes (LK-01)", "base/head snapshots + pr.patch"),
        "assertions": _prov(
            "hand_built",
            f"{GENERATOR}: ast classifier ({HANDBUILT_ASSERTION_NOTE})",
            "LK-04 (radius_testing.assertions) emits a different record shape (AssertionRecord/TestSummary); "
            "this is a hand-built AssertionFeatures per design 3.2/3.6, one per test function at head",
        ),
        "tamper": _prov(
            "real",
            "radius_analysis.tamper.analyze_tampering (EV-02)",
            "offline StaticPackageRegistry lacking pytimeparse-ultra; default (no registry) result in tamper_variants",
        ),
        "changed_test_ids": _prov("derived", "LK-01 symbols that are test functions present at head"),
        "stage_b": _prov("hand_built", "expected.json test_outcomes", "outcomes copied per scenario"),
    }
    modes = {
        "gold": {
            "mode": "gold",
            "status": "complete",
            "provenance": {
                **shared_prov,
                "criterion_symbol": _prov("hand_built", "expected.json links[]", "score 1.0, rank 1"),
                "symbol_test": _prov("hand_built", "expected.json links[].tests", "ADDRESSED tests as EXERCISED_BY edges, score 0.9 (l_st), kind gold"),
                "criterion_test": _prov("hand_built", "expected.json links[].tests", "ADDRESSED_BY weight 1.0, method gold_expected_json"),
            },
            "stage_a": gold_a.to_dict(),
        },
        "auto": {
            "mode": "auto",
            "status": "criterion_test_pending_vs04",
            "provenance": {
                **shared_prov,
                "criterion_symbol": _prov("real", "radius_linking.infrastructure.pipeline.link_changeset (LK-02)", "combined links, no reranker"),
                "symbol_test": _prov("real", "radius_testing.linking StaticLinker + NamingLinker + combine_links (LK-03)", "head python sources; no dynamic coverage"),
                "criterion_test": _prov("hand_built", "empty", "VS-04 (test relevance) does not exist yet; VS-02 adds the real snapshot"),
            },
            "stage_a": auto_a.to_dict(),
        },
    }
    bundle: dict[str, Any] = {
        "schema": SCHEMA,
        "fixture": fx.id,
        "generated_by": GENERATOR,
        "contracts": "radius_evidence.domain.inputs (StageAInput, StageBInput)",
        "expected_verdict": expected["expected_verdict"],
        "modes": modes,
        "stage_b": {
            name: stage_b_block(expected["test_outcomes"][name])
            for name in ("base", "head", "head_with_probes")
            if name in expected["test_outcomes"]
        },
        "tamper_variants": {"no_registry": tamper_plain},
        "tamper": tamper,
    }
    # `tamper` at top level duplicates stage_a.tamper with the waived/unanalyzable/rule_errors facts
    return encode(bundle)


def render(bundle: dict[str, Any]) -> str:
    return json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def generate_all(only: list[str] | None = None, *, existing: bool = True) -> dict[str, str]:
    loader = _load_intent_loader()
    fixtures = {fx.id: fx for fx in loader.discover()}
    names = only or list(ALL_FIXTURES)
    out: dict[str, str] = {}
    for name in names:
        path = OUT_DIR / name / "inputs.json"
        committed = json.loads(path.read_text(encoding="utf-8")) if existing and path.is_file() else None
        out[name] = render(build_fixture(fixtures[name], committed))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="regenerate in memory and diff against the files")
    ap.add_argument("--fixture", action="append", help="limit to one fixture (repeatable)")
    args = ap.parse_args(argv)
    if not args.check and not HAVE_TAMPER:
        print("error: radius_analysis.tamper (EV-02) not importable; use RADIUS_VS01_EXTRA_SRC", file=sys.stderr)
        return 2
    generated = generate_all(args.fixture, existing=True)
    if not args.check:
        for name, text in generated.items():
            target = OUT_DIR / name / "inputs.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {target.relative_to(ROOT).as_posix()}")
        return 0
    if not HAVE_TAMPER:
        print("notice: EV-02 not importable here; tamper section compared against itself (skipped)")
    drift = 0
    for name, text in generated.items():
        target = OUT_DIR / name / "inputs.json"
        current = target.read_text(encoding="utf-8").replace("\r\n", "\n") if target.is_file() else ""
        if current != text:
            drift += 1
            diff = difflib.unified_diff(
                current.splitlines(), text.splitlines(), f"committed/{name}", f"generated/{name}", lineterm="", n=2
            )
            print("\n".join(list(diff)[:60]))
    if drift:
        print(f"DRIFT in {drift} fixture bundle(s); run scripts/verdict_v2_make_fixtures.py", file=sys.stderr)
        return 1
    print(f"ok: {len(generated)} bundles match the generator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
