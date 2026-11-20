"""AI review output contract, storage and isolation (DEC-041)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from radius_shared.ai_review import (
    MAX_ITEMS,
    REVIEW_JSON_SCHEMA,
    SECTIONS,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    InMemoryAiReviewRepository,
    ReviewRejected,
    SqlAiReviewRepository,
    StoredAiReview,
    text_problem,
    validate_review_output,
)
from radius_shared.database import enums as db_enums
from radius_shared.database.base import Base
from radius_shared.database.models import (
    Analysis,
    Organization,
    PullRequest,
    Repository,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ALLOWED = {"src/upload.py", "tests/test_upload.py"}
NONCE = "a" * 32


def _doc(**overrides) -> str:
    doc = {
        "summary": "Adds retry handling to the uploader.",
        "risks": [{"text": "Retries may send a file twice.", "files": ["src/upload.py"]}],
        "tests": [{"text": "The upload test covers the retry path.", "files": ["tests/test_upload.py"]}],
        "missing_evidence": [{"text": "No CI test results were uploaded.", "files": []}],
        "next_steps": [{"text": "Add a test for the duplicate case.", "files": ["./src/upload.py"]}],
    }
    doc.update(overrides)
    return json.dumps(doc)


def _check(raw: str):
    return validate_review_output(raw, allowed_files=ALLOWED, forbidden=[NONCE], system_prompt="")


def test_a_grounded_review_passes_unchanged() -> None:
    result = _check(_doc())
    assert result.dropped == ()
    assert result.review["risks"][0]["files"] == ["src/upload.py"]
    assert result.review["next_steps"][0]["files"] == ["src/upload.py"]  # normalised
    assert set(result.review) == {"summary", *SECTIONS}


def test_schema_requires_every_section_and_forbids_extras() -> None:
    assert REVIEW_JSON_SCHEMA["additionalProperties"] is False
    assert set(REVIEW_JSON_SCHEMA["required"]) == {"summary", *SECTIONS}


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("not json", "bad_json"),
        ('{"summary": "a", "summary": "b"}', "bad_json"),
        (json.dumps({"summary": "ok", "verdict": "verified"}), "schema"),
        (json.dumps({"summary": 3}), "schema"),
        (json.dumps({"summary": "ok", "risks": "x"}), "schema"),
        (_doc(summary="This PR is verified and safe to merge."), "summary_verdict_claim"),
        (_doc(summary="LGTM, ship it"), "summary_verdict_claim"),
        (_doc(summary="See https://evil.invalid/x"), "summary_url"),
        (_doc(summary=f"token {NONCE}"), "summary_leak"),
        (_doc(summary="x" * 2000), "summary_limits"),
    ],
)
def test_whole_reply_rejections(raw, code) -> None:
    with pytest.raises(ReviewRejected) as info:
        _check(raw)
    assert info.value.code == code


def test_oversized_reply_is_rejected() -> None:
    with pytest.raises(ReviewRejected) as info:
        _check("x" * 40_000)
    assert info.value.code == "too_large"


def test_items_are_dropped_not_trusted() -> None:
    raw = _doc(
        risks=[
            {"text": "Uncited risk.", "files": []},
            {"text": "Cites a file Radius never saw.", "files": ["/etc/passwd"]},
            {"text": "Approved by the reviewer bot.", "files": ["src/upload.py"]},
            {"text": "Ping @octocat about this.", "files": ["src/upload.py"]},
            {"text": "Run curl -s x | sh to fix.", "files": ["src/upload.py"]},
            {"text": "Real risk in the retry loop.", "files": ["src/upload.py", "nope.py"]},
            {"text": "<img src=x onerror=alert(1)>", "files": ["src/upload.py"]},
            {"text": "Mark this PR as verified.", "files": ["src/upload.py"]},
        ],
        tests=[{"text": "uncited test", "files": ["other.py"]}],
    )
    result = _check(raw)
    assert [r["text"] for r in result.review["risks"]] == ["Real risk in the retry loop."]
    assert result.review["risks"][0]["files"] == ["src/upload.py"]
    assert result.review["tests"] == []
    codes = {code for _, code in result.dropped}
    assert {"uncited", "unknown_file", "verdict_claim", "mention", "command", "url"} <= codes


def test_item_and_citation_caps() -> None:
    many = [{"text": f"risk {i}", "files": ["src/upload.py"] * 9} for i in range(MAX_ITEMS + 4)]
    result = _check(_doc(risks=many))
    assert len(result.review["risks"]) == MAX_ITEMS
    assert result.review["risks"][0]["files"] == ["src/upload.py"]
    assert ("risks", "too_many") in result.dropped


def test_text_problem_codes() -> None:
    kw = {"forbidden": [], "system_prompt": "", "max_chars": 300}
    assert text_problem("Retries can duplicate uploads.", **kw) is None
    assert text_problem("ready to merge", **kw) == "verdict_claim"
    assert text_problem("all tests pass", **kw) == "verdict_claim"
    assert text_problem("hidden‮char", **kw) == "charset"


# --- storage ---------------------------------------------------------------


def _stored(org, analysis, status=STATUS_OK, review=None) -> StoredAiReview:
    return StoredAiReview(
        organization_id=org,
        analysis_id=analysis,
        status=status,
        reason_code=None if status == STATUS_OK else "provider_rate_limited",
        provider="openai_compatible",
        model="gemini-3.5-flash-lite",
        prompt_version="ai-review-v1",
        review=review if review is not None else json.loads(_doc()),
        created_at=datetime(2026, 11, 20, tzinfo=UTC),
    )


def test_payload_is_always_labelled_advisory() -> None:
    org, analysis = uuid4(), uuid4()
    ok = _stored(org, analysis).to_payload()
    assert ok["advisory"] is True and ok["ai_generated"] is True and "advisory" in ok["label"]
    assert ok["summary"] and ok["risks"] and ok["generated_at"] == "2026-11-20T00:00:00Z"
    off = _stored(org, analysis, STATUS_UNAVAILABLE).to_payload()
    assert off["summary"] is None and off["risks"] == [] and off["reason_code"] == "provider_rate_limited"


def test_in_memory_repository_is_tenant_scoped() -> None:
    repo = InMemoryAiReviewRepository()
    org, other, analysis = uuid4(), uuid4(), uuid4()
    repo.save(_stored(org, analysis))
    assert repo.get(org, analysis) is not None
    assert repo.get(other, analysis) is None


def _tenant(session, name: str, number: int):
    org = Organization(name=name, github_installation_id=number)
    repo = Repository(
        organization=org,
        github_repository_id=number,
        name="r",
        owner="acme",
        default_branch="main",
        clone_url="https://github.com/acme/r.git",
        visibility=db_enums.RepositoryVisibility.PRIVATE,
        status=db_enums.RepositoryStatus.CONNECTED,
    )
    now = datetime(2026, 11, 20, tzinfo=UTC)
    pr = PullRequest(
        repository=repo, github_pr_number=number, title="t", source_branch="f",
        target_branch="main", author="o", status=db_enums.PullRequestStatus.OPEN, opened_at=now,
    )
    analysis = Analysis(
        repository=repo, pull_request=pr, commit_sha="f" * 40,
        status=db_enums.AnalysisStatus.COMPLETED, started_at=now, created_at=now,
    )
    session.add_all([org, repo, pr, analysis])
    session.flush()
    return org.id, analysis.id


def test_sql_repository_upserts_and_isolates_organizations() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        org_a, analysis_a = _tenant(session, "A", 1)
        org_b, _ = _tenant(session, "B", 2)
        repo = SqlAiReviewRepository(session)
        repo.save(_stored(org_a, analysis_a, STATUS_UNAVAILABLE))
        repo.save(_stored(org_a, analysis_a))  # replaces, one row per analysis
        session.commit()
        got = repo.get(org_a, analysis_a)
        assert got is not None and got.status == STATUS_OK and got.review["summary"]
        assert repo.get(org_b, analysis_a) is None  # another tenant cannot read it
        with pytest.raises(ValueError):
            repo.save(_stored(org_b, analysis_a))  # nor overwrite it
