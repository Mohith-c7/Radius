"""IN-10: end-to-end harness runs on synthetic and F-14 data (no network)."""
# ruff: noqa: E402, I001  (helper import needs the sys.path setup below, as in the IN-03 tests)
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
if _HERE not in _sys.path:  # helper module lives next to the tests (importlib mode)
    _sys.path.insert(0, _HERE)

import copy
import json
from dataclasses import replace

import pytest
from eval_helpers import F14_DIR, SYNTHETIC_GOLD, case, dataset, pred
from radius_intent.evaluation.compare import CompareError, compare_runs
from radius_intent.evaluation.config import (
    MASTER_SEED,
    ConfigError,
    ExtractorSpec,
    parse_config,
)
from radius_intent.evaluation.extractors import (
    ENV_ALLOW_REAL,
    ExtractionOutcome,
    HarnessExtractor,
    RealProviderNotAllowed,
    RecordingProvider,
    ReplayProvider,
    blocks_key,
    build_extractor,
    build_provider,
    fake_lines_handler,
    list_kinds,
)
from radius_intent.evaluation.loader import load_gold
from radius_intent.evaluation.report import (
    fmt_ci,
    render_compare_markdown,
    render_markdown,
    render_summary_json,
)
from radius_intent.evaluation.runner import (
    SYNTHETIC_LABEL,
    load_run,
    make_run_id,
    run_experiment,
    write_run,
)
from radius_intent.infrastructure.llm import FakeProvider, LlmRequest
from radius_intent.infrastructure.llm.anthropic_provider import AnthropicProvider

RESAMPLES = 40


def config(*extractors, **over):
    specs = tuple(
        ExtractorSpec(eid, kind, opts) for eid, kind, opts in extractors
    ) or (ExtractorSpec("det", "deterministic"),)
    base = parse_config({"name": "unit", "extractors": [{"id": "x", "kind": "null"}]})
    return replace(base, extractors=specs, resamples=RESAMPLES, seed=11, **over)


FAKE = {"provider": {"type": "fake-lines"}}


def build(cfg, **kw):
    return [
        build_extractor(s, rate_testability=cfg.rate_testability, **kw)
        for s in cfg.extractors
    ]


@pytest.fixture(scope="module")
def synthetic():
    return load_gold(SYNTHETIC_GOLD)


@pytest.fixture(scope="module")
def full_run(synthetic):
    cfg = config(
        ("det", "deterministic", {}),
        ("llm", "llm", FAKE),
        ("comb", "combined", FAKE),
        ("oracle", "oracle", {}),
        ("null", "null", {}),
    )
    return cfg, run_experiment(cfg, synthetic, build(cfg), provenance={"git": {"sha": "abc"}})


def metric(art, ex, name):
    return art.record["extractors"][ex]["metrics"][name]["estimate"]


# ---------------------------------------------------------------- end to end


def test_perfect_extractor_gets_f1_one_and_empty_extractor_recall_zero(full_run):
    _, art = full_run
    for mode in ("iou", "text_exact", "text_fuzzy"):
        assert metric(art, "oracle", f"{mode}.all.f1") == 1.0
        assert metric(art, "null", f"{mode}.all.recall") == 0.0
    assert metric(art, "oracle", "tx.accuracy") == 1.0
    assert metric(art, "null", "iou.all.precision") is None
    assert metric(art, "null", "abstention.empty_prediction_rate") == 1.0


def test_deterministic_extractor_behaves_on_synthetic_gold(full_run):
    _, art = full_run
    p = metric(art, "det", "iou.all.precision")
    r = metric(art, "det", "iou.all.recall")
    assert p == 1.0  # every extracted bullet is a gold criterion by construction
    assert 0.5 < r < 1.0  # compound duplicate and unheaded prose are missed
    assert metric(art, "det", "iou.kind:issue.recall") == 1.0
    assert metric(art, "det", "nogold.fp_rate") == 0.0


def test_llm_fake_has_high_recall_low_precision_and_usage(full_run):
    _, art = full_run
    assert metric(art, "llm", "iou.all.recall") > 0.9
    assert metric(art, "llm", "iou.all.precision") < 0.8
    assert metric(art, "llm", "nogold.fp_rate") == 1.0
    usage = art.record["extractors"]["llm"]["usage"]
    assert usage["llm_calls"] == 10 and usage["input_tokens"] == 1000
    assert usage["output_tokens"] == 500
    assert art.record["extractors"]["det"]["usage"]["llm_calls"] == 0


def test_intervals_bracket_estimates(full_run):
    _, art = full_run
    for entry in art.record["extractors"].values():
        for m in entry["metrics"].values():
            if m["low"] is not None:
                assert m["low"] - 1e-9 <= m["estimate"] <= m["high"] + 1e-9


def test_manifest_records_reproducibility_fields(full_run):
    cfg, art = full_run
    man = art.record["manifest"]
    assert man["label"] == SYNTHETIC_LABEL
    assert man["config_sha256"] == cfg.sha256 and len(man["config_sha256"]) == 64
    assert man["dataset"]["sha256"] and man["dataset"]["synthetic"] is True
    assert man["seeds"] == {"bootstrap": 11}
    assert man["git"] == {"sha": "abc"}
    versions = man["versions"]
    assert versions["det"]["extractor_version"] == "det-extract-v1"
    assert versions["det"]["testability_rules"] == "testability-rules-v1"
    assert versions["llm"]["prompt_version"] == "intent-extract-llm-v1"
    assert versions["llm"]["model"] == "fake-lines-1"
    assert man["harness_version"] == "intent-eval-v1"
    assert man["timings_s"]["total"] >= 0
    assert man["case_order"] == sorted(man["case_order"])
    assert man["run_id"].startswith("unit-")


def _stable(record):
    rec = copy.deepcopy(record)
    rec["manifest"].pop("created_at")
    rec["manifest"].pop("timings_s")
    for e in rec["extractors"].values():
        e.pop("timing_s")
    return rec


def test_same_inputs_give_identical_results(synthetic, full_run):
    cfg, first = full_run
    second = run_experiment(cfg, synthetic, build(cfg), provenance={"git": {"sha": "abc"}})
    assert _stable(first.record) == _stable(second.record)
    other_seed = run_experiment(replace(cfg, seed=12), synthetic, build(replace(cfg, seed=12)))
    a = first.record["extractors"]["det"]["metrics"]["iou.all.f1"]
    b = other_seed.record["extractors"]["det"]["metrics"]["iou.all.f1"]
    assert a["estimate"] == b["estimate"] and (a["low"], a["high"]) != (b["low"], b["high"])


def test_run_id_depends_on_config_and_dataset(synthetic):
    a, b = config(), config()
    assert make_run_id(a, synthetic) == make_run_id(b, synthetic)
    assert make_run_id(replace(a, seed=99), synthetic) != make_run_id(a, synthetic)


def test_f14_fixture_run_with_deterministic_extractor():
    cfg = config(("det", "deterministic", {}), ("oracle", "oracle", {}))
    ds = load_gold(F14_DIR, "f14-fixtures")
    art = run_experiment(cfg, ds, build(cfg))
    assert art.record["manifest"]["dataset"]["n_cases"] == 8
    assert metric(art, "oracle", "iou.all.f1") == 1.0
    det = art.record["extractors"]["det"]
    assert det["groups"]["all"]["iou"]["gold"] == 18
    assert 0.0 <= metric(art, "det", "iou.all.recall") < 1.0
    assert "SYNTHETIC" in render_markdown(art.record)


def test_extractor_exception_is_recorded_and_scored_as_empty():
    class Boom(HarnessExtractor):
        def extract(self, c):
            raise RuntimeError("kaput")

    cfg = config(("boom", "null", {}))
    ds = dataset(case("a", gold=((0, 5),)))
    art = run_experiment(cfg, ds, [Boom(cfg.extractors[0], rate=False)])
    entry = art.record["extractors"]["boom"]
    assert entry["errors"] == [{"case_id": "a", "error": "RuntimeError('kaput')"}]
    assert metric(art, "boom", "iou.all.recall") == 0.0
    assert "kaput" in render_markdown(art.record)


def test_price_gives_cost_estimate(synthetic):
    cfg = config(("llm", "llm", FAKE), price_per_mtok=(1.0, 5.0))
    art = run_experiment(cfg, synthetic, build(cfg))
    u = art.record["extractors"]["llm"]["usage"]
    assert u["estimated_cost_usd"] == pytest.approx(1000 / 1e6 * 1 + 500 / 1e6 * 5)


def test_non_synthetic_dataset_has_no_banner():
    cfg = config(("null", "null", {}))
    ds = dataset(case("a", gold=((0, 5),)), synthetic=False)
    art = run_experiment(cfg, ds, build(cfg))
    assert art.record["manifest"]["label"] is None
    assert "SYNTHETIC" not in render_markdown(art.record)


# ------------------------------------------------------------------ providers


def _request(texts):
    blocks = "\n".join(
        f"<<<RADIUS_DATA_abc123 id={sid} kind=pr_body>>>\n{t}\n<<<END_RADIUS_DATA_abc123>>>"
        for sid, t in texts.items()
    )
    return LlmRequest(system="rules RADIUS_DATA_abc123 end", user=blocks)


def test_blocks_key_ignores_nonce_and_distinguishes_text():
    k1 = blocks_key(_request({"a": "hello"}))
    assert k1 == blocks_key(_request({"a": "hello"}))
    assert k1 != blocks_key(_request({"a": "bye"}))
    assert len(blocks_key(LlmRequest(system="no nonce", user="x"))) == 64


def test_record_then_replay_reproduces_predictions(synthetic):
    cfg = config(("rec", "llm", FAKE))
    recorder = RecordingProvider(FakeProvider(fake_lines_handler))
    ex = build_extractor(
        cfg.extractors[0],
        rate_testability=True,
        provider_factory=lambda *_a, **_k: recorder,
    )
    live = run_experiment(cfg, synthetic, [ex])
    extras = live.extras["rec"]
    assert len(extras["llm_recordings"]["responses"]) == 10

    replay = ReplayProvider(extras["llm_recordings"]["responses"], model_id="r")
    ex2 = build_extractor(
        cfg.extractors[0],
        rate_testability=True,
        provider_factory=lambda *_a, **_k: replay,
    )
    again = run_experiment(cfg, synthetic, [ex2])
    assert replay.misses == 0 and again.extras["rec"]["replay_misses"] == 0
    assert (
        live.record["extractors"]["rec"]["totals"]
        == again.record["extractors"]["rec"]["totals"]
    )
    # a replay that knows nothing counts misses and predicts nothing
    empty = ReplayProvider({})
    ex3 = build_extractor(
        cfg.extractors[0], rate_testability=True, provider_factory=lambda *_a, **_k: empty
    )
    run_experiment(cfg, synthetic, [ex3])
    assert empty.misses == 10


def test_build_provider_fake_replay_and_errors(tmp_path):
    assert isinstance(build_provider({"type": "fake-lines"}), FakeProvider)
    rec = tmp_path / "rec.json"
    rec.write_text(json.dumps({"model": "m1", "responses": {"k": "{}"}}), encoding="utf-8")
    p = build_provider({"type": "replay", "recordings": "rec.json"}, base_dir=str(tmp_path))
    assert isinstance(p, ReplayProvider) and p.model_id == "m1"
    with pytest.raises(ConfigError, match="recordings"):
        build_provider({"type": "replay"})
    with pytest.raises(ConfigError, match="cannot read"):
        build_provider({"type": "replay", "recordings": str(tmp_path / "none.json")})
    rec.write_text("[1]", encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON object"):
        build_provider({"type": "replay", "recordings": str(rec)})
    with pytest.raises(ConfigError, match="unknown provider"):
        build_provider({"type": "gemini"})


def test_real_provider_needs_flag_and_env():
    opts = {"type": "anthropic", "model": "claude-haiku-5-5"}
    with pytest.raises(RealProviderNotAllowed):
        build_provider(opts)
    with pytest.raises(RealProviderNotAllowed):
        build_provider(opts, allow_real_llm=True, environ={})
    with pytest.raises(RealProviderNotAllowed):
        build_provider(opts, allow_real_llm=False, environ={ENV_ALLOW_REAL: "1"})
    ok = build_provider(
        {**opts, "record": False}, allow_real_llm=True, environ={ENV_ALLOW_REAL: "1"}
    )
    assert isinstance(ok, AnthropicProvider)  # constructed lazily; no client, no network
    rec = build_provider(opts, allow_real_llm=True, environ={ENV_ALLOW_REAL: "1"})
    assert isinstance(rec, RecordingProvider) and rec.model_id == "claude-haiku-5-5"


def test_build_extractor_validation():
    with pytest.raises(ConfigError, match="provider"):
        build_extractor(ExtractorSpec("l", "llm"), rate_testability=True)
    with pytest.raises(ConfigError, match="unknown extractor kind"):
        build_extractor(ExtractorSpec("z", "magic"), rate_testability=True)
    assert {k.kind for k in list_kinds()} == {
        "deterministic", "llm", "combined", "oracle", "null"
    }


def test_testability_rating_can_be_disabled(synthetic):
    cfg = config(("det", "deterministic", {}), rate_testability=False)
    art = run_experiment(cfg, synthetic, build(cfg))
    assert metric(art, "det", "testability.unrated_pred_rate") == 1.0
    assert metric(art, "det", "tx.abstain_rate") == 1.0
    assert "testability_rules" not in art.record["manifest"]["versions"]["det"]


def test_llm_budget_cap_yields_no_criteria_not_a_crash(synthetic):
    cfg = config(("llm", "llm", {**FAKE, "analysis_token_cap": 10}))
    art = run_experiment(cfg, synthetic, build(cfg))
    assert metric(art, "llm", "iou.all.recall") == 0.0
    assert art.record["extractors"]["llm"]["usage"]["cases_with_diagnostics"] == 10


# ------------------------------------------------------------------- config


def test_config_defaults_and_hash_stability():
    cfg = parse_config({"name": "n", "extractors": [{"id": "a", "kind": "null"}]})
    assert cfg.seed == MASTER_SEED == 20261102
    assert cfg.matching.iou_threshold == 0.5 and cfg.resamples == 10_000
    same = parse_config({"extractors": [{"kind": "null", "id": "a"}], "name": "n"})
    assert cfg.sha256 == same.sha256
    assert parse_config({"name": "m", "extractors": [{"id": "a", "kind": "null"}]}).sha256 != cfg.sha256


@pytest.mark.parametrize(
    ("patch", "fragment"),
    [
        ({"name": ""}, "name"),
        ({"seed": "x"}, "seed"),
        ({"bogus": 1}, "unknown config keys"),
        ({"extractors": []}, "non-empty"),
        ({"extractors": [5]}, "must be an object"),
        ({"extractors": [{"id": "", "kind": "null"}]}, "id"),
        ({"extractors": [{"id": "a", "kind": "nope"}]}, "kind"),
        ({"extractors": [{"id": "a", "kind": "null"}, {"id": "a", "kind": "null"}]}, "duplicate"),
        ({"matching": {"iou_threshold": 2}}, "matching"),
        ({"matching": {"nope": 1}}, "matching"),
        ({"matching": []}, "must be an object"),
        ({"bootstrap": {"resamples": 0}}, "resamples"),
        ({"bootstrap": {"confidence": 1.5}}, "confidence"),
        ({"rate_testability": "yes"}, "rate_testability"),
        ({"price_per_mtok": [1]}, "price_per_mtok"),
        ({"gold": {"path": 3}}, "gold.path"),
        ({"gold": {"adapter": 3}}, "gold.adapter"),
    ],
)
def test_config_validation(patch, fragment):
    doc = {"name": "n", "extractors": [{"id": "a", "kind": "null"}], **patch}
    with pytest.raises(ConfigError, match=fragment):
        parse_config(doc)
    with pytest.raises(ConfigError):
        parse_config([])


def test_config_accepts_price_and_gold():
    cfg = parse_config(
        {
            "name": "n",
            "extractors": [{"id": "a", "kind": "llm", "provider": {"type": "fake-lines"}}],
            "price_per_mtok": [1, 2],
            "gold": {"path": "p", "adapter": "native"},
        }
    )
    assert cfg.price_per_mtok == (1.0, 2.0) and cfg.gold_path == "p"
    assert cfg.extractors[0].as_dict()["provider"] == {"type": "fake-lines"}


# ----------------------------------------------------------------- comparison


def test_compare_runs_detects_difference_and_is_deterministic(full_run):
    _, art = full_run
    r1 = compare_runs(art.record, art.record, extractor_a="oracle", extractor_b="null", resamples=100)
    r2 = compare_runs(art.record, art.record, extractor_a="oracle", extractor_b="null", resamples=100)
    assert r1 == r2
    rec = r1["differences"]["iou.all.recall"]
    assert rec["estimate"] > 0 and rec["excludes_zero"] and rec["a"] == 1.0
    self_cmp = compare_runs(art.record, art.record, extractor_a="det", extractor_b="det", resamples=50)
    assert self_cmp["differences"]["iou.all.f1"]["estimate"] == 0.0
    assert not self_cmp["differences"]["iou.all.f1"]["excludes_zero"]
    assert r1["synthetic"] and r1["n_cases"] == 10 and r1["seed"] == 11
    md = render_compare_markdown(r1)
    assert "SYNTHETIC" in md and "A - B" in md and "oracle" in md and "| yes |" in md


def test_compare_errors_and_warnings(full_run, synthetic):
    cfg, art = full_run
    with pytest.raises(CompareError, match="choose one"):
        compare_runs(art.record, art.record)
    with pytest.raises(CompareError, match="no extractor"):
        compare_runs(art.record, art.record, extractor_a="zzz", extractor_b="det")

    smaller = dataset(*[c for c in synthetic.cases][:6])
    cfg2 = config(("det", "deterministic", {}), matching=replace(cfg.matching, iou_threshold=0.6))
    other = run_experiment(cfg2, smaller, build(cfg2)).record
    with pytest.raises(CompareError, match="different dataset"):
        compare_runs(art.record, other, extractor_a="det", extractor_b="det")
    res = compare_runs(
        art.record, other, extractor_a="det", extractor_b="det",
        resamples=30, allow_dataset_mismatch=True,
    )
    assert res["n_cases"] == 6
    assert any("dataset hashes differ" in w for w in res["warnings"])
    assert any("matching thresholds differ" in w for w in res["warnings"])
    assert any("shared PRs" in w for w in res["warnings"])

    disjoint = copy.deepcopy(other)
    disjoint["extractors"]["det"]["cases"] = {"zzz": next(iter(other["extractors"]["det"]["cases"].values()))}
    with pytest.raises(CompareError, match="share no PR ids"):
        compare_runs(art.record, disjoint, extractor_a="det", extractor_b="det", allow_dataset_mismatch=True)


# --------------------------------------------------------------------- report


def test_markdown_report_contains_all_required_sections(full_run):
    _, art = full_run
    md = render_markdown(art.record)
    for needle in (
        "SYNTHETIC — not a research result",
        "## Summary",
        "### Matching modes",
        "span IoU (primary)",
        "### Per source type",
        "agent_prompt",
        "### Per PR slice",
        "well_specified",
        "author:agent",
        "Cohen's kappa",
        "Confusion matrix",
        "behavioral_testable",
        "false-positive rate",
        "## Reproducibility",
        "det-extract-v1",
        "intent-extract-llm-v1",
        art.record["manifest"]["dataset"]["sha256"],
        art.record["manifest"]["config_sha256"],
    ):
        assert needle in md, needle
    assert md.rstrip().endswith("not a research result.** This run used synthetic or fixture-derived data and exists only to exercise the harness.")


def test_summary_json_drops_per_pr_vectors(full_run):
    _, art = full_run
    summary = json.loads(render_summary_json(art.record))
    assert "cases" not in summary["extractors"]["det"]
    assert summary["extractors"]["det"]["metrics"]["iou.all.f1"]["estimate"] is not None
    assert summary["manifest"]["seeds"]["bootstrap"] == 11


def test_fmt_ci_variants():
    assert fmt_ci(None) == "n/a"
    assert fmt_ci({"estimate": None}) == "n/a"
    assert fmt_ci({"estimate": 0.5, "low": None, "high": None}) == "0.500"
    assert fmt_ci({"estimate": 0.5, "low": 0.25, "high": 0.75}) == "0.500 [0.250, 0.750]"


def test_report_without_labels_says_so():
    cfg = config(("o", "oracle", {}))
    ds = dataset(case("a", gold=((0, 5),)))
    art = run_experiment(cfg, ds, build(cfg))
    assert "No matched criterion carries a gold testability label." in render_markdown(art.record)


def test_write_and_load_run_roundtrip(tmp_path, full_run):
    _, art = full_run
    path = write_run(art, tmp_path / "out")
    loaded = load_run(tmp_path / "out")
    assert loaded == json.loads(path.read_text(encoding="utf-8")) == load_run(path)
    assert (tmp_path / "out" / "llm.llm_recordings.json").exists() is False  # fake provider records nothing
    (tmp_path / "bad.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="not a run record"):
        load_run(tmp_path / "bad.json")
    with pytest.raises(ValueError, match="cannot read"):
        load_run(tmp_path / "missing")


def test_extras_are_written_next_to_run(tmp_path, synthetic):
    cfg = config(("rec", "llm", FAKE))
    rec = RecordingProvider(FakeProvider(fake_lines_handler))
    ex = build_extractor(
        cfg.extractors[0], rate_testability=True, provider_factory=lambda *_a, **_k: rec
    )
    art = run_experiment(cfg, synthetic, [ex])
    write_run(art, tmp_path)
    data = json.loads((tmp_path / "rec.llm_recordings.json").read_text(encoding="utf-8"))
    assert data["prompt_version"] == "intent-extract-llm-v1" and data["responses"]


def test_extraction_outcome_defaults():
    out = ExtractionOutcome((pred(0, 1),))
    assert out.llm_calls == 0 and out.diagnostics == ()
