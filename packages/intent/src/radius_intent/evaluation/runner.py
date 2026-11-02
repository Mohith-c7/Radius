"""Run extractors over a gold set and assemble the run record (EP-05 style).

The record (``run.json``) is the single source of truth: ``report`` and
``compare`` re-derive tables and paired statistics from its per-PR count
vectors, so no information is lost between a run and later analysis.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import ExperimentConfig
from .extractors import ExtractionOutcome, HarnessExtractor
from .gold import GoldDataset
from .metrics import (
    CaseScore,
    compute_metrics,
    confusion_matrix,
    group_counts,
    group_names,
    score_case,
)
from .stats import bootstrap_metrics, sum_vectors

HARNESS_VERSION = "intent-eval-v1"
SYNTHETIC_LABEL = "SYNTHETIC — not a research result"
RUN_FILE = "run.json"
REPORT_JSON = "report.json"
REPORT_MD = "report.md"


@dataclass(frozen=True)
class RunArtifacts:
    """The run record plus files that belong next to it (not inside it)."""

    record: dict[str, Any]
    extras: dict[str, dict[str, Any]]


def slug(text: str) -> str:
    out = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")
    return out or "run"


def make_run_id(config: ExperimentConfig, dataset: GoldDataset) -> str:
    """Deterministic id: name, config hash prefix, dataset hash prefix."""
    return f"{slug(config.name)}-{config.sha256[:8]}-{dataset.sha256[:8]}"


def _dataset_summary(dataset: GoldDataset) -> dict[str, Any]:
    return {
        "name": dataset.name,
        "version": dataset.version,
        "split": dataset.split,
        "synthetic": dataset.synthetic,
        "sha256": dataset.sha256,
        "n_cases": len(dataset.cases),
        "n_gold_criteria": sum(len(c.criteria) for c in dataset.cases),
        "n_cases_without_gold": sum(1 for c in dataset.cases if not c.criteria),
        "warnings": list(dataset.warnings),
        "notes": list(dataset.notes),
    }


def run_experiment(
    config: ExperimentConfig,
    dataset: GoldDataset,
    extractors: Sequence[HarnessExtractor],
    *,
    provenance: Mapping[str, Any] | None = None,
    timer: Callable[[], float] = time.perf_counter,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> RunArtifacts:
    """Execute every extractor on every PR and bootstrap the metrics."""
    started = now()
    t_run = timer()
    cases = sorted(dataset.cases, key=lambda c: c.case_id)
    entries: dict[str, Any] = {}
    extras: dict[str, dict[str, Any]] = {}
    versions: dict[str, Any] = {}
    for ex in extractors:
        t0 = timer()
        scores: list[CaseScore] = []
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "llm_calls": 0,
            "cache_hits": 0,
            "cases_with_diagnostics": 0,
        }
        errors: list[dict[str, str]] = []
        for case in cases:
            try:
                outcome = ex.extract(case)
            except Exception as exc:  # one bad PR must not hide the others
                errors.append({"case_id": case.case_id, "error": repr(exc)})
                outcome = ExtractionOutcome(())
            usage["input_tokens"] += outcome.input_tokens
            usage["output_tokens"] += outcome.output_tokens
            usage["llm_calls"] += outcome.llm_calls
            usage["cache_hits"] += outcome.cache_hits
            usage["cases_with_diagnostics"] += bool(outcome.diagnostics)
            scores.append(score_case(case, outcome.criteria, config.matching))
        vectors = [s.vector for s in scores]
        totals = sum_vectors(vectors)
        intervals = bootstrap_metrics(
            vectors,
            compute_metrics,
            resamples=config.resamples,
            seed=config.seed,
            confidence=config.confidence,
        )
        if config.price_per_mtok:
            p_in, p_out = config.price_per_mtok
            usage["estimated_cost_usd"] = round(
                usage["input_tokens"] / 1e6 * p_in + usage["output_tokens"] / 1e6 * p_out,
                6,
            )
        elapsed = timer() - t0
        describe = ex.describe()
        versions[ex.spec.extractor_id] = describe
        entries[ex.spec.extractor_id] = {
            "id": ex.spec.extractor_id,
            "kind": ex.spec.kind,
            "describe": describe,
            "metrics": {k: v.as_dict() for k, v in intervals.items()},
            "totals": dict(sorted(totals.items())),
            "groups": {
                g: {
                    mode: group_counts(totals, g, mode)
                    for mode in ("iou", "text_exact", "text_fuzzy")
                }
                for g in group_names(totals)
            },
            "confusion": confusion_matrix(totals),
            "usage": usage,
            "errors": errors,
            "timing_s": round(elapsed, 4),
            "cases": {
                s.case_id: {
                    "vector": dict(sorted(s.vector.items())),
                    "n_pred": s.n_pred,
                    "n_gold": s.n_gold,
                    "false_positives": list(s.false_positives),
                    "false_negatives": list(s.false_negatives),
                }
                for s in scores
            },
        }
        extra = ex.finalize()
        if extra:
            extras[ex.spec.extractor_id] = extra
    manifest: dict[str, Any] = {
        "harness_version": HARNESS_VERSION,
        "label": SYNTHETIC_LABEL if dataset.synthetic else None,
        "run_id": make_run_id(config, dataset),
        "config_sha256": config.sha256,
        "config": config.as_dict(),
        "dataset": _dataset_summary(dataset),
        "seeds": {"bootstrap": config.seed},
        "versions": versions,
        "case_order": [c.case_id for c in cases],
        "created_at": started.isoformat(),
        "timings_s": {"total": round(timer() - t_run, 4)},
        **dict(provenance or {}),
    }
    return RunArtifacts({"manifest": manifest, "extractors": entries}, extras)


def write_run(artifacts: RunArtifacts, out_dir: Path) -> Path:
    """Write ``run.json`` and any extras (for example LLM recordings)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / RUN_FILE).write_text(
        json.dumps(artifacts.record, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    for extractor_id, extra in artifacts.extras.items():
        for name, payload in extra.items():
            (out_dir / f"{slug(extractor_id)}.{name}.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
    return out_dir / RUN_FILE


def load_run(path: Path) -> dict[str, Any]:
    """Read a run directory or ``run.json`` file."""
    file = path / RUN_FILE if path.is_dir() else path
    try:
        record = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read run record {file}: {exc}") from exc
    if not isinstance(record, dict) or "manifest" not in record:
        raise ValueError(f"{file} is not a run record")
    return record
