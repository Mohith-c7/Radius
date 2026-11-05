"""Validate gold files and export a public (text-free) copy.

    python scripts/gold_validate.py check [--gold-dir DIR] [--complete] [--allow-synthetic]
    python scripts/gold_validate.py export-public --gold-dir DIR --out DIR

``check`` validates every ``<pr-id>/`` directory: schema, source hashes and
digest, span bounds, span text equal to the stored slice, trimmed spans,
annotator/adjudicator rules. Exit status 1 on any error.

``export-public`` writes sources with ``text`` removed (hashes and lengths kept)
and explicit criteria with ``text`` removed, so third-party PR text is not
redistributed (DATA_HYGIENE sections 2 and 6). Spans stay verifiable by anyone
who re-fetches the sources and matches ``text_sha256``. Only PRs with a
complete ``adjudicated.json`` are exported, and only the adjudicated file.
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_lib as gl  # noqa: E402


def public_copy(sources_doc: dict, adjudicated: dict) -> tuple[dict, dict]:
    src = copy.deepcopy(sources_doc)
    adj = copy.deepcopy(adjudicated)
    for s in src["sources"]:
        s["text"] = None
    src["text_redistributable"] = False
    src["pr"].pop("author_login_sha256", None)
    adj["criteria"] = [c for c in adj["criteria"] if c.get("resolution") != "dropped"]
    for c in adj["criteria"]:
        c.pop("options", None)
        c.pop("notes", None)
        if c["explicit"]:
            c["text"] = None
    adj.pop("notes", None)
    return src, adj


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--gold-dir", default=str(gl.GOLD_DIR))
    c.add_argument("--complete", action="store_true", help="require status complete")
    c.add_argument("--allow-synthetic", action="store_true")
    e = sub.add_parser("export-public")
    e.add_argument("--gold-dir", default=str(gl.GOLD_DIR))
    e.add_argument("--out", required=True)
    e.add_argument("--allow-synthetic", action="store_true")
    args = ap.parse_args(argv)
    gold_dir = Path(args.gold_dir)
    ids = gl.list_pr_ids(gold_dir)
    if args.cmd == "check":
        n_err = 0
        for pid in ids:
            errs, warns = gl.validate_pr_dir(
                gold_dir, pid, require_complete=args.complete, allow_synthetic=args.allow_synthetic
            )
            for line in errs:
                print("ERROR", line)
            for line in warns:
                print("warn ", line)
            n_err += len(errs)
        print(f"{len(ids)} PR dir(s) checked, {n_err} error(s)")
        return 1 if n_err else 0
    out = Path(args.out)
    exported = 0
    for pid in ids:
        src, _anns, adj = gl.load_pr(gold_dir, pid)
        if adj is None or adj.get("status") != "complete":
            continue
        errs, _ = gl.validate_pr_dir(gold_dir, pid, require_complete=False,
                                     allow_synthetic=args.allow_synthetic)
        if errs:
            print("ERROR", errs[0], file=sys.stderr)
            return 1
        psrc, padj = public_copy(src, adj)
        gl.write_json_atomic(out / pid / "sources.json", psrc)
        gl.write_json_atomic(out / pid / "adjudicated.json", padj)
        exported += 1
    print(f"exported {exported} PR(s) to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
