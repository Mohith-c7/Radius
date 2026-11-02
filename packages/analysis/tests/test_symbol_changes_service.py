"""LK-01: service-level behaviour (options, degradation, determinism, snapshots, fixtures, CLI)."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from radius_analysis.symbol_changes import (
    ALGO_VERSION,
    ChangeKind,
    DictSnapshot,
    DiffReversedSnapshot,
    DirectorySnapshot,
    ExtractionOptions,
    GitSnapshot,
    RefRange,
    SymbolChangeSet,
    extract_symbol_changes,
    parse_unified_diff,
)
from radius_analysis.symbol_changes.__main__ import main as cli_main
from radius_analysis.symbol_changes.model import compress_lines, expand_ranges
from radius_analysis.symbol_changes.service import detect_language, is_ignored

from .symbol_changes_helpers import make_diff, run, summary

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "benchmarks" / "fixtures" / "intent"


# ----------------------------------------------------------------------- degradation


def test_unsupported_language_is_a_file_level_unit() -> None:
    result = run({"cfg/app.yaml": "a: 1\n"}, {"cfg/app.yaml": "a: 2\n"})
    (sym,) = result.symbols
    assert (sym.kind, sym.qualified_name, sym.change_kind.value) == ("file", "<file>", "modified_body")
    assert "unsupported_language" in sym.notes
    assert sym.language == "unknown"
    assert result.files[0].level.value == "file"
    assert result.unattributed_hunks == ()
    assert sym.hunks and sym.confidence == 0.5


def test_go_file_added_and_deleted() -> None:
    added = run({}, {"main.go": "package main\n"})
    assert [(s.change_kind.value, "unsupported_language" in s.notes) for s in added.symbols] == [
        ("added", True)
    ]
    deleted = run({"main.go": "package main\n"}, {})
    assert [s.change_kind.value for s in deleted.symbols] == ["removed"]


def test_binary_file_is_file_level_without_hunks() -> None:
    diff = "diff --git a/i.png b/i.png\nindex 1..2 100644\nBinary files a/i.png and b/i.png differ\n"
    result = run({}, {}, diff=diff)
    (sym,) = result.symbols
    assert "binary_file" in sym.notes and sym.hunks == ()


def test_nul_bytes_in_a_text_diff_are_treated_as_binary() -> None:
    base = {"a.py": b"x = 1\x00\n"}
    head = {"a.py": b"x = 2\x00\n"}
    result = extract_symbol_changes(DictSnapshot(base), DictSnapshot(head), make_diff(
        {"a.py": "x = 1\n"}, {"a.py": "x = 2\n"}
    ))
    assert "binary_file" in result.symbols[0].notes


def test_mode_only_change_reports_nothing() -> None:
    result = run({}, {}, diff="diff --git a/run.py b/run.py\nold mode 100644\nnew mode 100755\n")
    assert result.symbols == ()
    assert result.files[0].level.value == "none"


def test_missing_snapshot_degrades_with_reason() -> None:
    diff = make_diff({"a.py": "x = 1\n"}, {"a.py": "x = 2\n"})
    result = extract_symbol_changes(DictSnapshot({}), DictSnapshot({"a.py": "x = 2\n"}), diff)
    assert "snapshot_missing_base" in result.symbols[0].notes
    result = extract_symbol_changes(DictSnapshot({"a.py": "x = 1\n"}), DictSnapshot({}), diff)
    assert "snapshot_missing_head" in result.symbols[0].notes


def test_oversized_file_degrades() -> None:
    big = "x = 1\n" * 100
    result = run(
        {"a.py": big}, {"a.py": big + "y = 2\n"}, options=ExtractionOptions(max_file_bytes=100)
    )
    assert "file_too_large" in result.symbols[0].notes


def test_time_budget_degrades_remaining_files() -> None:
    base = {f"m{i}.py": "x = 1\n" for i in range(4)}
    head = {f"m{i}.py": "x = 2\n" for i in range(4)}
    ticks = iter([0.0, 0.0, 0.5, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0])
    diff = make_diff(base, head)
    result = extract_symbol_changes(
        DictSnapshot(base),
        DictSnapshot(head),
        diff,
        ExtractionOptions(time_budget_seconds=1.0),
        clock=lambda: next(ticks),
    )
    assert result.truncated
    levels = [f.level.value for f in result.files]
    assert levels[:2] == ["symbol", "symbol"] and levels[2:] == ["file", "file"]
    assert all("timeout" in f.notes for f in result.files[2:])


def test_max_files_degrades_the_tail() -> None:
    base = {f"m{i}.py": "x = 1\n" for i in range(3)}
    head = {f"m{i}.py": "x = 2\n" for i in range(3)}
    result = run(base, head, options=ExtractionOptions(max_files=1))
    assert result.truncated
    assert [f.level.value for f in result.files] == ["symbol", "file", "file"]
    assert "max_files_exceeded" in result.files[1].notes


def test_oversized_diff_is_refused_gracefully() -> None:
    result = run({"a.py": "x = 1\n"}, {"a.py": "x = 2\n"}, options=ExtractionOptions(max_diff_bytes=10))
    assert result.truncated and result.notes == ("diff_too_large",) and result.symbols == ()


def test_unreadable_internal_error_degrades_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    import radius_analysis.symbol_changes.service as service

    def boom(_text: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "index_python", boom)
    result = run({"a.py": "x = 1\n"}, {"a.py": "x = 2\n"})
    assert result.symbols[0].notes == ("internal_error:RuntimeError",)


def test_decode_errors_are_noted() -> None:
    head = b"x = '\xff'\n"
    diff = make_diff({"a.py": "x = 1\n"}, {"a.py": "x = 2\n"})
    result = extract_symbol_changes(DictSnapshot({"a.py": "x = 1\n"}), DictSnapshot({"a.py": head}), diff)
    assert "head_decode_errors" in result.files[0].notes


def test_lone_cr_is_normalised_to_keep_line_numbers() -> None:
    base = "def f():\r    return 1\r\ndef g():\n    return 1\n"
    head = "def f():\r    return 1\r\ndef g():\n    return 2\n"
    result = run({"a.py": base}, {"a.py": head})
    assert summary(result) == [("g", "function", "modified_body")]
    assert "head_lone_cr_normalized" in result.files[0].notes


# ----------------------------------------------------------------------- ignore / generated


def test_default_ignore_globs_and_generated_headers() -> None:
    files = {
        "node_modules/x/index.js": "a=1\n",
        "web/dist/app.min.js": "a=1\n",
        "proto/api_pb2.py": "a = 1\n",
        "src/gen.py": "# Code generated by tool. DO NOT EDIT.\na = 1\n",
        "src/real.py": "def f():\n    return 1\n",
    }
    head = {k: v.replace("1", "2") for k, v in files.items()}
    result = run(files, head)
    assert [s.path for s in result.symbols] == ["src/real.py"]
    ignored = {f.path: f.notes for f in result.files if f.level.value == "ignored"}
    assert set(ignored) == {
        "node_modules/x/index.js", "web/dist/app.min.js", "proto/api_pb2.py", "src/gen.py"
    }
    assert ignored["src/gen.py"] == ("ignored:generated_header",)


def test_ignore_list_is_configurable() -> None:
    files = {"vendor/lib.py": "def f():\n    return 1\n"}
    head = {"vendor/lib.py": "def f():\n    return 2\n"}
    assert run(files, head).symbols == ()
    opts = ExtractionOptions(ignore_globs=(), detect_generated_headers=False)
    assert len(run(files, head, options=opts).symbols) == 1
    assert is_ignored("a/b/c.py", ("a/*/c.py",)) == "a/*/c.py"
    assert is_ignored("a/b/c.py", ("b/",)) == "b/"
    assert is_ignored("a/b.py", ("b/",)) is None
    assert detect_language("X.TSX") == ("typescript", ".tsx")
    assert detect_language("README")[0] == "unknown"


# ----------------------------------------------------------------------- model / determinism


def _sample() -> tuple[dict[str, str], dict[str, str]]:
    base = {
        "a.py": "import os\n\n\ndef f(a):\n    return a\n\n\nclass K:\n    def m(self):\n        return 1\n",
        "web/b.ts": "export function g(a: number) {\n  return a;\n}\n",
        "README.md": "hi\n",
    }
    head = {
        "a.py": "import os\nimport sys\n\n\ndef f(a, b=1):\n    return a\n\n\nclass K:\n    def m(self):\n        return 2\n",
        "web/b.ts": "export function g(a: number) {\n  return a + 1;\n}\n",
        "README.md": "hello\n",
        "new.py": "def n():\n    return 1\n",
    }
    return base, head


def test_json_roundtrip_and_contract_fields() -> None:
    result = run(*_sample())
    again = SymbolChangeSet.from_json(result.to_json())
    assert again == result
    assert again.to_json() == result.to_json()
    data = json.loads(result.to_json())
    assert data["algo_version"] == ALGO_VERSION == "symbol-changes-v1"
    assert set(data) == {
        "algo_version", "config", "truncated", "notes", "counts", "files", "symbols",
        "unattributed_hunks",
    }
    sym = data["symbols"][0]
    assert {
        "symbol_id", "key", "language", "path", "qualified_name", "kind", "change_kind",
        "secondary_kinds", "is_behavioral", "old_symbol_id", "new_symbol_id", "old_path",
        "old_qualified_name", "old_range", "new_range", "old_signature", "new_signature",
        "old_body_hash", "new_body_hash", "hunks", "confidence", "notes",
    } <= set(sym)
    assert data["counts"]["symbols"] == len(data["symbols"])
    assert result.for_path("a.py")


def test_output_is_deterministic_and_order_independent() -> None:
    base, head = _sample()
    first = run(base, head).to_json()
    for _ in range(3):
        assert run(base, head).to_json() == first
    shuffled_base = dict(reversed(list(base.items())))
    shuffled_head = dict(reversed(list(head.items())))
    assert run(shuffled_base, shuffled_head).to_json() == first
    # diff file order must not matter either
    diffs = parse_unified_diff(make_diff(base, head))
    assert len(diffs) == 4


def test_symbols_are_sorted_by_path_then_line() -> None:
    result = run(*_sample())
    keys = [s.sort_key() for s in result.symbols]
    assert keys == sorted(keys)


def test_formatting_mutation_does_not_change_the_symbol_set() -> None:
    """LK-01 acceptance: re-formatting the head never adds or removes a changed symbol."""

    base = {"a.py": "def f(a):\n    return a\n\n\ndef g(a):\n    return a\n"}
    head = {"a.py": "def f(a):\n    return a + 1\n\n\ndef g(a):\n    return a\n"}
    plain = run(base, head)
    noisy_head = {"a.py": "def f(a):\n    return (a+1)\n\n\n\ndef g( a ):\n    return a\n"}
    noisy = run(base, noisy_head)
    changed_names = lambda r: {s.qualified_name for s in r.symbols if s.is_behavioral}  # noqa: E731
    assert changed_names(plain) == changed_names(noisy) == {"f"}


def test_change_kind_helpers() -> None:
    assert not ChangeKind.FORMATTING_ONLY.is_behavioral
    assert not ChangeKind.DOCSTRING_OR_COMMENT_ONLY.is_behavioral
    assert ChangeKind.MODIFIED_BODY.is_behavioral
    assert compress_lines([5, 1, 2, 3, 3, 9]) == compress_lines({1, 2, 3, 5, 9})
    assert [(r.start, r.end) for r in compress_lines([5, 1, 2, 3, 9])] == [(1, 3), (5, 5), (9, 9)]
    assert expand_ranges(compress_lines([1, 2, 4])) == {1, 2, 4}


# ----------------------------------------------------------------------- accounting property


def _changed_lines(diff_text: str) -> set[tuple[str, int, str, int]]:
    out: set[tuple[str, int, str, int]] = set()
    for fd in parse_unified_diff(diff_text):
        for hunk in fd.hunks:
            out |= {(fd.path, hunk.index, "-", n) for n in hunk.deleted}
            out |= {(fd.path, hunk.index, "+", n) for n in hunk.added}
    return out


def _attributed_lines(result: SymbolChangeSet) -> set[tuple[str, int, str, int]]:
    out: set[tuple[str, int, str, int]] = set()
    hunks = [h for s in result.symbols for h in s.hunks] + [u.hunk for u in result.unattributed_hunks]
    for h in hunks:
        out |= {(h.path, h.hunk_index, "-", n) for n in expand_ranges(h.old_lines)}
        out |= {(h.path, h.hunk_index, "+", n) for n in expand_ranges(h.new_lines)}
    return out


_PY_POOL = [
    "    x = 1", "    return x", "# comment", "import os", "", "    pass", "@decorator",
    "def extra(a):", "class Extra:", "    y = 2", "X = 3", "    ", "def (", "\treturn 1",
]
_TS_POOL = [
    "  const x = 1;", "  return x;", "// comment", "import a from 'a';", "", "}", "{",
    "export function extra(a: number) {", "class Extra {", "  y = 2;", "const X = 3;", "/* c */",
]


def _mutate(text: str, rng: random.Random, pool: list[str]) -> str:
    lines = text.split("\n")
    for _ in range(rng.randint(1, 6)):
        op = rng.choice(["delete", "insert", "replace", "dup"])
        if not lines:
            break
        i = rng.randrange(len(lines))
        if op == "delete":
            del lines[i]
        elif op == "insert":
            lines.insert(i, rng.choice(pool))
        elif op == "replace":
            lines[i] = rng.choice(pool)
        else:
            lines.insert(i, lines[i])
    return "\n".join(lines)


PY_BASE = (
    "import os\n\nX = 1\n\n\n@dec\ndef f(a, b=2):\n    \"\"\"Doc.\"\"\"\n    x = a + b\n    return x\n\n\n"
    "class K(Base):\n    y = 1\n\n    def m(self):\n        def inner():\n            return 1\n"
    "        return inner()\n\n    @property\n    def p(self):\n        return 2\n\n\n"
    "g = lambda q: q + 1\n"
)
TS_BASE = (
    "import a from 'a';\n\nexport const X = 1;\n\n/** doc */\nexport function f(a: number) {\n"
    "  const x = a + 1;\n  return x;\n}\n\nexport class K {\n  y = 1;\n  m() {\n"
    "    return 1;\n  }\n}\n\nexport const h = (q: number) => q + 1;\n"
)


@pytest.mark.parametrize("seed", range(120))
@pytest.mark.parametrize(("path", "base", "pool"), [
    ("m.py", PY_BASE, _PY_POOL),
    ("m.ts", TS_BASE, _TS_POOL),
])
def test_every_changed_line_is_attributed_or_unattributed(
    seed: int, path: str, base: str, pool: list[str]
) -> None:
    rng = random.Random(seed)
    head = _mutate(base, rng, pool)
    if head == base:
        return
    diff = make_diff({path: base}, {path: head}, context=rng.choice([0, 1, 3]))
    result = run({path: base}, {path: head}, diff=diff)
    assert _attributed_lines(result) == _changed_lines(diff)
    # determinism for the very same input
    assert run({path: base}, {path: head}, diff=diff).to_json() == result.to_json()


def test_accounting_across_files_add_delete_and_move() -> None:
    base = {"a.py": PY_BASE, "gone.py": PY_BASE, "t.ts": TS_BASE}
    head = {"a.py": PY_BASE.replace("a + b", "a - b"), "new.py": PY_BASE, "t.ts": TS_BASE.replace("q + 1", "q")}
    diff = make_diff(base, head)
    result = run(base, head, diff=diff)
    assert _attributed_lines(result) == _changed_lines(diff)


# ----------------------------------------------------------------------- scale


def test_huge_file_is_fast() -> None:
    funcs = "".join(f"def func_{i}(a):\n    value = a + {i}\n    return value\n\n\n" for i in range(4000))
    base = {"big.py": funcs}
    head = {"big.py": funcs.replace("a + 2000", "a - 2000")}
    started = time.perf_counter()
    result = run(base, head)
    assert time.perf_counter() - started < 20
    assert summary(result) == [("func_2000", "function", "modified_body")]


def test_many_unmatched_symbols_respect_the_similarity_budget() -> None:
    old = "".join(f"def old_{i}(a):\n    value = a * {i} + {i} - a\n    return value / 2\n\n" for i in range(30))
    new = old.replace("old_", "new_").replace("* ", "+ ")
    result = run({"a.py": old}, {"a.py": new}, options=ExtractionOptions(max_similarity_pairs=5))
    assert "rename_detection_skipped_limit" in result.notes


def test_deeply_nested_expression_does_not_crash() -> None:
    deep = "x = " + "(" * 400 + "1" + ")" * 400 + "\n"
    result = run({"a.py": "x = 1\n"}, {"a.py": deep})
    assert result.symbols  # either a module change or a degraded file-level unit


# ----------------------------------------------------------------------- snapshots


def test_diff_reversed_snapshot_rebuilds_the_base() -> None:
    base, head = _sample()
    diff = make_diff(base, head)
    rebuilt = DiffReversedSnapshot(DictSnapshot(head), parse_unified_diff(diff))
    for path in ("a.py", "web/b.ts", "README.md"):
        assert rebuilt.read(path) == base[path].encode()
    assert rebuilt.read("new.py") is None
    full = extract_symbol_changes(DictSnapshot(base), DictSnapshot(head), diff)
    assert extract_symbol_changes(None, DictSnapshot(head), diff).to_json() == full.to_json()


def test_diff_reversed_snapshot_handles_deleted_files_and_mismatch() -> None:
    diff = make_diff({"gone.py": "a = 1\nb = 2\n", "k.py": "x = 1\n"}, {"k.py": "x = 2\n"})
    snap = DiffReversedSnapshot(DictSnapshot({"k.py": "x = 2\n"}), parse_unified_diff(diff))
    assert snap.read("gone.py") == b"a = 1\nb = 2\n"
    wrong = DiffReversedSnapshot(DictSnapshot({"k.py": "something else\n"}), parse_unified_diff(diff))
    assert wrong.read("k.py") is None
    assert snap.read("untouched.py") is None
    binary = parse_unified_diff("diff --git a/i b/i\nBinary files a/i and b/i differ\n")
    assert DiffReversedSnapshot(DictSnapshot({"i": b"x"}), binary).read("i") is None


def test_directory_snapshot_is_confined_to_its_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_bytes(b"x = 1\n")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    snap = DirectorySnapshot(root)
    assert snap.read("pkg/a.py") == b"x = 1\n"
    assert snap.read("../secret.txt") is None
    assert snap.read("/etc/passwd") is None
    assert snap.read("pkg") is None
    assert snap.read("missing.py") is None


def test_git_snapshot_rejects_option_like_refs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid git ref"):
        GitSnapshot(tmp_path, "--upload-pack=evil")
    with pytest.raises(ValueError, match="Invalid git ref"):
        GitSnapshot(tmp_path, "")
    assert GitSnapshot(tmp_path, "HEAD").read("../x") is None
    assert GitSnapshot(tmp_path / "nope", "HEAD").read("a.py") is None


# ----------------------------------------------------------------------- git integration


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_real_git_repository_refs_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-q", "-b", "main")
    (tmp_path / "pkg").mkdir()
    body = "    total = 0\n    for i in items:\n        if i.ok and i.price > 0:\n            total += i.price * i.qty\n    return total\n"
    (tmp_path / "pkg" / "a.py").write_text(f"def compute(items):\n{body}", encoding="utf-8", newline="\n")
    (tmp_path / "pkg" / "b.py").write_text("X = 1\n", encoding="utf-8", newline="\n")
    git("add", ".")
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "feature")
    git("mv", "pkg/a.py", "pkg/moved.py")
    (tmp_path / "pkg" / "moved.py").write_text(
        f"def compute_all(items):\n{body}", encoding="utf-8", newline="\n"
    )
    (tmp_path / "pkg" / "b.py").write_text("X = 2\n", encoding="utf-8", newline="\n")
    git("add", ".")
    git("commit", "-q", "-m", "head")

    refs = RefRange(tmp_path, "main", "feature")
    result = extract_symbol_changes(None, GitSnapshot(tmp_path, "feature"), refs)
    kinds = {(s.path, s.qualified_name, s.change_kind.value) for s in result.symbols}
    assert ("pkg/b.py", "<module>", "modified_body") in kinds
    assert any(
        s.path == "pkg/moved.py" and s.old_path == "pkg/a.py" and s.qualified_name == "compute_all"
        for s in result.symbols
    )

    assert cli_main(["--repo", str(tmp_path), "--base", "main", "--head", "feature", "--indent", "0"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["algo_version"] == ALGO_VERSION
    assert printed["counts"]["symbols"] == len(result.symbols)


def test_cli_with_diff_file_and_head_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = {"a.py": "def f():\n    return 1\n"}
    head = {"a.py": "def f():\n    return 2\n"}
    (tmp_path / "head").mkdir()
    (tmp_path / "head" / "a.py").write_text(head["a.py"], encoding="utf-8")
    patch = tmp_path / "pr.patch"
    patch.write_text(make_diff(base, head), encoding="utf-8")
    assert cli_main(["--diff", str(patch), "--head-dir", str(tmp_path / "head"), "--ignore", "*.md"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [s["qualified_name"] for s in data["symbols"]] == ["f"]
    assert cli_main(["--diff", str(patch)]) == 2
    assert cli_main([]) == 2


# ----------------------------------------------------------------------- F-14 golden fixtures


def _tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


FIXTURE_DIRS = sorted(d for d in FIXTURES.iterdir() if (d / "pr.patch").exists()) if FIXTURES.exists() else []


@pytest.mark.skipif(not FIXTURE_DIRS, reason="F-14 fixtures not present")
@pytest.mark.parametrize("fixture", FIXTURE_DIRS, ids=[d.name for d in FIXTURE_DIRS])
def test_f14_fixture_sanity(fixture: Path) -> None:
    diff = (fixture / "pr.patch").read_text(encoding="utf-8")
    base, head = _tree(fixture / "base"), _tree(fixture / "head")
    result = extract_symbol_changes(DictSnapshot(base), DictSnapshot(head), diff)
    assert _attributed_lines(result) == _changed_lines(diff)
    assert all(f.level.value in {"symbol", "file"} for f in result.files)
    # base rebuilt from head + patch gives exactly the same answer
    assert extract_symbol_changes(None, DictSnapshot(head), diff).to_json() == result.to_json()
    # every changed Python file has at least one changed symbol
    for fd in parse_unified_diff(diff):
        if fd.path.endswith(".py"):
            assert result.for_path(fd.path), fd.path


@pytest.mark.skipif(not FIXTURE_DIRS, reason="F-14 fixtures not present")
def test_f14_test_tampering_fixture_exposes_what_ev02_needs() -> None:
    fixture = FIXTURES / "04_test_tampering"
    diff = (fixture / "pr.patch").read_text(encoding="utf-8")
    result = extract_symbol_changes(
        DictSnapshot(_tree(fixture / "base")), DictSnapshot(_tree(fixture / "head")), diff
    )
    by_name = {s.qualified_name: s for s in result.symbols}
    assert by_name["reserve"].change_kind is ChangeKind.MODIFIED_BODY
    assert by_name["reserve"].path == "src/stock.py"
    assert by_name["test_reserve_more_than_stock_raises"].change_kind is ChangeKind.REMOVED
    assert by_name["test_reserve_exact_stock"].change_kind is ChangeKind.MODIFIED_BODY
    assert by_name["test_reserve_rejects_non_positive"].change_kind is (
        ChangeKind.DECORATOR_OR_ANNOTATION_CHANGED
    )
    removed = by_name["test_reserve_more_than_stock_raises"]
    assert removed.old_range is not None and removed.new_range is None and removed.hunks
