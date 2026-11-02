"""IN-02: the collector against the recorded-style scenario and a stateful fake."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from radius_github.fake_api import (
    RECORDED_HEAD_SHA,
    RECORDED_OWNER,
    RECORDED_REPO,
    RECORDED_TOKEN,
    FakeGitHub,
    install_recorded_scenario,
    load_fixture,
)
from radius_github.intent_links import IssueRef
from radius_github.intent_rest import CallBudget, EtagCache, GitHubRestReader
from radius_github.intent_sources import (
    COMMITS_ID,
    MAX_API_CALLS,
    PR_BODY_ID,
    PR_TITLE_ID,
    SPEC_ID,
    CollectorConfig,
    GitHubIntentCollector,
    IntentSourceUnavailableError,
    PullRequestHint,
    RepoContext,
    SourceStatus,
    comments_source_id,
    is_owned_source_id,
    issue_outcome_from_payload,
    issue_source_id,
    maintainer_comments_text,
)
from radius_intent.domain import IntentSourceKind

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
CTX = RepoContext(RECORDED_OWNER, RECORDED_REPO, 1, RECORDED_HEAD_SHA, "55001122")
BASE = f"/repos/{RECORDED_OWNER}/{RECORDED_REPO}"


def make_collector(fake, *, comments: bool = False, cache: EtagCache | None = None, token=lambda: RECORDED_TOKEN):
    return GitHubIntentCollector(
        GitHubRestReader(transport=fake, cache=cache),
        token,
        config=CollectorConfig(include_issue_comments=comments),
        clock=lambda: NOW,
    )


def scenario() -> FakeGitHub:
    return install_recorded_scenario(FakeGitHub())


def test_all_sources_are_fetched_with_provenance() -> None:
    fake = scenario()
    collection = make_collector(fake).collect(CTX)

    assert collection.complete
    assert collection.stopped_reason is None
    assert collection.presence() == {
        "pr-title": "present",
        "pr-body": "present",
        "commits": "present",
        "intent.yml": "present",
        "issue:12": "present",
        "issue:13": "present",
    }
    by_id = {o.source_id: o for o in collection.outcomes}
    assert by_id["pr-title"].kind is IntentSourceKind.PR_TITLE
    assert by_id["pr-title"].source.text == "Add greeting helper"
    assert by_id["pr-body"].kind is IntentSourceKind.PR_BODY
    assert "Fixes #12" in by_id["pr-body"].source.text
    assert "reviewer note" not in by_id["pr-body"].source.text  # HTML comment stripped
    assert by_id["pr-body"].source.suspicious_content_removed
    assert by_id["pr-body"].reference == f"{RECORDED_OWNER}/{RECORDED_REPO}#1"
    assert by_id["intent.yml"].kind is IntentSourceKind.SPEC_FILE
    assert by_id["intent.yml"].source.text.startswith("version: 1")
    assert by_id["intent.yml"].reference == f".radius/intent.yml@{RECORDED_HEAD_SHA[:12]}"
    assert by_id["issue:12"].kind is IntentSourceKind.ISSUE
    assert by_id["issue:12"].source.text.startswith("Greeting helper should validate input\n\n")
    assert by_id["issue:12"].reference == f"{RECORDED_OWNER}/{RECORDED_REPO}#12"
    for outcome in collection.outcomes:
        assert outcome.origin == "rest_api"
        assert outcome.source.fetched_at == NOW
        assert len(outcome.source.raw_text_hash) == 64
    # The spec file was read at the analysis commit, not at the branch tip.
    spec_call = next(c for c in fake.calls if c.path.endswith("/contents/.radius/intent.yml"))
    assert spec_call.query == {"ref": RECORDED_HEAD_SHA}


def test_commit_messages_are_one_cleaned_source_without_merge_commits() -> None:
    collection = make_collector(scenario()).collect(CTX)
    commits = collection.outcome(COMMITS_ID).source
    assert commits.kind is IntentSourceKind.COMMIT_MESSAGE
    assert "Commit a1a1a1a:\nfeat: add greet() helper" in commits.text
    assert "must reject empty names" in commits.text
    assert "Co-authored-by" not in commits.text and "Signed-off-by" not in commits.text
    assert "Generated with" not in commits.text
    assert "Merge branch" not in commits.text
    assert "merge_commits_skipped:1" in collection.diagnostics


def test_issues_come_from_body_and_commit_messages() -> None:
    fake = scenario()
    collection = make_collector(fake).collect(CTX)
    assert fake.count(r"/issues/12$") == 1  # from the PR body
    assert fake.count(r"/issues/13$") == 1  # "Fixes #13" only in a commit message
    assert collection.outcome("issue:13").status is SourceStatus.PRESENT


def test_call_order_and_count() -> None:
    fake = scenario()
    collection = make_collector(fake).collect(CTX)
    assert fake.paths() == [
        f"{BASE}/pulls/1",
        f"{BASE}/pulls/1/commits",
        f"{BASE}/contents/.radius/intent.yml",
        f"{BASE}/issues/12",
        f"{BASE}/issues/13",
    ]
    assert collection.api_calls == 5 <= MAX_API_CALLS


def test_missing_spec_file_is_absent_not_an_error() -> None:
    fake = scenario()
    fake.remove(f"{BASE}/contents/.radius/intent.yml", params={"ref": RECORDED_HEAD_SHA})
    collection = make_collector(fake).collect(CTX)
    spec = collection.outcome(SPEC_ID)
    assert (spec.status, spec.reason, spec.source) == (SourceStatus.ABSENT, "not_found", None)
    assert collection.complete


def test_spec_file_at_another_sha_is_not_used() -> None:
    fake = scenario()
    other = RepoContext(RECORDED_OWNER, RECORDED_REPO, 1, "9" * 40, "55001122")
    assert make_collector(fake).collect(other).outcome(SPEC_ID).reason == "not_found"


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        ([{"type": "file"}], "not_a_file"),
        ({"type": "dir"}, "not_a_file"),
        ({"type": "symlink"}, "not_a_file"),
        ({"type": "file", "size": 5 * 1024 * 1024, "encoding": "none", "content": ""}, "too_large"),
        ({"type": "file", "size": 10, "encoding": "none", "content": ""}, "unreadable"),
        ({"type": "file", "size": 10, "encoding": "base64", "content": ""}, "unreadable"),
        ("junk", "not_a_file"),
    ],
)
def test_unusable_spec_responses_are_absent(data, reason) -> None:
    fake = scenario()
    fake.put(f"{BASE}/contents/.radius/intent.yml", data, params={"ref": RECORDED_HEAD_SHA})
    spec = make_collector(fake).collect(CTX).outcome(SPEC_ID)
    assert (spec.status, spec.reason) == (SourceStatus.ABSENT, reason)


def test_spec_file_with_invalid_utf8_and_nul_is_sanitized() -> None:
    fake = scenario()
    raw = b"version: 1\x00\nnote: caf\xe9\n"
    fake.put(
        f"{BASE}/contents/.radius/intent.yml",
        {"type": "file", "size": len(raw), "encoding": "base64", "content": base64.b64encode(raw).decode()},
        params={"ref": RECORDED_HEAD_SHA},
    )
    spec = make_collector(fake).collect(CTX).outcome(SPEC_ID).source
    assert "\x00" not in spec.text and spec.suspicious_content_removed
    assert "caf\ufffd" in spec.text


def test_issues_permission_denied_is_absent_with_reason_and_other_sources_survive() -> None:
    fake = scenario()
    fake.deny_prefix(f"{BASE}/issues")
    collection = make_collector(fake).collect(CTX)
    for sid in ("issue:12", "issue:13"):
        outcome = collection.outcome(sid)
        assert (outcome.status, outcome.reason) == (SourceStatus.ABSENT, "forbidden")
    assert collection.outcome(PR_BODY_ID).status is SourceStatus.PRESENT
    assert collection.complete


@pytest.mark.parametrize(
    ("status", "reason"), [(404, "not_found"), (410, "gone")]
)
def test_missing_or_deleted_issue_is_absent(status, reason) -> None:
    fake = scenario()
    fake.fail(f"{BASE}/issues/12", status, "gone")
    outcome = make_collector(fake).collect(CTX).outcome("issue:12")
    assert (outcome.status, outcome.reason) == (SourceStatus.ABSENT, reason)


def test_pull_request_number_is_not_an_issue() -> None:
    fake = scenario()
    fake.put_issue(RECORDED_OWNER, RECORDED_REPO, 12, title="x", body="y", is_pull_request=True)
    outcome = make_collector(fake).collect(CTX).outcome("issue:12")
    assert (outcome.status, outcome.reason) == (SourceStatus.ABSENT, "is_pull_request")


def test_rate_limit_midway_marks_rest_unavailable_and_stops_calling() -> None:
    fake = scenario()
    fake.rate_limit_after(3)  # PR, commits, spec succeed; the first issue is limited
    collection = make_collector(fake).collect(CTX)
    assert collection.stopped_reason == "rate_limited"
    assert collection.outcome(SPEC_ID).status is SourceStatus.PRESENT
    for sid in ("issue:12", "issue:13"):
        outcome = collection.outcome(sid)
        assert (outcome.status, outcome.reason) == (SourceStatus.UNAVAILABLE, "rate_limited")
    assert len(fake.calls) == 4  # the 5th call was never made
    assert collection.complete  # link discovery itself succeeded


def test_rate_limited_from_the_start_degrades_everything() -> None:
    fake = scenario()
    fake.rate_limit_after(0)
    collection = make_collector(fake).collect(CTX)
    assert not collection.complete
    assert {o.status for o in collection.outcomes} == {SourceStatus.UNAVAILABLE}
    assert len(fake.calls) == 1


def test_pull_request_not_found_is_absent_and_not_complete_free_of_errors() -> None:
    fake = scenario()
    fake.remove(f"{BASE}/pulls/1")
    collection = make_collector(fake).collect(CTX)
    assert collection.outcome(PR_TITLE_ID).reason == "not_found"
    assert collection.outcome(PR_BODY_ID).status is SourceStatus.ABSENT


def test_token_provider_failure_is_unavailable_not_an_exception() -> None:
    def boom() -> str:
        raise RuntimeError("cannot mint")

    collection = make_collector(scenario(), token=boom).collect(CTX)
    assert not collection.complete
    assert {o.reason for o in collection.outcomes} == {"token_error"}


def test_api_call_budget_is_respected_and_drops_the_least_important_sources() -> None:
    fake = scenario()
    # PR, commits, spec use 3; only one issue fits.
    collection = make_collector(fake).collect(CTX, budget=CallBudget(max_calls=4))
    assert len(fake.calls) == 4
    assert collection.api_calls == 4
    assert collection.outcome("issue:12").status is SourceStatus.PRESENT
    skipped = collection.outcome("issue:13")
    assert (skipped.status, skipped.reason) == (SourceStatus.UNAVAILABLE, "budget_exhausted")


def test_many_links_are_capped_at_ten_issues_and_fifteen_calls() -> None:
    fake = scenario()
    body = "\n".join(f"Fixes #{n}" for n in range(100, 130))
    fake.put_pull(RECORDED_OWNER, RECORDED_REPO, 1, title="t", body=body, head_sha=RECORDED_HEAD_SHA)
    for n in range(100, 130):
        fake.put_issue(RECORDED_OWNER, RECORDED_REPO, n, title=f"i{n}", body="b")
    collection = make_collector(fake).collect(CTX)
    issue_ids = [o.source_id for o in collection.outcomes if o.source_id.startswith("issue:")]
    assert len(issue_ids) == 10
    assert any(d.startswith("linked_issues_truncated:") for d in collection.diagnostics)
    assert len(fake.calls) <= 15


def test_payload_hint_spares_the_pull_request_call() -> None:
    fake = scenario()
    hint = PullRequestHint(title="From payload", body="Fixes #12", has_body=True)
    collection = make_collector(fake).collect(CTX, hint=hint)
    assert f"{BASE}/pulls/1" not in fake.paths()
    title = collection.outcome(PR_TITLE_ID)
    assert title.origin == "webhook_payload" and title.source.text == "From payload"
    assert collection.outcome("issue:12").status is SourceStatus.PRESENT


def test_incomplete_hint_falls_back_to_the_rest_api() -> None:
    fake = scenario()
    hint = PullRequestHint(title="Only a title", body=None, has_body=False)
    assert not hint.complete
    collection = make_collector(fake).collect(CTX, hint=hint)
    assert f"{BASE}/pulls/1" in fake.paths()
    assert collection.outcome(PR_TITLE_ID).origin == "rest_api"
    assert collection.outcome(PR_TITLE_ID).source.text == "Add greeting helper"


def test_known_pr_outcomes_spare_the_call_only_when_both_are_present() -> None:
    fake = scenario()
    first = make_collector(fake).collect(CTX)
    known = (first.outcome(PR_TITLE_ID), first.outcome(PR_BODY_ID))
    fake2 = scenario()
    second = make_collector(fake2).collect(CTX, known_pr=known)
    assert f"{BASE}/pulls/1" not in fake2.paths()
    assert second.outcome(PR_BODY_ID).source == known[1].source
    # An absent body forces the REST fallback.
    from dataclasses import replace

    absent = replace(known[1], status=SourceStatus.ABSENT, source=None, reason="empty")
    fake3 = scenario()
    make_collector(fake3).collect(CTX, known_pr=(known[0], absent))
    assert f"{BASE}/pulls/1" in fake3.paths()


def test_empty_pr_body_is_absent_with_reason_empty() -> None:
    fake = scenario()
    fake.put_pull(RECORDED_OWNER, RECORDED_REPO, 1, title="t", body=None, head_sha=RECORDED_HEAD_SHA)
    body = make_collector(fake).collect(CTX).outcome(PR_BODY_ID)
    assert (body.status, body.reason) == (SourceStatus.ABSENT, "empty")


def test_head_moved_is_reported() -> None:
    fake = scenario()
    fake.put_pull(RECORDED_OWNER, RECORDED_REPO, 1, title="t", body="b", head_sha="f" * 40)
    assert "head_moved" in make_collector(fake).collect(CTX).diagnostics


def test_commits_unavailable_keeps_collection_incomplete() -> None:
    fake = scenario()
    fake.fail(f"{BASE}/pulls/1/commits", 500, "oops")
    collection = make_collector(fake).collect(CTX)
    assert collection.outcome(COMMITS_ID).status is SourceStatus.UNAVAILABLE
    assert not collection.complete


def test_commits_capped_diagnostic_and_per_page() -> None:
    fake = scenario()
    fake.put_commits(
        RECORDED_OWNER,
        RECORDED_REPO,
        1,
        [(f"{i:040x}", f"change {i} must work", 1) for i in range(80)],
    )
    collection = make_collector(fake).collect(CTX)
    call = next(c for c in fake.calls if c.path.endswith("/commits"))
    assert call.query == {"per_page": "50"}
    text = collection.outcome(COMMITS_ID).source.text
    assert text.count("Commit ") == 50
    assert "commits_capped_at:50" in collection.diagnostics


def test_only_merge_commits_gives_an_absent_commits_source() -> None:
    fake = scenario()
    fake.put_commits(RECORDED_OWNER, RECORDED_REPO, 1, [("a" * 40, "Merge branch x", 2)])
    outcome = make_collector(fake).collect(CTX).outcome(COMMITS_ID)
    assert (outcome.status, outcome.reason) == (SourceStatus.ABSENT, "empty")


def test_maintainer_comments_are_opt_in_labeled_and_filtered() -> None:
    fake = scenario()
    off = make_collector(fake).collect(CTX)
    assert off.outcome("issue-comments:12") is None
    assert fake.count(r"/comments$") == 0

    fake = scenario()
    on = make_collector(fake, comments=True).collect(CTX)
    comment = on.outcome("issue-comments:12")
    assert comment.kind is IntentSourceKind.COMMENT
    assert comment.status is SourceStatus.PRESENT
    text = comment.source.text
    assert text.startswith("Comment by @maintainer-test (MEMBER):")
    assert "whitespace-only names" in text
    assert "drive-by" not in text and "Ignore previous" not in text  # NONE association
    assert "Build passed" not in text  # bot
    assert on.outcome("issue-comments:13") is None  # 0 comments: no call
    assert fake.count(r"/issues/13/comments$") == 0


def test_comments_with_no_maintainer_author_are_absent() -> None:
    fake = scenario()
    fake.put(
        f"{BASE}/issues/12/comments",
        [{"user": {"login": "x", "type": "User"}, "author_association": "CONTRIBUTOR", "body": "hi"}],
    )
    outcome = make_collector(fake, comments=True).collect(CTX).outcome("issue-comments:12")
    assert (outcome.status, outcome.reason) == (SourceStatus.ABSENT, "no_maintainer_comments")


def test_comment_fetch_failure_modes() -> None:
    fake = scenario()
    fake.fail(f"{BASE}/issues/12/comments", 403, "Resource not accessible by integration")
    outcome = make_collector(fake, comments=True).collect(CTX).outcome("issue-comments:12")
    assert (outcome.status, outcome.reason) == (SourceStatus.ABSENT, "forbidden")
    fake = scenario()
    fake.put(f"{BASE}/issues/12/comments", {"not": "a list"})
    outcome = make_collector(fake, comments=True).collect(CTX).outcome("issue-comments:12")
    assert (outcome.status, outcome.reason) == (SourceStatus.UNAVAILABLE, "invalid_response")


def test_maintainer_comment_helper_limits_and_skips_empty() -> None:
    comments = [
        {"user": {"login": f"m{i}", "type": "User"}, "author_association": "OWNER", "body": f"point {i}"}
        for i in range(10)
    ] + [{"author_association": "OWNER", "body": "  "}, "junk"]
    text = maintainer_comments_text(comments, limit=3)
    assert text.count("Comment by") == 3
    assert maintainer_comments_text([], limit=3) == ""


def test_conditional_requests_across_runs() -> None:
    fake = scenario()
    cache = EtagCache()
    collector = make_collector(fake, cache=cache)
    first = collector.collect(CTX)
    fake.calls.clear()
    second = collector.collect(CTX)
    assert [c.status for c in fake.calls] == [304] * 5
    assert all(o.from_cache for o in second.outcomes)
    assert {o.source_id: o.source.raw_text_hash for o in first.outcomes} == {
        o.source_id: o.source.raw_text_hash for o in second.outcomes
    }


def test_pull_request_edit_changes_the_hash_but_unrelated_sources_keep_theirs() -> None:
    fake = scenario()
    cache = EtagCache()
    collector = make_collector(fake, cache=cache)
    before = collector.collect(CTX)
    pull = load_fixture("pull_1.json")
    pull["body"] += "\n- [ ] new requirement must hold"
    fake.put(f"{BASE}/pulls/1", pull)
    after = collector.collect(CTX)
    assert after.outcome(PR_BODY_ID).source.raw_text_hash != before.outcome(PR_BODY_ID).source.raw_text_hash
    assert after.outcome(PR_TITLE_ID).source.raw_text_hash == before.outcome(PR_TITLE_ID).source.raw_text_hash
    assert after.outcome("issue:12").source.raw_text_hash == before.outcome("issue:12").source.raw_text_hash


# -- ids and the port --------------------------------------------------------------


def test_source_id_conventions() -> None:
    same = IssueRef("Acme", "Widgets", 5)
    assert issue_source_id(same, "acme", "widgets") == "issue:5"
    other = IssueRef("other", "lib", 7)
    assert issue_source_id(other, "acme", "widgets") == "issue:other:lib:7"
    long = IssueRef("o" * 50, "r" * 50, 7)
    long_id = issue_source_id(long, "acme", "widgets")
    assert len(long_id) <= 64 and long_id.startswith("issue:x") and long_id.endswith(":7")
    assert comments_source_id("issue:5") == "issue-comments:5"
    assert len(comments_source_id(long_id)) <= 64
    assert len(comments_source_id("issue:" + "a" * 58)) <= 64


def test_ownership_rules() -> None:
    K = IntentSourceKind
    assert is_owned_source_id("pr-title", K.PR_TITLE)
    assert is_owned_source_id("pr-body", K.PR_BODY)
    assert is_owned_source_id("commits", K.COMMIT_MESSAGE)
    assert is_owned_source_id("issue:3", K.ISSUE)
    assert is_owned_source_id("issue-comments:3", K.COMMENT)
    assert not is_owned_source_id("issue", K.ISSUE)  # the IN-08 default id is the engineer's
    assert not is_owned_source_id("intent.yml", K.SPEC_FILE)
    assert not is_owned_source_id("agent-prompt", K.AGENT_PROMPT)
    assert not is_owned_source_id("manual:abc", K.COMMENT)
    assert not is_owned_source_id("pr-body", K.ISSUE)


def test_issue_outcome_from_payload() -> None:
    payload = load_fixture("issue_12.json")
    ref = IssueRef(RECORDED_OWNER, RECORDED_REPO, 12)
    outcome = issue_outcome_from_payload(
        ref, payload, default_owner=RECORDED_OWNER, default_repo=RECORDED_REPO, now=NOW
    )
    assert outcome.source_id == "issue:12" and outcome.origin == "webhook_payload"
    pull = issue_outcome_from_payload(
        ref, {"pull_request": {}}, default_owner=RECORDED_OWNER, default_repo=RECORDED_REPO, now=NOW
    )
    assert pull.reason == "is_pull_request"


def test_fetcher_port_semantics() -> None:
    fake = scenario()
    collector = make_collector(fake)
    fetcher = collector.fetcher(CTX)
    aid = "00000000-0000-4000-8000-000000000001"
    title = fetcher.fetch(aid, IntentSourceKind.PR_TITLE, "")
    assert title.source_id == "pr-title"
    assert fetcher.fetch(aid, IntentSourceKind.ISSUE, "#12").source_id == "issue:12"
    assert fetcher.fetch(aid, IntentSourceKind.SPEC_FILE, "").source_id == "intent.yml"
    assert fetcher.fetch(aid, IntentSourceKind.COMMIT_MESSAGE, "").source_id == "commits"
    assert fetcher.fetch(aid, IntentSourceKind.AGENT_PROMPT, "") is None
    assert fetcher.fetch(aid, IntentSourceKind.ISSUE, "garbage") is None
    fake.deny_prefix(f"{BASE}/issues")
    assert collector.fetcher(CTX).fetch(aid, IntentSourceKind.ISSUE, "#12") is None  # absent
    fake.allow_prefix(f"{BASE}/issues")
    fake.rate_limit_after(0)
    with pytest.raises(IntentSourceUnavailableError):
        collector.fetcher(CTX).fetch(aid, IntentSourceKind.ISSUE, "#12")


def _cross_repo_scenario() -> FakeGitHub:
    fake = scenario()
    body = "Fixes #12\nCloses other/lib#7\nResolves https://github.com/Other/Lib/issues/8\nFixes RADIUS-SANDBOX-OWNER/radius-sandbox#13"
    fake.put_pull(RECORDED_OWNER, RECORDED_REPO, 1, title="t", body=body, head_sha=RECORDED_HEAD_SHA)
    fake.put_issue("other", "lib", 7, title="Secret roadmap", body="private text")
    fake.put_issue("other", "lib", 8, title="Another", body="more private text")
    return fake


def test_cross_repo_links_are_skipped_by_default_without_any_request() -> None:
    fake = _cross_repo_scenario()
    collection = make_collector(fake).collect(CTX)
    for sid in ("issue:other:lib:7", "issue:Other:Lib:8"):
        outcome = collection.outcome(sid)
        assert (outcome.status, outcome.reason, outcome.source) == (
            SourceStatus.ABSENT,
            "cross_repo_disabled",
            None,
        )
    assert not any("/repos/other/" in p or "/repos/Other/" in p for p in fake.paths())
    # Same-repo links (any case, either spelling) are still fetched.
    assert collection.outcome("issue:12").status is SourceStatus.PRESENT
    assert collection.outcome("issue:13").status is SourceStatus.PRESENT


def test_cross_repo_links_are_fetched_when_allowed() -> None:
    fake = _cross_repo_scenario()
    collector = GitHubIntentCollector(
        GitHubRestReader(transport=fake),
        lambda: RECORDED_TOKEN,
        config=CollectorConfig(allow_cross_repo=True),
        clock=lambda: NOW,
    )
    collection = collector.collect(CTX)
    seven = collection.outcome("issue:other:lib:7")
    assert seven.status is SourceStatus.PRESENT and "private text" in seven.source.text
    assert "/repos/other/lib/issues/7" in fake.paths()


def test_cross_repo_skip_removes_a_previously_stored_cross_repo_source() -> None:
    from uuid import uuid4

    from radius_github.intent_ingestion import IntentIngestionService
    from radius_intent.application import IntentSnapshotService
    from radius_intent.domain import IntentSource
    from radius_intent.infrastructure import (
        InMemoryIntentRepository,
        default_extractors,
    )

    repo = InMemoryIntentRepository()
    snapshots = IntentSnapshotService(repo, default_extractors())
    org, aid = uuid4(), str(uuid4())
    stale = IntentSource.from_text("issue:other:lib:7", IntentSourceKind.ISSUE, "leaked text must exist", NOW)
    snapshots.on_sources_changed(aid, org, [stale], NOW, trigger="t")
    service = IntentIngestionService(repo, snapshots, clock=lambda: NOW)
    service.apply(org, aid, make_collector(_cross_repo_scenario()).collect(CTX), trigger="t")
    assert "issue:other:lib:7" not in {s.source_id for s in service.current_sources(org, aid)}
