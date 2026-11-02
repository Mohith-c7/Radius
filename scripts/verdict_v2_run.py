#!/usr/bin/env python
"""Run the whole Verdict v2 pipeline on the 8 F-14 fixtures (first end-to-end demo).

    python scripts/verdict_v2_run.py                       # all fixtures, gold + auto
    python scripts/verdict_v2_run.py 08 --mode auto --markdown
    python scripts/verdict_v2_run.py --source bundle       # Stage B on the VS-01 bundles

Modes (``--source collect``, the default, runs the real Stage A on the fixture checkout):

* ``gold``: the fixture's ``expected.json`` links are given as ``.radius/intent.yml``
  hints (``paths`` = the gold symbol file, ``tests`` = the gold tests) and VS-04
  relevance is off. Real LK-01, LK-02, LK-03, LK-04 and EV-02 do the rest. This is
  the design's "gold-bundle" mode.
* ``auto``: no hints; criterion -> test relevance comes from VS-04 alone.

``--source bundle`` skips Stage A and scores the committed VS-01 ``inputs.json`` bundles.

The printed table compares the computed states and PR verdict with
``verdict_v2.fixture_expectations.json``. Differences are listed, not hidden.
No network, no clock in scoring (the timestamp is fixed), no LLM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
for _src in (*sorted((ROOT / "packages").glob("*/src")), ROOT / "apps" / "worker" / "src"):
    if str(_src) not in sys.path:
        sys.path.append(str(_src))

from radius_analysis.tamper import (  # noqa: E402
    StaticPackageRegistry,
    TamperConfig,
    analyze_tampering,
)
from radius_analysis.tamper.config import Params  # noqa: E402
from radius_shared.verdict_v2_flag import VerdictV2Mode  # noqa: E402
from radius_worker.orchestrator import ExecuteAnalysisCommand  # noqa: E402
from radius_worker.verdict_v2 import adapters  # noqa: E402
from radius_worker.verdict_v2.collect import (  # noqa: E402
    Producers,
    VerdictStageACollector,
    _snapshots,
    default_tamper,
)
from radius_worker.verdict_v2.scoring import (  # noqa: E402
    ScoringPipeline,
    run_verdict_v2_best_effort,
)
from radius_worker.verdict_v2.sources import (  # noqa: E402
    IntentFacts,
    OutcomeFacts,
    StaticIntent,
)

INTENT = ROOT / "benchmarks" / "fixtures" / "intent"
BUNDLES = ROOT / "benchmarks" / "fixtures" / "verdict_v2"
EXPECT = ROOT / "docs" / "research" / "design" / "verdict_v2.fixture_expectations.json"
TESTABILITY = {
    "testable": "behavioral_testable",
    "vague": "subjective_or_vague",
    "non_functional": "non_functional_measurable",
}
OFFLINE_REGISTRY_KNOWN = frozenset({"pytest", "requests", "pytimeparse"})
STAMP = "2026-11-02T00:00:00Z"


def sha_for(name: str) -> str:
    return hashlib.sha1(name.encode()).hexdigest()  # noqa: S324 - fixture id, not security


def uuid_for(name: str, salt: str) -> UUID:
    return UUID(hashlib.sha256(f"{salt}:{name}".encode()).hexdigest()[:32])


def fixture_dirs(selectors: list[str]) -> list[Path]:
    all_dirs = sorted(p for p in INTENT.iterdir() if (p / "expected.json").is_file())
    if not selectors:
        return all_dirs
    return [p for p in all_dirs if any(p.name.startswith(s) for s in selectors)]


def criteria_for(
    expected: dict[str, Any], *, gold: bool, hint_provenance: str | None = None
) -> tuple[SimpleNamespace, ...]:
    """Fixture criteria as IN-01 look-alikes.

    Gold-mode semantics (decision DEC-029): the criteria are ``confirmed`` and the
    expected links are fed as hints that count as ``human_confirmed`` (the author's
    design intent, not a PR author's self-attestation), so the 8 gold results stay as
    designed. Pass ``hint_provenance="author_head_spec"`` to see the author-hint cap.
    """

    links = {link["criterion"]: link for link in expected.get("links", [])}
    out = []
    for c in expected["criteria"]:
        link = links.get(c["id"], {})
        paths = (link["symbol"].split("::", 1)[0],) if gold and link.get("symbol") else ()
        tests = tuple(link.get("tests", ())) if gold else ()
        extra = {"hints_provenance": hint_provenance} if hint_provenance else {}
        out.append(
            SimpleNamespace(
                id=c["id"],
                text=c["text"],
                state="confirmed",
                weight=1.0,
                testability=TESTABILITY.get(c["testability"], c["testability"]),
                hints=SimpleNamespace(paths=paths, tests=tests),
                **extra,
            )
        )
    return tuple(out)


def cases_for(expected: dict[str, Any]) -> list[SimpleNamespace]:
    cases = []
    for test_id, outcome in sorted(expected["test_outcomes"]["head"].items()):
        parts = test_id.split("::")
        cases.append(
            SimpleNamespace(
                file=parts[0],
                classname=parts[1] if len(parts) > 2 else None,
                name=parts[-1],
                outcome=outcome,
            )
        )
    return cases


def tamper_producer(registry: str):
    if registry != "static":
        return default_tamper

    def run(changeset: Any, command: Any):
        base, head, _ = _snapshots(command)
        return analyze_tampering(
            changeset,
            base,
            head,
            TamperConfig(params=Params(use_registry=True)),
            diff_text=command.diff_text or None,
            package_registry=StaticPackageRegistry(set(OFFLINE_REGISTRY_KNOWN)),
        )

    return run


class FixedSha:
    def __init__(self, sha: str) -> None:
        self._sha = sha

    def head_sha(self, analysis_id: UUID, command: Any) -> str:  # noqa: ARG002
        return self._sha


class FixedOutcomes:
    def __init__(self, facts: OutcomeFacts) -> None:
        self._facts = facts

    def load(self, analysis_id: UUID, stage_a: Any) -> OutcomeFacts:  # noqa: ARG002
        return self._facts


def _setup(path: Path, mode: str, registry: str, hint_provenance: str | None = None):
    expected = json.loads((path / "expected.json").read_text(encoding="utf-8"))
    name = path.name
    command = ExecuteAnalysisCommand(
        analysis_id=uuid_for(name, "analysis"),
        repository_id=uuid_for(name, "repository"),
        repository_path=path / "head",
        diff_text=(path / "pr.patch").read_text(encoding="utf-8").replace("\r\n", "\n"),
    )
    collector = VerdictStageACollector(
        StaticIntent(IntentFacts(criteria=criteria_for(expected, gold=mode == "gold", hint_provenance=hint_provenance))),
        head_sha_port=FixedSha(sha_for(name)),
        producers=Producers(
            tamper=tamper_producer(registry),
            # gold = the author's hints only; auto = VS-04 relevance, no hints
            relevance=None if mode == "gold" else Producers().relevance,
        ),
    )
    facts = OutcomeFacts(cases=adapters.case_inputs(cases_for(expected)).items, uploads=1)
    return command, collector, facts


def collect_stage_a(path: Path, mode: str, registry: str, hint_provenance: str | None = None):
    """Real Stage A on one fixture (no scoring)."""

    command, collector, _ = _setup(path, mode, registry, hint_provenance)
    return collector.collect(command.analysis_id, command)


def run_collect(
    path: Path, mode: str, registry: str, hint_provenance: str | None = None
) -> dict[str, Any]:
    command, collector, facts = _setup(path, mode, registry, hint_provenance)
    report = run_verdict_v2_best_effort(
        mode=VerdictV2Mode.SHADOW,
        analysis_id=command.analysis_id,
        command=command,
        collector=collector,
        outcomes=FixedOutcomes(facts),
        clock=_fixed_clock,
    )
    if report.status != "ok" or report.payload is None:
        raise SystemExit(f"{path.name} ({mode}): Stage A/B failed: {report.reason_code}")
    return report.payload


def _fixed_clock():
    from datetime import UTC, datetime

    return datetime(2026, 11, 2, tzinfo=UTC)


def run_bundle(name: str, mode: str) -> dict[str, Any]:
    sys.path.insert(0, str(BUNDLES))
    import loader  # noqa: PLC0415

    stage_b = loader.stage_b(name, mode=mode, scenario="head")
    return ScoringPipeline(mode="shadow", clock=_fixed_clock).score_full(stage_b).payload


def render_markdown(bundle: dict[str, Any]) -> str | None:
    try:
        from radius_github.verdict_v2.markdown import render_comment
        from radius_github.verdict_v2.view import VerdictV2View
    except ImportError:
        return None
    return render_comment(VerdictV2View.from_payload(bundle))


def compare(bundle: dict[str, Any], exp: dict[str, Any], mode: str, registry: str) -> list[str]:
    diffs = []
    want_verdict = exp["expected_verdict"]
    if exp["fixture"].startswith("06") and registry != "static":
        want_verdict = exp["offline_registry_variant"]["expected_verdict"]
    if bundle["verdict"] != want_verdict:
        diffs.append(f"verdict {bundle['verdict']} != expected {want_verdict}")
    want_states = exp[mode]["states"]
    got = {c["criterion_id"]: c["state"] for c in bundle["criteria"]}
    for cid, state in want_states.items():
        if got.get(cid) != state:
            diffs.append(f"{cid} {got.get(cid)} != expected {state}")
    return diffs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("fixtures", nargs="*", help="fixture number prefixes (default: all 8)")
    ap.add_argument("--mode", choices=("gold", "auto", "both"), default="both")
    ap.add_argument("--source", choices=("collect", "bundle"), default="collect")
    ap.add_argument(
        "--registry",
        choices=("static", "none"),
        default="static",
        help="static: offline package registry so T012 can say registry_missing (fixture 06)",
    )
    ap.add_argument("--markdown", action="store_true", help="print the rendered PR comment")
    ap.add_argument("--json", action="store_true", help="print the full bundle JSON")
    args = ap.parse_args(argv)

    expectations = {
        f["fixture"]: f for f in json.loads(EXPECT.read_text(encoding="utf-8"))["fixtures"]
    }
    modes = ("gold", "auto") if args.mode == "both" else (args.mode,)
    mismatches = 0
    print(f"{'fixture':38} {'mode':5} {'verdict':22} {'decided':7} {'UIM':>5} {'cov':>5}  criteria")
    for path in fixture_dirs(args.fixtures):
        for mode in modes:
            if args.source == "bundle":
                bundle = run_bundle(path.name, mode)
            else:
                bundle = run_collect(path, mode, args.registry)
            diffs = compare(bundle, expectations[path.name], mode, args.registry)
            mismatches += bool(diffs)
            crit = " ".join(
                f"{c['criterion_id']}={c['state']}({c['S']:.3f})" for c in bundle["criteria"]
            )
            s = bundle["summary"]
            print(
                f"{path.name:38} {mode:5} {bundle['verdict']:22} "
                f"{bundle['justification']['decided_by']:7} {s['uim']:5.2f} "
                f"{s['intent_coverage']:5.2f}  {crit}"
            )
            if bundle.get("degraded"):
                print(f"{'':44}degraded: {', '.join(bundle['degraded'])}")
            for d in diffs:
                print(f"{'':44}DIFF vs fixture_expectations ({mode}): {d}")
            if args.markdown:
                text = render_markdown(bundle)
                print("\n" + (text or "(renderer not available)") + "\n")
            if args.json:
                print(json.dumps(bundle, indent=1, sort_keys=True))
    print(f"\n{mismatches} fixture/mode run(s) differ from verdict_v2.fixture_expectations.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
