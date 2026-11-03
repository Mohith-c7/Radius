"""Adapter: adjudicated IN-09 gold files -> the IN-10 harness input (``radius.intent.gold/1``).

Use it with the extraction metrics harness, one role at a time::

    python scripts/intent_eval.py run --config exp.json \\
        --gold benchmarks/gold/intent --adapter gold_to_eval:adapt_test

``adapt_dev`` and ``adapt_test`` select PRs by their sampling role. There is
deliberately no all-roles adapter: the preregistration forbids tuning on the test
split, and one dataset file must carry one split. Pilot PRs (including the
calibration round) are never exported; they are not part of any analysis set.

What is exported, and what is refused:

* only ``adjudicated.json`` files with ``status == "complete"``; a PR with a
  pending item, or without an adjudicated file, is an error (never silently
  dropped, because a quietly shrunken test set changes the result);
* explicit criteria whose resolution is not ``dropped``; implicit criteria have no
  span and are not part of the headline extraction metric (GUIDELINES section 4);
* the stored (sanitized) source text that the offsets index;
* ``synthetic`` is true only if every PR is synthetic; a mix is an error. The
  harness then labels its report accordingly.

Stdlib only.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_lib as gl  # noqa: E402

SCHEMA_ID = "radius.intent.gold/1"
EXPORTED_ROLES = ("dev", "test")


class AdapterError(ValueError):
    pass


def adapt_role(path: Path | str, role: str) -> dict:
    """Build the harness gold dict for all PRs of ``role`` under ``path``."""

    if role not in EXPORTED_ROLES:
        raise AdapterError(f"role must be one of {EXPORTED_ROLES}, got {role!r}")
    gold_dir = Path(path)
    cases: list[dict] = []
    synthetic_flags: set[bool] = set()
    problems: list[str] = []
    versions: set[str] = set()
    for pr_id in gl.list_pr_ids(gold_dir):
        src, _anns, adj = gl.load_pr(gold_dir, pr_id)
        pr = src["pr"]
        if pr.get("role") != role:
            continue
        if adj is None or adj.get("status") != "complete":
            problems.append(f"{pr_id}: no complete adjudicated.json")
            continue
        errs, _ = gl.validate_annotation_doc(adj, src, require_complete=True)
        if errs:
            problems.append(f"{pr_id}: adjudicated.json invalid: {errs[0]}")
            continue
        if any(c.get("resolution") == "pending" for c in adj["criteria"]):
            problems.append(f"{pr_id}: pending adjudication items")
            continue
        if any(s["text"] is None for s in src["sources"]):
            problems.append(f"{pr_id}: source text withheld; re-fetch before evaluating")
            continue
        criteria = []
        for c in adj["criteria"]:
            if c.get("resolution") == "dropped" or not c.get("explicit"):
                continue
            span = c["span"]
            criteria.append({
                "id": c["id"],
                "span": {"source_id": span["source_id"], "start": span["start"], "end": span["end"]},
                "testability": c.get("testability"),
                "text": c.get("text"),
            })
        synthetic_flags.add(bool(src.get("synthetic")))
        versions.add(str(adj.get("guidelines_version", "")))
        cases.append({
            "case_id": pr_id,
            "well_specified": adj.get("well_specified"),
            "author_type": pr.get("author_type"),
            "group": (pr.get("stratum") or {}).get("richness"),
            "sources": [
                {"source_id": s["source_id"], "kind": s["kind"], "text": s["text"]}
                for s in src["sources"]
            ],
            "criteria": criteria,
        })
    if problems:
        raise AdapterError(
            f"{len(problems)} PR(s) of role {role!r} are not ready: " + "; ".join(problems[:10])
        )
    if not cases:
        raise AdapterError(f"no PRs of role {role!r} under {gold_dir}")
    if len(synthetic_flags) > 1:
        raise AdapterError("synthetic and real PRs are mixed; refusing to build one dataset")
    return {
        "schema": SCHEMA_ID,
        "name": "radius-intent-gold",
        "version": "+".join(sorted(versions)) or "unknown",
        "split": role,
        "synthetic": synthetic_flags == {True},
        "offset_unit": "codepoint",
        "notes": [
            "Built by scripts/gold_to_eval.py from adjudicated IN-09 files: explicit, non-dropped "
            "criteria only; implicit criteria and links are not exported."
        ],
        "cases": cases,
    }


def adapt_dev(path: Path | str) -> dict:
    return adapt_role(path, "dev")


def adapt_test(path: Path | str) -> dict:
    return adapt_role(path, "test")
