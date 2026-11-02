# Verdict v2 alpha: build-ready slice design

**Status:** decisions D1-D17 accepted as recommended in section 8.2 by owner delegation on 2026-11-02 (recorded as DEC-027 in `../../decisions.md`); the design is otherwise as proposed. Date: 2026-11-02. Author: architect pass (docs only, no code).

**Status:** proposed design for owner sign-off. Date: 2026-11-02. Author: architect pass (docs only, no code).

**Companions (same folder):** `verdict_v2.schema.json` (JSON Schema of the stored/served verdict payload), `verdict_v2.example.08.json` (a complete payload for fixture 08), `verdict_v2.fixture_expectations.json` (machine-readable expectations for the 8 F-14 fixtures).
**Reads with:** `../DESIGN.md` (6.3 to 6.5), `../tasks/{EV-evidence-quality,VD-verdict-v2,LK-linking}.md`, `../../decisions.md` (DEC-003, DEC-006 to DEC-009, DEC-026), `../preregistration/PREREGISTRATION.md` (RQ2 predictor UIM).

Everything in this file is grounded in the code on `origin/develop` at `e3538fa` plus the unmerged branch `feature/evidence-tamper-rules` (EV-02). Where a number or behaviour was measured by running existing code on the F-14 fixtures it says "measured"; where it is a choice it says "decision"; where it assumes something not yet verified it says "assumption".

---

## 0. Summary and what the code review found

**Goal.** A user-visible, per-criterion verdict on a pull request, behind one flag, built from evidence that already exists in the repository, assembled by several agents in parallel without touching the same file.

Findings from reading the code that shape the design (all verified):

| # | Finding | Evidence | Consequence |
|---|---|---|---|
| F1 | The default product is still file-level selection plus a heuristic score. Intent (IN-*), linking (LK-01/02/03) and tamper (EV-02) are built but feed no verdict. | `apps/worker/src/radius_worker/orchestrator.py` computes symbol changes and (on the EV-02 branch) tamper findings, then only logs counts. | v2 must be a separate pipeline reading these outputs, not a patch of v1. |
| F2 | By default the worker runs no tests (`execute_tests=False`, `WORKER_EXECUTE_TESTS` off). Test evidence arrives later from CI via `POST /analyses/{id}/tests/results`, which re-scores v1 but **never republishes to GitHub**: the API holds no App credentials. | `apps/worker/src/radius_worker/config.py`; `apps/api/src/radius_api/routes/tests.py`; `docs/CI_INTEGRATION_GUIDE.md` line 32; `docs/audit/RADIUS_AUDIT.md` line 434. | "Republish after CI" is not optional polish: without it the first v2 comment is always "awaiting CI" and is never updated. It is in the slice (VS-07). |
| F3 | Per-case outcomes exist only for CI uploads (`test_result_uploads.cases`, `ReportedTestCase`). Worker-run (sandbox) results are aggregate only (`TestRunResult`). | `packages/shared/src/radius_shared/database/models.py` `TestResultUpload`; `packages/testing/.../domain/entities.py`. | Alpha supports CI-uploaded JUnit/JSON with per-case results. Worker-run results are out of scope (decision D7). |
| F4 | Symbol-to-test links (LK-03) are per symbol, not per criterion. When one function implements several criteria (4 of the 8 fixtures), every test of that function would support every criterion. Measured on fixture 08: criterion C4 ("not on the common-password list", no test at all) received support from three unrelated tests. | Ran LK-02 and LK-03 on the fixtures (see 7.3). | A criterion-to-test **relevance** edge is required (new task VS-04). Without it v2 would over-credit and be worse than v1. |
| F5 | LK-02 combined scores are rank-calibrated, not probabilities (`packages/linking/README.md`). Measured top-1 criterion-to-symbol scores on the fixtures range 0.28 to 0.91. Using them directly as `l(c,e)` would make a correctly linked single-function PR unprovable. | Same run. | The alpha maps scores through a saturating gate (3.4), not a raw multiplier. LK-06 owns real calibration later. |
| F6 | DESIGN 6.3 sets `cap_static = 0.4` and 6.4 `tau_support = 0.6`. Under those, no static-only criterion can reach `proven` with fewer than about four independent strong tests; the F-14 fixtures could never produce `verified`. | Hand computation, 7.2. | Alpha uses a named **alpha-static profile** (cap 0.6, tau 0.5), both inside the pre-registered sweep grid (decision D2). |
| F7 | `radius_intent.domain.enums.CriterionState` already exists and means the human-confirmation lifecycle (`proposed`, `confirmed`, ...). | `packages/intent/src/radius_intent/domain/enums.py`. | The per-criterion support state (DEC-008: proven, weak, unevidenced, contradicted, excluded) must be named `SupportState` in code to avoid a clash. |
| F8 | Migrations 0011 and 0012 are taken (intent persistence, organization status). The task files still say 0011 to 0015 for LK-05/EV-01/EV-04/EV-08/VD-03. | `infra/database/migrations/versions/`. | Task migration numbers are stale; this document reassigns them (section 4). |
| F9 | Shared registration points exist that every table task would otherwise edit: `radius_shared/database/__init__.py`, `infra/database/migrations/env.py`, `.github/workflows/ci.yml` PYTHONPATH, `apps/api/.../main.py` router list, `data-panels.tsx`. | Read. | A single scaffold task (VS-00) edits them once; later tasks never do. |

**Recommendation in one paragraph.** Name the slice **Verdict v2 alpha**, profile `alpha-static`, `algo_version = verdict-v2-alpha-1`. One env var `RADIUS_FEATURE_VERDICT_V2` (`off` default, `shadow`, `on`). Stage A (needs the repository checkout) builds the IEG and static facts inside the analysis job; Stage B (pure, needs only stored data plus CI outcomes) scores, decides and renders, and is re-run whenever CI results arrive. The whole computed bundle is stored as versioned JSON in one new table `verdict_v2`; normalized tables (`evidence_items`, `evidence_quality`, `ieg_nodes/edges`, `criterion_support`) are specified in section 4 as projections of the same dataclasses and are **off the critical path**. v1 code paths are not edited.

---

## 1. Slice scope

### 1.1 Included in Verdict v2 alpha

| Area | In the alpha | Source of truth in the repo |
|---|---|---|
| Intent | Criteria of the latest intent snapshot with lifecycle state not `rejected`/`orphaned`; weight, testability, hints (`paths`, `tests`) | `packages/intent` (IN-01/05/07), worker `intent_ingestion.py` |
| Change model | Changed symbols with change kind and behavioral flag, Python only | `radius_analysis.symbol_changes` (LK-01) |
| Criterion to symbol | Combined, ranked links | `radius_linking` (LK-02) |
| Symbol to test | Static plus naming links (dynamic coverage links are consumed if present, never required) | `radius_testing.linking` (LK-03) |
| Criterion to test | New relevance edge | VS-04 (in `radius_linking`) |
| Assertion strength | `a_static` from AST features of each linked test | LK-04 (new, `radius_testing.assertions`) and EV-06 |
| Freshness | `f(e) in {0,1}` by head SHA binding | EV-07 |
| Independence | Lite: pre-existing unchanged test 1.0, changed in the PR 0.8 (unknown author) or 0.6 (PR carries an agent trailer) | EV-03-lite |
| Tamper | Findings of `tamper-rules-v1`, attached to tests/symbols; severity penalties; high severity fails the verdict | `radius_analysis.tamper` (EV-02, branch `feature/evidence-tamper-rules`) |
| Test outcomes | Per-case outcomes from CI uploads; skipped/failed/flaky handled | `test_result_uploads.cases`, `ReportedTestCase`, F-11 flaky data |
| Flakiness | Rerun-detected flaky tests contribute nothing and are flagged; history flakiness score discounts | F-11 (`docs/FLAKY_TESTS.md`) |
| Support, UIM, states | `S(c)`, `UIM`, 5 per-criterion states (DEC-008) | VD-01, VD-02 |
| Verdict | 4 PR-level states (DEC-008), ordered rules, justification tree | VD-03 |
| Surfaces | PR comment and Check Run v2 (updated in place, republished after CI), `GET /analyses/{id}/verdict`, dashboard panel | VD-06, VS-09, VS-10 |

### 1.2 Explicitly excluded (each has an existing task; none is needed for a first visible slice)

Mutation testing and `d_mut` (EV-04, EV-05, EV-09, EV-10); calibration, `P`, intervals, conformal abstention (CA-*); process signals and trajectories (PR-*); triage and agent re-prompt (TR-*); manager views (MG-*); the policy engine, per-repo thresholds, path strictness and waivers (VD-04, VD-05; the alpha uses one in-code config object); new LLM calls of any kind (DEC-009: nothing the verdict reads is LLM output); TypeScript evidence (EV-14); non-behavioral evidence (EV-13); non-functional typed evidence (EV-15); Check Run annotations (the current client has no annotations parameter, `packages/github/src/radius_github/client.py::create_check_run`); explainability rendering by LLM (VD-08); org-level flag override (follow-up of VD-07).

### 1.3 The flag

`RADIUS_FEATURE_VERDICT_V2` (worker and API settings, same alias, same pattern as the existing `RADIUS_FEATURE_*` fields in `apps/worker/src/radius_worker/config.py`).

| Value | Behaviour |
|---|---|
| `off` (default; also unset, `false`, `0`) | Nothing changes. No v2 code runs. |
| `shadow` | Stage A and B run and are stored; **v1 is published**; the dashboard shows v2 labelled "shadow". Free evaluation data (VD-07 research hook). |
| `on` (also `true`, `1`) | v2 is computed, stored and **published instead of v1** when it succeeded; v1 is still computed and stored (`confidence_reports` unchanged) and is the automatic fallback. |

Prerequisite for a useful run: `RADIUS_FEATURE_INTENT_INGESTION=true` (otherwise there is no snapshot and the verdict is `insufficient_evidence: intent_missing`, which is the honest result). Org-level override is a follow-up and not designed here.

---

## 2. Packages, modules and file ownership

### 2.1 Placement decisions (DEC-003 / DEC-007 rationale)

| Concern | Placement | New package? | Why |
|---|---|---|---|
| Evidence model, `a_static`, freshness, independence, `q(e)`, IEG model and builder, `S(c)`, UIM, states | `packages/evidence`, import name `radius_evidence` | **New** (named and approved in DEC-007 and DESIGN 4.1; first task starting now justifies it under DEC-003) | A pure, stdlib-only domain below `confidence`. It must not depend on analysis/linking/testing (those are producers; adapters live in the worker). |
| Verdict rules, justification tree, `VerdictV2` model, verdict persistence | `radius_confidence.verdict_v2` | Sub-package of existing `packages/confidence` | The confidence domain already owns `VerificationStatus` and the verdict contract (DEC-008). All files are new, so v1 files are not edited. Direction `confidence -> evidence` (evidence stays pure). |
| Assertion extraction (LK-04) | `radius_testing.assertions` | Sub-package of `packages/testing` | Same precedent as LK-03 (`radius_testing.linking`): it reads test files using testing's discovery conventions. Output is a plain dataclass; the evidence package never imports testing. |
| Criterion-to-test relevance (VS-04) | `radius_linking` (new files) | Existing package | It is a linker; reuses `domain/bm25.py` and `domain/text.py`. |
| Tamper | `radius_analysis.tamper` | Already a sub-package on the EV-02 branch (not `packages/tamper`) | Decided by EV-02 (its README): avoids a cycle with LK-01. Unchanged here. |
| PR comment / Check Run v2 renderer | `radius_github.verdict_v2` | Sub-package of `packages/github` | Does not import any domain package: it renders a plain `VerdictV2View` parsed from the stored payload JSON. `publisher.py` is not edited. |
| Composition (adapters from LK-01/02/03/04, EV-02, DB into evidence inputs; DB persistence orchestration; publish switch) | `apps/worker/src/radius_worker/verdict_v2/` | Worker-internal | Only the worker and tests may import every domain. |
| API route and schemas | `apps/api/src/radius_api/routes/verdict_v2.py`, `schemas/verdict_v2.py` | New files | Same pattern as `routes/intent.py`. |
| Dashboard panel | `apps/dashboard/components/verdict-v2-panel.tsx`, `lib/verdict-v2.ts` | New files | One mount line is added once (VS-00). |

### 2.2 Dependency graph (arrows point from importer to imported; no cycles)

```
                      apps/worker  (composition root)  ---------------------------+
                      apps/api  (reads stored payload only)                       |
                          |  \                                                    |
                          |   +--> radius_github.verdict_v2  (no domain imports) |
                          v                                                       v
   radius_confidence.verdict_v2 ---------> radius_evidence.domain  <------ radius_evidence.application
        (rules, tree, store)                   (pure, stdlib only)                |
                |                                      ^                          v
                |                                      |            radius_evidence.infrastructure (later: SQL repos)
                v                                      |                          |
   radius_shared (db models, errors, logging)  <-------+--------------------------+

   producers (imported ONLY by apps/worker adapters and tests):
   radius_analysis.symbol_changes (LK-01) <- radius_analysis.tamper (EV-02)
   radius_intent  (criteria, hints)
   radius_linking (LK-02, VS-04)  -> radius_analysis, radius_graph (infra only; its domain is pure)
   radius_testing.linking (LK-03), radius_testing.assertions (LK-04) -> radius_graph
```

Import rules (enforce with import-linter contracts created in VS-00, in the style of `packages/linking/.importlinter`, wired into `.github/workflows/ci.yml` next to the intent and linking contracts):

1. `radius_evidence.domain` imports only the standard library and itself. `application` imports `domain`. `infrastructure` may import `radius_shared` and SQLAlchemy.
2. `radius_evidence` never imports `radius_analysis`, `radius_intent`, `radius_linking`, `radius_testing`, `radius_graph`, `radius_confidence`, `radius_github`.
3. `radius_confidence.verdict_v2.domain` imports only the stdlib and `radius_evidence.domain`. Nothing in `radius_confidence` v1 (`domain/`, `application/`, `infrastructure/`) may import `verdict_v2` (v1 stays untouched and independent).
4. `radius_github.verdict_v2` imports only the stdlib and `radius_github` itself.
5. Producers never import `radius_evidence` or `radius_confidence.verdict_v2`. Data crosses the boundary as plain dataclasses/dicts defined by the contracts in section 3.
6. `__init__.py` files in all new packages are docstring-only (no barrel re-exports). Consumers import by full module path. This removes the main source of merge conflicts.

### 2.3 File ownership map (one owner per path; "contract" files are frozen after VS-00)

`VS-00` creates the files marked **C** (contract) with the dataclasses and defaults in section 3; their content is then owned by the named task, and changing a field name or default afterwards requires a "contract change" PR approved by the architect (this document is updated in the same PR).

| Path | Task owner |
|---|---|
| `packages/evidence/src/radius_evidence/domain/enums.py` | VS-00 **C** |
| `.../domain/model.py` (EvidenceItem, Reason, FreshnessInfo, IndependenceInfo, FlakyInfo, AssertionFeatures, AssertionFact) | VS-00 **C**, then EV-01 |
| `.../domain/config.py` (every parameter dataclass and defaults, section 3.8) | VS-00 **C** |
| `.../domain/inputs.py` (stage B input DTOs, section 3.7) | VS-00 **C** |
| `.../domain/strength.py` (`a_static`) | EV-06 |
| `.../domain/freshness.py` | EV-07 |
| `.../domain/independence.py` | EV-03 (lite) |
| `.../domain/quality.py` (`EvidenceQuality`, combiner) | EV-08 |
| `.../domain/ieg.py` (nodes, edges, graph, path queries) and `.../application/ieg_builder.py` | LK-05 |
| `.../domain/support.py` (`SupportResult`, `S(c)`) | VD-01 |
| `.../domain/states.py` (states, `UimResult`, flags) | VD-02 |
| `.../application/pipeline.py` (pure Stage B: inputs -> bundle) | VS-03 |
| `.../infrastructure/*_repository.py` (normalized tables; Beta) | EV-01 / EV-08 / LK-05 / VD-02 (one file each, see 4.3) |
| `packages/confidence/src/radius_confidence/verdict_v2/domain/model.py` (`VerdictV2`, `Verdict`, `RuleResult`, `JustificationNode`) | VS-00 **C**, then VD-03 |
| `.../verdict_v2/domain/rules.py`, `tree.py`, `application/service.py`, `infrastructure/sqlalchemy_store.py` | VD-03 |
| `packages/github/src/radius_github/verdict_v2/view.py` (`VerdictV2View`, `from_payload`) | VS-00 **C**, then VD-06 |
| `.../verdict_v2/markdown.py`, `publisher.py` | VD-06 |
| `packages/testing/src/radius_testing/assertions/**` | LK-04 |
| `packages/linking/src/radius_linking/domain/test_doc.py`, `application/test_relevance.py` | VS-04 |
| `packages/shared/src/radius_shared/database/verdict_v2.py` (models `VerdictV2Row`, `VerdictV2RequestRow`) | VS-00 (stub) then VD-03 |
| `packages/shared/src/radius_shared/database/{evidence,evidence_quality,ieg,criterion_support}.py` | Beta tasks (4.3) |
| `infra/database/migrations/versions/20261102_0013_*`, `..._0014_*` | VS-00 creates chained placeholders; VD-03 and VS-07 fill their own |
| `apps/worker/src/radius_worker/verdict_v2/collect.py`, `adapters.py`, `sources.py` (Stage A) | VS-05 |
| `.../verdict_v2/scoring.py`, `store.py` (Stage B, fallback, status) | VS-06 |
| `.../verdict_v2/requests.py` (outbox consumer) and the one-line API enqueue | VS-07 |
| `.../verdict_v2/publish.py`, and the `_publish_github_result` branch in `runner.py` | VS-08 |
| `apps/worker/src/radius_worker/config.py` and `apps/api/src/radius_api/config.py` (flag fields), `.env.example`, `docs/DEPLOYMENT.md`, `docker-compose.yml` | VD-07-lite |
| `apps/worker/src/radius_worker/runner.py` (Stage A/B hook, ~15 lines) | VS-05 (hook), VS-08 (publish branch); sequenced, see 7.4 |
| `apps/api/src/radius_api/routes/verdict_v2.py`, `schemas/verdict_v2.py`, `docs/API_CONTRACTS.md` section | VS-09 |
| `apps/api/src/radius_api/main.py` (router include), `routes/verdict_v2.py` stub | VS-00 |
| `apps/dashboard/components/verdict-v2-panel.tsx`, `lib/verdict-v2.ts`, `tests/verdict-v2.test.mjs`, a prop on `components/intent-panel.tsx` | VS-10 |
| `apps/dashboard/components/data-panels.tsx` (one mount line) | VS-00 |
| `benchmarks/fixtures/verdict_v2/**` (stage bundles) | VS-01 |
| `tests/test_verdict_v2_fixtures.py` (vertical-slice acceptance) | VS-02 |

Files that stay untouched: everything under `packages/confidence/src/radius_confidence/{domain,application,infrastructure,dto,interfaces}`, `packages/github/src/radius_github/publisher.py`, `apps/worker/src/radius_worker/orchestrator.py`, `apps/api/src/radius_api/routes/confidence.py`.

Deliberate decision: v2 does **not** edit the orchestrator. The orchestrator discards the symbol changes and tamper report (log only). Rather than changing its return type (a hot file that the EV-02 branch also edits), Stage A re-runs `extract_symbol_changes` and `analyze_tampering` from the checkout path in `ExecuteAnalysisCommand`. Cost: LK-01 runs twice when `RADIUS_FEATURE_SYMBOL_CHANGES` is also on. Mitigation: a per-process cache keyed by (repository path, base, head) in `collect.py`. Sharing the result with the orchestrator is a follow-up once v2 is the default.

---

## 3. Data contracts

All dataclasses are `@dataclass(frozen=True, slots=True)`, JSON-serializable through `to_dict()`/`from_dict()` with sorted keys, floats rounded to 6 decimals (the `radius_linking` convention), no clocks inside the domain, tuples instead of lists. Identifiers are plain strings.

### 3.1 Enumerations (`radius_evidence/domain/enums.py`)

```python
class EvidenceKind(StrEnum):        # alpha produces only the first two
    TEST_OUTCOME = "test_outcome"
    TAMPER_FINDING = "tamper_finding"
    # reserved, not produced yet: MUTATION_RESULT, COVERAGE_RECORD, STATIC_ANALYSIS, ATTESTATION, PROCESS_SIGNAL

class EvidenceSource(StrEnum):
    CI_UPLOAD = "ci_upload"
    WORKER_RUN = "worker_run"       # reserved (D7)
    STATIC_RULES = "static_rules"

class Outcome(StrEnum):
    PASSED = "passed"; FAILED = "failed"; ERROR = "error"; SKIPPED = "skipped"
    FLAKY = "flaky"                 # failed then passed on rerun (F-11): neither pass nor fail
    NOT_RUN = "not_run"             # linked test with no reported case

class AuthoredBy(StrEnum):  HUMAN = "human"; AGENT = "agent"; UNKNOWN = "unknown"
class IndependenceBasis(StrEnum):
    PRE_EXISTING_UNCHANGED = "pre_existing_unchanged"; CHANGED_IN_PR = "changed_in_pr"

class AssertKind(StrEnum):
    VALUE_EQUALITY = "value_equality"; APPROX_EQUALITY = "approx_equality"
    EXCEPTION_TYPE_MESSAGE = "exception_type_message"; EXCEPTION_TYPE = "exception_type"
    MEMBERSHIP = "membership"; COMPARISON_BOUND = "comparison_bound"; LENGTH_CHECK = "length_check"
    TRUTHINESS = "truthiness"; NONE_CHECK = "none_check"; TYPE_CHECK = "type_check"
    MOCK_CALLED = "mock_called"; SNAPSHOT = "snapshot"
    TAUTOLOGY = "tautology"; NO_ASSERTION = "no_assertion"; OTHER = "other"

class SupportState(StrEnum):        # DEC-008. NOT radius_intent's CriterionState (finding F7)
    PROVEN = "proven"; WEAK = "weak"; UNEVIDENCED = "unevidenced"
    CONTRADICTED = "contradicted"; EXCLUDED = "excluded"

class Flag(StrEnum):                # orthogonal to state; any number per criterion
    TAMPERED = "tampered"; FLAKY_EVIDENCE = "flaky_evidence"; STALE_EVIDENCE = "stale_evidence"
    LOW_LINK_CONFIDENCE = "low_link_confidence"; UNCONFIRMED = "unconfirmed"
    PENDING_RESULTS = "pending_results"; STATIC_ONLY = "static_only"
    NO_STRONG_ASSERTION = "no_strong_assertion"; NEEDS_TYPED_EVIDENCE = "needs_typed_evidence"
    NO_LINKED_TEST = "no_linked_test"

class NodeKind(StrEnum):  CRITERION="criterion"; SYMBOL="symbol"; TEST="test"; EVIDENCE="evidence"; FINDING="finding"
class EdgeKind(StrEnum):
    IMPLEMENTED_BY = "implemented_by"   # criterion -> symbol   (LK-02)
    EXERCISED_BY = "exercised_by"       # symbol    -> test     (LK-03)
    ADDRESSED_BY = "addressed_by"       # criterion -> test     (VS-04 relevance, or an intent.yml tests hint)
    PRODUCED = "produced"               # test      -> evidence item
    AFFECTS = "affects"                 # tamper finding -> test | symbol
```

PR-level (`radius_confidence/verdict_v2/domain/model.py`):

```python
class Verdict(StrEnum):             # DEC-008, equals the 4 DESIGN 6.5 states
    VERIFIED = "verified"; FAILED = "failed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"; NEEDS_REVIEW = "needs_review"
```

**Mapping of the vocabulary you may meet elsewhere** (so nobody invents a sixth state): `partially_evidenced` = `weak`; `unproven` = `unevidenced`; `not_testable` = `excluded` with reason `not_testable` (vague/untestable criteria); `tampered` = flag `TAMPERED` on any state (its effect is on `q`, section 3.4, and on the PR rules, section 3.9); `needs_review` exists **only at PR level** (DEC-008). Recommendation D3: do not add a sixth criterion state.

### 3.2 Assertion features (LK-04 output, EV-06 input) (`radius_evidence/domain/model.py`)

```python
@dataclass(frozen=True, slots=True)
class AssertionFact:
    kind: AssertKind
    line: int
    target_symbol_ids: tuple[str, ...] = ()      # LK-01 symbol ids, best effort via data flow; may be empty
    compares_computed_value: bool = False        # operand is a call result / computed expression, not a literal-only compare
    note: str | None = None

@dataclass(frozen=True, slots=True)
class AssertionFeatures:                          # one per test function
    test_id: str                                  # path::Class::function (radius_testing.linking.normalize_test_id form)
    path: str
    line_start: int
    line_end: int
    assertions: tuple[AssertionFact, ...]
    n_assertions: int
    expects_exception: bool                       # pytest.raises / assertRaises present
    is_parametrized: bool
    n_param_cases: int | None
    has_skip_marker: bool                         # skip / skipif / xfail decorator
    name_terms: tuple[str, ...]                   # stemmed identifier terms of the test name (used by VS-04)
    literal_terms: tuple[str, ...]                # terms of string/number literals in the body (used by VS-04)
    called_symbol_refs: tuple[str, ...] = ()      # path::qualified_name of project callables called, best effort
    algo_version: str = "test-assertions-v1"
```

LK-04 (in `radius_testing.assertions`) emits plain dicts with exactly these keys (`to_dict`); `radius_evidence` parses them with `AssertionFeatures.from_dict`. Neither package imports the other.

### 3.3 `EvidenceItem` (`radius_evidence/domain/model.py`)

```python
@dataclass(frozen=True, slots=True)
class Reason:           code: str; detail: str; ref: str | None = None

@dataclass(frozen=True, slots=True)
class FreshnessInfo:    bound_sha: str; current_sha: str; f: float; reason: str   # "current_head" | "stale_sha" | "unbound"

@dataclass(frozen=True, slots=True)
class IndependenceInfo: authored_by: AuthoredBy; basis: IndependenceBasis; factor: float; reasons: tuple[Reason, ...] = ()

@dataclass(frozen=True, slots=True)
class FlakyInfo:        flagged: bool; source: str | None = None; score: float | None = None   # source: "rerun" | "history"

@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str                    # "ev_" + sha256(analysis_id | kind | subject | head_sha | algo)[:20]; deterministic
    kind: EvidenceKind
    source: EvidenceSource
    analysis_id: str
    repository_id: str
    head_sha: str                       # 40 lowercase hex; items without it are rejected at construction (SHA-binding guarantee)
    subject_id: str                     # test_id for TEST_OUTCOME, finding_id (EV-02 "tf_...") for TAMPER_FINDING
    path: str | None
    symbol_ids: tuple[str, ...]         # symbols this item is about (tests: symbols linked via EXERCISED_BY; findings: finding.symbol)
    criterion_ids: tuple[str, ...]      # informational denormalization of the IEG paths; authoritative per-criterion values are EvidenceQuality
    outcome: Outcome | None             # tests only
    duration_ms: int | None
    features: AssertionFeatures | None  # tests only
    severity: str | None                # findings only: info|low|medium|high|critical (EV-02 Severity.label)
    rule_id: str | None                 # findings only: "T001" ...
    independence: IndependenceInfo
    flaky: FlakyInfo
    freshness: FreshnessInfo
    reasons: tuple[Reason, ...]
    collected_at: str                   # ISO-8601 UTC; excluded from inputs_digest
    algo_versions: dict[str, str]       # {"assertions": "test-assertions-v1", "independence": "indep-lite-1", ...}
```

JSON example (a test item from fixture 08, abbreviated):

```json
{
  "evidence_id": "ev_7c1e90ab53d2f1a44b0e",
  "kind": "test_outcome", "source": "ci_upload",
  "analysis_id": "5b0b9c6e-0000-4000-8000-000000000008", "repository_id": "d41d8cd9-0000-4000-8000-000000000001",
  "head_sha": "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3",
  "subject_id": "tests/test_validators.py::test_rejects_missing_digit",
  "path": "tests/test_validators.py",
  "symbol_ids": ["python:src/validators.py::validate_password#function@981c887bac80"],
  "criterion_ids": ["c_2f6a11"],
  "outcome": "passed", "duration_ms": 3,
  "features": {"test_id": "tests/test_validators.py::test_rejects_missing_digit", "path": "tests/test_validators.py",
               "line_start": 14, "line_end": 17, "n_assertions": 1, "expects_exception": false,
               "is_parametrized": false, "n_param_cases": null, "has_skip_marker": false,
               "assertions": [{"kind": "value_equality", "line": 16, "compares_computed_value": true, "target_symbol_ids": [], "note": null}],
               "name_terms": ["reject", "miss", "digit"], "literal_terms": ["abcdefgh", "false"], "called_symbol_refs": ["src/validators.py::validate_password"],
               "algo_version": "test-assertions-v1"},
  "severity": null, "rule_id": null,
  "independence": {"authored_by": "unknown", "basis": "changed_in_pr", "factor": 0.8, "reasons": [{"code": "test_added_in_pr", "detail": "test function is new in this PR", "ref": null}]},
  "flaky": {"flagged": false, "source": null, "score": null},
  "freshness": {"bound_sha": "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3", "current_sha": "4f2a9d1c0b7e6a53f8c1d2e3b4a59687c0d1e2f3", "f": 1.0, "reason": "current_head"},
  "reasons": [], "collected_at": "2026-11-02T10:15:00Z",
  "algo_versions": {"assertions": "test-assertions-v1", "independence": "indep-lite-1", "freshness": "fresh-1"}
}
```

Item construction rules (EV-01): a CI case is joined to its test id by `case_to_test_id(case, known_test_ids)` (JUnit `classname`/`file`/`name` to `path::Class::function`; parametrization suffixes stripped by `normalize_test_id`); a case that matches no known test id is kept as an item with `symbol_ids=()` and is only usable for the PR-level "any failure" rule (section 3.9). A linked test with no reported case yields an item with `outcome=NOT_RUN`. Tamper findings become `TAMPER_FINDING` items with `outcome=None`.

### 3.4 IEG (`radius_evidence/domain/ieg.py`, built by LK-05)

```python
@dataclass(frozen=True, slots=True)
class IegNode:  node_id: str; kind: NodeKind; ref: str; attrs: dict[str, Any]
# node_id: "crit:<criterion_id>" | "sym:<LK-01 symbol_id>" | "tst:<test_id>" | "evd:<evidence_id>" | "tfd:<finding_id>"

@dataclass(frozen=True, slots=True)
class IegEdge:
    edge_id: str            # "e_" + sha256(kind | src | dst | method)[:16]
    kind: EdgeKind
    src: str; dst: str
    weight: float           # raw producer score in [0,1]; the quality layer maps it (3.5)
    method: str             # "combined" | "explicit" | "static" | "naming" | "dynamic" | "lexical_test_relevance" | "intent_yml_hint" | "tamper_rule"
    reasons: tuple[Reason, ...] = ()
    attrs: dict[str, Any] = {}      # e.g. {"rank": 1, "by_linker": {"lexical": 0.31, "identifier": 0.0}, "kind": "direct_call", "bm25_raw": 1.18}

@dataclass(frozen=True, slots=True)
class Ieg:  analysis_id: str; head_sha: str; nodes: tuple[IegNode, ...]; edges: tuple[IegEdge, ...]; inputs_digest: str; algo_version: str = "ieg-1"
```

Builder inputs (all plain DTOs, section 3.7): `CriterionSymbolEdgeInput` from `radius_linking.LinkSet.links` (`linker == "combined"`, `rank <= max_symbols_per_criterion = 3`); `SymbolTestEdgeInput` from `radius_testing.linking.LinkSet.links` (`linker == "combined"`); `CriterionTestEdgeInput` from VS-04; `TamperFindingInput` from `radius_analysis.tamper.TamperReport.findings`. LK-02 and LK-03 both use the LK-01 `symbol_id` string for symbols (assumption verified on the fixtures by printing both outputs; VS-05 adds a regression test). Graph invariants (tested by LK-05): no edge with a missing endpoint; ids unique; edge kinds connect only the allowed node kinds; output sorted, byte-identical for equal inputs; query `paths(criterion_id)` returns every `criterion -> symbol -> test` path with the three weights.

### 3.5 Evidence quality and link strength (`radius_evidence/domain/quality.py`, EV-08)

Link strength of a path `c -> s -> t` (one evidence item per (criterion, test); the **best** path wins, paths are never summed):

```
l_cs = 0                              if w(IMPLEMENTED_BY) < link_min_cs          (default 0.20)
     = min(1, w / link_sat_cs)        otherwise                                   (default link_sat_cs = 0.40)
l_st = w(EXERCISED_BY)                if w >= min_test_link else 0                (default 0.50; drops import-only links, measured 0.25)
r_ct = w(ADDRESSED_BY)                (0 = edge absent = the test is not evidence for this criterion)
l(c,e) = l_cs * l_st * r_ct
```

Why saturate `l_cs` (finding F5): LK-02's noisy-OR is rank-calibrated; measured top-1 scores for correctly linked criteria on the fixtures were 0.35 (08 C2), 0.33 (08 C3), 0.46 (03 C1), 0.76 (01 C2), 0.91 (01 C1). A raw multiplier would cap a perfectly linked criterion at 0.35 support. The gate says: "a link at or above 0.40 is trusted as the implementing symbol; between 0.20 and 0.40 it is scaled; below 0.20 it is no link". A criterion linked with an `intent.yml` `paths` hint scores 0.95 and therefore saturates. LK-06 replaces this mapping with a calibrated one (the mapping is one function, `LinkMapping`, in `config.py`).

Quality of an item for a criterion:

```
a_static  = strength(features)                                  # EV-06, 3.6
d_eff     = min(cap_static, a_static)                           # no mutation data in the alpha: DESIGN 6.3 second branch
i         = independence.factor                                 # EV-03-lite
f         = freshness.f                                         # EV-07
flaky_f   = 0 if flaky.flagged and source == "rerun"; else 1 - min(flaky_discount_max, score) when score known; else 1
tamper_p  = 1 - PROD_k (1 - penalty(severity_k))                # findings attached to this test (AFFECTS edge); penalty: critical/high 1.0, medium 0.5, low 0.2, info 0
q(e, c)   = d_eff * i * f * flaky_f * (1 - tamper_p)            # DESIGN 6.3 plus the flaky factor the F-11 doc reserves for EV-08
usable    = outcome == PASSED and r_ct > 0 and l_st > 0 and l_cs > 0 and q > 0
```

`EvidenceQuality` (stored for every (evidence, criterion) pair, including unusable ones, with `status` explaining why, for ablations): `evidence_id, criterion_id, a_static, d_mut (None), d_eff, cap_static, i, f, flaky_f, tamper_penalty, q, l_cs, l_st, r_ct, l, lambda_kind, term, group, rank_in_group, discount, contribution, status, path (symbol_id, test_id), algo_version`.

### 3.6 `a_static` (EV-06) and relevance (VS-04)

`a_static(features) = max over assertion facts of table[kind]`; no facts and not `expects_exception` gives `NO_ASSERTION` = 0; a test with `has_skip_marker` is scored but its outcome is `SKIPPED` so `q` is 0. Defaults (config, hypotheses):

| Kind | Score | Kind | Score |
|---|---|---|---|
| value_equality | 1.00 | membership | 0.35 |
| approx_equality | 0.90 | comparison_bound | 0.35 |
| exception_type_message | 0.90 | length_check | 0.30 |
| exception_type | 0.80 | snapshot | 0.30 |
| truthiness | 0.25 | none_check | 0.25 |
| mock_called | 0.20 | type_check | 0.20 |
| tautology | 0.00 | no_assertion | 0.00 |

Decision (resolves a DESIGN ambiguity): DESIGN 6.3 ranks "type/None checks" together; the F-14 fixtures disagree with each other on `isinstance`-only (fixture 03 C2 `none`, fixture 08 C3 `weak`). The alpha separates them: `none_check` 0.25, `type_check` 0.20. Max is optimistic for tests mixing a strong and a weak assertion; that is intended (one strong assertion is a real constraint).

Relevance `r_ct` (VS-04, `radius_linking.application.test_relevance`): corpus = all test functions in test files that have at least one `EXERCISED_BY` edge or were modified in the PR (pin and record this; BM25 `idf` depends on the corpus). Document of a test = `name_terms` counted twice + `literal_terms`. Query = `terms(criterion.text)`. `raw` = BM25 (`radius_linking.domain.bm25.BM25Index`, k1 1.2, b 0.75). Edge only if `raw >= relevance_gate` (default 0.5); `weight = min(1, raw / relevance_sat)` (default 1.5). A `tests` hint in `.radius/intent.yml` (`CriterionHints.tests`) creates an edge with `weight = 1.0`, `method = intent_yml_hint`. Measured on the fixtures the lexical relevance is useful but not reliable (it finds the gold tests for 08 C1/C2/C3 and 03 C1/C3, finds only about half of the gold tests of 01 C1 while also crediting 01's `rejects_*` tests to C1, finds none for 05 C2 and 06 C2, and is corpus-sensitive: shrinking the corpus to the strongly linked tests changed 02 C1 from weak to unevidenced and 05 from weak to unevidenced). So: (a) a missing relevance edge is reported to the user as `no_linked_test` with the action "add a `tests:` hint", never silently credited; (b) the VD tasks are accepted against gold links (3.10), not against auto links.

### 3.7 Stage B input DTOs (`radius_evidence/domain/inputs.py`)

Producers are adapted to these in `apps/worker/.../adapters.py`; tests and fixture bundles construct them directly.

```python
@dataclass(frozen=True, slots=True)
class CriterionInput:        criterion_id: str; text: str; weight: float; testability: str   # radius_intent Testability value
                             lifecycle: str                                                  # proposed|confirmed|edited|needs_reconfirmation
                             hints_paths: tuple[str, ...] = (); hints_tests: tuple[str, ...] = ()
@dataclass(frozen=True, slots=True)
class SymbolInput:           symbol_id: str; path: str; qualified_name: str; kind: str; language: str
                             change_kind: str; is_behavioral: bool; is_test: bool; is_pseudo: bool    # <module>, <file>
@dataclass(frozen=True, slots=True)
class CriterionSymbolEdgeInput:  criterion_id: str; symbol_id: str; score: float; rank: int; by_linker: dict[str, float]; reasons: tuple[Reason, ...]
@dataclass(frozen=True, slots=True)
class SymbolTestEdgeInput:   symbol_id: str; test_id: str; score: float; kind: str; depth: int | None
@dataclass(frozen=True, slots=True)
class CriterionTestEdgeInput: criterion_id: str; test_id: str; weight: float; method: str; bm25_raw: float | None
@dataclass(frozen=True, slots=True)
class TamperFindingInput:    finding_id: str; rule_id: str; check: str; severity: str; confidence: float; path: str
                             symbol: str | None; test_id: str | None; reason: str; old_snippet: str | None; new_snippet: str | None
@dataclass(frozen=True, slots=True)
class CaseOutcomeInput:      test_id: str | None; raw_file: str | None; raw_classname: str | None; raw_name: str | None; outcome: Outcome
@dataclass(frozen=True, slots=True)
class StageAInput:           # persisted inside the bundle after Stage A
    analysis_id: str; repository_id: str; head_sha: str; changeset_ref: str
    criteria: tuple[CriterionInput, ...]; symbols: tuple[SymbolInput, ...]
    criterion_symbol: tuple[CriterionSymbolEdgeInput, ...]; symbol_test: tuple[SymbolTestEdgeInput, ...]
    criterion_test: tuple[CriterionTestEdgeInput, ...]; assertions: tuple[AssertionFeatures, ...]
    tamper: tuple[TamperFindingInput, ...]; tamper_waived: int; tamper_unanalyzable: tuple[str, ...]
    changed_test_ids: frozenset[str]            # tests added/modified in this PR (for independence)
    agent_signal: bool                          # PR carries an agent trailer (EV-03-lite)
    degraded: tuple[str, ...]                   # LK-01 notes/truncation, e.g. "truncated", "unsupported_language:ts"
    algo_versions: dict[str, str]               # symbol-changes-v1, criterion-symbol-links-v1, static-link-v1, tamper-rules-v1, ...
@dataclass(frozen=True, slots=True)
class StageBInput:
    stage_a: StageAInput
    cases: tuple[CaseOutcomeInput, ...]; uploads: int; flaky_test_ids: frozenset[str]; flaky_scores: dict[str, float]
    results_received: bool                      # at least one CI upload for this analysis and head
    ci_failed_cases: int
```

### 3.8 Configuration (one object, `radius_evidence/domain/config.py`, created by VS-00)

```python
@dataclass(frozen=True, slots=True)
class VerdictV2Config:
    profile: str = "alpha-static"
    quality: QualityConfig; support: SupportConfig; rules: RuleConfig; link: LinkMapping
    def digest(self) -> str   # sha256 of canonical JSON; stored on every verdict
```

| Parameter | Alpha default | DESIGN / pre-reg default | Note |
|---|---|---|---|
| `cap_static` | 0.60 | 0.4 | pre-reg sweep {0.2, 0.4, 0.6}; decision D2 |
| `tau_support` | 0.50 | 0.6 | pre-reg sweep {0.4 ... 0.8} |
| `tau_weak` (lower bound of `weak`) | 0.20 | 0.2 | |
| `iota_agent` / `iota_unknown` / human, pre-existing | 0.6 / 0.8 / 1.0 | 0.6 / 0.8 / 1.0 | EV-03-lite |
| `tamper penalty` critical, high / medium / low / info | 1.0 / 0.5 / 0.2 / 0 | same | |
| `lambda_kind[test_outcome]` | 1.0 | per kind | single kind in the alpha |
| `rho` (correlation discount per rank in a group) | 0.70 | not set (VD-01 says "diminishing returns") | decision, below |
| `s_cap` (max `S` from static-only evidence) | 0.90 | not set | decision, below |
| `strong_min` (a_static needed for at least one item before `proven`) | 0.50 | not set | prevents many weak tests summing to proven |
| `link_min_cs` / `link_sat_cs` | 0.20 / 0.40 | link caps 0.95 | 3.5 |
| `min_test_link` | 0.50 | not set | |
| `relevance_gate` / `relevance_sat` | 0.5 / 1.5 | not set | VS-04 |
| `flaky_discount_max` | 0.5 | not set | |
| `uim_max` | 0.20 | `uim_max` unspecified | decision |
| `min_intent_coverage` | 0.50 | "floor" unspecified | decision |
| `fail_on_tamper_at_least` | high | high = nullify | |
| `review_on_tamper_at_least` | medium | policy trigger | |
| `link_review_min` (best `l_cs` of a proven criterion) | 0.50 | not set | |
| `max_criteria` / `max_symbols` / `max_tests` / `max_bundle_bytes` / `timeout_s` | 50 / 5000 / 3000 / 2 MiB / 120 | | failure isolation |

### 3.9 Support `S(c)`, UIM, states, verdict rules

**Formula chosen (DESIGN 6.4 plus the two things it leaves open).** For criterion `c` and its usable items `E(c)`:

```
term(e)    = lambda_kind(e) * q(e, c) * l(c, e)
group(e)   = the symbol id on the best path of e                      # correlation proxy: tests of the same symbol overlap
sorted within a group by term desc (ties: evidence_id); k = 0-based rank in its group
contrib(e) = term(e) * rho^k                                           # diminishing returns for correlated evidence
S_raw(c)   = 1 - PROD_{e in E(c)} (1 - contrib(e))                     # noisy-OR over groups and ranks
S(c)       = min(S_raw(c), s_cap)                                      # cap: static-only evidence can never reach 1.0
```

Ambiguities in DESIGN and the decisions: (1) VD-01 asks for "cap the number of correlated items" without a rule; decision: the geometric discount `rho^k` per symbol group (coverage-line overlap replaces the proxy when dynamic coverage links exist, later). (2) DESIGN has no ceiling for static-only support; decision `s_cap = 0.90`. (3) `l` was ill-defined; decision 3.5. (4) A pile of weak tests must not equal a strong one: `proven` additionally requires one counted item with `a_static >= strong_min`; otherwise the state is `weak` and the flag `no_strong_assertion` is set.

Hand-checkable values (cap_static 0.6, i 0.8, l_st 0.9, l_cs = r = 1): one strong test `term = 0.6*0.8*0.9 = 0.432`; two: `1 - 0.568*(1 - 0.432*0.7) = 0.604`; four: 0.734. One truthiness test: `0.25*0.8*0.9 = 0.18`; two: 0.283.

**Per-criterion state (first match wins):**

| Order | Condition | State | Flags / reason code |
|---|---|---|---|
| 1 | lifecycle `rejected`/`orphaned` (not in input) or testability in {`subjective_or_vague`, `untestable_external`} | `excluded` | reason `not_testable` or `rejected` |
| 2 | any item attached to `c` (same gates as `usable` except outcome) has outcome `FAILED` or `ERROR` | `contradicted` | reason `failing_linked_test` with evidence ids. Independence discounts support, never a failure: a failing test counts however it was authored |
| 3 | testability `non_functional_measurable` (no typed evidence in the alpha) | `unevidenced` | flag `needs_typed_evidence` (EV-15 will lift it) |
| 4 | `S(c) >= tau_support` and a strong item exists | `proven` | |
| 5 | `S(c) >= tau_support` and no strong item | `weak` | flag `no_strong_assertion` |
| 6 | `tau_weak <= S(c) < tau_support` | `weak` | |
| 7 | otherwise | `unevidenced` | flag `no_linked_test` when `E(c)` is empty and no `ADDRESSED_BY` edge exists |

Other flags: `tampered` if any finding (any severity above info) is attached to a test in the criterion's candidate paths or to a linked symbol; `flaky_evidence`, `stale_evidence` (an item with `f=0` was ignored), `low_link_confidence` (best `l_cs < link_review_min` on a `proven` criterion), `unconfirmed` (lifecycle `proposed`), `pending_results` (no CI upload yet), `static_only` (always set in the alpha).

**UIM (unproven intent mass, exact definition used in the alpha and compatible with PREREGISTRATION RQ2):**

```
C*  = criteria whose state is not "excluded"
UIM = SUM_{c in C*} w_c * [ S(c) < tau_support ]  /  SUM_{c in C*} w_c        (= 0.0 when C* is empty; the verdict then uses rule R2a)
```

`w_c` = `Criterion.weight` (IN-01, in (0, 1], default 1.0). `contradicted` and `unevidenced` criteria have `S < tau` by construction. `non_functional_measurable` criteria count (as unevidenced). Excluded criteria leave both numerator and denominator and are listed in the output with their reason. The pre-registered predictor is the full pipeline's UIM; the alpha UIM is computed under the `alpha-static` profile and is tagged with `profile`, so alpha data is never mixed into confirmatory analysis (open decision D17).

**Intent coverage (decision, resolves "coverage of changed symbols by linked evidence" in DESIGN 6.5 rule 2):**

```
B = changed symbols with is_behavioral and not is_test and not (is_pseudo and kind == "file")     # <module> counts, <file> (non-code) does not
covered(s) = exists a non-excluded criterion with an IMPLEMENTED_BY edge to s with weight >= link_min_cs
             OR s is in the same file as a covered non-pseudo symbol                                # a module-level constant next to the linked function
intent_coverage = |{s in B : covered(s)}| / |B|        (1.0 when B is empty)
```

This is "intent coverage": which behavioral changes are accounted for by a stated criterion. It is the scope-creep signal (fixture 05). Evidence coverage per criterion is already `S(c)`. Both numbers are reported.

**PR-level decision table (ordered; every rule is evaluated and recorded, the first rule that fires decides; thresholds from `RuleConfig`).**

| Rule | Condition | Verdict | Reason code |
|---|---|---|---|
| R1a | any criterion `contradicted` | `failed` | `contradicted_criterion` |
| R1b | any CI case `FAILED`/`ERROR` for this head (matched to a criterion or not; sticky across uploads, as in v1) | `failed` | `ci_failure` |
| R1c | any unwaived tamper finding with severity >= `fail_on_tamper_at_least` (high) | `failed` | `tamper_high` |
| R2p | no CI upload received yet for this head (`results_received == False`) | `insufficient_evidence`, `pending=true` | `awaiting_test_results` |
| R2a | no non-excluded criterion exists, or none of testability `behavioral_testable`, while `B` is non-empty | `insufficient_evidence` | `intent_missing_or_untestable` |
| R2b | `UIM > uim_max` | `insufficient_evidence` | `unproven_intent_mass` |
| R2c | `intent_coverage < min_intent_coverage` | `insufficient_evidence` | `low_intent_coverage` |
| R2d | `degraded` contains `truncated`, `unsupported_language:*` for a behavioral file, or `snapshot_missing:*` | `insufficient_evidence` | `analysis_degraded` |
| R3a | any unwaived tamper finding with severity >= `review_on_tamper_at_least` (medium) | `needs_review` | `tamper_medium` |
| R3b | any flaky test attached to a criterion that is `proven` | `needs_review` | `flaky_dependency` |
| R3c | a `proven` criterion with `low_link_confidence` | `needs_review` | `weak_link_for_proven_criterion` |
| R4 | none above | `verified` | `all_rules_passed` |

R2p precedes R2a/b/c so that an unscored PR says "awaiting CI" instead of listing every criterion as unproven; R1 precedes it so a tamper `failed` shows immediately, without waiting for CI. `needs_review` in the alpha is reachable only through the policy-style triggers R3a to R3c, as VD-03 requires until calibration exists (CA-04). A PR with no behavioral change and no criteria (docs only, `B` empty) has R2a not firing and `UIM = 0`: it passes R2 and reaches R4 only if `intent_coverage` is 1.0 (empty `B`); EV-13 (non-behavioral evidence) will state that explicitly, until then the comment says "no behavioral change detected".

**Justification tree.** `justification` is stored and served as JSON (schema in `verdict_v2.schema.json`):

```json
{
  "schema": "verdict-v2-justification-1",
  "verdict": "insufficient_evidence",
  "decided_by": "R2b",
  "rules": [
    {"id": "R1a", "label": "contradicted criterion", "fired": false, "inputs": {"contradicted": []}},
    {"id": "R1b", "label": "failing CI case", "fired": false, "inputs": {"failed_cases": 0}},
    {"id": "R1c", "label": "high tamper finding", "fired": false, "inputs": {"threshold": "high", "max_severity": null, "finding_ids": []}},
    {"id": "R2p", "label": "awaiting CI results", "fired": false, "inputs": {"results_received": true}},
    {"id": "R2a", "label": "intent missing or untestable", "fired": false, "inputs": {"testable_criteria": 4}},
    {"id": "R2b", "label": "unproven intent mass", "fired": true,
     "inputs": {"uim": 0.75, "uim_max": 0.2, "criteria": [{"criterion_id": "c_2f6a11", "S": 0.432, "state": "weak"}, "..."]},
     "refs": {"criterion_ids": ["c_2f6a11", "c_81b0c4", "c_d3a2f7"], "evidence_ids": []}},
    {"id": "R2c", "label": "intent coverage", "fired": false, "inputs": {"intent_coverage": 1.0, "min": 0.5}},
    {"id": "R4", "label": "all rules passed", "fired": false, "inputs": {}}
  ],
  "thresholds": {"tau_support": 0.5, "uim_max": 0.2, "min_intent_coverage": 0.5, "fail_on_tamper_at_least": "high"},
  "versions": {"verdict": "verdict-v2-alpha-1", "evidence_quality": "evq-static-1", "support": "support-noisyor-1", "ieg": "ieg-1",
               "assertions": "test-assertions-v1", "relevance": "test-relevance-1", "freshness": "fresh-1", "independence": "indep-lite-1",
               "symbol_changes": "symbol-changes-v1", "criterion_symbol_links": "criterion-symbol-links-v1", "symbol_test_links": "link-combine-v1", "tamper": "tamper-rules-v1"},
  "config_digest": "sha256:...", "profile": "alpha-static", "inputs_digest": "sha256:..."
}
```

Invariant (tested by VD-03): every id in `refs` exists in the bundle; every rule is present exactly once, in the order above; `decided_by` is the first fired rule; the verdict is reproducible by `compute(bundle.stage_a + stage_b inputs, config)`.

### 3.10 `VerdictV2` and algo_version fields

`algo_version = "verdict-v2-alpha-1"` is the umbrella. Component versions (above) are stamped on every item/edge/result and copied into `justification.versions`. Any change to a default in 3.8 or to a formula bumps the component version (and the umbrella, `-2`), and the old implementation stays selectable until the evaluation freezes (IMPLEMENTATION_PLAN 1.6).

```python
@dataclass(frozen=True, slots=True)
class CriterionVerdict:
    criterion_id: str; text: str; weight: float; testability: str; lifecycle: str
    state: SupportState; S: float; S_raw: float; reasons: tuple[Reason, ...]; flags: tuple[Flag, ...]
    items: tuple[EvidenceQuality, ...]          # every item considered, usable or not
    best_link: dict[str, Any]                   # {"symbol_id", "l_cs", "l_st", "r_ct"} of the strongest path
@dataclass(frozen=True, slots=True)
class VerdictV2:
    analysis_id: str; head_sha: str; revision: int; verdict: Verdict; pending: bool
    reasons: tuple[Reason, ...]; criteria: tuple[CriterionVerdict, ...]
    uim: float; uim_numerator: float; uim_denominator: float; intent_coverage: float
    unlinked_symbols: tuple[str, ...]; tamper: tuple[TamperFindingInput, ...]
    justification: dict; algo_version: str; profile: str; config_digest: str; inputs_digest: str
    evidence_basis: str = "static_only"
```

---

## 4. Persistence plan

### 4.1 Principle: bundle first, projections later

The alpha stores one row per computation in `verdict_v2` with the **whole computed bundle** as JSON (Stage A input, Stage B outcomes, evidence items, `EvidenceQuality` rows, IEG nodes/edges, per-criterion results, justification). Reasons: Stage B must be re-runnable after CI without the repository, which needs Stage A's facts persisted anyway; one writer, one table, one idempotency key; the research hook (all intermediate values for ablations) is satisfied by the bundle; and it removes four migrations and four repositories from the critical path. The normalized tables of 4.3 are exact projections of the same dataclasses (column = field), written by a later projection step, so nothing is reworked when they land. Decision D1 asks the owner to confirm.

### 4.2 Alpha tables (migrations 0013 and 0014)

`verdict_v2` (model `VerdictV2Row`, module `radius_shared/database/verdict_v2.py`):

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | `UuidPrimaryKeyMixin` |
| `organization_id` | uuid fk `organizations.id` NOT NULL, indexed | tenant isolation; every repository method takes it first |
| `analysis_id` | uuid fk `analyses.id` NOT NULL, indexed | |
| `head_sha` | varchar(40) NOT NULL | |
| `revision` | int NOT NULL | 1,2,3...; `UNIQUE(analysis_id, revision)` |
| `inputs_digest` | varchar(64) NOT NULL | sha256 of canonical JSON of {Stage A input, Stage B input, config digest, algo versions}; no timestamps. `UNIQUE(analysis_id, inputs_digest)`: recomputing identical inputs is a no-op (idempotency) |
| `status` | varchar(16) NOT NULL | `ok` / `error` / `skipped` |
| `mode` | varchar(8) NOT NULL | `shadow` / `on` |
| `verdict` | varchar(24) NULL | `verified`...; NULL unless `status = ok` |
| `pending` | bool NOT NULL default false | |
| `reason_code` | varchar(48) NULL | decided-by reason, or error/skip code |
| `algo_version`, `profile`, `config_digest` | varchar | |
| `criteria_total/proven/weak/unevidenced/contradicted/excluded` | int | list/summary queries without parsing JSON |
| `uim`, `intent_coverage` | float NULL | |
| `bundle` | JSON NOT NULL | schema `verdict-v2-bundle-1`; capped at `max_bundle_bytes`, over-cap lists are truncated with counts and `truncated: true` |
| `justification` | JSON NULL | 3.9 |
| `error_detail` | text NULL | redacted (`redact_secrets`), max 2000 chars |
| `fallback` | varchar(8) NULL | `v1` when status is `error`/`skipped` and v1 was published |
| `published_at` | timestamptz NULL | |
| `published_digest` | varchar(64) NULL | digest of the rendered body last sent to GitHub; identical re-renders are not re-sent |
| `publish_error` | text NULL | |
| `computed_at`, `created_at` | timestamptz NOT NULL | not part of any digest |

`verdict_v2_requests` (model `VerdictV2RequestRow`; the outbox for republish after CI): `id`, `organization_id`, `analysis_id` (`UNIQUE`), `reason` (`ci_results` / `manual`), `requested_at`, `claimed_at` NULL, `claim_token` NULL, `attempts` int default 0, `last_error` text NULL. API upserts (`ON CONFLICT (analysis_id) DO UPDATE SET requested_at = now, claimed_at = NULL`); the worker claims with `FOR UPDATE SKIP LOCKED` (the same technique as `SqlAlchemyAnalysisJobQueue`), recomputes, and deletes the row only if `requested_at` is unchanged since the claim.

### 4.3 Beta projection tables (specified now, built later; not on the critical path)

| Table | Revision | Task | Columns (all also have `organization_id`, `analysis_id`, `run_id` uuid = the `verdict_v2.id` that produced them, `algo_version`, `created_at`) |
|---|---|---|---|
| `evidence_items` | 0015 | EV-01 | `evidence_id` varchar(24), `kind`, `source`, `head_sha`, `subject_id` text, `path`, `outcome`, `severity`, `rule_id`, `authored_by`, `independence_factor`, `independence_basis`, `flaky` bool, `freshness_f`, `features` JSON, `reasons` JSON. `UNIQUE(run_id, evidence_id)` |
| `evidence_quality` | 0016 | EV-08 | `evidence_id`, `criterion_id`, `a_static`, `d_mut` NULL, `d_eff`, `i`, `f`, `flaky_f`, `tamper_penalty`, `q`, `l_cs`, `l_st`, `r_ct`, `l`, `term`, `group_symbol`, `rank_in_group`, `contribution`, `status`. `UNIQUE(run_id, evidence_id, criterion_id)` |
| `ieg_nodes` / `ieg_edges` | 0017 | LK-05 | nodes: `node_id`, `kind`, `ref`, `attrs` JSON, `UNIQUE(run_id, node_id)`; edges: `edge_id`, `kind`, `src`, `dst`, `weight`, `method`, `reasons` JSON, `attrs` JSON, `UNIQUE(run_id, edge_id)`, indexes `(run_id, src)` and `(run_id, dst)`. Generic tables instead of `criterion_symbol_link`/`symbol_test_link`/`test_assertion` (LK-05 text): one builder, one writer, and new node/edge kinds (mutants, process events) need no migration. DESIGN's three named tables can be SQL views later |
| `criterion_support` | 0018 | VD-02 | `criterion_id`, `state`, `S`, `S_raw`, `weight`, `flags` JSON, `n_items`, `reasons` JSON. `UNIQUE(run_id, criterion_id)` |

Superseded runs are kept (DESIGN 3: each trigger creates a new assessment row; older rows retained). Retention beyond the 5 newest runs per analysis is a follow-up (QS-06).

### 4.4 Migration ordering rules

Latest revision on `develop` is `20261102_0012`. Revision ids are assigned here, per task, so no two PRs invent the same id, and the chain is created **once**:

1. VS-00 creates `20261102_0013_verdict_v2.py` (`down_revision = "20261102_0012"`) and `20261102_0014_verdict_v2_requests.py` (`down_revision = "20261102_0013"`) as no-op placeholders whose `upgrade`/`downgrade` are empty, so the chain exists before any owner starts.
2. VD-03 fills 0013 and the model; VS-07 fills 0014 and its model. Each task edits only its own file, so merge order does not matter and there are no rebase conflicts on `down_revision`.
3. Beta revisions 0015 to 0018 are reserved to EV-01, EV-08, LK-05, VD-02 in that order. They are created in numeric order by a single preparatory commit (`VS-B0`) that adds the chained placeholders, then each owner fills its own file.
4. Mutation (EV-04, the old "0013") and `trust_assessment` (old "0015") move to 0019 and later; the task files' numbers are superseded by this section.
5. Every migration has `downgrade`, a test that upgrades from the previous head, and an ORM/migration parity test like `packages/shared/tests/test_intent_migration.py`. New tables are covered by `test_database_metadata.py`'s `issubset` check, so that shared test needs no edit.

### 4.5 Tenant isolation and idempotency

Every table has `organization_id NOT NULL` with an index; repository classes take `organization_id` as the first argument and filter every query by it (the `IntentRepository` convention); a lookup of another organization's row behaves like a missing row. Required tests per table: tenant A cannot read or overwrite tenant B (the Definition of Done in IMPLEMENTATION_PLAN 1.4). API routes call `ensure_same_organization` through the analysis' repository (as `routes/confidence.py`). Idempotency keys: `verdict_v2 (analysis_id, inputs_digest)`, `verdict_v2_requests (analysis_id)`, `evidence_id`/`edge_id`/`node_id` (content hashes), and the published-body digest.

---

## 5. Orchestration

### 5.1 Two stages

```
analysis job (existing)                         worker apps/worker/src/radius_worker/runner.py::_run_claimed_job
  publish_in_progress (existing)
  ingest_intent_best_effort (existing, IN-02)
  orchestrator.execute(command)  -> v1 report saved                      [UNCHANGED]
  >>> NEW  verdict_v2.run_stage_a_b_best_effort(session_factory, analysis_id, command, settings)   (skipped when mode == off)
        Stage A  (needs the checkout)      -> StageAInput persisted in verdict_v2.bundle
        Stage B  (pure; DB outcomes only)  -> VerdictV2 persisted (status ok)
  _publish_github_result: mode == on and latest v2 status == ok  ->  publish v2   else  publish v1 (existing path)

CI upload (API process)                         POST /analyses/{id}/tests/results   [existing route]
  recalculate v1 (existing)
  >>> NEW  if mode != off: upsert verdict_v2_requests(analysis_id, reason="ci_results")     (one small edit, VS-07)

worker run_loop (existing poll)
  >>> NEW  verdict_v2.requests.process_pending(): claim -> Stage B on the latest ok Stage A bundle (no clone) -> persist -> publish if digest changed
```

### 5.2 Stage A: inputs and steps (`apps/worker/.../verdict_v2/collect.py`, `adapters.py`, `sources.py`)

| Input | How it is obtained | Existing API used |
|---|---|---|
| Intent snapshot, criteria, hints | `IntentRepository` latest snapshot of the analysis, criteria with lifecycle not `rejected`/`orphaned` | `radius_intent.interfaces.repository`, `infrastructure/sqlalchemy_repository.py` |
| Symbol changes | `extract_symbol_changes(base, head, diff)` as in `orchestrator._extract_symbol_changes` (`GitSnapshot` / `RefRange` from `ExecuteAnalysisCommand`) | `radius_analysis.symbol_changes` |
| Criterion to symbol | `radius_linking.infrastructure.pipeline.link_changeset(criteria_inputs(...), changeset, head, base, python_sources=...)` | `radius_linking` |
| Symbol to test | `StaticLinker().link(sources, targets)`, `NamingLinker().link(...)`, `combine_links(static, naming[, dynamic if produced])`; targets from `LinkTarget.from_changed_symbol` for non-test, non-`file` symbols | `radius_testing.linking` |
| Assertion features | `radius_testing.assertions.extract(sources)` for test files in the corpus (3.6) | LK-04 |
| Criterion to test | VS-04 `link_tests(criteria, test_docs, symbol_test_links, hints)` | VS-04 |
| Tamper | `analyze_tampering(changeset, base, head, TamperConfig(), diff_text=..., package_registry=...)`; registry lookups follow the egress policy (no network by default: T012 `registry_missing` needs a registry, otherwise `unverified_new_dependency` at medium, see fixture 06) | `radius_analysis.tamper` (EV-02) |
| Changed tests / agent signal | test ids that appear in the changeset; commit trailers from the `commit_message` intent sources already stored by IN-02 | `intent_sources` rows |
| Python sources | a safe reader with the symlink guard of `orchestrator._read_python_sources` (re-implemented in `sources.py`, not imported: it is private) | |

Stage A writes a `verdict_v2` row only after Stage B ran, so there is a single row per computation. If Stage A raises or exceeds `timeout_s`, the row is written with `status=error`, `error_detail` (redacted) and `fallback=v1`.

### 5.3 Stage B (`scoring.py`, pure function in `radius_evidence.application.pipeline`)

Inputs: the latest ok `StageAInput` from `verdict_v2.bundle.stage_a` (or the one just computed), plus from the DB: merged per-case outcomes from `test_result_uploads` (`list_result_uploads`, `merge_cases`: failed beats passed beats skipped, as v1), flaky ids from `TestRunResult.flaky_tests` and the history flakiness service (`docs/FLAKY_TESTS.md` section 3), `results_received`, `ci_failed_cases`. Steps: items -> IEG -> `EvidenceQuality` -> `S(c)` -> states -> `UIM`, `intent_coverage` -> rules -> `VerdictV2`. Output digest unchanged -> no new row. The Stage A input is stored in the bundle even when Stage B fails, so a later recompute (for example after a fix in Stage B code) does not need the checkout.

### 5.4 Failure isolation and fallback

Both stages run inside one `try/except Exception` in `run_stage_a_b_best_effort`, modeled on `ingest_intent_best_effort`: it opens its own session and transaction, never raises, never touches the v1 tables, and cannot fail the analysis job. Result codes: `ok`, `skipped` (reasons: `flag_off`, `no_intent_snapshot` is **not** a skip: it produces a real `insufficient_evidence: intent_missing_or_untestable` verdict), `error` (exception class name in `reason_code`, redacted message in `error_detail`). Soft budgets (`timeout_s`, `max_*` in 3.8) are checked cooperatively between steps; hitting one yields `degraded` entries (e.g. `truncated`) and rule R2d, not an exception. When mode is `on` and status is not `ok`, the publisher falls back to v1 and the v2 row records `fallback = v1` and the reason; the dashboard panel shows "v2 unavailable: <reason>". Logging: one structured `LOGGER.info` per run with `analysis_id`, `revision`, `verdict`, `uim`, `intent_coverage`, `duration_ms`, `status`, and counts only (no code, no intent text).

### 5.5 Republish after CI (VD-06 requirement) and the minimum needed

Minimum: (1) API: one call to `request_recompute(analysis_id)` in `ingest_test_results`, after `recalculate_from_test_results`, only when the API setting mode is not `off` (a single insert/upsert; no GitHub credentials, no network); (2) worker: `process_pending()` in `SqlAlchemyWorkerRuntime.run_loop` after the claim step; (3) publisher: update the existing Check Run and the existing comment in place (same `COMMENT_MARKER`, same Check Run name), skipping the PATCH when `published_digest` equals the new rendered digest. Latency is the worker poll interval (default 2 s) plus Stage B (pure, no clone). Superseded heads: the route already rejects uploads for a non-latest analysis (409, `_ensure_latest_for_pull_request`), so a request never targets a stale head; the worker re-checks the analysis is still the latest before publishing. Fork PRs: GitHub App tokens are used as for v1; permission limits are the v1 ones and are documented, not solved here.

---

## 6. Output surfaces

### 6.1 PR comment v2

Rules: same `COMMENT_MARKER` as v1 (`<!-- radius-confidence-report -->`) so a v1 comment is updated in place to v2 and vice versa (one comment per PR); a second hidden marker carries `rev` and body digest. Criterion text, test ids and snippets are **untrusted**: render them through `escape_md()` (escape `` ` `` `<` `>` `[` `]` `|` and line breaks; neutralize `@` mentions and `#123` / `GH-123` autolinks by wrapping in inline code; cap at 140 characters). Total body is capped at 60 000 characters (GitHub limit 65 536): tables truncate with "+N more, see the dashboard"; the Check Run `text` shares the body. Icons are renderer constants (`ICONS`), shown here as text.

Skeleton:

````markdown
<!-- radius-confidence-report -->
<!-- radius-verdict-v2 rev=<n> digest=<8 hex> -->
## Radius verdict (v2 alpha): <VERDICT LABEL>

**<proven> of <total> stated criteria proven** | unproven intent mass **<uim>** (limit <uim_max>) | intent coverage **<pct>%** | evidence: static assertion strength only (no mutation testing)

**Why:** <one sentence from the deciding rule, with ids>

| # | Criterion | State | Support | Evidence |
| --- | --- | --- | --- | --- |
| C1 | `<escaped text>` | PROVEN | 0.60 / 0.50 | 2 tests, strongest: exact value check |
...

### What to do next
1. ...

<details><summary>Tamper findings (<n>)</summary> ... </details>
<details><summary>Changed code with no stated criterion (<n>)</summary> ... </details>
<details><summary>Per-criterion evidence</summary> ... </details>
<details><summary>Legacy v1 signals (file-level selection, uncalibrated heuristic score)</summary> ... </details>

_Computed deterministically from validated evidence; no language model judged correctness. algo verdict-v2-alpha-1 | head `<sha7>` | [details](<dashboard url>)_
````

States are worded as: PROVEN, WEAK, UNPROVEN (state `unevidenced`), CONTRADICTED, EXCLUDED (reason shown), and flags as short tags (`tampered`, `flaky`, `unconfirmed`, `no test linked`).

### 6.2 Worked example: fixture 08 (`benchmarks/fixtures/intent/08_multi_criterion_partial_evidence`)

PR: "add `validate_password`" with four criteria, the two digit/length rules strongly tested, the uppercase rule tested only by `isinstance(..., bool)`, the common-password rule untested. Author supplied `.radius/intent.yml` `paths`/`tests` hints, so links are the "gold-bundle" ones (`l_cs = 1`, `r_ct = 1`); numbers below are the normative values of the formula (verified by hand, 3.9), `l_st = 0.9` (measured: LK-03 `direct_call`), tests added in the PR by an unknown author (`i = 0.8`), CI uploaded JUnit with all five tests passing.

````markdown
## Radius verdict (v2 alpha): Not verified - insufficient evidence

**1 of 4 stated criteria proven** | unproven intent mass **0.75** (limit 0.20) | intent coverage **100%** | evidence: static assertion strength only (no mutation testing)

**Why:** 3 of 4 criteria are below the support threshold 0.50 (C2, C3, C4), so the unproven intent mass 0.75 exceeds 0.20. All five tests passed, but passing is not enough: two of the criteria are checked weakly or not at all.

| # | Criterion | State | Support | Evidence |
| --- | --- | --- | --- | --- |
| C1 | `a password needs at least 8 characters` | PROVEN | 0.60 / 0.50 | 2 tests (boundary 7 and 8), exact-value checks |
| C2 | `a password needs at least one digit` | WEAK | 0.43 / 0.50 | 1 test: exact value, but one test alone stays under the threshold |
| C3 | `a password needs at least one uppercase letter` | UNPROVEN | 0.14 / 0.50 | 1 test: asserts only the return type (`isinstance(..., bool)`) |
| C4 | `a password must not be on the common-password list (case-insensitive)` | UNPROVEN | 0.00 / 0.50 | no linked test |

### What to do next
1. **C4**: no test checks the common-password rule. Add a test that a listed password is rejected, in a different letter case.
2. **C3**: `test_uppercase_rule_runs` would pass for any boolean result. Assert the exact value for a password without an uppercase letter.
3. **C2**: add a second case (for example a password with digits only), or a boundary case.

<details><summary>Per-criterion evidence</summary>

**C2** support 0.432 = 1 item. `test_rejects_missing_digit`: outcome passed; assertion strength 1.00 capped at 0.60; independence 0.80 (test added in this PR, author unknown); freshness 1.0; link symbol->test 0.90 (direct call); contribution 0.432.

</details>

<details><summary>Legacy v1 signals (file-level selection, uncalibrated heuristic score)</summary>

Verification status `insufficient_evidence`; heuristic confidence score (uncalibrated, not a probability) ...

</details>

_Computed deterministically from validated evidence; no language model judged correctness. algo verdict-v2-alpha-1 | head `4f2a9d1` | [details](https://dashboard.example/analyses/5b0b9c6e)_
````

Without hints, the same PR currently links C1 and C2 only weakly and C4 to nothing (measured values in 7.3: C1 0.497, C2 0.382, C3 0.119, C4 0): the verdict is the same, and the comment adds "no `tests:` hint and no lexical match: add a hint to `.radius/intent.yml`". That difference is the honest cost of lexical relevance (risk R2).

### 6.3 Check Run summary

Same name as v1 (`Radius confidence`, `CHECK_RUN_NAME`; required-check configurations keep working; D10). `title = "Radius v2: <label> (<proven>/<total> criteria proven)"`; `summary` = the first two bold lines of the comment; `text` = the full body; `details_url` = dashboard. Conclusions: `verified` -> `success`; `failed` -> `failure`; `insufficient_evidence` and `needs_review` -> `neutral`. A pending verdict (R2p) is published completed with `neutral` and title "Radius v2: awaiting CI test results", never left `in_progress`. Annotations on tamper findings need a client extension and are a follow-up.

### 6.4 API

New, additive route `GET /api/v1/analyses/{analysis_id}/verdict` (`routes/verdict_v2.py`). `GET /analyses/{id}/confidence` and its DTO are not changed. Response uses the standard `success_response` envelope; 404 with `meta.reason in {disabled, not_computed}` when absent.

```json
{ "success": true, "data": {
  "verdict_version": 2, "algo_version": "verdict-v2-alpha-1", "profile": "alpha-static", "mode": "on", "status": "ok",
  "analysis_id": "...", "head_sha": "4f2a9d1c...", "revision": 2, "computed_at": "2026-11-02T10:16:04Z",
  "verdict": "insufficient_evidence", "pending": false,
  "reasons": [{"code": "unproven_intent_mass", "rule_id": "R2b", "detail": "unproven intent mass 0.75 exceeds 0.20"}],
  "score": null, "score_kind": "none", "trust_probability": null,
  "summary": {"criteria_total": 4, "proven": 1, "weak": 1, "unevidenced": 2, "contradicted": 0, "excluded": 0,
              "uim": 0.75, "intent_coverage": 1.0, "tamper": {"critical": 0, "high": 0, "medium": 0, "low": 0}, "evidence_basis": "static_only"},
  "criteria": [ {"criterion_id": "c_2f6a11", "text": "...", "state": "proven", "S": 0.604, "S_raw": 0.604, "weight": 1.0, "flags": ["static_only"],
                 "reasons": [], "best_link": {"symbol_id": "...", "l_cs": 1.0, "l_st": 0.9, "r_ct": 1.0},
                 "items": [ {"evidence_id": "ev_...", "test_id": "...", "outcome": "passed", "a_static": 1.0, "d_eff": 0.6, "i": 0.8, "f": 1.0, "flaky_f": 1.0, "tamper_penalty": 0.0, "q": 0.48, "l": 0.9, "term": 0.432, "status": "counted"} ] } ],
  "tamper_findings": [], "unlinked_symbols": [],
  "next_actions": [{"criterion_id": "c_d3a2f7", "code": "no_linked_test", "text": "..."}],
  "justification": { "...": "3.9" },
  "v1": {"verification_status": "insufficient_evidence", "confidence_score": 31.0, "score_kind": "heuristic_uncalibrated", "risk_level": "high"},
  "dashboard_url": "..." } }
```

`score_kind` stays honest: v2 has no number to calibrate, so `score` is `null` and `score_kind` is `"none"`; the only score in the payload is the clearly labeled `v1` block copied from `confidence_reports` with its own `score_kind` (`CURRENT_SCORE_KIND`). `trust_probability` is reserved and stays `null` until calibration exists (CA-*). `docs/API_CONTRACTS.md` gets a section (VS-09); the OpenAPI schema is generated from `schemas/verdict_v2.py`.

### 6.5 Dashboard panel (extends IN-11)

Mounted under the Intent panel on the analysis detail page (`data-panels.tsx`, anchor `#verdict`), rendering nothing when the API returns 404/`disabled`. Contents: (1) header: verdict badge, deciding reason, tags `v2 alpha`, `static evidence only`, `shadow` when applicable, `pending CI`; (2) summary strip: proven/weak/unproven/contradicted/excluded counts, UIM bar with the `uim_max` marker, intent coverage; (3) criteria matrix: criterion text | state chip | support bar with the `tau_support` marker | evidence count | flags | expand; (4) expanded row: per evidence item the `q` factor bars (assertion strength, independence, freshness, tamper, flaky) and link chain (criterion -> symbol -> test with the three link weights and "why linked" reasons), failing/skipped tests; (5) tamper findings with rule id, severity, before/after snippet; (6) unlinked changed symbols; (7) next actions; (8) a collapsed "v1 result" comparison and a provenance footer (`algo_version`, `profile`, `config_digest`, `inputs_digest`, revision). The IN-11 criteria checklist (`components/intent-panel.tsx`) gains an optional prop `supportByCriterion` that shows the state chip beside each criterion. Security: all text is rendered as React text nodes only (the rule at the top of `intent-panel.tsx`); no markdown, no `dangerouslySetInnerHTML`. Accessible table, keyboard-expandable rows. Tests with `node --test` on `lib/verdict-v2.ts` (parsing, tolerant of unknown fields).

---

## 7. Work breakdown

Size: S under 1 day, M 1 to 3, L 3 to 5 (IMPLEMENTATION_PLAN 2). "Fakes" = the contract fixtures from VS-00/VS-01.

### 7.1 Tasks

| ID | Title | Depends on | Size | Owner files (section 2.3) | Acceptance (checkable) | Starts day 1 against |
|---|---|---|---|---|---|---|
| **VS-00** | Contract scaffold: `packages/evidence` (layers, `.importlinter`, package.json, CI PYTHONPATH and lint-imports step), contract dataclasses/enums/config/inputs (sections 3.1 to 3.8), `radius_confidence.verdict_v2.domain.model`, `radius_github.verdict_v2.view` (`from_payload`), DB module stubs registered in `radius_shared/database/__init__.py` and `migrations/env.py`, placeholder migrations 0013/0014, API router stub, dashboard mount, JSON schema validation test | none | M | all **C** rows, registration files | import-linter passes; every dataclass round-trips `to_dict/from_dict`; `verdict_v2.example.08.json` validates against `verdict_v2.schema.json` and parses with `VerdictV2View.from_payload`; chained migrations upgrade/downgrade on SQLite; stubs return 404 `disabled`; no behavior change with the flag off (existing test suites unchanged) | n/a (gate) |
| **VD-07-lite** | Flag `RADIUS_FEATURE_VERDICT_V2` (`off\|shadow\|on`, bool-compatible parsing) in worker and API settings, `.env.example`, `docs/DEPLOYMENT.md`, compose | none | S | config files | table-driven parse test (unset/false/0/off = off; true/1/on = on; shadow); v1 output byte-identical with the flag off (golden of an existing v1 comment test) | day 1 |
| **VS-01** | Golden stage bundles for the 8 fixtures: `benchmarks/fixtures/verdict_v2/<fixture>/{stage_a.gold.json, stage_b.json, expected.json}` (hand-authored from `expected.json` links, section 7.3 gold values) plus a loader | none (formats are in section 3.7) | M | `benchmarks/fixtures/verdict_v2/**` | each bundle validates against the DTOs; loader test; expected states/UIM/verdict equal the tables in 7.3; stage A auto-mode snapshots are added by VS-02 | day 1 |
| **LK-04** | Test assertion extraction (`radius_testing.assertions`, emits `AssertionFeatures` dicts incl. `name_terms`, `literal_terms`, `called_symbol_refs`) | LK-03 (done) | L | `packages/testing/.../assertions/**` | fixture per `AssertKind` (incl. `pytest.raises`, `unittest assertRaises`, `isinstance`, `is not None`, tautology `x == x`, no assertion, mock asserts, snapshot); the 8 fixtures' tests classify as in 7.2; property test: random test bodies never crash; deterministic output; ids equal `normalize_test_id` form | day 1 |
| **EV-06** | `a_static` (`strength.py`) | VS-00 contract | S | `domain/strength.py` | table in 3.6 as config; ranking test on the fixture tests (strong > weak > none) matches `expected.json` bands; property: monotone in each kind's score; tautology/no assertion = 0 | day 1 with hand-built `AssertionFeatures` |
| **EV-07** | Freshness (`freshness.py`): `f` by SHA binding; decay hook off by default | VS-00 | S | `domain/freshness.py` | unbound/other SHA -> 0 with reason; same SHA -> 1; unit tests; history of ignored items returned for audit | day 1 |
| **EV-03 (lite)** | Independence factor (`independence.py`) and the PR-level agent-trailer detector (pure function over commit message strings; patterns in config) | VS-00 | S | `domain/independence.py`; detector in `apps/worker/.../adapters.py` is VS-05's | pre-existing unchanged 1.0; changed+human 1.0; changed+agent 0.6; changed+unknown 0.8; patterns table-tested incl. `Co-Authored-By: Claude` and `[bot]` | day 1 |
| **EV-01** | Evidence item model, factories (`from_case`, `from_finding`), SHA-binding validation, `case_to_test_id` joiner. Alpha scope: model + (de)serialization; table 0015 is Beta | VS-00 | M | `domain/model.py` (content), factories in `domain/` + `application/` | unbound or non-40-hex SHA rejected; deterministic `evidence_id`; JUnit/JSON-case joins on the 8 fixtures' `test_outcomes`; malformed/oversized input rejected safely (fuzz) | day 1 |
| **EV-08** | `q(e,c)` combiner + `EvidenceQuality` + link mapping (`quality.py`) | VS-00 (+EV-06/07/03 interfaces) | M | `domain/quality.py` | golden hand-computed cases (3.5 and the values in 3.9); monotone in `a`, `i`, `f`, `l`; tamper high nullifies; flaky rerun nullifies; sensitivity script writes a table over `cap_static`, `tau`, `rho` (pre-reg sweeps) | day 1 with fake features |
| **LK-05** | IEG model + builder (`ieg.py`, `ieg_builder.py`), alpha scope in-memory + JSON; tables 0017 are Beta | VS-00 | L | `domain/ieg.py`, `application/ieg_builder.py` | invariants in 3.4; byte-identical for shuffled inputs; `paths(criterion)` on a 2k-node synthetic graph under 50 ms; no cross-analysis edges | day 1 with DTOs |
| **VS-04** | Criterion-to-test relevance (`radius_linking`): `test_doc.py`, `test_relevance.py`, hints | LK-04 contract (name/literal terms) | M | listed in 2.3 | deterministic; raw below `relevance_gate` creates no edge; `tests` hint -> weight 1.0; on fixture 08 every gold pair of C1/C2/C3 is found and C4 has none; a precision/recall report for all 8 fixtures against the gold `links[].tests` pairs, with the known misses listed (05 C2, 06 C2, part of 01 C1) and no target number invented before it is measured | day 1 with hand-built test docs |

| **VS-04** | Criterion-to-test relevance (`radius_linking`): `test_doc.py`, `test_relevance.py`, hints | LK-04 contract (name/literal terms) | M | listed in 2.3 | deterministic; raw below `relevance_gate` creates no edge; `tests` hint -> weight 1.0; on fixture 08 every gold pair of C1/C2/C3 is found and C4 has none; a precision/recall report for all 8 fixtures against the gold `links[].tests` pairs, with the known misses listed (05 C2, 06 C2, part of 01 C1) and no target number invented before it is measured | day 1 with hand-built test docs Status: implemented in `packages/linking` (`application/relevance.py`, `domain/relevance.py`, `scripts/relevance_eval.py`, branch `feature/linking-criterion-test-relevance`); differs from 3.6 by using a multi-signal rule (normalised BM25 + assertion anchors + name + hints + penalties) instead of a raw BM25 gate; fixture-sanity numbers in the linking README. |
| **VD-01** | `S(c)` (`support.py`) | VS-00 | M | `domain/support.py` | formula 3.9; hand-computed goldens (0.432, 0.604, 0.734, 0.180, 0.283); properties: `S` in [0, `s_cap`], monotone in `q` and `l`, `S = 0` with no items, order-independent, deterministic; `rho` and `s_cap` configurable; all intermediates returned | day 1 with fake `EvidenceQuality` |
| **VD-02** | States, flags, UIM, intent coverage (`states.py`) | VD-01 interface | M | `domain/states.py` | the 7-row state table and every transition tested; UIM weights and exclusion; intent coverage cases incl. `<module>` same-file rule and `<file>` exclusion; fixtures reproduce the 7.3 gold states | day 1 with fake `SupportResult` |
| **VD-03** | Verdict rules R1 to R4, justification tree, `VerdictV2` store (`radius_confidence.verdict_v2`), migration 0013 | VS-00 | L | `verdict_v2/**`, `database/verdict_v2.py`, migration 0013 | rule-order table tests (each rule fires alone and in combination, first fired decides); tree schema-valid; every `refs` id exists; reproducible from stored bundle (`compute` equals stored); tenant isolation; idempotent on `(analysis_id, inputs_digest)` | day 1 with fake `CriterionVerdict`s |
| **VS-03** | Pure Stage B pipeline (`application/pipeline.py`) wiring EV-01/03/06/07/08, LK-05, VD-01/02/03 | EV-01, EV-03, EV-06, EV-07, EV-08, LK-05, VD-01, VD-02, VD-03 | M | `application/pipeline.py` | on the VS-01 gold bundles the output equals `expected.json` (7.3) to 3 decimals; the 8 PR verdicts; byte-identical on repeat and under input shuffling; < 200 ms per fixture | after wave 1 |
| **VD-06** | `radius_github.verdict_v2`: `markdown.py` (renderer, escaping, truncation), `publisher.py` (create/update Check Run and comment in place, digest skip) | VS-00 (`VerdictV2View`) | L | listed in 2.3 | snapshot tests of the markdown for the 8 fixtures from `verdict_v2.fixture_expectations.json`-derived payloads (including the 6.2 example); injection tests (`@everyone`, `<script>`, `](http://x)`, `#1`, 10 kB criterion); size cap; fake client: one comment total, updated in place across v1 -> v2 -> v2 | day 1 with the example payload |
| **VS-05** | Stage A worker collector, adapters, runner hook, persistence of the `StageAInput` | LK-05, LK-04, VS-04, EV-02 merged, VD-07-lite, VS-00 | L | `verdict_v2/{collect,adapters,sources}.py`, runner hook | produces a `StageAInput` for each of the 8 fixtures through the real LK-01/02/03/04/VS-04/EV-02 code (auto mode snapshot recorded); flag off = hook not called; any exception -> status `error`, job unaffected (tested by injecting a failing linker); symbol-id equality LK-02/LK-03 asserted | after wave 1 + EV-02 |
| **VS-06** | Stage B worker: DB outcomes -> pipeline -> persist, fallback/status, flaky inputs | VS-03, VD-03, VS-05 | M | `verdict_v2/{scoring,store}.py` | integration test on SQLite: outcomes from stored `test_result_uploads` produce the same verdict as the pure pipeline; no results -> R2p pending; second identical run -> no new row; failure -> `error` row and v1 untouched | wave 2 |
| **VS-07** | Republish-after-CI: API enqueue (one edit in `routes/tests.py`), `requests.py` consumer in `run_loop`, migration 0014 | VS-06, VD-07-lite | S | listed in 2.3 | upload via the API test client creates exactly one request row (replays collapse); worker recomputes without cloning; stale (non-latest) analysis is not published; no change when the flag is off | wave 2 |
| **VS-08** | Worker publish switch (v2 vs v1 vs shadow) and republish tracking (`published_digest`) | VD-06, VS-06 | S | `verdict_v2/publish.py`, branch in `_publish_github_result` | mode matrix test (off/shadow/on x ok/error): on+ok publishes v2 only; on+error publishes v1 and records `fallback`; shadow publishes v1; publish failure does not fail the job (existing behavior) | wave 3 |
| **VS-09** | API route, schemas, API_CONTRACTS section | VS-00, VD-03 | M | listed in 2.3 | OpenAPI schema matches `verdict_v2.schema.json`; org isolation test (other org -> 404); flag off -> 404 `disabled`; `/confidence` response byte-identical to before | day 1 with an in-memory store |
| **VS-10** | Dashboard panel and intent-panel chip | VS-00 | M | listed in 2.3 | node tests for `lib/verdict-v2.ts` (all fixtures' payloads, unknown fields tolerated, 404 hides); text-only rendering test (script string in a criterion stays text); lint and build pass | day 1 with the example payload |
| **VS-02** | Vertical-slice acceptance test (7.3): fixtures end to end in two modes (gold bundles and auto), plus DB-backed run with a fake GitHub client | VS-03 (gold), VS-05/06/08 (auto, DB) | M | `tests/test_verdict_v2_fixtures.py` | the matrix in 7.3 holds; gold mode asserts states/S/UIM/verdicts exactly; auto mode asserts the 8 PR verdicts exactly and records criterion states as a reviewed snapshot (diffs need review); flag off run leaves v1 comment identical | wave 3 |

EV-02 (tamper) is an existing task on branch `feature/evidence-tamper-rules`; it must be merged before VS-05/VS-02 auto mode. Everything else works against fakes before it merges.

### 7.2 Order, parallelism and critical path

```
day 0       VS-00 (gate, M) ........ VD-07-lite (S) in parallel, independent
wave 1      (all parallel, day 1 on)  LK-04 L | LK-05 L | VD-03 L | VD-06 L | VS-04 M | EV-01 M | EV-08 M | VD-01 M | VD-02 M
            VS-09 M | VS-10 M | VS-01 M | EV-06 S | EV-07 S | EV-03-lite S        (EV-02 merge happens in parallel)
wave 2      VS-03 M (needs EV-*, LK-05, VD-01..03)  |  VS-05 L (needs LK-04, LK-05, VS-04, EV-02)  ->  VS-06 M  ->  VS-07 S
wave 3      VS-08 S (needs VD-06, VS-06)  ->  VS-02 M (acceptance)
critical path: VS-00 -> LK-04 -> VS-05 -> VS-06 -> VS-08 -> VS-02   (about 1.5 + 4 + 3 + 2 + 1 + 2 = 13 working days with enough agents)
```

Cut lines: **Milestone A** (pure, no DB/GitHub): VS-00 + wave 1 domain tasks + VS-03 + VS-01 + the gold half of VS-02; demonstrable as a script printing the verdict and the markdown for the 8 fixtures. **Milestone B** (persisted + API + dashboard): + VD-03 persistence, VS-05, VS-06, VS-09, VS-10. **Milestone C** (visible in the PR, updated after CI): + VS-07, VS-08, VD-06 live. The dashboard (VS-10) can trail Milestone C without blocking it.

### 7.3 End-to-end acceptance scenario on the 8 F-14 fixtures

Two modes. **Gold mode** (normative): inputs are the VS-01 bundles built from each `expected.json` (`links[].tests` as `ADDRESSED_BY` edges with weight 1.0, `l_cs = 1`, `l_st = 0.9`, `a_static` from the test code as in 7.2, outcomes from `test_outcomes.head`, tamper from `tamper_findings` with the EV-02 severities, tests added in the PR with unknown author). Values are exact to 3 decimals and test the VD formulas in isolation from linking quality. **Auto mode**: real LK-01/02/03/04, VS-04 and EV-02 on the fixture repositories; the PR verdict must equal the expectation; per-criterion states are a reviewed snapshot because they depend on linking quality. Auto-mode numbers below were measured with a prototype of the formula on the real LK-02/LK-03 outputs (relevance corpus = all test functions of the fixture head); the implementation may differ in the last digits.

`a_static` used (from the test bodies): value equality 1.0 (all `expected.json` "strong" value checks), `pytest.raises(ValueError)` 0.8, `is not None` and bare truthiness 0.25, `<= hi` and `in range(...)` 0.35, `isinstance` 0.20, `x == x` 0.0. Config: alpha-static (`cap_static` 0.6, `tau_support` 0.5, `rho` 0.7, `i` 0.8 for tests added in the PR).

| Fixture | `expected.json` criterion states | Gold mode states (S) | Auto mode states (S) | UIM gold / auto | Intent coverage | Rule that decides | PR verdict (expected, both modes) |
|---|---|---|---|---|---|---|---|
| 01 correct, strong tests | C1 proven, C2 proven | proven (0.734), proven (0.604) | proven (0.734), proven (0.688) | 0 / 0 | 1.00 | R4 | `verified` (matches `expected_verdict`) |
| 02 correct, weak tests | C1 weak, C2 unevidenced | weak (0.283), unevidenced (0.000) | weak (0.225), unevidenced (0.157) | 1.0 / 1.0 | 1.00 | R2b | `insufficient_evidence` |
| 03 incorrect, passes weak tests | C1 weak, C2 unevidenced, C3 weak | weak (0.252), unevidenced (0.144), weak (0.252) | weak (0.252), unevidenced (0.000), weak (0.290) | 1.0 / 1.0 | 1.00 | R2b | `insufficient_evidence` (never `verified` for a wrong PR; `failed` is not derivable from the shipped tests) |
| 04 test tampering | C1 weak, C2 unevidenced, C3 unevidenced | all unevidenced (0.000) | all unevidenced (0.000) | 1.0 / 1.0 | 1.00 | R1c (T001, T002, T004, T005 high) | `failed` |
| 05 scope creep | C1 proven, C2 proven | proven (0.604), proven (0.688) | weak (0.336), unevidenced (0.000) | 0 / 1.0 | 0.33 (1 of 3 behavioral symbols) | R2c in gold mode; R2b and R2c in auto | `insufficient_evidence` |
| 06 hallucinated dependency | C1 proven, C2 proven | proven (0.688), proven (0.604) | proven (0.604), unevidenced (0.000) | 0 / 0.5 | 1.00 | R1c (T012 `registry_missing` high, needs an offline `StaticPackageRegistry` that lacks `pytimeparse-ultra`) | `failed`; with no registry available T012 is `unverified_new_dependency` (medium) and the verdict is `needs_review` via R3a |
| 07 vague intent | C1 excluded, C2 unevidenced | excluded, unevidenced (`needs_typed_evidence`) | same | 1.0 / 1.0 (over C2 only) | 1.00 | R2a | `insufficient_evidence` (`intent_missing_or_untestable`) |
| 08 multi-criterion partial | C1 proven, C2 proven, C3 weak, C4 unevidenced | proven (0.604), weak (0.432), unevidenced (0.144), unevidenced (0.000) | weak (0.497), weak (0.382), unevidenced (0.119), unevidenced (0.000) | 0.75 / 1.0 | 1.00 | R2b | `insufficient_evidence` |

All 8 PR verdicts match `expected_verdict` in both modes (the 06 offline variant noted). Machine-readable version: `verdict_v2.fixture_expectations.json`.

**Disagreements with the fixtures' `expected.json`, stated honestly (each needs an owner decision; none changes a PR verdict):**

1. **04 C1** expected `weak`, formula gives `unevidenced`. The weak test (`is not None`) is the one T004 flags at high severity, and DESIGN 6.3 says a high finding nullifies `q`. Recommend updating the fixture to `unevidenced` and adding the flag `tampered` to its expectations. (The tamper severities in the fixture are labeled `assumed_severity` until EV-02's decision, D12.)
2. **08 C2** expected `proven`, gold mode gives `weak` (0.432): with `cap_static 0.6` one static-only test cannot reach 0.5. Recommend the fixture schema gain `expected_state_by_profile` (`alpha-static`: weak, future `mutation`: proven), rather than lowering thresholds to fit one fixture.
3. **08 C3 vs 03 C2**: both are `isinstance`-only tests; one is labeled `weak`, the other `none`. The alpha scores `type_check` 0.20 and gives `unevidenced` to both. Recommend relabeling 08 C3 to `unevidenced`.
4. **05 C2 and 06 C2 (auto mode)**: the lexical relevance finds no test (criterion words do not appear in the test names). Expected `proven`, auto gives `unevidenced`. This is the documented limit of VS-04 (risk R2); gold mode covers the formula, and the `tests:` hint closes the gap in practice.
5. **05 symbol naming**: `expected.json` names `src/config.py::REQUEST_TIMEOUT_SECONDS`; LK-01 reports module-level constants as the pseudo-symbol `src/config.py::<module>`. The acceptance test compares through the `<module>` mapping.
6. **02 C2 (auto)**: a spurious lexical link (`address`) gives the weak test `test_normalize_handles_plain_address` credit 0.157 for the "without `@` raises ValueError" criterion that has no test; the state is still `unevidenced` (below 0.2) but the link is wrong. Gold has none. Tracked under R2.
7. **04 tamper `file` vs finding ids**: `expected.json` lists tamper findings by rule and test; the acceptance test matches on (`rule_id`, `test_id` or path), not on `finding_id`.
8. **06 T012** requires registry lookups (`registry_missing`); production egress is policy-controlled (DEC-021), so the `failed` outcome needs the lookup enabled; offline it degrades to `needs_review` (above).

### 7.4 Merge sequencing for the few shared files

`runner.py` is edited by VS-05 (hook, after `orchestrator.execute`) and VS-08 (publish branch); VS-08 starts after VS-05 merges. `routes/tests.py` is edited only by VS-07. `config.py` (worker and API) only by VD-07-lite. `data-panels.tsx`, `main.py`, `database/__init__.py`, `env.py`, `ci.yml` only by VS-00. Every other path has exactly one owner (2.3). The EV-02 branch edits `orchestrator.py`, `config.py` (tamper flag) and `runner.py` (one line); it must merge before VS-05 and VD-07-lite rebase onto it, which is an ordinary rebase of three small hunks.

---

## 8. Risks and open decisions

### 8.1 Risks

| ID | Risk | Mitigation in this design |
|---|---|---|
| R1 | Criterion-to-symbol links are rank-calibrated, not probabilities (finding F5). | Saturating gate (3.5), `intent.yml` hints saturate, `low_link_confidence` flag and rule R3c; LK-06 calibrates later. |
| R2 | Lexical criterion-to-test relevance is weak and corpus-sensitive (measured, 3.6). False credit or missed credit. | Hard gate (no credit without an edge), hint-first UX, `no_linked_test` action, gold-mode acceptance, measurement report in VS-04; semantic linker is a follow-up. False safety is worse than a missed link, hence the gate. |
| R3 | Test id joins between JUnit (`classname`, `file`, `name`) and AST ids can fail (parametrization, nested classes, unittest). | `case_to_test_id` with `normalize_test_id`; unmatched failed cases still trigger R1b; join statistics logged and shown (`unmatched_cases`). |
| R4 | EV-02 is not merged; the worker files it edits overlap with ours. | Section 7.4; everything else is built against fakes. |
| R5 | Untrusted text (criterion text, test names, snippets) flows into a PR comment: mention spam, link injection, markup. | `escape_md`, length caps, injection tests in VD-06; dashboard text-only. |
| R6 | Comment and Check Run size limits (65 536). | 60 000 cap, truncation with counts, details collapsed. |
| R7 | Static-only `verified` can still be wrong (a "strong" test that cannot fail). | Cap 0.6, `rho`, `s_cap`, label "static assertion strength only", `strong_min`; mutation (EV-04) is the real answer and is the next milestone. |
| R8 | Cost: Stage A re-runs LK-01 and links tests; large repos. | `max_*` budgets, `degraded` -> R2d, per-process cache, only Python files parsed. |
| R9 | Concurrency: CI upload and analysis finishing at the same time. | `inputs_digest` idempotency, `UNIQUE(analysis_id, revision)`, claim token, latest-analysis re-check before publishing. |
| R10 | Alpha parameters tuned by eye on 8 hand-written fixtures. | Fixtures are examples, not validation; the alpha profile is labeled and versioned; pre-registered tuning happens later on the dev split (PREREGISTRATION 2.2 rule 8). |

### 8.2 Open decisions (each with a recommendation)

| ID | Decision needed | Recommendation |
|---|---|---|
| D1 | Normalize tables now or bundle JSON first (4.1)? | Bundle first; normalized tables as Beta projections. Cuts four migrations from the critical path, no rework. |
| D2 | Use the `alpha-static` profile (cap 0.6, tau 0.5) instead of DESIGN defaults (0.4, 0.6)? | Yes, labeled as a profile with its own `algo_version`; both values are in the pre-registered sweep grid; DESIGN defaults stay available as a second profile. Under DESIGN defaults nothing is `proven` and no PR is `verified`. |
| D3 | Add a sixth criterion state `tampered`/`partially_evidenced`? | No. DEC-008 stays; `tampered` is a flag, `weak` covers partial. |
| D4 | `needs_review` reachable in the alpha only through R3a to R3c (policy triggers)? | Yes, as VD-03 states; calibration-based abstention arrives with CA-04. |
| D5 | May the alpha emit `verified` (green check) from static evidence alone? | Yes, with the visible label "static assertion strength only"; strictness comes from UIM, coverage and tamper rules. Alternative: cap at `neutral` until mutation exists. |
| D6 | Relevance method: lexical now, embeddings later? | Lexical plus `tests:` hints now; embedding linker only after the VS-04 measurement shows the need. |
| D7 | Worker-run (sandbox) results have no per-case outcomes (F3). | Alpha supports CI-uploaded per-case results only; a follow-up stores per-case sandbox outcomes. State it in the comment ("per-test results required"). |
| D8 | Meaning of "coverage" in rule 2 (3.9 intent coverage) and the `<module>` same-file rule. | As defined; revisit when LK-05 blast-radius candidates exist. |
| D9 | Republish transport: outbox + worker consumer, or give the API App credentials? | Outbox. The API holding no GitHub credentials is a deliberate property (`docs/CI_INTEGRATION_GUIDE.md`). |
| D10 | Keep the Check Run name `Radius confidence` and the comment marker? | Yes: branch protection and the in-place update keep working. |
| D11 | Non-Python behavioral changes. | `insufficient_evidence: analysis_degraded` (R2d); TypeScript arrives with EV-14. |
| D12 | EV-02 severities for T001, T002, T004, T005, T012 are `assumed_severity: high` in the fixtures; `fail_on_tamper_at_least = high` depends on them. | Owner confirms the severity table when merging EV-02; R1c reads severity from the engine, never hard-codes rule ids. |
| D13 | Authorship is `unknown` by default (i = 0.8), `agent` only from commit trailers (0.6). | Accept for the alpha; full authorship (EV-03) later. Note this under-weights agent PRs that lack trailers. |
| D14 | Record DEC-027 for: `packages/evidence` creation, sub-package placements, alpha profile, bundle-first persistence. | Yes, in VS-00's PR. |
| D15 | Flag is three-valued (`off\|shadow\|on`) rather than boolean. | Yes (VD-07's shadow mode is a stated goal); boolean spellings stay valid. |
| D16 | Generic `ieg_nodes/ieg_edges` instead of the three named link tables. | Generic; named tables as views if needed. |
| D17 | The pre-registration's UIM is defined on the full pipeline; the alpha's differs by profile. | Keep `profile` on every stored result; never pool alpha-static results with confirmatory data; the pre-registration is a draft and may add the profile as an amendment before freeze. |

---

## 9. Definition of done for the slice

With `RADIUS_FEATURE_VERDICT_V2=on`, a pull request that has an intent snapshot and a CI-uploaded JUnit report gets, within one worker poll interval of the upload, one PR comment and one Check Run showing per-criterion states, the unproven intent mass, tamper findings and next actions; the same payload is served at `GET /analyses/{id}/verdict` and shown in the dashboard; with the flag off every existing test passes unchanged and the published v1 comment is byte-identical; a v2 failure leaves the v1 result published and records why; and `tests/test_verdict_v2_fixtures.py` passes in both modes on all 8 fixtures.
