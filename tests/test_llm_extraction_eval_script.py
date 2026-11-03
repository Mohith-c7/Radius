"""Pure logic and the no-key behaviour of scripts/llm_extraction_eval.py (no network, no key)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "llm_extraction_eval.py"
_spec = importlib.util.spec_from_file_location("llm_extraction_eval", _SCRIPT)
ev = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ev
_spec.loader.exec_module(ev)

BODY = "Users must be able to export reports as CSV files.\nThe export should be fast.\n"


def _meta(tmp_path: Path, number: int, title: str, body: str | None = BODY) -> None:
    (tmp_path / f"meta-{number}.json").write_text(
        json.dumps({"number": str(number), "title": title, "body": body}), encoding="utf-8"
    )


def test_load_metas_sorts_numerically_and_skips_incomplete(tmp_path):
    _meta(tmp_path, 10, "ten")
    _meta(tmp_path, 9, "nine")
    (tmp_path / "meta-11.json").write_text(json.dumps({"number": 11}), encoding="utf-8")
    assert [m["title"] for m in ev.load_metas(tmp_path)] == ["nine", "ten"]


def test_grounding_drop_rate_counts_only_grounding_codes():
    rows = [
        {"llm_kept": 3, "llm_dropped": ["dropped_span_mismatch", "dropped_ungrounded_text", "dropped_url"]},
        {"llm_kept": 1, "llm_dropped": []},
    ]
    g = ev.grounding_drop_rate(rows)
    assert (g["kept"], g["dropped"], g["proposed"]) == (4, 2, 6)
    assert g["rate"] == pytest.approx(2 / 6)
    assert g["by_code"] == {"dropped_span_mismatch": 1, "dropped_ungrounded_text": 1}
    assert ev.grounding_drop_rate([])["rate"] is None


def test_summarize_and_format():
    rows = [
        {"number": 1, "title": "a", "summary": ["x"], "llm": ["y", "z"], "llm_kept": 2,
         "llm_dropped": ["dropped_short_quote"], "llm_degraded": 0, "llm_input_tokens": 10,
         "llm_output_tokens": 5, "llm_latency_ms": 12.5},
        {"number": 2, "title": "b", "summary": [], "llm": [], "llm_kept": 0,
         "llm_dropped": [], "llm_degraded": 1, "llm_input_tokens": 0,
         "llm_output_tokens": 0, "llm_latency_ms": 0.0},
    ]
    s = ev.summarize(rows)
    assert s["prs"] == 2 and s["summary_prs_with_criteria"] == 1 and s["llm_total"] == 2
    assert s["degraded_runs"] == 1 and s["input_tokens"] == 10 and s["latency_ms"] == 12.5
    text = ev.format_summary(s)
    assert "grounding drop rate: 33.3%" in text
    assert "DEGRADED" in ev.format_row(rows[1]) and "llm      - y" in ev.format_row(rows[0])
    assert "n/a" in ev.format_summary(ev.summarize([rows[1]]))


def test_run_with_a_fake_provider_reports_kept_and_dropped(tmp_path):
    from radius_intent.infrastructure.llm import FakeProvider

    quote = "Users must be able to export reports as CSV files."

    def handler(request):
        import re

        if quote not in request.user:  # the title call: nothing to propose
            return json.dumps({"criteria": []})
        sid = re.search(r"id=(\S+) kind", request.user).group(1)
        good = {"source_id": sid, "quote": quote, "start": BODY.index(quote),
                "end": BODY.index(quote) + len(quote), "text": quote}
        bad = {"source_id": sid, "quote": "Totally invented sentence here.", "start": 0,
               "end": 31, "text": "Totally invented sentence here."}
        return json.dumps({"criteria": [good, bad]})

    rows = ev.run([{"number": 7, "title": "feat: export", "body": BODY}], FakeProvider(handler))
    [row] = rows
    assert row["llm"] == [quote] and row["llm_dropped"] == ["dropped_span_mismatch"]
    assert row["llm_input_tokens"] > 0
    assert ev.summarize(rows)["grounding"]["rate"] == pytest.approx(0.5)


def test_main_without_a_key_does_nothing_and_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _meta(tmp_path, 1, "t")
    assert ev.main(["--meta-dir", str(tmp_path)]) == 2
    assert "nothing was sent" in capsys.readouterr().err
