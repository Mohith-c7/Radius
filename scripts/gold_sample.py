"""Candidate PR sampler and source fetcher for the IN-09 gold set.

Stdlib only. Subcommands::

    python scripts/gold_sample.py sample --input candidates.jsonl --out sample.json \\
        [--seed 20261102] [--n-pilot 30] [--n-dev 30] [--n-test 130] \\
        [--exclude split_report.json]... [--dataset-manifest aidev-hf] \\
        [--max-per-repo 4] [--criteria-per-pr 4]
    python scripts/gold_sample.py fetch-sources --sample sample.json --yes \\
        [--gold-dir benchmarks/gold/intent] [--token-env GITHUB_TOKEN] [--role test]

``sample`` reads CSV or JSONL of candidate PRs (for example an export of the
AIDev ``pull_request`` / ``related_issue`` tables; nothing is downloaded here)
and writes a reproducible manifest: seed, parameters, input hash, stratum
counts, the chosen PRs with their role (pilot, dev, test) and a power check
against PREREGISTRATION section 5.5. The output has no timestamps, so the same
input and seed give byte-identical output.

Recognised input fields (first present wins): pr_id/id; repo/repository/
repo_full_name/repo_url; number/pr_number; url/html_url; author_type
(agent|human) or agent/agent_name (non-empty means agent) or is_agent; language/
repo_language/primary_language; additions + deletions or changed_lines or size;
created_at; body, title; has_issue_link/related_issue_count/issue_urls;
has_spec_file; richness (overrides the derived value); license.

Source richness (derived from the first matching rule, in this order):
``spec_file`` (flag), ``issue_link`` (closing keyword, #n, issue URL or flag),
``structured_template`` (>= 2 markdown headings, or a checklist, or an
acceptance heading), ``bare_oneliner`` (<= 1 non-empty line and < 200 chars),
``prose`` (everything else). Without a body or any flag the richness is
``unknown`` and the candidate is dropped (reported) because it cannot be
stratified.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_lib as gl  # noqa: E402

SAMPLE_SCHEMA = "radius-gold-sample-v1"
DEFAULT_SEED = 20261102
RICHNESS = ("spec_file", "issue_link", "structured_template", "bare_oneliner", "prose")
SIZE_BUCKETS = (("S", 50), ("M", 300), ("L", math.inf))  # changed lines upper bounds
# PREREGISTRATION 5.5 arithmetic
REQUIRED_CRITERIA = 461
REQUIRED_TEST_PRS = 120
MIN_STRATUM_TEST = 5

_CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[:\s]+"
    r"(?:[\w.-]+/[\w.-]+)?#\d+|https?://github\.com/[\w.-]+/[\w.-]+/issues/\d+|(?<![\w/])#\d+\b",
    re.IGNORECASE,
)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+\S", re.MULTILINE)
_CHECKLIST = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+\S", re.MULTILINE)
_ACCEPT = re.compile(r"acceptance criteria|given .* when .* then|^\s*scenario:", re.I | re.M)


def _load_datasets_module():
    path = Path(__file__).resolve().parent / "datasets.py"
    spec = importlib.util.spec_from_file_location("radius_datasets_for_gold", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# Input normalisation
# --------------------------------------------------------------------------


def _first(rec: dict, *keys):
    for k in keys:
        v = rec.get(k)
        if v not in (None, ""):
            return v
    return None


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "t")
    return bool(v)


def _repo_of(rec: dict) -> str | None:
    raw = _first(rec, "repo", "repository", "repo_full_name", "repo_url", "repository_url")
    if not raw:
        return None
    raw = str(raw).strip()
    m = re.search(r"(?:github\.com/(?:repos/)?|api\.github\.com/repos/)([\w.-]+/[\w.-]+)", raw)
    if m:
        raw = m.group(1)
    raw = re.sub(r"\.git$", "", raw)
    return raw if re.fullmatch(r"[\w.-]+/[\w.-]+", raw) else None


def derive_richness(rec: dict) -> str | None:
    explicit = _first(rec, "richness")
    if explicit:
        return str(explicit) if str(explicit) in RICHNESS else None
    body = _first(rec, "body")
    flags_present = any(
        k in rec for k in ("has_spec_file", "has_issue_link", "related_issue_count", "issue_urls")
    )
    if body is None and not flags_present:
        return None
    body = str(body or "")
    if _truthy(rec.get("has_spec_file")):
        return "spec_file"
    n_issues = _first(rec, "related_issue_count")
    if (
        _truthy(rec.get("has_issue_link"))
        or (n_issues is not None and str(n_issues).isdigit() and int(n_issues) > 0)
        or _first(rec, "issue_urls")
        or _CLOSING.search(body)
    ):
        return "issue_link"
    if len(_HEADING.findall(body)) >= 2 or _CHECKLIST.search(body) or _ACCEPT.search(body):
        return "structured_template"
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if len(lines) <= 1 and len(body.strip()) < 200:
        return "bare_oneliner"
    return "prose"


def size_bucket(rec: dict) -> str | None:
    n = _first(rec, "changed_lines", "size")
    if n is None:
        add, dele = rec.get("additions"), rec.get("deletions")
        if add in (None, "") and dele in (None, ""):
            return None
        n = int(float(add or 0)) + int(float(dele or 0))
    try:
        n = float(n)
    except (TypeError, ValueError):
        return None
    for name, upper in SIZE_BUCKETS:
        if n < upper:
            return name
    return "L"


def normalize_candidate(rec: dict) -> tuple[dict | None, str | None]:
    """Return ``(candidate, None)`` or ``(None, reason)``."""
    repo = _repo_of(rec)
    number = _first(rec, "number", "pr_number")
    try:
        number = int(float(number)) if number is not None else None
    except (TypeError, ValueError):
        number = None
    if repo is None or number is None or number < 1:
        return None, "missing_repo_or_number"
    pid = gl.pr_id_for(repo, number)
    atype = _first(rec, "author_type")
    agent_name = _first(rec, "agent", "agent_name")
    if atype:
        atype = str(atype).strip().lower()
        atype = "agent" if atype in ("agent", "ai", "bot") else "human" if atype == "human" else None
    elif agent_name:
        atype = "agent"
    elif "is_agent" in rec and rec["is_agent"] not in (None, ""):
        atype = "agent" if _truthy(rec["is_agent"]) else "human"
    elif agent_name is None and any(k in rec for k in ("agent", "agent_name")):
        atype = "human"
    if atype is None:
        return None, "unknown_author_type"
    rich = derive_richness(rec)
    if rich is None:
        return None, "unknown_richness"
    bucket = size_bucket(rec)
    if bucket is None:
        return None, "unknown_size"
    lang = str(_first(rec, "language", "repo_language", "primary_language") or "unknown")
    return (
        {
            "pr_id": pid,
            "repo": repo,
            "number": number,
            "url": str(_first(rec, "html_url", "url") or f"https://github.com/{repo}/pull/{number}"),
            "author_type": atype,
            "agent_name": str(agent_name) if agent_name else None,
            "language": lang.strip().lower() or "unknown",
            "size_bucket": bucket,
            "richness": rich,
            "created_at": str(_first(rec, "created_at") or ""),
            "license": str(_first(rec, "license", "repo_license") or "UNKNOWN"),
            "title": str(rec.get("title") or ""),
            "body": str(rec.get("body") or ""),
            "source_id": str(_first(rec, "pr_id", "id") or pid),
        },
        None,
    )


def read_candidates(path: Path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    if str(path).lower().endswith((".jsonl", ".ndjson")):
        return [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    if str(path).lower().endswith(".json"):
        data = json.loads(text)
        return data if isinstance(data, list) else data["records"]
    return list(csv.DictReader(io.StringIO(text)))


# --------------------------------------------------------------------------
# Exclusions (training / dev splits, DATA_HYGIENE section 3)
# --------------------------------------------------------------------------


def load_exclusions(paths: list[str]) -> tuple[set[str], set[str], set[str]]:
    """Return ``(ids, repos, content_hashes)`` to exclude.

    Accepted files: a split report from ``datasets.py split`` (uses
    ``train_ids``, plus ``dev_ids``/``exclude_ids`` if present), a JSONL/JSON/CSV
    of records (every record excluded; its repo is excluded too, which keeps the
    gold set repository-disjoint from training), or a text file with one id per
    line.
    """
    ids: set[str] = set()
    repos: set[str] = set()
    hashes: set[str] = set()
    for p in paths:
        path = Path(p)
        text = path.read_text(encoding="utf-8")
        low = str(path).lower()
        if low.endswith(".json"):
            data = json.loads(text)
            if isinstance(data, dict) and ("train_ids" in data or "exclude_ids" in data):
                for k in ("train_ids", "dev_ids", "exclude_ids"):
                    ids.update(str(x) for x in data.get(k, []))
                continue
            recs = data if isinstance(data, list) else data.get("records", [])
        elif low.endswith((".jsonl", ".ndjson")):
            recs = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
        elif low.endswith(".csv"):
            recs = list(csv.DictReader(io.StringIO(text)))
        else:
            ids.update(ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#"))
            continue
        for r in recs:
            for k in ("pr_id", "id"):
                if r.get(k) not in (None, ""):
                    ids.add(str(r[k]))
            repo = _repo_of(r)
            n = _first(r, "number", "pr_number")
            if repo:
                repos.add(repo.lower())
                if n is not None and str(n).isdigit():
                    ids.add(gl.pr_id_for(repo, int(n)))
            if r.get("content_hash"):
                hashes.add(str(r["content_hash"]))
    return ids, repos, hashes


# --------------------------------------------------------------------------
# Sampling
# --------------------------------------------------------------------------


def _key(seed: int, *parts: str) -> int:
    return int(hashlib.sha256((str(seed) + ":" + ":".join(parts)).encode()).hexdigest()[:16], 16)


def allocate(capacity: dict[tuple, int], n: int, seed: int) -> dict[tuple, int]:
    """Water-filling: spread ``n`` evenly over strata, capped by capacity.

    Remainders go to strata in seeded order, so the result is deterministic.
    """
    quota = {s: 0 for s in capacity}
    live = sorted(s for s, c in capacity.items() if c > 0)
    remaining = n
    while remaining > 0 and live:
        share, extra = divmod(remaining, len(live))
        order = sorted(live, key=lambda s: _key(seed, "alloc", *map(str, s)))
        extras = set(order[:extra])
        progressed = 0
        for s in live:
            want = share + (1 if s in extras else 0)
            give = min(want, capacity[s] - quota[s])
            quota[s] += give
            progressed += give
        remaining -= progressed
        live = [s for s in live if quota[s] < capacity[s]]
        if progressed == 0:
            break
    return quota


def select(cands: list[dict], n: int, seed: int, max_per_repo: int) -> tuple[list[dict], dict]:
    """Pick ``n`` candidates stratified by (richness, author_type), balancing
    language and size margins greedily and capping PRs per repository.
    """
    strata: dict[tuple, list[dict]] = {}
    for c in cands:
        strata.setdefault((c["richness"], c["author_type"]), []).append(c)
    for lst in strata.values():
        lst.sort(key=lambda c: (_key(seed, "order", c["pr_id"]), c["pr_id"]))
    # capacity respects the repo cap approximately (exact repo cap applied while picking)
    capacity = {s: len(lst) for s, lst in strata.items()}
    quota = allocate(capacity, n, seed)
    lang_n: Counter = Counter()
    size_n: Counter = Counter()
    repo_n: Counter = Counter()
    chosen: list[dict] = []
    deficits: dict[tuple, int] = {}
    for s in sorted(strata):
        got = 0
        pool = list(strata[s])
        while got < quota[s] and pool:
            best = min(
                (c for c in pool if repo_n[c["repo"]] < max_per_repo),
                key=lambda c: (lang_n[c["language"]] + size_n[c["size_bucket"]],
                               _key(seed, "pick", c["pr_id"]), c["pr_id"]),
                default=None,
            )
            if best is None:
                break
            pool.remove(best)
            chosen.append(best)
            lang_n[best["language"]] += 1
            size_n[best["size_bucket"]] += 1
            repo_n[best["repo"]] += 1
            got += 1
        if got < quota[s]:
            deficits[s] = quota[s] - got
    # Redistribute deficits from the repo cap to strata with spare candidates.
    if deficits:
        taken = {c["pr_id"] for c in chosen}
        missing = sum(deficits.values())
        spare = [c for s in sorted(strata) for c in strata[s]
                 if c["pr_id"] not in taken and repo_n[c["repo"]] < max_per_repo]
        spare.sort(key=lambda c: (lang_n[c["language"]] + size_n[c["size_bucket"]],
                                  _key(seed, "pick", c["pr_id"]), c["pr_id"]))
        for c in spare:
            if missing == 0:
                break
            if repo_n[c["repo"]] >= max_per_repo:
                continue
            chosen.append(c)
            repo_n[c["repo"]] += 1
            lang_n[c["language"]] += 1
            size_n[c["size_bucket"]] += 1
            missing -= 1
    return chosen, {"quota": {"|".join(s): q for s, q in sorted(quota.items())},
                    "capacity": {"|".join(s): c for s, c in sorted(capacity.items())}}


def assign_roles(chosen: list[dict], n_pilot: int, n_dev: int, n_test: int, seed: int) -> None:
    """Assign whole repositories to pilot / dev / test (in place, key ``role``).

    Repositories are visited in seeded order and given to the role with the
    largest remaining relative deficit, so no repository spans two roles
    (PREREGISTRATION 5.3: split by repository).
    """
    targets = {"test": n_test, "dev": n_dev, "pilot": n_pilot}
    got = {r: 0 for r in targets}
    by_repo: dict[str, list[dict]] = {}
    for c in chosen:
        by_repo.setdefault(c["repo"], []).append(c)
    repos = sorted(by_repo, key=lambda r: (_key(seed, "repo", r), r))
    # big repos first so they fit; ties by seeded order
    repos.sort(key=lambda r: -len(by_repo[r]))
    for repo in repos:
        k = len(by_repo[repo])
        role = max(
            targets,
            key=lambda r: (targets[r] - got[r], -list(targets).index(r)),
        )
        for c in by_repo[repo]:
            c["role"] = role
        got[role] += k
    pilot = sorted((c for c in chosen if c["role"] == "pilot"),
                   key=lambda c: (_key(seed, "calib", c["pr_id"]), c["pr_id"]))
    calib = {c["pr_id"] for c in pilot[:10]}
    for c in chosen:
        c["calibration"] = c["pr_id"] in calib


def kappa_halfwidth(n_items: float, po: float = 0.85, pe: float = 0.5) -> float:
    """PREREGISTRATION 5.5 approximation: 1.96 * sqrt(po (1 - po) / (n (1 - pe)^2))."""
    return 1.96 * math.sqrt(po * (1 - po) / (n_items * (1 - pe) ** 2))


def power_check(chosen: list[dict], criteria_per_pr: float, *, n_test_target: int) -> dict:
    test = [c for c in chosen if c["role"] == "test"]
    exp_criteria = len(test) * criteria_per_pr
    need_prs = math.ceil(REQUIRED_CRITERIA / criteria_per_pr)
    shortfalls: list[str] = []
    if len(test) < REQUIRED_TEST_PRS:
        shortfalls.append(f"test PRs {len(test)} < {REQUIRED_TEST_PRS} required")
    if exp_criteria < REQUIRED_CRITERIA:
        shortfalls.append(
            f"expected criteria {exp_criteria:.0f} < {REQUIRED_CRITERIA} "
            f"(need >= {need_prs} test PRs at {criteria_per_pr} criteria per PR)"
        )
    counts = Counter((c["richness"], c["author_type"]) for c in test)
    for s in sorted({(c["richness"], c["author_type"]) for c in chosen}):
        if counts[s] < MIN_STRATUM_TEST:
            shortfalls.append(f"stratum {s[0]}|{s[1]} has {counts[s]} test PRs (< {MIN_STRATUM_TEST})")
    for rich in RICHNESS:
        for at in ("agent", "human"):
            if counts[(rich, at)] == 0 and (rich, at) not in {(c["richness"], c["author_type"]) for c in chosen}:
                shortfalls.append(f"stratum {rich}|{at} is empty")
    repos_test = {c["repo"] for c in test}
    repos_other = {c["repo"] for c in chosen if c["role"] != "test"}
    return {
        "source": "PREREGISTRATION.md section 5.5",
        "assumed_criteria_per_pr": criteria_per_pr,
        "n_test_prs": len(test),
        "n_test_target": n_test_target,
        "required_test_prs": REQUIRED_TEST_PRS,
        "expected_criteria": exp_criteria,
        "required_criteria": REQUIRED_CRITERIA,
        "required_test_prs_at_assumed_rate": need_prs,
        "expected_kappa_items": round(exp_criteria * 1.25),
        "kappa_halfwidth_approx": (
            kappa_halfwidth(exp_criteria * 1.25) if exp_criteria > 0 else None
        ),
        "kappa_assumptions": "po 0.85, pe 0.5, items = 1.25 x criteria (prereg ratio 600/480)",
        "test_repos": len(repos_test),
        "repo_overlap_test_vs_other_roles": sorted(repos_test & repos_other),
        "shortfalls": shortfalls,
        "ok": not shortfalls,
    }


def sample(
    records: list[dict],
    *,
    seed: int = DEFAULT_SEED,
    n_pilot: int = 30,
    n_dev: int = 30,
    n_test: int = 130,
    max_per_repo: int = 4,
    criteria_per_pr: float = 4.0,
    exclude_ids: set[str] | None = None,
    exclude_repos: set[str] | None = None,
    exclude_hashes: set[str] | None = None,
    input_sha256: str = "",
    dataset_manifest: dict | None = None,
) -> dict:
    exclude_ids = exclude_ids or set()
    exclude_repos = {r.lower() for r in (exclude_repos or set())}
    exclude_hashes = exclude_hashes or set()
    rejected: Counter = Counter()
    cands: list[dict] = []
    seen_ids: set[str] = set()
    for rec in records:
        c, why = normalize_candidate(rec)
        if c is None:
            rejected[why] += 1
            continue
        if c["pr_id"] in seen_ids:
            rejected["duplicate_id"] += 1
            continue
        seen_ids.add(c["pr_id"])
        if c["pr_id"] in exclude_ids or c["source_id"] in exclude_ids:
            rejected["excluded_id_train_or_dev"] += 1
            continue
        if c["repo"].lower() in exclude_repos:
            rejected["excluded_repo_of_train_or_dev"] += 1
            continue
        cands.append(c)
    ds = _load_datasets_module()
    kept, dropped = ds.dedupe(
        [{"id": c["pr_id"], "repo": c["repo"], "title": c["title"], "body": c["body"]} for c in cands],
        ["repo", "title", "body"],
    )
    kept_ids = {r["id"] for r in kept}
    for r in kept:
        if r["content_hash"] in exclude_hashes:
            kept_ids.discard(r["id"])
            rejected["excluded_content_hash"] += 1
    rejected["duplicate_content"] += len(dropped)
    cands = [c for c in cands if c["pr_id"] in kept_ids]

    n_total = n_pilot + n_dev + n_test
    chosen, alloc = select(cands, n_total, seed, max_per_repo)
    chosen.sort(key=lambda c: c["pr_id"])
    assign_roles(chosen, n_pilot, n_dev, n_test, seed)

    def counts(items, key):
        return dict(sorted(Counter(key(c) for c in items).items()))

    def strat(c):
        return f"{c['richness']}|{c['author_type']}"

    warnings = []
    if len(chosen) < n_total:
        warnings.append(f"selected {len(chosen)} of {n_total} requested (not enough eligible candidates)")
    unknown_license = sum(1 for c in chosen if c["license"] == "UNKNOWN")
    if unknown_license:
        warnings.append(
            f"{unknown_license} selected PR(s) have an unknown repository licence; store references "
            "and hashes only and do not redistribute their text (DATA_HYGIENE section 2)"
        )
    out_items = [
        {
            "pr_id": c["pr_id"],
            "repo": c["repo"],
            "number": c["number"],
            "url": c["url"],
            "role": c["role"],
            "calibration": c["calibration"],
            "author_type": c["author_type"],
            "agent_name": c["agent_name"],
            "language": c["language"],
            "size_bucket": c["size_bucket"],
            "richness": c["richness"],
            "created_at": c["created_at"],
            "license": c["license"],
        }
        for c in chosen
    ]
    return {
        "schema_version": SAMPLE_SCHEMA,
        "seed": seed,
        "params": {
            "n_pilot": n_pilot, "n_dev": n_dev, "n_test": n_test,
            "max_per_repo": max_per_repo, "criteria_per_pr": criteria_per_pr,
            "stratify": "richness x author_type; language and size_bucket balanced greedily",
        },
        "input": {
            "sha256": input_sha256,
            "n_records": len(records),
            "n_eligible": len(cands),
            "rejected": dict(sorted(rejected.items())),
        },
        "exclusions": {
            "n_ids": len(exclude_ids), "n_repos": len(exclude_repos),
            "n_content_hashes": len(exclude_hashes),
            "rule": "DATA_HYGIENE section 3: nothing from training/dev splits; repos of "
                    "excluded records are excluded too when records (not only ids) were given",
        },
        "dataset_manifest": dataset_manifest,
        "allocation": alloc,
        "strata_counts": {
            "eligible": counts(cands, strat),
            "selected": counts(chosen, strat),
            "selected_by_role": {
                r: counts([c for c in chosen if c["role"] == r], strat)
                for r in ("pilot", "dev", "test")
            },
            "language": counts(chosen, lambda c: c["language"]),
            "size_bucket": counts(chosen, lambda c: c["size_bucket"]),
            "author_type": counts(chosen, lambda c: c["author_type"]),
            "role": counts(chosen, lambda c: c["role"]),
        },
        "power_check": power_check(chosen, criteria_per_pr, n_test_target=n_test),
        "warnings": warnings,
        "prs": out_items,
    }


# --------------------------------------------------------------------------
# fetch-sources (GitHub REST; injectable fetcher; never prints the token)
# --------------------------------------------------------------------------


class RateLimitExceeded(RuntimeError):
    pass


class FetchError(RuntimeError):
    pass


def urllib_fetcher(url: str, headers: dict) -> tuple[int, dict, bytes]:
    """Default transport. Returns ``(status, lowercase headers, body)``."""
    if not url.startswith("https://api.github.com/"):
        raise FetchError("refusing to fetch a non-GitHub-API URL")
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (host checked)
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()


class GithubClient:
    """Tiny REST client: rate-limit aware, retrying, token never exposed."""

    API = "https://api.github.com"

    def __init__(self, fetcher=None, token: str | None = None, *, sleeper=time.sleep,
                 clock=time.time, reserve: int = 5, max_wait: float = 1200, retries: int = 3):
        self._fetch = fetcher or urllib_fetcher
        self._token = token
        self._sleep = sleeper
        self._clock = clock
        self.reserve = reserve
        self.max_wait = max_wait
        self.retries = retries
        self.requests = 0
        self.waited = 0.0

    def __repr__(self) -> str:  # never leak the token
        return f"GithubClient(authenticated={bool(self._token)}, requests={self.requests})"

    def _headers(self) -> dict:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "radius-gold-kit",
        }
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _wait_for_reset(self, headers: dict) -> None:
        reset = headers.get("x-ratelimit-reset")
        retry_after = headers.get("retry-after")
        if retry_after and str(retry_after).isdigit():
            wait = float(retry_after)
        elif reset and str(reset).isdigit():
            wait = max(0.0, float(reset) - self._clock()) + 1.0
        else:
            wait = 60.0
        if wait > self.max_wait:
            raise RateLimitExceeded(f"rate limit resets in {wait:.0f}s (> max_wait {self.max_wait:.0f}s)")
        self.waited += wait
        self._sleep(wait)

    def get(self, path: str, params: dict | None = None):
        """GET ``path``; returns ``(status, parsed_json_or_None, headers)``. 404 is returned."""
        url = self.API + path
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        attempt = 0
        while True:
            self.requests += 1
            try:
                status, headers, body = self._fetch(url, self._headers())
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                attempt += 1
                if attempt > self.retries:
                    raise FetchError(f"network error after {self.retries} retries: {type(exc).__name__}") from None
                self._sleep(2 ** attempt)
                continue
            remaining = headers.get("x-ratelimit-remaining")
            limited = status in (403, 429) and (
                remaining == "0" or "retry-after" in headers or status == 429
            )
            if limited:
                attempt += 1
                if attempt > self.retries + 2:
                    raise RateLimitExceeded("still rate limited after waiting")
                self._wait_for_reset(headers)
                continue
            if status >= 500:
                attempt += 1
                if attempt > self.retries:
                    raise FetchError(f"GitHub server error {status} for {path}")
                self._sleep(2 ** attempt)
                continue
            if remaining is not None and remaining.isdigit() and int(remaining) <= self.reserve:
                # proactive: pause until reset before the next call
                self._wait_for_reset(headers)
            if status == 404:
                return 404, None, headers
            if status >= 400:
                raise FetchError(f"GitHub API error {status} for {path}")
            try:
                data = json.loads(body.decode("utf-8")) if body else None
            except ValueError:
                raise FetchError(f"invalid JSON from {path}") from None
            return status, data, headers

    def get_paged(self, path: str, *, per_page: int = 100, max_items: int = 300) -> list:
        items: list = []
        page = 1
        while len(items) < max_items:
            _s, data, _h = self.get(path, {"per_page": per_page, "page": page})
            if not data:
                break
            items.extend(data)
            if len(data) < per_page:
                break
            page += 1
        return items[:max_items]


_ISSUE_REF = re.compile(
    r"(?:(?P<repo>[\w.-]+/[\w.-]+)#(?P<n1>\d+))"
    r"|(?:https?://github\.com/(?P<repo2>[\w.-]+/[\w.-]+)/issues/(?P<n2>\d+))"
    r"|(?<![\w/&])#(?P<n3>\d+)\b"
)


def find_issue_refs(text: str, default_repo: str, limit: int = 5) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for m in _ISSUE_REF.finditer(text or ""):
        repo = m.group("repo") or m.group("repo2") or default_repo
        n = int(m.group("n1") or m.group("n2") or m.group("n3"))
        if (repo, n) not in out:
            out.append((repo, n))
        if len(out) >= limit:
            break
    return out


def _utc(clock=None) -> str:
    ts = clock() if clock else time.time()
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def fetch_pr_sources(client: GithubClient, item: dict, *, now: str, synthetic: bool = False) -> dict:
    """Snapshot one PR's intent sources into a ``sources.json`` document."""
    repo, number = item["repo"], item["number"]
    st, pull, _ = client.get(f"/repos/{repo}/pulls/{number}")
    if st == 404 or not isinstance(pull, dict):
        raise FetchError(f"PR not found: {repo}#{number}")
    sources: list[dict] = []
    flags_union = {"sanitizer": None}

    def add(source_id: str, kind: str, raw: str, url: str):
        text, sanitizer, flags = gl.sanitize_for_gold(raw, source_id=source_id, kind=kind)
        flags_union["sanitizer"] = sanitizer
        if not text.strip():
            return
        sources.append(gl.make_source(
            source_id, kind, raw, text=text, fetched_at=now, origin_url=url,
            truncated=flags["truncated"], suspicious_content_removed=flags["suspicious_content_removed"],
        ))

    pr_url = pull.get("html_url") or item["url"]
    add("pr-title", "pr_title", pull.get("title") or "", pr_url)
    add("pr-body", "pr_body", pull.get("body") or "", pr_url)
    for irepo, n in find_issue_refs(f"{pull.get('title') or ''}\n{pull.get('body') or ''}", repo):
        s2, issue, _ = client.get(f"/repos/{irepo}/issues/{n}")
        if s2 == 404 or not isinstance(issue, dict) or "pull_request" in issue:
            continue
        sid = f"issue-{n}" if irepo == repo else f"issue-{irepo.replace('/', '__')}-{n}"
        add(sid, "issue", f"{issue.get('title') or ''}\n\n{issue.get('body') or ''}".strip(),
            issue.get("html_url") or f"https://github.com/{irepo}/issues/{n}")
    for cm in client.get_paged(f"/repos/{repo}/pulls/{number}/commits"):
        msg = ((cm.get("commit") or {}).get("message")) or ""
        sha = str(cm.get("sha") or "")[:12]
        if not sha or msg.startswith("Merge ") or not msg.strip():
            continue
        add(f"commit-{sha}", "commit_message", msg, cm.get("html_url") or "")
    head_sha = ((pull.get("head") or {}).get("sha")) or ""
    if head_sha:
        s3, spec, _ = client.get(f"/repos/{repo}/contents/.radius/intent.yml", {"ref": head_sha})
        if s3 == 200 and isinstance(spec, dict) and spec.get("encoding") == "base64":
            raw = base64.b64decode(spec.get("content", "")).decode("utf-8", "replace")
            add("spec-radius-intent-yml", "spec_file", raw, spec.get("html_url") or "")
    if not sources:
        raise FetchError(f"no usable text sources for {repo}#{number}")
    login = ((pull.get("user") or {}).get("login")) or ""
    return {
        "schema_version": gl.SOURCES_SCHEMA_VERSION,
        "pr_id": item["pr_id"],
        "pr": {
            "repo": repo,
            "number": number,
            "url": pr_url,
            "author_type": item["author_type"],
            "agent_name": item.get("agent_name"),
            "author_login_sha256": gl.login_hash(login) if login else gl.sha256_text("unknown"),
            "language": item["language"],
            "size": {"bucket": item["size_bucket"]},
            "stratum": {"richness": item["richness"], "author_type": item["author_type"]},
            "role": item["role"],
            "created_at": pull.get("created_at") or item.get("created_at") or "",
            "license": item.get("license", "UNKNOWN"),
        },
        "sources": sources,
        "sources_digest": gl.sources_digest(sources),
        "sanitizer": flags_union["sanitizer"] or "canonicalize_text",
        "text_redistributable": False,
        "synthetic": synthetic,
    }


def fetch_sources(
    sample_doc: dict,
    gold_dir: Path,
    client: GithubClient,
    *,
    roles: set[str] | None = None,
    refresh: bool = False,
    now: str | None = None,
    synthetic: bool = False,
    log=print,
) -> dict:
    """Write ``<gold_dir>/<pr-id>/sources.json`` for each sampled PR (idempotent)."""
    now = now or _utc()
    report = {"written": [], "skipped_existing": [], "changed_upstream": [], "failed": []}
    for item in sample_doc["prs"]:
        if roles and item["role"] not in roles:
            continue
        pid = item["pr_id"]
        path = gl.pr_dir(gold_dir, pid) / "sources.json"
        has_ann = bool(list(gl.pr_dir(gold_dir, pid).glob("annotator-*.json"))) or (
            gl.pr_dir(gold_dir, pid) / "adjudicated.json"
        ).exists()
        if path.exists() and not refresh:
            report["skipped_existing"].append(pid)
            continue
        try:
            doc = fetch_pr_sources(client, item, now=now, synthetic=synthetic)
        except (FetchError, KeyError) as exc:
            report["failed"].append({"pr_id": pid, "error": str(exc)})
            log(f"FAILED {pid}: {exc}")
            continue
        if path.exists():
            old = gl.read_json(path)
            if old["sources_digest"] == doc["sources_digest"]:
                report["skipped_existing"].append(pid)
                continue
            if has_ann:
                report["changed_upstream"].append(pid)
                log(f"WARNING {pid}: upstream text changed but annotations exist; not overwritten")
                continue
        gl.write_json_atomic(path, doc)
        report["written"].append(pid)
        log(f"wrote {pid} ({len(doc['sources'])} sources, {client.requests} requests so far)")
    return report


def make_queue(sample_doc: dict, annotator_id: str, roles: list[str] | None = None) -> list[str]:
    """Annotation order for one annotator: roles in the given order (default pilot,
    dev, test; calibration PRs first), shuffled within each group by a seed that
    depends on the sample seed and the annotator id, so the two annotators see
    different orders (controls order and fatigue effects).
    """
    gl.check_annotator_id(annotator_id)
    roles = roles or ["pilot", "dev", "test"]
    out: list[str] = []
    for role in roles:
        group = [p for p in sample_doc["prs"] if p["role"] == role]
        calib = sorted((p for p in group if p.get("calibration")), key=lambda p: p["pr_id"])
        rest = [p for p in group if not p.get("calibration")]
        rest.sort(key=lambda p: (_key(sample_doc["seed"], "queue", annotator_id, p["pr_id"]), p["pr_id"]))
        out += [p["pr_id"] for p in calib] + [p["pr_id"] for p in rest]
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None, *, fetcher=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--input", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--seed", type=int, default=DEFAULT_SEED)
    s.add_argument("--n-pilot", type=int, default=30)
    s.add_argument("--n-dev", type=int, default=30)
    s.add_argument("--n-test", type=int, default=130)
    s.add_argument("--max-per-repo", type=int, default=4)
    s.add_argument("--criteria-per-pr", type=float, default=4.0)
    s.add_argument("--exclude", action="append", default=[])
    s.add_argument("--dataset-manifest", help="manifest id in benchmarks/datasets/manifests")
    f = sub.add_parser("fetch-sources")
    f.add_argument("--sample", required=True)
    f.add_argument("--gold-dir", default=str(gl.GOLD_DIR))
    f.add_argument("--yes", action="store_true", help="required: this contacts api.github.com")
    f.add_argument("--token-env", default="GITHUB_TOKEN")
    f.add_argument("--role", action="append", choices=["pilot", "dev", "test"])
    f.add_argument("--refresh", action="store_true")
    f.add_argument("--max-wait", type=float, default=1200)
    q = sub.add_parser("queue")
    q.add_argument("--sample", required=True)
    q.add_argument("--annotator", required=True)
    q.add_argument("--out", required=True)
    q.add_argument("--role", action="append", choices=["pilot", "dev", "test"])
    args = ap.parse_args(argv)

    if args.cmd == "queue":
        ids = make_queue(gl.read_json(Path(args.sample)), args.annotator, args.role)
        Path(args.out).write_text("\n".join(ids) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {len(ids)} PR ids to {args.out}")
        return 0

    if args.cmd == "sample":
        inp = Path(args.input)
        raw = inp.read_bytes()
        records = read_candidates(inp)
        ids, repos, hashes = load_exclusions(args.exclude)
        manifest_info = None
        if args.dataset_manifest:
            ds = _load_datasets_module()
            found = [m for m in ds.load_manifests() if m["id"] == args.dataset_manifest]
            if not found:
                print(f"error: no manifest {args.dataset_manifest!r}", file=sys.stderr)
                return 2
            m = found[0]
            manifest_info = {
                "id": m["id"], "revision": m["source"].get("revision"),
                "license": m["license"]["name"], "redistribution": m["redistribution"]["allowed"],
            }
        doc = sample(
            records, seed=args.seed, n_pilot=args.n_pilot, n_dev=args.n_dev, n_test=args.n_test,
            max_per_repo=args.max_per_repo, criteria_per_pr=args.criteria_per_pr,
            exclude_ids=ids, exclude_repos=repos, exclude_hashes=hashes,
            input_sha256=hashlib.sha256(raw).hexdigest(), dataset_manifest=manifest_info,
        )
        gl.write_json_atomic(Path(args.out), doc)
        pc = doc["power_check"]
        print(f"selected {len(doc['prs'])} PRs; test {pc['n_test_prs']}; "
              f"expected criteria {pc['expected_criteria']:.0f}/{pc['required_criteria']}")
        for w in doc["warnings"] + pc["shortfalls"]:
            print(f"WARNING: {w}")
        return 0 if pc["ok"] else 1

    if not args.yes:
        print("error: fetch-sources contacts api.github.com; pass --yes to proceed", file=sys.stderr)
        return 2
    token = os.environ.get(args.token_env) or os.environ.get("GH_TOKEN")
    if not token:
        print(f"warning: no token in ${args.token_env}; unauthenticated limit is 60 requests/hour",
              file=sys.stderr)
    client = GithubClient(fetcher, token, max_wait=args.max_wait)
    doc = gl.read_json(Path(args.sample))
    try:
        rep = fetch_sources(doc, Path(args.gold_dir), client,
                            roles=set(args.role) if args.role else None, refresh=args.refresh)
    except RateLimitExceeded as exc:
        print(f"stopped: {exc}; rerun later (completed PRs are kept)", file=sys.stderr)
        return 3
    print(json.dumps({k: len(v) for k, v in rep.items()}))
    return 0 if not rep["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
