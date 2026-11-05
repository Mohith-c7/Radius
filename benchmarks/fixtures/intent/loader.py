"""Loader and verifier for the intent-to-evidence golden fixtures (F-14).

Each sub-directory next to this file is one fixture::

    <id>/
      README.md        what the fixture demonstrates
      intent.md        the intent source (PR description)
      expected.json    labelled ground truth (validated by expected.schema.json)
      base/            repository state before the change
      head/            repository state after the change
      probes/          optional extra tests overlaid on head (stronger evidence)
      pr.patch         unified diff base -> head (generated, kept in sync by test)

CLI (run from anywhere)::

    python benchmarks/fixtures/intent/loader.py list
    python benchmarks/fixtures/intent/loader.py validate    # schema only
    python benchmarks/fixtures/intent/loader.py verify      # schema + run tests
    python benchmarks/fixtures/intent/loader.py write-patches
    python benchmarks/fixtures/intent/loader.py harness     # harness kwargs as JSON

``verify`` really executes pytest on base, head, head+probes and every declared
mutant, and compares per-test outcomes with ``expected.json``. Only the Python
standard library and ``pytest`` are required.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = FIXTURES_DIR / "expected.schema.json"
_SKIP_PARTS = {"__pycache__", ".pytest_cache"}


# --------------------------------------------------------------------------- IO


def _read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def read_tree(root: Path) -> dict[str, str]:
    """Return {posix relative path: text} for every file under root."""
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not (_SKIP_PARTS & set(path.relative_to(root).parts)):
            if path.suffix == ".pyc":
                continue
            files[path.relative_to(root).as_posix()] = _read_text(path)
    return files


def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------- fixture


@dataclass(frozen=True)
class Fixture:
    id: str
    path: Path
    expected: dict

    @property
    def base(self) -> dict[str, str]:
        return read_tree(self.path / "base")

    @property
    def head(self) -> dict[str, str]:
        return read_tree(self.path / "head")

    @property
    def probes(self) -> dict[str, str]:
        probes = self.path / "probes"
        return read_tree(probes) if probes.is_dir() else {}

    def patch_text(self) -> str:
        return make_patch(self.base, self.head)


def discover() -> list[Fixture]:
    fixtures = []
    for path in sorted(FIXTURES_DIR.iterdir()):
        if path.is_dir() and (path / "expected.json").is_file():
            expected = json.loads(_read_text(path / "expected.json"))
            fixtures.append(Fixture(id=path.name, path=path, expected=expected))
    return fixtures


def make_patch(base: dict[str, str], head: dict[str, str]) -> str:
    """Deterministic unified diff (a/ b/ prefixes) between two file maps."""
    chunks: list[str] = []
    for rel in sorted(set(base) | set(head)):
        old, new = base.get(rel), head.get(rel)
        if old == new:
            continue
        old_lines = old.splitlines(keepends=True) if old is not None else []
        new_lines = new.splitlines(keepends=True) if new is not None else []
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{rel}" if old is not None else "/dev/null",
            tofile=f"b/{rel}" if new is not None else "/dev/null",
        )
        chunks.append(f"diff --git a/{rel} b/{rel}\n" + "".join(diff))
    return "".join(chunks)


def harness_kwargs(fixture: Fixture) -> dict:
    """Arguments for ``benchmarks.scenarios.harness.Scenario`` (base, change, delete)."""
    base, head = fixture.base, fixture.head
    change = {rel: text for rel, text in head.items() if base.get(rel) != text}
    delete = tuple(sorted(rel for rel in base if rel not in head))
    return {
        "name": fixture.id,
        "base": base,
        "change": change,
        "delete": delete,
        "expect_full_suite_fails": any(
            v in {"failed", "error"}
            for v in fixture.expected["test_outcomes"]["head"].values()
        ),
    }


# ------------------------------------------------------------------ schema check


def validate_schema(instance, schema, root_schema=None, path="$") -> list[str]:
    """Validate against the JSON Schema subset used by expected.schema.json.

    Supported keywords: type (name or list), enum, const, required, properties,
    additionalProperties (bool or schema), items, minItems, minLength, pattern,
    uniqueItems, patternProperties, $ref (local "#/$defs/..").
    """
    root_schema = root_schema or schema
    errors: list[str] = []
    if "$ref" in schema:
        node = root_schema
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return validate_schema(instance, node, root_schema, path)

    types = schema.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        if not any(_is_type(instance, name) for name in names):
            return [f"{path}: expected {names}, got {type(instance).__name__}"]
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in {schema['enum']}")
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(f"{path}: {instance!r} !~ {schema['pattern']}")
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if schema.get("uniqueItems") and len({json.dumps(i, sort_keys=True) for i in instance}) != len(instance):
            errors.append(f"{path}: items not unique")
        if "items" in schema:
            for i, item in enumerate(instance):
                errors += validate_schema(item, schema["items"], root_schema, f"{path}[{i}]")
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required '{key}'")
        pattern_props = schema.get("patternProperties", {})
        for key, value in instance.items():
            if key in props:
                errors += validate_schema(value, props[key], root_schema, f"{path}.{key}")
                continue
            matched = [s for p, s in pattern_props.items() if re.search(p, key)]
            for sub in matched:
                errors += validate_schema(value, sub, root_schema, f"{path}.{key}")
            if not matched:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    errors.append(f"{path}: unexpected property '{key}'")
                elif isinstance(extra, dict):
                    errors += validate_schema(value, extra, root_schema, f"{path}.{key}")
    return errors


def _is_type(value, name: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "null": value is None,
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
    }[name]


def load_schema() -> dict:
    return json.loads(_read_text(SCHEMA_PATH))


def check_consistency(fixture: Fixture) -> list[str]:
    """Cross-field checks that JSON Schema cannot express."""
    exp = fixture.expected
    errors: list[str] = []
    crit_ids = [c["id"] for c in exp["criteria"]]
    if len(set(crit_ids)) != len(crit_ids):
        errors.append("duplicate criterion ids")
    all_tests = {t for state in exp["test_outcomes"].values() for t in state}
    for link in exp["links"]:
        if link["criterion"] not in crit_ids:
            errors.append(f"link to unknown criterion {link['criterion']}")
        for test in link["tests"]:
            if test not in all_tests:
                errors.append(f"link test not in any test_outcomes: {test}")
    banded = {e["test"] for e in exp["evidence_quality"]}
    for test in banded:
        if test not in all_tests:
            errors.append(f"evidence_quality test unknown: {test}")
    for mutant in exp.get("mutants", []):
        for test in mutant["killed_by"]:
            if test not in exp["test_outcomes"]["head"]:
                errors.append(f"mutant {mutant['id']} killed_by unknown test {test}")
    if not (fixture.path / "README.md").is_file():
        errors.append("README.md missing")
    if not (fixture.path / "intent.md").is_file():
        errors.append("intent.md missing")
    return errors


# --------------------------------------------------------------- test execution


def run_pytest(files: dict[str, str]) -> dict[str, str]:
    """Run pytest on a file map in an isolated temp dir; return per-test outcomes.

    Outcome ids look like ``tests/test_x.py::test_name`` and map to one of
    passed / failed / skipped / error.
    """
    with tempfile.TemporaryDirectory(prefix="radius-fixture-") as tmp:
        root = Path(tmp)
        write_tree(root, files)
        report = root / "_junit.xml"
        subprocess.run(
            [
                sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
                f"--junitxml={report}", "-q", "--no-header",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if not report.is_file():
            raise RuntimeError("pytest produced no junit report")
        return _parse_junit(report)


def _parse_junit(report: Path) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for case in ET.parse(report).getroot().iter("testcase"):
        classname = case.get("classname", "")
        test_id = f"{classname.replace('.', '/')}.py::{case.get('name')}"
        if case.find("failure") is not None:
            outcome = "failed"
        elif case.find("error") is not None:
            outcome = "error"
        elif case.find("skipped") is not None:
            outcome = "skipped"
        else:
            outcome = "passed"
        outcomes[test_id] = outcome
    return outcomes


def apply_mutant(files: dict[str, str], mutant: dict) -> dict[str, str]:
    text = files[mutant["file"]]
    if text.count(mutant["old"]) != 1:
        raise ValueError(
            f"mutant {mutant['id']}: 'old' must occur exactly once in {mutant['file']}"
        )
    mutated = dict(files)
    mutated[mutant["file"]] = text.replace(mutant["old"], mutant["new"])
    return mutated


def verify_outcomes(fixture: Fixture) -> list[str]:
    """Re-run the claimed behaviour; return a list of mismatches (empty = ok)."""
    exp = fixture.expected
    errors: list[str] = []

    def compare(label: str, actual: dict[str, str], claimed: dict[str, str]) -> None:
        if actual != claimed:
            errors.append(f"{label}: claimed {claimed} but actual {actual}")

    base, head = fixture.base, fixture.head
    compare("base", run_pytest(base), exp["test_outcomes"]["base"])
    compare("head", run_pytest(head), exp["test_outcomes"]["head"])
    if "head_with_probes" in exp["test_outcomes"]:
        probes = fixture.probes
        if not probes:
            errors.append("head_with_probes claimed but no probes/ directory")
        compare(
            "head_with_probes",
            run_pytest({**head, **probes}),
            exp["test_outcomes"]["head_with_probes"],
        )
    for mutant in exp.get("mutants", []):
        actual = run_pytest(apply_mutant(head, mutant))
        failed = sorted(t for t, o in actual.items() if o in {"failed", "error"})
        if failed != sorted(mutant["killed_by"]):
            errors.append(
                f"mutant {mutant['id']}: claimed killed_by {sorted(mutant['killed_by'])}, actual {failed}"
            )
    return errors


# --------------------------------------------------------------------------- CLI


def _cmd_list(_: argparse.Namespace) -> int:
    for fx in discover():
        e = fx.expected
        print(f"{fx.id:42} {e['scenario']:24} verdict={e['expected_verdict']}")
    return 0


def _cmd_validate(_: argparse.Namespace) -> int:
    schema, bad = load_schema(), 0
    for fx in discover():
        errors = validate_schema(fx.expected, schema) + check_consistency(fx)
        print(f"{'OK  ' if not errors else 'FAIL'} {fx.id}")
        for err in errors:
            print(f"     {err}")
        bad += bool(errors)
    return 1 if bad else 0


def _cmd_verify(args: argparse.Namespace) -> int:
    schema, bad = load_schema(), 0
    for fx in discover():
        errors = validate_schema(fx.expected, schema) + check_consistency(fx)
        if not errors:
            errors += verify_outcomes(fx)
        if fx.patch_text() != _read_text(fx.path / "pr.patch"):
            errors.append("pr.patch out of date (run write-patches)")
        print(f"{'OK  ' if not errors else 'FAIL'} {fx.id}")
        for err in errors:
            print(f"     {err}")
        bad += bool(errors)
    return 1 if bad else 0


def _cmd_write_patches(_: argparse.Namespace) -> int:
    for fx in discover():
        (fx.path / "pr.patch").write_text(fx.patch_text(), encoding="utf-8", newline="\n")
        print(f"wrote {fx.id}/pr.patch")
    return 0


def _cmd_harness(_: argparse.Namespace) -> int:
    print(json.dumps([harness_kwargs(fx) for fx in discover()], indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn in (
        ("list", _cmd_list),
        ("validate", _cmd_validate),
        ("verify", _cmd_verify),
        ("write-patches", _cmd_write_patches),
        ("harness", _cmd_harness),
    ):
        sub.add_parser(name).set_defaults(fn=fn)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
