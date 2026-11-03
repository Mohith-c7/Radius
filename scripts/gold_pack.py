"""Offline annotator kit: export blinded tasks, import the completed annotations (IN-09).

For a second annotator who works on another machine, without the Radius
repository, network access or the product::

    python scripts/gold_pack.py export --annotator bob --seed 20261102 --out kit-bob/ \\
        [--prs ids.txt] [--first calibration.txt] [--allow-synthetic]
    # bob: cd kit-bob && python scripts/gold_annotate.py serve --annotator bob --queue queue.txt --open
    # bob returns the folder (or just benchmarks/gold/intent/*/annotator-bob.json)
    python scripts/gold_pack.py import --kit kit-bob/ [--gold-dir DIR] [--include-incomplete]

The kit is self-contained and stdlib only: the annotation tool, the schema, the
guidelines, ``queue.txt`` (a seeded, annotator-specific random order) and one
``sources.json`` per assigned PR. **Blinding:** the kit never contains another
annotator's file, an adjudicated file, a candidate-criteria list or any Radius
output. Candidate criteria are deliberately not shown: a pre-filled list anchors
the annotator (PREREGISTRATION 5.1); the annotator selects spans in the text
themselves.

``import`` is all-or-nothing and checks, against the *repository's own*
``sources.json`` (not the kit's copy): the schema and every semantic rule of
``gold_lib.validate_annotation_doc`` (spans equal the stored text, sources digest,
labels), that the file belongs to the annotator named in the kit manifest, that
the kit's source files were not altered (sha256 in ``KIT_MANIFEST.json``), that
no foreign file is present, and that nothing is overwritten without ``--force``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_lib as gl  # noqa: E402

KIT_VERSION = "gold-kit-pack-1"
KIT_MANIFEST = "KIT_MANIFEST.json"
SCRIPTS = ("gold_annotate.py", "gold_lib.py")
DOCS = (
    ("docs/research/annotation/GUIDELINES.md", "docs/GUIDELINES.md"),
    ("docs/research/datasets/ANNOTATION_GUIDE.md", "docs/ANNOTATION_GUIDE.md"),
)
README = """\
Radius gold annotation kit (offline)

Annotator: {annotator}      PRs: {n}      Guidelines: {gl}{synthetic}

1. Read docs/ANNOTATION_GUIDE.md, then docs/GUIDELINES.md.
2. Start the tool (Python 3.12, nothing to install, no network needed):
       python scripts/gold_annotate.py serve --annotator {annotator} --queue queue.txt --open{allow}
   Work through the PRs in the order of queue.txt. Do not reorder, skip around or
   look anything up about these PRs. Your work is saved after every change.
3. Do not discuss PRs with the other annotator, do not use an AI assistant, and do
   not open other people's files.
4. When finished, send back this whole folder (or only the files named
   benchmarks/gold/intent/<pr>/annotator-{annotator}.json) to the person who gave
   it to you. The texts are third-party content for annotation only: do not paste
   them anywhere else, and delete the kit when told to.
"""


class PackError(ValueError):
    pass


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _read_ids(path: str | None) -> list[str] | None:
    if not path:
        return None
    return [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]


def build_queue(pr_ids: list[str], annotator: str, seed: int, first: list[str] | None) -> list[str]:
    """Seeded, annotator-specific order; ``first`` ids (for example calibration) lead."""

    rng = random.Random(f"{seed}:{annotator}")
    head = [p for p in (first or []) if p in set(pr_ids)]
    rest = [p for p in pr_ids if p not in set(head)]
    rng.shuffle(head)
    rng.shuffle(rest)
    return head + rest


def export_kit(
    gold_dir: Path, annotator: str, out: Path, *, seed: int,
    pr_ids: list[str] | None = None, first: list[str] | None = None,
    allow_synthetic: bool = False, force: bool = False,
) -> dict:
    gl.check_annotator_id(annotator)
    gold_dir, out = Path(gold_dir), Path(out)
    if out.exists() and any(out.iterdir()):
        if not force:
            raise PackError(f"{out} is not empty (use --force to replace an earlier kit)")
        if not (out / KIT_MANIFEST).exists():
            raise PackError(f"{out} is not empty and is not a kit; refusing to delete it")
    conflicts = gl.load_conflicts(gold_dir)
    chosen: list[str] = []
    skipped: list[dict] = []
    docs: dict[str, dict] = {}
    for pid in pr_ids if pr_ids is not None else gl.list_pr_ids(gold_dir):
        path = gl.pr_dir(gold_dir, pid) / "sources.json"
        if not path.exists():
            skipped.append({"pr_id": pid, "reason": "no sources.json"})
            continue
        doc = gl.read_json(path)
        errs = gl.validate_sources_doc(doc)
        reason = None
        if errs:
            reason = f"sources.json invalid: {errs[0]}"
        elif doc.get("synthetic") and not allow_synthetic:
            reason = "synthetic (pass --allow-synthetic)"
        elif any(s["text"] is None for s in doc["sources"]):
            reason = "source text withheld"
        else:
            reason = gl.has_conflict(conflicts, annotator, doc)
        if reason:
            skipped.append({"pr_id": pid, "reason": reason})
            continue
        chosen.append(pid)
        docs[pid] = doc
    if not chosen:
        raise PackError("no PR is assignable to this annotator")
    synth = {bool(d.get("synthetic")) for d in docs.values()}
    if len(synth) > 1:
        raise PackError("synthetic and real PRs are mixed")
    queue = build_queue(chosen, annotator, seed, first)

    if out.exists() and force:
        shutil.rmtree(out)
    files: dict[str, str] = {}

    def put(rel: str, data: bytes) -> None:
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files[rel] = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()

    here = Path(__file__).resolve().parent
    for name in SCRIPTS:
        put(f"scripts/{name}", (here / name).read_bytes())
    put("benchmarks/gold/intent/schema.json", gl.SCHEMA_PATH.read_bytes())
    for src_rel, dst_rel in DOCS:
        src = gl.REPO_ROOT / src_rel
        if src.exists():
            put(dst_rel, src.read_bytes())
    for pid in chosen:
        put(f"benchmarks/gold/intent/{pid}/sources.json",
            (gl.pr_dir(gold_dir, pid) / "sources.json").read_bytes())
    put("queue.txt", ("\n".join(queue) + "\n").encode("utf-8"))
    is_synth = synth == {True}
    put("README.txt", README.format(
        annotator=annotator, n=len(chosen), gl=gl.GUIDELINES_VERSION,
        synthetic="      SYNTHETIC (test data)" if is_synth else "",
        allow=" --allow-synthetic" if is_synth else "",
    ).encode("utf-8"))
    manifest = {
        "kit_version": KIT_VERSION,
        "guidelines_version": gl.GUIDELINES_VERSION,
        "annotator": annotator,
        "seed": seed,
        "synthetic": is_synth,
        "blinded": True,
        "queue": queue,
        "sources_digest": {pid: docs[pid]["sources_digest"] for pid in chosen},
        "files": dict(sorted(files.items())),
        "skipped": skipped,
    }
    (out / KIT_MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _check_kit_integrity(kit: Path, manifest: dict) -> list[str]:
    errors: list[str] = []
    for rel, digest in manifest["files"].items():
        p = kit / rel
        if not p.exists():
            errors.append(f"kit file missing: {rel}")
        elif rel.startswith("benchmarks/gold/intent/") and rel.endswith("sources.json") and _sha256_file(p) != digest:
            errors.append(f"{rel}: source text was altered after export")
    root = kit / "benchmarks" / "gold" / "intent"
    allowed_pr = set(manifest["sources_digest"])
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if d.name not in allowed_pr:
            errors.append(f"{d.name}: PR is not part of this kit")
            continue
        for f in d.iterdir():
            if f.name == "sources.json":
                continue
            if f.name != f"annotator-{manifest['annotator']}.json":
                errors.append(f"{d.name}/{f.name}: foreign file in the kit (only annotator-{manifest['annotator']}.json is accepted)")
    return errors


def import_kit(kit: Path, gold_dir: Path, *, include_incomplete: bool = False,
               force: bool = False, allow_synthetic: bool = False) -> dict:
    kit, gold_dir = Path(kit), Path(gold_dir)
    mpath = kit / KIT_MANIFEST
    if not mpath.exists():
        raise PackError(f"{mpath} not found: not a kit")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    annotator = manifest["annotator"]
    gl.check_annotator_id(annotator)
    if manifest.get("synthetic") and not allow_synthetic:
        raise PackError("kit is synthetic (pass --allow-synthetic)")
    errors = _check_kit_integrity(kit, manifest)
    ready: list[tuple[str, Path, dict]] = []
    incomplete: list[str] = []
    missing: list[str] = []
    for pid in manifest["queue"]:
        f = kit / "benchmarks" / "gold" / "intent" / pid / f"annotator-{annotator}.json"
        if not f.exists():
            missing.append(pid)
            continue
        target_src_path = gl.pr_dir(gold_dir, pid) / "sources.json"
        if not target_src_path.exists():
            errors.append(f"{pid}: not present in the target gold dir {gold_dir}")
            continue
        src = gl.read_json(target_src_path)
        if src["sources_digest"] != manifest["sources_digest"][pid]:
            errors.append(f"{pid}: sources differ from the ones exported (digest mismatch)")
            continue
        try:
            doc = gl.read_json(f)
        except (OSError, ValueError) as exc:
            errors.append(f"{pid}: unreadable annotation: {exc}")
            continue
        if doc.get("annotator_id") != annotator or doc.get("kind") == "adjudicated":
            errors.append(f"{pid}: annotation does not belong to {annotator}")
            continue
        errs, _warn = gl.validate_annotation_doc(doc, src, require_complete=False)
        if errs:
            errors.append(f"{pid}: {errs[0]}" + (f" (+{len(errs) - 1} more)" if len(errs) > 1 else ""))
            continue
        if doc["status"] != "complete" and not include_incomplete:
            incomplete.append(pid)
            continue
        dest = gl.pr_dir(gold_dir, pid) / f"annotator-{annotator}.json"
        if dest.exists() and not force:
            errors.append(f"{pid}: {dest.name} already exists in the gold dir (use --force)")
            continue
        ready.append((pid, dest, doc))
    result = {"annotator": annotator, "imported": [], "incomplete": incomplete,
              "missing": missing, "errors": errors}
    if errors:
        return result  # all-or-nothing: nothing is written
    for pid, dest, doc in ready:
        gl.write_json_atomic(dest, doc)
        result["imported"].append(pid)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--gold-dir", default=str(gl.GOLD_DIR))
    e.add_argument("--annotator", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--seed", type=int, required=True)
    e.add_argument("--prs", help="file with one pr id per line (default: all)")
    e.add_argument("--first", help="file with pr ids to put first (for example the calibration PRs)")
    e.add_argument("--allow-synthetic", action="store_true")
    e.add_argument("--force", action="store_true")
    i = sub.add_parser("import")
    i.add_argument("--kit", required=True)
    i.add_argument("--gold-dir", default=str(gl.GOLD_DIR))
    i.add_argument("--include-incomplete", action="store_true")
    i.add_argument("--allow-synthetic", action="store_true")
    i.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "export":
            m = export_kit(Path(args.gold_dir), args.annotator, Path(args.out), seed=args.seed,
                           pr_ids=_read_ids(args.prs), first=_read_ids(args.first),
                           allow_synthetic=args.allow_synthetic, force=args.force)
            print(f"kit for {m['annotator']}: {len(m['queue'])} PRs, {len(m['skipped'])} skipped -> {args.out}")
            for s in m["skipped"]:
                print(f"  skipped {s['pr_id']}: {s['reason']}")
            return 0
        r = import_kit(Path(args.kit), Path(args.gold_dir), include_incomplete=args.include_incomplete,
                       force=args.force, allow_synthetic=args.allow_synthetic)
    except (PackError, gl.GoldError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for msg in r["errors"]:
        print(f"error: {msg}", file=sys.stderr)
    print(f"annotator {r['annotator']}: imported {len(r['imported'])}, incomplete {len(r['incomplete'])}, "
          f"not started {len(r['missing'])}, errors {len(r['errors'])}")
    return 2 if r["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
