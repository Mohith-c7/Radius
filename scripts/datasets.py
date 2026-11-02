"""Dataset manifests, verification, fetching, licence report and splits (EP-03).

Standard library only. Manifests live in ``benchmarks/datasets/manifests/*.json``
and conform to ``benchmarks/datasets/manifest.schema.json``. Third-party dataset
contents are never committed; only manifests (source, pinned revision, licence,
sha256) are. Downloads go to a git-ignored cache directory
(``.cache/datasets`` or ``$RADIUS_DATASET_CACHE``).

Subcommands::

    python scripts/datasets.py list
    python scripts/datasets.py validate                  # manifests vs schema
    python scripts/datasets.py verify [--id ID]          # offline; local/cache files vs sha256
    python scripts/datasets.py fetch --id ID --yes [--path P]  # download + sha256 check
    python scripts/datasets.py license-report [--format md|json]
    python scripts/datasets.py split --input recs.jsonl --mode repo|time \\
        --seed 20261102 --test-frac 0.2 --out DIR

Note: this file is named ``datasets.py`` as required by the task; import it by
path (importlib), not as ``datasets``, to avoid shadowing the Hugging Face package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASETS_DIR = REPO_ROOT / "benchmarks" / "datasets"
MANIFESTS_DIR = DATASETS_DIR / "manifests"
SCHEMA_PATH = DATASETS_DIR / "manifest.schema.json"
DEFAULT_SEED = 20261102
DEFAULT_MAX_BYTES = 2 * 1024**3  # fetch refuses anything larger unless overridden

# --------------------------------------------------------------------------
# Minimal JSON-schema subset validator (stdlib only)
# Supports: type, enum, const, pattern, required, properties,
# additionalProperties (bool), items, minItems, minimum.
# --------------------------------------------------------------------------

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value, name: str) -> bool:
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def validate_schema(value, schema: dict, path: str = "$") -> list[str]:
    """Return a list of error strings (empty if valid)."""
    errors: list[str] = []
    t = schema.get("type")
    if t is not None:
        names = t if isinstance(t, list) else [t]
        if not any(_type_ok(value, n) for n in names):
            return [f"{path}: expected {names}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str) and "pattern" in schema:
        if re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required '{key}'")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(f"{path}: unexpected property '{key}'")
        for key, sub in props.items():
            if key in value:
                errors.extend(validate_schema(value[key], sub, f"{path}.{key}"))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                errors.extend(validate_schema(item, schema["items"], f"{path}[{i}]"))
    return errors


def load_schema(path: Path = SCHEMA_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def semantic_errors(m: dict) -> list[str]:
    """Cross-field rules the schema subset cannot express."""
    errs: list[str] = []
    lic = m.get("license", {})
    red = m.get("redistribution", {})
    if lic.get("verdict") == "unknown" and red.get("allowed") != "no":
        errs.append(
            "license verdict 'unknown' requires redistribution.allowed == 'no' "
            "(UNKNOWN - do not redistribute)"
        )
    if lic.get("verdict") == "unknown" and "UNKNOWN" not in lic.get("name", ""):
        errs.append("license.name must contain 'UNKNOWN' when verdict is unknown")
    if m.get("status") == "available":
        files = m.get("files", [])
        if not files and m.get("source", {}).get("type") in ("huggingface", "zenodo", "local"):
            errs.append("status 'available' requires at least one file entry")
        for f in files:
            if not f.get("sha256"):
                errs.append(f"status 'available': file {f.get('path')} lacks sha256")
    seen = set()
    for f in m.get("files", []):
        if f["path"] in seen:
            errs.append(f"duplicate file path {f['path']}")
        seen.add(f["path"])
        p = Path(f["path"])
        if p.is_absolute() or ".." in p.parts:
            errs.append(f"unsafe file path {f['path']}")
    return errs


def validate_manifest(m: dict, schema: dict | None = None) -> list[str]:
    return validate_schema(m, schema or load_schema()) + semantic_errors(m)


def load_manifests(directory: Path = MANIFESTS_DIR) -> list[dict]:
    out = []
    for p in sorted(directory.glob("*.json")):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


# --------------------------------------------------------------------------
# Hashing, verification, fetching
# --------------------------------------------------------------------------


def _lf_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(bytes([13, 10]), bytes([10]))


def sha256_file(path: Path, chunk: int = 1 << 20, normalize_eol: bool = False) -> str:
    """sha256 of a file. normalize_eol hashes CRLF as LF (repo text files are
    stored with LF in git but may be checked out with CRLF on Windows)."""
    if normalize_eol:
        return hashlib.sha256(_lf_bytes(path)).hexdigest()
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def cache_dir() -> Path:
    return Path(os.environ.get("RADIUS_DATASET_CACHE", REPO_ROOT / ".cache" / "datasets"))


def local_path(manifest: dict, file_entry: dict, cache: Path | None = None) -> Path:
    """Where a manifest file lives locally (repo for kind=local, else cache)."""
    if manifest["source"]["type"] == "local":
        return REPO_ROOT / file_entry["path"]
    return (cache or cache_dir()) / manifest["id"] / file_entry["path"]


def verify_file(
    path: Path,
    expected_sha256: str,
    expected_size: int | None = None,
    normalize_eol: bool = False,
):
    """Return (status, detail); status in ok|missing|size-mismatch|hash-mismatch."""
    if not path.is_file():
        return "missing", "file not present"
    size = path.stat().st_size
    if normalize_eol:
        size = len(_lf_bytes(path))
    if expected_size is not None and size != expected_size:
        return "size-mismatch", f"size {size} != {expected_size}"
    actual = sha256_file(path, normalize_eol=normalize_eol)
    if actual != expected_sha256:
        return "hash-mismatch", f"sha256 {actual} != {expected_sha256}"
    return "ok", ""


def verify_manifest(manifest: dict, cache: Path | None = None) -> list[dict]:
    rows = []
    for f in manifest.get("files", []):
        p = local_path(manifest, f, cache)
        if not f.get("sha256"):
            rows.append({"path": f["path"], "status": "unhashed", "detail": ""})
            continue
        status, detail = verify_file(
            p, f["sha256"], f.get("size"), manifest["source"]["type"] == "local"
        )
        rows.append({"path": f["path"], "status": status, "detail": detail})
    return rows


def fetch_manifest(
    manifest: dict,
    cache: Path,
    max_bytes: int = DEFAULT_MAX_BYTES,
    opener=urllib.request.urlopen,
    only_paths: list[str] | None = None,
) -> list[dict]:
    """Download every file of a manifest to cache, verifying sha256.

    Never called without an explicit --yes at the CLI. Files without sha256 or
    url are refused (no trust-on-first-use). Partial files are removed on failure.
    """
    if manifest["source"]["type"] == "local":
        return [{"path": f["path"], "status": "local"} for f in manifest.get("files", [])]
    files = manifest.get("files", [])
    if only_paths:
        unknown = set(only_paths) - {f["path"] for f in files}
        if unknown:
            raise ValueError(f"{manifest['id']}: unknown --path {sorted(unknown)}")
        files = [f for f in files if f["path"] in only_paths]
    if not files:
        raise ValueError(f"{manifest['id']}: no files listed (status {manifest['status']})")
    total = sum(f.get("size") or 0 for f in files)
    if total > max_bytes:
        raise ValueError(
            f"{manifest['id']}: {total} bytes exceeds --max-bytes {max_bytes}"
        )
    results = []
    for f in files:
        if not f.get("sha256") or not f.get("url"):
            raise ValueError(f"{manifest['id']}: {f['path']} needs url and sha256 to fetch")
        dest = local_path(manifest, f, cache)
        if dest.is_file() and verify_file(dest, f["sha256"], f.get("size"))[0] == "ok":
            results.append({"path": f["path"], "status": "cached"})
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with opener(f["url"]) as resp, open(tmp, "wb") as out:
                while block := resp.read(1 << 20):
                    out.write(block)
            status, detail = verify_file(tmp, f["sha256"], f.get("size"))
            if status != "ok":
                raise ValueError(f"{manifest['id']}: {f['path']}: {status} {detail}")
            tmp.replace(dest)
        finally:
            if tmp.exists():
                tmp.unlink()
        results.append({"path": f["path"], "status": "downloaded"})
    return results


# --------------------------------------------------------------------------
# Licence report
# --------------------------------------------------------------------------


def license_rows(manifests: list[dict]) -> list[dict]:
    rows = []
    for m in manifests:
        lic = m["license"]
        rows.append(
            {
                "id": m["id"],
                "license": lic["name"],
                "verdict": lic["verdict"],
                "redistribution": m["redistribution"]["allowed"],
                "status": m["status"],
            }
        )
    return rows


def license_report_md(manifests: list[dict]) -> str:
    lines = [
        "| id | licence | verdict | redistribute | status |",
        "|---|---|---|---|---|",
    ]
    for r in license_rows(manifests):
        lines.append(
            f"| {r['id']} | {r['license']} | {r['verdict']} | "
            f"{r['redistribution']} | {r['status']} |"
        )
    unknown = [r["id"] for r in license_rows(manifests) if r["verdict"] == "unknown"]
    lines.append("")
    lines.append(
        "UNKNOWN - do not redistribute: " + (", ".join(unknown) if unknown else "none")
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Splits: deterministic, leakage-checked
# --------------------------------------------------------------------------


def content_hash(record: dict, fields: list[str]) -> str:
    """sha256 of the canonical JSON of the selected fields."""
    payload = json.dumps({k: record.get(k) for k in fields}, sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dedupe(records: list[dict], hash_fields: list[str]):
    """Drop records with identical content hash (first by id order wins).

    Returns (kept, dropped_ids). Deterministic: records are ordered by id first.
    """
    seen: dict[str, str] = {}
    kept, dropped = [], []
    for r in sorted(records, key=lambda r: str(r["id"])):
        h = content_hash(r, hash_fields)
        if h in seen:
            dropped.append(str(r["id"]))
            continue
        seen[h] = str(r["id"])
        r = dict(r)
        r["content_hash"] = h
        kept.append(r)
    return kept, dropped


def _bucket(seed: int, key: str) -> int:
    return int(hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()[:16], 16)


def split_by_repo(records: list[dict], seed: int = DEFAULT_SEED, test_frac: float = 0.2):
    """Whole repos go to test or train. Repos ranked by seeded hash (stable under
    record reordering); smallest-rank repos fill test until >= test_frac of records."""
    if not 0 < test_frac < 1:
        raise ValueError("test_frac must be in (0,1)")
    by_repo: dict[str, list[dict]] = {}
    for r in records:
        by_repo.setdefault(r["repo"], []).append(r)
    target = test_frac * len(records)
    train, test = [], []
    n_test = 0
    for repo in sorted(by_repo, key=lambda x: (_bucket(seed, x), x)):
        if n_test < target:
            test.extend(by_repo[repo])
            n_test += len(by_repo[repo])
        else:
            train.extend(by_repo[repo])
    return _sorted(train), _sorted(test)


def split_by_time(records: list[dict], test_frac: float = 0.2, time_field: str = "created_at"):
    """Chronological: oldest records train, newest test. ISO-8601 strings compare
    lexicographically; ties broken by id so the cut is deterministic. A tie group
    straddling the cut goes entirely to test (no equal-timestamp leakage)."""
    if not 0 < test_frac < 1:
        raise ValueError("test_frac must be in (0,1)")
    ordered = sorted(records, key=lambda r: (str(r[time_field]), str(r["id"])))
    cut = len(ordered) - max(1, round(len(ordered) * test_frac))
    cut = max(cut, 0)
    if 0 < cut < len(ordered):
        boundary = str(ordered[cut][time_field])
        while cut > 0 and str(ordered[cut - 1][time_field]) == boundary:
            cut -= 1
    return ordered[:cut], ordered[cut:]


def _sorted(rs):
    return sorted(rs, key=lambda r: str(r["id"]))


def check_leakage(
    train: list[dict],
    test: list[dict],
    mode: str,
    time_field: str = "created_at",
) -> list[str]:
    """Return human-readable violations; empty means clean."""
    v: list[str] = []
    tr_ids = {str(r["id"]) for r in train}
    for r in test:
        if str(r["id"]) in tr_ids:
            v.append(f"instance {r['id']} appears in both train and test")
    tr_hash = {r["content_hash"] for r in train if r.get("content_hash")}
    for r in test:
        if r.get("content_hash") in tr_hash:
            v.append(f"content hash of {r['id']} also present in train")
    if mode == "repo":
        shared = {r["repo"] for r in train} & {r["repo"] for r in test}
        for repo in sorted(shared):
            v.append(f"repo {repo} appears in both train and test")
    if mode == "time" and train and test:
        max_train = max(str(r[time_field]) for r in train)
        min_test = min(str(r[time_field]) for r in test)
        if max_train >= min_test:
            v.append(
                f"temporal ordering violated: latest train {max_train} >= "
                f"earliest test {min_test}"
            )
    return v


def make_split(
    records: list[dict],
    mode: str,
    seed: int = DEFAULT_SEED,
    test_frac: float = 0.2,
    hash_fields: list[str] | None = None,
    time_field: str = "created_at",
) -> dict:
    """Dedupe, split, check leakage, return a report dict (ids only, no payloads)."""
    if mode not in ("repo", "time"):
        raise ValueError("mode must be 'repo' or 'time'")
    ids = [str(r["id"]) for r in records]
    dup_ids = sorted({i for i in ids if ids.count(i) > 1})
    if dup_ids:
        raise ValueError(f"duplicate instance ids in input: {dup_ids[:5]}")
    kept, dropped = dedupe(records, hash_fields or ["repo", "text"])
    if mode == "repo":
        train, test = split_by_repo(kept, seed, test_frac)
    else:
        train, test = split_by_time(kept, test_frac, time_field)
    violations = check_leakage(train, test, mode, time_field)
    return {
        "mode": mode,
        "seed": seed,
        "test_frac": test_frac,
        "n_input": len(records),
        "n_deduped_dropped": len(dropped),
        "dropped_ids": dropped,
        "n_train": len(train),
        "n_test": len(test),
        "train_ids": [str(r["id"]) for r in train],
        "test_ids": [str(r["id"]) for r in test],
        "violations": violations,
        "ok": not violations,
    }


def split_report_md(rep: dict) -> str:
    lines = [
        f"# Split report ({rep['mode']})",
        "",
        f"- seed: {rep['seed']}; test fraction target: {rep['test_frac']}",
        f"- input: {rep['n_input']}; dropped as duplicates: {rep['n_deduped_dropped']}",
        f"- train: {rep['n_train']}; test: {rep['n_test']}",
        f"- leakage check: {'PASS' if rep['ok'] else 'FAIL'}",
    ]
    for v in rep["violations"]:
        lines.append(f"  - {v}")
    return "\n".join(lines) + "\n"


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _select(manifests, ident):
    if ident is None:
        return manifests
    sel = [m for m in manifests if m["id"] == ident]
    if not sel:
        raise SystemExit(f"unknown dataset id: {ident}")
    return sel


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("validate")
    p = sub.add_parser("verify")
    p.add_argument("--id")
    p = sub.add_parser("fetch")
    p.add_argument("--id", required=True)
    p.add_argument("--yes", action="store_true", help="required: confirm download")
    p.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    p.add_argument("--allow-ci", action="store_true")
    p.add_argument("--path", action="append", help="fetch only this file (repeatable)")
    p = sub.add_parser("license-report")
    p.add_argument("--format", choices=["md", "json"], default="md")
    p = sub.add_parser("split")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--mode", required=True, choices=["repo", "time"])
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--test-frac", type=float, default=0.2)
    p.add_argument("--hash-fields", default="repo,text")
    p.add_argument("--time-field", default="created_at")
    p.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)

    if a.cmd == "split":
        rep = make_split(read_jsonl(a.input), a.mode, a.seed, a.test_frac,
                         a.hash_fields.split(","), a.time_field)
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "split.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
        (a.out / "report.md").write_text(split_report_md(rep), encoding="utf-8")
        print(split_report_md(rep))
        return 0 if rep["ok"] else 1

    manifests = load_manifests()
    if a.cmd == "list":
        for m in manifests:
            print(f"{m['id']:34} {m['status']:10} {m['license']['verdict']:13} {m['name']}")
        return 0
    if a.cmd == "validate":
        schema = load_schema()
        bad = 0
        for m in manifests:
            for e in validate_manifest(m, schema):
                bad += 1
                print(f"{m.get('id')}: {e}")
        print(f"{len(manifests)} manifests, {bad} errors")
        return 1 if bad else 0
    if a.cmd == "verify":
        worst = 0
        for m in _select(manifests, a.id):
            for r in verify_manifest(m):
                print(f"{m['id']}: {r['path']}: {r['status']} {r['detail']}")
                # missing cache files are normal offline; mismatches are failures
                if r["status"] in ("hash-mismatch", "size-mismatch"):
                    worst = 1
        return worst
    if a.cmd == "fetch":
        if not a.yes:
            print("refusing to download without --yes", file=sys.stderr)
            return 2
        if os.environ.get("CI") and not a.allow_ci:
            print("refusing to fetch in CI (pass --allow-ci to override)", file=sys.stderr)
            return 2
        m = _select(manifests, a.id)[0]
        if m["license"]["verdict"] == "unknown":
            print("WARNING: licence UNKNOWN - for local research only; do not redistribute",
                  file=sys.stderr)
        for r in fetch_manifest(m, cache_dir(), a.max_bytes, only_paths=a.path):
            print(f"{m['id']}: {r['path']}: {r['status']}")
        return 0
    if a.cmd == "license-report":
        if a.format == "json":
            print(json.dumps(license_rows(manifests), indent=2))
        else:
            print(license_report_md(manifests))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
