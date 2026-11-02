"""Pure logic of scripts/verdict_v2_replay.py: selection, cache, metadata parsing, rendering."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "verdict_v2_replay_under_test", ROOT / "scripts" / "verdict_v2_replay.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rp = _load()
SHA = "a" * 40


def raw_pr(number, title, *, login="dev", base="develop", head="feature/x", merged="2026-11-02T10:00:00Z", changed=5):
    return {
        "number": number,
        "title": title,
        "body": f"body {number}",
        "html_url": f"https://github.com/o/r/pull/{number}",
        "user": {"login": login},
        "base": {"ref": base, "sha": "b" * 40},
        "head": {"ref": head, "sha": "c" * 40},
        "merge_commit_sha": SHA,
        "merged_at": merged,
        "changed_files": changed,
        "additions": 3,
        "deletions": 1,
    }


class FakeGh:
    """Read-only fake: serves canned JSON, records every path asked."""

    def __init__(self, listing, details=None):
        self.listing = listing
        self.details = details or {}
        self.calls = []

    def get(self, path, **params):
        self.calls.append((path, params))
        if path.endswith("/pulls"):
            return self.listing if params.get("page") == 1 else []
        if path.endswith("/files"):
            return [{"filename": "docs/a.md", "status": "added", "additions": 2, "deletions": 0}]
        number = int(path.rsplit("/", 1)[1])
        return self.details.get(number) or next(r for r in self.listing if r["number"] == number)


def args_for(tmp_path, **kw):
    ns = argparse.Namespace(
        repo="o/r", select="last", n=30, per_stratum=6, numbers=None, lifecycle="proposed",
        cache_dir=str(tmp_path / "cache"), timeout=5.0, max_files=300, max_source_mb=1,
        force=False, retry_failed=False,
    )
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def test_title_type_and_stratum():
    assert rp.title_type("feat(intent): add x") == "feat"
    assert rp.title_type("fix!: boom") == "fix"
    assert rp.stratum_of("build(deps): Bump y") == "ci"
    assert rp.stratum_of("chore: z") == "ci"
    assert rp.stratum_of("Codex/dashboard phase1") == "other"
    assert rp.stratum_of("test(x): y") == "other"


def test_skip_reasons():
    ok = rp.normalise_pr(raw_pr(1, "feat: a"), "o/r")
    assert rp.skip_reason(ok) is None
    assert rp.skip_reason({**ok, "author": "dependabot[bot]"}) == "bot_author"
    assert rp.skip_reason({**ok, "title": "Merge pull request #5 from x/y"}) == "merge_or_release_only"
    assert rp.skip_reason({**ok, "title": "Release: things"}) == "merge_or_release_only"
    assert rp.skip_reason({**ok, "head_ref": "dev", "base_ref": "main"}) == "branch_promotion"
    assert rp.skip_reason({**ok, "merge_sha": ""}) == "no_merge_commit"
    assert rp.skip_reason({**ok, "changed_files": 301}) == "too_many_files:301"
    assert rp.skip_reason({**ok, "changed_files": 300}) is None
    assert rp.skip_reason({**ok, "changed_files": None}) is None  # unknown until detail is fetched


def prs():
    rows = [
        raw_pr(10, "feat: a", merged="2026-11-02T01:00:00Z"),
        raw_pr(11, "fix: b", merged="2026-11-02T02:00:00Z"),
        raw_pr(12, "docs: c", merged="2026-11-02T03:00:00Z"),
        raw_pr(13, "ci: d", merged="2026-11-02T04:00:00Z"),
        raw_pr(14, "build(deps): e", login="dependabot[bot]", merged="2026-11-02T05:00:00Z"),
        raw_pr(15, "feat: f", merged="2026-11-02T06:00:00Z"),
        raw_pr(16, "feat: huge", merged="2026-11-02T07:00:00Z", changed=999),
        raw_pr(17, "Release: x", head="dev", base="main", merged="2026-11-02T08:00:00Z"),
    ]
    return [rp.normalise_pr(r, "o/r") for r in rows]


def test_select_last_skips_ineligible_and_is_deterministic():
    chosen = rp.select_prs(prs(), mode="last", n=3)
    assert [p["number"] for p in chosen] == [12, 13, 15]
    assert chosen == rp.select_prs(list(reversed(prs())), mode="last", n=3)


def test_select_stratified_takes_most_recent_per_stratum():
    chosen = rp.select_prs(prs(), mode="stratified", per_stratum=1)
    assert [p["number"] for p in chosen] == [11, 12, 13, 15]  # feat -> 15 (newest), fix, docs, ci
    with pytest.raises(ValueError):
        rp.select_prs(prs(), mode="nope")


def test_classify_paths():
    assert rp.classify_paths(["docs/a.md", "README.md"])["profile"] == "docs"
    assert rp.classify_paths([".github/workflows/ci.yml"])["profile"] == "ci_infra"
    assert rp.classify_paths(["a/b.py", "tests/test_b.py"])["profile"] == "mixed"
    assert rp.classify_paths([])["profile"] == "empty"


def test_explain_variants():
    assert "no verdict" in rp.explain({"status": "timeout", "reason": "exceeded 5s"})
    line = rp.explain(
        {"verdict": "insufficient_evidence", "decided_by": "R2a", "n_criteria": 0, "status": "ok"}
    )
    assert "no criteria extracted" in line and "R2a" in line
    line = rp.explain(
        {
            "verdict": "needs_review", "decided_by": "R3a", "n_criteria": 2, "uim": 0.5,
            "intent_coverage": 0.25, "criteria": [{"state": "weak"}, {"state": "weak"}],
            "tamper": [{"rule_id": "T001"}], "degraded": ["producer_failed:x"],
        }
    )
    assert "2 weak" in line and "T001" in line and "producer_failed:x" in line


def test_replay_with_fake_gh_is_read_only_and_cached(tmp_path):
    rows = [raw_pr(1, "docs: one"), raw_pr(2, "feat: two", merged="2026-11-02T11:00:00Z")]
    gh = FakeGh(rows)
    seen = []

    def child(pr, args):
        seen.append(pr["number"])
        assert pr["files"] and pr["files"][0]["path"] == "docs/a.md"
        return {
            "schema": rp.SCHEMA, "number": pr["number"], "title": pr["title"], "stratum": "docs",
            "lifecycle": args.lifecycle, "status": "ok", "verdict": "insufficient_evidence",
            "decided_by": "R2a", "n_criteria": 0, "uim": 0.0, "intent_coverage": 0.0,
            "tamper": [], "degraded": [], "runtime_total_s": 1.5, "changed_files": 1,
        }

    out = rp.replay(gh, args_for(tmp_path), child=child, log=lambda _m: None)
    assert [r["number"] for r in out] == [1, 2] and sorted(seen) == [1, 2]
    assert all(call[0].startswith("repos/o/r/pulls") for call in gh.calls)  # only GET-able reads
    # second run: everything comes from the cache, the child is not invoked again
    seen.clear()
    again = rp.replay(FakeGh(rows), args_for(tmp_path), child=child, log=lambda _m: None)
    assert seen == [] and [r["number"] for r in again] == [1, 2]
    # --force reruns
    rp.replay(FakeGh(rows), args_for(tmp_path, force=True), child=child, log=lambda _m: None)
    assert sorted(seen) == [1, 2]


def test_cache_is_keyed_on_merge_sha_lifecycle_and_schema(tmp_path):
    cache = tmp_path
    pr = {"number": 7, "merge_sha": SHA}
    rp.store_result(cache, {"schema": rp.SCHEMA, "number": 7, "lifecycle": "proposed",
                            "merge_sha": SHA, "status": "ok"})
    assert rp.load_cached(cache, pr, "proposed")["status"] == "ok"
    assert rp.load_cached(cache, pr, "confirmed") is None
    assert rp.load_cached(cache, {**pr, "merge_sha": "d" * 40}, "proposed") is None
    (cache / "pr-7.json").write_text(json.dumps({"schema": "old", "lifecycle": "proposed"}))
    assert rp.load_cached(cache, pr, "proposed") is None
    (cache / "pr-7.json").write_text("{not json")
    assert rp.load_cached(cache, pr, "proposed") is None


def test_failed_results_retry_only_when_asked(tmp_path):
    rows = [raw_pr(3, "fix: three")]
    calls = []

    def child(pr, args):
        calls.append(1)
        return rp._failure(pr, args, "timeout", "exceeded 5s")

    rp.replay(FakeGh(rows), args_for(tmp_path), child=child, log=lambda _m: None)
    rp.replay(FakeGh(rows), args_for(tmp_path), child=child, log=lambda _m: None)
    assert len(calls) == 1
    rp.replay(FakeGh(rows), args_for(tmp_path, retry_failed=True), child=child, log=lambda _m: None)
    assert len(calls) == 2


def test_metadata_failure_is_recorded_not_raised(tmp_path):
    class Boom(FakeGh):
        def get(self, path, **params):
            if path.endswith("/pulls"):
                return super().get(path, **params)
            raise RuntimeError("rate limited")

    out = rp.replay(Boom([raw_pr(4, "feat: four")]), args_for(tmp_path), child=None, log=lambda _m: None)
    assert out[0]["status"] == "failed" and "metadata" in out[0]["reason"]


def test_aggregate_and_rendering():
    def ok(n, verdict, rule, crit, t, cov=0.0, tamper=(), degraded=()):
        return {"number": n, "stratum": "feat", "status": "ok", "verdict": verdict,
                "decided_by": rule, "n_criteria": crit, "uim": 1.0, "intent_coverage": cov,
                "tamper": list(tamper), "degraded": list(degraded), "runtime_total_s": t,
                "changed_files": 3}

    results = [
        ok(1, "insufficient_evidence", "R2a", 0, 1.0),
        ok(2, "needs_review", "R3a", 2, 3.0, 0.5, tamper=[{"rule_id": "T1"}]),
        ok(3, "insufficient_evidence", "R2a", 0, 2.0, degraded=["producer_failed:relevance"]),
        {"number": 4, "stratum": "ci", "status": "timeout", "reason": "exceeded 5s"},
    ]
    agg = rp.aggregate(results)
    assert agg["n_total"] == 4 and agg["n_ok"] == 3
    assert agg["verdicts"] == {"insufficient_evidence": 2, "needs_review": 1}
    assert agg["no_intent_fraction"] == pytest.approx(0.667, abs=1e-3)
    assert agg["runtime_median_s"] == 2.0 and agg["runtime_p95_s"] == 3.0
    assert agg["tamper_runs"] == 1 and agg["degraded_runs"] == 1
    table = rp.render_table(results)
    assert "#4" in table and "timeout" in table and "R3a" in table
    assert "verdict distribution" in rp.render_aggregate(agg)
    assert rp.aggregate([])["runtime_median_s"] is None
    rp.render_aggregate(rp.aggregate([]))  # empty input must render


def test_derive_intent_and_linked_issues_on_plain_text():
    body = "## Summary\nAdds a retry.\n\n- The client retries three times on 503.\n\nCloses #12\n"
    intent = rp.derive_intent("feat(client): retry on 503", body)
    assert "pr_body" in intent["sources"]
    assert all(c.state.value == "proposed" for c in intent["criteria"])
    assert rp.linked_issues("t", body, "o/r") == ["o/r#12"]
    empty = rp.derive_intent("chore: x", "")
    assert isinstance(empty["criteria"], tuple)


def _git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)


def test_resolve_range_and_materialize_python_tree(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "a.py").write_bytes(b"x = 1\n")
    (repo / "notes.md").write_text("hi\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "feat")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "b.py").write_bytes(b"y = 2\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "feat")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--no-ff", "-qm", "Merge pull request #1", "feat")
    merge = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                           text=True, check=True).stdout.strip()
    base, head, kind = rp.resolve_range(repo, {"merge_sha": merge})
    assert kind == "merge_commit" and base != head
    info = rp.materialize_python_tree(repo, head, tmp_path / "out")
    assert info == {"files": 2, "bytes": 12, "truncated": False}
    assert (tmp_path / "out" / "pkg" / "b.py").is_file()
    assert not (tmp_path / "out" / "notes.md").exists()
    capped = rp.materialize_python_tree(repo, head, tmp_path / "out2", max_bytes=7)
    assert capped["truncated"] is True and capped["files"] == 1
    # a squash-style single-parent commit
    b2, h2, k2 = rp.resolve_range(repo, {"merge_sha": head})
    assert k2 == "single_parent" and h2 == head and b2 != head
    with pytest.raises(LookupError):
        rp.resolve_range(repo, {"merge_sha": "f" * 40})
    with pytest.raises(LookupError):
        rp.resolve_range(repo, {"merge_sha": "--upload-pack=x"})
