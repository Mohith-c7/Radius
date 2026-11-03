#!/usr/bin/env python
"""Machine-check what can be checked before the pre-registration freeze (EP-02).

    python scripts/prereg_check.py [--root DIR] [--json] [--informational] [--only PREFIX]

Prints one line per item of ``docs/research/preregistration/FREEZE_CHECKLIST.md``:

* ``PASS``   the machine-checkable condition holds;
* ``FAIL``   a machine-checkable condition required before the freeze does not hold;
* ``MANUAL`` a human (usually the owner) must decide or attest; the line says what
  was found so the decision is informed.

Exit status: 1 if any item is ``FAIL`` (this is the "not ready to freeze" signal and
is the expected outcome today), else 0; ``--informational`` always exits 0.

This script **never freezes anything**, never edits any file, and a ``PASS`` never means
a result is good; it means a stated precondition is met. It does not call the network.
Absence checks are grep-based ("token not found in scripts/ and packages/*/src") and
say exactly what they looked for; a miss there can be a naming difference, which is why
the detail names the tokens.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
CHECKOUT = SCRIPTS.parent
for _p in (SCRIPTS, CHECKOUT / "packages" / "shared" / "src", CHECKOUT / "packages" / "confidence" / "src", CHECKOUT / "packages" / "evidence" / "src",
           CHECKOUT / "packages" / "testing" / "src", CHECKOUT / "packages" / "analysis" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import gold_lib as gl  # noqa: E402

PASS, FAIL, MANUAL = "PASS", "FAIL", "MANUAL"
MASTER_SEED = "20261102"
PREREG = "docs/research/preregistration/PREREGISTRATION.md"
PREREG_CHANGELOG = "docs/research/preregistration/CHANGELOG.md"
FREEZE_BLOCK = re.compile(r"<!-- FREEZE-BLOCK-START -->.*?<!-- FREEZE-BLOCK-END -->\n?", re.S)


@dataclass
class Result:
    id: str
    status: str
    owner: str
    title: str
    detail: str

    def to_dict(self) -> dict:
        return {"id": self.id, "status": self.status, "owner": self.owner,
                "title": self.title, "detail": self.detail}


CHECKS: list[tuple[str, str, str, Callable[[Path], tuple[str, str]]]] = []


def check(cid: str, owner: str, title: str):
    def deco(fn):
        CHECKS.append((cid, owner, title, fn))
        return fn
    return deco


# ------------------------------------------------------------------ helpers


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")


def _exists(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def _grep_tree(root: Path, tokens: list[str], dirs: tuple[str, ...] = ("scripts", "packages")) -> dict[str, list[str]]:
    """token -> relative paths of non-test .py files (scripts/ and packages/*/src) that contain it."""
    found: dict[str, list[str]] = {t: [] for t in tokens}
    for d in dirs:
        base = root / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            rel = p.relative_to(root).as_posix()
            if "/tests/" in rel or "/test_" in rel or rel.startswith("scripts/prereg_check"):
                continue
            if d == "packages" and "/src/" not in rel:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore").lower()
            for t in tokens:
                if t.lower() in text:
                    found[t].append(rel)
    return found


START_MARK, END_MARK = "<!-- FREEZE-BLOCK-START -->", "<!-- FREEZE-BLOCK-END -->"


def _hash_lines(text: str, *, anchored: bool) -> tuple[str, int]:
    """SHA-256 of the text without the freeze block, and the number of lines dropped.

    ``anchored=False`` emulates the documented command
    ``sed '/<!-- FREEZE-BLOCK-START -->/,/<!-- FREEZE-BLOCK-END -->/d'`` exactly: a range
    opens at ANY line containing the start marker and closes at the next line containing the
    end marker (or at end of file). ``anchored=True`` only opens at a line that consists of the
    start marker alone.
    """

    kept, dropped, in_range = [], 0, False
    norm = text.replace("\r", "")
    rows = norm.split("\n")
    if norm.endswith("\n"):
        rows = rows[:-1]
    for line in rows:
        if not in_range:
            opens = line.strip() == START_MARK if anchored else START_MARK in line
            if opens:
                in_range, dropped = True, dropped + 1
                continue
            kept.append(line)
        else:
            dropped += 1
            if (line.strip() == END_MARK) if anchored else (END_MARK in line):
                in_range = False
    return hashlib.sha256(("\n".join(kept) + "\n").encode("utf-8")).hexdigest(), dropped
def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                             timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def _real_gold(root: Path):
    """Return (gold_dir, [(pr_id, sources, annotations, adjudicated)]) for non-synthetic PRs."""
    gdir = root / "benchmarks" / "gold" / "intent"
    prs = []
    for pid in gl.list_pr_ids(gdir):
        src, anns, adj = gl.load_pr(gdir, pid)
        if not src.get("synthetic"):
            prs.append((pid, src, anns, adj))
    return gdir, prs


# ------------------------------------------------------------- A: the document


@check("A1.prereg_file_and_freeze_block", "agent", "Pre-registration file has a parseable freeze block")
def _a1(root):
    t = _read(root, PREREG)
    m = re.search(r"\*\*Freeze status: ([^*]+)\*\*", t)
    if "<!-- FREEZE-BLOCK-START -->" not in t or not m:
        return FAIL, "freeze block markers or status line missing"
    return PASS, f"status line: {m.group(1).strip()}"


@check("A2.prereg_hash_current", "agent", "Recorded content hash equals the recomputed canonical hash")
def _a2(root):
    t = _read(root, PREREG)
    block = FREEZE_BLOCK.search(t)
    recorded = re.findall(r"`([0-9a-f]{64})`", block.group(0) if block else "")
    actual, _dropped = _hash_lines(t, anchored=False)
    if not recorded:
        return FAIL, f"no hash in the freeze block; recomputed {actual}"
    if recorded[-1] != actual:
        return FAIL, f"recorded {recorded[-1]} but the documented procedure gives {actual} (document edited after the hash)"
    frozen = "Freeze status: FROZEN" in t
    return PASS, f"hash {actual} matches the documented procedure" + ("" if frozen else " (a DRAFT tracking hash, not a freeze hash)")


@check("A2b.hash_procedure_covers_document", "owner", "The documented hash procedure excludes only the freeze block")
def _a2b(root):
    t = _read(root, PREREG)
    h_doc, dropped_doc = _hash_lines(t, anchored=False)
    h_anch, dropped_anch = _hash_lines(t, anchored=True)
    if dropped_doc != dropped_anch:
        total = len(t.split("\n"))
        return FAIL, (f"the documented sed command drops {dropped_doc} lines but the freeze block is {dropped_anch}: a line outside the "
                      f"block contains the start marker (the command printed in the document itself), so everything from there to the end "
                      f"of the file ({dropped_doc - dropped_anch} lines of {total}) is excluded from the hash and can change without changing it. "
                      f"With anchored patterns the hash would be {h_anch}. Fix the procedure (anchor the patterns) before the freeze; "
                      f"the change alters the hash, which is acceptable only before the freeze")
    return PASS, f"the freeze block ({dropped_anch} lines) is the only excluded part"


@check("A3.no_placeholder_phrases", "agent", "Known open placeholders in the pre-registration are resolved")
def _a3(root):
    t = _read(root, PREREG)
    phrases = ["Reconcile the two files before freeze", "count to be read from the manifest",
               "is therefore blank in v0.2"]
    open_ = [p for p in phrases if p in t]
    if open_:
        return FAIL, "still present: " + "; ".join(repr(p) for p in open_)
    return PASS, "none of the tracked placeholder phrases remain (the list is not exhaustive)"


@check("A4.pilots_listed", "owner", "Pre-freeze pilots are listed in the pre-registration changelog")
def _a4(root):
    t = _read(root, PREREG_CHANGELOG)
    m = re.search(r"## 4\. Pre-freeze pilots\n(.*?)(?=\n## )", t, re.S)
    if not m:
        return FAIL, "section 4 not found"
    if "None yet" in m.group(1) or "None recorded" in m.group(1):
        return FAIL, "section 4 records no pilot; PREREGISTRATION 17.3 requires a timing pilot on 100 dev patches"
    return MANUAL, "section 4 has entries; owner confirms they are complete"


@check("A5.tuning_closed_logged", "owner", "A 'tuning closed' entry exists (commit, algo_version, manifest hash)")
def _a5(root):
    t = _read(root, PREREG_CHANGELOG)
    m = re.search(r"## 5\. Tuning-closed log\n(.*?)(?=\n## )", t, re.S)
    if not m:
        return FAIL, "section 5 not found"
    if "None yet" in m.group(1):
        return FAIL, "section 5 says 'None yet'"
    return MANUAL, "section 5 has entries; owner confirms commit, algo_version and manifest hash are present"


# ------------------------------------------------------------------ B: data


@check("B1.dataset_manifests_valid", "agent", "All dataset manifests validate against their schema")
def _b1(root):
    spec = importlib.util.spec_from_file_location("radius_datasets_script", root / "scripts" / "datasets.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["radius_datasets_script"] = mod
    spec.loader.exec_module(mod)
    manifests = mod.load_manifests(root / "benchmarks" / "datasets" / "manifests")
    bad = {m.get("id", "?"): mod.validate_manifest(m)[:1] for m in manifests if mod.validate_manifest(m)}
    if bad:
        return FAIL, f"{len(bad)} invalid: {bad}"
    return PASS, f"{len(manifests)} manifests valid (hashes of downloaded files are not verified here; run scripts/datasets.py verify)"


@check("B2.label_and_patch_sources_pinned", "owner", "Primary label and patch sources are pinned (revision, sha256)")
def _b2(root):
    problems = []
    for mid in ("swe-bench-verified", "swe-abs-verified", "swe-bench-experiments"):
        p = root / "benchmarks" / "datasets" / "manifests" / f"{mid}.json"
        if not p.exists():
            problems.append(f"{mid}: manifest missing")
            continue
        m = json.loads(p.read_text(encoding="utf-8"))
        files = m.get("files") or []
        if not files or not all(f.get("sha256") for f in files):
            problems.append(f"{mid}: no pinned files with sha256")
    if problems:
        return FAIL, "; ".join(problems)
    return PASS, "swe-bench-verified, swe-abs-verified and swe-bench-experiments have sha256-pinned files"


@check("B3.secondary_label_sources", "owner", "Secondary label sources (UTBoost, PatchDiff, ...) obtained or declared unavailable")
def _b3(root):
    states = {}
    for mid in ("utboost", "patchdiff", "swe-bench-plus", "swe-mutation"):
        p = root / "benchmarks" / "datasets" / "manifests" / f"{mid}.json"
        if p.exists():
            states[mid] = json.loads(p.read_text(encoding="utf-8")).get("status")
    return MANUAL, f"manifest status: {states}; owner sends author requests or declares them unavailable (datasets/AUTHOR_REQUESTS.md)"


@check("B4.split_tool_matches_rule", "agent", "Split tool implements the pre-registered rule (2.2: 40/60 time split, 60/40 fit/calibration in dev)")
def _b4(root):
    src = _read(root, "scripts/datasets.py")
    m = re.search(r'"--test-frac".*?default=([0-9.]+)', src)
    frac = m.group(1) if m else "?"
    has_cal = "calibration" in src.lower()
    seed = re.search(r"DEFAULT_SEED\s*=\s*(\d+)", src)
    probs = []
    if frac != "0.6":
        probs.append(f"--test-frac default is {frac}, the rule needs 0.6 (the cut point can be set by flag, so only the default differs)")
    if not has_cal:
        probs.append("no calibration fold: the tool makes a two-way train/test split only")
    if not seed or seed.group(1) != MASTER_SEED:
        probs.append(f"DEFAULT_SEED is {seed.group(1) if seed else 'missing'}, expected {MASTER_SEED}")
    if probs:
        return FAIL, "; ".join(probs)
    return PASS, "defaults and three-way split present"


@check("B5.split_cut_points_recorded", "owner", "Split cut points computed from the manifest and recorded")
def _b5(root):
    cands = list((root / "docs" / "research" / "preregistration").glob("split*")) + \
        list((root / "benchmarks" / "datasets").glob("splits/*"))
    if not cands:
        return FAIL, "no split report found under preregistration/ or benchmarks/datasets/splits/"
    return MANUAL, f"found {[c.name for c in cands]}; owner confirms they came from the frozen manifest hash"


@check("B6.master_seed_consistent", "agent", f"Master seed {MASTER_SEED} is used consistently")
def _b6(root):
    places = [PREREG, "docs/research/datasets/DATA_HYGIENE.md", "scripts/datasets.py", "scripts/gold_sample.py",
              "packages/intent/src/radius_intent/evaluation/config.py"]
    missing = [p for p in places if not _exists(root, p) or MASTER_SEED not in _read(root, p)]
    if missing:
        return FAIL, f"seed not found in: {missing}"
    return PASS, f"found in {len(places)} files"


@check("B7.manifest_facts_remeasured", "owner", "Manifest facts re-measured and the power table (section 12) recomputed")
def _b7(root):
    return MANUAL, "needs the pinned data; PREREGISTRATION section 12 still uses literature numbers"


# --------------------------------------------------------------- C: gold set


@check("C1.gold_schema_and_fixture", "agent", "Gold schema loads and the synthetic fixture validates")
def _c1(root):
    gdir = root / "benchmarks" / "gold" / "intent"
    gl.load_schema(gdir / "schema.json")
    synth = root / "benchmarks" / "gold" / "synthetic"
    errs = []
    ids = gl.list_pr_ids(synth)
    for pid in ids:
        e, _w = gl.validate_pr_dir(synth, pid, require_complete=True, allow_synthetic=True)
        errs += e
    if errs or not ids:
        return FAIL, f"{len(ids)} synthetic PRs; errors: {errs[:2]}"
    return PASS, f"schema loads; {len(ids)} synthetic PRs validate (tooling check only, not data)"


@check("C2.guidelines_revised_after_calibration", "annotators", "Guidelines revised after the calibration round")
def _c2(root):
    t = _read(root, "docs/research/annotation/GUIDELINES.md")
    versions = re.findall(r"^- (gl-[0-9.]+)", t, re.M)
    if len(versions) <= 1:
        return FAIL, f"change log lists only {versions or 'no version'}; no revision after calibration yet"
    return MANUAL, f"change log lists {versions}; owner confirms the last one followed the 10-PR calibration"


@check("C3.gold_set_size", "annotators", "Real adjudicated gold: >= 120 test PRs and >= 30 pilot PRs")
def _c3(root):
    _g, prs = _real_gold(root)
    counts: dict[str, int] = {}
    for _pid, src, _anns, adj in prs:
        if adj and adj.get("status") == "complete":
            role = src["pr"].get("role", "?")
            counts[role] = counts.get(role, 0) + 1
    ok = counts.get("test", 0) >= 120 and counts.get("pilot", 0) >= 30
    detail = f"complete adjudicated real PRs by role: {counts or 'none'} ({len(prs)} real PR directories)"
    return (PASS if ok else FAIL), detail + ("" if ok else "; need test >= 120 and pilot >= 30")


@check("C4.pilot_agreement_gate", "annotators", "Pilot kappa >= 0.60 (presence and testability) on >= 30 real pilot PRs")
def _c4(root):
    import gold_agreement as ga

    gdir, prs = _real_gold(root)
    pilot = [pid for pid, src, anns, _a in prs if src["pr"].get("role") == "pilot" and len(anns) >= 2]
    if not pilot:
        return FAIL, "no real pilot PR with two annotator files"
    comps, _docs, skipped = ga.collect(gdir, pr_ids=pilot)
    rep = ga.build_report(comps, n_boot=200, seed=int(MASTER_SEED))
    pres, test = rep["gate"]["presence_kappa"], rep["gate"]["testability_kappa"]
    ok = len(comps) >= 30 and rep["gate"]["presence_pass"] and rep["gate"]["testability_pass"]
    return (PASS if ok else FAIL), (
        f"{len(comps)} complete pilot PRs ({len(skipped)} skipped); presence kappa {pres}, testability kappa {test}"
    )


@check("C5.annotator_roles_and_consent", "owner", "Annotators A, B and adjudicator C are three people; consent and conflicts recorded")
def _c5(root):
    _g, prs = _real_gold(root)
    ids = sorted({a for _p, _s, anns, _adj in prs for a in anns})
    adj = sorted({adj["adjudicator_id"] for _p, _s, _a, adj in prs if adj and adj.get("adjudicator_id")})
    return MANUAL, (f"annotator ids in real data: {ids or 'none'}; adjudicator ids: {adj or 'none'}; "
                    "written acknowledgements and Radius-developer disclosure are not machine-visible")


# ------------------------------------------------------------- D: baselines

BASELINES: list[tuple[str, str, list[str], str]] = [
    ("B0", "CI pass/fail only", [], "degenerate on test-passing patches (PREREGISTRATION 6.3); list as constant predictor or not run"),
    ("B1", "coverage of changed lines", ["packages/confidence/src/radius_confidence/domain/coverage.py"], "coverage domain code exists; no baseline predictor evaluated"),
    ("B2", "Radius v1 heuristic score", ["packages/confidence/src/radius_confidence/infrastructure/scoring.py"], "scoring exists; not run as a baseline on labelled data"),
    ("B3", "LLM-as-judge on diff + issue", [], ""),
    ("B4", "AgentProof-style criterion mapping", [], ""),
    ("B5", "tamper rules only", ["packages/analysis/src/radius_analysis/tamper"], "rules exist; a rules-only predictor is not built or validated"),
    ("B6", "whole-file mutation score, no linking", ["packages/testing/src/radius_testing/mutation/matrix.py"], "engine exists; the whole-file variant is not implemented"),
    ("B7", "execution-free rubric verifier", [], ""),
    ("B8", "fail-to-pass reproduction-test verifier", [], ""),
    ("B9", "ScopeProof-style static retrieval", ["packages/linking/src"], "own linker exists; not a re-implementation of the baseline"),
    ("B10", "linking baselines (BM25/VSM, T-BERT, LiSSA, alignment classifier)", ["packages/linking/src"], "BM25 is inside the linker; no standalone or neural baselines"),
    ("B11", "calibration baselines (Platt, isotonic, temperature, selective, LTT)", ["packages/confidence/src/radius_confidence/calibration"], "Platt, isotonic, LTT and CRC exist (toolkit, unvalidated on real data); temperature scaling and the selective baseline with a held-out threshold are not implemented"),
    ("B12", "triage baselines (random, by-size, JIT, JITLine, LLM reviewer)", [], ""),
]


def _baseline_check(bid: str, title: str, paths: list[str], note: str):
    @check(f"D.{bid}", "owner", f"Baseline {bid} ({title}) implemented and validated, or listed as not run with a reason")
    def _fn(root):
        present = [p for p in paths if _exists(root, p)]
        if not present:
            return FAIL, "no implementation found" + (f" ({note})" if note else "") + "; implement it or list it as not run with a reason"
        return MANUAL, f"evidence: {present}; {note}. Validation against the baseline's published behaviour is not recorded"
    return _fn


for _b in BASELINES:
    _baseline_check(*_b)


# -------------------------------------------------------------- E: analysis


@check("E1.statistical_procedures", "agent", "Named statistical procedures (2.4) have an implementation")
def _e1(root):
    tokens = ["holm", "benjamini", "clopper", "delong", "mcnemar", "wilcoxon", "bootstrap"]
    found = _grep_tree(root, tokens)
    missing = [t for t in tokens if not found[t]]
    if missing:
        return FAIL, f"tokens not found in scripts/ and packages/*/src: {missing}; present: {[t for t in tokens if found[t]]}"
    return PASS, "all named procedures have a code occurrence (existence, not correctness)"


@check("E2.rq_analysis_scripts", "agent", "An analysis path exists for each RQ (RQ1..RQ6)")
def _e2(root):
    named = {
        "RQ1": ["scripts/intent_eval.py"],
        "RQ3": ["scripts/calibration_report.py"],
    }
    by_name = {"RQ2": ["*rq2*", "*auroc*"], "RQ4": ["*rq4*"], "RQ5": ["*rq5*", "*triage*"], "RQ6": ["*rq6*", "*overhead*"]}
    present = [rq for rq, files in named.items() if all(_exists(root, f) for f in files)]
    missing = [rq for rq in named if rq not in present]
    for rq, globs in by_name.items():
        hits = [p for g in globs for base in ("scripts", "packages") if (root / base).exists()
                for p in (root / base).rglob(g + ".py") if "/tests/" not in p.as_posix()]
        (present if hits else missing).append(rq)
    if missing:
        return FAIL, (f"no analysis script found by file name for {sorted(missing)}; present: {sorted(present)}. "
                      "Present does not mean complete: RQ1 and RQ3 cover only part of their hypotheses (for example no paired "
                      "ECE/Brier cluster-bootstrap differences or repartition test H3c)")
    return MANUAL, f"named scripts exist for {sorted(present)}; owner confirms they cover every confirmatory hypothesis"


@check("E3.harness_provenance_fields", "agent", "Harness records algo_version, seed, commit, dataset and config hashes (RQ1 harness)")
def _e3(root):
    base = root / "packages" / "intent" / "src" / "radius_intent" / "evaluation"
    src = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in sorted(base.glob("*.py")))
    need = ["harness_version", "config_sha256", "dirty", "dataset"]
    miss = [n for n in need if n not in src]
    if miss:
        return FAIL, f"tokens missing in radius_intent/evaluation: {miss}"
    return MANUAL, "RQ1 extraction harness records them; harnesses for RQ2 to RQ6 do not exist yet (see E2)"


@check("E4.feature_provenance_test", "agent", "Feature-provenance test (no gold at inference) exists and passes")
def _e4(root):
    hits = []
    for d in ("tests", "packages"):
        base = root / d
        if base.exists():
            for p in base.rglob("test_*.py"):
                if "provenance" in p.read_text(encoding="utf-8", errors="ignore").lower() and "feature" in p.name.lower():
                    hits.append(p.relative_to(root).as_posix())
    if not hits:
        return FAIL, "no test file named like test_*feature*provenance*.py; PREREGISTRATION 2.2 rule 5 requires one"
    return MANUAL, f"candidate tests: {hits}; owner confirms they cover rule 5 and pass"


@check("E5.conformal_loss_verified", "owner", "Conformal loss formulation checked by the CA-05 implementer (7.1)")
def _e5(root):
    from radius_confidence.calibration import find_nonincreasing_violation, prereg_shifted_loss

    conf, ok, alpha = [0.8, 0.8, 0.3], [1, 0, 0], 0.1
    v = find_nonincreasing_violation(lambda i, t: prereg_shifted_loss(conf[i], ok[i], t, alpha), 3, [0.0, 0.5, 0.9])
    if v:
        return MANUAL, (f"the shifted loss of 7.1 is NOT non-increasing in the threshold (counterexample: {v}); "
                        "see docs/research/evaluation/CALIBRATION_TOOLKIT.md. Owner/implementer must decide the formulation")
    return MANUAL, "no counterexample on the built-in example; verification still needs to be recorded"


@check("E6.ece_floor_recomputed", "owner", "ECE noise floor recomputed with the real dev score distribution (7.5)")
def _e6(root):
    have = _exists(root, "packages/confidence/src/radius_confidence/calibration/metrics.py") and \
        "def ece_noise_floor" in _read(root, "packages/confidence/src/radius_confidence/calibration/metrics.py")
    return MANUAL, ("ece_noise_floor() and calibration_report.py are ready" if have else "tool missing") + \
        "; needs real dev scores, which do not exist yet"


# --------------------------------------------------- F: system under test


@check("F1.verdict_config_digest_recorded", "owner", "Digest of the frozen Verdict v2 config is recorded in the pre-registration")
def _f1(root):
    from radius_evidence.domain.config import VerdictV2Config

    digest = VerdictV2Config().digest()
    if digest in _read(root, PREREG):
        return PASS, f"digest {digest} appears in the pre-registration"
    return FAIL, (f"current default digest is {digest} (profile {VerdictV2Config().profile}); it is not recorded in "
                  "PREREGISTRATION.md. The thresholds were fitted to the 8 F-14 fixtures (KNOWN_LIMITATIONS); "
                  "the frozen configuration comes from dev tuning under rule 2.2.8, not from this default")


@check("F2.thresholds_fitting_data_declared", "owner", "Thresholds frozen with the fitting data declared")
def _f2(root):
    t = _read(root, PREREG)
    declared = "fitted to the 8" in t or "F-14 fixtures were used to set" in t
    if not declared:
        return FAIL, ("PREREGISTRATION does not state that the current defaults (cap_static, tau_support) were fitted to "
                      "the 8 F-14 fixtures (KNOWN_LIMITATIONS); the freeze must declare either that origin or a dev-set refit")
    return MANUAL, "a declaration phrase is present; owner confirms it is accurate"


@check("F3.algo_version_tagged", "owner", "Frozen pipeline algo_version tagged in git")
def _f3(root):
    tags = _git(root, "tag", "--list")
    shown = tags.split() if tags else []
    return MANUAL, f"git tags: {shown[:10] or 'none'}; the owner creates the tag at freeze (not done here)"


@check("F4.operator_set_and_budget_frozen", "owner", "Mutation operator set and budgets are named in the pre-registration and match the code")
def _f4(root):
    try:
        from radius_testing.mutation.budget import MutationBudget
        from radius_testing.mutation.operators import EXPERIMENTAL_OPERATOR_IDS, OPERATOR_IDS
    except ImportError as exc:
        return MANUAL, f"radius_testing not importable here ({exc})"
    b = MutationBudget()
    digest = hashlib.sha256(json.dumps(
        {"operators": list(OPERATOR_IDS), "experimental": list(EXPERIMENTAL_OPERATOR_IDS),
         "max_mutants": b.max_mutants, "wall_clock_seconds": b.wall_clock_seconds,
         "per_mutant_timeout_seconds": b.per_mutant_timeout_seconds}, sort_keys=True).encode()).hexdigest()
    t = _read(root, PREREG)
    probs = []
    if not all(op in t for op in OPERATOR_IDS):
        probs.append("the operator ids are not all named in PREREGISTRATION.md")
    if b.max_mutants != 50:
        probs.append(f"code max_mutants default {b.max_mutants} vs 50 in 17.3")
    if b.wall_clock_seconds != 1200.0:
        probs.append(f"MutationBudget.wall_clock_seconds default is {b.wall_clock_seconds:.0f} s, 17.3(a) states a 20-minute (1200 s) per-patch cap; if that field is the per-patch cap they differ")
    note = f"code digest of (operators, experimental, budget defaults) = {digest}"
    if probs:
        return FAIL, "; ".join(probs) + "; " + note
    return MANUAL, "named and consistent; " + note + "; owner records the digest in the pre-registration"


@check("F5.circularity_protocol_documented", "agent", "Circularity protocol present in MUTATION_EVIDENCE section 12")
def _f5(root):
    t = _read(root, "docs/research/design/MUTATION_EVIDENCE.md")
    if "## 12. Circularity" not in t:
        return FAIL, "section 12 heading not found"
    n = len(re.findall(r"^\d+\. \*\*", t.split("## 12. Circularity", 1)[1].split("## 13.", 1)[0], re.M))
    return PASS, f"section 12 present with {n} numbered protocol steps"


@check("F6.circularity_protocol_in_prereg", "owner", "Pre-registration references and freezes the circularity protocol")
def _f6(root):
    t = _read(root, PREREG)
    if "MUTATION_EVIDENCE" not in t and "held-out mutants" not in t.lower():
        return FAIL, ("PREREGISTRATION.md does not reference MUTATION_EVIDENCE section 12 or the held-out-mutant control; "
                      "the protocol is 'to be frozen with the pre-registration' but is not yet part of it")
    return MANUAL, "referenced; owner confirms the protocol text is frozen with it"


@check("F7.circularity_controls_implemented", "agent", "Circularity controls exist in code (held-out mutant split, input-manifest check, overlap measurement)")
def _f7(root):
    controls = {
        "held-out mutant split": ["held_out", "heldout", "held-out"],
        "input manifest / label-store rejection": ["label_store", "input_manifest", "inputs_manifest"],
        "site-overlap measurement": ["site_overlap", "overlap_rate"],
    }
    missing = []
    for name, toks in controls.items():
        found = _grep_tree(root, toks, dirs=("packages",))
        if not any(found.values()):
            missing.append(name)
    if missing:
        return FAIL, f"no code occurrence of tokens for: {missing}"
    return MANUAL, "token matches exist for all controls; owner reviews that they implement section 12"


# ----------------------------------------------------- G: fixtures, owner acts


@check("G1.f14_fixtures_complete", "agent", "The 8 F-14 fixtures are present with required files and keys")
def _g1(root):
    base = root / "benchmarks" / "fixtures" / "intent"
    dirs = sorted(d for d in base.iterdir() if d.is_dir() and re.match(r"^\d\d_", d.name)) if base.exists() else []
    schema = json.loads((base / "expected.schema.json").read_text(encoding="utf-8"))
    required = schema.get("required", [])
    bad = []
    for d in dirs:
        for f in ("expected.json", "intent.md", "pr.patch"):
            if not (d / f).exists():
                bad.append(f"{d.name}/{f} missing")
        if (d / "expected.json").exists():
            exp = json.loads((d / "expected.json").read_text(encoding="utf-8"))
            lacking = [k for k in required if k not in exp]
            if lacking:
                bad.append(f"{d.name}: missing keys {lacking}")
    if len(dirs) != 8 or bad:
        return FAIL, f"{len(dirs)} fixture dirs (expected 8); problems: {bad[:3]}"
    return PASS, "8 fixtures with required files and top-level keys (full schema validation: benchmarks/test_intent_fixtures.py)"


for _cid, _owner, _title, _detail in [
    ("H1.label_agreement_and_audit", "owner", "Label agreement between sources measured; L_audit sample drawn (2.3)", "needs two label sources and a human audit (CA-09)"),
    ("H2.compute_budget_declared", "owner", "RQ2 compute budget declared (17.3: N x median cost from the timing pilot)", "blank by design until the timing pilot has run"),
    ("H3.user_study_ready", "owner", "User-study materials, ethics determination, consent form, recruitment plan", "human work (TR-05)"),
    ("H4.rq6_hardware_declared", "owner", "RQ6 hardware and sandbox configuration declared", "needs the measurement machine"),
    ("H5.no_test_results_viewed", "owner", "Attestation: no test-split labels or results have been viewed", "only the owner can attest this"),
]:
    def _mk(detail=_detail):
        return lambda root: (MANUAL, detail)
    CHECKS.append((_cid, _owner, _title, _mk()))


@check("H6.freeze_act", "owner", "Freeze: hash in the block, version table row, signed tag, external deposit")
def _h6(root):
    t = _read(root, PREREG)
    state = "FROZEN" if "Freeze status: FROZEN" in t else "DRAFT"
    tags = _git(root, "tag", "--list", "prereg*") or ""
    return MANUAL, f"document status {state}; prereg tags: {tags.split() or 'none'}; owner act only (commands in PREREGISTRATION 17.10)"


# --------------------------------------------------------------------- main


def run_checks(root: Path, only: str | None = None) -> list[Result]:
    results = []
    for cid, owner, title, fn in CHECKS:
        if only and not cid.startswith(only):
            continue
        try:
            status, detail = fn(root)
        except Exception as exc:  # a broken check must be visible, not silently skipped
            status, detail = FAIL, f"check could not run: {type(exc).__name__}: {exc}"
        results.append(Result(cid, status, owner, title, detail))
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(CHECKOUT), help="repository root to check (default: this checkout)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", help="run only checks whose id starts with this prefix")
    ap.add_argument("--informational", action="store_true", help="always exit 0")
    args = ap.parse_args(argv)
    results = run_checks(Path(args.root), args.only)
    counts = {s: sum(1 for r in results if r.status == s) for s in (PASS, FAIL, MANUAL)}
    if args.json:
        print(json.dumps({"counts": counts, "results": [r.to_dict() for r in results]}, indent=2))
    else:
        for r in results:
            print(f"{r.status:<6} {r.id}  [{r.owner}]  {r.title}")
            print(f"       {r.detail}")
        print(f"\n{counts[PASS]} PASS, {counts[FAIL]} FAIL, {counts[MANUAL]} MANUAL. "
              "Not a freeze: this script changes nothing and a PASS is a precondition met, not a result.")
    return 0 if args.informational or counts[FAIL] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
