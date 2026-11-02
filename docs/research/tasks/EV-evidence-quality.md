# Phase EV: Evidence Quality (Milestones M2 and M4) -- Weak-test pillar, RQ2

Goal: measure not just *whether* evidence passed, but whether it *could have caught a failure*. See `../DESIGN.md` section 6.3. Template and rules: `../IMPLEMENTATION_PLAN.md`.

M2 = cheap signals (EV-01 to EV-03, EV-06 to EV-08). M4 = mutation-based signals (EV-04, EV-05, EV-09 to EV-11).

---

### EV-01 Evidence item model and normalizers   [ ]
- Owner type: agent-ok
- Depends on: LK-05
- Branch: `feature/evidence-model`
- Size: L
- Goal: one normalized representation for every kind of evidence.
- Steps: `EvidenceItem` (kind, source, head_sha, payload_ref, collected_at, authored_by, flaky flag); normalizers for JUnit XML, JSON test reports (exists in `packages/testing`), coverage (coverage.py XML/JSON, lcov), SARIF (static analysis), mutation results (EV-04), manual attestation; migration `0012` (`evidence_item`).
- Acceptance: each normalizer has fixtures incl. malformed/oversized input rejected safely; items always bound to repo + head SHA; unbound items rejected (keeps existing SHA-binding guarantee).
- Tests: parser fuzzing; tenant isolation.
- Contract: see design/VERDICT_V2_SLICE.md (docs/research/design/; Verdict v2 alpha: alpha scope is the model, factories and JSON; table is Beta (migration 0015))

### EV-02 Tamper rule engine and catalog (Python first)   [x]
- Owner type: agent-ok
- Depends on: LK-01
- Branch: `feature/tamper-rules`
- Size: XL (split by rule family)
- Goal: deterministic diff-level detection of evidence weakening, in `packages/tamper`.
- Rule IDs and behavior (each has fixture pass/fail pairs and an explanation template):
  - `T001` test deleted without removing the code under test.
  - `T002` test newly skipped/xfail/`pytest.mark.skip`/`@unittest.skip`/`if False`.
  - `T003` assertion removed or count of assertions in a test reduced.
  - `T004` assertion weakened (equality -> truthiness; exact -> `in`; value check -> `is not None`; tolerance widened).
  - `T005` tautological assertion (`assert True`, `assert x == x`, `assert 1`).
  - `T006` expected value changed in the same PR as the code under test, without justification (snapshot/golden updates included).
  - `T007` broad exception swallow in code or test (`except: pass`) newly added.
  - `T008` the code under test is mocked inside its own test (test mocks the SUT).
  - `T009` coverage suppression added (`# pragma: no cover`, `.coveragerc` omit, `--cov-fail-under` lowered).
  - `T010` CI/config weakening (`continue-on-error`, `if: false`, removed test step, timeouts increased, retries added, `|| true`).
  - `T011` retry/sleep/timeouts added to tests to force a pass.
  - `T012` hallucinated or unpinned new dependency (name not found on the registry, typosquat distance, or lockfile mismatch).
  - `T013` type/lint suppressions added (`# type: ignore`, `# noqa`, `eslint-disable`) beyond a threshold.
  - `T014` stubbed implementation (`pass`, `raise NotImplementedError`, `return None` placeholders) in non-abstract code.
  - `T015` security downgrade (TLS verification off, hard-coded credentials, interpolated SQL) -- may reuse Semgrep-style rules.
  - `T016` debug artifacts left behind (print/breakpoint) -- low severity.
- Steps: rule interface (`id`, `severity`, `languages`, `evaluate(diff, ast_before, ast_after) -> findings`); registry; severity penalties per `DESIGN.md` 6.3; `radius rules` CLI listing; configuration (enable/disable, severity override via policy).
- Out of scope: LLM-based tamper detection.
- Acceptance: >= 95% recall on seeded fixtures per rule, zero findings on the clean fixtures; each finding includes before/after snippet and explanation; performance under 1 s for a 1k-line diff.
- Tests: pass/fail pair per rule; mutation of whitespace must not change findings; large-diff test.
- Research hook: rule hit rates on agent vs human PRs (RQ2/RQ4).
- Note: Verik (Apache-2.0) and SlopGate implement overlapping rules; reuse of ideas is fine, but check licenses before copying any code, and prefer independent implementation. AgentProof's license was not visible; do not copy.
- Contract: see design/VERDICT_V2_SLICE.md (docs/research/design/; Verdict v2 alpha: consumed through TamperFindingInput; severities drive rules R1c/R3a)

### EV-03 Authorship and independence analysis   [ ]
- Owner type: agent-ok
- Depends on: EV-02
- Branch: `feature/evidence-independence`
- Size: M
- Goal: compute `i(e)`: was this test written/modified by the same agent in the same PR?
- Steps: classify authorship of each test file/function in the PR (commit author, co-author trailers, bot accounts, trajectory data when available (PR-02)); mark pre-existing (unchanged) tests as independent; mark tests changed in the PR as dependent; produce `authored_by` and `independence_factor` using the defaults in `DESIGN.md` 6.3 (configurable).
- Acceptance: fixtures verify classification; unknown authorship uses `iota_unknown`; documented limits.
- Research hook: report how often evidence is non-independent in agent PRs.
- Contract: see design/VERDICT_V2_SLICE.md (docs/research/design/; Verdict v2 alpha: alpha ships the lite independence factor only (section 3.5))

### EV-04 Mutation service (Python)   [ ]
- Owner type: pair
- Depends on: F-07, LK-03, EV-01
- Branch: `feature/mutation-service`
- Size: XL (split: engine adapter; scoping; scheduler; result import)
- Goal: run mutation testing only on changed symbols (and their directly linked tests) in the sandbox.
- Steps:
  1. Engine adapters behind a port: start with `mutmut` and/or `cosmic-ray` for Python; record engine+version.
  2. Scope: mutate only lines of changed symbols (from LK-01); run only linked tests (LK-03) first; escalate to the wider selected set if the linked set is empty.
  3. Operators: arithmetic, comparison, boolean, return value, constant, conditional boundary, exception removal, call removal; document which are enabled.
  4. Budget: max mutants per PR, max wall time, per-mutant timeout; deterministic sampling with recorded seed when over budget.
  5. Persist `mutation_run` and `mutant` (killed/survived/timeout/error/equivalent_suspect, `killed_by_test_id`). Migration `0013`.
  6. Async: publishes partial results first; the verdict shows "mutation pending" until done (policy: block or not).
- Out of scope: JS/TS (EV-14).
- Acceptance: on fixtures with known weak tests, survivors are found where expected; budget limits enforced; sandbox constraints verified (no network, limits); resumable after worker crash.
- Tests: engine adapter contract tests; timeout tests; seed determinism test.
- Research hook: store per-run timings and mutant counts (overhead analysis); seeds.
- Risks: slow on big repos -> caching (EV-09).

### EV-05 Detection power `d_mut`   [ ]
- Owner type: agent-ok
- Depends on: EV-04
- Branch: `feature/evidence-detection-power`
- Size: M
- Goal: compute `d_mut(e, c)` = killed mutants (attributed to evidence `e`) / non-equivalent mutants in symbols linked to criterion `c`.
- Steps: attribution of kills to tests; handle shared kills (credit split or multi-credit, configurable); handle zero-mutant symbols (e.g. comments-only) -> `d` undefined -> use static fallback.
- Acceptance: unit tests on small hand-calculated cases; edge cases documented.

### EV-06 Static assertion strength `a_static`   [ ]
- Owner type: agent-ok
- Depends on: LK-04
- Branch: `feature/evidence-assertion-strength`
- Size: M
- Goal: cheap proxy for detection power when mutation data is unavailable.
- Steps: score in [0,1] from `strength_features`: value-equality on computed result (high), exception type + message (medium), type/None/length only (low), no assertion or tautology (0), mock-call-only (low), snapshot-only (low unless snapshot reviewed). Calibrate weights against `d_mut` later (EP-08).
- Acceptance: rank correlation with `d_mut` on the fixtures reported; capped contribution (`cap_static`).
- Research hook: correlation between `a_static` and `d_mut` is a paper result (cheap proxy validity).
- Contract: see design/VERDICT_V2_SLICE.md (docs/research/design/; Verdict v2 alpha: a_static table in 3.6)

### EV-07 Freshness binding and staleness   [ ]
- Owner type: agent-ok
- Depends on: EV-01
- Branch: `feature/evidence-freshness`
- Size: S
- Goal: `f(e)` = 1 if bound to current head SHA, else 0; keep history for audit; optional decay for evidence from earlier commits that touch unchanged symbols (policy-gated, default off).
- Acceptance: a new commit invalidates old evidence for changed symbols but not for unchanged ones when decay is enabled.
- Contract: see design/VERDICT_V2_SLICE.md (docs/research/design/; Verdict v2 alpha: f in {0,1} by head SHA, 3.5)

### EV-08 `q(e)` combiner and configuration   [ ]
- Owner type: agent-ok
- Depends on: EV-02, EV-03, EV-05, EV-06, EV-07
- Branch: `feature/evidence-quality-combiner`
- Size: M
- Goal: implement `q(e,c) = d_eff * i * f * (1 - tamper_penalty)` exactly as in `DESIGN.md` 6.3; store in `evidence_quality` (migration `0014`) with all components and `algo_version`.
- Acceptance: golden tests with hand-computed values; all parameters in one config object; sensitivity script varies parameters and writes a report; monotonicity properties tested (e.g. increasing `d` never decreases `q`).
- Research hook: parameter defaults are hypotheses; sensitivity results go into EP-12.
- Contract: see design/VERDICT_V2_SLICE.md (docs/research/design/; Verdict v2 alpha: q(e,c) and link mapping in 3.5; evidence_quality table is Beta (migration 0016))

### EV-09 Mutation caching and budgets   [ ]
- Owner type: agent-ok
- Depends on: EV-04
- Branch: `feature/mutation-cache`
- Size: M
- Goal: avoid rerunning mutants whose (mutant hash, relevant test hashes, dependency hash) are unchanged.
- Acceptance: second run on an unchanged symbol is a cache hit (measured); cache invalidates on test change; correctness equivalence test (cached vs full).

### EV-10 Equivalent and flaky mutant handling   [ ]
- Owner type: pair
- Depends on: EV-04, F-11
- Branch: `feature/mutation-equivalent-flaky`
- Size: M
- Goal: reduce false "survivors": detect likely equivalent mutants (trivial compiler-equivalence heuristics, identical bytecode/AST after normalization), rerun survivors/timeouts to exclude flakiness; mark `equivalent_suspect`; exclude from denominator by policy.
- Acceptance: documented heuristic and measured false-positive rate on a labelled sample; never silently dropped (always visible in UI).

### EV-11 Evidence API and UI   [ ]
- Owner type: agent-ok
- Depends on: EV-08
- Branch: `feature/evidence-api-ui`
- Size: L
- Goal: `GET /analyses/{id}/evidence`, `/evidence/{eid}`, `/tamper`; UI listing evidence with quality breakdown ("why is this strong/weak"), survivors with the mutated line shown, tamper findings with before/after.
- Acceptance: each `q` component visible; links to the criterion; empty states; accessibility checks.
- Product hook: "your tests passed, but they would not have caught this bug" -- shown with a concrete surviving mutant.

### EV-12 (Stretch) Adversarial probe generation   [ ]
- Decision 2026-11-02 (DEC-019): the human decision is made. Advisory, sandbox-only, flag-gated (`RADIUS_FEATURE_PROBES`), never written to the user's repo, never counted as contributor evidence, and LLM-written probes need the DEC-021 egress policy. The task stays a not-started stretch; start only after EV-04 and the M4 gate.
- Owner type: human-required decision first
- Depends on: EV-04, DEC (Radius generating tests)
- Branch: `feature/evidence-probes`
- Size: XL
- Goal: automatically generate property-based or adversarial probes against changed symbols to expose behavior differences (e.g. differential testing against the base version, Hypothesis-based properties, tester-vs-mutant loops).
- Rules: probes are verification artifacts stored in Radius, never committed to the user's repo; clearly labelled "generated"; counted with a lower `i(e)` (since not independent human intent).
- Acceptance: on fixtures with seeded bugs that existing tests miss, probes find a meaningful fraction; false-alarm rate measured.
- Risks: conflicts with the "Radius does not generate code" principle; requires explicit decision.

### EV-13 Evidence for non-behavioral changes   [ ]
- Owner type: pair
- Depends on: EV-01, LK-01
- Branch: `feature/evidence-non-behavioral`
- Size: M
- Goal: handle refactors, renames, docs, config, dependency bumps. Provide "behavior preserved" evidence: AST-equivalence for pure refactors, public API surface diff, type check, differential run of the existing suite, lockfile review.
- Acceptance: pure rename/format PRs are `verified` with explicit "no behavior change" evidence; mixed PRs are split by symbol.

### EV-14 TypeScript tamper rules and mutation adapter   [ ]
- Owner type: agent-ok
- Depends on: F-09, EV-02, EV-04
- Branch: `feature/evidence-typescript`
- Size: XL
- Goal: port T001-T016 where applicable (Jest/Vitest: `it.skip`, `expect(true)`, `toBeTruthy` weakening) and add a Stryker adapter.
- Acceptance: fixtures per rule; Stryker runs within budget in sandbox.

### EV-15 Non-functional evidence hooks   [ ]
- Owner type: pair
- Depends on: EV-01
- Branch: `feature/evidence-non-functional`
- Size: M
- Goal: accept performance benchmarks, security scan (SARIF), accessibility checks as evidence for `non_functional` criteria, mapped by tags in `.radius/intent.yml`.
- Acceptance: a `non_functional` criterion cannot be `proven` by unit tests alone; requires typed evidence.
