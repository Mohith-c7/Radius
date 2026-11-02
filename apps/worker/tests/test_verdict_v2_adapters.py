"""Pure adapters of Verdict v2 Stage A (VS-05): total on malformed producer data."""

from __future__ import annotations

import math
from types import SimpleNamespace as NS

from radius_evidence.domain.enums import Outcome
from radius_evidence.domain.inputs import CriterionInput
from radius_worker.verdict_v2 import adapters


def crit(**kw):
    base = {
        "id": "C1",
        "text": "a password needs a digit",
        "state": "confirmed",
        "weight": 1.0,
        "testability": "behavioral_testable",
        "hints": NS(paths=("src/a.py",), tests=("tests/test_a.py::test_x",)),
    }
    return NS(**{**base, **kw})


def sym(**kw):
    base = {
        "symbol_id": "python:src/a.py::f#function@abc",
        "path": "src/a.py",
        "qualified_name": "f",
        "kind": "function",
        "language": "python",
        "change_kind": NS(value="modified_body"),
        "is_behavioral": True,
    }
    return NS(**{**base, **kw})


# ----------------------------------------------------------------- criteria


def test_criterion_inputs_convert_and_sort() -> None:
    out = adapters.criterion_inputs([crit(id="C2"), crit(id="C1")])
    assert [c.criterion_id for c in out.items] == ["C1", "C2"]
    first = out.items[0]
    assert first.hints_paths == ("src/a.py",)
    assert first.hints_tests == ("tests/test_a.py::test_x",)
    assert first.lifecycle == "confirmed"
    assert not out.notes


def test_criterion_inputs_drop_rejected_and_report_malformed() -> None:
    out = adapters.criterion_inputs(
        [
            crit(id="ok"),
            crit(id="gone", state=NS(value="rejected")),
            crit(id="", text="x"),
            crit(id="nan", weight=math.nan),
            crit(id="zero", weight=0),
            crit(id="boolw", weight=True),
            object(),
        ]
    )
    assert [c.criterion_id for c in out.items] == ["ok"]
    assert out.dropped["criterion_malformed"] == 2  # empty id and a plain object
    assert out.dropped["criterion_weight"] == 3
    assert "adapter_dropped:criterion_weight" in out.notes


def test_criterion_inputs_limit() -> None:
    items = [crit(id=f"C{i:02}") for i in range(5)]
    out = adapters.criterion_inputs(items, limit=3)
    assert len(out.items) == 3
    assert out.dropped["criteria_over_limit"] == 2


def test_agent_signal() -> None:
    assert adapters.agent_signal(["fix\n\nCo-Authored-By: Claude <x@y>"])
    assert not adapters.agent_signal(["plain", 3])  # type: ignore[list-item]


# ----------------------------------------------------------------- symbols


def test_symbol_inputs_flags_and_test_files() -> None:
    changeset = NS(
        symbols=(
            sym(),
            sym(
                symbol_id="python:tests/test_a.py::test_x#function@1",
                path="tests/test_a.py",
                qualified_name="TestA.test_x",
            ),
            sym(symbol_id="python:src/c.py::<module>#module@2", path="src/c.py",
                qualified_name="<module>", kind="module"),
            sym(symbol_id="", path="p"),
            NS(),
        )
    )
    out = adapters.symbol_inputs(changeset)
    by_path = {s.path: s for s in out.items}
    assert by_path["src/a.py"].is_behavioral and not by_path["src/a.py"].is_test
    assert by_path["tests/test_a.py"].is_test
    assert by_path["src/c.py"].is_pseudo
    assert out.dropped["symbol_malformed"] == 2
    assert adapters.changed_test_ids(out.items) == frozenset(
        {"tests/test_a.py::TestA::test_x"}
    )
    b = adapters.behavioral_symbols(out.items)
    assert {s.path for s in b} == {"src/a.py", "src/c.py"}


def test_unsupported_languages_marker() -> None:
    out = adapters.symbol_inputs(
        NS(symbols=(sym(language="typescript", symbol_id="ts:a.ts::g", path="a.ts"),))
    )
    assert adapters.unsupported_languages(out.items) == ("unsupported_language:typescript",)
    assert adapters.unsupported_languages(adapters.symbol_inputs(NS(symbols=(sym(),))).items) == ()


def test_changed_test_ids_skip_removed_and_non_tests() -> None:
    out = adapters.symbol_inputs(
        NS(
            symbols=(
                sym(symbol_id="a", path="tests/test_a.py", qualified_name="helper"),
                sym(symbol_id="b", path="tests/test_a.py", qualified_name="test_gone",
                    change_kind=NS(value="removed")),
                sym(symbol_id="c", path="tests/test_a.py", qualified_name="test_new[1]"),
            )
        )
    )
    assert adapters.changed_test_ids(out.items) == frozenset({"tests/test_a.py::test_new"})


# ----------------------------------------------------------------- links


def link(**kw):
    base = {
        "criterion_id": "C1",
        "symbol_id": "S1",
        "linker": "combined",
        "score": 0.8,
        "rank": 1,
        "evidence": (NS(kind="lexical", detail="shared term", linker="lexical"),),
    }
    return NS(**{**base, **kw})


def test_criterion_symbol_edges_keep_top_ranks_and_linker_scores() -> None:
    linkset = NS(
        links=(
            link(),
            link(symbol_id="S2", rank=2, score=0.5),
            link(symbol_id="S9", rank=4, score=0.9),
            link(linker="lexical"),
            link(score=math.nan),
            link(score=1.5),
            link(criterion_id="CX"),
        ),
        by_linker=(link(linker="lexical", score=0.31), link(linker="bad", score="x")),
    )
    out = adapters.criterion_symbol_edges(linkset, known_criteria=["C1"])
    assert [(e.symbol_id, e.rank) for e in out.items] == [("S1", 1), ("S2", 2)]
    assert out.items[0].by_linker == {"lexical": 0.31}
    assert out.items[0].reasons[0].code == "lexical"
    assert out.dropped["criterion_symbol_malformed"] >= 1


def test_symbol_test_edges_normalise_ids_and_keep_best() -> None:
    def st(test_id, score, kind="direct_call", depth=None):
        return NS(symbol_id="S1", test_id=test_id, score=score,
                  kind=NS(value=kind), depth=depth)

    out = adapters.symbol_test_edges(
        NS(
            links=(
                st("tests/t.py::test_a[1-2]", 0.4),
                st("tests/t.py::test_a[3]", 0.9, depth=1),
                st("", 0.9),
                st("tests/t.py::test_b", math.inf),
            )
        )
    )
    assert len(out.items) == 1
    assert out.items[0].test_id == "tests/t.py::test_a"
    assert out.items[0].score == 0.9 and out.items[0].depth == 1
    assert out.dropped["symbol_test_malformed"] == 2


def test_hint_test_edges_resolution() -> None:
    c = CriterionInput(
        "C1", "t", 1.0, "behavioral_testable", "confirmed",
        hints_tests=("tests/t.py::test_a", "tests/t.py", "t.py::test_c", "tests/t.py::nope"),
    )
    known = ["tests/t.py::test_a", "tests/t.py::test_b", "tests/u.py::Cls::test_c"]
    out = adapters.hint_test_edges([c], known)
    ids = {e.test_id for e in out.items}
    assert ids == {"tests/t.py::test_a", "tests/t.py::test_b"}
    assert all(e.method == "intent_yml_hint" and e.weight == 1.0 for e in out.items)
    assert out.dropped["hint_unresolved"] == 2


def test_relevance_edges_validate_and_filter() -> None:
    raw = [
        {"criterion_id": "C1", "test_id": "tests/t.py::test_a[1]", "weight": 0.4},
        NS(criterion_id="C1", test_id="tests/t.py::test_a", weight=0.7, method="m", bm25_raw=1.2),
        {"criterion_id": "C1", "test_id": "t", "weight": 0.0},
        {"criterion_id": "C1", "test_id": "t", "weight": "x"},
        {"criterion_id": "CZ", "test_id": "t", "weight": 0.5},
    ]
    out = adapters.relevance_edges(raw, known_criteria=["C1"])
    assert [(e.test_id, e.weight, e.method) for e in out.items] == [
        ("tests/t.py::test_a", 0.7, "m")
    ]
    assert out.dropped["relevance_malformed"] == 2


def test_merge_criterion_test_edges_prefers_higher_weight_then_hint() -> None:
    from radius_evidence.domain.inputs import CriterionTestEdgeInput as E

    merged = adapters.merge_criterion_test_edges(
        [E("C1", "t", 1.0, "intent_yml_hint")],
        [E("C1", "t", 0.4, "rel"), E("C1", "u", 0.4, "rel")],
    )
    assert [(e.test_id, e.weight, e.method) for e in merged] == [
        ("t", 1.0, "intent_yml_hint"),
        ("u", 0.4, "rel"),
    ]
    tie = adapters.merge_criterion_test_edges(
        [E("C1", "t", 0.5, "rel")], [E("C1", "t", 0.5, "intent_yml_hint")]
    )
    assert tie[0].method == "intent_yml_hint"


def test_short_symbol_id() -> None:
    f = adapters.short_symbol_id
    assert f("python:src/a.py::Cls.m#method@abc") == "src/a.py::Cls.m"
    assert f("src/a.py::g") == "src/a.py::g"


# ----------------------------------------------------------------- assertions


def _record(kind="equality", **kw):
    rec = {
        "test_id": "tests/t.py::test_a",
        "kind": kind,
        "expected": {"form": "literal", "literal_kind": "bool", "text": "True"},
        "location": {"line": 3, "path": "tests/t.py"},
        "strength_features": {},
        "subject": {"text": "f()", "refs": []},
    }
    rec.update(kw)
    return rec


def test_assertion_features_relabels_exact_bool_identity_only() -> None:
    data = {
        "assertions": [
            _record("identity"),
            _record("identity", test_id="tests/t.py::test_neg",
                    strength_features={"negated": True}),
            _record("identity", test_id="tests/t.py::test_none",
                    expected={"form": "literal", "literal_kind": "none", "text": "None"}),
        ],
        "tests": [],
    }
    out = adapters.assertion_features(data)
    kinds = {f.test_id: f.assertions[0].kind.value for f in out.items}
    assert kinds["tests/t.py::test_a"] == "value_equality"
    assert kinds["tests/t.py::test_neg"] == "truthiness"
    assert kinds["tests/t.py::test_none"] == "truthiness"
    assert data["assertions"][0]["kind"] == "identity"  # input untouched


def test_assertion_features_accept_objects_and_report_garbage() -> None:
    class AS:
        def to_dict(self):
            return {"assertions": [_record(), {"test_id": 3}, "junk"], "tests": []}

    out = adapters.assertion_features(AS())
    assert len(out.items) == 1
    assert out.dropped
    assert adapters.assertion_features("nonsense").dropped == {"assertion_set_malformed": 1}
    assert adapters.assertion_features({"assertions": "no"}).items == ()


# ----------------------------------------------------------------- tamper


def test_tamper_inputs_unwaived_findings_only() -> None:
    finding = NS(
        to_dict=lambda: {
            "finding_id": "tf_1", "rule_id": "T001", "check": "x",
            "severity": "high", "confidence": 0.9, "path": "tests/t.py",
            "reason": "r", "symbol": None, "test_id": None,
        }
    )
    bad = NS(to_dict=lambda: {"rule_id": "T002"})
    report = NS(
        findings=(finding, bad),
        waived=(object(), object()),
        unanalyzable=(NS(path="b.py"), NS(path="a.py")),
        truncated=True,
        rule_errors=("boom",),
    )
    out = adapters.tamper_inputs(report)
    assert [f.finding_id for f in out.findings] == ["tf_1"]
    assert out.waived == 2 and out.unanalyzable == ("a.py", "b.py")
    assert out.truncated and out.rule_errors == ("boom",)
    assert out.dropped == {"tamper_finding_malformed": 1}


# ----------------------------------------------------------------- outcomes


def test_case_inputs_map_outcomes_and_drop_unknown() -> None:
    cases = [
        NS(file="tests/t.py", classname=None, name="test_a", outcome="passed"),
        NS(file=None, classname="C", name="test_b", outcome=NS(value="failed")),
        NS(file="tests/t.py", classname=None, name="test_c", outcome="weird"),
    ]
    out = adapters.case_inputs(cases)
    assert [c.outcome for c in out.items] == [Outcome.PASSED, Outcome.FAILED]
    assert out.dropped == {"case_outcome_unknown": 1}
    assert adapters.failed_case_count(out.items) == 1


def test_flaky_test_ids_match_path_and_name() -> None:
    known = ["tests/test_a.py::test_x", "tests/test_a.py::Cls::test_y", "tests/other.py::test_x"]
    got = adapters.flaky_test_ids(
        ["tests/test_a.py::test_x", "test_a.py::test_y[3]", "noise", 7], known
    )
    assert got == frozenset({"tests/test_a.py::test_x", "tests/test_a.py::Cls::test_y"})


def test_build_test_docs_from_sources_and_records() -> None:
    src = '''
import pytest

@pytest.mark.parametrize("v", ["a"])
def test_one(v):
    """doc text"""
    assert f(v) == "x"

class TestK:
    def test_two(self):
        assert True

def helper():
    pass
'''
    docs = adapters.build_test_docs(
        {"tests/t.py": src, "tests/bad.py": "def ("},
        ["tests/t.py::test_one", "tests/t.py::TestK::test_two", "tests/bad.py::test_z",
         "tests/missing.py::test_q"],
        {"assertions": [
            {"test_id": "tests/t.py::test_one", "kind": "equality",
             "subject": {"text": "f(v)", "refs": [{"name": "f"}]},
             "expected": {"text": "'x'"}},
            {"test_id": 5},
        ]},
    )
    by_id = {d.test_id: d for d in docs}
    assert set(by_id) == {"tests/t.py::test_one", "tests/t.py::TestK::test_two"}
    one = by_id["tests/t.py::test_one"]
    assert one.docstring == "doc text" and "a" in one.param_ids
    assert one.assertions and one.assertions[0].symbol_names == ("f",)
