# Decisions

This file records project-level decisions that should guide implementation.

## DEC-001: Radius is the canonical product name

Radius replaces the earlier ShipSafe naming in README and developer-facing documentation. Future code, folders, APIs, UI copy, and docs should use Radius.

## DEC-002: Uppercase docs are the source of truth

The substantive documents such as `PROJECT_OVERVIEW.md`, `PHASE1_SPECIFICATION.md`, `MODULE_ARCHITECTURE.md`, `DATABASE_DESIGN.md`, and `API_CONTRACTS.md` are canonical. Lowercase legacy files remain only as compatibility pointers.

## DEC-003: Phase 1 package scaffold follows domain boundaries

The Phase 1 package layout is:

- `repository`
- `parser`
- `graph`
- `analysis`
- `testing`
- `confidence`
- `shared`

Earlier placeholder packages that represented future or implementation-specific concerns are removed until a documented phase requires them.

## DEC-004: Phase 1 pipeline order

The Phase 1 execution pipeline is:

1. Receive GitHub event or manual analysis trigger.
2. Synchronize the repository.
3. Analyze the Git diff to identify changed files.
4. Parse source files and extract semantic metadata.
5. Build or update the dependency graph.
6. Compute changed symbols and blast radius.
7. Select and execute relevant existing tests.
8. Generate an explainable confidence report.
9. Publish results through the API, dashboard, and GitHub Check.

The diff step may run before parsing to limit work, but deterministic parsing and graph data remain the foundation for impact analysis.

## DEC-005: Branching model

Radius uses an enterprise promotion flow:

```text
feature/* -> develop -> dev -> main
```

- `feature/*` branches are short-lived branches for isolated implementation work.
- `develop` is the active development integration branch.
- `dev` is the UAT branch. Feature branches must not merge directly into `dev`.
- `main` is the release branch and contains only release-ready code.
- `release/*` branches are optional and used only for named release stabilization.
- `hotfix/*` branches start from `main`, then merge back into `main`, `dev`, and `develop`.

This gives Radius a controlled promotion path while keeping feature work isolated before UAT.

## DEC-006: Research core is intent-to-evidence verification

Ratified: owner sign-off 2026-11-02.

The next phase of Radius is built around one question per pull request: for each stated intent (criterion), how much trustworthy evidence is there that it holds, and how much do we trust that evidence? Intent sources become atomic criteria, criteria are linked to symbols and tests in the Intent-Evidence Graph, and evidence is weighted by how likely it would have failed if the code were wrong (mutation, assertion strength, independence, freshness). The authoritative plan is `docs/research/` (`DESIGN.md`, `IMPLEMENTATION_PLAN.md`, `EVALUATION_PLAN.md`, `PRODUCT_AND_GTM.md`, `tasks/`). All formulas, weights and thresholds there remain hypotheses to be tested by the evaluation plan. Radius still verifies code and does not generate it. Source: F-01.

## DEC-007: New research packages are justified under DEC-003

Ratified: owner sign-off 2026-11-02.

DEC-003 removed placeholder packages "until a documented phase requires them". `docs/research/DESIGN.md` section 4.1 is that documented phase. The following packages may be added, each only when its first task starts and following the existing domain / application / infrastructure / interfaces layering: `packages/intent`, `packages/evidence`, `packages/mutation`, `packages/tamper`, `packages/trajectory`, `packages/calibration`, `packages/triage`, `packages/policy`. Existing `packages/testing` and `packages/confidence` stay. Creating a package without a task that needs it is still not allowed. Source: F-01.

## DEC-008: Verdict v2 has four states, including needs_review

Ratified: owner sign-off 2026-11-02.

Verdict v2 states are `verified`, `failed`, `insufficient_evidence` and `needs_review` (`DESIGN.md` section 6.5). `needs_review` is the abstention state: the system declines to decide and a human must (calibrated probability inside the abstention band, process signals above threshold, or a confidence interval that is too wide). It is a distinct fourth state and is not mapped into `insufficient_evidence`. Per-criterion states are `proven`, `weak`, `unevidenced`, `contradicted` and `excluded`. The v1 confidence output stays available behind a feature flag until v2 is the default. This resolves open decision 2 (DESIGN section 11), which is the recommended option in DESIGN. Source: F-01.

## DEC-009: LLM governance: the LLM proposes, evidence disposes

Ratified: owner sign-off 2026-11-02.

LLMs may propose (split or normalize criteria, verify links) and may polish explanations, always flag-gated. They never compute or influence a verdict or score: verdicts are deterministic from validated evidence. Every LLM output is schema-validated and span/quote-verified, source text (PR, issue, trace) is treated as untrusted data, the model receives no tools, and every call is logged (`llm_call_log`) with model and prompt versions. Calls go through a provider abstraction with caching, a per-org cost cap, a local-model option, secret/PII redaction, and a policy switch to disable code egress. Source: `DESIGN.md` sections 1 and 7; F-01.

## DEC-010: Default branch is develop (open decision 1)

Ratified: owner sign-off 2026-11-02.

The GitHub default branch becomes `develop` (it is currently `dev`), so new pull requests target the integration branch by default. This is the explicitly recommended option in task F-04. It refines DEC-005: the promotion flow is unchanged (`feature/*`, `fix/*`, `docs/*` -> `develop` -> `dev` -> `main`) and nobody commits directly to `dev` or `main`. Applying the setting is done by the owner after the F-04 docs merge. Source: F-01, F-04.

## DEC-011: Probe/test generation (EV-12) is deferred (open decision 3)

Provisional default (owner may revisit). The owner signed off the ratification set on 2026-11-02, but the docs contain no recommendation for this item, so the conservative option is recorded.

Decision: Radius does not generate tests or probes now. EV-12 stays a stretch task and is not started. If it is later allowed, the rules already written in EV-12 apply: probes are verification artifacts stored in Radius, never committed to the user's repo, labelled "generated", and counted with a lower independence factor `i(e)`. Reason: "Radius does NOT generate code" is a core principle in `docs/AI_CONTEXT.md`, and EV-12 itself says it needs an explicit decision. Revisit when: EV-04 (mutation) is done and the M4 gate has passed, or a design partner asks for it. Source: F-01.

## DEC-012: Open-source strategy and license are undecided; no license granted yet (open decision 4)

Provisional default (owner may revisit). The docs give no recommendation: PL-09 and QS-13 are the tasks that decide, and `PRODUCT_AND_GTM.md` only sketches a direction (open rule packs and benchmark, self-hostable, paid managed sandbox and SSO).

Decision: the working assumption is an open-core split (open: core engine, rule packs, benchmark, schemas; hosted/paid: managed sandbox, dashboards, SSO), but no license is chosen and none is added now (the repo has no LICENSE file). Until PL-09/QS-13 complete, no code or rules from other projects are copied (Verik is Apache-2.0; AgentProof and SlopGate licenses are unconfirmed). Revisit when: before any public release, external contributor, or design-partner code sharing; at the latest when QS-13 starts. Source: F-01.

## DEC-013: First language is Python (pytest), second is TypeScript (open decision 5)

Ratified: owner sign-off 2026-11-02.

Taken from the plan's explicit statements: `DESIGN.md` section 10 ("No language beyond Python (first) and TypeScript (second) until the evaluation shows value") and F-09 (Python first via stdlib `ast`, TypeScript second via a real parser). First test framework: pytest (the project's stated test stack in `docs/AI_CONTEXT.md`; EV-02 rules target pytest markers; EV-04 starts with `mutmut` and/or `cosmic-ray`). Jest/Vitest and Stryker follow with EV-14. Go/Java/Rust parsers stay experimental. Source: F-01, F-09.

## DEC-014: Calibration labels start from public benchmarks, then own history (open decision 6)

Provisional default (owner may revisit). The docs fix the order only ("Benchmark labels first (EP-03), revert/SZZ pipeline (CA-01)") and list label sources in CA-01; they do not choose between own history plus partners and public data only.

Decision: start with public OSS and benchmark data (SWE-bench-style datasets, Radius' own mutation benchmark, revert and SZZ-style labels mined from public repositories). Customer or design-partner repository history is not used for labels until a partner opts in explicitly in writing and QS-06 (retention/privacy) is done. Until `n_labels` passes the minimum, the UI says "uncalibrated prior". Revisit when: the first design partner is onboarded (PL-06) or CA-09 shows public labels are too noisy or too few. Source: F-01.

## DEC-015: LLM features are opt-in and code stays in the customer's environment by default (open decision 7)

Provisional default (owner may revisit). The docs specify the mechanisms (provider port for Gemini, Anthropic, OpenAI-compatible and local/Ollama in IN-04; per-org enable flag; policy to disable code egress; redaction) but name no default provider or egress stance.

Decision: all LLM-assisted features are off by default (feature flag plus per-org enable). By default no source code leaves the deployment; only redacted intent text (PR body, issues, commit messages) may be sent, and only to a provider the org configured. Code-bearing prompts (for example link verification quoting code spans) require the org to enable code egress explicitly, or use a local model. No default hosted provider is chosen; the first provider implemented is picked in IN-04. Revisit when: IN-04 starts, or a design partner requires a specific provider or air-gapped mode. Source: F-01.

## DEC-016: Leave the empty test commit c2d5db6 on dev

Ratified: owner decision 2026-11-02 (task F-16).

Commit `c2d5db6` ("test: verify commit identity for Mohith-c7") is an empty commit that exists on `dev` only. Decision: leave it. It will reach `main` naturally when `dev` is next promoted to `main` in a release (and `develop` if `dev` is ever merged back, as in the hotfix flow of DEC-005). Do not force-push `dev`, and do not add a revert.

Rationale: the commit changes no files, so it is harmless. A revert would be another empty commit and only add noise to history, and a force-push would rewrite a shared protected branch and break the "never force-push" rule in `docs/github-branch-protection.md`. Revisit if we ever need a clean `main` history (for example for an audit or a public release), at which point the options are a documented exception or a rebuilt release branch agreed by the owner. This also reinforces the rule in DEC-005 and `docs/DEVELOPMENT_GUIDE.md`: never push test or throwaway commits to `dev` or `main`.

## DEC-017: JS/TS parsing uses tree-sitter; Go/Java/Rust are experimental

Context (F-09): JS/TS were read with line-based regexes, which cannot see
comment/string context, multi-line statements, dynamic `import()` forms or
symbol ranges, and tsconfig `paths` were merged repository-wide.

Decision:

- Python stays on the stdlib `ast` module (first-class language).
- TypeScript and JavaScript are parsed with **tree-sitter** via the
  `tree-sitter`, `tree-sitter-typescript` (pinned `==0.23.2`) and
  `tree-sitter-javascript` (pinned `==0.25.0`) wheels. Reason: the project
  already ships tree-sitter for Go/Java/Rust, the wheels are prebuilt for
  Windows and Linux (CPython 3.12 abi3), parsing is in-process and
  deterministic, and the tree is error-tolerant so syntax errors are detectable
  (`has_error`) and reported as `parse_failures`.
- Rejected: the **TypeScript compiler API**. It gives full type information but
  needs a Node runtime and a subprocess/IPC boundary in the worker, adds a
  second dependency toolchain to the sandboxed deployment, and Radius only needs
  syntax-level facts plus path resolution, which is decidable without a type
  checker.
- Import resolution for JS/TS lives in `radius_graph.infrastructure.ts_resolver`
  (nearest `tsconfig.json`/`jsconfig.json` per file, `extends` chains, `baseUrl`,
  `paths`, extension and `index` resolution). Unresolved or bare specifiers are
  classified external, never errors.
- The regex import extractor survives only as `regex_import_fallback`, used when
  a grammar wheel cannot be loaded; it is logged at ERROR level and is not on the
  default path.
- Go, Java and Rust parsers are unchanged but marked **experimental**
  (`EXPERIMENTAL_LANGUAGES`, parser `experimental = True`, warning log and
  `RepositoryParseResult.experimental_languages`). They do not resolve imports to
  files.

Consequences: JS/TS files with unsupported syntax (for example Flow) become
parse failures, which lowers confidence instead of silently under-reporting
dependencies. Workspace package-name resolution and package `exports` are
follow-ups.
