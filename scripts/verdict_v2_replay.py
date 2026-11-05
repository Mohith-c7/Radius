#!/usr/bin/env python
"""Replay Verdict v2 (Stage A + B, static evidence) on merged PRs of this repository.

    python scripts/verdict_v2_replay.py --select last --n 30
    python scripts/verdict_v2_replay.py --select stratified --per-stratum 8
    python scripts/verdict_v2_replay.py --numbers 100 107 --force
    python scripts/verdict_v2_replay.py --summary-only        # re-render from the cache

What it is: an exploratory, descriptive first look at what the pipeline prints on real PRs
(IMPLEMENTATION_PLAN 1; ALIGNMENT_LOG 2026-11-03). It is NOT a pre-registered evaluation:
one repository, same team, no ground truth, no CI per-case results (static evidence only),
and intent comes from PR titles/bodies that were never written in the Radius format.

Safety: GitHub access is read-only (``gh api -X GET`` only); nothing is ever posted. Each PR
runs in its own child process (hard timeout, memory freed between PRs). Python sources are
read from git objects (``git archive``) into a temp directory that is removed afterwards;
base-side reads go through git itself; the checkout is never modified. Results are cached
per PR under ``--cache-dir`` (default ``.cache/verdict_v2_replay``, git-ignored), so a run is
resumable. No LLM and no network beyond the ``gh api`` GETs.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
for _src in (*sorted((ROOT / "packages").glob("*/src")), ROOT / "apps" / "worker" / "src"):
    if str(_src) not in sys.path:
        sys.path.append(str(_src))

SCHEMA = "verdict-v2-replay-1"
DEFAULT_REPO = "Mohith-c7/Radius"
DEFAULT_CACHE = ROOT / ".cache" / "verdict_v2_replay"
STAMP = datetime(2026, 11, 3, tzinfo=UTC)
STRATA = ("feat", "fix", "docs", "ci", "other")
_TYPE_RE = re.compile(r"^\s*(?P<type>[a-zA-Z]+)(?:\([^)]*\))?!?:")
_TYPE_TO_STRATUM = {
    "feat": "feat",
    "fix": "fix",
    "docs": "docs",
    "ci": "ci",
    "build": "ci",
    "chore": "ci",
    "security": "ci",
}
PROMOTION_BRANCHES = frozenset({"develop", "dev", "uat", "main"})


# ------------------------------------------------------------------ read-only gh


class GhReader(Protocol):
    def get(self, path: str, **params: Any) -> Any: ...


class GhError(RuntimeError):
    """A read-only ``gh api`` call failed."""


@dataclass(slots=True)
class GhCli:
    """Read-only GitHub access through the ``gh`` CLI (GET only)."""

    user: str | None = "Mohith-c7"
    timeout_s: float = 60.0
    _token: str | None = field(default=None, repr=False)

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.user:
            if self._token is None:
                out = subprocess.run(  # noqa: S603
                    ["gh", "auth", "token", "--user", self.user],  # noqa: S607
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_s,
                    check=False,
                )
                if out.returncode == 0 and out.stdout.strip():
                    self._token = out.stdout.strip()
            if self._token:
                env["GH_TOKEN"] = self._token
        return env

    def get(self, path: str, **params: Any) -> Any:
        argv = ["gh", "api", "-X", "GET", path.lstrip("/")]
        for key, value in params.items():
            argv += ["-f", f"{key}={value}"]
        out = subprocess.run(  # noqa: S603
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.timeout_s,
            env=self._env(),
            check=False,
        )
        if out.returncode != 0:
            raise GhError(f"gh api GET {path} failed: {out.stderr.strip()[:200]}")
        return json.loads(out.stdout)


def normalise_pr(raw: dict[str, Any], repo: str) -> dict[str, Any]:
    """The subset of a GitHub pull-request JSON object that the replay uses."""

    user = (raw.get("user") or {}).get("login") or ""
    return {
        "number": int(raw["number"]),
        "url": raw.get("html_url") or f"https://github.com/{repo}/pull/{raw['number']}",
        "title": raw.get("title") or "",
        "body": raw.get("body") or "",
        "author": user,
        "base_ref": (raw.get("base") or {}).get("ref") or "",
        "head_ref": (raw.get("head") or {}).get("ref") or "",
        "base_sha": (raw.get("base") or {}).get("sha") or "",
        "head_sha": (raw.get("head") or {}).get("sha") or "",
        "merge_sha": raw.get("merge_commit_sha") or "",
        "merged_at": raw.get("merged_at") or "",
        "changed_files": raw.get("changed_files"),
        "additions": raw.get("additions"),
        "deletions": raw.get("deletions"),
    }


def list_merged_prs(gh: GhReader, repo: str, *, max_pages: int = 5) -> list[dict[str, Any]]:
    """Merged PRs (newest merge first), normalised to the fields the replay needs."""

    out: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        rows = gh.get(
            f"repos/{repo}/pulls",
            state="closed",
            per_page=100,
            page=page,
            sort="updated",
            direction="desc",
        )
        if not rows:
            break
        out += [normalise_pr(r, repo) for r in rows if r.get("merged_at")]
        if len(rows) < 100:
            break
    out.sort(key=lambda p: (p["merged_at"], p["number"]), reverse=True)
    return out


def fetch_pr_detail(gh: GhReader, repo: str, number: int) -> dict[str, Any]:
    """PR metadata plus the changed-file list (paths and counts only)."""

    meta = normalise_pr(gh.get(f"repos/{repo}/pulls/{number}"), repo)
    files: list[dict[str, Any]] = []
    for page in range(1, 4):  # 300 files max; larger PRs are skipped before this call
        rows = gh.get(f"repos/{repo}/pulls/{number}/files", per_page=100, page=page)
        files += [
            {
                "path": r.get("filename", ""),
                "status": r.get("status", ""),
                "additions": r.get("additions", 0),
                "deletions": r.get("deletions", 0),
            }
            for r in rows
        ]
        if len(rows) < 100:
            break
    meta["files"] = files
    return meta


# ------------------------------------------------------------------ selection


def title_type(title: str) -> str:
    m = _TYPE_RE.match(title or "")
    return m["type"].lower() if m else ""


def stratum_of(title: str) -> str:
    return _TYPE_TO_STRATUM.get(title_type(title), "other")


def skip_reason(pr: dict[str, Any], *, max_files: int = 300) -> str | None:
    """Why a PR is not replayed, or ``None``. Cheap checks only."""

    author = pr.get("author", "")
    title = pr.get("title", "")
    if author.endswith("[bot]") or author.lower() in {"dependabot", "renovate"}:
        return "bot_author"
    if re.match(r"^\s*(merge\b|release\b)", title, re.IGNORECASE):
        return "merge_or_release_only"
    if pr.get("head_ref") in PROMOTION_BRANCHES and pr.get("base_ref") in PROMOTION_BRANCHES:
        return "branch_promotion"
    if not pr.get("merge_sha"):
        return "no_merge_commit"
    changed = pr.get("changed_files")
    if isinstance(changed, int) and changed > max_files:
        return f"too_many_files:{changed}"
    return None


def select_prs(
    prs: Sequence[dict[str, Any]],
    *,
    mode: str = "last",
    n: int = 30,
    per_stratum: int = 6,
    max_files: int = 300,
) -> list[dict[str, Any]]:
    """Deterministic selection from ``prs`` (any order). Skipped PRs are not counted.

    ``last``: the ``n`` most recently merged eligible PRs. ``stratified``: the
    ``per_stratum`` most recent eligible PRs of each of feat/fix/docs/ci/other by
    conventional-commit title prefix. The result is ordered by PR number.
    """

    ordered = sorted(prs, key=lambda p: (p.get("merged_at", ""), p["number"]), reverse=True)
    eligible = [p for p in ordered if skip_reason(p, max_files=max_files) is None]
    if mode == "last":
        chosen = eligible[: max(0, n)]
    elif mode == "stratified":
        chosen = []
        for stratum in STRATA:
            chosen += [p for p in eligible if stratum_of(p["title"]) == stratum][:per_stratum]
    else:
        raise ValueError(f"unknown selection mode {mode!r}")
    return sorted(chosen, key=lambda p: p["number"])


# ------------------------------------------------------------------ classification


def classify_paths(paths: Iterable[str]) -> dict[str, Any]:
    """Coarse content profile of a PR from file paths only."""

    ext: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    for p in paths:
        suffix = Path(p).suffix.lower() or "(none)"
        ext[suffix] += 1
        low = p.lower()
        if low.startswith((".github/", "infra/")) or "dockerfile" in low:
            kinds["ci_infra"] += 1
        elif low.endswith((".md", ".rst", ".txt")) or low.startswith("docs/"):
            kinds["docs"] += 1
        elif re.search(r"(^|/)(tests?|__tests__)/|test_[^/]*\.py$|\.test\.[jt]sx?$", low):
            kinds["tests"] += 1
        elif low.endswith(".py"):
            kinds["python_src"] += 1
        elif low.endswith((".ts", ".tsx", ".js", ".jsx")):
            kinds["js_ts_src"] += 1
        else:
            kinds["other"] += 1
    total = sum(kinds.values())
    dominant = "empty"
    if total:
        top, count = kinds.most_common(1)[0]
        dominant = top if count == total else "mixed"
    return {"extensions": dict(ext.most_common(8)), "kinds": dict(kinds), "profile": dominant}


# ------------------------------------------------------------------ git helpers


def _git(repo: Path, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def resolve_range(repo: Path, pr: dict[str, Any]) -> tuple[str, str, str]:
    """``(base, head, kind)`` commits of a merged PR from git (no network).

    Merge commit (2 parents): base = merge-base of the parents, head = second parent.
    Squash/rebase (1 parent): base = the parent, head = the merge commit itself.
    Raises ``LookupError`` when the commits are not in the local object store.
    """

    merge = pr.get("merge_sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", merge):
        raise LookupError("merge_commit_not_sha")
    out = _git(repo, "rev-list", "--parents", "-n", "1", merge)
    parts = out.stdout.split()
    if out.returncode != 0 or not parts:
        raise LookupError("merge_commit_not_local")
    parents = parts[1:]
    if len(parents) >= 2:
        mb = _git(repo, "merge-base", parents[0], parents[1])
        if mb.returncode != 0 or not mb.stdout.strip():
            raise LookupError("no_merge_base")
        return mb.stdout.strip(), parents[1], "merge_commit"
    if len(parents) == 1:
        return parents[0], merge, "single_parent"
    raise LookupError("root_commit")


def materialize_python_tree(
    repo: Path, sha: str, dest: Path, *, max_bytes: int = 60 * 1024 * 1024, max_files: int = 20000
) -> dict[str, Any]:
    """Extract the ``.py`` files of commit ``sha`` into ``dest`` (streamed ``git archive``).

    Stage A reads Python only, so other files are not written. Returns counts and whether
    the byte/file cap truncated the tree. Names that escape ``dest`` are skipped.
    """

    dest.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(  # noqa: S603
        ["git", "-C", str(repo), "archive", "--format=tar", sha],  # noqa: S607
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    files = total = 0
    truncated = False
    root = dest.resolve()
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith(".py"):
                    continue
                target = (dest / member.name).resolve()
                if root not in target.parents:
                    continue
                if files >= max_files or total + member.size > max_bytes:
                    truncated = True
                    break
                target.parent.mkdir(parents=True, exist_ok=True)
                handle = tar.extractfile(member)
                if handle is None:
                    continue
                with handle, open(target, "wb") as fh:
                    shutil.copyfileobj(handle, fh)
                files += 1
                total += member.size
    finally:
        if truncated:
            proc.kill()
        if proc.stdout:
            proc.stdout.close()
        proc.wait(timeout=30)
    return {"files": files, "bytes": total, "truncated": truncated}


# ------------------------------------------------------------------ intent


_BULLET = re.compile(r"^(?P<indent>[ \t]{0,1})(?:[-*+]|\d+[.)])[ \t]+(?P<text>\S.*)$")
_MD = re.compile(r"[*`]+")
_PREFIX = re.compile(r"^\s*[a-zA-Z]+(?:\([^)]*\))?!?:\s*")
MAX_BULLET_CRITERIA = 15


def bullet_criteria(sources: Sequence[Any]) -> tuple[Any, ...]:
    """SENSITIVITY MODE (not production): the PR title subject and top-level body bullets.

    The production deterministic extractor only reads acceptance-style sections, so it finds
    nothing in ordinary PR text. This mode turns every top-level bullet of at least five words
    (and the title without its conventional prefix) into a proposed criterion, to see what
    the downstream pipeline does when it is given *something*. It is a crude upper bound on
    recall with unknown precision.
    """

    from radius_intent.domain import Criterion, ExtractionMethod, IntentSourceKind, Span

    out: list[Any] = []
    seen: set[str] = set()
    for src in sources:
        if src.kind is IntentSourceKind.PR_TITLE:
            spans = [(0, len(src.text), _PREFIX.sub("", src.text).strip())]
        else:
            spans, pos = [], 0
            for line in src.text.splitlines(keepends=True):
                bare = line.rstrip("\r\n")
                m = _BULLET.match(bare)
                if m:
                    spans.append((pos + m.start("text"), pos + len(bare), m["text"]))
                pos += len(line)
        for start, end, raw in spans:
            text = _MD.sub("", raw).strip()
            if len(text.split()) < 5 or len(text) > 300 or end <= start:
                continue
            key = text.lower()
            if key in seen or len(out) >= MAX_BULLET_CRITERIA:
                continue
            seen.add(key)
            out.append(
                Criterion.create(
                    src,
                    Span(src.source_id, start, end),
                    extraction_method=ExtractionMethod.DETERMINISTIC,
                    extractor_version="replay-bullets-v0",
                    text=text,
                )
            )
    return tuple(out)


def derive_intent(
    title: str, body: str, *, now: datetime = STAMP, mode: str = "deterministic"
) -> dict[str, Any]:
    """Deterministic intent from PR title and body (no LLM, no network).

    ``mode="deterministic"`` uses the production source preparation (sanitiser), the
    deterministic extractor and the rule-based testability rater. ``mode="bullets"`` is the
    labelled sensitivity mode above. Criteria stay ``proposed`` (nobody confirmed them).
    """

    from radius_github.intent_sources import pull_request_outcomes
    from radius_intent.infrastructure.extraction import DeterministicCriterionExtractor
    from radius_intent.infrastructure.testability.pipeline import rate_criteria

    outcomes = pull_request_outcomes(title, body, now=now, origin="rest_api")
    sources = [o.source for o in outcomes if o.source is not None]
    findings = sorted({f for o in outcomes for f in o.findings})
    criteria: tuple[Any, ...] = ()
    if sources:
        if mode == "bullets":
            criteria = tuple(rate_criteria(bullet_criteria(sources)))
        elif mode == "summary":
            from radius_intent.infrastructure.extraction import ExtractionConfig

            summary = DeterministicCriterionExtractor(ExtractionConfig(mode="summary"))
            criteria = tuple(rate_criteria(summary.extract_sources(sources).criteria))
        else:
            report = DeterministicCriterionExtractor().extract_sources(sources)
            criteria = tuple(rate_criteria(report.criteria))
    return {
        "criteria": criteria,
        "sources": [o.kind.value for o in outcomes if o.source is not None],
        "sanitizer_findings": findings,
    }


def linked_issues(title: str, body: str, repo: str) -> list[str]:
    from radius_github.intent_links import parse_closing_references

    owner, name = repo.split("/", 1)
    refs = parse_closing_references(f"{title}\n{body}", default_owner=owner, default_repo=name)
    return [r.label() for r in refs]


# ------------------------------------------------------------------ the run (child)


def _peak_rss_mb() -> float | None:
    try:
        import resource  # noqa: PLC0415

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(peak / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)
    except ImportError:
        pass
    try:  # Windows
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        c = Counters()
        c.cb = ctypes.sizeof(c)
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.windll.psapi  # type: ignore[attr-defined]
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return round(c.PeakWorkingSetSize / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        return None
    return None


def _uuid(number: int, salt: str) -> UUID:
    import hashlib  # noqa: PLC0415

    return UUID(hashlib.sha256(f"replay:{salt}:{number}".encode()).hexdigest()[:32])


def explain(result: dict[str, Any]) -> str:
    """One human-readable line for a finished run."""

    verdict = result.get("verdict")
    if not verdict:
        return f"no verdict: {result.get('status')} ({result.get('reason') or 'n/a'})"
    n = result.get("n_criteria", 0)
    bits = [f"{verdict} by {result.get('decided_by') or '?'}"]
    if n == 0:
        bits.append("no criteria extracted from the PR text")
    else:
        states = Counter(c["state"] for c in result.get("criteria", []))
        listed = ", ".join(f"{v} {k}" for k, v in sorted(states.items()))
        bits.append(
            f"{n} criteria ({listed}), UIM {result.get('uim', 0):.2f}, "
            f"coverage {result.get('intent_coverage', 0):.2f}"
        )
    tamper = result.get("tamper", [])
    if tamper:
        bits.append(
            f"{len(tamper)} tamper finding(s): " + ", ".join(sorted({t['rule_id'] for t in tamper}))
        )
    if result.get("degraded"):
        bits.append("degraded: " + ", ".join(result["degraded"][:3]))
    return "; ".join(bits)


def _score(stage_a: Any, stage_b: Any) -> dict[str, Any]:
    from radius_shared.verdict_v2_flag import VerdictV2Mode  # noqa: PLC0415
    from radius_worker.verdict_v2.scoring import ScoringPipeline  # noqa: PLC0415

    pipeline = ScoringPipeline(mode=VerdictV2Mode.SHADOW.value, clock=lambda: STAMP)
    return pipeline.score_full(stage_b).payload


def assume_green_stage_b(stage_a: Any) -> Any:
    """Stage B input in which every linked or changed test is assumed to have PASSED.

    A counterfactual upper bound on static support ("if CI were green"); there is no CI
    per-case data for historical PRs, and without it every verdict is R2p.
    """

    from radius_evidence.domain.enums import Outcome  # noqa: PLC0415
    from radius_evidence.domain.inputs import CaseOutcomeInput  # noqa: PLC0415
    from radius_worker.verdict_v2.scoring import build_stage_b  # noqa: PLC0415

    ids = {e.test_id for e in stage_a.symbol_test} | {e.test_id for e in stage_a.criterion_test}
    ids |= set(stage_a.changed_test_ids) | {a.test_id for a in stage_a.assertions}
    cases = tuple(
        CaseOutcomeInput(
            test_id=t, raw_file=None, raw_classname=None, raw_name=None, outcome=Outcome.PASSED
        )
        for t in sorted(ids)
    )
    return build_stage_b(stage_a, cases=cases, uploads=1)


def summarise_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Pick the fields a human reads from a Verdict v2 bundle."""

    crit = [
        {
            "id": c["criterion_id"],
            "text": c["text"],
            "testability": c.get("testability"),
            "state": c["state"],
            "S": c["S"],
            "flags": c.get("flags", []),
            "reasons": [r["code"] for r in c.get("reasons", [])],
            "n_items": len(c.get("items", [])),
        }
        for c in payload["criteria"]
    ]
    summary = payload["summary"]
    return {
        "verdict": payload["verdict"],
        "decided_by": payload["justification"]["decided_by"],
        "reasons": [{"code": r["code"], "detail": r["detail"]} for r in payload["reasons"]],
        "n_criteria": len(crit),
        "criteria": crit,
        "uim": summary["uim"],
        "intent_coverage": summary["intent_coverage"],
        "criteria_counts": {
            k: summary[k] for k in ("proven", "weak", "unevidenced", "contradicted", "excluded")
        },
        "tamper": [
            {
                "rule_id": t.get("rule_id"),
                "severity": t.get("severity"),
                "check": t.get("check"),
                "path": t.get("path"),
                "symbol": t.get("symbol"),
                "reason": str(t.get("reason") or "")[:160],
                "waived": bool(t.get("waived")),
            }
            for t in payload.get("tamper_findings", [])
        ],
        "degraded": list(payload.get("degraded", [])),
        "unlinked_symbols": len(payload.get("unlinked_symbols", [])),
        "algo_version": payload.get("algo_version"),
    }


def run_one(
    pr: dict[str, Any],
    *,
    repo_path: Path,
    work_root: Path | None,
    repo: str,
    lifecycle: str = "proposed",
    max_source_mb: int = 60,
    intent_mode: str = "deterministic",
) -> dict[str, Any]:
    """Run Stage A + B for one PR. Never raises for pipeline problems."""

    clock = time.monotonic
    started = clock()
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "number": pr["number"],
        "url": pr.get("url"),
        "title": pr["title"],
        "stratum": stratum_of(pr["title"]),
        "author": pr.get("author"),
        "merged_at": pr.get("merged_at"),
        "merge_sha": pr.get("merge_sha"),
        "lifecycle": lifecycle,
        "intent_mode": intent_mode,
        "evidence_basis": "static_only_ci_assumed_green",
        "status": "failed",
    }
    tmp = Path(tempfile.mkdtemp(prefix=f"replay-{pr['number']}-", dir=work_root))
    try:
        base, head, kind = resolve_range(repo_path, pr)
        result.update(base_sha=base, head_sha=head, range_kind=kind)
        paths = [f["path"] for f in pr.get("files", [])]
        result["changed_files"] = pr.get("changed_files") or len(paths)
        result["additions"] = pr.get("additions")
        result["deletions"] = pr.get("deletions")
        result["content"] = classify_paths(paths)
        result["linked_issues"] = linked_issues(pr["title"], pr.get("body", ""), repo)

        t0 = clock()
        from dataclasses import replace  # noqa: PLC0415

        from radius_intent.domain import CriterionState  # noqa: PLC0415

        intent = derive_intent(pr["title"], pr.get("body", ""), mode=intent_mode)
        crits = intent["criteria"]
        if lifecycle == "confirmed":
            crits = tuple(replace(c, state=CriterionState.CONFIRMED) for c in crits)
        result["intent_sources"] = intent["sources"]
        result["sanitizer_findings"] = intent["sanitizer_findings"]
        t_intent = clock() - t0

        t0 = clock()
        tree = tmp / "head"
        result["source_tree"] = materialize_python_tree(
            repo_path, head, tree, max_bytes=max_source_mb * 1024 * 1024
        )
        diff = _git(repo_path, "diff", "--no-color", "--no-ext-diff", base, head, timeout=120)
        if diff.returncode != 0:
            raise RuntimeError("git_diff_failed")
        diff_text = diff.stdout.replace("\r\n", "\n")
        commits = _git(repo_path, "log", "--format=%B%x00", f"{base}..{head}")
        messages = tuple(m.strip() for m in commits.stdout.split("\x00") if m.strip())
        t_prep = clock() - t0

        from radius_worker.orchestrator import ExecuteAnalysisCommand  # noqa: PLC0415
        from radius_worker.verdict_v2.collect import (  # noqa: PLC0415
            Producers,
            VerdictStageACollector,
        )
        from radius_worker.verdict_v2.scoring import build_stage_b  # noqa: PLC0415
        from radius_worker.verdict_v2.sources import (  # noqa: PLC0415
            IntentFacts,
            StaticIntent,
            read_python_sources,
        )

        aid = _uuid(pr["number"], "analysis")
        command = ExecuteAnalysisCommand(
            analysis_id=aid,
            repository_id=_uuid(pr["number"], "repository"),
            repository_path=repo_path,
            diff_text=diff_text,
            base_ref=base,
            head_ref=head,
        )

        class _Sha:
            def head_sha(self, analysis_id: UUID, command: Any) -> str:  # noqa: ARG002
                return head

        collector = VerdictStageACollector(
            StaticIntent(IntentFacts(criteria=crits, commit_messages=messages)),
            head_sha_port=_Sha(),
            producers=Producers(read_sources=lambda _root: read_python_sources(tree)),
        )
        t0 = clock()
        try:
            stage_a = collector.collect(aid, command)
        except Exception as exc:  # noqa: BLE001 - recorded, not raised
            result.update(
                status="stage_a_error",
                reason=str(getattr(exc, "reason_code", None) or type(exc).__name__),
            )
            return result
        t_a = clock() - t0

        t0 = clock()
        # As shipped, with no CI upload yet: rule R2p always decides (recorded, not scored).
        shipped = _score(stage_a, build_stage_b(stage_a, cases=(), uploads=0))
        result["as_shipped_no_ci"] = {
            "verdict": shipped["verdict"],
            "decided_by": shipped["justification"]["decided_by"],
        }
        # Counterfactual ceiling: every linked/changed test is ASSUMED to pass. No test was run.
        payload = _score(stage_a, assume_green_stage_b(stage_a))
        t_b = clock() - t0
        result["view"] = "assume_green_counterfactual"
        result.update(summarise_payload(payload))
        result["n_symbols"] = len(stage_a.symbols)
        result["n_tests_linked"] = len({e.test_id for e in stage_a.symbol_test})
        result["agent_signal"] = bool(stage_a.agent_signal)
        result["runtime_s"] = {
            "intent": round(t_intent, 3),
            "prep": round(t_prep, 3),
            "stage_a": round(t_a, 3),
            "stage_b": round(t_b, 3),
        }
        result["status"] = "ok"
    except LookupError as exc:
        result.update(status="skipped", reason=str(exc))
    except Exception as exc:  # noqa: BLE001
        result.update(status="failed", reason=f"{type(exc).__name__}: {str(exc)[:160]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        result["runtime_total_s"] = round(clock() - started, 3)
        result["peak_rss_mb"] = _peak_rss_mb()
        result["explanation"] = explain(result)
    return result


# ------------------------------------------------------------------ cache + orchestration


def result_path(cache: Path, number: int) -> Path:
    return cache / f"pr-{number}.json"


def load_cached(
    cache: Path, pr: dict[str, Any], lifecycle: str, intent_mode: str = "deterministic"
) -> dict[str, Any] | None:
    try:
        data = json.loads(result_path(cache, pr["number"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("schema") != SCHEMA or data.get("lifecycle") != lifecycle:
        return None
    if data.get("intent_mode", "deterministic") != intent_mode:
        return None
    if data.get("merge_sha") != pr.get("merge_sha"):
        return None
    return data


def store_result(cache: Path, result: dict[str, Any]) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    final = result_path(cache, result["number"])
    tmp = final.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(final)  # atomic: a killed run never leaves a half-written result


ChildRunner = Callable[[dict[str, Any], argparse.Namespace], dict[str, Any]]


def _failure(
    pr: dict[str, Any], args: argparse.Namespace, status: str, reason: str
) -> dict[str, Any]:
    r = {
        "schema": SCHEMA,
        "number": pr["number"],
        "url": pr.get("url"),
        "title": pr["title"],
        "stratum": stratum_of(pr["title"]),
        "lifecycle": args.lifecycle,
        "intent_mode": getattr(args, "intent_mode", "deterministic"),
        "status": status,
        "reason": reason,
        "merged_at": pr.get("merged_at"),
        "merge_sha": pr.get("merge_sha"),
    }
    r["explanation"] = explain(r)
    return r


def run_in_child(pr: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Run one PR in a fresh interpreter with a hard timeout (memory freed on exit)."""

    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    meta = cache / f"meta-{pr['number']}.json"
    out = cache / f"child-{pr['number']}.json"
    meta.write_text(json.dumps(pr), encoding="utf-8")
    out.unlink(missing_ok=True)
    argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        str(meta),
        "--worker-out",
        str(out),
        "--repo",
        args.repo,
        "--lifecycle",
        args.lifecycle,
        "--intent-mode",
        getattr(args, "intent_mode", "deterministic"),
        "--max-source-mb",
        str(args.max_source_mb),
    ]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        subprocess.run(argv, timeout=args.timeout, check=False, env=env, capture_output=True)  # noqa: S603
    except subprocess.TimeoutExpired:
        return _failure(pr, args, "timeout", f"exceeded {args.timeout:g}s")
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _failure(pr, args, "failed", "child_crashed_without_result")
    finally:
        out.unlink(missing_ok=True)


def replay(
    gh: GhReader,
    args: argparse.Namespace,
    *,
    child: ChildRunner = run_in_child,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Select, fetch metadata (read-only), run each PR (cached, resumable)."""

    cache = Path(args.cache_dir)
    listing = list_merged_prs(gh, args.repo)
    if args.numbers:
        wanted = set(args.numbers)
        chosen = sorted((p for p in listing if p["number"] in wanted), key=lambda p: p["number"])
    else:
        chosen = select_prs(
            listing,
            mode=args.select,
            n=args.n,
            per_stratum=args.per_stratum,
            max_files=args.max_files,
        )
    log(f"selected {len(chosen)} of {len(listing)} merged PRs")
    results: list[dict[str, Any]] = []
    for pr in chosen:
        cached = None if args.force else load_cached(cache, pr, args.lifecycle, getattr(args, "intent_mode", "deterministic"))
        if cached and (cached["status"] in ("ok", "skipped") or not args.retry_failed):
            log(f"#{pr['number']}: cached ({cached['status']})")
            results.append(cached)
            continue
        reason = skip_reason(pr, max_files=args.max_files)
        if reason:
            result = _failure(pr, args, "skipped", reason)
        else:
            try:
                detail = fetch_pr_detail(gh, args.repo, pr["number"])
            except Exception as exc:  # noqa: BLE001
                result = _failure(pr, args, "failed", f"metadata: {type(exc).__name__}")
            else:
                reason = skip_reason(detail, max_files=args.max_files)
                result = _failure(pr, args, "skipped", reason) if reason else child(detail, args)
        result["merge_sha"] = pr.get("merge_sha")
        store_result(cache, result)
        log(f"#{pr['number']}: {result['status']}  {result.get('explanation', '')[:110]}")
        results.append(result)
    return results


# ------------------------------------------------------------------ aggregate


def _pct(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[k]


def aggregate(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in results if r.get("status") == "ok"]
    runtimes = [r["runtime_total_s"] for r in ok if "runtime_total_s" in r]
    n_crit = [r["n_criteria"] for r in ok]
    cov = [r["intent_coverage"] for r in ok]
    markers = Counter(m for r in ok for m in r.get("degraded", []))
    return {
        "n_total": len(results),
        "status": dict(Counter(r.get("status", "?") for r in results)),
        "n_ok": len(ok),
        "verdicts": dict(Counter(r["verdict"] for r in ok)),
        "decided_by": dict(Counter(r["decided_by"] for r in ok)),
        "runtime_median_s": statistics.median(runtimes) if runtimes else None,
        "runtime_p95_s": _pct(runtimes, 0.95) if runtimes else None,
        "runtime_max_s": max(runtimes) if runtimes else None,
        "criteria_median": statistics.median(n_crit) if n_crit else None,
        "criteria_mean": round(statistics.fmean(n_crit), 2) if n_crit else None,
        "criteria_max": max(n_crit) if n_crit else None,
        "no_intent_fraction": (
            round(sum(1 for c in n_crit if c == 0) / len(n_crit), 3) if n_crit else None
        ),
        "degraded_runs": sum(1 for r in ok if r.get("degraded")),
        "degraded_markers": dict(markers),
        "tamper_runs": sum(1 for r in ok if r.get("tamper")),
        "tamper_findings": sum(len(r.get("tamper", [])) for r in ok),
        "coverage_quartiles": [_pct(cov, q) for q in (0.25, 0.5, 0.75)] if cov else None,
        "coverage_zero": sum(1 for c in cov if c == 0),
        "agent_signal_runs": sum(1 for r in ok if r.get("agent_signal")),
    }


def render_table(results: Sequence[dict[str, Any]]) -> str:
    lines = [
        "| PR | type | files | verdict | rule | crit | UIM | cov | tamper | time s | degraded |",
        "|---|---|---:|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in sorted(results, key=lambda x: x["number"]):
        if r.get("status") != "ok":
            lines.append(
                f"| #{r['number']} | {r.get('stratum', '')} | - | {r.get('status')} "
                f"({str(r.get('reason', ''))[:40]}) | - | - | - | - | - | - | - |"
            )
            continue
        lines.append(
            f"| #{r['number']} | {r['stratum']} | {r.get('changed_files', '')} | {r['verdict']} | "
            f"{r['decided_by']} | {r['n_criteria']} | {r['uim']:.2f} | "
            f"{r['intent_coverage']:.2f} | {len(r['tamper'])} | {r['runtime_total_s']:.1f} | "
            f"{', '.join(r['degraded']) or '-'} |"
        )
    return "\n".join(lines)


def render_aggregate(agg: dict[str, Any]) -> str:
    def fmt(v: Any) -> str:
        return "n/a" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))

    quart = " / ".join(fmt(v) for v in (agg["coverage_quartiles"] or []))
    rows = [
        ("PRs processed", agg["n_total"]),
        ("status", json.dumps(agg["status"])),
        ("verdict distribution", json.dumps(agg["verdicts"])),
        ("deciding rule", json.dumps(agg["decided_by"])),
        ("runs with a degraded marker", f"{agg['degraded_runs']} / {agg['n_ok']}"),
        ("degraded markers", json.dumps(agg["degraded_markers"])),
        (
            "runtime median / p95 / max (s)",
            f"{fmt(agg['runtime_median_s'])} / {fmt(agg['runtime_p95_s'])} / "
            f"{fmt(agg['runtime_max_s'])}",
        ),
        (
            "criteria per PR median / mean / max",
            f"{fmt(agg['criteria_median'])} / {fmt(agg['criteria_mean'])} / "
            f"{fmt(agg['criteria_max'])}",
        ),
        ("fraction of PRs with no extractable intent", fmt(agg["no_intent_fraction"])),
        ("intent coverage q25 / q50 / q75", quart),
        (
            "PRs with tamper findings (total findings)",
            f"{agg['tamper_runs']} ({agg['tamper_findings']})",
        ),
    ]
    return "| metric | value |\n|---|---|\n" + "\n".join(f"| {k} | {v} |" for k, v in rows)


# ------------------------------------------------------------------ CLI


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--select", choices=("last", "stratified"), default="last")
    ap.add_argument("--n", type=int, default=30, help="last mode: number of PRs")
    ap.add_argument("--per-stratum", type=int, default=6, help="stratified mode")
    ap.add_argument("--numbers", type=int, nargs="*", help="explicit PR numbers (overrides --select)")
    ap.add_argument(
        "--lifecycle",
        choices=("proposed", "confirmed"),
        default="proposed",
        help="state given to the extracted criteria (nobody confirmed them: proposed)",
    )
    ap.add_argument(
        "--intent-mode",
        choices=("deterministic", "bullets", "summary"),
        default="deterministic",
        help="deterministic: production extractor; bullets: labelled sensitivity mode "
        "(title + top-level bullets become proposed criteria)",
    )
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    ap.add_argument("--timeout", type=float, default=300.0, help="per-PR hard timeout (s)")
    ap.add_argument("--max-files", type=int, default=300, help="skip PRs touching more files")
    ap.add_argument("--max-source-mb", type=int, default=60, help="cap on extracted .py bytes")
    ap.add_argument("--gh-user", default="Mohith-c7")
    ap.add_argument("--force", action="store_true", help="ignore cached results")
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--summary-only", action="store_true", help="render from the cache, no runs")
    ap.add_argument("--json-out", help="write the collected results as JSON")
    ap.add_argument("--worker", help=argparse.SUPPRESS)
    ap.add_argument("--worker-out", help=argparse.SUPPRESS)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.worker:
        pr = json.loads(Path(args.worker).read_text(encoding="utf-8"))
        res = run_one(
            pr,
            repo_path=ROOT,
            work_root=None,
            repo=args.repo,
            lifecycle=args.lifecycle,
            max_source_mb=args.max_source_mb,
            intent_mode=args.intent_mode,
        )
        Path(args.worker_out).write_text(json.dumps(res, sort_keys=True), encoding="utf-8")
        return 0
    if args.summary_only:
        cache = Path(args.cache_dir)
        loaded = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(cache.glob("pr-*.json"))]
        results = [
            r for r in loaded if r.get("schema") == SCHEMA
            and r.get("lifecycle") == args.lifecycle
            and r.get("intent_mode", "deterministic") == args.intent_mode
        ]
    else:
        results = replay(GhCli(user=args.gh_user), args)
    print(render_table(results))
    print()
    print(render_aggregate(aggregate(results)))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(results, indent=1, sort_keys=True), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
