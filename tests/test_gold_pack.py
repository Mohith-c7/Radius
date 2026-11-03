"""Offline annotator kit (export/import), IN-09 -> IN-10 adapter, extra agreement statistics.

Only the committed SYNTHETIC fixture in benchmarks/gold/synthetic is used. Nothing
here is real gold data or a result.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gold_agreement as ga  # noqa: E402
import gold_lib as gl  # noqa: E402
import gold_pack as gp  # noqa: E402
import gold_to_eval as ge  # noqa: E402

SYNTH = ROOT / "benchmarks" / "gold" / "synthetic"
PRS = ["synth-org__repo0__pr100", "synth-org__repo1__pr101"]


def _sources_only(dest: Path) -> Path:
    """A gold dir holding only sources.json (what the owner has before annotation)."""
    for pr in PRS:
        (dest / pr).mkdir(parents=True)
        shutil.copy(SYNTH / pr / "sources.json", dest / pr / "sources.json")
    return dest


def _kit_for(tmp_path: Path, annotator: str, gold: Path | None = None) -> tuple[Path, Path]:
    gold = gold or _sources_only(tmp_path / "gold")
    kit = tmp_path / f"kit-{annotator}"
    gp.export_kit(gold, annotator, kit, seed=7, allow_synthetic=True)
    return gold, kit


def _annotate(kit: Path, annotator: str) -> None:
    """Stand-in for the human: reuse the fixture's valid annotation for this annotator id."""
    for pr in PRS:
        shutil.copy(SYNTH / pr / f"annotator-{annotator}.json",
                    kit / "benchmarks" / "gold" / "intent" / pr / f"annotator-{annotator}.json")


# ------------------------------------------------------------------ export


def test_kit_is_blinded_self_contained_and_hashed(tmp_path):
    # export from the FULL synthetic dir, which contains annotator and adjudicated files
    kit = tmp_path / "kit"
    m = gp.export_kit(SYNTH, "synth-a", kit, seed=1, allow_synthetic=True)
    names = {p.name for p in kit.rglob("*") if p.is_file()}
    assert not any(n.startswith("annotator-") or n == "adjudicated.json" for n in names)
    assert {"gold_annotate.py", "gold_lib.py", "schema.json", "queue.txt", "README.txt",
            gp.KIT_MANIFEST} <= names
    assert sorted(m["queue"]) == PRS and m["blinded"] is True and m["synthetic"] is True
    for rel, digest in m["files"].items():
        assert gp._sha256_file(kit / rel) == digest
    assert "--allow-synthetic" in (kit / "README.txt").read_text(encoding="utf-8")


def test_queue_is_seeded_per_annotator_and_first_ids_lead():
    ids = [f"p{i}" for i in range(30)]
    a = gp.build_queue(ids, "alice", 1, None)
    assert a == gp.build_queue(ids, "alice", 1, None) and sorted(a) == sorted(ids)
    assert a != gp.build_queue(ids, "bob", 1, None) and a != gp.build_queue(ids, "alice", 2, None)
    led = gp.build_queue(ids, "alice", 1, ["p5", "p9"])
    assert set(led[:2]) == {"p5", "p9"}


def test_export_refuses_synthetic_conflicts_and_foreign_directories(tmp_path):
    gold = _sources_only(tmp_path / "gold")
    with pytest.raises(gp.PackError, match="no PR is assignable"):
        gp.export_kit(gold, "synth-a", tmp_path / "k1", seed=1)  # synthetic without the flag
    (gold / "conflicts.json").write_text(
        json.dumps({"synth-a": {"repos": ["synth-org/repo0"]}}), encoding="utf-8")
    m = gp.export_kit(gold, "synth-a", tmp_path / "k2", seed=1, allow_synthetic=True)
    assert m["queue"] == [PRS[1]] and "conflict" in m["skipped"][0]["reason"]
    with pytest.raises(gp.PackError, match="not empty"):
        gp.export_kit(gold, "synth-a", tmp_path / "k2", seed=1, allow_synthetic=True)
    gp.export_kit(gold, "synth-a", tmp_path / "k2", seed=1, allow_synthetic=True, force=True)
    stranger = tmp_path / "stranger"
    stranger.mkdir()
    (stranger / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(gp.PackError, match="not a kit"):
        gp.export_kit(gold, "synth-a", stranger, seed=1, allow_synthetic=True, force=True)
    assert (stranger / "keep.txt").exists()
    with pytest.raises(gl.GoldError):
        gp.export_kit(gold, "radius-bot", tmp_path / "k3", seed=1, allow_synthetic=True)


def test_kit_runs_standalone_without_the_repository(tmp_path):
    _gold, kit = _kit_for(tmp_path, "synth-a")
    res = subprocess.run(
        [sys.executable, "-I", "scripts/gold_annotate.py", "status", "--annotator", "synth-a",
         "--allow-synthetic"],
        cwd=kit, capture_output=True, text=True, timeout=60, check=False,
    )
    assert res.returncode == 0, res.stderr
    assert all(pr in res.stdout for pr in PRS)


# ------------------------------------------------------------------ import


def test_two_kits_round_trip_into_agreement_report(tmp_path):
    gold = _sources_only(tmp_path / "gold")
    for aid in ("synth-a", "synth-b"):
        _gold, kit = _kit_for(tmp_path, aid, gold)
        _annotate(kit, aid)
        r = gp.import_kit(kit, gold, allow_synthetic=True)
        assert r["errors"] == [] and sorted(r["imported"]) == PRS
        for pr in PRS:
            assert gl.read_json(gold / pr / f"annotator-{aid}.json") == gl.read_json(
                SYNTH / pr / f"annotator-{aid}.json")
    comps, _docs, skipped = ga.collect(gold, allow_synthetic=True)
    assert len(comps) == 2 and skipped == []
    rep = ga.build_report(comps, n_boot=100, seed=3, synthetic=True)
    assert rep["well_specified"]["po"] is not None and "ci95" in rep["well_specified"]
    assert {"presence_agreement", "testability_agreement"} <= set(rep["overall"]["ci95"])
    md = ga.report_markdown(rep)
    assert "Percent agreement" in md and "SYNTHETIC" in md


def test_import_is_all_or_nothing_and_checks_ownership_and_tampering(tmp_path):
    gold, kit = _kit_for(tmp_path, "synth-a")
    _annotate(kit, "synth-a")
    p0 = kit / "benchmarks/gold/intent" / PRS[0] / "annotator-synth-a.json"
    p1 = kit / "benchmarks/gold/intent" / PRS[1] / "annotator-synth-a.json"

    # (1) one annotation belongs to someone else -> nothing imported, even the valid one
    doc = json.loads(p1.read_text(encoding="utf-8"))
    doc["annotator_id"] = "synth-b"
    p1.write_text(json.dumps(doc), encoding="utf-8")
    r = gp.import_kit(kit, gold, allow_synthetic=True)
    assert r["imported"] == [] and any("does not belong" in e for e in r["errors"])
    assert not list(gold.rglob("annotator-*.json"))
    shutil.copy(SYNTH / PRS[1] / "annotator-synth-a.json", p1)

    # (2) a foreign file smuggled into the kit
    foreign = p0.with_name("annotator-synth-b.json")
    shutil.copy(SYNTH / PRS[0] / "annotator-synth-b.json", foreign)
    r = gp.import_kit(kit, gold, allow_synthetic=True)
    assert any("foreign file" in e for e in r["errors"]) and not list(gold.rglob("annotator-*.json"))
    foreign.unlink()

    # (3) source text altered in the kit
    src = kit / "benchmarks/gold/intent" / PRS[0] / "sources.json"
    original = src.read_bytes()
    src.write_bytes(original.replace(b"synthetic", b"synthetiX", 1))
    r = gp.import_kit(kit, gold, allow_synthetic=True)
    assert any("altered" in e for e in r["errors"]) and not list(gold.rglob("annotator-*.json"))
    src.write_bytes(original)

    # (4) span that no longer matches the stored text
    bad = json.loads(p0.read_text(encoding="utf-8"))
    bad["criteria"][0]["span"]["end"] += 1
    p0.write_text(json.dumps(bad), encoding="utf-8")
    r = gp.import_kit(kit, gold, allow_synthetic=True)
    assert r["errors"] and not list(gold.rglob("annotator-*.json"))
    shutil.copy(SYNTH / PRS[0] / "annotator-synth-a.json", p0)

    # (5) clean now; second import refuses to overwrite without --force
    assert gp.import_kit(kit, gold, allow_synthetic=True)["errors"] == []
    again = gp.import_kit(kit, gold, allow_synthetic=True)
    assert any("already exists" in e for e in again["errors"])
    assert gp.import_kit(kit, gold, allow_synthetic=True, force=True)["errors"] == []


def test_incomplete_annotations_are_reported_not_imported(tmp_path):
    gold, kit = _kit_for(tmp_path, "synth-a")
    _annotate(kit, "synth-a")
    p0 = kit / "benchmarks/gold/intent" / PRS[0] / "annotator-synth-a.json"
    doc = json.loads(p0.read_text(encoding="utf-8"))
    doc["status"] = "in_progress"
    p0.write_text(json.dumps(doc), encoding="utf-8")
    r = gp.import_kit(kit, gold, allow_synthetic=True)
    assert r["incomplete"] == [PRS[0]] and r["imported"] == [PRS[1]] and r["errors"] == []
    r = gp.import_kit(kit, gold, allow_synthetic=True, include_incomplete=True, force=True)
    assert sorted(r["imported"]) == PRS


def test_synthetic_kit_needs_the_flag_on_import(tmp_path):
    gold, kit = _kit_for(tmp_path, "synth-a")
    with pytest.raises(gp.PackError, match="synthetic"):
        gp.import_kit(kit, gold)


def test_cli_export_and_import(tmp_path, capsys):
    gold = _sources_only(tmp_path / "gold")
    kit = tmp_path / "kit"
    assert gp.main(["export", "--gold-dir", str(gold), "--annotator", "synth-a", "--seed", "3",
                    "--out", str(kit), "--allow-synthetic"]) == 0
    _annotate(kit, "synth-a")
    assert gp.main(["import", "--kit", str(kit), "--gold-dir", str(gold), "--allow-synthetic"]) == 0
    assert "imported 2" in capsys.readouterr().out
    assert gp.main(["import", "--kit", str(kit), "--gold-dir", str(gold), "--allow-synthetic"]) == 2


# ------------------------------------------------------------------ adapter


def test_adapter_exports_adjudicated_explicit_criteria_for_the_harness():
    from radius_intent.evaluation.gold import parse_gold

    doc = ge.adapt_test(SYNTH)
    ds = parse_gold(doc)
    expected = 0
    for pr in PRS:
        adj = gl.read_json(SYNTH / pr / "adjudicated.json")
        expected += sum(1 for c in adj["criteria"] if c["explicit"] and c["resolution"] != "dropped")
    assert len(ds.cases) == 2 and sum(len(c.criteria) for c in ds.cases) == expected
    assert doc["synthetic"] is True and doc["split"] == "test"
    with pytest.raises(ge.AdapterError, match="no PRs of role 'dev'"):
        ge.adapt_dev(SYNTH)
    with pytest.raises(ge.AdapterError):
        ge.adapt_role(SYNTH, "pilot")


def test_adapter_refuses_unfinished_adjudication(tmp_path):
    gold = tmp_path / "gold"
    shutil.copytree(SYNTH, gold)
    path = gold / PRS[0] / "adjudicated.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["criteria"][0]["resolution"] = "pending"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ge.AdapterError, match="not ready"):
        ge.adapt_test(gold)
    path.unlink()
    with pytest.raises(ge.AdapterError, match="no complete adjudicated"):
        ge.adapt_test(gold)


def test_harness_runs_on_the_adapted_gold(tmp_path):
    from radius_intent.evaluation.cli import main as eval_main

    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({
        "name": "adapter-check", "seed": 1,
        "gold": {"path": str(SYNTH), "adapter": "gold_to_eval:adapt_test"},
        "bootstrap": {"resamples": 20, "confidence": 0.95}, "rate_testability": False,
        "extractors": [{"id": "sanity-oracle", "kind": "oracle"}, {"id": "sanity-null", "kind": "null"}],
    }), encoding="utf-8")
    out = tmp_path / "out"
    assert eval_main(["run", "--config", str(cfg), "--out-root", str(out), "--quiet"]) == 0
    report = json.loads(next(out.glob("*/report.json")).read_text(encoding="utf-8"))
    oracle = report["extractors"]["sanity-oracle"]["groups"]["all"]["iou"]
    assert oracle["tp"] == oracle["gold"] == oracle["pred"] > 0
    assert report["extractors"]["sanity-null"]["groups"]["all"]["iou"]["tp"] == 0
