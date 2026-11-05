# ruff: noqa: E402, I001  (helper import needs the sys.path setup below; no conftest to avoid plugin-name clashes)
"""Symbol documents (LK-01 integration), call-graph neighbours, pipeline and evaluation hooks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sys as _sys
from pathlib import Path as _Path

_HERE = str(_Path(__file__).parent)
if _HERE not in _sys.path:  # helper module lives next to the tests (importlib mode)
    _sys.path.insert(0, _HERE)

from linking_helpers import crit, sym
from radius_analysis.symbol_changes import DictSnapshot, extract_symbol_changes
from radius_analysis.symbol_changes.testing import dedent, make_diff
from radius_linking.application import (
    ablation,
    evaluate_linkset,
    evaluate_rankings,
    gold_from_expected,
    link_criteria,
    links_as_expected,
    rankings_from_linkset,
)
from radius_linking.domain import CriterionInput, Link, LinkSet, Reason
from radius_linking.infrastructure.linkers import ChangePriorLinker, default_linkers
from radius_linking.infrastructure.neighbors import CallGraphNeighbors
from radius_linking.infrastructure.pipeline import (
    changeset_ref,
    criteria_inputs,
    criterion_input,
    link_changeset,
)
from radius_linking.infrastructure.symbol_docs import build_symbol_docs

BASE = {
    "src/pricing.py": dedent("""
        def line_total(unit_price, quantity):
            return round(unit_price * quantity, 2)
        """),
    "src/cart.py": dedent("""
        class Cart:
            def total(self):
                return 0
        """),
}
HEAD = {
    "src/pricing.py": dedent('''
        def line_total(unit_price, quantity):
            return round(unit_price * quantity, 2)


        @app.route("/api/discount")
        def apply_discount(price, percent):
            """Reduce price by percent."""
            # reject nonsense early
            if percent < 0 or percent > 100:
                raise ValueError("percent must be between 0 and 100")
            return round(price * (1 - percent / 100), 2)
        '''),
    "src/cart.py": dedent("""
        class Cart:
            def total(self):
                return 1
        """),
    "web/format.ts": dedent("""
        /** Format a price label. */
        export function priceLabel(p: number): string {
          // two decimals
          return "$" + p.toFixed(2);
        }
        """),
}


def changes():
    diff = make_diff(BASE, HEAD)
    cs = extract_symbol_changes(DictSnapshot(BASE), DictSnapshot(HEAD), diff)
    return cs, DictSnapshot(HEAD), DictSnapshot(BASE)


def docs_by_name():
    cs, head, base = changes()
    return {d.qualified_name: d for d in build_symbol_docs(cs, head, base)}


def test_python_symbol_document_fields():
    d = docs_by_name()["apply_discount"]
    assert d.docstring == "Reduce price by percent."
    assert {"percent", "price", "ValueError", "round"} <= set(d.identifiers)
    assert "percent must be between 0 and 100" in d.literals
    assert "100" in d.literals and "2" in d.literals
    assert any("reject nonsense" in c for c in d.comments)
    assert any("/api/discount" in dec for dec in d.decorators)
    assert d.change_kind == "added" and d.is_behavioral and not d.is_test


def test_class_document_excludes_nested_method_bodies():
    docs = docs_by_name()
    assert "Cart.total" in docs
    assert "Cart" not in docs or "total" not in docs["Cart"].identifiers


def test_typescript_document_via_regex_path():
    d = docs_by_name()["priceLabel"]
    assert d.language == "typescript" or d.language
    assert d.docstring.startswith("Format a price label")
    assert any("two decimals" in c for c in d.comments)
    assert "$" in d.literals and "2" in d.literals


def test_missing_file_degrades_to_name_only_document():
    cs, _head, base = changes()
    empty = DictSnapshot({})
    docs = build_symbol_docs(cs, empty, empty)
    assert len(docs) == len(cs.symbols)
    assert all(d.identifiers == () for d in docs)


def test_unparsable_python_falls_back_to_regex():
    head = {"src/pricing.py": "def broken(:\n    return 'x'  # note\n"}
    cs = extract_symbol_changes(
        DictSnapshot({}), DictSnapshot(head), make_diff({}, head)
    )
    docs = build_symbol_docs(cs, DictSnapshot(head))
    assert docs  # never raises


def test_removed_symbol_is_read_from_base():
    base = {"src/a.py": "def gone():\n    return 'bye'\n"}
    head = {"src/a.py": "x = 1\n"}
    cs = extract_symbol_changes(
        DictSnapshot(base), DictSnapshot(head), make_diff(base, head)
    )
    doc = next(
        d
        for d in build_symbol_docs(cs, DictSnapshot(head), DictSnapshot(base))
        if d.qualified_name == "gone"
    )
    assert doc.change_kind == "removed" and "bye" in doc.literals


def test_test_files_are_flagged():
    base = {}
    head = {"tests/test_a.py": "def test_x():\n    assert 1\n"}
    cs = extract_symbol_changes(
        DictSnapshot(base), DictSnapshot(head), make_diff(base, head)
    )
    assert all(d.is_test for d in build_symbol_docs(cs, DictSnapshot(head)))


# ------------------------------------------------------------------ pipeline


def test_link_changeset_end_to_end_with_hash_stable_ref():
    cs, head, base = changes()
    c = [
        crit("apply_discount rejects a percent outside 0..100 with ValueError", "C1"),
        crit("the price label shows two decimals", "C2"),
    ]
    ls, docs = link_changeset(c, cs, head, base, snapshot_id="s1", python_sources=HEAD)
    assert ls.ranking("C1")[0].endswith(
        "apply_discount#function@" + ls.ranking("C1")[0].split("@")[1]
    )
    names = {d.symbol_id: d.qualified_name for d in docs}
    assert names[ls.ranking("C1")[0]] == "apply_discount"
    assert names[ls.ranking("C2")[0]] == "priceLabel"
    assert ls.changeset_ref == changeset_ref(cs) and ls.snapshot_id == "s1"
    again, _ = link_changeset(c, cs, head, base, snapshot_id="s1", python_sources=HEAD)
    assert again.to_json() == ls.to_json()


def test_criterion_adapter_uses_hints_rationale_and_states():
    from datetime import UTC, datetime

    from radius_intent.domain import Criterion as IntentCriterion
    from radius_intent.domain import (
        CriterionHints,
        ExtractionMethod,
        IntentSource,
        IntentSourceKind,
        Span,
    )

    text = "apply_discount must reject percent above 100"
    src = IntentSource.from_text(
        "s1", IntentSourceKind.PR_BODY, text, datetime(2026, 1, 1, tzinfo=UTC)
    )
    hints = CriterionHints(
        paths=("src/pricing.py",), tests=("tests/test_pricing.py::test_x",)
    )
    c = IntentCriterion.create(
        src,
        Span("s1", 0, len(text)),
        extraction_method=ExtractionMethod.DETERMINISTIC,
        extractor_version="t",
        hints=hints,
    )
    ci = criterion_input(c)
    assert ci.paths == ("src/pricing.py",) and ci.tests == (
        "tests/test_pricing.py::test_x",
    )
    assert ci.criterion_id == c.id and ci.state == "proposed"
    assert criteria_inputs([c]) == [ci]
    assert (
        criteria_inputs(
            [
                c.transition_to(
                    __import__(
                        "radius_intent.domain", fromlist=["CriterionState"]
                    ).CriterionState.REJECTED
                )
            ]
        )
        == []
    )


def test_call_graph_neighbors_find_callers_and_callees():
    sources = {
        "src/a.py": "def core():\n    return 1\n",
        "src/b.py": "from a import core\n\ndef caller():\n    return core()\n",
        "src/c.py": "from b import caller\n\ndef outer():\n    return caller()\n",
    }
    refs = ["src/a.py::core", "src/b.py::caller", "src/c.py::outer"]
    g = CallGraphNeighbors(sources, refs)
    n = g.neighbors("src/a.py::core")
    assert n["src/b.py::caller"] == 1 and n["src/c.py::outer"] == 2
    callee_side = g.neighbors("src/c.py::outer")
    assert callee_side["src/b.py::caller"] == 1 and callee_side["src/a.py::core"] == 2
    assert g.neighbors("src/nope.py::x") == {}


def test_call_graph_ignores_non_python_and_bad_sources():
    g = CallGraphNeighbors(
        {"x.ts": "export const a = 1", "bad.py": "def (:"}, ["x.ts::a"]
    )
    assert g.neighbors("x.ts::a") == {}
    assert g.neighbors("bad.py::f") == {}


def test_structural_uses_call_graph_end_to_end():
    sources = {
        "src/a.py": "def core():\n    return 1\n",
        "lib/b.py": "from a import core\n\ndef caller():\n    return core()\n",
    }
    a = sym("src/a.py", "core")
    b = sym("lib/b.py", "caller")
    ls = link_criteria(
        [crit("x", paths=("src/a.py::core",))],
        [a, b],
        linkers=default_linkers(),
        prior=ChangePriorLinker(),
        neighbors=CallGraphNeighbors(sources, [a.ref, b.ref]),
    )
    got = {x.symbol_id: x for x in ls.by_linker if x.linker == "structural"}
    assert any(e.kind == "call_graph" for e in got[b.symbol_id].evidence)


# ------------------------------------------------------------------ evaluation


def test_evaluate_rankings_top1_top3_mrr_by_hand():
    gold = {"C1": {"a"}, "C2": {"b"}, "C3": {"c"}, "C4": {"d"}, "C5": set()}
    rankings = {
        "C1": ["a", "x"],  # rank 1
        "C2": ["x", "y", "b"],  # rank 3
        "C3": ["x", "y", "z", "c"],  # rank 4
        # C4 has no prediction at all
    }
    m = evaluate_rankings(rankings, gold)
    assert m.n == 4  # C5 has no gold and is skipped
    assert m.top1 == pytest.approx(1 / 4)
    assert m.top3 == pytest.approx(2 / 4)
    assert m.mrr == pytest.approx((1 + 1 / 3 + 1 / 4 + 0) / 4)
    assert m.to_dict() == {"n": 4, "top1": 0.25, "top3": 0.5, "mrr": 0.3958}


def test_evaluate_rankings_empty_gold():
    assert evaluate_rankings({"C1": ["a"]}, {}).n == 0


def test_any_gold_symbol_counts_and_first_hit_is_used():
    m = evaluate_rankings({"C1": ["x", "g2", "g1"]}, {"C1": {"g1", "g2"}})
    assert m.mrr == pytest.approx(0.5) and m.top3 == 1.0 and m.top1 == 0.0


def test_gold_from_expected_reads_fixture_schema():
    exp = {
        "links": [
            {"criterion": "C1", "symbol": "a::f", "tests": []},
            {"criterion": "C1", "symbol": "a::g"},
            {"criterion": "C2", "symbol": "a::f"},
        ]
    }
    assert gold_from_expected(exp) == {
        "C1": frozenset({"a::f", "a::g"}),
        "C2": frozenset({"a::f"}),
    }


def test_evaluate_linkset_and_ablation_on_synthetic_corpus():
    a = sym("src/pricing.py", "apply_discount", docstring="Reduce price by percent")
    b = sym("src/emails.py", "normalize_email", docstring="Lowercase email")
    criteria = [
        crit("apply_discount reduces the price by percent", "C1"),
        crit("normalize_email lowercases an email address", "C2"),
    ]
    gold = {"C1": {a.ref}, "C2": {b.ref}}
    linkers = {x.name: x for x in default_linkers()}

    def run(enabled):
        return link_criteria(
            criteria,
            [a, b],
            linkers=[linkers[n] for n in sorted(enabled)],
            prior=ChangePriorLinker(),
        )

    ls = run(frozenset(linkers))
    per = evaluate_linkset(ls, [a, b], gold, linker_names=("explicit",))
    assert per["combined"].top1 == 1.0 and per["lexical"].mrr == 1.0
    assert (
        per["explicit"].n == 2 and per["explicit"].top1 == 0.0
    )  # silent linker reports zeros
    abl = ablation(run, sorted(linkers), [a, b], gold)
    assert abl["all"].top1 == 1.0
    assert {"without:lexical", "only:identifier", "without:explicit"} <= set(abl)
    assert abl["only:explicit"].top1 == 0.0


def test_rankings_use_label_mapping_and_expected_style_output():
    a = sym("src/pricing.py", "apply_discount")
    ls = link_criteria(
        [crit("apply_discount", "hash123")],
        [a],
        linkers=default_linkers(),
        prior=ChangePriorLinker(),
    )
    assert rankings_from_linkset(ls, [a], label_of={"hash123": "C1"}) == {"C1": [a.ref]}
    out = links_as_expected(ls, [a], label_of={"hash123": "C1"}, k=1)
    assert (
        out[0]["criterion"] == "C1"
        and out[0]["symbol"] == a.ref
        and out[0]["rank"] == 1
    )


def test_model_validation_and_roundtrip():
    with pytest.raises(ValueError):
        Reason("l", "k", "d", 1.5)
    with pytest.raises(ValueError):
        Link("c", "s", "l", float("nan"))
    with pytest.raises(ValueError):
        Link("c", "s", "l", 0.5, rank=-1)
    link = Link("c", "s", "l", 0.123456789, (Reason("l", "k", "d", 0.5),), rank=2)
    assert Link.from_dict(json.loads(json.dumps(link.to_dict()))) == link
    ls = LinkSet("snap", "cs", links=(link,), algo_versions={"b": "2", "a": "1"})
    assert list(json.loads(ls.to_json())["algo_versions"]) == ["a", "b"]
    assert ls.top("c", 1) == (link,) and ls.top("other", 1) == ()
    assert LinkSet.from_dict(ls.to_dict()) == ls


def test_criterion_input_full_text_includes_rationale():
    assert CriterionInput("c", "a", "b").full_text == "a\nb"
    assert CriterionInput("c", "a").full_text == "a"


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[3] / "benchmarks" / "fixtures" / "intent"
)


@pytest.mark.skipif(not FIXTURE_ROOT.is_dir(), reason="F-14 fixtures not present")
def test_f14_fixture_sanity_every_linkable_criterion_is_hit_in_top3():
    """Fixture sanity, not a research result: tiny hand-written PRs."""

    hits = total = 0
    for fx in sorted(
        p for p in FIXTURE_ROOT.iterdir() if (p / "expected.json").is_file()
    ):
        expected = json.loads((fx / "expected.json").read_text(encoding="utf-8"))
        base = {
            str(p.relative_to(fx / "base")).replace("\\", "/"): p.read_text(
                encoding="utf-8"
            )
            for p in (fx / "base").rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        }
        head = {
            str(p.relative_to(fx / "head")).replace("\\", "/"): p.read_text(
                encoding="utf-8"
            )
            for p in (fx / "head").rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        }
        cs = extract_symbol_changes(
            DictSnapshot(base), DictSnapshot(head), make_diff(base, head)
        )
        criteria = [CriterionInput(c["id"], c["text"]) for c in expected["criteria"]]
        ls, docs = link_changeset(
            criteria, cs, DictSnapshot(head), DictSnapshot(base), python_sources=head
        )
        metrics = evaluate_rankings(
            rankings_from_linkset(ls, docs), gold_from_expected(expected)
        )
        hits += round(metrics.top3 * metrics.n)
        total += metrics.n
    assert total >= 18
    assert hits / total >= 0.85


def test_python_async_function_class_bases_and_annotations():
    head = {"src/m.py": dedent("""
            class Repo(BaseRepo):
                \"\"\"Stores things.\"\"\"
                table = "things"

                def get(self):
                    return 1


            async def fetch(url: UrlType, *args, retries: int = 3, **kw) -> Result:
                return await client.get(url)
            """)}
    cs = extract_symbol_changes(
        DictSnapshot({}), DictSnapshot(head), make_diff({}, head)
    )
    docs = {d.qualified_name: d for d in build_symbol_docs(cs, DictSnapshot(head))}
    assert docs["Repo"].docstring == "Stores things."
    assert {"BaseRepo", "table"} <= set(docs["Repo"].identifiers) and "things" in docs[
        "Repo"
    ].literals
    assert {"UrlType", "Result", "retries", "args", "kw", "client"} <= set(
        docs["fetch"].identifiers
    )
