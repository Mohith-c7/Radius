"""IN-09: stratified sampler and the fetch-sources subcommand (offline).

Candidates and API responses are synthetic; no network is used.
"""

from __future__ import annotations

import base64
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gold_lib as gl  # noqa: E402
import gold_sample as gsm  # noqa: E402
import gold_synthetic as gs  # noqa: E402

NOW = "2026-01-01T00:00:00+00:00"


@pytest.fixture(scope="module")
def candidates():
    return gs.make_candidates(500, seed=7)


def run(cands, **kw):
    return gsm.sample(cands, **kw)


# ---------------------------------------------------------------- derivation


@pytest.mark.parametrize(
    "rec,expected",
    [
        ({"body": "x", "has_spec_file": "true"}, "spec_file"),
        ({"body": "Fixes #12"}, "issue_link"),
        ({"body": "closes octo/repo#4"}, "issue_link"),
        ({"body": "see https://github.com/o/r/issues/9"}, "issue_link"),
        ({"body": "no link", "related_issue_count": "2"}, "issue_link"),
        ({"body": "## A\nx\n## B\ny"}, "structured_template"),
        ({"body": "- [ ] do it\n- [x] done"}, "structured_template"),
        ({"body": "fix typo"}, "bare_oneliner"),
        ({"body": ""} | {"has_issue_link": False}, "bare_oneliner"),
        ({"body": "line one\nline two\nline three"}, "prose"),
        ({"body": "x", "richness": "prose"}, "prose"),
        ({"title": "no body column at all"}, None),
        ({"body": "x", "richness": "nonsense"}, None),
    ],
)
def test_richness_derivation(rec, expected):
    assert gsm.derive_richness(rec) == expected


def test_issue_number_in_url_fragment_not_confused_with_heading():
    assert gsm.derive_richness({"body": "colour #fff and so on\n\nmore text\nmore"}) == "prose"


@pytest.mark.parametrize(
    "rec,why",
    [
        ({"number": 1, "body": "x"}, "missing_repo_or_number"),
        ({"repo": "o/r", "body": "x", "additions": 1}, "missing_repo_or_number"),
        ({"repo": "o/r", "number": 1, "body": "x", "additions": 1}, "unknown_author_type"),
        ({"repo": "o/r", "number": 1, "agent": "codex", "additions": 1}, "unknown_richness"),
        ({"repo": "o/r", "number": 1, "agent": "codex", "body": "x"}, "unknown_size"),
    ],
)
def test_unusable_candidates_are_rejected_with_reason(rec, why):
    c, reason = gsm.normalize_candidate(rec)
    assert c is None and reason == why


def test_aidev_like_field_names_are_understood():
    c, _ = gsm.normalize_candidate({
        "id": 99, "repo_url": "https://api.github.com/repos/Octo/Cat", "number": "7",
        "agent": "Devin", "body": "fix", "additions": "10", "deletions": "5", "repo_language": "Go",
    })
    assert c["repo"] == "Octo/Cat" and c["author_type"] == "agent" and c["language"] == "go"
    assert c["size_bucket"] == "S" and c["pr_id"] == "Octo__Cat__pr7"


def test_size_buckets():
    f = gsm.size_bucket
    assert f({"changed_lines": 49}) == "S" and f({"changed_lines": 50}) == "M"
    assert f({"additions": 200, "deletions": 100}) == "L" and f({}) is None


# ---------------------------------------------------------------- sampling


def test_sampling_is_reproducible_and_seed_sensitive(candidates):
    a = run(candidates, seed=1)
    b = run(candidates, seed=1)
    c = run(candidates, seed=2)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert [p["pr_id"] for p in a["prs"]] != [p["pr_id"] for p in c["prs"]]
    assert "created" not in json.dumps({k: v for k, v in a.items() if k != "prs"})  # no timestamps
    assert a["seed"] == 1 and a["params"]["n_test"] == 130


def test_input_order_does_not_change_the_sample(candidates):
    a = run(candidates, seed=3)
    b = run(list(reversed(candidates)), seed=3)
    assert [p["pr_id"] for p in a["prs"]] == [p["pr_id"] for p in b["prs"]]


def test_strata_are_balanced_across_richness_and_author(candidates):
    out = run(candidates, seed=11)
    sel = out["strata_counts"]["selected"]
    assert len(sel) == 10  # 5 richness x 2 author types
    assert max(sel.values()) - min(sel.values()) <= 1
    assert sum(sel.values()) == 190 == len(out["prs"])
    lang = out["strata_counts"]["language"]
    assert len(lang) == 5 and max(lang.values()) - min(lang.values()) <= 12  # margins roughly balanced


def test_repo_cap_and_unique_ids(candidates):
    out = run(candidates, seed=5, max_per_repo=2)
    per_repo = Counter(p["repo"] for p in out["prs"])
    assert max(per_repo.values()) <= 2
    assert len({p["pr_id"] for p in out["prs"]}) == len(out["prs"])


def test_roles_split_by_repository_and_power_check(candidates):
    out = run(candidates, seed=5)
    roles = {}
    for p in out["prs"]:
        roles.setdefault(p["repo"], set()).add(p["role"])
    assert all(len(r) == 1 for r in roles.values())  # whole repos on one side
    pc = out["power_check"]
    assert pc["repo_overlap_test_vs_other_roles"] == []
    assert out["strata_counts"]["role"]["test"] == pc["n_test_prs"] >= 120
    assert pc["expected_criteria"] == pc["n_test_prs"] * 4 >= 461
    assert pc["required_test_prs_at_assumed_rate"] == 116  # ceil(461 / 4)
    assert pc["ok"] is True and pc["shortfalls"] == []
    calib = [p for p in out["prs"] if p["calibration"]]
    assert len(calib) == 10 and all(p["role"] == "pilot" for p in calib)


def test_power_check_flags_shortfalls():
    small = gs.make_candidates(60, seed=3)
    out = run(small, seed=1, n_pilot=5, n_dev=5, n_test=30)
    pc = out["power_check"]
    assert pc["ok"] is False
    assert any("test PRs" in s and "< 120" in s for s in pc["shortfalls"])
    assert any("expected criteria" in s for s in pc["shortfalls"])
    # a lower assumed criteria rate raises the PR requirement
    out2 = run(small, seed=1, n_pilot=5, n_dev=5, n_test=30, criteria_per_pr=2.0)
    assert out2["power_check"]["required_test_prs_at_assumed_rate"] == 231


def test_shortage_of_candidates_is_reported_not_silent():
    out = run(gs.make_candidates(40, seed=2), seed=1, n_pilot=10, n_dev=10, n_test=40)
    assert any("not enough eligible candidates" in w for w in out["warnings"])
    assert len(out["prs"]) < 60


def test_exclusions_remove_train_dev_ids_and_their_repos(candidates, tmp_path):
    first = run(candidates, seed=9)
    drop_ids = [p["pr_id"] for p in first["prs"][:20]]
    rep = tmp_path / "split_report.json"
    rep.write_text(json.dumps({"mode": "repo", "train_ids": drop_ids, "test_ids": ["keep"]}))
    ids, repos, hashes = gsm.load_exclusions([str(rep)])
    assert ids == set(drop_ids) and not repos
    out = run(candidates, seed=9, exclude_ids=ids)
    chosen = {p["pr_id"] for p in out["prs"]}
    assert not chosen & set(drop_ids)
    assert out["input"]["rejected"]["excluded_id_train_or_dev"] == 20
    # records-based exclusion also removes the whole repository (repo-disjoint from training)
    recs = tmp_path / "train.jsonl"
    victim = first["prs"][0]
    recs.write_text(json.dumps({"id": "t1", "repo": victim["repo"], "number": 999}) + "\n")
    ids, repos, _ = gsm.load_exclusions([str(recs)])
    out = run(candidates, seed=9, exclude_ids=ids, exclude_repos=repos)
    assert victim["repo"] not in {p["repo"] for p in out["prs"]}
    assert out["input"]["rejected"]["excluded_repo_of_train_or_dev"] >= 1


def test_plain_text_id_list_exclusions(tmp_path):
    p = tmp_path / "ids.txt"
    p.write_text("# comment\nfoo__bar__pr1\n\nfoo__bar__pr2\n")
    ids, _, _ = gsm.load_exclusions([str(p)])
    assert ids == {"foo__bar__pr1", "foo__bar__pr2"}


def test_duplicate_content_is_dropped_before_sampling():
    base = gs.make_candidates(30, seed=4)
    dup = dict(base[0])
    dup.update(id="cand-dup", number=9999)
    # same repo/title/body as base[0] but a different PR number
    out = run(base + [dup], seed=1, n_pilot=2, n_dev=2, n_test=10)
    assert out["input"]["rejected"].get("duplicate_content") == 1


def test_cli_sample_writes_manifest_and_reports_dataset_manifest(tmp_path, candidates, capsys):
    inp = tmp_path / "cands.jsonl"
    inp.write_text("\n".join(json.dumps(c) for c in candidates), encoding="utf-8")
    out = tmp_path / "sample.json"
    rc = gsm.main(["sample", "--input", str(inp), "--out", str(out), "--seed", "4",
                   "--dataset-manifest", "aidev-hf"])
    doc = json.loads(out.read_text("utf-8"))
    assert rc == 0 and doc["dataset_manifest"]["id"] == "aidev-hf"
    assert doc["dataset_manifest"]["revision"]
    assert doc["input"]["sha256"] and doc["input"]["n_records"] == 500
    out2 = tmp_path / "sample2.json"
    gsm.main(["sample", "--input", str(inp), "--out", str(out2), "--seed", "4",
              "--dataset-manifest", "aidev-hf"])
    assert out.read_bytes() == out2.read_bytes()
    assert gsm.main(["sample", "--input", str(inp), "--out", str(out2), "--dataset-manifest", "nope"]) == 2


def test_cli_csv_input(tmp_path):
    inp = tmp_path / "c.csv"
    rows = ["repo,number,agent,body,additions,deletions,language"]
    for i in range(1, 25):
        rows.append(f"o{i % 6}/r,{i},{'codex' if i % 2 else ''},\"Fixes #{i}\",{i * 3},1,python")
    inp.write_text("\n".join(rows), encoding="utf-8")
    out = tmp_path / "s.json"
    gsm.main(["sample", "--input", str(inp), "--out", str(out), "--n-pilot", "2", "--n-dev", "2",
              "--n-test", "6"])
    doc = json.loads(out.read_text("utf-8"))
    assert len(doc["prs"]) == 10 and {p["richness"] for p in doc["prs"]} == {"issue_link"}


# ---------------------------------------------------------------- fetch-sources


class FakeGithub:
    """Serves synthetic REST responses; records calls and the headers it saw."""

    def __init__(self, items, *, fail_once_rate_limit=False):
        self.calls: list[str] = []
        self.headers_seen: list[dict] = []
        self.routes: dict[str, tuple[int, object]] = {}
        self.rate_limited = fail_once_rate_limit
        for it in items:
            repo, n = it["repo"], it["number"]
            self.routes[f"/repos/{repo}/pulls/{n}"] = (200, {
                "title": f"Add thing {n}", "body": f"Fixes #{n}\n\n- [ ] it must work\n<!-- hidden -->",
                "html_url": f"https://github.com/{repo}/pull/{n}", "head": {"sha": "a" * 40},
                "user": {"login": "someone"}, "created_at": "2025-05-05T00:00:00Z"})
            self.routes[f"/repos/{repo}/issues/{n}"] = (200, {
                "title": "Issue", "body": "Expected: returns 200", "html_url": f"https://github.com/{repo}/issues/{n}"})
            self.routes[f"/repos/{repo}/pulls/{n}/commits"] = (200, [
                {"sha": "b" * 40, "commit": {"message": "feat: thing\n\nbody"}, "html_url": "u"},
                {"sha": "c" * 40, "commit": {"message": "Merge branch main"}, "html_url": "u"}])
            self.routes[f"/repos/{repo}/contents/.radius/intent.yml"] = (404, {})

    def __call__(self, url, headers):
        self.calls.append(url)
        self.headers_seen.append(dict(headers))
        path = url[len("https://api.github.com"):].split("?")[0]
        if self.rate_limited:
            self.rate_limited = False
            return 403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1000100"}, b"{}"
        status, body = self.routes.get(path, (404, {}))
        return status, {"x-ratelimit-remaining": "4000"}, json.dumps(body).encode()


def small_sample():
    return run(gs.make_candidates(80, seed=2), seed=1, n_pilot=2, n_dev=2, n_test=8)


def test_fetch_writes_valid_sources_and_is_idempotent(tmp_path):
    sample = small_sample()
    fake = FakeGithub(sample["prs"])
    client = gsm.GithubClient(fake, token="ghp_SECRET_TOKEN_VALUE_123")
    gold = tmp_path / "gold"
    rep = gsm.fetch_sources(sample, gold, client, roles={"test"}, now=NOW, synthetic=True, log=lambda *_: None)
    n_test = sum(1 for p in sample["prs"] if p["role"] == "test")
    assert len(rep["written"]) == n_test and not rep["failed"]
    pid = rep["written"][0]
    doc = gl.read_json(gold / pid / "sources.json")
    assert gl.validate_sources_doc(doc) == []
    kinds = [s["kind"] for s in doc["sources"]]
    assert kinds[:2] == ["pr_title", "pr_body"] and "issue" in kinds and "commit_message" in kinds
    assert not any(s["source_id"].startswith("commit-cccc") for s in doc["sources"])  # merge commit skipped
    body = next(s for s in doc["sources"] if s["kind"] == "pr_body")
    assert "hidden" not in body["text"] and body["raw_text_sha256"] != body["text_sha256"]
    assert doc["text_redistributable"] is False and doc["synthetic"] is True
    assert doc["pr"]["author_login_sha256"] == gl.login_hash("someone")
    assert "someone" not in json.dumps(doc)  # no plain login stored
    first_calls = len(fake.calls)
    rep2 = gsm.fetch_sources(sample, gold, client, roles={"test"}, now=NOW, synthetic=True, log=lambda *_: None)
    assert not rep2["written"] and len(rep2["skipped_existing"]) == n_test
    assert len(fake.calls) == first_calls  # idempotent: no request for existing sources


def test_token_never_stored_or_printed(tmp_path, capsys):
    sample = small_sample()
    fake = FakeGithub(sample["prs"])
    secret = "ghp_SECRET_TOKEN_VALUE_123"
    client = gsm.GithubClient(fake, token=secret)
    assert secret not in repr(client) and secret not in str(vars(client).get("_fetch", ""))
    gold = tmp_path / "gold"
    logs: list[str] = []
    gsm.fetch_sources(sample, gold, client, roles={"test"}, now=NOW, log=logs.append)
    assert any(h.get("Authorization") == f"Bearer {secret}" for h in fake.headers_seen)
    assert not any(secret in line for line in logs)
    for p in gold.rglob("*.json"):
        assert secret not in p.read_text("utf-8")
    assert secret not in capsys.readouterr().out


def test_rate_limit_waits_until_reset_then_succeeds():
    sample = small_sample()
    fake = FakeGithub(sample["prs"], fail_once_rate_limit=True)
    slept: list[float] = []
    client = gsm.GithubClient(fake, sleeper=slept.append, clock=lambda: 1_000_000.0)
    item = next(p for p in sample["prs"])
    doc = gsm.fetch_pr_sources(client, item, now=NOW)
    assert doc["sources"] and slept == [101.0]  # reset - now + 1 s


def test_rate_limit_longer_than_max_wait_stops_cleanly():
    sample = small_sample()
    fake = FakeGithub(sample["prs"], fail_once_rate_limit=True)
    client = gsm.GithubClient(fake, sleeper=lambda s: None, clock=lambda: 0.0, max_wait=60)
    with pytest.raises(gsm.RateLimitExceeded):
        gsm.fetch_pr_sources(client, sample["prs"][0], now=NOW)


def test_proactive_pause_when_budget_nearly_spent():
    calls = {"n": 0}

    def fetcher(url, headers):
        calls["n"] += 1
        return 200, {"x-ratelimit-remaining": "2", "x-ratelimit-reset": "1000030"}, b'{"a": 1}'

    slept = []
    client = gsm.GithubClient(fetcher, sleeper=slept.append, clock=lambda: 1_000_000.0, reserve=5)
    client.get("/repos/o/r/pulls/1")
    assert slept == [31.0]


def test_missing_pr_is_reported_as_failure_and_others_continue(tmp_path):
    sample = small_sample()
    fake = FakeGithub(sample["prs"][1:])  # first PR 404s
    client = gsm.GithubClient(fake)
    rep = gsm.fetch_sources(sample, tmp_path, client, now=NOW, log=lambda *_: None)
    assert [f["pr_id"] for f in rep["failed"]] == [sample["prs"][0]["pr_id"]]
    assert len(rep["written"]) == len(sample["prs"]) - 1


def test_upstream_change_never_overwrites_annotated_sources(tmp_path):
    sample = small_sample()
    fake = FakeGithub(sample["prs"])
    client = gsm.GithubClient(fake)
    gold = tmp_path / "g"
    gsm.fetch_sources(sample, gold, client, roles={"test"}, now=NOW, synthetic=True, log=lambda *_: None)
    pid = next(p["pr_id"] for p in sample["prs"] if p["role"] == "test")
    (gold / pid / "annotator-synth-a.json").write_text("{}")
    item = next(p for p in sample["prs"] if p["pr_id"] == pid)
    key = f"/repos/{item['repo']}/pulls/{item['number']}"
    status, body = fake.routes[key]
    fake.routes[key] = (status, {**body, "body": "edited upstream"})
    before = (gold / pid / "sources.json").read_text("utf-8")
    rep = gsm.fetch_sources(sample, gold, client, roles={"test"}, refresh=True, now=NOW,
                            synthetic=True, log=lambda *_: None)
    assert rep["changed_upstream"] == [pid]
    assert (gold / pid / "sources.json").read_text("utf-8") == before


def test_spec_file_source_is_picked_up():
    sample = small_sample()
    fake = FakeGithub(sample["prs"])
    item = sample["prs"][0]
    yml = base64.b64encode(b"criteria:\n  - text: must work\n").decode()
    fake.routes[f"/repos/{item['repo']}/contents/.radius/intent.yml"] = (
        200, {"encoding": "base64", "content": yml, "html_url": "u"})
    doc = gsm.fetch_pr_sources(gsm.GithubClient(fake), item, now=NOW)
    assert any(s["kind"] == "spec_file" for s in doc["sources"])


def test_fetch_cli_requires_yes_and_refuses_foreign_hosts(tmp_path, capsys):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(small_sample()))
    assert gsm.main(["fetch-sources", "--sample", str(p), "--gold-dir", str(tmp_path / "g")]) == 2
    with pytest.raises(gsm.FetchError):
        gsm.urllib_fetcher("https://evil.example/x", {})


def test_find_issue_refs():
    refs = gsm.find_issue_refs("Fixes #3, see o/r#4 and https://github.com/x/y/issues/5 and #3", "d/d")
    assert refs == [("d/d", 3), ("o/r", 4), ("x/y", 5)]


def test_queue_orders_differ_per_annotator_and_put_calibration_first(tmp_path):
    sample = run(gs.make_candidates(300, seed=7), seed=5)
    qa = gsm.make_queue(sample, "alice")
    qb = gsm.make_queue(sample, "bob")
    assert sorted(qa) == sorted(qb) == sorted(p["pr_id"] for p in sample["prs"])
    assert qa != qb and qa == gsm.make_queue(sample, "alice")
    calib = {p["pr_id"] for p in sample["prs"] if p["calibration"]}
    assert set(qa[:10]) == calib and set(qb[:10]) == calib
    roles = {p["pr_id"]: p["role"] for p in sample["prs"]}
    seq = [roles[i] for i in qa]
    assert seq == sorted(seq, key=["pilot", "dev", "test"].index)  # pilot, then dev, then test
    path = tmp_path / "s.json"
    path.write_text(json.dumps(sample))
    out = tmp_path / "q.txt"
    assert gsm.main(["queue", "--sample", str(path), "--annotator", "alice", "--out", str(out),
                     "--role", "test"]) == 0
    assert out.read_text("utf-8").split() == gsm.make_queue(sample, "alice", ["test"])
