"""Stage A: collect the plain-data facts of one analysis from the checkout (VS-05).

Producers (LK-01 symbol changes, EV-02 tamper, LK-02 criterion->symbol, LK-03
symbol->test, LK-04 assertions, optional VS-04 relevance) are re-run from the
checkout (the orchestrator is not edited, design 2.3). Each producer is guarded
with a timeout and isolated:

* ``symbol_changes``, ``tamper`` and the intent load are *critical*: without them
  the verdict could be falsely clean, so their failure raises :class:`StageAError`
  and the caller keeps v1 published.
* every other producer degrades the analysis (``producer_failed:<name>``, or
  ``producer_timeout:<name>`` plus the blocking marker ``truncated``) and the
  evidence it would have supplied is simply absent, which only lowers support.

Nothing here logs criterion text or code; failures carry the exception class only.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from uuid import UUID

from radius_evidence.domain.config import LinkMapping
from radius_evidence.domain.enums import ALL_PROVENANCE, Provenance
from radius_evidence.domain.inputs import CriterionInput, StageAInput
from radius_evidence.domain.versions import (
    CRITERION_SYMBOL_LINKS_VERSION,
    SYMBOL_CHANGES_VERSION,
    SYMBOL_TEST_LINKS_VERSION,
    TAMPER_VERSION,
)
from radius_shared.logging import get_logger

from radius_worker.verdict_v2 import adapters
from radius_worker.verdict_v2.link_scope import scope_link_sources
from radius_worker.verdict_v2.sources import (
    HeadShaPort,
    IntentFacts,
    IntentPort,
    read_hinted_files,
    read_python_sources,
    resolve_head_sha,
)

LOGGER = get_logger(__name__)

TRUNCATED = "truncated"


class StageAError(Exception):
    """A critical Stage A producer failed; v1 stays the published verdict."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class ProducerTimeoutError(Exception):
    """A guarded producer exceeded its time budget."""


#: Default Stage A budgets, sized for a slow host (0.1 CPU); the worker settings
#: ``RADIUS_VERDICT_V2_STAGE_A_TIMEOUT_SECONDS`` / ``..._STEP_TIMEOUT_SECONDS`` set them.
DEFAULT_TIMEOUT_S = 300.0
DEFAULT_STEP_TIMEOUT_S = 120.0


@dataclass(frozen=True, slots=True)
class CollectLimits:
    """Soft budgets (design 3.8); hitting one yields the ``truncated`` marker."""

    max_criteria: int = 50
    max_symbols: int = 5000
    max_tests: int = 3000
    timeout_s: float = DEFAULT_TIMEOUT_S
    step_timeout_s: float = DEFAULT_STEP_TIMEOUT_S
    #: Hard stop for the mutation producer (its own wall clock is smaller; this is the
    #: watchdog that abandons it if the sandbox hangs). Set from the worker settings.
    mutation_timeout_s: float = 660.0


def guarded[T](fn: Callable[[], T], timeout_s: float) -> T:
    """Run ``fn`` with a timeout in a worker thread.

    A timed-out call is abandoned (Python threads cannot be killed); its result is
    discarded. Exceptions propagate unchanged.
    """

    if timeout_s <= 0:
        raise ProducerTimeoutError
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="verdict-v2")
    future = pool.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeout as exc:
        future.cancel()
        raise ProducerTimeoutError from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


# ------------------------------------------------------------------ producers


def _snapshots(command: Any) -> tuple[Any, Any, Any]:
    """``(base, head, diff source)`` as the orchestrator builds them."""

    from radius_analysis.symbol_changes import DirectorySnapshot, GitSnapshot, RefRange

    base = GitSnapshot(command.repository_path, command.base_ref) if command.base_ref else None
    head = (
        GitSnapshot(command.repository_path, command.head_ref)
        if command.head_ref
        else DirectorySnapshot(command.repository_path)
    )
    if command.diff_text:
        source: Any = command.diff_text
    elif command.base_ref and command.head_ref:
        source = RefRange(command.repository_path, command.base_ref, command.head_ref)
    else:
        raise StageAError("no_diff_source")
    return base, head, source


SPEC_PATH = ".radius/intent.yml"


def _source_kind(criterion: Any) -> str:
    kind = getattr(getattr(getattr(criterion, "origin", None), "source", None), "kind", "")
    return str(getattr(kind, "value", kind))


def _norm_spec(data: bytes) -> bytes:
    return data.replace(b"\r", b"").strip()


def default_spec_provenance(command: Any) -> str:
    """``base_spec`` when ``.radius/intent.yml`` exists unchanged on the base ref.

    The PR author controls the head spec, so its hints are trusted only when the
    identical file is already on the base ref (read through the same local git
    snapshot the other producers use). A missing base ref, a missing base file or any
    difference means ``author_head_spec`` (contract 3).
    """

    base, head, _ = _snapshots(command)
    if base is None:
        return Provenance.AUTHOR_HEAD_SPEC.value
    head_bytes, base_bytes = head.read(SPEC_PATH), base.read(SPEC_PATH)
    if head_bytes is not None and base_bytes is not None and (
        _norm_spec(head_bytes) == _norm_spec(base_bytes)
    ):
        return Provenance.BASE_SPEC.value
    return Provenance.AUTHOR_HEAD_SPEC.value


def _norm_text(text: str) -> str:
    return " ".join(str(text).split()).casefold()


def spec_paths_by_text(text: str) -> dict[str, tuple[str, ...]]:
    """``{normalised criterion text: paths}`` of a ``.radius/intent.yml`` text.

    Parsed by the intent package's own spec parser, so the paths are exactly what the
    analysis would read. Criteria with the same text are merged (union of paths: wider
    scope, never narrower).
    """

    from radius_intent.infrastructure.extraction.candidates import Collector
    from radius_intent.infrastructure.extraction.spec_file import extract_spec
    from radius_intent.infrastructure.extraction.text import split_lines

    collector = Collector("spec")
    extract_spec(split_lines(text), "spec", collector)
    out: dict[str, tuple[str, ...]] = {}
    for cand in collector.candidates:
        key = _norm_text(cand.text)
        paths = tuple(getattr(cand.hints, "paths", ()) or ())
        out[key] = tuple(sorted({*out.get(key, ()), *paths}))
    return out


def default_base_spec_paths(command: Any) -> dict[str, tuple[str, ...]]:
    """DEC-043: criterion paths of ``.radius/intent.yml`` at the BASE ref (empty if none)."""

    base, _, _ = _snapshots(command)
    data = base.read(SPEC_PATH) if base is not None else None
    if data is None:
        return {}
    return spec_paths_by_text(data.decode("utf-8", errors="replace"))


def default_symbol_changes(command: Any) -> Any:
    from radius_analysis.symbol_changes import extract_symbol_changes

    base, head, source = _snapshots(command)
    return extract_symbol_changes(base, head, source)


def default_tamper(changeset: Any, command: Any) -> Any:
    from radius_analysis.tamper import analyze_tampering

    base, head, _ = _snapshots(command)
    return analyze_tampering(changeset, base, head, diff_text=command.diff_text or None)


def _resolve_commit(repository_path: Any, ref: str) -> str | None:
    """The commit sha ``ref`` names in the checkout, or ``None``."""

    import subprocess

    if not ref or ref.startswith("-"):
        return None
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, ref validated above
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],  # noqa: S607
            cwd=repository_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip().lower()
    return sha if result.returncode == 0 and sha else None


def _ref_resolves(repository_path: Any, ref: str) -> bool:
    """True when ``ref`` names a commit in the checkout (a missing base must not read as "no policy")."""

    return _resolve_commit(repository_path, ref) is not None


def default_repo_config(command: Any) -> dict[str, Any]:
    """VD-04/VD-05: capture ``.radius/policy.yml`` and ``waivers.yml`` at the BASE ref.

    The head side is passed only so that a base policy that opted in with
    ``head_policy: tighten_only`` can have its head copy read; waivers are never read
    from the head.
    """

    from radius_analysis.symbol_changes import DirectorySnapshot, GitSnapshot
    from radius_evidence.policy.repo_config import collect_repo_config

    repository = getattr(command, "repository_path", None)
    base_ref = getattr(command, "base_ref", None) or None
    if not repository or not base_ref:
        return collect_repo_config(None, None, base_ref=base_ref)
    head_ref = getattr(command, "head_ref", None)
    head = GitSnapshot(repository, head_ref) if head_ref else DirectorySnapshot(repository)
    # The runner passes a branch ref (``origin/<target branch>``). Record the commit it
    # named: the comment renders only a sha, so a branch name showed as "unknown".
    base_sha = _resolve_commit(repository, base_ref)
    return collect_repo_config(
        GitSnapshot(repository, base_sha or base_ref).read,
        head.read,
        base_ref=base_sha or base_ref,
        base_available=base_sha is not None,
    )


def default_link_criteria(
    criteria: Sequence[CriterionInput],
    changeset: Any,
    command: Any,
    sources: dict[str, str],
) -> Any:
    from radius_linking.domain.model import CriterionInput as LinkCriterion
    from radius_linking.infrastructure.pipeline import link_changeset

    base, head, _ = _snapshots(command)
    inputs = [
        LinkCriterion(
            criterion_id=c.criterion_id,
            text=c.text,
            paths=c.hints_paths,
            tests=c.hints_tests,
            weight=c.weight,
            state=c.lifecycle,
        )
        for c in criteria
    ]
    linkset, _docs = link_changeset(inputs, changeset, head, base, python_sources=sources)
    return linkset


def default_link_tests(sources: dict[str, str], targets: Sequence[Any]) -> Any:
    from radius_testing.linking import NamingLinker, StaticLinker, combine_links

    static = StaticLinker().link(sources, targets)
    naming = NamingLinker().link(sources, targets)
    return combine_links(static, naming)


def default_assertions(
    test_files: Sequence[str], sources: dict[str, str], links: Any, targets: Sequence[Any]
) -> Any:
    from radius_testing.assertions import LinkTargetResolver, extract_assertions

    return extract_assertions(
        test_files, sources, links, resolver=LinkTargetResolver(list(targets))
    )


def default_relevance(
    criteria: Sequence[CriterionInput],
    criterion_linkset: Any,
    test_linkset: Any,
    sources: dict[str, str],
    assertion_set: Any,
) -> list[dict[str, Any]]:
    """VS-04 ``r_ct`` for the criteria x tests connected through a changed symbol."""

    from radius_linking.application.relevance import relevance_from_links
    from radius_linking.domain.chain import SymbolTestEdge
    from radius_linking.domain.model import CriterionInput as LinkCriterion

    inputs = [
        LinkCriterion(
            criterion_id=c.criterion_id,
            text=c.text,
            paths=c.hints_paths,
            tests=c.hints_tests,
            weight=c.weight,
            state=c.lifecycle,
        )
        for c in criteria
    ]
    c2s = [
        replace(lk, symbol_id=adapters.short_symbol_id(lk.symbol_id))
        for lk in getattr(criterion_linkset, "links", ())
    ]
    s2t = [
        SymbolTestEdge(
            symbol_id=adapters.short_symbol_id(lk.symbol_id),
            test_id=lk.test_id,
            score=lk.score,
            kind=getattr(lk.kind, "value", str(lk.kind)),
            linker="combined",
        )
        for lk in getattr(test_linkset, "links", ())
    ]
    docs = adapters.build_test_docs(
        sources,
        {e.test_id for e in s2t},
        assertion_set.to_dict() if assertion_set is not None else None,
    )
    rel = relevance_from_links(inputs, docs, c2s, s2t)
    return [
        {
            "criterion_id": i.criterion_id,
            "test_id": i.test_id,
            "weight": i.r_ct,
            "method": "criterion_test_relevance",
        }
        for i in rel.items
        if i.r_ct > 0.0
    ]


@dataclass(slots=True)
class Producers:
    """Injectable producer callables (tests substitute fakes)."""

    symbol_changes: Callable[[Any], Any] = default_symbol_changes
    #: Provenance of the head ``.radius/intent.yml`` (``base_spec`` only if unchanged on base).
    spec_provenance: Callable[[Any], str] = default_spec_provenance
    #: DEC-043: ``(command) -> {criterion text: paths}`` of the BASE spec copy.
    base_spec_paths: Callable[[Any], dict[str, tuple[str, ...]]] = default_base_spec_paths
    tamper: Callable[[Any, Any], Any] = default_tamper
    link_criteria: Callable[..., Any] = default_link_criteria
    link_tests: Callable[..., Any] = default_link_tests
    assertions: Callable[..., Any] = default_assertions
    #: VD-04/VD-05 repository config at the base ref: ``(command) -> dict``.
    repo_config: Callable[[Any], dict[str, Any]] = default_repo_config
    #: VS-04 relevance: ``(criteria, criterion_linkset, symbol_test_linkset, sources,
    #: assertion_set) -> edges``. ``None`` means unavailable (hints only, marker
    #: ``relevance_unavailable``).
    relevance: Callable[..., Any] | None = default_relevance
    #: LK-03 dynamic-coverage links (flag-gated); ``None`` = not produced.
    dynamic_links: Callable[..., Any] | None = None
    #: Contract 5 mutation evidence (flag ``RADIUS_FEATURE_MUTATION``, default off):
    #: ``(MutationRequest) -> MutationInput``. ``None`` = flag off, nothing runs and
    #: ``StageAInput.mutation`` stays ``None``. Sandbox backend only (see ``mutation.py``).
    mutation: Callable[[Any], Any] | None = None
    read_sources: Callable[[Path], tuple[dict[str, str], bool]] = read_python_sources
    #: ``(root, paths) -> {path: text}``: only the test files ``tests:`` hints name.
    hinted_sources: Callable[[Path, Sequence[str]], dict[str, str]] = read_hinted_files


# ------------------------------------------------------------------ collector


@dataclass(slots=True)
class _Run:
    """Per-collect mutable state: degraded markers and the time budget."""

    limits: CollectLimits
    degraded: list[str] = field(default_factory=list)
    algo: dict[str, str] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)
    #: Wall time per step in ms (logged once per collect; no content).
    timings: dict[str, int] = field(default_factory=dict)

    def remaining(self) -> float:
        return self.limits.timeout_s - (time.monotonic() - self.started)

    def mark(self, *markers: str) -> None:
        for m in markers:
            if m not in self.degraded:
                self.degraded.append(m)

    def step[T](
        self,
        name: str,
        fn: Callable[[], T],
        default: T,
        *,
        timeout_s: float | None = None,
        blocking_timeout: bool = True,
    ) -> T:
        """Run a non-critical producer; degrade (never raise) on failure or timeout.

        ``timeout_s`` replaces the default step budget (the mutation producer has its own
        wall clock). A timeout marks ``truncated`` (blocking) unless ``blocking_timeout``
        is false: the mutation producer's evidence is optional, so its timeout only
        records ``producer_timeout:mutation``.
        """

        budget = (
            min(self.limits.step_timeout_s, self.remaining())
            if timeout_s is None
            else timeout_s
        )
        began = time.monotonic()
        try:
            return guarded(fn, budget)
        except ProducerTimeoutError:
            self.mark(f"producer_timeout:{name}")
            if blocking_timeout:
                self.mark(TRUNCATED)
            self.log_timeout(name, budget)
        except Exception as exc:  # noqa: BLE001 - isolation by contract
            self.mark(f"producer_failed:{name}")
            LOGGER.warning(
                "Verdict v2 producer failed",
                extra={"producer": name, "reason_code": type(exc).__name__},
            )
        finally:
            self.timings[name] = int((time.monotonic() - began) * 1000)
        return default

    def log_timeout(self, name: str, budget: float) -> None:
        LOGGER.warning(
            "Verdict v2 producer timed out",
            extra={
                "producer": name,
                "budget_s": round(max(budget, 0.0), 1),
                "elapsed_ms": int((time.monotonic() - self.started) * 1000),
            },
        )

    def critical[T](self, name: str, fn: Callable[[], T]) -> T:
        budget = min(self.limits.step_timeout_s, self.remaining())
        began = time.monotonic()
        try:
            return guarded(fn, budget)
        except StageAError:
            raise
        except ProducerTimeoutError as exc:
            self.log_timeout(name, budget)
            raise StageAError(f"{name}_timeout") from exc
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "Verdict v2 critical producer failed",
                extra={"producer": name, "reason_code": type(exc).__name__},
            )
            raise StageAError(f"{name}_failed") from exc
        finally:
            self.timings[name] = int((time.monotonic() - began) * 1000)


class VerdictStageACollector:
    """``StageACollector`` implementation (see ``ports.py``)."""

    def __init__(
        self,
        intent: IntentPort,
        *,
        head_sha_port: HeadShaPort | None = None,
        producers: Producers | None = None,
        limits: CollectLimits | None = None,
    ) -> None:
        self._intent = intent
        self._head_port = head_sha_port or (intent if hasattr(intent, "head_sha") else None)
        self._producers = producers or Producers()
        self._limits = limits or CollectLimits()

    # -- helpers ----------------------------------------------------------

    def _head_sha(self, analysis_id: UUID, command: Any) -> str:
        sha = None
        if self._head_port is not None:
            sha = self._head_port.head_sha(analysis_id, command)
        sha = sha or resolve_head_sha(command)
        if not sha:
            raise StageAError("head_sha_unresolved")
        return sha

    def _spec_provenance(self, facts: IntentFacts, command: Any) -> str:
        """Provenance of spec-file criteria; any failure means author-controlled."""

        author = Provenance.AUTHOR_HEAD_SPEC.value
        uses_spec = any(_source_kind(c) == "spec_file" for c in facts.criteria)
        if not uses_spec:
            return author
        try:
            value = guarded(
                lambda: self._producers.spec_provenance(command), self._limits.step_timeout_s
            )
        except Exception:  # noqa: BLE001 - unknown means author-controlled
            return author
        return value if value in ALL_PROVENANCE else author

    def _with_scope_paths(
        self, facts: IntentFacts, criteria: Any, spec_provenance: str, command: Any
    ) -> Any:
        """DEC-043: attach the BASE-copy ``paths:`` that decide whether the PR affects a
        ``.radius/intent.yml`` criterion.

        Unchanged spec (``base_spec``): the paths as read. Changed or added spec: the
        paths of the base criterion with the same text, so editing ``paths:`` in the PR
        cannot move a criterion out of scope; a criterion with no base copy, or a base
        that cannot be read, keeps no scope paths and always stays in scope.
        """

        spec_ids = {
            str(getattr(c, "id", "")) for c in facts.criteria if _source_kind(c) == "spec_file"
        }
        if not spec_ids:
            return criteria
        base: dict[str, tuple[str, ...]] | None = None
        if spec_provenance != Provenance.BASE_SPEC.value:
            try:
                base = guarded(
                    lambda: self._producers.base_spec_paths(command),
                    self._limits.step_timeout_s,
                )
            except Exception as exc:  # noqa: BLE001 - unknown base: nothing is scoped out
                LOGGER.warning(
                    "Verdict v2 base spec read failed", extra={"reason_code": type(exc).__name__}
                )
                base = {}
        items = []
        for c in criteria.items:
            paths: tuple[str, ...] = ()
            if c.criterion_id in spec_ids:
                paths = c.hints_paths if base is None else base.get(_norm_text(c.text), ())
            items.append(replace(c, scope_paths=paths) if paths else c)
        return adapters.Adapted(tuple(items), criteria.dropped)

    # -- API --------------------------------------------------------------

    def resolve_head(self, analysis_id: UUID, command: Any) -> str | None:
        """The head sha, or ``None`` when it cannot be resolved (never raises)."""

        try:
            return self._head_sha(analysis_id, command)
        except Exception:  # noqa: BLE001 - used on the error path only
            return None

    def collect(self, analysis_id: UUID, command: Any) -> StageAInput:
        """Build the :class:`StageAInput`; raises :class:`StageAError` on critical failure."""

        run = _Run(self._limits)
        prod = self._producers
        head_sha = self._head_sha(analysis_id, command)

        try:
            facts: IntentFacts = guarded(
                lambda: self._intent.load(analysis_id), self._limits.step_timeout_s
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "Verdict v2 intent load failed",
                extra={"analysis_id": str(analysis_id), "reason_code": type(exc).__name__},
            )
            raise StageAError("intent_load_failed") from exc

        spec_provenance = self._spec_provenance(facts, command)
        criteria = adapters.criterion_inputs(
            facts.criteria,
            limit=self._limits.max_criteria,
            spec_provenance=spec_provenance,
        )
        if criteria.dropped.get("criteria_over_limit"):
            run.mark(TRUNCATED)
        run.mark(*criteria.notes)
        criteria = self._with_scope_paths(facts, criteria, spec_provenance, command)
        if adapters.has_unconfirmed_inferred_intent(facts.criteria):
            run.mark(adapters.UNCONFIRMED_INFERRED_MARKER)

        changeset = run.critical("symbol_changes", lambda: prod.symbol_changes(command))
        run.algo["symbol_changes"] = getattr(changeset, "algo_version", SYMBOL_CHANGES_VERSION)
        if getattr(changeset, "truncated", False):
            run.mark(TRUNCATED)
        symbols = adapters.symbol_inputs(changeset)
        run.mark(*symbols.notes)
        sym_items = symbols.items
        if len(sym_items) > self._limits.max_symbols:
            sym_items = sym_items[: self._limits.max_symbols]
            run.mark(TRUNCATED)
        run.mark(*adapters.unsupported_languages(sym_items))
        run.mark(*adapters.unanalyzed_file_markers(changeset, sym_items))  # B-02

        report = run.critical("tamper", lambda: prod.tamper(changeset, command))
        tamper = adapters.tamper_inputs(report)
        if tamper.truncated:
            run.mark(TRUNCATED)
        if tamper.rule_errors:
            raise StageAError("tamper_incomplete")
        run.mark(*adapters.tamper_unanalyzed_markers(report))  # B-03
        run.mark(*(f"adapter_dropped:{k}" for k in sorted(tamper.dropped)))
        run.algo["tamper"] = getattr(report, "catalog_version", TAMPER_VERSION)

        try:
            repo_config = guarded(lambda: prod.repo_config(command), self._limits.step_timeout_s)
        except Exception as exc:  # noqa: BLE001 - never crash; fail towards "not verified"
            LOGGER.warning(
                "Verdict v2 repository config read failed",
                extra={"analysis_id": str(analysis_id), "reason_code": type(exc).__name__},
            )
            repo_config = {
                "base_ref": str(getattr(command, "base_ref", "") or ""),
                "policy": {"status": "unreadable"},
                "waivers": {"status": "unreadable"},
            }

        root = Path(command.repository_path)
        # ``tests:`` hints link directly to the tests they name once those tests are found
        # in the hinted files. This reads and parses only those files, first and with its
        # own budget, so it never depends on whole-repo linking finishing in time.
        hint_files = sorted(
            {h.replace("\\", "/").split("::", 1)[0] for c in criteria.items for h in c.hints_tests}
        )
        hinted_texts: dict[str, str] = {}
        hinted_ids: set[str] = set()
        if hint_files:
            hinted_texts, hinted_ids = run.step(
                "hinted_tests",
                lambda: _hinted_tests(prod.hinted_sources(root, hint_files)),
                ({}, set()),
                timeout_s=self._limits.step_timeout_s,
            )

        sources, src_truncated = run.step(
            "read_sources", lambda: prod.read_sources(root), ({}, False)
        )
        if src_truncated:
            run.mark(TRUNCATED)
        for path, text in hinted_texts.items():
            sources.setdefault(path, text)

        link_targets = self._link_targets(changeset, sym_items)
        crit_sym = adapters.Adapted((), {})
        crit_linkset = None
        if criteria.items and sym_items:
            linkset = run.step(
                "criterion_symbol_links",
                lambda: prod.link_criteria(criteria.items, changeset, command, sources),
                None,
            )
            crit_linkset = linkset
            if linkset is not None:
                crit_sym = adapters.criterion_symbol_edges(
                    linkset,
                    known_criteria=[c.criterion_id for c in criteria.items],
                )
                run.algo["criterion_symbol_links"] = getattr(
                    linkset, "algo_version", CRITERION_SYMBOL_LINKS_VERSION
                )
        run.mark(*crit_sym.notes)

        sym_test = adapters.Adapted((), {})
        test_links = None
        if link_targets:
            # Whole-repo linking parses every file it is given: give it only the test
            # files that can reach a changed file (plus the hinted ones).
            test_links = run.step(
                "symbol_test_links",
                lambda: prod.link_tests(
                    _scoped_sources(sources, link_targets, hinted_texts), link_targets
                ),
                None,
            )
            if prod.dynamic_links is not None and test_links is not None:
                test_links = run.step(
                    "dynamic_links",
                    lambda: prod.dynamic_links(sources, link_targets, test_links),
                    test_links,
                )
            if test_links is not None:
                sym_test = adapters.symbol_test_edges(test_links)
                run.algo["symbol_test_links"] = (
                    getattr(test_links, "algo_version", "") or SYMBOL_TEST_LINKS_VERSION
                )
        run.mark(*sym_test.notes)
        edges_st = sym_test.items
        tests_in_links = sorted({e.test_id for e in edges_st})
        if len(tests_in_links) > self._limits.max_tests:
            keep = set(tests_in_links[: self._limits.max_tests])
            edges_st = tuple(e for e in edges_st if e.test_id in keep)
            run.mark(TRUNCATED)

        mutation_input = None
        if prod.mutation is not None and edges_st and crit_sym.items:
            from radius_worker.verdict_v2.mutation import (
                request_from_stage_a,
                unmeasured_input,
            )

            request = request_from_stage_a(
                Path(command.repository_path), changeset, sym_items, crit_sym.items, edges_st
            )
            mutation_started = time.monotonic()
            mutation_input = run.step(
                "mutation",
                lambda: prod.mutation(request),
                None,
                timeout_s=self._limits.mutation_timeout_s,
                blocking_timeout=False,
            )
            # The mutation stage has its own wall clock (``mutation_timeout_s``). Its time
            # must not eat the shared Stage A budget, or every later producer (assertions,
            # relevance) times out, the blocking ``truncated`` marker is set and the whole
            # verdict degrades whenever mutants actually ran (found on fixture 08).
            run.started += time.monotonic() - mutation_started
            if mutation_input is None:
                mutation_input = unmeasured_input("producer_failed")
            elif getattr(mutation_input, "status", "") != "measured":
                run.mark(f"mutation_unmeasured:{mutation_input.reason or 'unknown'}")
        elif prod.mutation is not None:
            from radius_worker.verdict_v2.mutation import unmeasured_input

            mutation_input = unmeasured_input("no_linked_tests")
            run.mark("mutation_unmeasured:no_linked_tests")

        changed_tests = adapters.changed_test_ids(sym_items)
        test_files = sorted(
            {
                t.split("::", 1)[0]
                for t in {*(e.test_id for e in edges_st), *changed_tests, *hinted_ids}
            }
        )
        features = adapters.Adapted((), {})
        aset = None
        if test_files:
            aset = run.step(
                "assertions",
                lambda: prod.assertions(test_files, sources, test_links, link_targets),
                None,
            )
            if aset is not None:
                features = adapters.assertion_features(aset)
                run.algo["assertion_extract"] = getattr(aset, "algo_version", "")
        run.mark(*features.notes)

        known_tests = {a.test_id for a in features.items} | {e.test_id for e in edges_st}
        known_tests |= set(changed_tests)
        hints = adapters.hint_test_edges(criteria.items, known_tests | hinted_ids)
        run.mark(*hints.notes)
        relevance_edges: tuple[Any, ...] = ()
        if prod.relevance is not None and criteria.items and known_tests:
            raw = run.step(
                "relevance",
                lambda: prod.relevance(
                    criteria.items, crit_linkset, test_links, sources, aset
                ),
                None,
            )
            if raw is not None:
                rel = adapters.relevance_edges(
                    raw, known_criteria=[c.criterion_id for c in criteria.items]
                )
                relevance_edges = rel.items
                run.mark(*rel.notes)
        elif prod.relevance is None:
            run.mark("relevance_unavailable")
        crit_test = adapters.merge_criterion_test_edges(
            hints.items, relevance_edges, author_hint_cap=LinkMapping().author_hint_cap
        )
        LOGGER.info(
            "Verdict v2 stage A collected",
            extra={
                "analysis_id": str(analysis_id),
                "elapsed_ms": int((time.monotonic() - run.started) * 1000),
                "step_ms": dict(run.timings),
                "degraded": list(run.degraded),
                "spec_provenance": spec_provenance,
                "hint_edges": len(hints.items),
                "criterion_test_edges": len(crit_test),
            },
        )

        return StageAInput(
            analysis_id=str(analysis_id),
            repository_id=str(getattr(command, "repository_id", "")),
            head_sha=head_sha,
            changeset_ref=_changeset_ref(changeset),
            criteria=criteria.items,
            symbols=sym_items,
            criterion_symbol=crit_sym.items,
            symbol_test=edges_st,
            criterion_test=crit_test,
            assertions=features.items,
            tamper=tamper.findings,
            tamper_waived=tamper.waived,
            tamper_unanalyzable=tamper.unanalyzable,
            changed_test_ids=changed_tests,
            added_test_ids=adapters.changed_test_ids(sym_items, added_only=True),
            agent_signal=adapters.agent_signal(facts.commit_messages),
            degraded=tuple(run.degraded),
            algo_versions=dict(sorted(run.algo.items())),
            repo_config=repo_config,
            mutation=mutation_input,
            changed_paths=_changed_paths(changeset, sym_items),
        )

    @staticmethod
    def _link_targets(changeset: Any, symbols: Sequence[Any]) -> list[Any]:
        """LK-03 targets: behavioral, non-test, non-pseudo-file changed symbols."""

        from radius_testing.linking import LinkTarget

        keep = {s.symbol_id for s in symbols if not s.is_test and s.kind != "file"}
        out = []
        for s in getattr(changeset, "symbols", ()) or ():
            if s.symbol_id in keep and s.is_behavioral:
                try:
                    out.append(LinkTarget.from_changed_symbol(s))
                except (AttributeError, TypeError, ValueError):
                    continue
        return out


def _hinted_tests(texts: dict[str, str]) -> tuple[dict[str, str], set[str]]:
    """``(texts, test ids)`` of the hinted files: the tests that really exist there."""

    from radius_testing.linking.naming import python_test_records

    return texts, {r.test_id for r in python_test_records(texts)}


def _scoped_sources(
    sources: dict[str, str], targets: Sequence[Any], keep: dict[str, str]
) -> dict[str, str]:
    """:func:`scope_link_sources`, falling back to every source if scoping fails."""

    try:
        scoped = scope_link_sources(sources, targets, keep)
    except Exception as exc:  # noqa: BLE001 - scoping is an optimisation only
        LOGGER.warning(
            "Verdict v2 link scoping failed", extra={"reason_code": type(exc).__name__}
        )
        return sources
    LOGGER.info(
        "Verdict v2 link scope",
        extra={"files_total": len(sources), "files_linked": len(scoped)},
    )
    return scoped


def _changed_paths(changeset: Any, symbols: Sequence[Any]) -> tuple[str, ...] | None:
    """Every changed file (new and old paths); ``None`` when the list may be incomplete."""

    files = getattr(changeset, "files", None)
    if files is None or getattr(changeset, "truncated", False):
        return None
    paths: set[str] = {s.path for s in symbols}
    for f in files:
        for p in (getattr(f, "path", None), getattr(f, "old_path", None)):
            if isinstance(p, str) and p:
                paths.add(p.replace("\\", "/"))
    return tuple(sorted(paths))


def _changeset_ref(changeset: Any) -> str:
    try:
        from radius_linking.infrastructure.pipeline import changeset_ref

        return changeset_ref(changeset)
    except Exception:  # noqa: BLE001
        return str(getattr(changeset, "algo_version", SYMBOL_CHANGES_VERSION))
