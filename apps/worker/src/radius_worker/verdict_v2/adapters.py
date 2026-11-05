"""Pure adapters: producer outputs -> frozen ``radius_evidence`` input DTOs (VS-05).

Every function is total on dirty input: a malformed item is dropped and counted in
the returned :class:`Adapted` notes, never raised. Producers are imported only
under ``TYPE_CHECKING`` or duck-typed, so nothing here leaks a producer type into
``radius_evidence`` (design 2.2 rule 5). No I/O, no clocks.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from radius_evidence.domain.assertion_records import features_from_assertion_set
from radius_evidence.domain.enums import (
    ALL_PROVENANCE,
    TRUSTED_HINT_PROVENANCE,
    Outcome,
    Provenance,
)
from radius_evidence.domain.factories import (
    EvidenceInputError,
    finding_input_from_dict,
    normalize_test_id,
)
from radius_evidence.domain.independence import detect_agent_trailers
from radius_evidence.domain.inputs import (
    CaseOutcomeInput,
    CriterionInput,
    CriterionSymbolEdgeInput,
    CriterionTestEdgeInput,
    SymbolInput,
    SymbolTestEdgeInput,
    TamperFindingInput,
)
from radius_evidence.domain.model import AssertionFeatures, Reason

MODULE_SYMBOL = "<module>"
FILE_SYMBOL = "<file>"
#: Criterion lifecycle values that never enter the verdict (design 1.1).
DROPPED_LIFECYCLE = frozenset({"rejected", "orphaned"})
_TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$|(^|/)tests?/[^/]*\.py$")
_MAX_TEXT = 10_000
_MAX_HINTS = 50


@dataclass(frozen=True, slots=True)
class Adapted[T]:
    """Converted items plus the number of dropped inputs per reason code."""

    items: tuple[T, ...]
    dropped: Mapping[str, int]

    @property
    def notes(self) -> tuple[str, ...]:
        """``adapter_dropped:<what>`` markers (non-blocking degraded reasons)."""

        return tuple(f"adapter_dropped:{k}" for k, v in sorted(self.dropped.items()) if v)


def _unit(value: Any) -> float | None:
    """A finite float in [0, 1] (tiny float noise tolerated), else ``None``.

    Out-of-range scores are producer bugs: the item is dropped, never clamped.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < -1e-9 or value > 1.0 + 1e-9:
        return None
    return max(0.0, min(1.0, float(value)))


def _str(value: Any, limit: int = _MAX_TEXT) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value[:limit]


def _enum_value(value: Any) -> str:
    inner = getattr(value, "value", value)
    return inner if isinstance(inner, str) else str(inner)


def is_test_file(path: str) -> bool:
    """Heuristic for Python test files (mirrors LK-03 conventions)."""

    return bool(_TEST_FILE.search(path.replace("\\", "/")))


# ----------------------------------------------------------------- intent


_CONFIRMED_LIFECYCLE = frozenset({"confirmed", "edited"})


def criterion_provenance(
    criterion: Any, lifecycle: str, *, spec_provenance: str = Provenance.AUTHOR_HEAD_SPEC.value
) -> tuple[str, str]:
    """``(criterion provenance, hints provenance)`` of one IN-01 criterion (contract 3).

    * an explicit ``provenance`` / ``hints_provenance`` attribute (fixture harness,
      fakes) wins when it is one of the five known tags;
    * a criterion a human confirmed or edited (lifecycle ``confirmed`` / ``edited``;
      reachable only through the authenticated intent API) is ``human_confirmed``, and
      so are its hints;
    * an LLM-extracted criterion is ``llm_proposed``;
    * otherwise the source decides: the spec file is ``spec_provenance`` (``base_spec``
      only when the same file exists unchanged on the base ref, else
      ``author_head_spec``); every other source (PR title/body, commits, comments,
      issues, agent prompt) is ``author_pr_body`` because the PR author may control it.
    """

    origin = getattr(criterion, "origin", None)
    source = getattr(origin, "source", None)
    kind = _enum_value(getattr(source, "kind", "")) if source is not None else ""
    method = _enum_value(getattr(origin, "extraction_method", "")) if origin is not None else ""
    if lifecycle in _CONFIRMED_LIFECYCLE:
        crit = hint = Provenance.HUMAN_CONFIRMED.value
    else:
        if method == "llm":
            crit = Provenance.LLM_PROPOSED.value
        elif kind == "spec_file":
            crit = spec_provenance
        else:
            crit = Provenance.AUTHOR_PR_BODY.value
        hint = spec_provenance if kind == "spec_file" else Provenance.AUTHOR_PR_BODY.value
    explicit = getattr(criterion, "provenance", None)
    if isinstance(explicit, str) and explicit in ALL_PROVENANCE:
        crit = explicit
    explicit_hint = getattr(criterion, "hints_provenance", None)
    if isinstance(explicit_hint, str) and explicit_hint in ALL_PROVENANCE:
        hint = explicit_hint
    return crit, hint


#: Extractor version prefix of criteria inferred from ordinary PR text (summary mode).
INFERRED_EXTRACTOR_PREFIX = "det-extract-summary"
#: Blocking degraded marker (R2d): inferred criteria nobody confirmed are in the analysis.
UNCONFIRMED_INFERRED_MARKER = "unconfirmed_inferred_intent"


def has_unconfirmed_inferred_intent(criteria: Iterable[Any]) -> bool:
    """True when a live criterion was inferred (summary mode or an LLM) and is not confirmed.

    Such criteria are the PR author's own words, read heuristically. While one is present
    the verdict cannot be ``verified`` (the marker is a blocking degraded reason, R2d);
    a human confirming or editing it (lifecycle ``confirmed`` / ``edited``) lifts the block.
    """

    for c in criteria:
        life = _enum_value(getattr(c, "state", "proposed"))
        if life in DROPPED_LIFECYCLE or life in _CONFIRMED_LIFECYCLE:
            continue
        origin = getattr(c, "origin", None)
        version = str(getattr(origin, "extractor_version", "") or "")
        if version.startswith(INFERRED_EXTRACTOR_PREFIX):
            return True
        # DEC-034: a model-proposed criterion is never trusted until a human confirms it.
        if _enum_value(getattr(origin, "extraction_method", "")) == "llm":
            return True
    return False


def criterion_inputs(
    criteria: Iterable[Any],
    *,
    limit: int = 50,
    spec_provenance: str = Provenance.AUTHOR_HEAD_SPEC.value,
) -> Adapted[CriterionInput]:
    """IN-01 ``Criterion`` objects -> :class:`CriterionInput` (duck-typed).

    Rejected/orphaned criteria are omitted. Over ``limit`` the remainder is dropped
    (reason ``criteria_over_limit``) and the caller marks the analysis truncated.
    """

    out: list[CriterionInput] = []
    dropped: dict[str, int] = {}

    def drop(code: str) -> None:
        dropped[code] = dropped.get(code, 0) + 1

    for c in criteria:
        try:
            cid = _str(getattr(c, "id", None), 200)
            text = _str(getattr(c, "text", None))
            lifecycle = _enum_value(getattr(c, "state", "proposed"))
            weight = getattr(c, "weight", 1.0)
            if cid is None or text is None:
                drop("criterion_malformed")
                continue
            if lifecycle in DROPPED_LIFECYCLE:
                continue
            if (
                isinstance(weight, bool)
                or not isinstance(weight, (int, float))
                or not math.isfinite(weight)
                or not 0.0 < weight <= 1.0
            ):
                drop("criterion_weight")
                continue
            hints = getattr(c, "hints", None)
            paths = tuple(
                p for p in (getattr(hints, "paths", ()) or ())[:_MAX_HINTS] if _str(p, 500)
            )
            tests = tuple(
                t for t in (getattr(hints, "tests", ()) or ())[:_MAX_HINTS] if _str(t, 500)
            )
            prov, hint_prov = criterion_provenance(
                c, lifecycle, spec_provenance=spec_provenance
            )
            out.append(
                CriterionInput(
                    criterion_id=cid,
                    text=text,
                    weight=float(weight),
                    testability=_enum_value(getattr(c, "testability", "unrated")),
                    lifecycle=lifecycle,
                    hints_paths=paths,
                    hints_tests=tests,
                    provenance=prov,
                    hints_provenance=hint_prov,
                )
            )
        except Exception:  # noqa: BLE001 - dirty producer data must not escape
            drop("criterion_malformed")
    out.sort(key=lambda x: x.criterion_id)
    if len(out) > limit:
        dropped["criteria_over_limit"] = len(out) - limit
        out = out[:limit]
    return Adapted(tuple(out), dropped)


def agent_signal(messages: Iterable[Any], patterns: Iterable[str] | None = None) -> bool:
    """True when a commit message carries an agent trailer (EV-03-lite)."""

    return detect_agent_trailers(messages, patterns).detected


# ----------------------------------------------------------------- symbols


def symbol_inputs(changeset: Any) -> Adapted[SymbolInput]:
    """LK-01 ``SymbolChangeSet.symbols`` -> :class:`SymbolInput` (sorted by id)."""

    out: dict[str, SymbolInput] = {}
    dropped: dict[str, int] = {}
    for s in getattr(changeset, "symbols", ()) or ():
        try:
            sid = _str(getattr(s, "symbol_id", None), 1000)
            path = _str(getattr(s, "path", None), 1000)
            qname = _str(getattr(s, "qualified_name", None), 1000)
            if sid is None or path is None or qname is None:
                dropped["symbol_malformed"] = dropped.get("symbol_malformed", 0) + 1
                continue
            kind = _enum_value(getattr(s, "kind", "function"))
            out[sid] = SymbolInput(
                symbol_id=sid,
                path=path.replace("\\", "/"),
                qualified_name=qname,
                kind=kind,
                language=str(getattr(s, "language", "") or ""),
                change_kind=_enum_value(getattr(s, "change_kind", "modified_body")),
                is_behavioral=bool(getattr(s, "is_behavioral", False)),
                is_test=is_test_file(path),
                is_pseudo=qname in (MODULE_SYMBOL, FILE_SYMBOL) or kind in ("module", "file"),
            )
        except Exception:  # noqa: BLE001
            dropped["symbol_malformed"] = dropped.get("symbol_malformed", 0) + 1
    return Adapted(tuple(out[k] for k in sorted(out)), dropped)


def changed_test_ids(
    symbols: Iterable[SymbolInput], *, added_only: bool = False
) -> frozenset[str]:
    """Ids (``path::Class::function``) of test functions added or changed in the PR.

    ``added_only`` keeps the functions that are new in the PR (contract 2
    ``added_test_ids``); the default is every added or modified one.
    """

    ids: set[str] = set()
    for s in symbols:
        if not s.is_test or s.is_pseudo or s.change_kind == "removed":
            continue
        if added_only and s.change_kind != "added":
            continue
        parts = s.qualified_name.split(".")
        if not parts[-1].startswith("test"):
            continue
        ids.add(normalize_test_id("::".join([s.path, *parts])))
    return frozenset(ids)


def behavioral_symbols(symbols: Iterable[SymbolInput]) -> tuple[SymbolInput, ...]:
    """``B`` of design 3.9: behavioral, non-test, not the ``<file>`` pseudo-symbol."""

    return tuple(
        s
        for s in symbols
        if s.is_behavioral and not s.is_test and not (s.is_pseudo and s.kind == "file")
    )


def unsupported_languages(symbols: Iterable[SymbolInput]) -> tuple[str, ...]:
    """``unsupported_language:<lang>`` markers for behavioral non-Python changes (D11)."""

    langs = {
        s.language or "unknown"
        for s in behavioral_symbols(symbols)
        if s.language and s.language != "python"
    }
    return tuple(f"unsupported_language:{lang}" for lang in sorted(langs))


def _tamper_covered(path: str) -> bool:
    """True for CI workflows, dependency manifests and build/test configuration.

    Those are analysed by the tamper catalog (config weakening, dependencies), not by LK-01.
    Dockerfiles, shell scripts, SQL, Go, Terraform, other YAML ... are not."""

    try:
        from radius_analysis.tamper.classify import Role, classify_path
    except ImportError:  # pragma: no cover
        return False
    return bool(set(classify_path(path)) & {Role.MANIFEST, Role.CI_WORKFLOW, Role.BUILD_CONFIG})


UNANALYZED_FILES_PREFIX = "unanalyzed_files:"
TAMPER_UNANALYZED_PREFIX = "tamper_unanalyzed:"


def unanalyzed_file_markers(changeset: Any, symbols: Iterable[SymbolInput] = ()) -> tuple[str, ...]:
    """Blocking markers for changed files that are neither provably inert nor analysable (B-02).

    A file is analysable when LK-01 produced symbols for it. Files LK-01 handled at file
    level (unknown language, binary, over budget, parse failure) or ignored (vendor, dist,
    generated ...) are invisible to the symbol-based rules, so each one that is not on the
    inert allowlist (``rules.is_inert_path``) yields ``unanalyzed_files:<n>`` and, for a
    language other than Python, ``unsupported_language:<lang>``. File-level pseudo symbols
    are counted as well when a changeset carries no file list.
    """

    from radius_confidence.verdict_v2.domain.rules import is_inert_path

    covered = _tamper_covered

    paths: set[str] = set()
    langs: set[str] = set()
    for f in getattr(changeset, "files", ()) or ():
        level = _enum_value(getattr(f, "level", ""))
        if level not in ("file", "ignored"):
            continue
        path = str(getattr(f, "path", "") or "")
        old = getattr(f, "old_path", None)
        if is_inert_path(path) and (not old or is_inert_path(str(old))):
            continue
        if covered(path) and (not old or covered(str(old)) or is_inert_path(str(old))):
            continue  # the tamper catalog inspects it (its failure is B-03's marker)
        paths.add(path or str(old))
        lang = str(getattr(f, "language", "") or "unknown")
        if level == "file" and lang != "python":
            langs.add(lang)
    for s in symbols:
        if (
            s.is_pseudo
            and s.kind == "file"
            and s.is_behavioral
            and not is_inert_path(s.path)
            and not covered(s.path)
        ):
            paths.add(s.path)
            if s.language != "python":
                langs.add(s.language or "unknown")
    out = [f"unsupported_language:{lang}" for lang in sorted(langs)]
    if paths:
        out.append(f"{UNANALYZED_FILES_PREFIX}{len(paths)}")
    return tuple(out)


#: Engine notes that mean the tamper analysis did not look at everything.
_TAMPER_INCOMPLETE_NOTES = (
    "context_error",
    "context_time_budget_exceeded",
    "max_files_exceeded",
    "base_snapshot_unavailable",
    "rule_time_budget_exceeded",
)


def tamper_unanalyzed_markers(report: Any) -> tuple[str, ...]:
    """Blocking ``tamper_unanalyzed:*`` markers when tamper analysis could not complete (B-03).

    ``unanalyzable`` files of a test, CI, build, manifest or snapshot role and incomplete
    engine notes (``context_error:*``, a time budget, the file cap, no base snapshot) must
    never read as "no findings".
    """

    try:
        from radius_analysis.tamper.classify import Role, classify_path
    except ImportError:  # pragma: no cover - the analysis package is a worker dependency
        classify_path = None  # type: ignore[assignment]
        Role = None  # type: ignore[assignment]  # noqa: N806
    relevant = (
        {Role.TEST, Role.CONFTEST, Role.CI_WORKFLOW, Role.BUILD_CONFIG, Role.MANIFEST, Role.SNAPSHOT}
        if Role is not None
        else set()
    )
    files: set[str] = set()
    for u in getattr(report, "unanalyzable", ()) or ():
        path = str(getattr(u, "path", "") or "")
        if classify_path is None or (set(classify_path(path)) & relevant):
            files.add(path)
    out: list[str] = []
    if files:
        out.append(f"{TAMPER_UNANALYZED_PREFIX}files={len(files)}")
    notes = {str(n) for n in getattr(report, "notes", ()) or ()}
    for note in sorted(notes):
        head = note.split(":", 1)[0]
        if head in _TAMPER_INCOMPLETE_NOTES:
            out.append(f"{TAMPER_UNANALYZED_PREFIX}{head}")
    return tuple(out)


# ----------------------------------------------------------------- links


def _link_reasons(evidence: Iterable[Any]) -> tuple[Reason, ...]:
    out: list[Reason] = []
    for r in list(evidence or ())[:10]:
        kind = _str(getattr(r, "kind", None), 100)
        detail = _str(getattr(r, "detail", None), 300)
        if kind and detail:
            out.append(Reason(kind, detail, _str(getattr(r, "linker", None), 100)))
    return tuple(out)


def criterion_symbol_edges(
    linkset: Any, *, max_rank: int = 3, known_criteria: Iterable[str] = ()
) -> Adapted[CriterionSymbolEdgeInput]:
    """LK-02 combined links (rank <= ``max_rank``) -> edge DTOs, with per-linker scores."""

    known = set(known_criteria)
    links = tuple(getattr(linkset, "links", ()) or ())
    by_linker: dict[tuple[str, str], dict[str, float]] = {}
    for link in getattr(linkset, "by_linker", ()) or ():
        score = _unit(getattr(link, "score", None))
        if score is not None:
            by_linker.setdefault((link.criterion_id, link.symbol_id), {})[
                str(link.linker)
            ] = round(score, 6)
    out: list[CriterionSymbolEdgeInput] = []
    dropped: dict[str, int] = {}
    for link in links:
        try:
            if getattr(link, "linker", "combined") != "combined":
                continue
            rank = int(getattr(link, "rank", 0))
            if rank < 1 or rank > max_rank:
                continue
            score = _unit(getattr(link, "score", None))
            cid, sid = _str(link.criterion_id, 200), _str(link.symbol_id, 1000)
            if score is None or cid is None or sid is None:
                dropped["criterion_symbol_malformed"] = (
                    dropped.get("criterion_symbol_malformed", 0) + 1
                )
                continue
            if known and cid not in known:
                continue
            out.append(
                CriterionSymbolEdgeInput(
                    criterion_id=cid,
                    symbol_id=sid,
                    score=score,
                    rank=rank,
                    by_linker=by_linker.get((cid, sid), {}),
                    reasons=_link_reasons(getattr(link, "evidence", ())),
                )
            )
        except Exception:  # noqa: BLE001
            dropped["criterion_symbol_malformed"] = (
                dropped.get("criterion_symbol_malformed", 0) + 1
            )
    out.sort(key=lambda e: (e.criterion_id, e.rank, e.symbol_id))
    return Adapted(tuple(out), dropped)


def symbol_test_edges(linkset: Any) -> Adapted[SymbolTestEdgeInput]:
    """LK-03 combined links -> edge DTOs (test ids normalised, parametrisation stripped)."""

    out: dict[tuple[str, str], SymbolTestEdgeInput] = {}
    dropped: dict[str, int] = {}
    for link in getattr(linkset, "links", ()) or ():
        try:
            score = _unit(getattr(link, "score", None))
            sid, tid = _str(link.symbol_id, 1000), _str(link.test_id, 1000)
            if score is None or sid is None or tid is None:
                dropped["symbol_test_malformed"] = dropped.get("symbol_test_malformed", 0) + 1
                continue
            depth = getattr(link, "depth", None)
            edge = SymbolTestEdgeInput(
                symbol_id=sid,
                test_id=normalize_test_id(tid),
                score=score,
                kind=_enum_value(getattr(link, "kind", "unknown")),
                depth=depth if isinstance(depth, int) and not isinstance(depth, bool) else None,
            )
            key = (edge.symbol_id, edge.test_id)
            if key not in out or edge.score > out[key].score:
                out[key] = edge
        except Exception:  # noqa: BLE001
            dropped["symbol_test_malformed"] = dropped.get("symbol_test_malformed", 0) + 1
    return Adapted(tuple(out[k] for k in sorted(out)), dropped)


def hint_test_edges(
    criteria: Iterable[CriterionInput],
    known_test_ids: Iterable[str],
    *,
    weight: float = 1.0,
) -> Adapted[CriterionTestEdgeInput]:
    """``tests`` hints of ``.radius/intent.yml`` -> ADDRESSED_BY edges (design 3.6).

    A hint is ``path::Class::function`` (exact), ``path`` (every known test in the
    file) or ``path::name`` where ``name`` is the last segment. Hints naming no
    known test are dropped (reason ``hint_unresolved``): a hint never invents a test.
    """

    known = sorted({normalize_test_id(t) for t in known_test_ids})
    out: dict[tuple[str, str], CriterionTestEdgeInput] = {}
    dropped: dict[str, int] = {}
    for c in criteria:
        for hint in c.hints_tests:
            h = normalize_test_id(hint)
            hits = [t for t in known if t == h]
            if not hits:
                if "::" in h:
                    hits = [t for t in known if t.startswith(h.split("::", 1)[0] + "::") and t.rsplit("::", 1)[-1] == h.rsplit("::", 1)[-1]]
                else:
                    hits = [t for t in known if t.split("::", 1)[0] == h]
            if not hits:
                dropped["hint_unresolved"] = dropped.get("hint_unresolved", 0) + 1
            for t in hits:
                out[(c.criterion_id, t)] = CriterionTestEdgeInput(
                    criterion_id=c.criterion_id,
                    test_id=t,
                    weight=weight,
                    method="intent_yml_hint",
                    provenance=c.hints_provenance,
                )
    return Adapted(tuple(out[k] for k in sorted(out)), dropped)


def relevance_edges(
    raw_edges: Iterable[Any], *, known_criteria: Iterable[str] = ()
) -> Adapted[CriterionTestEdgeInput]:
    """VS-04 relevance output (objects or dicts with criterion_id/test_id/weight/method)."""

    known = set(known_criteria)
    out: dict[tuple[str, str], CriterionTestEdgeInput] = {}
    dropped: dict[str, int] = {}

    def get(obj: Any, key: str) -> Any:
        return obj.get(key) if isinstance(obj, Mapping) else getattr(obj, key, None)

    for e in raw_edges:
        try:
            weight = _unit(get(e, "weight"))
            cid, tid = _str(get(e, "criterion_id"), 200), _str(get(e, "test_id"), 1000)
            if weight is None or cid is None or tid is None or weight <= 0.0:
                dropped["relevance_malformed"] = dropped.get("relevance_malformed", 0) + 1
                continue
            if known and cid not in known:
                continue
            raw = get(e, "bm25_raw")
            edge = CriterionTestEdgeInput(
                criterion_id=cid,
                test_id=normalize_test_id(tid),
                weight=weight,
                method=_str(get(e, "method"), 100) or "lexical_test_relevance",
                bm25_raw=float(raw) if isinstance(raw, (int, float)) and math.isfinite(raw) else None,
            )
            key = (edge.criterion_id, edge.test_id)
            if key not in out or edge.weight > out[key].weight:
                out[key] = edge
        except Exception:  # noqa: BLE001
            dropped["relevance_malformed"] = dropped.get("relevance_malformed", 0) + 1
    return Adapted(tuple(out[k] for k in sorted(out)), dropped)


def _effective_weight(e: CriterionTestEdgeInput, author_hint_cap: float) -> float:
    """Weight used to rank edges: an untrusted hint is ranked at its capped weight."""

    if e.method == "intent_yml_hint" and e.provenance not in TRUSTED_HINT_PROVENANCE:
        return min(e.weight, author_hint_cap)
    return e.weight


def merge_criterion_test_edges(
    *groups: Iterable[CriterionTestEdgeInput],
    author_hint_cap: float = 0.7,
) -> tuple[CriterionTestEdgeInput, ...]:
    """Union by (criterion, test); the highest weight wins (hints win ties).

    An author-supplied hint competes at its capped weight, so a stronger relevance
    edge is not displaced by a hint that Stage B will cap anyway.
    """

    best: dict[tuple[str, str], CriterionTestEdgeInput] = {}
    for group in groups:
        for e in group:
            key = (e.criterion_id, e.test_id)
            cur = best.get(key)
            if cur is None or (
                _effective_weight(e, author_hint_cap),
                e.method == "intent_yml_hint",
            ) > (
                _effective_weight(cur, author_hint_cap),
                cur.method == "intent_yml_hint",
            ):
                best[key] = e
    return tuple(best[k] for k in sorted(best))


# ----------------------------------------------------------------- assertions


def _exact_bool_identity(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Treat ``x is True`` / ``x is False`` as an exact value check.

    LK-04 labels the comparison ``identity`` (scored like truthiness, 0.25 by the
    frozen converter). With a boolean literal on the right it pins the exact result
    of the code under test, which is what the F-14 gold labels call a strong check
    ("exact boolean"). Only that case is re-labelled; ``is`` against anything else
    keeps its kind. The input is not mutated.
    """

    records = data.get("assertions")
    if not isinstance(records, list):
        return data
    patched: list[Any] = []
    changed = False
    for rec in records:
        expected = rec.get("expected") if isinstance(rec, Mapping) else None
        if (
            isinstance(rec, Mapping)
            and rec.get("kind") == "identity"
            and isinstance(expected, Mapping)
            and expected.get("form") == "literal"
            and expected.get("literal_kind") == "bool"
            and not (rec.get("strength_features") or {}).get("negated")
        ):
            rec = {**rec, "kind": "equality"}
            changed = True
        patched.append(rec)
    return {**data, "assertions": patched} if changed else data


def assertion_features(assertion_set: Any) -> Adapted[AssertionFeatures]:
    """LK-04 ``AssertionSet`` -> ``AssertionFeatures`` via the frozen converter."""

    data = assertion_set.to_dict() if hasattr(assertion_set, "to_dict") else assertion_set
    if not isinstance(data, Mapping):
        return Adapted((), {"assertion_set_malformed": 1})
    conv = features_from_assertion_set(_exact_bool_identity(data))
    dropped: dict[str, int] = {}
    for reason in conv.rejected:
        dropped[reason.code] = dropped.get(reason.code, 0) + 1
    return Adapted(conv.features, dropped)


# ----------------------------------------------------------------- tamper


@dataclass(frozen=True, slots=True)
class TamperAdapted:
    findings: tuple[TamperFindingInput, ...]
    waived: int
    unanalyzable: tuple[str, ...]
    truncated: bool
    rule_errors: tuple[str, ...]
    dropped: Mapping[str, int]


def tamper_inputs(report: Any) -> TamperAdapted:
    """EV-02 ``TamperReport`` -> unwaived finding DTOs plus counts."""

    findings: list[TamperFindingInput] = []
    dropped: dict[str, int] = {}
    for f in getattr(report, "findings", ()) or ():
        try:
            findings.append(finding_input_from_dict(f.to_dict()))
        except (EvidenceInputError, AttributeError, TypeError, ValueError):
            dropped["tamper_finding_malformed"] = dropped.get("tamper_finding_malformed", 0) + 1
    findings.sort(key=lambda f: f.finding_id)
    return TamperAdapted(
        findings=tuple(findings),
        waived=len(getattr(report, "waived", ()) or ()),
        unanalyzable=tuple(
            sorted(str(getattr(u, "path", "")) for u in getattr(report, "unanalyzable", ()) or ())
        ),
        truncated=bool(getattr(report, "truncated", False)),
        rule_errors=tuple(str(e)[:200] for e in getattr(report, "rule_errors", ()) or ()),
        dropped=dropped,
    )


# ----------------------------------------------------------------- outcomes

_OUTCOMES = {
    "passed": Outcome.PASSED,
    "failed": Outcome.FAILED,
    "error": Outcome.ERROR,
    "skipped": Outcome.SKIPPED,
    "flaky": Outcome.FLAKY,
}


def case_inputs(cases: Iterable[Any]) -> Adapted[CaseOutcomeInput]:
    """CI ``ReportedTestCase`` rows -> :class:`CaseOutcomeInput` (unknown outcome: dropped)."""

    out: list[CaseOutcomeInput] = []
    dropped: dict[str, int] = {}
    for c in cases:
        outcome = _OUTCOMES.get(_enum_value(getattr(c, "outcome", "")).lower())
        if outcome is None:
            dropped["case_outcome_unknown"] = dropped.get("case_outcome_unknown", 0) + 1
            continue
        file = getattr(c, "file", None)
        classname = getattr(c, "classname", None)
        name = getattr(c, "name", None)
        out.append(
            CaseOutcomeInput(
                test_id=None,
                raw_file=file if isinstance(file, str) else None,
                raw_classname=classname if isinstance(classname, str) else None,
                raw_name=name if isinstance(name, str) else None,
                outcome=outcome,
            )
        )
    return Adapted(tuple(out), dropped)


def flaky_test_ids(
    identities: Iterable[str], known_test_ids: Iterable[str]
) -> frozenset[str]:
    """Map CI ``file::name`` flaky identities to known test ids (path and last segment)."""

    known = sorted({normalize_test_id(t) for t in known_test_ids})
    out: set[str] = set()
    for ident in identities:
        if not isinstance(ident, str) or "::" not in ident:
            continue
        file, name = ident.replace("\\", "/").rsplit("::", 1)
        name = name.split("[", 1)[0]
        for t in known:
            path, _, tail = t.partition("::")
            if (path == file or path.endswith("/" + file) or file.endswith("/" + path)) and (
                tail.rsplit("::", 1)[-1] == name
            ):
                out.add(t)
    return frozenset(out)


def failed_case_count(cases: Sequence[CaseOutcomeInput]) -> int:
    return sum(1 for c in cases if c.outcome in (Outcome.FAILED, Outcome.ERROR))


# ----------------------------------------------------------------- relevance inputs


def short_symbol_id(symbol_id: str) -> str:
    """``python:src/a.py::f#function@abc123`` -> ``src/a.py::f`` (VS-04 expects this form)."""

    head, sep, _ = symbol_id.partition("#")
    if ":" in head.split("::", 1)[0]:
        head = head.split(":", 1)[1]
    return head if sep or head != symbol_id else symbol_id


def _dotted(node: Any) -> str:
    import ast

    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001
        return ""


def build_test_docs(
    sources: Mapping[str, str],
    test_ids: Iterable[str],
    assertion_set: Mapping[str, Any] | None = None,
) -> list[Any]:
    """VS-04 ``TestDoc`` s for the given test ids, from head sources and LK-04 records.

    Name, docstring, parametrize ids and string literals come from a light ``ast`` pass
    over the test files; assertion facts come from the LK-04 ``AssertionSet`` dict when
    given. Unparseable files and unknown ids are skipped.
    """

    import ast

    from radius_linking.domain import AssertionFact, TestDoc

    wanted = {normalize_test_id(t) for t in test_ids}
    facts_by_test: dict[str, list[Any]] = {}
    records = (assertion_set or {}).get("assertions") if assertion_set else None
    for rec in records if isinstance(records, list) else ():
        tid = rec.get("test_id") if isinstance(rec, Mapping) else None
        if isinstance(tid, str):
            try:
                facts_by_test.setdefault(normalize_test_id(tid), []).append(
                    AssertionFact.from_assertion_dict(rec)
                )
            except Exception:  # noqa: BLE001
                continue
    paths = sorted({t.split("::", 1)[0] for t in wanted})
    docs: list[Any] = []
    for path in paths:
        text = sources.get(path)
        if not isinstance(text, str):
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue

        def visit(body: list[Any], prefix: str, *, _path: str = path) -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    visit(node.body, f"{prefix}::{node.name}")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    tid = f"{prefix}::{node.name}"
                    if tid not in wanted:
                        continue
                    params: list[str] = []
                    for dec in node.decorator_list:
                        if "parametrize" in _dotted(dec):
                            params += [
                                c.value
                                for c in ast.walk(dec)
                                if isinstance(c, ast.Constant) and isinstance(c.value, str)
                            ]
                    lits = [
                        n.value
                        for n in ast.walk(node)
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    ]
                    docs.append(
                        TestDoc(
                            tid,
                            node.name,
                            ast.get_docstring(node) or "",
                            tuple(params),
                            tuple(facts_by_test.get(tid, ())),
                            tuple(lits),
                        )
                    )

        visit(tree.body, path)
    return docs
