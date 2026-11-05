#!/usr/bin/env python3
"""Run the guarded ``llm`` extraction mode over cached PR texts (owner-run, needs a key).

    ANTHROPIC_API_KEY=... python scripts/llm_extraction_eval.py \
        --meta-dir D:/nuclei/worktrees/replay_cache [--model claude-sonnet-5-5] \
        [--limit 10] [--json out.json]

Input: ``meta-<n>.json`` files written by ``scripts/verdict_v2_replay.py`` (fields
``number``, ``title``, ``body``). For each PR it prints the deterministic ``summary`` criteria
next to the LLM proposals that survived the guard, then the totals and the GROUNDING DROP
RATE: the share of model proposals that the deterministic post-filters removed (quote not
verbatim in the PR text, wording not grounded in the quote, too short, schema violation).

Safety: this sends PR titles and bodies to the model provider, so it only runs with
``ANTHROPIC_API_KEY`` set and prints a notice first. Without the key it exits with code 2
and does nothing (no network). It measures nothing about correctness: there is no ground
truth here, only recall proxy (criteria per PR) and the drop rate. Do not read the output as
precision.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _src in ("packages/intent/src", "packages/github/src", "packages/shared/src"):
    sys.path.insert(0, str(ROOT / _src))

STAMP = datetime(2026, 11, 3, tzinfo=UTC)
#: Output-guard / evidence-check codes that count as a grounding or schema drop.
GROUNDING_DROP_CODES = frozenset(
    {
        "dropped_span_mismatch",
        "dropped_quote_not_in_source",
        "dropped_ungrounded_text",
        "dropped_short_quote",
        "dropped_unknown_source",
        "dropped_schema",
        "dropped_limits",
        "dropped_over_cap",
    }
)


# ------------------------------------------------------------------ pure logic


def load_metas(meta_dir: Path) -> list[dict[str, Any]]:
    """Cached PR metadata sorted by PR number; entries without a title are skipped."""

    out: list[dict[str, Any]] = []
    for path in sorted(
        meta_dir.glob("meta-*.json"), key=lambda p: int(p.stem.split("-")[1])
    ):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("title") is not None and "number" in data:
            out.append(data)
    return out


def grounding_drop_rate(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Share of model proposals removed by the post-filters.

    ``proposed`` = kept + dropped (a rejected whole reply counts once). ``None`` rate when
    the model proposed nothing.
    """

    items = list(rows)
    kept = sum(int(r.get("llm_kept", 0)) for r in items)
    dropped = 0
    by_code: dict[str, int] = {}
    for r in items:
        for code in r.get("llm_dropped", []):
            if code in GROUNDING_DROP_CODES:
                dropped += 1
                by_code[code] = by_code.get(code, 0) + 1
    total = kept + dropped
    return {
        "kept": kept,
        "dropped": dropped,
        "proposed": total,
        "rate": (dropped / total) if total else None,
        "by_code": dict(sorted(by_code.items())),
    }


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    base = [len(r.get("summary", [])) for r in rows]
    llm = [int(r.get("llm_kept", 0)) for r in rows]
    return {
        "prs": n,
        "summary_prs_with_criteria": sum(c > 0 for c in base),
        "summary_total": sum(base),
        "llm_prs_with_criteria": sum(c > 0 for c in llm),
        "llm_total": sum(llm),
        "degraded_runs": sum(int(r.get("llm_degraded", 0)) for r in rows),
        "input_tokens": sum(int(r.get("llm_input_tokens", 0)) for r in rows),
        "output_tokens": sum(int(r.get("llm_output_tokens", 0)) for r in rows),
        "latency_ms": round(sum(float(r.get("llm_latency_ms", 0.0)) for r in rows), 1),
        "grounding": grounding_drop_rate(list(rows)),
    }


def format_row(row: Mapping[str, Any]) -> str:
    head = (
        f"#{row['number']:<4} summary={len(row['summary']):<3} "
        f"llm={row['llm_kept']:<3} dropped={len(row['llm_dropped']):<3} "
        f"{'DEGRADED ' if row['llm_degraded'] else ''}{str(row['title'])[:60]}"
    )
    lines = [head]
    lines += [f"    summary  - {c}" for c in row["summary"]]
    lines += [f"    llm      - {c}" for c in row["llm"]]
    return "\n".join(lines)


def format_summary(s: Mapping[str, Any]) -> str:
    g = s["grounding"]
    rate = "n/a (the model proposed nothing)" if g["rate"] is None else f"{g['rate']:.1%}"
    return "\n".join(
        [
            f"PRs: {s['prs']}",
            f"summary: PRs with >=1 criterion {s['summary_prs_with_criteria']}/{s['prs']}, "
            f"total {s['summary_total']}",
            f"llm:     PRs with >=1 criterion {s['llm_prs_with_criteria']}/{s['prs']}, "
            f"total {s['llm_total']}, degraded runs {s['degraded_runs']}",
            f"grounding drop rate: {rate} ({g['dropped']} dropped of {g['proposed']} proposed; "
            f"{g['by_code']})",
            f"usage: {s['input_tokens']} input / {s['output_tokens']} output tokens, "
            f"{s['latency_ms']} ms of model latency",
        ]
    )


# ------------------------------------------------------------------ runner


def run(
    metas: Sequence[Mapping[str, Any]],
    provider: Any,
    *,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Run summary and llm extraction per PR with ``provider`` (a real or fake LlmProvider)."""

    from radius_github.intent_sources import pull_request_outcomes
    from radius_intent.infrastructure.extraction import (
        DeterministicCriterionExtractor,
        ExtractionConfig,
    )
    from radius_intent.infrastructure.llm import (
        EnvEgressPolicy,
        LlmCriterionExtractor,
        LlmExtractionConfig,
        PrTextLlmExtractor,
    )

    config = LlmExtractionConfig(enabled=True, orgs=frozenset({"*"}))
    rows: list[dict[str, Any]] = []
    for pr in metas:
        outcomes = pull_request_outcomes(
            pr["title"], pr.get("body") or "", now=STAMP, origin="rest_api"
        )
        sources = [o.source for o in outcomes if o.source is not None]
        det = DeterministicCriterionExtractor(ExtractionConfig(mode="summary"))
        summary = [c.text for s in sources for c in det.extract(s)]
        # fresh extractor per PR: no cache or ledger shared across PRs
        llm = PrTextLlmExtractor(
            LlmCriterionExtractor(
                provider,
                organization_id="eval",
                config=config,
                policy=EnvEgressPolicy(True, frozenset({"*"})),
            )
        )
        proposed = [c.text for s in sources for c in llm.extract(s)]
        runs = llm.runs
        rows.append(
            {
                "number": int(pr["number"]),
                "title": pr["title"],
                "summary": summary,
                "llm": proposed,
                "llm_kept": len(proposed),
                "llm_dropped": [code for r in runs for code in r.dropped_codes],
                "llm_degraded": sum(1 for r in runs if r.degraded),
                "llm_degraded_reasons": [r.degraded_reason for r in runs if r.degraded],
                "llm_input_tokens": sum(r.input_tokens for r in runs),
                "llm_output_tokens": sum(r.output_tokens for r in runs),
                "llm_latency_ms": round(sum(r.latency_ms for r in runs), 1),
                "model": next((r.model for r in runs if r.model), model),
            }
        )
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--meta-dir", type=Path, required=True)
    ap.add_argument("--model", default=None, help="model id (default: RADIUS_LLM_INTENT_MODEL)")
    ap.add_argument("--limit", type=int, default=0, help="only the first N PRs (0 = all)")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        print(
            "ANTHROPIC_API_KEY is not set: nothing was sent and nothing was run.",
            file=sys.stderr,
        )
        return 2
    from radius_intent.infrastructure.llm import LlmExtractionConfig
    from radius_intent.infrastructure.llm.anthropic_provider import AnthropicProvider

    model = args.model or LlmExtractionConfig.from_env(os.environ).model
    metas = load_metas(args.meta_dir)
    if args.limit > 0:
        metas = metas[: args.limit]
    print(
        f"NOTICE: sending the title and body of {len(metas)} PR(s) to the model provider "
        f"(model {model}).",
        file=sys.stderr,
    )
    rows = run(metas, AnthropicProvider(model), model=model)
    for row in rows:
        print(format_row(row))
    summary = summarize(rows)
    print(format_summary(summary))
    if args.json:
        args.json.write_text(
            json.dumps({"rows": rows, "summary": summary}, indent=1), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
