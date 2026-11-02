"""Summary-mode criteria under the author-trust rules (DEC-032)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace as NS

from radius_confidence.verdict_v2.domain.rules import is_blocking_degraded
from radius_intent.domain import CriterionState, IntentSource, IntentSourceKind
from radius_intent.infrastructure.extraction import (
    DeterministicCriterionExtractor,
    ExtractionConfig,
)
from radius_worker.config import WorkerSettings
from radius_worker.verdict_v2 import adapters

NOW = datetime(2026, 11, 3, tzinfo=UTC)
BODY = "## Summary\n- Rejects uploads larger than 5 MB with a 413\n- Users no longer see the banner\n"


def _criteria():
    source = IntentSource.from_text("pr-body", IntentSourceKind.PR_BODY, BODY, NOW)
    return DeterministicCriterionExtractor(ExtractionConfig(mode="summary")).extract(
        source
    )


def test_summary_criteria_are_author_pr_body_proposed_and_hintless() -> None:
    crits = _criteria()
    assert len(crits) == 2
    out = adapters.criterion_inputs(crits, spec_provenance="base_spec")
    for item in out.items:
        # a base-branch spec never upgrades PR-body text
        assert (item.provenance, item.hints_provenance) == (
            "author_pr_body",
            "author_pr_body",
        )
        assert item.lifecycle == "proposed"
        assert item.hints_tests == () and item.hints_paths == ()
    assert adapters.hint_test_edges(out.items, ["tests/test_a.py::test_x"]).items == ()


def test_unconfirmed_summary_criteria_block_verified_via_a_degraded_marker() -> None:
    crits = _criteria()
    assert adapters.has_unconfirmed_inferred_intent(crits)
    assert is_blocking_degraded(adapters.UNCONFIRMED_INFERRED_MARKER)


def test_human_confirmation_lifts_the_block_and_rejected_criteria_do_not_count() -> (
    None
):
    first, second = _criteria()
    confirmed = first.confirm()
    assert not adapters.has_unconfirmed_inferred_intent([confirmed])
    assert adapters.criterion_provenance(confirmed, "confirmed") == (
        "human_confirmed",
        "human_confirmed",
    )
    assert not adapters.has_unconfirmed_inferred_intent([second.reject()])
    assert adapters.has_unconfirmed_inferred_intent([confirmed, second])
    assert second.state is CriterionState.PROPOSED


def test_other_criteria_never_set_the_marker() -> None:
    plain = NS(
        state=NS(value="proposed"), origin=NS(extractor_version="det-extract-v1")
    )
    assert not adapters.has_unconfirmed_inferred_intent([plain])
    assert not adapters.has_unconfirmed_inferred_intent([])


def test_worker_setting_defaults_to_sections_and_reads_the_env(monkeypatch) -> None:
    monkeypatch.delenv("RADIUS_INTENT_EXTRACTION_MODE", raising=False)
    assert WorkerSettings(_env_file=None).intent_extraction_mode == "sections"
    monkeypatch.setenv("RADIUS_INTENT_EXTRACTION_MODE", "summary")
    assert WorkerSettings(_env_file=None).intent_extraction_mode == "summary"
