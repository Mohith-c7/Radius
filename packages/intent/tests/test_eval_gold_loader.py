"""IN-10: gold contract validation, offset units, hashing and loaders."""
# ruff: noqa: E402, I001  (helper import needs the sys.path setup below, as in the IN-03 tests)
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
if _HERE not in _sys.path:  # helper module lives next to the tests (importlib mode)
    _sys.path.insert(0, _HERE)

import copy
import json
import sys

import pytest
from eval_helpers import F14_DIR, SYNTHETIC_GOLD, load_synthetic_doc
from radius_intent.domain import IntentSourceKind, Testability
from radius_intent.evaluation.gold import (
    GOLD_SCHEMA_ID,
    EvalSpan,
    GoldFormatError,
    convert_offsets,
    parse_gold,
)
from radius_intent.evaluation.loader import (
    GoldLoadError,
    adapt_f14_fixtures,
    load_gold,
    register_adapter,
    resolve_adapter,
)


def minimal(**over):
    doc = {
        "schema": GOLD_SCHEMA_ID,
        "name": "t",
        "version": "1",
        "split": "dev",
        "cases": [
            {
                "case_id": "a",
                "sources": [
                    {"source_id": "s", "kind": "pr_body", "text": "hello world"}
                ],
                "criteria": [
                    {"id": "C1", "span": {"source_id": "s", "start": 0, "end": 5}}
                ],
            }
        ],
    }
    doc.update(over)
    return doc


def errors_of(doc):
    with pytest.raises(GoldFormatError) as exc:
        parse_gold(doc)
    return exc.value.errors


def test_synthetic_gold_parses_and_hash_is_stable():
    ds = parse_gold(load_synthetic_doc())
    assert ds.synthetic and len(ds.cases) == 10
    assert ds.sha256 == parse_gold(load_synthetic_doc()).sha256
    assert any("share a span" in w for w in ds.warnings)
    kinds = {s.kind for c in ds.cases for s in c.sources}
    assert {IntentSourceKind.ISSUE, IntentSourceKind.AGENT_PROMPT} <= kinds


def test_hash_ignores_case_order_but_not_content():
    doc = load_synthetic_doc()
    shuffled = copy.deepcopy(doc)
    shuffled["cases"].reverse()
    assert parse_gold(doc).sha256 == parse_gold(shuffled).sha256
    changed = copy.deepcopy(doc)
    changed["cases"][0]["criteria"][0]["testability"] = "subjective_or_vague"
    assert parse_gold(doc).sha256 != parse_gold(changed).sha256


def test_legacy_testability_names_are_accepted():
    doc = minimal()
    doc["cases"][0]["criteria"][0]["testability"] = "vague"
    assert parse_gold(doc).cases[0].criteria[0].testability is Testability.VAGUE


def _dup_source(d):
    d["cases"][0]["sources"].append(dict(d["cases"][0]["sources"][0]))


def _dup_criterion(d):
    d["cases"][0]["criteria"].append(dict(d["cases"][0]["criteria"][0]))


def _dup_case(d):
    d["cases"].append(copy.deepcopy(d["cases"][0]))


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda d: d.update(schema="nope"), "$.schema"),
        (lambda d: d.update(name=""), "$.name"),
        (lambda d: d.update(cases=[]), "non-empty list"),
        (lambda d: d.update(synthetic="yes"), "$.synthetic"),
        (lambda d: d.update(offset_unit="bytes"), "offset_unit"),
        (lambda d: d.update(notes="x"), "$.notes"),
        (lambda d: d["cases"][0].update(case_id=""), "case_id"),
        (lambda d: d["cases"][0].update(sources=[]), "sources"),
        (lambda d: d["cases"][0]["sources"][0].update(kind="tweet"), "unknown source kind"),
        (lambda d: d["cases"][0]["sources"][0].update(text=5), "text must be a string"),
        (lambda d: d["cases"][0]["sources"][0].update(source_id=""), "source_id must be"),
        (_dup_source, "duplicate source_id"),
        (lambda d: d["cases"][0].update(well_specified="maybe"), "well_specified"),
        (lambda d: d["cases"][0].update(group=3), "group must be"),
        (lambda d: d["cases"][0].update(offset_unit="x"), "offset_unit"),
        (lambda d: d["cases"][0].update(criteria={}), "criteria must be a list"),
        (lambda d: d["cases"][0]["criteria"].append(5), "criterion must be an object"),
        (lambda d: d["cases"][0]["criteria"][0].update(id=""), "id must be"),
        (lambda d: d["cases"][0]["criteria"][0]["span"].update(end=99), "span [0,99)"),
        (lambda d: d["cases"][0]["criteria"][0]["span"].update(end=0), "span [0,0)"),
        (lambda d: d["cases"][0]["criteria"][0]["span"].update(start="a"), "integers"),
        (lambda d: d["cases"][0]["criteria"][0].update(span=7), "span must be an object"),
        (lambda d: d["cases"][0]["criteria"][0]["span"].update(source_id="zzz"), "unknown source_id"),
        (lambda d: d["cases"][0]["criteria"][0].update(testability="shiny"), "unknown testability"),
        (lambda d: d["cases"][0]["criteria"][0].update(testability="unrated"), "not a valid gold label"),
        (lambda d: d["cases"][0]["criteria"][0].update(text=3), "text must be"),
        (lambda d: d["cases"][0]["criteria"][0].update(alt_spans="x"), "alt_spans"),
        (_dup_criterion, "duplicate criterion id"),
        (_dup_case, "duplicate case_id"),
    ],
)
def test_validation_errors_are_reported(mutate, fragment):
    doc = minimal()
    mutate(doc)
    assert any(fragment in e for e in errors_of(doc))


def test_all_errors_are_collected_not_just_the_first():
    doc = minimal(name="", split="")
    doc["cases"][0]["criteria"][0]["span"]["end"] = 99
    errors = errors_of(doc)
    assert len(errors) >= 3
    assert "3 gold format error(s)" in str(GoldFormatError(errors[:3]))


def test_error_message_truncates_long_lists():
    msg = str(GoldFormatError([f"e{i}" for i in range(15)]))
    assert "(+5 more)" in msg


def test_non_object_documents_rejected():
    assert errors_of([]) == ("$: document must be an object",)
    assert errors_of(minimal(cases=["x"]))[0].startswith("$.cases[0]")


def test_flat_criterion_form_and_alt_spans():
    doc = minimal()
    doc["cases"][0]["criteria"] = [
        {
            "id": "C1",
            "source_id": "s",
            "start": 0,
            "end": 5,
            "alt_spans": [{"source_id": "s", "start": 6, "end": 11}],
        }
    ]
    crit = parse_gold(doc).cases[0].criteria[0]
    assert crit.span.end == 5 and crit.alt_spans[0].start == 6
    assert len(crit.all_spans) == 2


def test_convert_offsets_all_units():
    text = "a\U0001f680béc"  # astral char: 2 utf16 units, 4 utf8 bytes; e-acute: 2 bytes
    assert convert_offsets(text, 1, 2, "codepoint") == (1, 2)
    assert convert_offsets(text, 1, 3, "utf16") == (1, 2)  # the emoji
    assert convert_offsets(text, 3, 4, "utf16") == (2, 3)  # b
    assert convert_offsets(text, 1, 5, "utf8") == (1, 2)
    assert convert_offsets(text, 6, 8, "utf8") == (3, 4)  # e-acute
    with pytest.raises(ValueError, match="splits a character"):
        convert_offsets(text, 2, 3, "utf16")  # inside the surrogate pair
    with pytest.raises(ValueError, match="splits a character"):
        convert_offsets(text, 7, 8, "utf8")
    with pytest.raises(ValueError, match="unknown offset_unit"):
        convert_offsets(text, 0, 1, "ucs4")


def test_utf16_offsets_in_a_document_are_converted_to_codepoints():
    text = "\U0001f680 ship it"
    doc = minimal()
    doc["offset_unit"] = "utf16"
    doc["cases"][0]["sources"][0]["text"] = text
    doc["cases"][0]["criteria"][0]["span"] = {"source_id": "s", "start": 3, "end": 7}
    crit = parse_gold(doc).cases[0].criteria[0]
    assert text[crit.span.start : crit.span.end] == "ship"


def test_case_helpers():
    case = parse_gold(load_synthetic_doc()).cases[0]
    assert case.kind_of("pr_body") is IntentSourceKind.PR_BODY
    assert case.kind_of("nope") is None and case.source("nope") is None
    assert case.slice(case.criteria[0].span).startswith("Users can export")
    assert case.slice(EvalSpan("nope", 0, 1)) == ""


# ---------------------------------------------------------------------- loader


def test_load_native_file_and_directory(tmp_path):
    ds = load_gold(SYNTHETIC_GOLD)
    assert len(ds.cases) == 10
    d = tmp_path / "gold"
    d.mkdir()
    doc = minimal()
    header = {k: v for k, v in doc.items() if k != "cases"}
    (d / "dataset.json").write_text(json.dumps(header), encoding="utf-8")
    one = doc["cases"][0]
    two = copy.deepcopy(one)
    two["case_id"] = "b"
    (d / "a.json").write_text(json.dumps(one), encoding="utf-8")
    (d / "b.json").write_text(json.dumps({"cases": [two]}), encoding="utf-8")
    assert [c.case_id for c in load_gold(d).cases] == ["a", "b"]


def test_load_errors(tmp_path):
    with pytest.raises(GoldLoadError, match="does not exist"):
        load_gold(tmp_path / "missing")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(GoldLoadError, match="invalid JSON"):
        load_gold(bad)
    arr = tmp_path / "arr.json"
    arr.write_text("[]", encoding="utf-8")
    with pytest.raises(GoldLoadError, match="JSON object"):
        load_gold(arr)
    invalid = tmp_path / "inv.json"
    invalid.write_text(json.dumps(minimal(name="")), encoding="utf-8")
    with pytest.raises(GoldLoadError, match=r"\$\.name"):
        load_gold(invalid)
    with pytest.raises(GoldLoadError, match="unknown adapter"):
        load_gold(invalid, "nope")


def test_custom_adapter_by_registration_and_import_path(tmp_path, monkeypatch):
    seen = []

    def adapter(path):
        seen.append(path.name)
        return minimal()

    register_adapter("unit-test", adapter)
    assert load_gold(tmp_path / "whatever", "unit-test").name == "t"
    assert seen == ["whatever"]

    (tmp_path / "my_adapter_mod.py").write_text(
        "import json\n"
        "def adapt(path):\n"
        f"    return json.loads({json.dumps(json.dumps(minimal()))})\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("my_adapter_mod", None)
    assert load_gold(tmp_path, "my_adapter_mod:adapt").cases[0].case_id == "a"
    with pytest.raises(GoldLoadError, match="cannot import"):
        resolve_adapter("my_adapter_mod:missing")
    with pytest.raises(GoldLoadError, match="cannot import"):
        resolve_adapter("no_such_module_xyz:f")
    (tmp_path / "not_callable_mod.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(GoldLoadError, match="not callable"):
        resolve_adapter("not_callable_mod:x")


def test_f14_adapter_derives_spans_from_fixtures():
    ds = load_gold(F14_DIR, "f14-fixtures")
    assert ds.synthetic and len(ds.cases) == 8
    by_id = {c.case_id: c for c in ds.cases}
    case = by_id["01_correct_strong_tests"]
    assert [case.slice(c.span) for c in case.criteria] == [
        "It returns the price reduced by `percent`, rounded to 2 decimals.",
        "`percent` must be within 0..100 inclusive; anything else raises `ValueError`.",
    ]
    assert all(c.testability is Testability.TESTABLE for c in case.criteria)
    vague = by_id["07_vague_intent"]
    assert len(vague.criteria) == 2 and vague.criteria[0].span == vague.criteria[1].span
    assert {c.testability for c in vague.criteria} == {
        Testability.VAGUE,
        Testability.NON_FUNCTIONAL,
    }
    assert any("criterion dropped" in n for n in ds.notes)  # prose fixture only partly alignable
    multi = by_id["05_scope_creep"]
    assert "Leading and trailing" in multi.slice(multi.criteria[1].span)


def test_f14_adapter_errors(tmp_path):
    with pytest.raises(GoldLoadError, match="not found"):
        adapt_f14_fixtures(tmp_path / "nope")
    with pytest.raises(GoldLoadError, match="no fixtures"):
        adapt_f14_fixtures(tmp_path)
    fx = tmp_path / "x"
    fx.mkdir()
    (fx / "expected.json").write_text(json.dumps({"id": "x", "criteria": []}), encoding="utf-8")
    with pytest.raises(GoldLoadError, match=r"intent\.md missing"):
        adapt_f14_fixtures(tmp_path)


def test_documented_json_schema_accepts_the_synthetic_gold_and_rejects_garbage():
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = F14_DIR.parents[2] / "docs" / "research" / "evaluation" / "intent_gold.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(load_synthetic_doc(), schema)
    bad = minimal()
    bad["cases"][0]["sources"][0]["kind"] = "tweet"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
    assert set(schema["required"]) == {"schema", "name", "version", "split", "cases"}
