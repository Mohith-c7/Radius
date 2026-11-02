"""Local annotation tool for the IN-09 gold set (single file, stdlib only).

A small web UI served on 127.0.0.1 (http.server + vanilla JS, no external
requests). The annotator selects spans in the stored source texts, labels
testability, sets the well-specified flag and finishes the PR; the tool saves
``annotator-<id>.json`` after every change, supports resume and logs active
time. Source text is untrusted: it is never placed in HTML, only sent as JSON
and rendered with ``textContent``; the page is served with a nonce-only CSP.

    python scripts/gold_annotate.py serve  --annotator alice [--queue prs.txt] [--open]
    python scripts/gold_annotate.py serve  --adjudicator carol --prefill-from-radius
    python scripts/gold_annotate.py status --annotator alice
    python scripts/gold_annotate.py add    --annotator alice --pr PR --quote "must return 400" \\
                                           --testability behavioral_testable

Modes
-----
* annotate (default): *blinded*. Only the annotator's own file is read; no
  other annotator's file and no Radius output is ever loaded. Annotator ids that
  look like tools (``radius*``, ``system*``, ...) are refused.
* adjudicate (``--adjudicator``): edits ``adjudicated.json`` created by
  ``gold_agreement.py skeleton``. The adjudicator must not be one of the two
  annotators. ``--prefill-from-radius`` (OFF by default, adjudicate only)
  adds deterministic-extractor output as clearly marked suggestions. Anchoring
  risk: showing system output biases humans toward it, so it is refused in
  annotate mode and every item taken from it is flagged
  ``from_radius_suggestion`` in the output.

Keyboard: see the '?' overlay in the UI.
"""

from __future__ import annotations

import argparse
import copy
import hmac
import json
import os
import secrets
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_lib as gl  # noqa: E402

MAX_BODY = 2 * 1024 * 1024
MAX_DELTA = 120.0  # seconds of active time accepted per request


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Workspace:
    """Everything the UI (or a script) may do, with all validation server-side."""

    def __init__(
        self,
        gold_dir: Path,
        user_id: str,
        *,
        mode: str = "annotate",
        allow_synthetic: bool = False,
        prefill_from_radius: bool = False,
        queue: list[str] | None = None,
        clock=_now,
    ):
        if mode not in ("annotate", "adjudicate"):
            raise gl.GoldError("mode must be annotate or adjudicate")
        if prefill_from_radius and mode != "adjudicate":
            raise gl.GoldError(
                "--prefill-from-radius is only allowed for adjudication: showing system output "
                "during independent annotation anchors the annotator (PREREGISTRATION 5.1)"
            )
        gl.check_annotator_id(user_id)
        self.gold_dir = Path(gold_dir)
        self.user = user_id
        self.mode = mode
        self.allow_synthetic = allow_synthetic
        self.prefill = prefill_from_radius
        self.clock = clock
        self.conflicts = gl.load_conflicts(self.gold_dir)
        self._queue = queue
        self._lock = threading.Lock()

    # -- paths -----------------------------------------------------------
    def _file(self, pr_id: str) -> Path:
        d = gl.pr_dir(self.gold_dir, pr_id)
        return d / ("adjudicated.json" if self.mode == "adjudicate" else f"annotator-{self.user}.json")

    def _sources(self, pr_id: str) -> dict:
        path = gl.pr_dir(self.gold_dir, pr_id) / "sources.json"
        if not path.exists():
            raise gl.GoldError(f"unknown PR {pr_id}")
        doc = gl.read_json(path)
        errs = gl.validate_sources_doc(doc)
        if errs:
            raise gl.GoldError(f"{pr_id}/sources.json invalid: {errs[0]}")
        if doc.get("synthetic") and not self.allow_synthetic:
            raise gl.GoldError(f"{pr_id} is synthetic; pass --allow-synthetic")
        reason = gl.has_conflict(self.conflicts, self.user, doc)
        if reason:
            raise gl.GoldError(f"{pr_id}: {reason}; this PR is not assigned to you")
        if any(s["text"] is None for s in doc["sources"]):
            raise gl.GoldError(f"{pr_id}: source text withheld; re-fetch sources before annotating")
        return doc

    # -- listing ---------------------------------------------------------
    def pr_ids(self) -> list[str]:
        ids = gl.list_pr_ids(self.gold_dir)
        if self._queue is not None:
            known = set(ids)
            ids = [i for i in self._queue if i in known]
        out = []
        for pid in ids:
            try:
                self._sources(pid)
            except gl.GoldError:
                continue  # conflicts, synthetic or withheld: not offered
            if self.mode == "adjudicate" and not self._file(pid).exists():
                continue
            out.append(pid)
        return out

    def status_rows(self) -> list[dict]:
        rows = []
        for pid in self.pr_ids():
            path = self._file(pid)
            row = {"pr_id": pid, "status": "not_started", "n_criteria": 0, "active_seconds": 0,
                   "pending": 0}
            if path.exists():
                doc = gl.read_json(path)
                row.update(
                    status=doc["status"],
                    n_criteria=len([c for c in doc["criteria"] if c.get("resolution") != "dropped"]),
                    active_seconds=doc["timing"]["active_seconds"],
                    pending=sum(1 for c in doc["criteria"] if c.get("resolution") == "pending"),
                )
            rows.append(row)
        return rows

    # -- load / save -----------------------------------------------------
    def load(self, pr_id: str) -> dict:
        with self._lock:
            src = self._sources(pr_id)
            path = self._file(pr_id)
            if path.exists():
                doc = gl.read_json(path)
                errs, _ = gl.validate_annotation_doc(doc, src)
                if errs:
                    raise gl.GoldError(f"existing file invalid ({errs[0]}); fix or move {path.name}")
                if self.mode == "annotate" and doc.get("annotator_id") != self.user:
                    raise gl.GoldError("annotation file belongs to another annotator")
            elif self.mode == "adjudicate":
                raise gl.GoldError(
                    f"{pr_id}: no adjudicated.json skeleton; run gold_agreement.py skeleton first"
                )
            else:
                doc = gl.new_annotation(pr_id, src, self.user, now=self.clock(),
                                        synthetic=bool(src.get("synthetic")))
            if self.mode == "adjudicate":
                if self.user in doc["annotators"]:
                    raise gl.GoldError("an annotator of this PR cannot adjudicate it")
                doc["adjudicator_id"] = self.user
            pr = src["pr"]
            meta = {"repo": pr["repo"], "number": pr["number"], "url": pr.get("url", ""),
                    "language": pr.get("language", "")}
            if self.mode == "adjudicate":
                meta["author_type"] = pr.get("author_type")
            return {
                "pr_id": pr_id,
                "meta": meta,
                "sources": [
                    {"source_id": s["source_id"], "kind": s["kind"], "text": s["text"],
                     "truncated": s.get("truncated", False)}
                    for s in src["sources"]
                ],
                "doc": doc,
            }

    def save(self, pr_id: str, client_doc: dict | None, delta_seconds: float = 0.0,
             new_session: bool = False) -> dict:
        """Validate and persist. Returns ``{"ok": True, "doc": ...}``; raises GoldError."""
        with self._lock:
            src = self._sources(pr_id)
            path = self._file(pr_id)
            if path.exists():
                doc = gl.read_json(path)
            elif self.mode == "annotate":
                doc = gl.new_annotation(pr_id, src, self.user, now=self.clock(),
                                        synthetic=bool(src.get("synthetic")))
            else:
                raise gl.GoldError("no skeleton to adjudicate")
            if self.mode == "adjudicate":
                if self.user in doc["annotators"]:
                    raise gl.GoldError("an annotator of this PR cannot adjudicate it")
                doc["adjudicator_id"] = self.user
            before = copy.deepcopy(doc)
            if client_doc is not None:
                self._merge_client(doc, client_doc)
            delta = max(0.0, min(float(delta_seconds or 0), MAX_DELTA))
            doc["timing"]["active_seconds"] = round(doc["timing"]["active_seconds"] + delta, 1)
            if new_session:
                doc["timing"]["sessions"] = doc["timing"].get("sessions", 0) + 1
            doc["timing"]["last_saved_at"] = self.clock()
            if doc["well_specified"] != before["well_specified"]:
                doc["well_specified_set_at"] = self.clock()
            errs, warns = gl.validate_annotation_doc(doc, src)
            if errs:
                raise gl.GoldError("; ".join(errs[:5]))
            gl.write_json_atomic(path, doc)
            return {"ok": True, "doc": doc, "warnings": warns}

    def _merge_client(self, doc: dict, cdoc: dict) -> None:
        """Copy only client-editable fields; server fields can not be forged."""
        if self.mode == "annotate":
            doc["criteria"] = [self._clean_criterion(c) for c in cdoc.get("criteria", [])]
        else:
            server_items = {c["id"]: c for c in doc["criteria"]}
            merged = []
            for c in cdoc.get("criteria", []):
                item = self._clean_criterion(c, adjudicated=True)
                old = server_items.get(item["id"])
                if old is not None:
                    for k in ("origin", "options", "reasons"):
                        if k in old:
                            item[k] = old[k]
                else:
                    item.pop("origin", None)
                    item.pop("options", None)
                merged.append(item)
            doc["criteria"] = merged
        doc["well_specified"] = cdoc.get("well_specified", doc["well_specified"])
        doc["no_recoverable_intent"] = bool(cdoc.get("no_recoverable_intent", False))
        if cdoc.get("status") in ("in_progress", "complete", "skeleton"):
            doc["status"] = cdoc["status"]
        if "notes" in cdoc:
            doc["notes"] = str(cdoc["notes"])[:4000]
        if self.mode == "annotate":
            doc["blinded"] = True

    @staticmethod
    def _clean_criterion(c: dict, *, adjudicated: bool = False) -> dict:
        out = {
            "id": c.get("id"),
            "explicit": bool(c.get("explicit")),
            "span": c.get("span"),
            "text": c.get("text"),
            "testability": c.get("testability"),
        }
        if c.get("evidence"):
            out["evidence"] = c["evidence"]
        if c.get("compound_group"):
            out["compound_group"] = c["compound_group"]
        if c.get("notes"):
            out["notes"] = str(c["notes"])[:2000]
        if adjudicated:
            out["resolution"] = c.get("resolution")
            if c.get("from_radius_suggestion"):
                out["from_radius_suggestion"] = True
        if isinstance(out["span"], dict):
            out["span"] = {k: out["span"].get(k) for k in ("source_id", "start", "end")}
        return out

    # -- programmatic helpers (used by tests, `add` and the synthetic run) --
    def add_criterion(
        self,
        pr_id: str,
        *,
        testability: str,
        quote: str | None = None,
        source_id: str | None = None,
        start: int | None = None,
        end: int | None = None,
        occurrence: int = 0,
        explicit: bool = True,
        text: str | None = None,
        evidence: list[dict] | None = None,
        notes: str = "",
        compound_group: str | None = None,
        resolution: str | None = None,
    ) -> dict:
        """Add one criterion. Explicit: give ``quote`` (n-th occurrence) or offsets."""
        loaded = self.load(pr_id)
        doc = loaded["doc"]
        texts = {s["source_id"]: s["text"] for s in loaded["sources"]}
        crit: dict = {"explicit": explicit, "testability": testability}
        if explicit:
            if quote is not None:
                sids = [source_id] if source_id else list(texts)
                found = []
                for sid in sids:
                    pos = texts[sid].find(quote)
                    while pos != -1:
                        found.append((sid, pos))
                        pos = texts[sid].find(quote, pos + 1)
                if len(found) <= occurrence:
                    raise gl.GoldError(f"quote not found (occurrence {occurrence}): {quote[:40]!r}")
                source_id, start = found[occurrence]
                end = start + len(quote)
            if source_id is None or start is None or end is None:
                raise gl.GoldError("explicit criteria need quote or source_id/start/end")
            crit["span"] = {"source_id": source_id, "start": start, "end": end}
            crit["text"] = texts[source_id][start:end] if source_id in texts else None
        else:
            crit["span"] = None
            crit["text"] = text
            if evidence:
                crit["evidence"] = evidence
        if notes:
            crit["notes"] = notes
        if compound_group:
            crit["compound_group"] = compound_group
        if resolution:
            crit["resolution"] = resolution
        used = [int(c["id"][1:]) for c in doc["criteria"]]
        crit["id"] = f"{'a' if self.mode == 'adjudicate' else 'c'}{max(used, default=0) + 1}"
        doc["criteria"].append(crit)
        return self.save(pr_id, doc)["doc"]

    def finish(self, pr_id: str, *, well_specified: bool | None, no_recoverable_intent: bool = False,
               seconds: float = 0.0) -> dict:
        loaded = self.load(pr_id)
        doc = loaded["doc"]
        doc["well_specified"] = well_specified
        doc["no_recoverable_intent"] = no_recoverable_intent
        doc["status"] = "complete"
        return self.save(pr_id, doc, delta_seconds=seconds)["doc"]

    # -- Radius suggestions (adjudication only, default off) -------------
    def suggestions(self, pr_id: str) -> list[dict]:
        if not self.prefill:
            raise gl.GoldError("suggestions are disabled (use --adjudicator with --prefill-from-radius)")
        src = self._sources(pr_id)
        try:
            from radius_intent.domain.enums import IntentSourceKind
            from radius_intent.domain.source import IntentSource
            from radius_intent.infrastructure.extraction import DeterministicCriterionExtractor
            from radius_intent.infrastructure.testability import rate_criteria
        except ImportError as exc:  # pragma: no cover - depends on PYTHONPATH
            raise gl.GoldError(
                "radius_intent is not importable; set PYTHONPATH=packages/intent/src:packages/shared/src"
            ) from exc
        fetched = datetime(2026, 1, 1, tzinfo=timezone.utc)
        sources = [
            IntentSource.from_text(s["source_id"], IntentSourceKind(s["kind"]), s["text"], fetched)
            for s in src["sources"]
        ]
        extractor = DeterministicCriterionExtractor()
        out = []
        for source in sources:
            for crit in rate_criteria(extractor.extract(source)):
                text = source.text
                a, b = crit.span.start, crit.span.end
                while a < b and text[a].isspace():
                    a += 1
                while b > a and text[b - 1].isspace():
                    b -= 1
                if b > a:
                    out.append({"source_id": source.source_id, "start": a, "end": b,
                                "text": text[a:b], "testability": crit.testability.value})
        out.sort(key=lambda s: (s["source_id"], s["start"]))
        return out


# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------


def make_handler(ws: Workspace, token: str, allowed_hosts: set[str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RadiusGoldAnnotate/1"

        def log_message(self, fmt, *args):  # quiet; never log paths with tokens
            pass

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

        def _authorized(self, query_token: str | None = None) -> bool:
            if self.headers.get("Host", "") not in allowed_hosts:
                return False
            supplied = self.headers.get("X-Gold-Token") or query_token or ""
            return hmac.compare_digest(supplied, token)

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            q = parse_qs(url.query)
            if url.path == "/":
                if not self._authorized((q.get("t") or [None])[0]):
                    return self._send(403, b"forbidden", "text/plain")
                nonce = secrets.token_urlsafe(12)
                csp = (
                    "default-src 'none'; script-src 'nonce-%s'; style-src 'nonce-%s'; "
                    "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
                ) % (nonce, nonce)
                page = PAGE.replace("__NONCE__", nonce).encode("utf-8")
                return self._send(200, page, "text/html; charset=utf-8", {"Content-Security-Policy": csp})
            if not self._authorized():
                return self._json(403, {"error": "forbidden"})
            try:
                if url.path == "/api/config":
                    return self._json(200, {
                        "mode": ws.mode, "user": ws.user, "prefill": ws.prefill,
                        "testability": list(gl.TESTABILITY), "guidelines": gl.GUIDELINES_VERSION,
                    })
                if url.path == "/api/prs":
                    return self._json(200, {"prs": ws.status_rows()})
                parts = url.path.strip("/").split("/")
                if len(parts) == 3 and parts[:2] == ["api", "pr"]:
                    return self._json(200, ws.load(parts[2]))
                if len(parts) == 4 and parts[:2] == ["api", "pr"] and parts[3] == "suggestions":
                    return self._json(200, {"suggestions": ws.suggestions(parts[2])})
            except gl.GoldError as exc:
                return self._json(400, {"error": str(exc)})
            self._json(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if not self._authorized():
                return self._json(403, {"error": "forbidden"})
            parts = urlparse(self.path).path.strip("/").split("/")
            if not (len(parts) == 4 and parts[:2] == ["api", "pr"] and parts[3] == "save"):
                return self._json(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n < 0 or n > MAX_BODY:
                    return self._json(413, {"error": "body too large"})
                body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                res = ws.save(parts[2], body.get("doc"), body.get("delta_seconds", 0),
                              bool(body.get("new_session")))
                return self._json(200, res)
            except (gl.GoldError, ValueError, TypeError) as exc:
                return self._json(400, {"error": str(exc)})

    return Handler


def serve(ws: Workspace, *, port: int = 0, open_browser: bool = False, announce=print):
    """Start the server; returns ``(httpd, url)`` (caller runs ``serve_forever``)."""
    token = secrets.token_urlsafe(18)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), lambda *a, **k: None)
    real_port = httpd.server_address[1]
    hosts = {f"127.0.0.1:{real_port}", f"localhost:{real_port}"}
    httpd.RequestHandlerClass = make_handler(ws, token, hosts)
    url = f"http://127.0.0.1:{real_port}/?t={token}"
    announce(f"Radius gold annotation ({ws.mode}, user {ws.user}) at {url}")
    announce("Local only. Press Ctrl+C to stop; work is saved after every change.")
    if open_browser:
        webbrowser.open(url)
    return httpd, url


# --------------------------------------------------------------------------
# Page (static; contains no source text)
# --------------------------------------------------------------------------

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Radius gold annotation</title>
<style nonce="__NONCE__">
:root{--bg:#fafafa;--fg:#1b1b1b;--mut:#666;--line:#d8d8d8;--sel:#ffe58a;--a:#cfe8ff;--b:#ffd9b8;--sug:#e3d4ff;--ok:#1a7f37;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#e8e8e8;--mut:#9a9a9a;--line:#3a3a3a;--sel:#6b5a12;--a:#1d3b57;--b:#5a3a1a;--sug:#3d2f5c;--ok:#4cc26a;--bad:#ff7b72}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;display:flex;flex-direction:column;height:100vh}
header,footer{padding:6px 12px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center;flex-wrap:wrap}
footer{border-top:1px solid var(--line);border-bottom:0;color:var(--mut)}
main{flex:1;display:flex;min-height:0}
#left{flex:3;display:flex;flex-direction:column;min-width:0;border-right:1px solid var(--line)}
#right{flex:2;overflow:auto;padding:8px 12px;min-width:280px}
#tabs{display:flex;gap:4px;flex-wrap:wrap;padding:6px 12px;border-bottom:1px solid var(--line)}
#tabs button{border:1px solid var(--line);background:transparent;color:var(--fg);border-radius:4px;padding:2px 8px;cursor:pointer}
#tabs button.on{background:var(--sel)}
#text{flex:1;overflow:auto;margin:0;padding:12px;white-space:pre-wrap;word-break:break-word;font:13px/1.5 ui-monospace,Consolas,monospace}
.seg.c{background:var(--a)}.seg.sel{background:var(--sel);outline:1px solid var(--fg)}.seg.opt{background:var(--b)}.seg.sug{background:var(--sug)}
.crit{border:1px solid var(--line);border-radius:6px;padding:6px 8px;margin:6px 0;cursor:pointer}
.crit.sel{border-color:var(--fg);box-shadow:0 0 0 2px var(--sel)}
.crit .t{white-space:pre-wrap;word-break:break-word;color:var(--mut);max-height:4.5em;overflow:hidden}
.tag{font-size:12px;border:1px solid var(--line);border-radius:10px;padding:0 6px;margin-right:4px}
.pending{border-style:dashed}
button.act,select,textarea{font:inherit;color:var(--fg);background:transparent;border:1px solid var(--line);border-radius:4px}
button.act{padding:2px 8px;cursor:pointer}
textarea{width:100%;min-height:3.5em}
#msg.bad{color:var(--bad)}#msg.ok{color:var(--ok)}
#help{position:fixed;inset:10% 15%;background:var(--bg);border:2px solid var(--fg);padding:16px;overflow:auto;display:none}
.banner{background:var(--sug);padding:4px 8px;border-radius:4px;margin:4px 0}
kbd{border:1px solid var(--line);border-radius:3px;padding:0 4px;font:12px ui-monospace,monospace}
</style></head><body>
<header><strong id="who"></strong><select id="prsel" aria-label="PR"></select>
<span id="meta"></span><span id="ws"></span><span id="timer"></span><span id="msg" role="status"></span></header>
<main><section id="left"><div id="tabs"></div><pre id="text" tabindex="0" aria-label="source text"></pre></section>
<aside id="right"><div id="adjbanner"></div><div id="ctl"></div><div id="list"></div><div id="sugs"></div></aside></main>
<footer><span id="selinfo">no selection</span><span>? help</span></footer>
<div id="help" role="dialog" aria-label="shortcuts"></div>
<script nonce="__NONCE__">
"use strict";
const $=id=>document.getElementById(id);
const TOKEN=new URLSearchParams(location.search).get('t')||'';
const KEYS={1:'behavioral_testable',2:'structural_checkable',3:'non_functional_measurable',4:'subjective_or_vague',5:'untestable_external'};
const SHORT={behavioral_testable:'behav',structural_checkable:'struct',non_functional_measurable:'nfr',subjective_or_vague:'vague',untestable_external:'external'};
const S={cfg:null,prs:[],data:null,doc:null,src:0,sel:null,cur:null,defT:'behavioral_testable',dirty:false,undo:[],sugs:[],lastInput:Date.now(),delta:0,newSession:true,saving:false};
async function api(path,opts){
  const r=await fetch(path,Object.assign({headers:{'X-Gold-Token':TOKEN,'Content-Type':'application/json'}},opts||{}));
  const j=await r.json(); if(!r.ok) throw new Error(j.error||r.statusText); return j;
}
function msg(t,cls){const m=$('msg');m.textContent=t;m.className=cls||'';}
function el(tag,props,kids){const e=document.createElement(tag);if(props)for(const k in props){if(k==='text')e.textContent=props[k];else if(k==='class')e.className=props[k];else if(k.startsWith('on'))e.addEventListener(k.slice(2),props[k]);else e.setAttribute(k,props[k]);}(kids||[]).forEach(c=>e.appendChild(c));return e;}
const cps=()=>Array.from(S.data.sources[S.src].text);
function curSource(){return S.data.sources[S.src];}
function nextId(){const p=S.cfg.mode==='adjudicate'?'a':'c';let m=0;S.doc.criteria.forEach(c=>{m=Math.max(m,parseInt(c.id.slice(1),10)||0)});return p+(m+1);}
function snapshot(){S.undo.push(JSON.stringify(S.doc.criteria));if(S.undo.length>60)S.undo.shift();}
function changed(){S.dirty=true;renderText();renderList();clearTimeout(S._t);S._t=setTimeout(save,700);}
async function save(extra){
  if(!S.data||S.saving)return; S.saving=true;
  try{const d=S.delta;S.delta=0;const body={doc:S.dirty?S.doc:null,delta_seconds:d,new_session:S.newSession};
    const res=await api('/api/pr/'+encodeURIComponent(S.data.pr_id)+'/save',{method:'POST',body:JSON.stringify(body)});
    S.newSession=false;if(S.dirty){S.dirty=false;}S.doc.timing=res.doc.timing;
    if(res.doc.status!==S.doc.status)S.doc.status=res.doc.status;
    msg('saved '+new Date().toLocaleTimeString(),'ok');if(res.warnings&&res.warnings.length)msg(res.warnings[0],'');
  }catch(e){S.delta+=0;msg('NOT SAVED: '+e.message,'bad');if(S.doc&&S.doc.status==='complete'){S.doc.status='in_progress';renderCtl();}}
  finally{S.saving=false;}
}
function selToSpan(){
  const pre=$('text');const s=window.getSelection();
  if(!s||s.rangeCount===0||s.isCollapsed||!pre.contains(s.anchorNode)||!pre.contains(s.focusNode)){S.sel=null;$('selinfo').textContent='no selection';return;}
  const pos=(n,o)=>{
    if(n.nodeType===3){const seg=n.parentElement.closest('.seg');if(!seg)return null;return +seg.dataset.s+Array.from(n.data.slice(0,o)).length;}
    if(n===pre){const ch=pre.childNodes[o];return ch?+ch.dataset.s:Array.from(curSource().text).length;}
    if(n.classList&&n.classList.contains('seg')){return o===0?+n.dataset.s:+n.dataset.e;}
    return null;};
  let a=pos(s.anchorNode,s.anchorOffset),b=pos(s.focusNode,s.focusOffset);
  if(a===null||b===null)return; if(a>b)[a,b]=[b,a];
  const c=cps();while(a<b&&/\s/.test(c[a]))a++;while(b>a&&/\s/.test(c[b-1]))b--;
  if(b<=a){S.sel=null;$('selinfo').textContent='no selection';return;}
  S.sel={source_id:curSource().source_id,start:a,end:b};
  $('selinfo').textContent='selection ['+a+','+b+') '+c.slice(a,Math.min(b,a+80)).join('').replace(/\s+/g,' ');
}
function renderText(){
  const pre=$('text');const keepTop=pre.scrollTop;pre.textContent='';
  const c=cps(),n=c.length,sid=curSource().source_id;
  const marks=[];
  S.doc.criteria.forEach(k=>{
    if(k.span&&k.span.source_id===sid&&k.resolution!=='dropped')marks.push({s:k.span.start,e:k.span.end,cls:k.id===S.cur?'sel':'c'});
    if(k.options&&k.resolution==='pending'){Object.values(k.options).forEach(o=>{if(o.span&&o.span.source_id===sid)marks.push({s:o.span.start,e:o.span.end,cls:'opt'});});}
  });
  S.sugs.forEach(g=>{if(g.source_id===sid)marks.push({s:g.start,e:g.end,cls:'sug'});});
  const pts=new Set([0,n]);marks.forEach(m=>{pts.add(Math.min(m.s,n));pts.add(Math.min(m.e,n));});
  const P=Array.from(pts).sort((x,y)=>x-y);
  for(let i=0;i<P.length-1;i++){const a=P[i],b=P[i+1];if(a===b)continue;
    const cl=['seg'];marks.forEach(m=>{if(m.s<=a&&b<=m.e)cl.push(m.cls);});
    const sp=el('span',{class:cl.join(' ')});sp.dataset.s=a;sp.dataset.e=b;sp.textContent=c.slice(a,b).join('');pre.appendChild(sp);}
  pre.scrollTop=keepTop;
  const tabs=$('tabs');tabs.textContent='';
  S.data.sources.forEach((s,i)=>tabs.appendChild(el('button',{class:i===S.src?'on':'',text:s.kind+' '+s.source_id+(s.truncated?' (truncated)':''),onclick:()=>{S.src=i;S.sel=null;renderText();}})));
}
function critEl(k){
  const pending=k.resolution==='pending';
  const row=el('div',{class:'crit'+(k.id===S.cur?' sel':'')+(pending?' pending':''),tabindex:'0',onclick:()=>selectCrit(k.id)});
  const head=el('div');
  head.appendChild(el('span',{class:'tag',text:k.id}));
  head.appendChild(el('span',{class:'tag',text:k.explicit?'explicit':'implicit'}));
  if(k.testability)head.appendChild(el('span',{class:'tag',text:SHORT[k.testability]||k.testability}));
  if(k.resolution)head.appendChild(el('span',{class:'tag',text:k.resolution}));
  if(k.from_radius_suggestion)head.appendChild(el('span',{class:'tag',text:'radius-suggested'}));
  (k.reasons||[]).forEach(r=>head.appendChild(el('span',{class:'tag',text:r})));
  row.appendChild(head);
  row.appendChild(el('div',{class:'t',text:k.text||(pending?'(pending)':'')}));
  if(pending&&k.options){const ids=Object.keys(k.options);const bar=el('div');
    ids.forEach(aid=>bar.appendChild(el('button',{class:'act',text:'take '+aid,onclick:ev=>{ev.stopPropagation();takeOption(k,aid);}})));
    bar.appendChild(el('button',{class:'act',text:'drop',onclick:ev=>{ev.stopPropagation();snapshot();k.resolution='dropped';changed();}}));row.appendChild(bar);
    ids.forEach(aid=>{const o=k.options[aid];row.appendChild(el('div',{class:'t',text:aid+': '+(o.testability||'?')+' '+(o.text||'')}));});}
  return row;
}
function takeOption(k,aid){
  snapshot();const o=k.options[aid];const idx=(S.doc.annotators||[]).indexOf(aid);
  k.explicit=o.explicit;k.span=o.span||null;k.text=o.text;k.testability=o.testability;if(o.evidence)k.evidence=o.evidence;
  k.resolution=idx===0?'take_a':'take_b';changed();
}
function renderList(){
  const l=$('list');l.textContent='';
  const vis=S.doc.criteria.filter(k=>k.resolution!=='dropped');
  l.appendChild(el('div',{text:vis.length+' criteria'+(S.cfg.mode==='adjudicate'?' ('+vis.filter(k=>k.resolution==='pending').length+' pending)':'')}));
  vis.forEach(k=>l.appendChild(critEl(k)));
  const cur=S.doc.criteria.find(k=>k.id===S.cur);
  if(cur){const ta=el('textarea',{'aria-label':'notes'});ta.value=cur.notes||'';
    ta.addEventListener('input',()=>{cur.notes=ta.value;S.dirty=true;clearTimeout(S._t);S._t=setTimeout(save,1200);});
    ta.addEventListener('keydown',e=>e.stopPropagation());
    l.appendChild(el('div',{text:'Notes for '+cur.id}));l.appendChild(ta);}
}
function renderCtl(){
  const c=$('ctl');c.textContent='';
  const wsText=S.doc.well_specified===null?'unset':(S.doc.well_specified?'yes':'no');
  $('ws').textContent='well-specified: '+wsText+' | '+S.doc.status;
  c.appendChild(el('div',{text:'Default label (keys 1-5): '+S.defT}));
  [['w','well-specified: '+wsText,cycleWs],['o','no recoverable intent: '+(S.doc.no_recoverable_intent?'yes':'no'),()=>{S.doc.no_recoverable_intent=!S.doc.no_recoverable_intent;changed();renderCtl();}],
   ['c',S.doc.status==='complete'?'reopen (c)':'mark complete (c)',toggleComplete]].forEach(([k,t,f])=>c.appendChild(el('button',{class:'act',text:t+' ['+k+']',onclick:f})));
}
function cycleWs(){S.doc.well_specified=S.doc.well_specified===null?true:(S.doc.well_specified?false:null);changed();renderCtl();}
async function toggleComplete(){
  if(S.doc.status==='complete'){S.doc.status='in_progress';changed();renderCtl();return;}
  if(S.doc.well_specified===null&&!S.doc.no_recoverable_intent){msg('set well-specified (w) first: decide before looking at anything else','bad');return;}
  S.doc.status='complete';S.dirty=true;clearTimeout(S._t);await save();renderCtl();loadList();
}
function selectCrit(id){S.cur=id;const k=S.doc.criteria.find(x=>x.id===id);
  if(k&&k.span){const i=S.data.sources.findIndex(s=>s.source_id===k.span.source_id);if(i>=0)S.src=i;}
  renderText();renderList();}
function addFromSelection(){
  if(!S.sel){msg('select text first','bad');return;}
  const ex=S.doc.criteria.find(k=>k.span&&k.span.source_id===S.sel.source_id&&k.span.start===S.sel.start&&k.span.end===S.sel.end&&k.resolution!=='dropped');
  if(ex){selectCrit(ex.id);return;}
  snapshot();const c=cps();
  const k={id:nextId(),explicit:true,span:Object.assign({},S.sel),text:c.slice(S.sel.start,S.sel.end).join(''),testability:S.defT};
  if(S.cfg.mode==='adjudicate')k.resolution='added';
  S.doc.criteria.push(k);S.cur=k.id;window.getSelection().removeAllRanges();S.sel=null;$('selinfo').textContent='added '+k.id;changed();
}
function addImplicit(){
  const t=window.prompt('Implicit criterion (your paraphrase; evidence = current selection if any):');
  if(!t||!t.trim())return;snapshot();
  const k={id:nextId(),explicit:false,span:null,text:t.trim(),testability:S.defT};
  if(S.sel)k.evidence=[Object.assign({},S.sel)];if(S.cfg.mode==='adjudicate')k.resolution='added';
  S.doc.criteria.push(k);S.cur=k.id;changed();
}
function setLabel(t){
  S.defT=t;const k=S.doc.criteria.find(x=>x.id===S.cur);
  if(k&&k.resolution!=='dropped'){snapshot();k.testability=t;if(S.cfg.mode==='adjudicate'&&k.resolution==='pending')k.resolution='merged';changed();}
  renderCtl();
}
function replaceSpan(){
  const k=S.doc.criteria.find(x=>x.id===S.cur);if(!k||!S.sel||!k.explicit){msg('select a criterion and a span','bad');return;}
  snapshot();k.span=Object.assign({},S.sel);k.text=cps().slice(S.sel.start,S.sel.end).join('');
  if(S.cfg.mode==='adjudicate')k.resolution='merged';changed();
}
function deleteCur(){
  const i=S.doc.criteria.findIndex(x=>x.id===S.cur);if(i<0)return;snapshot();
  const k=S.doc.criteria[i];
  if(S.cfg.mode==='adjudicate'&&k.origin){k.resolution='dropped';}else S.doc.criteria.splice(i,1);
  S.cur=null;changed();
}
function splitCur(){
  const k=S.doc.criteria.find(x=>x.id===S.cur);if(!k||!k.explicit||!k.span){msg('select an explicit criterion first','bad');return;}
  snapshot();let g=k.compound_group;
  if(!g){let m=0;S.doc.criteria.forEach(c=>{if(c.compound_group)m=Math.max(m,parseInt(c.compound_group.slice(1),10)||0);});g='g'+(m+1);k.compound_group=g;}
  const n=JSON.parse(JSON.stringify(k));n.id=nextId();n.notes='';delete n.options;delete n.origin;delete n.reasons;
  if(S.cfg.mode==='adjudicate')n.resolution='added';S.doc.criteria.push(n);S.cur=n.id;changed();
}
function undo(){if(!S.undo.length)return;S.doc.criteria=JSON.parse(S.undo.pop());changed();}
async function loadSugs(){
  try{const r=await api('/api/pr/'+encodeURIComponent(S.data.pr_id)+'/suggestions');S.sugs=r.suggestions;renderText();renderSugs();}
  catch(e){msg(e.message,'bad');}
}
function renderSugs(){
  const d=$('sugs');d.textContent='';if(!S.cfg.prefill)return;
  if(!S.sugs.length){d.appendChild(el('button',{class:'act',text:'load Radius suggestions [g] (anchoring risk)',onclick:loadSugs}));return;}
  d.appendChild(el('div',{class:'banner',text:'Radius suggestions (deterministic extractor). Decide your own view first; accepted items are flagged.'}));
  S.sugs.forEach(g=>d.appendChild(el('div',{class:'crit',onclick:()=>{S.src=S.data.sources.findIndex(s=>s.source_id===g.source_id);renderText();}},[
    el('div',{class:'t',text:SHORT[g.testability]+': '+g.text}),
    el('button',{class:'act',text:'accept',onclick:ev=>{ev.stopPropagation();snapshot();
      S.doc.criteria.push({id:nextId(),explicit:true,span:{source_id:g.source_id,start:g.start,end:g.end},text:g.text,testability:g.testability,resolution:'added',from_radius_suggestion:true});changed();}})])));
}
async function loadList(){
  const r=await api('/api/prs');S.prs=r.prs;const sel=$('prsel');sel.textContent='';
  S.prs.forEach(p=>sel.appendChild(el('option',{value:p.pr_id,text:p.pr_id+' ['+p.status+(p.pending?' pending '+p.pending:'')+']'})));
  if(S.data)sel.value=S.data.pr_id;
}
async function openPr(id){
  if(S.dirty){clearTimeout(S._t);await save();}
  try{S.data=await api('/api/pr/'+encodeURIComponent(id));}catch(e){msg(e.message,'bad');return;}
  S.doc=S.data.doc;S.src=0;S.sel=null;S.cur=null;S.undo=[];S.sugs=[];S.dirty=false;S.newSession=true;
  const m=S.data.meta;$('meta').textContent=m.repo+'#'+m.number+' '+m.language;
  $('prsel').value=id;renderText();renderList();renderCtl();renderSugs();msg('opened '+id);
  $('adjbanner').textContent='';
  if(S.cfg.mode==='adjudicate')$('adjbanner').appendChild(el('div',{class:'banner',text:'Adjudication: blue=agreed/final, orange=annotator proposals. Resolve every pending item.'}));
}
async function step(d){
  await loadList();const i=S.prs.findIndex(p=>p.pr_id===S.data.pr_id);const j=Math.max(0,Math.min(S.prs.length-1,i+d));
  if(S.prs[j])openPr(S.prs[j].pr_id);
}
function help(){const h=$('help');h.textContent='';h.style.display=h.style.display==='block'?'none':'block';
  [['select text + Enter / a','add criterion from selection'],['1 2 3 4 5','set label of selected criterion (and default): behav, struct, nfr, vague, external'],
   ['i','add implicit criterion (prompt)'],['w','cycle well-specified (set BEFORE finishing)'],['o','toggle no recoverable intent'],['c','mark PR complete / reopen'],
   ['x or Delete','remove selected criterion'],['z','undo'],['d','split: duplicate the selected criterion on the same span (compound statement, shared compound_group)'],['r','replace selected criterion span with current selection'],['[ ]','previous / next source tab'],
   ['n p','next / previous PR'],['Ctrl+S','save now'],['g','load Radius suggestions (adjudication + --prefill-from-radius only)'],['?','this help']]
   .forEach(([k,t])=>h.appendChild(el('div',null,[el('kbd',{text:k}),el('span',{text:'  '+t})])));}
document.addEventListener('keydown',e=>{
  S.lastInput=Date.now();
  if(e.target.tagName==='TEXTAREA'||e.target.tagName==='INPUT'||e.target.tagName==='SELECT')return;
  if(e.ctrlKey&&e.key==='s'){e.preventDefault();save();return;}
  if(e.ctrlKey||e.metaKey||e.altKey||!S.doc)return;
  const k=e.key;
  if(KEYS[k]){e.preventDefault();setLabel(KEYS[k]);}
  else if(k==='Enter'||k==='a'){e.preventDefault();selToSpan();addFromSelection();}
  else if(k==='i'){e.preventDefault();selToSpan();addImplicit();}
  else if(k==='w')cycleWs();
  else if(k==='o'){S.doc.no_recoverable_intent=!S.doc.no_recoverable_intent;changed();renderCtl();}
  else if(k==='c')toggleComplete();
  else if(k==='x'||k==='Delete'){deleteCur();}
  else if(k==='z')undo();
  else if(k==='d')splitCur();
  else if(k==='r'){selToSpan();replaceSpan();}
  else if(k==='g'&&S.cfg.prefill)loadSugs();
  else if(k==='n')step(1);else if(k==='p')step(-1);
  else if(k==='['){S.src=Math.max(0,S.src-1);renderText();}else if(k===']'){S.src=Math.min(S.data.sources.length-1,S.src+1);renderText();}
  else if(k==='?')help();
  else if(k==='Escape'){$('help').style.display='none';}
});
document.addEventListener('mouseup',()=>{S.lastInput=Date.now();selToSpan();});
['mousemove','mousedown','scroll','touchstart'].forEach(ev=>document.addEventListener(ev,()=>{S.lastInput=Date.now();},{passive:true}));
setInterval(()=>{ // active time: focused and input within the last 60 s
  if(document.hasFocus()&&Date.now()-S.lastInput<60000&&S.data){S.delta+=1;}
  $('timer').textContent=S.doc?'active '+Math.round((S.doc.timing.active_seconds||0)+S.delta)+' s':'';
},1000);
setInterval(()=>{if(S.data&&S.delta>=15&&!S.dirty)save();},5000);
$('prsel').addEventListener('change',e=>openPr(e.target.value));
(async()=>{
  try{S.cfg=await api('/api/config');$('who').textContent=S.cfg.mode+' | '+S.cfg.user;await loadList();
    const first=S.prs.find(p=>p.status!=='complete')||S.prs[0];if(first)openPr(first.pr_id);else msg('no PRs available','bad');}
  catch(e){msg(e.message,'bad');}
})();
</script></body></html>
"""


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _read_queue(path: str | None) -> list[str] | None:
    if not path:
        return None
    return [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("serve", "status", "add"):
        p = sub.add_parser(name)
        p.add_argument("--gold-dir", default=str(gl.GOLD_DIR))
        p.add_argument("--annotator")
        p.add_argument("--adjudicator")
        p.add_argument("--queue", help="file with PR ids in the order to annotate")
        p.add_argument("--allow-synthetic", action="store_true")
        p.add_argument("--prefill-from-radius", action="store_true",
                       help="adjudication only; OFF by default (anchoring bias)")
    s = sub.choices["serve"]
    s.add_argument("--port", type=int, default=0)
    s.add_argument("--open", action="store_true")
    a = sub.choices["add"]
    a.add_argument("--pr", required=True)
    a.add_argument("--quote", required=True)
    a.add_argument("--testability", required=True, choices=list(gl.TESTABILITY))
    a.add_argument("--occurrence", type=int, default=0)
    args = ap.parse_args(argv)
    if bool(args.annotator) == bool(args.adjudicator):
        print("error: give exactly one of --annotator / --adjudicator", file=sys.stderr)
        return 2
    try:
        ws = Workspace(
            Path(args.gold_dir), args.adjudicator or args.annotator,
            mode="adjudicate" if args.adjudicator else "annotate",
            allow_synthetic=args.allow_synthetic, prefill_from_radius=args.prefill_from_radius,
            queue=_read_queue(args.queue),
        )
        if args.cmd == "status":
            rows = ws.status_rows()
            for r in rows:
                print(f"{r['pr_id']:50s} {r['status']:12s} criteria={r['n_criteria']:3d} "
                      f"active={r['active_seconds']:.0f}s pending={r['pending']}")
            done = sum(1 for r in rows if r["status"] == "complete")
            print(f"{done}/{len(rows)} complete")
            return 0
        if args.cmd == "add":
            ws.add_criterion(args.pr, testability=args.testability, quote=args.quote,
                             occurrence=args.occurrence)
            print("added")
            return 0
        httpd, _url = serve(ws, port=args.port, open_browser=args.open)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
        finally:
            httpd.server_close()
        return 0
    except gl.GoldError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
