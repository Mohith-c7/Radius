"""scripts/prereg_check.py: statuses, hash procedure, gold counting, checklist sync.

Uses synthetic roots for the semantic cases. The sync test pins FREEZE_CHECKLIST.md to the
script output for the real repository: when a check changes status (someone fixes an item),
update the Status column of the checklist in the same change.
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import prereg_check as pc  # noqa: E402

CHECKLIST = ROOT / "docs" / "research" / "preregistration" / "FREEZE_CHECKLIST.md"
SYNTH = ROOT / "benchmarks" / "gold" / "synthetic"
START, END = pc.START_MARK, pc.END_MARK


@functools.lru_cache(maxsize=1)
def _real_results():
    return tuple(pc.run_checks(ROOT))


def _prereg_text(hash_hex: str, tail: str = "end\n", status: str = "DRAFT -- not frozen.") -> str:
    return (
        f"# T\n\n{START}\n**Freeze status: {status}**\n| hash | `{hash_hex}` |\n{END}\n\nbody\n{tail}"
    )


def _root_with_prereg(tmp_path: Path, text: str) -> Path:
    p = tmp_path / pc.PREREG
    p.parent.mkdir(parents=True)
    p.write_text(text, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------ real repository


def test_every_check_runs_with_a_valid_status_and_ids_are_unique():
    results = _real_results()
    ids = [r.id for r in results]
    assert len(ids) == len(set(ids)) > 40
    assert {r.status for r in results} <= {pc.PASS, pc.FAIL, pc.MANUAL}
    assert not [r for r in results if "could not run" in r.detail], [r.id for r in results if "could not run" in r.detail]
    assert all(r.detail for r in results)


def test_exit_codes_and_json(capsys):
    assert pc.main(["--informational"]) == 0
    capsys.readouterr()
    rc = pc.main(["--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == (1 if out["counts"]["FAIL"] else 0)
    assert sum(out["counts"].values()) == len(out["results"])
    assert pc.main(["--only", "B6", "--informational"]) == 0


def test_the_checker_never_reports_the_document_as_frozen():
    r = {x.id: x for x in _real_results()}
    assert "not frozen" in r["A1.prereg_file_and_freeze_block"].detail.lower()
    assert r["H6.freeze_act"].status == pc.MANUAL  # an owner act, never PASS


def test_checklist_statuses_match_the_script_output():
    """Each checklist row's status (DONE/TODO/OWNER) must equal the script's PASS/FAIL/MANUAL."""
    mapping = {"DONE": pc.PASS, "TODO": pc.FAIL, "OWNER": pc.MANUAL}
    results = {r.id: r.status for r in _real_results()}
    rows = {}
    for line in CHECKLIST.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and re.fullmatch(r"[A-H]\d?b?\.?[A-Za-z]*\d*", cells[0]) and cells[-1].split(" ")[0] in mapping:
            rows[cells[0]] = mapping[cells[-1].split(" ")[0]]
    # row ids are the short prefixes (A1, D.B0, ...); script ids continue with a descriptive suffix
    by_prefix = {cid.split(".", 1)[0] if not cid.startswith("D.") else cid: st for cid, st in results.items()}
    assert len(rows) == len(results), (len(rows), len(results))
    for short, expected in rows.items():
        assert by_prefix[short] == expected, f"{short}: checklist says {expected}, script says {by_prefix[short]}"


# ---------------------------------------------------------- hash procedure


def test_documented_sed_semantics_match_the_recorded_draft_hash():
    t = (ROOT / pc.PREREG).read_text(encoding="utf-8").replace("\r\n", "\n")
    recorded = re.findall(r"`([0-9a-f]{64})`", pc.FREEZE_BLOCK.search(t).group(0))[-1]
    assert pc._hash_lines(t, anchored=False)[0] == recorded


def test_stray_marker_makes_the_documented_procedure_skip_the_tail():
    stray = f"see: `sed '/{START}/,/{END}/d'`\nline after\n"
    text = _prereg_text("0" * 64, tail=stray + "TAIL-A\n")
    h_doc, dropped_doc = pc._hash_lines(text, anchored=False)
    h_anch, dropped_anch = pc._hash_lines(text, anchored=True)
    assert dropped_anch == 4 and dropped_doc > dropped_anch
    changed = _prereg_text("0" * 64, tail=stray + "TAIL-B\n")
    assert pc._hash_lines(changed, anchored=False)[0] == h_doc  # tail edit invisible
    assert pc._hash_lines(changed, anchored=True)[0] != h_anch  # anchored hash sees it


def test_a2_and_a2b_on_synthetic_documents(tmp_path):
    clean = _prereg_text("0" * 64)
    good = _prereg_text(pc._hash_lines(clean, anchored=False)[0])
    root = _root_with_prereg(tmp_path / "ok", good)
    assert pc._a2(root)[0] == pc.PASS and pc._a2b(root)[0] == pc.PASS
    edited = good.replace("body", "BODY")
    assert pc._a2(_root_with_prereg(tmp_path / "bad", edited))[0] == pc.FAIL
    stray = _prereg_text("0" * 64, tail=f"`/{START}/,/{END}/d`\ntail\n")
    h = pc._hash_lines(stray, anchored=False)[0]
    broken = _root_with_prereg(tmp_path / "stray", stray.replace("0" * 64, h))
    assert pc._a2(broken)[0] == pc.PASS and pc._a2b(broken)[0] == pc.FAIL
    assert "FROZEN" not in pc._a1(broken)[1]


def test_a3_detects_tracked_placeholders(tmp_path):
    root = _root_with_prereg(tmp_path, _prereg_text("0" * 64, tail="Reconcile the two files before freeze.\n"))
    assert pc._a3(root)[0] == pc.FAIL
    assert pc._a3(_root_with_prereg(tmp_path / "clean", _prereg_text("0" * 64)))[0] == pc.PASS


# --------------------------------------------------------------- gold counts


def _as_real_gold(tmp_path: Path, role: str) -> Path:
    gdir = tmp_path / "benchmarks" / "gold" / "intent"
    shutil.copytree(SYNTH, gdir)
    for p in gdir.rglob("*.json"):
        doc = json.loads(p.read_text(encoding="utf-8"))
        if "synthetic" in doc:
            doc["synthetic"] = False
        if p.name == "sources.json":
            doc["pr"]["role"] = role
        p.write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def test_gold_checks_count_real_adjudicated_prs_and_compute_the_gate(tmp_path):
    root = _as_real_gold(tmp_path, "pilot")
    status, detail = pc._c3(root)
    assert status == pc.FAIL and "'pilot': 2" in detail
    status, detail = pc._c4(root)
    assert status == pc.FAIL and "2 complete pilot PRs" in detail and "kappa" in detail
    assert pc._c3(_as_real_gold(tmp_path / "t", "test"))[1].count("'test': 2") == 1
    # synthetic data never counts
    assert "none" in pc._c3(ROOT)[1] and pc._c4(ROOT)[0] == pc.FAIL


# ---------------------------------------------------------------- baselines


def test_baseline_check_is_fail_without_code_and_never_pass_with_it(tmp_path):
    fn = {cid: f for cid, _o, _t, f in pc.CHECKS}
    assert fn["D.B3"](tmp_path)[0] == pc.FAIL
    assert fn["D.B3"](ROOT)[0] == pc.FAIL
    present = tmp_path / "packages" / "linking" / "src"
    present.mkdir(parents=True)
    assert fn["D.B9"](tmp_path)[0] == pc.MANUAL
    assert pc.PASS not in {fn[f"D.B{i}"](ROOT)[0] for i in range(13)}


def test_empty_root_degrades_to_visible_failures_not_crashes(tmp_path):
    results = pc.run_checks(tmp_path)
    assert len(results) == len(pc.CHECKS)
    assert all(r.status in {pc.FAIL, pc.MANUAL} for r in results)
    assert any("could not run" in r.detail for r in results)


def test_digest_check_prints_a_real_config_digest():
    status, detail = pc._f1(ROOT)
    m = re.search(r"digest (?:is )?([0-9a-f]{64})", detail)
    assert status in {pc.FAIL, pc.PASS} and m
    from radius_evidence.domain.config import VerdictV2Config

    assert m.group(1) == VerdictV2Config().digest()
