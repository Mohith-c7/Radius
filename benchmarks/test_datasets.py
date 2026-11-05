"""Unit tests for scripts/datasets.py (EP-03): schema, hashing, fetch, splits.

Pure logic on synthetic data; no network (fetch uses an injected opener).
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "datasets.py"
_spec = importlib.util.spec_from_file_location("radius_datasets", _PATH)
ds = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ds
_spec.loader.exec_module(ds)


# ---------------------------------------------------------------- manifests


def test_all_committed_manifests_valid():
    manifests = ds.load_manifests()
    assert len(manifests) >= 15
    schema = ds.load_schema()
    for m in manifests:
        assert ds.validate_manifest(m, schema) == [], m["id"]


def test_manifest_ids_unique_and_match_filenames():
    paths = sorted(ds.MANIFESTS_DIR.glob("*.json"))
    ids = [json.loads(p.read_text(encoding="utf-8"))["id"] for p in paths]
    assert len(set(ids)) == len(ids)
    assert [p.stem for p in paths] == ids


def test_unknown_license_never_redistributable():
    for m in ds.load_manifests():
        if m["license"]["verdict"] == "unknown":
            assert m["redistribution"]["allowed"] == "no", m["id"]
            assert "UNKNOWN" in m["license"]["name"], m["id"]


def _good():
    return copy.deepcopy(
        next(m for m in ds.load_manifests() if m["id"] == "swe-bench-lite")
    )


def test_schema_rejects_missing_and_bad_fields():
    m = _good()
    del m["license"]
    assert any("license" in e for e in ds.validate_manifest(m))
    m = _good()
    m["files"][0]["sha256"] = "XYZ"
    assert any("sha256" in e for e in ds.validate_manifest(m))
    m = _good()
    m["surprise"] = 1
    assert any("unexpected property" in e for e in ds.validate_manifest(m))
    m = _good()
    m["status"] = "maybe"
    assert any("status" in e for e in ds.validate_manifest(m))


def test_semantic_rules():
    m = _good()
    m["redistribution"]["allowed"] = "yes"  # licence verdict is unknown
    assert any("do not redistribute" in e for e in ds.validate_manifest(m))
    m = _good()
    m["files"][0]["path"] = "../escape"
    assert any("unsafe" in e for e in ds.validate_manifest(m))
    m = _good()
    del m["files"][0]["sha256"]
    assert any("lacks sha256" in e for e in ds.validate_manifest(m))


# -------------------------------------------------------------- hash verify


def test_verify_file_statuses(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello")
    good = hashlib.sha256(b"hello").hexdigest()
    assert ds.verify_file(f, good, 5)[0] == "ok"
    assert ds.verify_file(f, good, 6)[0] == "size-mismatch"
    assert ds.verify_file(f, "0" * 64, 5)[0] == "hash-mismatch"
    assert ds.verify_file(tmp_path / "nope", good)[0] == "missing"


def test_verify_eol_normalisation(tmp_path):
    f = tmp_path / "t.txt"
    f.write_bytes(b"a\r\nb\r\n")
    lf_hash = hashlib.sha256(b"a\nb\n").hexdigest()
    assert ds.verify_file(f, lf_hash, 4, normalize_eol=True)[0] == "ok"
    assert ds.verify_file(f, lf_hash, 4)[0] == "size-mismatch"


def test_verify_manifest_offline_cache(tmp_path):
    m = _good()
    rows = ds.verify_manifest(m, cache=tmp_path)
    assert {r["status"] for r in rows} == {"missing"}  # offline-safe, no crash
    dest = tmp_path / m["id"] / m["files"][0]["path"]
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"corrupt")
    assert ds.verify_manifest(m, cache=tmp_path)[0]["status"] == "size-mismatch"


def test_local_manifests_verify_clean():
    for m in ds.load_manifests():
        if m["source"]["type"] == "local":
            assert {r["status"] for r in ds.verify_manifest(m)} == {"ok"}, m["id"]


# -------------------------------------------------------------------- fetch


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _fake_manifest(payload: bytes, sha: str | None = None):
    return {
        "id": "fake",
        "status": "available",
        "source": {"type": "huggingface"},
        "files": [
            {
                "path": "d/x.bin",
                "url": "https://example.invalid/x",
                "size": len(payload),
                "sha256": sha or hashlib.sha256(payload).hexdigest(),
            }
        ],
    }


def test_fetch_ok_and_cached(tmp_path):
    data = b"payload"
    calls = []

    def opener(url):
        calls.append(url)
        return _Resp(data)

    m = _fake_manifest(data)
    assert ds.fetch_manifest(m, tmp_path, opener=opener)[0]["status"] == "downloaded"
    assert ds.fetch_manifest(m, tmp_path, opener=opener)[0]["status"] == "cached"
    assert len(calls) == 1


def test_fetch_rejects_hash_mismatch_and_cleans_up(tmp_path):
    m = _fake_manifest(b"expected", sha="0" * 64)
    with pytest.raises(ValueError, match="hash-mismatch"):
        ds.fetch_manifest(m, tmp_path, opener=lambda u: _Resp(b"expected"))
    assert not list(tmp_path.rglob("x.bin*"))


def test_fetch_refuses_oversize_unhashed_and_unknown_path(tmp_path):
    m = _fake_manifest(b"abc")
    with pytest.raises(ValueError, match="exceeds"):
        ds.fetch_manifest(m, tmp_path, max_bytes=1, opener=lambda u: _Resp(b""))
    m["files"][0].pop("sha256")
    with pytest.raises(ValueError, match="needs url and sha256"):
        ds.fetch_manifest(m, tmp_path, opener=lambda u: _Resp(b""))
    with pytest.raises(ValueError, match="unknown --path"):
        ds.fetch_manifest(_fake_manifest(b"abc"), tmp_path, only_paths=["zzz"])


def test_cli_fetch_requires_yes():
    assert ds.main(["fetch", "--id", "swe-bench-lite"]) == 2


def test_license_report_flags_unknown():
    text = ds.license_report_md(ds.load_manifests())
    assert "UNKNOWN - do not redistribute:" in text
    assert "utboost" in text.split("UNKNOWN - do not redistribute:")[1]


# ------------------------------------------------------------------- splits


def _records(n_repos=10, per_repo=6):
    recs = []
    for r in range(n_repos):
        for i in range(per_repo):
            recs.append(
                {
                    "id": f"r{r}__{i}",
                    "repo": f"org/repo{r}",
                    "created_at": f"2025-{(r * per_repo + i) % 12 + 1:02d}-{i + 1:02d}T00:00:00Z",
                    "text": f"change {r}-{i}",
                }
            )
    return recs


def test_repo_split_deterministic_and_disjoint():
    recs = _records()
    a = ds.make_split(recs, "repo", seed=7, test_frac=0.3)
    b = ds.make_split(list(reversed(recs)), "repo", seed=7, test_frac=0.3)
    assert a["train_ids"] == b["train_ids"] and a["test_ids"] == b["test_ids"]
    assert a["ok"] and a["violations"] == []
    assert a["n_train"] + a["n_test"] == len(recs)
    assert a["n_test"] >= 0.3 * len(recs)
    repos_test = {i.split("__")[0] for i in a["test_ids"]}
    repos_train = {i.split("__")[0] for i in a["train_ids"]}
    assert not repos_test & repos_train
    c = ds.make_split(recs, "repo", seed=8, test_frac=0.3)
    assert c["test_ids"] != a["test_ids"]  # seed matters


def test_time_split_ordering_and_ties():
    recs = _records()
    rep = ds.make_split(recs, "time", test_frac=0.25)
    assert rep["ok"]
    by_id = {r["id"]: r for r in recs}
    assert max(by_id[i]["created_at"] for i in rep["train_ids"]) < min(
        by_id[i]["created_at"] for i in rep["test_ids"]
    )
    # all-equal timestamps: nothing can be train without tie leakage
    same = [dict(r, created_at="2025-01-01T00:00:00Z") for r in recs]
    rep2 = ds.make_split(same, "time", test_frac=0.25)
    assert rep2["ok"]


def test_dedupe_by_content_hash():
    recs = _records(3, 2)
    dup = dict(recs[0], id="zz_dup")  # same repo/text, different id
    rep = ds.make_split(recs + [dup], "repo", seed=1, test_frac=0.4)
    assert rep["n_deduped_dropped"] == 1
    assert "zz_dup" in rep["dropped_ids"]
    kept = set(rep["train_ids"]) | set(rep["test_ids"])
    assert "zz_dup" not in kept


def test_duplicate_instance_ids_rejected():
    recs = _records(2, 2)
    recs.append(dict(recs[0], text="other"))
    with pytest.raises(ValueError, match="duplicate instance ids"):
        ds.make_split(recs, "repo")


def test_leakage_detected_repo_instance_hash_and_time():
    recs = _records(4, 3)
    kept, _ = ds.dedupe(recs, ["repo", "text"])
    train = [r for r in kept if r["repo"] in ("org/repo0", "org/repo1")]
    test = [r for r in kept if r["repo"] in ("org/repo2", "org/repo3")]
    assert ds.check_leakage(train, test, "repo") == []

    # same repo on both sides
    leaky = test + [train[0]]
    v = ds.check_leakage(train, leaky, "repo")
    assert any("repo org/repo0" in x for x in v)
    # same instance on both sides
    assert any("appears in both" in x for x in v)
    # same content under a different id
    twin = dict(train[0], id="twin")
    assert any("content hash" in x for x in ds.check_leakage(train, [twin], "repo"))
    # temporal inversion
    old = [dict(r, created_at="2030-01-01T00:00:00Z") for r in train]
    new = [dict(r, created_at="2020-01-01T00:00:00Z") for r in test]
    assert any("temporal" in x for x in ds.check_leakage(old, new, "time"))


def test_cli_split_exit_code_and_outputs(tmp_path):
    inp = tmp_path / "in.jsonl"
    inp.write_text("\n".join(json.dumps(r) for r in _records()), encoding="utf-8")
    out = tmp_path / "out"
    rc = ds.main(["split", "--input", str(inp), "--mode", "repo", "--out", str(out)])
    assert rc == 0
    rep = json.loads((out / "split.json").read_text(encoding="utf-8"))
    assert rep["ok"] and (out / "report.md").read_text(encoding="utf-8").count("PASS")
    assert rep["seed"] == ds.DEFAULT_SEED
