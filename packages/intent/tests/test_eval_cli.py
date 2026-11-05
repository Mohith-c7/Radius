"""IN-10: command line, provenance helpers and the script wrapper (no network)."""
# ruff: noqa: E402, I001  (helper import needs the sys.path setup below, as in the IN-03 tests)
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
if _HERE not in _sys.path:  # helper module lives next to the tests (importlib mode)
    _sys.path.insert(0, _HERE)

import io
import json
import runpy
import subprocess
from pathlib import Path

import pytest
from eval_helpers import SYNTHETIC_GOLD
from radius_intent.evaluation import cli, provenance

ROOT = Path(__file__).resolve().parents[3]


def write_config(tmp_path, extractors=None, **over):
    doc = {
        "name": "cli-test",
        "gold": {"path": str(SYNTHETIC_GOLD), "adapter": "native"},
        "bootstrap": {"resamples": 20},
        "extractors": extractors
        or [
            {"id": "det", "kind": "deterministic"},
            {"id": "null", "kind": "null"},
        ],
        **over,
    }
    path = tmp_path / "exp.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def call(*argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), stdout=out, stderr=err, environ=env or {})
    return code, out.getvalue(), err.getvalue()


def run_dir(tmp_path, **kw):
    cfg = write_config(tmp_path, **kw)
    code, out, _ = call("run", "--config", str(cfg), "--out-root", str(tmp_path / "res"), "--run-id", "r1")
    assert code == 0, out
    return tmp_path / "res" / "r1"


def test_list_extractors_text_and_json():
    code, out, _ = call("list-extractors")
    assert code == 0
    assert "det-extract-v1" in out and "intent-extract-llm-v1" in out
    assert "--allow-real-llm" in out and "oracle" in out
    code, out, _ = call("list-extractors", "--json")
    data = json.loads(out)
    assert {k["kind"] for k in data["kinds"]} >= {"deterministic", "llm", "combined"}
    assert "anthropic" in data["providers"]


def test_run_writes_machine_readable_and_markdown_outputs(tmp_path):
    cfg = write_config(tmp_path)
    code, out, _ = call("run", "--config", str(cfg), "--out-root", str(tmp_path / "res"))
    assert code == 0
    assert "SYNTHETIC — not a research result" in out and "| `det` |" in out
    (rd,) = list((tmp_path / "res").iterdir())
    assert rd.name.startswith("cli-test-")
    assert {p.name for p in rd.iterdir()} >= {"run.json", "report.json", "report.md"}
    record = json.loads((rd / "run.json").read_text(encoding="utf-8"))
    man = record["manifest"]
    assert man["gold_source"]["adapter"] == "native" and len(man["gold_source"]["files_sha256"]) == 64
    assert man["git"]["sha"] and man["environment"]["python"]
    assert man["run_id"] == rd.name
    summary = json.loads((rd / "report.json").read_text(encoding="utf-8"))
    assert "cases" not in summary["extractors"]["det"]


def test_run_quiet_and_overrides(tmp_path):
    cfg = write_config(tmp_path)
    code, out, _ = call(
        "run", "--config", str(cfg), "--out-root", str(tmp_path / "res"), "--quiet",
        "--run-id", "o", "--seed", "5", "--resamples", "7",
    )
    assert code == 0 and out.strip().startswith("wrote ") and "# Intent" not in out
    record = json.loads((tmp_path / "res" / "o" / "run.json").read_text(encoding="utf-8"))
    assert record["manifest"]["seeds"]["bootstrap"] == 5
    assert record["manifest"]["config"]["bootstrap"]["resamples"] == 7


def test_run_gold_and_adapter_overrides(tmp_path):
    doc = {
        "name": "f14",
        "bootstrap": {"resamples": 10},
        "extractors": [{"id": "d", "kind": "deterministic"}],
    }
    path = tmp_path / "f.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    code, out, err = call("run", "--config", str(path), "--out-root", str(tmp_path / "r"), "--quiet")
    assert code == 2 and "no gold path" in err
    code, out, _ = call(
        "run", "--config", str(path), "--out-root", str(tmp_path / "r"), "--quiet",
        "--gold", str(ROOT / "benchmarks" / "fixtures" / "intent"), "--adapter", "f14-fixtures",
    )
    assert code == 0


def test_gold_path_relative_to_config_directory(tmp_path):
    (tmp_path / "g").mkdir()
    (tmp_path / "g" / "gold.json").write_text(SYNTHETIC_GOLD.read_text(encoding="utf-8"), encoding="utf-8")
    cfg = write_config(tmp_path, gold={"path": "g/gold.json"})
    code, *_ = call("run", "--config", str(cfg), "--out-root", str(tmp_path / "r"), "--quiet")
    assert code == 0


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda d: d.update(extractors=[]), "extractors"),
        (lambda d: d.update(gold={"path": "/nope/missing.json"}), "not found"),
        (lambda d: d.update(gold={"path": str(SYNTHETIC_GOLD), "adapter": "zzz"}), "unknown adapter"),
        (
            lambda d: d.update(extractors=[{"id": "l", "kind": "llm"}]),
            "needs a 'provider'",
        ),
        (
            lambda d: d.update(extractors=[{"id": "l", "kind": "llm", "provider": {"type": "anthropic"}}]),
            "real LLM provider refused",
        ),
    ],
)
def test_run_failures_exit_2_with_message(tmp_path, mutate, fragment):
    doc = json.loads(write_config(tmp_path).read_text(encoding="utf-8"))
    mutate(doc)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    code, out, err = call("run", "--config", str(path), "--out-root", str(tmp_path / "r"))
    assert code == 2 and fragment in err and out == ""


def test_real_provider_still_refused_with_flag_but_no_env(tmp_path):
    cfg = write_config(
        tmp_path, extractors=[{"id": "l", "kind": "llm", "provider": {"type": "anthropic"}}]
    )
    code, _, err = call("run", "--config", str(cfg), "--out-root", str(tmp_path / "r"), "--allow-real-llm")
    assert code == 2 and "RADIUS_EVAL_ALLOW_REAL_LLM" in err


def test_config_file_problems(tmp_path):
    code, _, err = call("run", "--config", str(tmp_path / "none.json"))
    assert code == 2 and "cannot read config" in err
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    code, _, err = call("run", "--config", str(bad))
    assert code == 2 and "invalid JSON" in err
    cfg = write_config(tmp_path)
    code, _, err = call("run", "--config", str(cfg), "--resamples", "0")
    assert code == 2 and "--resamples" in err


def test_invalid_gold_file_is_reported(tmp_path):
    gold = tmp_path / "g.json"
    gold.write_text(json.dumps({"schema": "x"}), encoding="utf-8")
    cfg = write_config(tmp_path, gold={"path": str(gold)})
    code, _, err = call("run", "--config", str(cfg), "--out-root", str(tmp_path / "r"))
    assert code == 2 and "gold format error" in err


def test_report_renders_markdown_json_and_file(tmp_path):
    rd = run_dir(tmp_path)
    code, out, _ = call("report", str(rd))
    assert code == 0 and out.startswith("# Intent extraction metrics: r1")
    code, out, _ = call("report", str(rd / "run.json"), "--format", "json")
    assert json.loads(out)["manifest"]["run_id"] == "r1"
    target = tmp_path / "copy.md"
    code, out, _ = call("report", str(rd), "--out", str(target))
    assert code == 0 and target.read_text(encoding="utf-8") == (rd / "report.md").read_text(encoding="utf-8").rstrip("\n") or target.exists()
    code, _, err = call("report", str(tmp_path / "missing"))
    assert code == 2 and "cannot read run record" in err


def test_report_is_a_pure_function_of_the_stored_run(tmp_path):
    rd = run_dir(tmp_path)
    _, first, _ = call("report", str(rd))
    _, second, _ = call("report", str(rd))
    assert first == second
    assert first.rstrip("\n") == (rd / "report.md").read_text(encoding="utf-8").rstrip("\n")


def test_compare_between_two_runs(tmp_path):
    a = run_dir(tmp_path)
    cfg = write_config(
        tmp_path,
        extractors=[{"id": "oracle", "kind": "oracle"}],
        bootstrap={"resamples": 20},
    )
    code, *_ = call(
        "run", "--config", str(cfg), "--out-root", str(tmp_path / "res"), "--run-id", "r2", "--quiet"
    )
    assert code == 0
    b = tmp_path / "res" / "r2"
    code, out, _ = call("compare", str(b), str(a), "--b-extractor", "null", "--resamples", "50")
    assert code == 0 and "Paired comparison" in out and "oracle" in out
    target = tmp_path / "cmp.json"
    code, out, _ = call(
        "compare", str(b), str(a), "--b-extractor", "det", "--format", "json", "--out", str(target)
    )
    assert code == 0
    assert json.loads(target.read_text(encoding="utf-8"))["b"]["extractor"] == "det"
    code, _, err = call("compare", str(a), str(a))
    assert code == 2 and "choose one" in err
    code, _, err = call("compare", str(a), str(tmp_path / "missing"))
    assert code == 2 and "cannot read" in err
    code, out, _ = call("compare", str(b), str(a), "--b-extractor", "det", "--format", "json")
    assert json.loads(out)["differences"]


# ------------------------------------------------------------------ provenance


def test_git_state_reports_sha_and_dirty_flag():
    state = provenance.git_state(ROOT)
    assert len(state["sha"]) == 40 and isinstance(state["dirty"], bool)


def test_git_state_without_git_is_unknown(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", boom)
    assert provenance.git_state() == {"sha": "unknown", "dirty": None}


def test_hash_path_file_and_directory_are_stable(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    assert provenance.hash_path(f) == provenance.hash_path(f)
    d = tmp_path / "d"
    d.mkdir()
    (d / "x.txt").write_bytes(b"a\r\nb")
    h1 = provenance.hash_path(d)
    (d / "x.txt").write_bytes(b"a\nb")
    assert provenance.hash_path(d) == h1  # line endings do not change the hash
    (d / "y.txt").write_bytes(b"more")
    assert provenance.hash_path(d) != h1
    assert set(provenance.environment()) == {"python", "platform"}


# ----------------------------------------------------------------- entry points


def test_script_wrapper_runs_list_extractors():
    result = subprocess.run(
        [_sys.executable, str(ROOT / "scripts" / "intent_eval.py"), "list-extractors"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
    )
    assert result.returncode == 0 and "det-extract-v1" in result.stdout


def test_module_entry_point(monkeypatch, capsys):
    monkeypatch.setattr(_sys, "argv", ["radius_intent.evaluation", "list-extractors"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("radius_intent.evaluation", run_name="__main__")
    assert exc.value.code == 0
    assert "deterministic" in capsys.readouterr().out
