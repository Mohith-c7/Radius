#!/usr/bin/env python3
"""Run sections vs summary extraction over cached PR metadata (read-only).

    python scripts/intent_summary_eval.py --meta-dir D:/nuclei/worktrees/replay_cache [--json out.json]

Reads ``meta-<n>.json`` files written earlier by ``scripts/verdict_v2_replay.py`` (fields
``number``, ``title``, ``body``). No network. Prints criteria per PR for both modes and the
summary-mode criteria with the rule that matched. A recall PROXY only: there is no ground truth.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _src in ("packages/intent/src", "packages/github/src", "packages/shared/src"):
    sys.path.insert(0, str(ROOT / _src))

STAMP = datetime(2026, 11, 3, tzinfo=UTC)


def run(meta_dir: Path) -> list[dict]:
    from radius_github.intent_sources import pull_request_outcomes
    from radius_intent.infrastructure.extraction import (
        DeterministicCriterionExtractor,
        ExtractionConfig,
    )

    out = []
    for path in sorted(
        meta_dir.glob("meta-*.json"), key=lambda p: int(p.stem.split("-")[1])
    ):
        pr = json.loads(path.read_text(encoding="utf-8"))
        outcomes = pull_request_outcomes(
            pr["title"], pr.get("body") or "", now=STAMP, origin="rest_api"
        )
        sources = [o.source for o in outcomes if o.source is not None]
        row: dict = {"number": int(pr["number"]), "title": pr["title"]}
        for mode in ("sections", "summary"):
            rep = DeterministicCriterionExtractor(
                ExtractionConfig(mode=mode)
            ).extract_sources(sources)
            rules = {t.criterion_id: t.rule for t in rep.traces}
            row[mode] = [
                {
                    "id": c.id,
                    "text": c.text,
                    "rule": rules.get(c.id),
                    "weight": c.weight,
                    "source": c.origin.source.kind.value,
                    "extractor_version": c.origin.extractor_version,
                }
                for c in rep.criteria
            ]
        out.append(row)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta-dir", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    rows = run(args.meta_dir)
    for r in rows:
        print(
            f"#{r['number']:<4} sections={len(r['sections']):<3} summary={len(r['summary']):<3} {r['title'][:70]}"
        )
    n = len(rows)
    for mode in ("sections", "summary"):
        counts = [len(r[mode]) for r in rows]
        print(
            f"{mode}: PRs with >=1 criterion {sum(c > 0 for c in counts)}/{n}, total {sum(counts)}, max {max(counts)}"
        )
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
