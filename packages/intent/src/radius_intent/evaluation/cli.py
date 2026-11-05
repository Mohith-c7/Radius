"""Command line for the extraction metrics harness.

    python -m radius_intent.evaluation list-extractors
    python -m radius_intent.evaluation run --config experiment.json
    python -m radius_intent.evaluation report benchmarks/results/intent/<run-id>
    python -m radius_intent.evaluation compare RUN_A RUN_B --a-extractor det --b-extractor llm

``run`` never makes network calls unless the config names the ``anthropic``
provider AND ``--allow-real-llm`` is passed AND ``RADIUS_EVAL_ALLOW_REAL_LLM=1``
is set.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO, Any

from .compare import CompareError, compare_runs
from .config import (
    ConfigError,
    ExperimentConfig,
    ExtractorSpec,
    parse_config,
)
from .extractors import PROVIDER_TYPES, build_extractor, list_kinds
from .loader import GoldLoadError, load_gold
from .provenance import environment, git_state, hash_path
from .report import render_compare_markdown, render_markdown, render_summary_json
from .runner import (
    REPORT_JSON,
    REPORT_MD,
    load_run,
    make_run_id,
    run_experiment,
    write_run,
)

DEFAULT_OUT_ROOT = "benchmarks/results/intent"


class _Failure(Exception):
    """User-facing failure with an exit code."""

    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="intent_eval",
        description="Intent extraction metrics harness (IN-10, RQ1).",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run extractors over a gold set")
    run.add_argument("--config", required=True, help="experiment config (JSON)")
    run.add_argument("--gold", help="gold path (overrides config gold.path)")
    run.add_argument("--adapter", help="gold adapter (overrides config gold.adapter)")
    run.add_argument("--seed", type=int, help="bootstrap seed (overrides config)")
    run.add_argument("--resamples", type=int, help="bootstrap resamples (overrides config)")
    run.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    run.add_argument("--run-id", help="output directory name (default: derived)")
    run.add_argument(
        "--allow-real-llm",
        action="store_true",
        help="permit the 'anthropic' provider (also needs RADIUS_EVAL_ALLOW_REAL_LLM=1)",
    )
    run.add_argument("--quiet", action="store_true", help="do not print the report")

    rep = sub.add_parser("report", help="render a stored run")
    rep.add_argument("run", help="run directory or run.json")
    rep.add_argument("--format", choices=("md", "json"), default="md")
    rep.add_argument("--out", help="write to this file instead of stdout")

    cmp_ = sub.add_parser("compare", help="paired bootstrap comparison of two runs")
    cmp_.add_argument("run_a")
    cmp_.add_argument("run_b")
    cmp_.add_argument("--a-extractor")
    cmp_.add_argument("--b-extractor")
    cmp_.add_argument("--resamples", type=int)
    cmp_.add_argument("--seed", type=int)
    cmp_.add_argument("--allow-dataset-mismatch", action="store_true")
    cmp_.add_argument("--format", choices=("md", "json"), default="md")
    cmp_.add_argument("--out", help="write to this file instead of stdout")

    lst = sub.add_parser("list-extractors", help="show extractor kinds and versions")
    lst.add_argument("--json", action="store_true")
    return ap


def _load_config(args: argparse.Namespace) -> tuple[ExperimentConfig, Path]:
    path = Path(args.config)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise _Failure(f"cannot read config {path}: {exc}") from exc
    except ValueError as exc:
        raise _Failure(f"invalid JSON in {path}: {exc}") from exc
    try:
        config = parse_config(doc)
    except ConfigError as exc:
        raise _Failure(f"{path}: {exc}") from exc
    overrides: dict[str, Any] = {}
    if args.seed is not None:
        overrides["seed"] = args.seed
    if args.resamples is not None:
        if args.resamples < 1:
            raise _Failure("--resamples must be >= 1")
        overrides["resamples"] = args.resamples
    if args.gold:
        overrides["gold_path"] = args.gold
    if args.adapter:
        overrides["gold_adapter"] = args.adapter
    return dataclasses.replace(config, **overrides), path.resolve().parent


def _resolve_gold(config: ExperimentConfig, config_dir: Path) -> Path:
    if not config.gold_path:
        raise _Failure("no gold path: set gold.path in the config or pass --gold")
    given = Path(config.gold_path)
    for candidate in (given, config_dir / given):
        if candidate.exists():
            return candidate
    raise _Failure(f"gold path not found: {config.gold_path}")


def _cmd_run(args: argparse.Namespace, out: IO[str], environ: Mapping[str, str]) -> int:
    config, config_dir = _load_config(args)
    gold_path = _resolve_gold(config, config_dir)
    try:
        dataset = load_gold(gold_path, config.gold_adapter)
    except GoldLoadError as exc:
        raise _Failure(str(exc)) from exc
    try:
        extractors = [
            build_extractor(
                spec,
                rate_testability=config.rate_testability,
                allow_real_llm=args.allow_real_llm,
                environ=environ,
                base_dir=str(config_dir),
            )
            for spec in config.extractors
        ]
    except ConfigError as exc:
        raise _Failure(str(exc)) from exc
    provenance = {
        "git": git_state(Path.cwd()),
        "environment": environment(),
        "gold_source": {
            "path": gold_path.as_posix(),
            "adapter": config.gold_adapter,
            "files_sha256": hash_path(gold_path),
        },
    }
    artifacts = run_experiment(config, dataset, extractors, provenance=provenance)
    run_id = args.run_id or make_run_id(config, dataset)
    artifacts.record["manifest"]["run_id"] = run_id
    out_dir = Path(args.out_root) / run_id
    write_run(artifacts, out_dir)
    (out_dir / REPORT_JSON).write_text(render_summary_json(artifacts.record), encoding="utf-8")
    markdown = render_markdown(artifacts.record)
    (out_dir / REPORT_MD).write_text(markdown, encoding="utf-8")
    if not args.quiet:
        out.write(markdown + "\n")
    out.write(f"wrote {out_dir.as_posix()}\n")
    return 0


def _emit(text: str, out_file: str | None, out: IO[str]) -> None:
    if out_file:
        Path(out_file).write_text(text, encoding="utf-8")
        out.write(f"wrote {out_file}\n")
    else:
        out.write(text if text.endswith("\n") else text + "\n")


def _load_run_or_fail(path: str) -> dict[str, Any]:
    try:
        return load_run(Path(path))
    except ValueError as exc:
        raise _Failure(str(exc)) from exc


def _cmd_report(args: argparse.Namespace, out: IO[str]) -> int:
    record = _load_run_or_fail(args.run)
    text = render_markdown(record) if args.format == "md" else render_summary_json(record)
    _emit(text, args.out, out)
    return 0


def _cmd_compare(args: argparse.Namespace, out: IO[str]) -> int:
    a, b = _load_run_or_fail(args.run_a), _load_run_or_fail(args.run_b)
    try:
        result = compare_runs(
            a,
            b,
            extractor_a=args.a_extractor,
            extractor_b=args.b_extractor,
            resamples=args.resamples,
            seed=args.seed,
            allow_dataset_mismatch=args.allow_dataset_mismatch,
        )
    except CompareError as exc:
        raise _Failure(str(exc)) from exc
    text = (
        render_compare_markdown(result)
        if args.format == "md"
        else json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    _emit(text, args.out, out)
    return 0


def _cmd_list(args: argparse.Namespace, out: IO[str]) -> int:
    kinds = list_kinds()
    if args.json:
        payload = {
            "kinds": [dataclasses.asdict(k) for k in kinds],
            "providers": PROVIDER_TYPES,
        }
        out.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return 0
    for k in kinds:
        versions = ", ".join(f"{n}={v}" for n, v in sorted(k.versions.items()))
        out.write(f"{k.kind:<14} {k.summary}\n")
        if versions:
            out.write(f"{'':<14} versions: {versions}\n")
        if k.options:
            out.write(f"{'':<14} options: {', '.join(k.options)}\n")
    out.write("\nLLM providers (option provider.type):\n")
    for name, summary in PROVIDER_TYPES.items():
        out.write(f"  {name:<12} {summary}\n")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Entry point; returns the process exit code."""
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    env = os.environ if environ is None else environ
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            return _cmd_run(args, out, env)
        if args.command == "report":
            return _cmd_report(args, out)
        if args.command == "compare":
            return _cmd_compare(args, out)
        return _cmd_list(args, out)
    except _Failure as exc:
        err.write(f"error: {exc}\n")
        return exc.code


# keep ExtractorSpec importable from the CLI module for scripted experiments
__all__ = ["ExtractorSpec", "main"]
