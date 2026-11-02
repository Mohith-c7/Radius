"""IN-09: annotation workspace and local server (synthetic PRs only)."""

from __future__ import annotations

import http.client
import json
import random
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gold_agreement as ga  # noqa: E402
import gold_annotate as gan  # noqa: E402
import gold_lib as gl  # noqa: E402
import gold_synthetic as gs  # noqa: E402

CLOCK = lambda: "2026-01-01T00:00:00+00:00"  # noqa: E731


@pytest.fixture()
def gold(tmp_path):
    rng = random.Random(3)
    truths = {}
    for i in range(3):
        doc, truth = gs.make_pr(i, rng, hostile=(i == 0))
        gs.write_pr(tmp_path, doc)
        truths[doc["pr_id"]] = truth
    return tmp_path, truths


def ws_for(gold_dir, user="synth-a", **kw):
    return gan.Workspace(gold_dir, user, allow_synthetic=True, clock=CLOCK, **kw)


# ---------------------------------------------------------------- policy


def test_prefill_refused_in_annotate_mode(gold):
    with pytest.raises(gl.GoldError, match="only allowed for adjudication"):
        gan.Workspace(gold[0], "synth-a", prefill_from_radius=True, allow_synthetic=True)


def test_prefill_is_off_by_default_and_suggestions_blocked(gold):
    gdir, truths = gold
    pid = next(iter(truths))
    adjudicator = gan.Workspace(gdir, "synth-c", mode="adjudicate", allow_synthetic=True)
    assert adjudicator.prefill is False
    with pytest.raises(gl.GoldError, match="disabled"):
        adjudicator.suggestions(pid)
    # and the CLI flag defaults to off
    assert "--prefill-from-radius" in gan.__doc__


def test_reserved_and_invalid_annotator_ids_refused(gold):
    for bad in ("radius", "system-x", "Alice", "../x"):
        with pytest.raises(gl.GoldError):
            gan.Workspace(gold[0], bad, allow_synthetic=True)


def test_synthetic_pr_not_offered_without_flag(gold):
    ws = gan.Workspace(gold[0], "alice")
    assert ws.pr_ids() == []
    with pytest.raises(gl.GoldError, match="synthetic"):
        ws.load(next(iter(gold[1])))


def test_blinded_mode_never_reads_other_annotators_or_radius_output(gold, monkeypatch):
    gdir, truths = gold
    pid = next(iter(truths))
    gs.apply_plan(ws_for(gdir, "synth-b"), pid, truths[pid])
    opened: list[str] = []
    real = gl.read_json

    def spy(path):
        opened.append(Path(path).name)
        return real(path)

    monkeypatch.setattr(gl, "read_json", spy)
    a = ws_for(gdir, "synth-a")
    loaded = a.load(pid)
    a.save(pid, loaded["doc"])
    a.status_rows()
    assert "annotator-synth-b.json" not in opened and "adjudicated.json" not in opened
    assert loaded["doc"]["criteria"] == [] and loaded["doc"]["blinded"] is True
    assert "meta" in loaded and "author_type" not in loaded["meta"]  # authorship hidden when blinded


def test_conflict_of_interest_blocks_assignment(gold):
    gdir, truths = gold
    pid = next(iter(truths))
    src = gl.read_json(gdir / pid / "sources.json")
    (gdir / "conflicts.json").write_text(json.dumps({"synth-a": {"repos": [src["pr"]["repo"]]}}))
    ws = ws_for(gdir, "synth-a")
    assert pid not in ws.pr_ids()
    with pytest.raises(gl.GoldError, match="conflict"):
        ws.load(pid)
    assert pid in ws_for(gdir, "synth-b").pr_ids()


# ---------------------------------------------------------------- saving


def test_add_criterion_by_quote_roundtrip_and_resume(gold):
    gdir, truths = gold
    pid = next(iter(truths))
    ws = ws_for(gdir)
    t = truths[pid][0]
    doc = ws.add_criterion(pid, testability=t["testability"], quote=t["quote"])
    c = doc["criteria"][0]
    body = next(s for s in gl.read_json(gdir / pid / "sources.json")["sources"] if s["source_id"] == "pr-body")
    assert body["text"][c["span"]["start"]: c["span"]["end"]] == c["text"] == t["quote"]
    again = ws_for(gdir).load(pid)["doc"]  # resume with a fresh workspace
    assert again["criteria"] == doc["criteria"] and again["status"] == "in_progress"
    assert [r["status"] for r in ws.status_rows() if r["pr_id"] == pid] == ["in_progress"]


def test_quote_occurrence_and_not_found(gold):
    gdir, truths = gold
    pid = next(iter(truths))
    ws = ws_for(gdir)
    with pytest.raises(gl.GoldError, match="not found"):
        ws.add_criterion(pid, testability="subjective_or_vague", quote="zzz-not-there")
    with pytest.raises(gl.GoldError):
        ws.add_criterion(pid, testability="subjective_or_vague", quote="Synthetic", occurrence=5)


def test_server_validation_rejects_bad_spans_and_keeps_old_file(gold):
    gdir, truths = gold
    pid = next(iter(truths))
    ws = ws_for(gdir)
    ws.add_criterion(pid, testability="behavioral_testable", quote=truths[pid][0]["quote"])
    before = (gdir / pid / "annotator-synth-a.json").read_text("utf-8")
    doc = ws.load(pid)["doc"]
    doc["criteria"][0]["span"]["end"] += 3  # offsets no longer match the text
    with pytest.raises(gl.GoldError):
        ws.save(pid, doc)
    doc = ws.load(pid)["doc"]
    doc["criteria"].append({"id": "c2", "explicit": True, "span": {"source_id": "pr-body", "start": 0, "end": 10**7},
                            "text": "x", "testability": "behavioral_testable"})
    with pytest.raises(gl.GoldError, match="outside"):
        ws.save(pid, doc)
    assert (gdir / pid / "annotator-synth-a.json").read_text("utf-8") == before


def test_client_cannot_forge_server_fields(gold):
    gdir, truths = gold
    pid = next(iter(truths))
    ws = ws_for(gdir)
    doc = ws.load(pid)["doc"]
    doc.update(annotator_id="synth-z", blinded=False, sources_digest="f" * 64, kind="adjudicated")
    doc["timing"] = {"active_seconds": 99999}
    res = ws.save(pid, doc)["doc"]
    assert res["annotator_id"] == "synth-a" and res["blinded"] is True and res["kind"] == "annotation"
    assert res["sources_digest"] != "f" * 64 and res["timing"]["active_seconds"] == 0


def test_time_logging_is_clamped_and_accumulates(gold):
    gdir, truths = gold
    pid = next(iter(truths))
    ws = ws_for(gdir)
    ws.save(pid, None, delta_seconds=15, new_session=True)
    ws.save(pid, None, delta_seconds=10_000)  # clamped to MAX_DELTA
    ws.save(pid, None, delta_seconds=-5)
    t = ws.load(pid)["doc"]["timing"]
    assert t["active_seconds"] == 15 + gan.MAX_DELTA and t["sessions"] == 1


def test_complete_requires_well_specified_decision(gold):
    gdir, truths = gold
    pid = next(iter(truths))
    ws = ws_for(gdir)
    doc = ws.load(pid)["doc"]
    doc["status"] = "complete"
    with pytest.raises(gl.GoldError, match="well_specified"):
        ws.save(pid, doc)
    doc["well_specified"] = True
    saved = ws.save(pid, doc)["doc"]
    assert saved["status"] == "complete" and saved["well_specified_set_at"]


def test_implicit_criterion_and_evidence(gold):
    gdir, truths = gold
    pid = next(iter(truths))
    ws = ws_for(gdir)
    doc = ws.add_criterion(pid, testability="behavioral_testable", explicit=False,
                           text="Existing users keep their sessions",
                           evidence=[{"source_id": "pr-body", "start": 0, "end": 5}])
    assert doc["criteria"][0]["span"] is None
    with pytest.raises(gl.GoldError):
        ws.add_criterion(pid, testability="behavioral_testable", explicit=False, text="  ")


def test_cli_status_and_add(gold, capsys):
    gdir, truths = gold
    pid = next(iter(truths))
    base = ["--gold-dir", str(gdir), "--annotator", "synth-a", "--allow-synthetic"]
    assert gan.main(["add", *base, "--pr", pid, "--quote", truths[pid][0]["quote"],
                     "--testability", "behavioral_testable"]) == 0
    assert gan.main(["status", *base]) == 0
    out = capsys.readouterr().out
    assert "in_progress" in out and "0/3 complete" in out
    assert gan.main(["serve", "--gold-dir", str(gdir), "--annotator", "synth-a", "--adjudicator", "synth-c"]) == 2
    assert gan.main(["status", "--gold-dir", str(gdir), "--annotator", "synth-a",
                     "--prefill-from-radius"]) == 2


# ---------------------------------------------------------------- adjudication


def make_skeleton(gdir, pid, truth):
    gs.apply_plan(ws_for(gdir, "synth-a"), pid, truth)
    other = "subjective_or_vague" if truth[0]["testability"] != "subjective_or_vague" else "untestable_external"
    gs.apply_plan(ws_for(gdir, "synth-b"), pid, truth, {"drop": {1}, "flip": {0: other}})
    src, anns, _ = gl.load_pr(gdir, pid)
    comp = ga.compare_pr(src, anns["synth-a"], anns["synth-b"])
    gl.write_json_atomic(gdir / pid / "adjudicated.json",
                         ga.build_skeleton(src, anns["synth-a"], anns["synth-b"], comp, "synth-c", now=CLOCK()))


def test_adjudication_flow_and_restrictions(gold):
    gdir, truths = gold
    pid = next(iter(truths))
    make_skeleton(gdir, pid, truths[pid])
    with pytest.raises(gl.GoldError, match="cannot adjudicate"):
        gan.Workspace(gdir, "synth-a", mode="adjudicate", allow_synthetic=True).load(pid)
    c = gan.Workspace(gdir, "synth-c", mode="adjudicate", allow_synthetic=True, clock=CLOCK)
    assert c.load(pid)["meta"]["author_type"]  # unblinded at adjudication
    doc = c.load(pid)["doc"]
    pending = [x for x in doc["criteria"] if x["resolution"] == "pending"]
    assert len(pending) == 2
    # the client cannot rewrite what the annotators proposed
    for x in doc["criteria"]:
        if x["resolution"] == "pending":
            x["options"] = {"forged": {}}
            x["origin"] = {"forged": "c9"}
    doc["status"] = "complete"
    doc["well_specified"] = True
    with pytest.raises(gl.GoldError, match="pending"):
        c.save(pid, doc)
    stored = gl.read_json(gdir / pid / "adjudicated.json")
    assert all("forged" not in x.get("options", {}) for x in stored["criteria"])
    server_copy = {y["id"]: y for y in gl.read_json(gdir / pid / "adjudicated.json")["criteria"]}
    for x in doc["criteria"]:
        if x["resolution"] == "pending":
            opts = server_copy[x["id"]]["options"]
            real = opts["synth-a"] if "synth-a" in opts else next(iter(opts.values()))
            x.update(span=real["span"], text=real["text"], testability=real["testability"],
                     resolution="take_a")
    saved = c.save(pid, doc)["doc"]
    assert saved["status"] == "complete" and saved["adjudicator_id"] == "synth-c"
    assert gl.validate_pr_dir(gdir, pid, require_complete=True, allow_synthetic=True)[0] == []


def test_adjudicate_requires_skeleton(gold):
    gdir, truths = gold
    pid = next(iter(truths))
    with pytest.raises(gl.GoldError, match="skeleton"):
        gan.Workspace(gdir, "synth-c", mode="adjudicate", allow_synthetic=True).load(pid)


def test_radius_suggestions_only_when_enabled_and_marked(gold):
    pytest.importorskip("radius_intent")
    gdir, truths = gold
    pid = list(truths)[1]
    make_skeleton(gdir, pid, truths[pid])
    c = gan.Workspace(gdir, "synth-c", mode="adjudicate", allow_synthetic=True, prefill_from_radius=True)
    sugs = c.suggestions(pid)
    texts = [s["text"] for s in sugs]
    assert any(t["quote"] in x or x in t["quote"] for t in truths[pid] for x in texts)
    assert all(s["testability"] in gl.TESTABILITY for s in sugs)
    src = gl.read_json(gdir / pid / "sources.json")
    body = next(s["text"] for s in src["sources"] if s["source_id"] == sugs[0]["source_id"])
    assert all(body[s["start"]: s["end"]] == s["text"] for s in sugs if s["source_id"] == sugs[0]["source_id"])
    # accepting one is recorded as such and still validates
    doc = c.load(pid)["doc"]
    s0 = sugs[0]
    doc["criteria"].append({"id": "a99", "explicit": True, "resolution": "added", "from_radius_suggestion": True,
                            "span": {"source_id": s0["source_id"], "start": s0["start"], "end": s0["end"]},
                            "text": s0["text"], "testability": s0["testability"]})
    out = c.save(pid, doc)["doc"]
    assert next(x for x in out["criteria"] if x["id"] == "a99")["from_radius_suggestion"] is True


# ---------------------------------------------------------------- HTTP / rendering safety


class Running:
    def __init__(self, ws):
        self.httpd, self.url = gan.serve(ws, announce=lambda *_: None)
        self.port = self.httpd.server_address[1]
        self.token = self.url.split("t=")[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def req(self, method, path, body=None, *, token="ok", host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if token == "ok":
            headers["X-Gold-Token"] = self.token
        elif token:
            headers["X-Gold-Token"] = token
        if host:
            headers["Host"] = host
        data = json.dumps(body) if body is not None else None
        if data:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=headers)
        r = conn.getresponse()
        raw = r.read()
        hdrs = dict(r.getheaders())
        conn.close()
        return r.status, hdrs, raw

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def server(gold):
    gdir, truths = gold
    run = Running(ws_for(gdir))
    yield run, gdir, truths
    run.stop()


def test_http_requires_token_and_valid_host(server):
    run, _, truths = server
    assert run.req("GET", "/api/prs", token=None)[0] == 403
    assert run.req("GET", "/api/prs", token="wrong")[0] == 403
    assert run.req("GET", "/api/prs", host="evil.example")[0] == 403  # DNS-rebinding guard
    assert run.req("GET", "/?t=wrong", token=None)[0] == 403
    assert run.req("GET", f"/?t={run.token}", token=None)[0] == 200
    assert run.req("POST", "/api/pr/x/save", {}, token=None)[0] == 403
    assert run.req("GET", "/api/nope")[0] == 404


def test_page_has_strict_csp_and_no_source_text_or_html_sinks(server):
    run, _, truths = server
    status, hdrs, raw = run.req("GET", f"/?t={run.token}", token=None)
    page = raw.decode()
    csp = hdrs["Content-Security-Policy"]
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    assert "default-src 'none'" in csp and "unsafe-inline" not in csp and "connect-src 'self'" in csp
    assert page.count(f'nonce="{nonce}"') == 2
    assert hdrs["X-Content-Type-Options"] == "nosniff" and hdrs["Cache-Control"] == "no-store"
    assert "alert(" not in page and "synthetic xss" not in page
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
                 "srcdoc", "javascript:"):
        assert sink not in page, sink
    # nonce differs per response
    other = run.req("GET", f"/?t={run.token}", token=None)[1]["Content-Security-Policy"]
    assert other != csp


def test_hostile_source_text_is_data_only_json(server):
    run, gdir, truths = server
    pid = next(iter(truths))  # hostile=True for the first PR
    status, hdrs, raw = run.req("GET", f"/api/pr/{pid}")
    assert status == 200 and hdrs["Content-Type"].startswith("application/json")
    data = json.loads(raw)
    body = next(s for s in data["sources"] if s["source_id"] == "pr-body")["text"]
    assert "<script>alert('synthetic xss probe')</script>" in body  # preserved byte-exact for offsets
    assert hdrs["X-Content-Type-Options"] == "nosniff"


def test_http_save_flow_and_rejection(server):
    run, gdir, truths = server
    pid = list(truths)[1]
    status, _, raw = run.req("GET", f"/api/pr/{pid}")
    data = json.loads(raw)
    doc = data["doc"]
    q = truths[pid][0]["quote"]
    body = next(s for s in data["sources"] if s["source_id"] == "pr-body")["text"]
    start = body.index(q)
    doc["criteria"].append({"id": "c1", "explicit": True, "testability": truths[pid][0]["testability"],
                            "span": {"source_id": "pr-body", "start": start, "end": start + len(q)},
                            "text": q})
    s, _, raw = run.req("POST", f"/api/pr/{pid}/save", {"doc": doc, "delta_seconds": 20, "new_session": True})
    assert s == 200 and json.loads(raw)["doc"]["timing"]["active_seconds"] == 20
    on_disk = gl.read_json(gdir / pid / "annotator-synth-a.json")
    assert on_disk["criteria"][0]["text"] == q
    doc["criteria"][0]["span"]["start"] += 1
    s, _, raw = run.req("POST", f"/api/pr/{pid}/save", {"doc": doc})
    assert s == 400 and "span slice" in json.loads(raw)["error"]
    assert run.req("GET", "/api/pr/..%2f..%2fetc")[0] == 400
    assert run.req("POST", f"/api/pr/{pid}/save", None)[0] in (200, 400)
    status, _, raw = run.req("GET", "/api/prs")
    assert json.loads(raw)["prs"][1]["n_criteria"] == 1


def test_suggestions_endpoint_blocked_when_prefill_off(server):
    run, _, truths = server
    s, _, raw = run.req("GET", f"/api/pr/{next(iter(truths))}/suggestions")
    assert s == 400 and "disabled" in json.loads(raw)["error"]


def test_page_script_is_syntactically_valid_javascript(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    js = re.search(r'<script nonce="__NONCE__">(.*)</script>', gan.PAGE, re.S).group(1)
    f = tmp_path / "page.js"
    f.write_text(js, encoding="utf-8")
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
