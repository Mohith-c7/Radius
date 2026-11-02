"""Author-controlled evidence (contract 3): provenance tags, the hint cap, base-spec trust.

The PR author writes the description, may add ``.radius/intent.yml`` with ``tests:`` hints
(which saturate the criterion->test link) and the tests those hints point at. Hints that
only the author vouches for are capped at ``LinkMapping.author_hint_cap``; hints from the
base branch or from a human-confirmed criterion are not.

Gold-mode semantics (DEC-030): the fixture harness feeds the expected links as hints on
``confirmed`` criteria, i.e. ``human_confirmed``, so the 8 gold results stay as designed.
The ``author_head_spec`` variant below shows the cap in action.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from radius_evidence.domain.config import LinkMapping, VerdictV2Config
from radius_evidence.domain.enums import (
    ALL_PROVENANCE,
    TRUSTED_HINT_PROVENANCE,
)
from radius_evidence.domain.inputs import (
    CriterionInput,
    CriterionTestEdgeInput,
    StageAInput,
)
from radius_evidence.domain.versions import CONTRACT_VERSION
from radius_shared.verdict_v2_payload import CONTRACT_VERSION as SHARED_CONTRACT_VERSION
from radius_worker.verdict_v2 import adapters
from radius_worker.verdict_v2.collect import (
    VerdictStageACollector,
    default_spec_provenance,
)
from radius_worker.verdict_v2.scoring import HINT_METHOD, apply_author_hint_cap
from radius_worker.verdict_v2.sources import IntentFacts, StaticIntent

ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "docs" / "research" / "design").is_dir()
)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "verdict_v2_run_author_trust", ROOT / "scripts" / "verdict_v2_run.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUN = _load_script()
DIRS = {p.name: p for p in RUN.fixture_dirs([])}
F01 = "01_correct_strong_tests"
F08 = "08_multi_criterion_partial_evidence"


def _origin(kind: str, method: str = "deterministic"):
    return NS(source=NS(kind=NS(value=kind)), extraction_method=NS(value=method))


def crit(**kw):
    base = {
        "id": "C1",
        "text": "a password needs a digit",
        "state": NS(value="proposed"),
        "weight": 1.0,
        "testability": "behavioral_testable",
        "hints": NS(paths=("src/a.py",), tests=("tests/test_a.py::test_x",)),
        "origin": _origin("spec_file"),
    }
    return NS(**{**base, **kw})


# ------------------------------------------------------------------ provenance mapping


def test_the_five_provenance_tags_and_the_trusted_subset() -> None:
    assert ALL_PROVENANCE == {
        "author_pr_body", "author_head_spec", "base_spec", "human_confirmed", "llm_proposed",
    }
    assert TRUSTED_HINT_PROVENANCE == {"base_spec", "human_confirmed"}


@pytest.mark.parametrize(
    ("kwargs", "spec", "expected"),
    [
        # spec file criterion, nobody confirmed it: provenance follows the spec file
        ({}, "author_head_spec", ("author_head_spec", "author_head_spec")),
        ({}, "base_spec", ("base_spec", "base_spec")),
        # a human confirmed or edited it (authenticated intent API): both are human_confirmed
        ({"state": NS(value="confirmed")}, "author_head_spec", ("human_confirmed", "human_confirmed")),
        ({"state": NS(value="edited")}, "author_head_spec", ("human_confirmed", "human_confirmed")),
        # PR description / title / commits / issues: the author may control it
        ({"origin": _origin("pr_body")}, "base_spec", ("author_pr_body", "author_pr_body")),
        ({"origin": _origin("issue")}, "base_spec", ("author_pr_body", "author_pr_body")),
        # LLM proposals stay llm_proposed (hints still follow the spec file / body)
        ({"origin": _origin("pr_body", "llm")}, "base_spec", ("llm_proposed", "author_pr_body")),
        # a look-alike without origin (fakes): author-controlled
        ({"origin": None}, "base_spec", ("author_pr_body", "author_pr_body")),
        # an explicit tag wins; unknown tags are ignored
        ({"hints_provenance": "base_spec"}, "author_head_spec", ("author_head_spec", "base_spec")),
        ({"provenance": "nonsense"}, "author_head_spec", ("author_head_spec", "author_head_spec")),
    ],
)
def test_criterion_provenance_mapping(kwargs, spec, expected) -> None:
    c = crit(**kwargs)
    life = getattr(getattr(c, "state", None), "value", "proposed")
    assert adapters.criterion_provenance(c, life, spec_provenance=spec) == expected


def test_criterion_inputs_carry_the_provenance_and_hint_edges_inherit_it() -> None:
    out = adapters.criterion_inputs([crit()], spec_provenance="author_head_spec")
    item = out.items[0]
    assert (item.provenance, item.hints_provenance) == ("author_head_spec", "author_head_spec")
    edges = adapters.hint_test_edges(out.items, ["tests/test_a.py::test_x"])
    assert [e.provenance for e in edges.items] == ["author_head_spec"]
    assert edges.items[0].method == HINT_METHOD


def test_provenance_survives_the_stage_a_json_round_trip() -> None:
    sa = StageAInput(
        analysis_id="a",
        repository_id="r",
        head_sha="0" * 40,
        changeset_ref="x",
        symbols=(), criterion_symbol=(), symbol_test=(), assertions=(), tamper=(),
        criteria=(
            CriterionInput("C1", "t", 1.0, "behavioral_testable", "proposed",
                           provenance="author_head_spec", hints_provenance="base_spec"),
        ),
        criterion_test=(
            CriterionTestEdgeInput("C1", "t.py::t", 1.0, HINT_METHOD, provenance="base_spec"),
        ),
    )
    back = StageAInput.from_dict(sa.to_dict())
    assert back == sa
    # a pre-contract-4 stored bundle (no tags) still loads, as author-controlled
    legacy = sa.to_dict()
    for c in legacy["criteria"]:
        c.pop("provenance"), c.pop("hints_provenance")
    for e in legacy["criterion_test"]:
        e.pop("provenance")
    old = StageAInput.from_dict(legacy)
    assert old.criteria[0].provenance == "author_pr_body"
    assert old.criterion_test[0].provenance == ""


def test_contract_version_is_three_and_shared_agrees() -> None:
    assert CONTRACT_VERSION == SHARED_CONTRACT_VERSION == "verdict-v2-contract-4"


# ----------------------------------------------------------------------- the cap


def _stage_a_with(*edges: CriterionTestEdgeInput) -> StageAInput:
    return StageAInput(
        analysis_id="a", repository_id="r", head_sha="0" * 40, changeset_ref="x",
        criteria=(), symbols=(), criterion_symbol=(), symbol_test=(),
        criterion_test=tuple(edges), assertions=(), tamper=(),
    )


@pytest.mark.parametrize(
    ("provenance", "capped"),
    [
        ("author_head_spec", True),
        ("author_pr_body", True),
        ("llm_proposed", True),
        ("", True),
        ("base_spec", False),
        ("human_confirmed", False),
    ],
)
def test_only_author_controlled_hint_edges_are_capped(provenance, capped) -> None:
    edge = CriterionTestEdgeInput("C1", "t.py::t", 1.0, HINT_METHOD, provenance=provenance)
    edges, pairs = apply_author_hint_cap(_stage_a_with(edge), 0.7)
    assert edges[0].weight == (0.7 if capped else 1.0)
    assert (pairs == {("C1", "t.py::t")}) is capped


def test_the_cap_never_raises_a_weight_and_ignores_relevance_edges() -> None:
    low = CriterionTestEdgeInput("C1", "t.py::a", 0.4, HINT_METHOD, provenance="author_head_spec")
    rel = CriterionTestEdgeInput("C1", "t.py::b", 0.95, "lexical_test_relevance")
    edges, pairs = apply_author_hint_cap(_stage_a_with(low, rel), 0.7)
    assert [e.weight for e in edges] == [0.4, 0.95]
    assert pairs == {("C1", "t.py::a")}  # still reliant on an author hint, just not reduced


def test_merge_ranks_an_author_hint_at_its_capped_weight() -> None:
    hint = CriterionTestEdgeInput("C1", "t.py::t", 1.0, HINT_METHOD, provenance="author_head_spec")
    rel = CriterionTestEdgeInput("C1", "t.py::t", 0.9, "lexical_test_relevance")
    # the better relevance edge is not displaced by a hint that will be capped to 0.7
    assert adapters.merge_criterion_test_edges([hint], [rel])[0].method == "lexical_test_relevance"
    trusted = CriterionTestEdgeInput("C1", "t.py::t", 1.0, HINT_METHOD, provenance="base_spec")
    assert adapters.merge_criterion_test_edges([trusted], [rel])[0].method == HINT_METHOD
    weak_rel = CriterionTestEdgeInput("C1", "t.py::t", 0.5, "lexical_test_relevance")
    assert adapters.merge_criterion_test_edges([hint], [weak_rel])[0].method == HINT_METHOD


def test_default_cap_is_a_configurable_part_of_the_config_digest() -> None:
    assert LinkMapping().author_hint_cap == 0.7
    other = VerdictV2Config(link=LinkMapping(author_hint_cap=0.5))
    assert other.digest() != VerdictV2Config().digest()


# --------------------------------------------- the cap in the real pipeline (fixtures)


def _by_id(payload):
    return {c["criterion_id"]: c for c in payload["criteria"]}


def test_gold_mode_hints_count_as_human_confirmed_and_are_not_capped() -> None:
    payload = RUN.run_collect(DIRS[F01], "gold", "static")
    crit_by_id = _by_id(payload)
    assert payload["verdict"] == "verified"
    assert {c["provenance"] for c in crit_by_id.values()} == {"human_confirmed"}
    for c in crit_by_id.values():
        assert all(h["provenance"] == "human_confirmed" for h in c["hints"])
        assert "author_supplied_hint" not in c["flags"]
    assert payload["summary"]["author_hint_criteria"] == 0


@pytest.mark.parametrize("trusted", ["base_spec", "human_confirmed"])
def test_trusted_hint_provenance_gives_the_gold_numbers(trusted) -> None:
    gold = RUN.run_collect(DIRS[F01], "gold", "static")
    again = RUN.run_collect(DIRS[F01], "gold", "static", trusted)
    assert [(c["criterion_id"], c["state"], c["S"]) for c in again["criteria"]] == [
        (c["criterion_id"], c["state"], c["S"]) for c in gold["criteria"]
    ]


def test_author_head_spec_hints_lower_support_and_change_the_state_of_fixture_01() -> None:
    gold = _by_id(RUN.run_collect(DIRS[F01], "gold", "static"))
    capped_payload = RUN.run_collect(DIRS[F01], "gold", "static", "author_head_spec")
    capped = _by_id(capped_payload)
    # same code, same tests, same hint text: only the provenance of the hint changed
    assert gold["C2"]["state"] == "proven" and capped["C2"]["state"] == "weak"
    for cid in gold:
        assert capped[cid]["S"] < gold[cid]["S"]
        assert "author_supplied_hint" in capped[cid]["flags"]
        reason = next(r for r in capped[cid]["reasons"] if r["code"] == "author_supplied_hint")
        assert "capped at 0.7" in reason["detail"]
    # the PR verdict moves from `verified` to a cautious one: the author's own hint is not enough
    assert capped_payload["verdict"] == "insufficient_evidence"
    assert capped_payload["justification"]["decided_by"] == "R2b"
    assert capped_payload["summary"]["author_hint_criteria"] == 2
    assert "2 criteria rely on author-supplied test hints" in capped_payload["presentation"]["summary_text"]
    assert {h["provenance"] for c in capped.values() for h in c["hints"]} == {"author_head_spec"}


def test_the_cap_value_is_configurable_and_a_cap_of_one_restores_gold() -> None:
    from radius_worker.verdict_v2.scoring import ScoringPipeline, build_stage_b

    sa = RUN.collect_stage_a(DIRS[F01], "gold", "static", "author_head_spec")
    cases = RUN.cases_for(
        __import__("json").loads((DIRS[F01] / "expected.json").read_text(encoding="utf-8"))
    )
    stage_b = build_stage_b(sa, cases=RUN.adapters.case_inputs(cases).items, uploads=1)
    loose = VerdictV2Config(link=LinkMapping(author_hint_cap=1.0))
    scored = ScoringPipeline(config=loose, mode="shadow", clock=RUN._fixed_clock).score_full(stage_b)
    assert scored.payload["verdict"] == "verified"
    # still flagged: the criterion relies on an author-supplied hint even when the cap is 1.0
    assert scored.payload["summary"]["author_hint_criteria"] == 2


def test_auto_mode_has_no_hints_so_nothing_is_capped() -> None:
    payload = RUN.run_collect(DIRS[F08], "auto", "static")
    assert payload["summary"]["author_hint_criteria"] == 0
    assert all(not c["hints"] for c in payload["criteria"])
    assert all("author_supplied_hint" not in c["flags"] for c in payload["criteria"])


def test_every_payload_says_alpha_uncalibrated_static() -> None:
    payload = RUN.run_collect(DIRS[F08], "gold", "static")
    assert payload["alpha"] is True and payload["calibrated"] is False
    assert payload["evidence_basis"] == "static_only"
    assert payload["contract_version"] == CONTRACT_VERSION
    pres = payload["presentation"]
    assert pres["state_labels"]["proven"] == "SUPPORTED"
    assert "not a proof of correctness" in pres["legend"]
    assert "uncalibrated" in pres["disclaimer"]
    assert "Verified" not in pres["verdict_label"]


# ------------------------------------------------------- base-spec trust (real git)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],  # noqa: S607
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def _repo(tmp_path: Path, *, base_spec: str | None, head_spec: str | None) -> NS:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    if base_spec is not None:
        (repo / ".radius").mkdir()
        (repo / ".radius" / "intent.yml").write_text(base_spec, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    if head_spec is not None:
        (repo / ".radius").mkdir(exist_ok=True)
        (repo / ".radius" / "intent.yml").write_text(head_spec, encoding="utf-8")
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "head")
    return NS(repository_path=repo, base_ref=base, head_ref="HEAD", diff_text="diff")


SPEC = "version: 1\ncriteria:\n  - id: c1\n    text: a thing\n    tests: [tests/test_a.py]\n"


def test_spec_unchanged_on_base_is_base_spec(tmp_path) -> None:
    cmd = _repo(tmp_path, base_spec=SPEC, head_spec=SPEC)
    assert default_spec_provenance(cmd) == "base_spec"


def test_crlf_only_difference_is_still_unchanged(tmp_path) -> None:
    cmd = _repo(tmp_path, base_spec=SPEC, head_spec=SPEC.replace("\n", "\r\n"))
    assert default_spec_provenance(cmd) == "base_spec"


@pytest.mark.parametrize(
    ("base", "head"),
    [
        (None, SPEC),  # the PR adds the file: author-supplied
        (SPEC, SPEC + "  - id: c2\n    text: easy\n"),  # the PR changes it
        (None, None),  # no spec anywhere
    ],
)
def test_added_or_changed_spec_is_author_head_spec(tmp_path, base, head) -> None:
    assert default_spec_provenance(_repo(tmp_path, base_spec=base, head_spec=head)) == "author_head_spec"


def test_no_base_ref_means_author_head_spec(tmp_path) -> None:
    cmd = _repo(tmp_path, base_spec=SPEC, head_spec=SPEC)
    cmd.base_ref = None
    assert default_spec_provenance(cmd) == "author_head_spec"


def _collector(spec_fn):
    from radius_worker.verdict_v2.collect import Producers

    return VerdictStageACollector(
        StaticIntent(IntentFacts()), producers=Producers(spec_provenance=spec_fn)
    )


@pytest.mark.parametrize(
    ("fn", "expected"),
    [
        (lambda _c: "base_spec", "base_spec"),
        (lambda _c: "bogus", "author_head_spec"),
        (lambda _c: (_ for _ in ()).throw(RuntimeError("boom")), "author_head_spec"),
    ],
)
def test_collector_resolves_spec_provenance_conservatively(fn, expected) -> None:
    facts = IntentFacts(criteria=(crit(),))
    assert _collector(fn)._spec_provenance(facts, NS()) == expected


def test_collector_does_not_consult_git_without_spec_criteria() -> None:
    called = []
    facts = IntentFacts(criteria=(crit(origin=_origin("pr_body")),))
    coll = _collector(lambda c: called.append(c) or "base_spec")
    assert coll._spec_provenance(facts, NS()) == "author_head_spec"
    assert not called
