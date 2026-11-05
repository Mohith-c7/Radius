"""Evidence item factories (EV-01): stable ids, test-id joiner, case/finding/aggregate.

Pure functions. No clocks (``collected_at`` is a parameter), no I/O. Every factory
builds the item through ``EvidenceItem`` so an unbound or non-40-hex head SHA is
rejected (SHA-binding guarantee).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from typing import Any

from radius_evidence.domain.config import SEVERITY_ORDER
from radius_evidence.domain.enums import (
    AuthoredBy,
    EvidenceKind,
    EvidenceSource,
    IndependenceBasis,
    Outcome,
)
from radius_evidence.domain.freshness import bind_freshness
from radius_evidence.domain.inputs import CaseOutcomeInput, TamperFindingInput
from radius_evidence.domain.model import (
    AssertionFeatures,
    EvidenceItem,
    FlakyInfo,
    IndependenceInfo,
    Reason,
)
from radius_evidence.domain.serialization import sha256_hex

EVIDENCE_ITEM_VERSION = "evidence-item-1"
MAX_FIELD_LEN = 2048

_PARAM_SUFFIX = re.compile(r"\[.*\]$", re.DOTALL)


class EvidenceInputError(ValueError):
    """Malformed or oversized evidence input (rejected, never partially accepted)."""


def make_evidence_id(
    analysis_id: str,
    kind: EvidenceKind | str,
    subject_id: str,
    head_sha: str,
    algo: str = EVIDENCE_ITEM_VERSION,
) -> str:
    """``ev_`` + first 20 hex of sha256(analysis | kind | subject | head | algo)."""

    kind_value = kind.value if isinstance(kind, EvidenceKind) else str(kind)
    raw = "|".join((analysis_id, kind_value, subject_id, head_sha, algo))
    return "ev_" + sha256_hex(raw)[:20]


def normalize_test_id(raw: str) -> str:
    """``path::Class::function`` without a parametrization suffix or phase marker."""

    cleaned = raw.strip().replace("\\", "/")
    if "|" in cleaned and cleaned.rsplit("|", 1)[-1] in {"run", "setup", "teardown"}:
        cleaned = cleaned.rsplit("|", 1)[0]
    return _PARAM_SUFFIX.sub("", cleaned)


def _candidates(
    raw_file: str | None, raw_classname: str | None, raw_name: str | None
) -> list[str]:
    if not raw_name:
        return []
    name = normalize_test_id(raw_name)
    if "::" in name:  # a pytest node id was reported as the name
        return [name]
    out: list[str] = []
    file_ = (raw_file or "").replace("\\", "/").removeprefix("./")
    cls = (raw_classname or "").strip()
    if file_:
        module = file_[:-3].replace("/", ".") if file_.endswith(".py") else file_
        rest = cls.removeprefix(module).lstrip(".") if cls.startswith(module) else ""
        if rest:
            out.append("::".join((file_, *rest.split("."), name)))
        out.append(f"{file_}::{name}")
    elif cls:
        parts = cls.split(".")
        for i in range(len(parts), 0, -1):
            module_path = "/".join(parts[:i]) + ".py"
            out.append("::".join((module_path, *parts[i:], name)))
    return out


def case_to_test_id(
    raw_file: str | None,
    raw_classname: str | None,
    raw_name: str | None,
    known_test_ids: Collection[str],
) -> str | None:
    """Join a CI case (JUnit classname/file/name) to a known test id, else ``None``.

    Exact candidate first; then a unique suffix match (src-layout prefixes).
    """

    candidates = _candidates(raw_file, raw_classname, raw_name)
    known = set(known_test_ids)
    for cand in candidates:
        if cand in known:
            return cand
    for cand in candidates:
        hits = sorted(k for k in known if k.endswith("/" + cand) or k.endswith(cand))
        if len(hits) == 1:
            return hits[0]
    return None


#: Worst-first order used to merge several cases of the same test (parametrized runs).
_MERGE_ORDER: tuple[Outcome, ...] = (
    Outcome.FAILED,
    Outcome.ERROR,
    Outcome.FLAKY,
    Outcome.PASSED,
    Outcome.SKIPPED,
    Outcome.NOT_RUN,
)


def merge_outcomes(outcomes: Iterable[Outcome]) -> Outcome:
    """Merge case outcomes of one test: any failure wins; passed beats skipped."""

    present = set(outcomes)
    for candidate in _MERGE_ORDER:
        if candidate in present:
            return candidate
    return Outcome.NOT_RUN


def _check_len(label: str, value: str | None) -> None:
    if value is not None and len(value) > MAX_FIELD_LEN:
        msg = f"{label} longer than {MAX_FIELD_LEN} characters"
        raise EvidenceInputError(msg)


def _not_applicable_independence(note: str) -> IndependenceInfo:
    return IndependenceInfo(
        AuthoredBy.UNKNOWN,
        IndependenceBasis.PRE_EXISTING_UNCHANGED,
        1.0,
        (Reason("independence_not_applicable", note),),
    )


def from_test(
    *,
    analysis_id: str,
    repository_id: str,
    head_sha: str,
    test_id: str,
    outcome: Outcome,
    collected_at: str,
    independence: IndependenceInfo,
    source: EvidenceSource = EvidenceSource.CI_UPLOAD,
    features: AssertionFeatures | None = None,
    symbol_ids: Iterable[str] = (),
    criterion_ids: Iterable[str] = (),
    flaky: FlakyInfo | None = None,
    duration_ms: int | None = None,
    reasons: Iterable[Reason] = (),
    current_sha: str | None = None,
    path: str | None = None,
    algo_versions: dict[str, str] | None = None,
) -> EvidenceItem:
    """One ``TEST_OUTCOME`` item for a test with a resolved outcome."""

    _check_len("test_id", test_id)
    if duration_ms is not None and duration_ms < 0:
        msg = "duration_ms must be >= 0"
        raise EvidenceInputError(msg)
    effective_flaky = flaky or FlakyInfo(False)
    if outcome is Outcome.FLAKY and not effective_flaky.flagged:
        effective_flaky = FlakyInfo(True, "rerun", None)
    return EvidenceItem(
        evidence_id=make_evidence_id(
            analysis_id, EvidenceKind.TEST_OUTCOME, test_id, head_sha
        ),
        kind=EvidenceKind.TEST_OUTCOME,
        source=source,
        analysis_id=analysis_id,
        repository_id=repository_id,
        head_sha=head_sha,
        subject_id=test_id,
        path=path
        if path is not None
        else (test_id.split("::", 1)[0] if "::" in test_id else None),
        symbol_ids=tuple(sorted(set(symbol_ids))),
        criterion_ids=tuple(sorted(set(criterion_ids))),
        outcome=outcome,
        duration_ms=duration_ms,
        features=features,
        severity=None,
        rule_id=None,
        independence=independence,
        flaky=effective_flaky,
        freshness=bind_freshness(head_sha, current_sha or head_sha),
        reasons=tuple(reasons),
        collected_at=collected_at,
        algo_versions=dict(algo_versions or {}),
    )


def from_case(
    case: CaseOutcomeInput,
    *,
    analysis_id: str,
    repository_id: str,
    head_sha: str,
    collected_at: str,
    independence: IndependenceInfo,
    known_test_ids: Collection[str] = (),
    **kwargs: Any,
) -> EvidenceItem:
    """Item for one reported CI case. A case matching no known test keeps empty links."""

    for label, value in (
        ("file", case.raw_file),
        ("classname", case.raw_classname),
        ("name", case.raw_name),
        ("test_id", case.test_id),
    ):
        _check_len(label, value)
    test_id = case.test_id or case_to_test_id(
        case.raw_file, case.raw_classname, case.raw_name, known_test_ids
    )
    reasons = list(kwargs.pop("reasons", ()))
    if test_id is None:
        label = "::".join(
            p for p in (case.raw_file, case.raw_classname, case.raw_name) if p
        )
        if not label:
            msg = "case has no test id, file, classname or name"
            raise EvidenceInputError(msg)
        test_id = "unmatched::" + normalize_test_id(label)
        reasons.append(Reason("unmatched_case", "case matches no known test id", label))
        kwargs["symbol_ids"] = ()
        kwargs["criterion_ids"] = ()
        kwargs["features"] = None
    return from_test(
        analysis_id=analysis_id,
        repository_id=repository_id,
        head_sha=head_sha,
        test_id=test_id,
        outcome=case.outcome,
        collected_at=collected_at,
        independence=independence,
        reasons=reasons,
        path=case.raw_file,
        **kwargs,
    )


def from_aggregate(
    *,
    analysis_id: str,
    repository_id: str,
    head_sha: str,
    collected_at: str,
    passed: int,
    failed: int,
    errors: int = 0,
    skipped: int = 0,
    source: EvidenceSource = EvidenceSource.WORKER_RUN,
    duration_ms: int | None = None,
) -> EvidenceItem:
    """One aggregate run result (no per-case data): not linkable to any symbol."""

    counts = {"passed": passed, "failed": failed, "errors": errors, "skipped": skipped}
    if any(
        not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in counts.values()
    ):
        msg = "aggregate counts must be non-negative integers"
        raise EvidenceInputError(msg)
    if failed + errors > 0:
        outcome = Outcome.FAILED if failed else Outcome.ERROR
    elif passed > 0:
        outcome = Outcome.PASSED
    elif skipped > 0:
        outcome = Outcome.SKIPPED
    else:
        outcome = Outcome.NOT_RUN
    detail = ", ".join(f"{k}={v}" for k, v in counts.items())
    return from_test(
        analysis_id=analysis_id,
        repository_id=repository_id,
        head_sha=head_sha,
        test_id=f"aggregate::{analysis_id}",
        outcome=outcome,
        collected_at=collected_at,
        independence=_not_applicable_independence("aggregate result"),
        source=source,
        duration_ms=duration_ms,
        path=None,
        reasons=(Reason("aggregate_only", detail),),
    )


def finding_input_from_dict(data: dict[str, Any]) -> TamperFindingInput:
    """Lenient parse of an EV-02 ``TamperFinding.to_dict()``; raises on malformed data."""

    try:
        return TamperFindingInput(
            finding_id=str(data["finding_id"]),
            rule_id=str(data["rule_id"]),
            check=str(data.get("check", "")),
            severity=str(data["severity"]),
            confidence=float(data.get("confidence", 1.0)),
            path=str(data["path"]),
            symbol=data.get("symbol"),
            test_id=data.get("test_id"),
            reason=str(data.get("reason") or ""),
            old_snippet=data.get("old_snippet"),
            new_snippet=data.get("new_snippet"),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        msg = f"malformed tamper finding: {exc}"
        raise EvidenceInputError(msg) from exc


def from_finding(
    finding: TamperFindingInput,
    *,
    analysis_id: str,
    repository_id: str,
    head_sha: str,
    collected_at: str,
    current_sha: str | None = None,
) -> EvidenceItem:
    """``TAMPER_FINDING`` item. Severity must be a known label; ids are required."""

    severity = finding.severity.lower() if isinstance(finding.severity, str) else ""
    if severity not in SEVERITY_ORDER:
        msg = f"unknown tamper severity {finding.severity!r}"
        raise EvidenceInputError(msg)
    if not finding.finding_id or not finding.rule_id or not finding.path:
        msg = "tamper finding needs finding_id, rule_id and path"
        raise EvidenceInputError(msg)
    for label, value in (("finding_id", finding.finding_id), ("path", finding.path)):
        _check_len(label, value)
    reasons = [
        Reason(finding.rule_id, finding.reason[:500] or finding.check, finding.path)
    ]
    if finding.test_id:
        reasons.append(
            Reason("affects_test", "finding attached to a test", finding.test_id)
        )
    return EvidenceItem(
        evidence_id=make_evidence_id(
            analysis_id, EvidenceKind.TAMPER_FINDING, finding.finding_id, head_sha
        ),
        kind=EvidenceKind.TAMPER_FINDING,
        source=EvidenceSource.STATIC_RULES,
        analysis_id=analysis_id,
        repository_id=repository_id,
        head_sha=head_sha,
        subject_id=finding.finding_id,
        path=finding.path,
        symbol_ids=(finding.symbol,) if finding.symbol else (),
        criterion_ids=(),
        outcome=None,
        duration_ms=None,
        features=None,
        severity=severity,
        rule_id=finding.rule_id,
        independence=_not_applicable_independence("static finding"),
        flaky=FlakyInfo(False),
        freshness=bind_freshness(head_sha, current_sha or head_sha),
        reasons=tuple(reasons),
        collected_at=collected_at,
        algo_versions={"tamper": "tamper-rules-v1"},
    )
