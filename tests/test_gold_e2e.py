"""IN-09 synthetic end-to-end run: sampler -> fetch -> annotate -> agreement -> adjudication.

All data are generated fakes with controlled noise. The assertions check the
tooling against hand-derived expectations; the numbers say nothing about real
annotation quality and must never be presented as gold results.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gold_agreement as ga  # noqa: E402
import gold_annotate as gan  # noqa: E402
import gold_lib as gl  # noqa: E402
import gold_sample as gsm  # noqa: E402
import gold_synthetic as gs  # noqa: E402

CLOCK = lambda: "2026-01-01T00:00:00+00:00"  # noqa: E731


class SyntheticGithub:
    """Fake REST API whose PR bodies carry planted criteria (truth kept by PR number)."""

    def __init__(self):
        self.truth: dict[tuple[str, int], list[dict]] = {}

    def body_for(self, repo, number):
        key = (repo, number)
        if key not in self.truth:
            rng = random.Random(number)
            pool = [(lab, ph) for lab, phs in gs.PHRASES.items() for ph in phs]
            rng.shuffle(pool)
            self.truth[key] = [{"source_id": "pr-body", "quote": ph, "testability": lab}
                               for lab, ph in pool[:4]]
        lines = [f"## Summary\nSynthetic change {number}. Not a real PR.\n", "## Acceptance Criteria"]
        lines += [f"- [ ] {t['quote']}" for t in self.truth[key]]
        return "\n".join(lines) + "\n"

    def __call__(self, url, headers):
        path = url[len("https://api.github.com"):].split("?")[0]
        parts = path.strip("/").split("/")
        repo = "/".join(parts[1:3])
        if len(parts) == 5 and parts[3] == "pulls":
            n = int(parts[4])
            body = {"title": f"Synthetic {n}", "body": self.body_for(repo, n), "head": {"sha": "d" * 40},
                    "user": {"login": f"user{n}"}, "html_url": f"https://example.invalid/{n}"}
            return 200, {"x-ratelimit-remaining": "999"}, json.dumps(body).encode()
        if len(parts) == 6 and parts[5] == "commits":
            return 200, {}, json.dumps([{"sha": "e" * 40, "commit": {"message": "wip"}, "html_url": ""}]).encode()
        return 404, {}, b"{}"


def trimmed_fraction(quote, words_cut):
    ws = quote.split(" ")
    kept = " ".join(ws[: len(ws) - words_cut])
    return len(kept) / len(quote)


def test_full_pipeline_with_controlled_noise(tmp_path):
    # 1. sample (candidate list is synthetic)
    cands = tmp_path / "cands.jsonl"
    cands.write_text("\n".join(json.dumps(c) for c in gs.make_candidates(300, seed=11)))
    sample_path = tmp_path / "sample.json"
    rc = gsm.main(["sample", "--input", str(cands), "--out", str(sample_path), "--seed", "99",
                   "--n-pilot", "2", "--n-dev", "2", "--n-test", "8"])
    assert rc == 1  # 8 test PRs: the power check must complain
    sample = json.loads(sample_path.read_text("utf-8"))
    assert sample["power_check"]["ok"] is False and len(sample["prs"]) == 12
    test_prs = [p for p in sample["prs"] if p["role"] == "test"]
    assert test_prs

    # 2. fetch sources through the injected fetcher (no network)
    gold = tmp_path / "gold"
    fake = SyntheticGithub()
    client = gsm.GithubClient(fake)
    rep = gsm.fetch_sources(sample, gold, client, now="2026-01-01T00:00:00+00:00", synthetic=True,
                            log=lambda *_: None)
    assert len(rep["written"]) == 12 and not rep["failed"]
    assert gl.list_pr_ids(gold) == sorted(p["pr_id"] for p in sample["prs"])
    pids = sorted(rep["written"])[:6]

    # 3. two independent annotators with planted noise, one adjudicator
    a = gan.Workspace(gold, "synth-a", allow_synthetic=True, clock=CLOCK)
    b = gan.Workspace(gold, "synth-b", allow_synthetic=True, clock=CLOCK)
    truths = {}
    for pid in pids:
        src = gl.read_json(gold / pid / "sources.json")
        truths[pid] = fake.truth[(src["pr"]["repo"], src["pr"]["number"])]
    noise = {
        0: {},
        1: {"drop": {1}},
        2: {"flip": {0: None}},  # label chosen below to differ from truth
        3: {"trim": {2: 1}},
        4: {"trim": {0: 6}},
        5: {"extra": [(None, "behavioral_testable")]},
    }
    expected_trim_iou = trimmed_fraction(truths[pids[3]][2]["quote"], 1)
    below = trimmed_fraction(truths[pids[4]][0]["quote"], 6)
    assert expected_trim_iou >= 0.5 > below  # the plan really hits both sides of the threshold
    for k, pid in enumerate(pids):
        gs.apply_plan(a, pid, truths[pid], {"seconds": 100})
        plan = dict(noise[k])
        plan["seconds"] = 110
        if k == 2:
            t0 = truths[pid][0]["testability"]
            plan["flip"] = {0: "subjective_or_vague" if t0 != "subjective_or_vague" else "untestable_external"}
        if k == 5:
            plan["extra"] = [("Not a real PR", "subjective_or_vague")]
        gs.apply_plan(b, pid, truths[pid], plan)

    # 4. agreement
    comps, docs, skipped = ga.collect(gold, pr_ids=pids, allow_synthetic=True)
    assert not skipped and len(comps) == 6
    rep = ga.build_report(comps, n_boot=200, seed=1, synthetic=True)
    o = rep["overall"]
    assert (o["n_explicit_a"], o["n_explicit_b"], o["n_matched"]) == (24, 24, 22)
    assert o["span_f1"] == pytest.approx(2 * 22 / 48)
    assert o["testability_kappa"]["po"] == pytest.approx(21 / 22)
    assert o["testability_kappa"]["n"] == 22
    assert 0.5 < o["testability_kappa"]["kappa"] < 1.0
    assert o["exact_span_share"] == pytest.approx(21 / 22)  # only the PR3 trim matched inexactly
    types = sorted(d["type"] for d in rep["disagreements"])
    assert types == ["only_a", "only_b", "overlap_below_threshold", "span_boundary", "testability_conflict"]
    assert rep["timing_seconds_per_pr"]["synth-a"]["median"] == 100
    assert rep["timing_seconds_per_pr"]["synth-b"]["median"] == 110
    assert rep["synthetic"] is True
    md = ga.report_markdown(rep)
    assert "SYNTHETIC DATA" in md

    # CLI path, including refusing synthetic data without the flag
    prs_file = tmp_path / "prs.txt"
    prs_file.write_text("\n".join(pids))
    assert ga.main(["compare", "--gold-dir", str(gold), "--prs", str(prs_file)]) == 2
    out_json = tmp_path / "report.json"
    assert ga.main(["compare", "--gold-dir", str(gold), "--prs", str(prs_file), "--allow-synthetic",
                    "--bootstrap", "50", "--out", str(out_json), "--md", str(tmp_path / "r.md")]) == 0
    assert json.loads(out_json.read_text("utf-8"))["overall"]["n_matched"] == 22

    # 5. adjudication skeletons (third person), then resolve programmatically
    assert ga.main(["skeleton", "--gold-dir", str(gold), "--prs", str(prs_file), "--allow-synthetic",
                    "--adjudicator", "synth-a"]) == 2  # an annotator cannot adjudicate
    assert ga.main(["skeleton", "--gold-dir", str(gold), "--prs", str(prs_file), "--allow-synthetic",
                    "--adjudicator", "synth-c"]) == 0
    status = {pid: gl.read_json(gold / pid / "adjudicated.json")["status"] for pid in pids}
    assert status[pids[0]] == "complete"  # nothing to resolve
    assert [p for p, s in status.items() if s == "skeleton"] == pids[1:]
    first = gl.read_json(gold / pids[1] / "adjudicated.json")
    assert ga.main(["skeleton", "--gold-dir", str(gold), "--prs", str(prs_file), "--allow-synthetic",
                    "--adjudicator", "synth-c"]) == 0
    assert gl.read_json(gold / pids[1] / "adjudicated.json") == first  # no overwrite without --force

    c = gan.Workspace(gold, "synth-c", mode="adjudicate", allow_synthetic=True, clock=CLOCK)
    for pid in pids[1:]:
        doc = c.load(pid)["doc"]
        for item in doc["criteria"]:
            if item["resolution"] != "pending":
                continue
            opts = item["options"]
            if "synth-a" in opts:
                o_ = opts["synth-a"]
                item.update(span=o_["span"], text=o_["text"], testability=o_["testability"],
                            resolution="take_a")
            else:  # only B proposed it: the adjudicator rejects it
                item["resolution"] = "dropped"
        doc["status"] = "complete"
        c.save(pid, doc)

    # 6. final checks on the adjudicated set
    total = 0
    for pid in pids:
        errs, _ = gl.validate_pr_dir(gold, pid, require_complete=True, allow_synthetic=True)
        assert errs == [], errs
        adj = gl.read_json(gold / pid / "adjudicated.json")
        assert adj["adjudicator_id"] == "synth-c" and adj["synthetic"] is True
        total += sum(1 for x in adj["criteria"] if x["resolution"] != "dropped")
    assert total == 24  # equals the planted truth: A was perfect, B's extra was rejected
    # adjudicated spans equal the planted quotes
    for pid in pids:
        adj = gl.read_json(gold / pid / "adjudicated.json")
        quotes = {t["quote"] for t in truths[pid]}
        assert {x["text"] for x in adj["criteria"] if x["resolution"] != "dropped"} == quotes


def test_all_synthetic_output_is_labelled_and_refused_by_default(tmp_path):
    gs.generate_fixture(tmp_path, n=1, seed=2)
    pid = gl.list_pr_ids(tmp_path)[0]
    with pytest.raises(gl.GoldError, match="synthetic"):
        ga.collect(tmp_path)
    for f in (tmp_path / pid).glob("*.json"):
        assert json.loads(f.read_text("utf-8"))["synthetic"] is True
    ws = gan.Workspace(tmp_path, "alice")
    assert ws.pr_ids() == []
