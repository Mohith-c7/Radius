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

**Superseded by DEC-019 (2026-11-02, decided by delegation).** The text below is kept as history.

Provisional default (owner may revisit). The owner signed off the ratification set on 2026-11-02, but the docs contain no recommendation for this item, so the conservative option is recorded.

Decision: Radius does not generate tests or probes now. EV-12 stays a stretch task and is not started. If it is later allowed, the rules already written in EV-12 apply: probes are verification artifacts stored in Radius, never committed to the user's repo, labelled "generated", and counted with a lower independence factor `i(e)`. Reason: "Radius does NOT generate code" is a core principle in `docs/AI_CONTEXT.md`, and EV-12 itself says it needs an explicit decision. Revisit when: EV-04 (mutation) is done and the M4 gate has passed, or a design partner asks for it. Source: F-01.

## DEC-012: Open-source strategy and license are undecided; no license granted yet (open decision 4)

**Superseded by DEC-018 (2026-11-02, decided by delegation).** The text below is kept as history.

Provisional default (owner may revisit). The docs give no recommendation: PL-09 and QS-13 are the tasks that decide, and `PRODUCT_AND_GTM.md` only sketches a direction (open rule packs and benchmark, self-hostable, paid managed sandbox and SSO).

Decision: the working assumption is an open-core split (open: core engine, rule packs, benchmark, schemas; hosted/paid: managed sandbox, dashboards, SSO), but no license is chosen and none is added now (the repo has no LICENSE file). Until PL-09/QS-13 complete, no code or rules from other projects are copied (Verik is Apache-2.0; AgentProof and SlopGate licenses are unconfirmed). Revisit when: before any public release, external contributor, or design-partner code sharing; at the latest when QS-13 starts. Source: F-01.

## DEC-013: First language is Python (pytest), second is TypeScript (open decision 5)

Ratified: owner sign-off 2026-11-02.

Taken from the plan's explicit statements: `DESIGN.md` section 10 ("No language beyond Python (first) and TypeScript (second) until the evaluation shows value") and F-09 (Python first via stdlib `ast`, TypeScript second via a real parser). First test framework: pytest (the project's stated test stack in `docs/AI_CONTEXT.md`; EV-02 rules target pytest markers; EV-04 starts with `mutmut` and/or `cosmic-ray`). Jest/Vitest and Stryker follow with EV-14. Go/Java/Rust parsers stay experimental. Source: F-01, F-09.

## DEC-014: Calibration labels start from public benchmarks, then own history (open decision 6)

**Superseded by DEC-020 (2026-11-02, decided by delegation).** The text below is kept as history.

Provisional default (owner may revisit). The docs fix the order only ("Benchmark labels first (EP-03), revert/SZZ pipeline (CA-01)") and list label sources in CA-01; they do not choose between own history plus partners and public data only.

Decision: start with public OSS and benchmark data (SWE-bench-style datasets, Radius' own mutation benchmark, revert and SZZ-style labels mined from public repositories). Customer or design-partner repository history is not used for labels until a partner opts in explicitly in writing and QS-06 (retention/privacy) is done. Until `n_labels` passes the minimum, the UI says "uncalibrated prior". Revisit when: the first design partner is onboarded (PL-06) or CA-09 shows public labels are too noisy or too few. Source: F-01.

## DEC-015: LLM features are opt-in and code stays in the customer's environment by default (open decision 7)

**Superseded by DEC-021 (2026-11-02, decided by delegation).** The text below is kept as history.

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

## DEC-018: Radius core is licensed Apache-2.0 (open core); proprietary parts live in separate modules

Decided by delegation 2026-11-02 (owner: "complete everything by taking the ideal decisions"). Supersedes DEC-012. The owner may veto; see the irreversibility note at the end.

**Status (2026-11-02): in effect.** The `LICENSE` and `NOTICE` files were added after the owner explicitly confirmed the decision and took ownership of the open points that had been flagged: written consent from the other contributor whose commits are in history, and any university/sponsor claim on the capstone-era code. Those two items remain recorded risks, not verified facts; the owner is responsible for resolving them.

Decision: the Radius repository (engine, parsers, graph, intent, evidence, mutation, tamper, calibration code, rule packs, schemas, benchmark harness, CLI/Action/MCP clients, self-hostable API and worker, and docs) is released under the **Apache License 2.0**. `LICENSE` and `NOTICE` are added; package metadata (`pyproject.toml`, `package.json` files) declares `Apache-2.0`. Copyright holder: Mohith Kumar, 2026.

Components that may be proprietary later, and only as **separate repositories or separately distributed modules** that depend on the open core through its public interfaces (the open repo never imports them): SSO/SAML/SCIM, enterprise RBAC and audit-log export, the managed multi-tenant cloud control plane and billing, the hosted sandbox fleet and its scheduling, org-level policy packs sold as a service, and enterprise support tooling. Rule: anything already committed to this repository under Apache-2.0 stays Apache-2.0; features are not moved from the open core into the paid tier after release (that would break the trust the open core is for). New paid features start in the private module. Trademark: the name "Radius" and logos are not licensed (Apache-2.0 section 6).

Alternatives considered:

| Option | For | Against | Verdict |
|---|---|---|---|
| Apache-2.0 | Explicit patent grant and patent-retaliation clause; accepted by enterprise legal teams; same license as the most relevant tools in the literature table (for example Verik); compatible with every dependency we have; keeps the self-hostable, auditable story that a developer-trust product needs; contributors and academics can reuse the benchmark | A competitor may host it as a service without contributing back | **Chosen** |
| MIT | Simplest, most permissive | No express patent grant; no NOTICE mechanism; weaker for a company product that will sell to enterprises | Rejected (Apache-2.0 is a better fit for the same permissiveness) |
| AGPL-3.0 | Deters SaaS cloning | Many enterprises ban AGPL outright, which blocks the self-hosted and "developer installs for free" wedge; our own CI gate blocks AGPL dependencies, so we would ship what we forbid; cloning risk is low before there is a market, and a clone still lacks the evaluation data, calibration labels and brand | Rejected |
| BSL / FSL (source-available) | Protects hosted revenue for a few years | Not OSI open source; undermines "open rule packs and benchmark" and academic reproducibility (the paper artifact); many packages and distributions refuse it; hurts trust | Rejected |
| Closed source | Maximal control | Contradicts the go-to-market (open benchmark, MCP directories, community rule packs) and the verification-trust premise (a verifier nobody can audit) | Rejected |

Dependency check (2026-11-02, `pip-licenses` on the installed runtime plus `llm` and `observability` extras, 138 distributions, plus `scripts/ci/license_check.py`): the gate passes; no AGPL/SSPL/GPL. Weak copyleft only: `psycopg`/`psycopg-binary` LGPL-3.0-only (dynamic, unmodified library use is compatible with Apache-2.0; if an image bundles it, ship the LGPL text and keep it replaceable) and MPL-2.0 packages (`certifi`, `pathspec`, `fqdn`, `tqdm`; file-level, unmodified). `tree-sitter` and the grammar wheels are MIT, `anthropic` and `google-genai` are Apache-2.0: all permit this choice. Node dependencies were not inventoried locally (no `pnpm`); the CI job covers them. Details: `THIRD_PARTY_NOTICES.md`. The gate policy is kept unchanged; a dependency reported as `UNKNOWN` must be resolved by hand before release (QS-13).

Borrowed material: none is copied. Mutahunter is AGPL-3.0 (no copying, vendoring or linking); Verik is Apache-2.0 (allowed with attribution if ever used); AgentProof, ScopeProof and SlopGate have no usable license and are treated as all rights reserved.

Consequences:

- `docs/research/datasets/INVENTORY.md`: the Radius fixtures and `benchmarks/real` are now Apache-2.0 and may be redistributed. Third-party datasets keep their own verdicts.
- Owner actions still needed: (1) git history shows 5 commits by a second author (Sanhitha); obtain a short written confirmation (email is enough) that her contributions may be distributed under Apache-2.0, or rewrite them; (2) the project has a capstone diary, so check whether the university or a sponsor has any claim on the IP before publishing; (3) commits co-authored with an AI assistant are treated as the owner's work, which is the owner's call; (4) remaining QS-13 items: `SECURITY.md`, optional SPDX headers, review of the Node dependency report in CI.
- Sole copyright today means the owner could still add a commercial license for future code; contributions accepted under the DCO (DEC-022) keep their authors' copyright, so relicensing contributed code later would need consent.

**Irreversibility:** publishing a LICENSE is effectively irreversible for copies already distributed. Anyone who received the code under Apache-2.0 keeps those rights for those versions forever. The owner can change the license for future releases only, and only for code they or consenting contributors own. Do not publish the repository publicly until the owner has accepted this decision.

Revisit when: before first public release (confirm), if a hosted competitor appears and the open core is being strip-mined (consider relicensing future versions only), or if legal counsel advises otherwise. Source: QS-13, PL-09.

## DEC-019: Radius does not generate tests into user repos; advisory sandbox-only probe suggestions are allowed for measurement

Decided by delegation 2026-11-02. Supersedes DEC-011 (which deferred everything).

Position: "Radius does NOT generate code" stays true for anything the user ships. Radius never writes, pushes, commits, or opens a PR with any generated test or probe in the user's repository or branch.

Allowed (behind a feature flag `RADIUS_FEATURE_PROBES`, default off; implementation is the EV-12 stretch task and stays unstarted until its gate):

- **Probe suggestions**: property-based or differential checks (for example a Hypothesis property, or a base-versus-head differential run) generated and executed only inside the Radius sandbox, against changed symbols, to measure how strong the existing evidence is (does a plausible behavior difference exist that no existing test catches).
- Each probe is stored in Radius (not in git), labelled `generated`, tied to `algo_version` and the generator model and prompt versions, and counted with a lower independence factor `i(e)`, as EV-12 already states.
- A probe result is **advisory**: it can raise a `probe_gap` finding or lower evidence strength for a criterion; it can never make a criterion `proven`, never turn a verdict into `verified`, and is never counted as the contributor's evidence. Confirmatory experiments in the pre-registration do not use probes as a feature; probe use would be a separate, pre-registered extension.
- The report may show a probe as suggestion text only when a human opens it explicitly; it is a suggestion, not a patch.

Forbidden: writing into the user's repo or PR; auto-committing; presenting generated probes as the author's tests; using probe output to compute the verdict as if it were project evidence; running LLM-generated probes outside the sandbox; sending repository code to an LLM to write probes unless the separate code-egress policy exists and the org enabled it (DEC-021). Probe-generation prompts must pass the prompt-injection guard (`radius_shared.llm_guard`, `docs/security/PROMPT_INJECTION.md`), generated code is untrusted and runs only under the hardened sandbox profile (`docs/security/EXECUTION_ISOLATION.md`). Deterministic (non-LLM) probe forms, such as differential execution of the existing suite, are not subject to the egress gate.

Rationale: SWE-ABS, UTBoost and PatchDiff show that adversarial or strengthened tests expose weak evidence, so measuring evidence strength with probes is on-thesis; generating code for users is not the product. Advisory and sandbox-only keeps both the principle and the research claim (C2 is a gold-free, PR-time predictor; probes are an optional extra signal).

Revisit when: EV-04 mutation is done and the M4 gate passed and the false-alarm rate on seeded fixtures is measured (the EV-12 acceptance); or a design partner asks to receive suggested tests (a new decision about a user-facing "suggested test" feature, still never auto-committed).

## DEC-020: Calibration labels: public benchmark labels first, own history second, partner data only under written opt-in

Decided by delegation 2026-11-02. Supersedes DEC-014.

Order and rules:

1. **Public benchmark labels (primary).** SWE-ABS strengthened-suite labels on SWE-bench Verified patches (`L_ABS`; SWE-ABS code is MIT; the dataset card says Apache-2.0 but the base SWE-bench data has no declared license, so rows are used locally and never redistributed), then UTBoost, PatchDiff and SWE-Bench+ labels if the authors release them (`docs/research/datasets/AUTHOR_REQUESTS.md`). Use only what `datasets/INVENTORY.md` lists as fetchable; "UNKNOWN" means use locally for research, do not redistribute, do not commit. SWE-Mutation data is not used for anything commercial until its license is clarified (the paper is CC BY-NC-SA 4.0).
2. **Public real-PR outcomes.** AIDev (CC-BY-4.0; embedded code keeps repo licenses, so filter by repo license before any redistribution) plus revert/SZZ-style and follow-up-fix labels mined from public repositories (CA-01), with right-censoring handled as in the pre-registration.
3. **Radius' own history** (this repository): allowed for development and sanity checks, never as the headline evaluation (circularity).
4. **Partner or customer data**: only with explicit written opt-in per organization that names the repositories, label types, purpose (calibration and research), retention period and deletion on request, and only after QS-06 (retention/privacy) is done. Default retention: derived features and labels for the contract term plus 12 months; **no raw source code, diffs or free text are stored beyond hashes and numeric features** unless the contract says so explicitly. Partner data is never mixed into a public benchmark release and is not used in confirmatory pre-registered analyses (it is exploratory or secondary there).
5. Until `n_labels` passes the minimum, the UI says "uncalibrated prior".

Rationale: public labels are reproducible and shareable and avoid consent and IP risk; partner data adds realism but is opt-in by contract. Revisit when: the first design partner onboards (PL-06) or CA-09 shows the public labels are too noisy or too few.

## DEC-021: LLM provider and egress defaults

Decided by delegation 2026-11-02. Supersedes DEC-015. Consistent with the shipped IN-04 implementation (`packages/intent/src/radius_intent/infrastructure/llm/config.py`, `.env.example`).

Defaults:

- **Off and opt-in per org.** `RADIUS_LLM_INTENT_ENABLED=false` (deployment-wide) and `RADIUS_LLM_INTENT_ORGS` (comma list, or `*`) must both allow a call; the `EgressPolicy` gate is checked before every provider call; a closed gate falls back to the deterministic result.
- **What may leave: redacted intent text only** (PR title and body, issue text, commit messages, spec files as ingested and sanitised by IN-02). **Never repository source code, diffs, test code or traces**, until a separate code-egress policy exists. That policy (proposed names, not implemented: `RADIUS_LLM_CODE_EGRESS` plus a per-org setting) must be a distinct, default-off switch with its own decision, a per-call code-span size limit, and local-model support. Because PR text can itself quote code, secret masking and the sanitiser run first, and the docs must tell admins that intent text can contain pasted snippets.
- **Provider abstraction, Anthropic first.** The Anthropic provider is the shipped adapter (optional extra `llm`; key from `ANTHROPIC_API_KEY` only, never logged). Default extraction model: `claude-haiku-5-5` (`RADIUS_LLM_INTENT_MODEL`). `claude-sonnet-5-5` is used **only in experiments** (judge-style baselines such as B3/B7 and extraction ablations), never in the product path by default. Model and prompt versions are pinned and logged (`PROMPT_VERSION`).
- **A local/self-hosted model option is required before enterprise GA**: an OpenAI-compatible/Ollama-style adapter behind the same provider port, with the same guard, schema validation and quote verification. It gates the enterprise tier, not the open core's first release. Not yet implemented.
- **Logging and retention.** Every call writes metadata only (purpose, provider, model, prompt hash, token counts, cost, cache hit, latency) to `llm_call_log` (DESIGN section 5). Prompts and responses are not persisted and not logged at INFO; the response cache is in memory today. If an org enables debug capture, bodies are redacted and kept at most 7 days. `llm_call_log` metadata default retention is 90 days, configurable. Before enabling for a customer, check the provider's current commercial terms on data retention and training use (not verified here).
- **Cost caps.** Token caps stand in for cost: `RADIUS_LLM_INTENT_ANALYSIS_TOKEN_CAP=30000` per analysis and `RADIUS_LLM_INTENT_ORG_TOKEN_CAP=1000000` per org (a durable period-based ledger is a follow-up; today it is in memory). Exceeding a cap degrades to the deterministic result, never to an error. Hosted plans add a hard monthly org budget.
- **The LLM never influences verdict or score** (DEC-009) and never receives tools.

Known gap, to fix as a follow-up task (no code is changed by this decision): the older experimental `SemanticPruner` (`packages/analysis/src/radius_analysis/ai/pruner.py`, Gemini, enabled by `GEMINI_API_KEY` in `apps/worker`) sends caller source and callee diffs to a third-party model and is not governed by the DEC-015 gate. It must be put behind the same org-level egress policy and the code-egress switch (default off) or removed before any customer deployment or public release; until then `GEMINI_API_KEY` must stay unset in any shared environment. The `google-genai` and `google-generativeai` dependencies belong to that feature; they are now the optional `gemini` extra (no longer core dependencies).

Revisit when: the code-egress policy is designed (a new DEC), a design partner requires air-gapped mode or a specific provider, or the local-model adapter lands.

## DEC-022: Contributions use the DCO, not a CLA; inbound = outbound under Apache-2.0

Decided by delegation 2026-11-02.

Contributors sign commits with `Signed-off-by` (DCO). No CLA. Reasons and trade-off are in `CONTRIBUTING.md`: lighter and friendlier, rights stay with contributors, and the open core cannot be quietly relicensed, which supports developer trust; the cost is that relicensing contributed code later needs consent, so paid features are separate modules (DEC-018). Enforcement by a CI check is turned on when external contributors appear. Revisit when: an enterprise customer or acquirer requires the right to relicense contributions (a CLA can then be introduced for new contributions going forward).

## DEC-023: Telemetry is opt-in, anonymous, and never contains code or intent text

Decided by delegation 2026-11-02. Applies to PL-08.

Self-hosted and local installs send **no telemetry by default** (no phone-home). Opt-in only (`RADIUS_TELEMETRY`, off by default; name proposed, not implemented), limited to coarse product events and versions: no source code, diffs, file paths, PR text, repo names or user identifiers; a random install id that the user can reset. The hosted product's operational logs and billing metering are first-party service data described in the privacy policy, not "telemetry". Research data from users goes through DEC-020 (written opt-in), never through product telemetry. Revisit when: PL-08 is implemented.

## DEC-024: Name and branding are flagged, not decided

Decided by delegation 2026-11-02: no change.

"Radius" is the canonical product name (DEC-001). It is a very common word and also the name of well-known software (for example the RADIUS network authentication protocol), so trademark clearance, domain and package-name availability have **not** been checked and must not be assumed. Before public release or paid plans the owner should run a trademark search in the intended classes and secure package and organization names. The license does not grant the name (DEC-018). Not blocking for the research phase.

## DEC-025: Pre-registration v0.2 choices for the 11 owner decisions

Decided by delegation 2026-11-02. The choices and justifications are in `docs/research/preregistration/PREREGISTRATION.md` section 17 (version 0.2-draft). Summary: headline label `L_ABS`; UIM as the single pre-specified confirmatory predictor; RQ2 target 5,000 patches with a declared per-patch mutation budget and whole-cluster truncation; alpha 0.10 and tolerance 0.03; user-study primary outcome is fixed-cap detection rate; ethics route is an institutional determination before recruitment; RQ4 uses 4 open agent configurations run by us (no proprietary agents in the primary analysis); Holm within each RQ; 90-day horizon with partner data exploratory only; external deposit as a signed git tag plus an archive deposit, key holder is the owner ("owner to configure"); artifacts that appear before freeze are added by a logged draft revision (after freeze, by amendment). The pre-registration stays a DRAFT: it is **not frozen** and the prerequisites in its section 16 are not met. Freezing remains the owner's act.

## DEC-026: Criterion-to-symbol linking lives in `packages/linking`

Decided by delegation (LK-02 implementer), 2026-11-02. Justified under DEC-003 and DEC-007 (a new package only when a task that needs it starts, with the domain / application / infrastructure layering).

- **Why a new package and not `packages/analysis`.** The linking domain has its own model (`Link`, `LinkSet`, `Reason`), ports (`LinkerPort`, `NeighborPort`, `Reranker`) and consumers (LK-05 IEG, LK-06 combination, LK-07 evaluation, later LK-03/04). It depends on three other domains (LK-01 change sets in `analysis`, criteria in `intent`, the call graph in `graph`) but none of them should depend on it. Keeping it out of `analysis` avoids making the analysis package depend on `intent` and on LLM plumbing. The domain is stdlib-only, enforced by `packages/linking/.importlinter` (wired into `ci.yml` next to the intent contracts) and an AST test.
- **LLM re-ranker egress.** DEC-021 allows only redacted intent text to leave, and never repository source code. The optional re-ranker therefore sends the sanitised criterion text plus, per candidate, only an opaque reference, the symbol kind, qualified name, file path and change kind. It never sends bodies, docstrings, comments, literals, signatures or diffs. Names and paths are still code-derived, so the re-ranker has its own default-off gate (`RADIUS_LLM_LINK_RERANK_ENABLED` plus `RADIUS_LLM_LINK_RERANK_ORGS`, checked before every call through the IN-04 `EgressPolicy`) and an operator must accept that before enabling it. A richer code-egress policy (DEC-021 follow-up) is required before any code span is sent.
- **The LLM only re-ranks.** It can reorder and explain candidates produced by the deterministic linkers; the pipeline discards any symbol that was not a candidate, and the verdict never reads its output (DEC-009).

Revisit when: the code-egress policy is designed, LK-06 replaces the combination, or a second consumer needs the linking domain split further.

## DEC-027: Verdict v2 alpha slice decisions D1-D17 accepted as recommended, and `packages/evidence`

Accepted as recommended in `docs/research/design/VERDICT_V2_SLICE.md` section 8.2, by owner delegation 2026-11-02. This also records D14: the new package `packages/evidence` (import name `radius_evidence`) is justified under DEC-003 and DEC-007 because the first task that needs it (VS-00) starts now. It is a stdlib-only domain below `confidence`; producers never import it and it never imports them (`packages/evidence/.importlinter`, wired into `ci.yml`). Sub-package placements are as in design section 2.1 (`radius_confidence.verdict_v2`, `radius_github.verdict_v2`, `radius_testing.assertions`, `radius_linking` for relevance, `apps/worker/.../verdict_v2`).

| ID | Decision | Chosen option | Reason |
| --- | --- | --- | --- |
| D1 | Normalize tables now or store the bundle first | Bundle JSON first (table `verdict_v2`); normalized tables are Beta projections | Removes four migrations from the critical path and nothing is reworked later. |
| D2 | Profile for cap and threshold | `alpha-static` (`cap_static` 0.6, `tau_support` 0.5), versioned and labelled; DESIGN defaults 0.4/0.6 kept as a second profile | Both values are in the pre-registered sweep grid; under 0.4/0.6 nothing is `proven` and no PR is `verified`. |
| D3 | Sixth criterion state | No; `tampered` is a flag, `weak` covers partial | Keeps DEC-008 intact. |
| D4 | When `needs_review` is reachable | Only through rules R3a to R3c until calibration (CA-04) | Abstention without calibration would be invented. |
| D5 | May the alpha emit `verified` from static evidence | Yes, labelled "static assertion strength only" | Strictness comes from UIM, coverage and tamper rules; a permanent neutral would hide the product. |
| D6 | Criterion-to-test relevance method | Lexical plus `tests:` hints now; embeddings only if the VS-04 measurement shows the need | Cheap, deterministic, explainable; a missing edge is reported, never silently credited. |
| D7 | Worker-run (sandbox) results | Alpha uses CI-uploaded per-case results only; stated in the comment | Sandbox results are aggregate only today. |
| D8 | Meaning of "coverage" in the PR rules | Intent coverage as defined in design 3.9, including the `<module>` same-file rule | Gives the scope-creep signal; revisit with LK-05 blast-radius candidates. |
| D9 | Republish transport | Outbox table plus worker consumer | The API deliberately holds no GitHub credentials. |
| D10 | Check Run name and comment marker | Keep `Radius confidence` and `<!-- radius-confidence-report -->` | Branch protection and in-place comment updates keep working. |
| D11 | Non-Python behavioral changes | `insufficient_evidence` with `analysis_degraded` (R2d); TypeScript arrives with EV-14 | Honest result instead of a guess. |
| D12 | EV-02 severities for T001, T002, T004, T005, T012 | Confirmed as the configured defaults (high), still overridable by configuration; rule R1c reads severity from the engine and never hard-codes rule ids | `fail_on_tamper_at_least = high` depends on them. |
| D13 | Authorship default | `unknown` (i = 0.8); `agent` (0.6) only from commit trailers | Accepted for the alpha; known to under-weight agent PRs without trailers. |
| D14 | Record a DEC for the package and placements | Done by this entry | Required by DEC-003 and DEC-007. |
| D15 | Shape of the flag | Three-valued `off\|shadow\|on`; boolean spellings stay valid | Shadow mode is the free evaluation hook (VD-07). |
| D16 | IEG persistence tables | Generic `ieg_nodes` and `ieg_edges`; named link tables only as views if needed | New node and edge kinds need no migration. |
| D17 | Alpha UIM versus the pre-registered UIM | Every stored result carries `profile`; alpha-static results are never pooled with confirmatory data; the pre-registration may add the profile as an amendment before freeze | Keeps the confirmatory analysis clean. |

Revisit when: calibration exists (CA-*), mutation evidence lands (EV-04), or the first measurements (VS-04, the 8 F-14 fixtures) contradict a default; defaults are hypotheses, not results.

## DEC-028: A guarded import that cannot be verified offline is `medium`; only a registry miss is `high` (T012)

Context: fixture 06 (`pytimeparse-ultra` pinned in `requirements.txt`, imported behind `try/except ImportError`) reached `failed` through R1c even with no registry, because EV-02 reported `unverified_guarded_import` at `high`. The Verdict v2 design (section 7.3) expected `needs_review` offline and `failed` only when a registry lookup says the package does not exist. Without a registry the engine cannot tell a real private or niche package from a hallucinated one; the evidence is "unverified", not "known false". Failing the PR on that is a false accusation; ignoring it is false safety.

| Option | Offline result for fixture 06 | Trade-off |
| --- | --- | --- |
| Keep `high` | `failed` (R1c) | Catches the fixture without a registry, but fails every PR that adds a real but unlocked optional dependency behind a guarded import. |
| **`medium` offline, `registry_missing` (high) when a registry says it does not exist** | `needs_review` (R3a); `failed` with a registry | Conservative in both directions: never `verified`, never `failed` without proof. |

Decision: the default severity of `T012:unverified_guarded_import` is `medium` (EV-02 `DependencyRule.checks`, overridable through `severity_overrides` as before). `registry_missing` and `typosquat` stay `high`. This refines D12 for this one check only; the fixture facts agree (its README says the `high` severity is "an assumption until EV-02 decides" and records the registry 404 as the proof). The PR verdict for fixture 06 is `needs_review` offline and `failed` with the registry, as in `verdict_v2.fixture_expectations.json`.

Consequence: until a PyPI adapter ships (follow-up of EV-02), a hallucinated dependency is surfaced as `needs_review` with the finding listed, not blocked. Revisit when the registry adapter and the egress policy (DEC-021) allow lookups by default.

## DEC-029: Verdict v2 policy and waivers are repository files read from the base branch (VD-04, VD-05)

Context: a policy engine and waivers let people tune and accept findings. If the PR author could edit the file that judges the PR, the control would be void.

Decision: `.radius/policy.yml` and `.radius/waivers.yml` are read from the base side of the PR only. A head policy is read only when the base policy opts in with `head_policy: tighten_only`, and then each setting is kept only if it is at least as strict. Threshold overrides have narrow hard bounds. Lowering or disabling a `high` or `critical` tamper finding needs a recorded `allow_disable` reason. A base policy that cannot be read or parsed marks the analysis incomplete (R2d) instead of falling back to defaults; a broken waivers file ignores all waivers. A waiver needs a reason, an owner and an expiry at most 90 days from `created`, and can never cover a contradicted criterion or a failed CI case. `mode` (advisory or blocking) only maps the verdict to the Check Run conclusion.

Consequences: no migration (the policy and waiver audit travel in the stored bundle); no in-product role check or `audit_log` row yet, the control is review and CODEOWNERS on `.radius/`; org-level defaults are a follow-up. Details: `docs/policy.md`.

## DEC-030: Verdict v2 alpha honesty and author-trust hardening (wording, advisory check, provenance, author-hint cap)

Context: the independent review of 2026-11-03 (`docs/research/ALIGNMENT_LOG.md`, findings 2 to 5) found that the v2 comment said `PROVEN` / `Verified` and the Check Run was green on `verified`, while the evidence is static assertion strength only with thresholds fitted to the 8 fixtures; and that the PR author controls the criteria (PR body), the `.radius/intent.yml` read from the PR head and the `tests:` hints that set link strength to 0.95 to 1.0.

Decision (alpha, no new features, contract 4, all additions optional):

1. **Wording.** User-visible `PROVEN` becomes `SUPPORTED` (`unevidenced` becomes `UNSUPPORTED`); the verdict `verified` is shown as "Supported by static evidence (alpha)". The JSON enum values are unchanged; a presentation mapping lives in the renderer, the API (`presentation` block, `radius_shared.verdict_v2_wording`) and the dashboard. A one-line disclaimer is the first visible line of the comment and of the Check Run summary; the Check Run title carries "alpha - static evidence only - uncalibrated". The payload adds `alpha: true`, `calibrated: false`, `evidence_basis`, `contract_version`.
2. **Check Run conclusion.** `RADIUS_VERDICT_V2_CHECK_CONCLUSIONS=advisory` (default): never `success`; `failed` is `failure` only when decided by R1a, R1b or R1c (failing linked test, failing CI, high tamper); everything else `neutral`. `strict`: `verified` is `success`. Unknown values mean `advisory`. Combined with the policy engine (DEC-029): policy `mode: blocking` overrides the knob (`verified` is `success`, everything else, pending included, `failure`); policy `mode: advisory` never fails and is green only with the `strict` knob; no policy follows the table above. This supersedes the DEC-029 reading where advisory `verified` was `success`.
3. **Provenance and the cap.** Criteria and hints carry `author_pr_body | author_head_spec | base_spec | human_confirmed | llm_proposed`. Hint edges that are not `base_spec` or `human_confirmed` are capped at `LinkMapping.author_hint_cap = 0.7` in Stage B (so the cap is in the config digest and a stored Stage A can be re-scored). `base_spec` requires the identical `.radius/intent.yml` on the base ref (local `git show`); `human_confirmed` is lifecycle `confirmed` or `edited`. The flag and reason `author_supplied_hint` and a comment line make reliance visible. The intent-versus-diff check reuses intent coverage and R2c; the comment now states when coverage is below the minimum.
4. **Gold mode.** The fixture harness feeds the expected links as hints on `confirmed` criteria, i.e. `human_confirmed` (they represent the design author's intent, not a PR author's self-attestation), so the 8 gold results and `verdict_v2.fixture_expectations.json` are unchanged. Auto mode has no hints and is unchanged. The cap is shown by a variant (`run_collect(..., hint_provenance="author_head_spec")`, test `test_author_head_spec_hints_lower_support_and_change_the_state_of_fixture_01`): fixture 01 goes from `verified` to `insufficient_evidence` (R2b), C2 from `proven` (0.604) to `weak` (0.450).

| Option for the cap | Trade-off |
| --- | --- |
| Ignore author hints entirely | Safest, but removes the only way to link tests the lexical linker misses. |
| **Cap at 0.7, lift for base-branch spec or human confirmation** | Hints still help, none can saturate a link alone; cost: more `insufficient_evidence` on PRs that add their own spec. |
| Leave as is | Reproduces the review finding. |

Consequences: PRs that add `.radius/intent.yml` in the same PR now score lower until a human confirms the criteria or the spec is merged first. The cap value 0.7 is a hypothesis like the other thresholds. The threat model and its limits are in `docs/security/VERDICT_V2_THREAT_MODEL.md`. The policy engine (VD-04) is expected to enforce human-confirmed criteria on protected paths. Revisit when calibration exists or when the first real PRs show the cap's cost.


## DEC-031: `verified` needs at least one in-scope criterion; zero criteria is `insufficient_evidence` (R2e), `not_applicable` for docs-only changes

Context: the first replay on 29 merged PRs (`docs/research/evaluation/REPLAY_2026-11.md`, F2) found 11 PRs `verified` with zero criteria (docs, CI, licence, dependency bumps, test-only): R2a only fires when behavioral symbols changed, so everything else fell through to R4. A "verified" word on a LICENSE or workflow change is a vacuous pass.

Decision:

1. New rule **R2e**, evaluated right after R2a (so after R1 and R2p, before R2b), fires when there is no non-excluded criterion, no behavioral symbol changed (otherwise R2a already decides) and no unwaived tamper finding at or above `review_on_tamper_at_least` (otherwise R3a gives the more useful `needs_review`). Verdict `insufficient_evidence`; reason code `no_intent_criteria`; message "no intent criteria were extracted; add a spec or confirm criteria".
2. When every changed path is documentation or inert metadata (`is_inert_path`: markdown/rst/txt, images, `docs/`, `changelog.d/`, LICENSE and similar, `.gitignore`, `.editorconfig`), the same rule R2e uses reason code `not_applicable` ("only documentation or inert files changed, so there is nothing to verify; this is not a pass"). CI workflows, dependency manifests, lockfiles, Dockerfiles and tests are deliberately not inert: they stay `no_intent_criteria`.
3. No fifth verdict value. `not_applicable` is a reason code on `insufficient_evidence`, because a new enum value would change the contract, the API schema, the dashboard and every consumer, and `verified` would repeat the vacuous pass. The Check Run stays `neutral` (it is `neutral` for every non-R1 outcome, also with `strict`). The rule list grows from 12 to 13 (14 to 15 with a policy); `R2e` is added to the justification schema enum (additive: readers that validate the enum must learn the id). Contract version unchanged.

Consequences: docs and CI PRs now read "insufficient evidence" (neutral, never red) instead of "supported by static evidence"; the 8 fixtures are unchanged (all have criteria). Residual: the not-applicable test uses the paths of the changed-symbol list (a file with no symbol is invisible), and a PR that is genuinely fine but unspecified is still `insufficient_evidence` until criteria are confirmed; that is the intended message, not a defect.

## DEC-032: Opt-in `summary` intent extraction mode; unconfirmed inferred criteria block `verified`

Context: the replay of 2026-11 (`docs/research/evaluation/REPLAY_2026-11.md`, F1) found that the deterministic extractor yields 0 criteria on all 29 of this repository's PRs, so the intent layer contributes nothing on ordinary PR text. The `bullets` sensitivity pass was a crude upper bound (83 criteria, unknown precision) and not product behaviour.

Decision:

1. `RADIUS_INTENT_EXTRACTION_MODE` (worker setting) = `sections` (default, unchanged behaviour) | `summary` (opt-in; unknown values mean `sections`). `summary` adds, for the PR title and PR body only, deterministic (no LLM) proposals: a conventional-commit title (feat, fix, perf, revert, security) whose subject reads as behaviour, and bullets under Summary / Changes / What / Why / Description / Overview headings that read as behaviour (leading verb such as adds, fixes, rejects; a modal such as must or should; or a marker such as now, no longer, never). Test-plan bullets count only if phrased as a requirement. Boilerplate, checkbox templates, "Generated with", "Co-Authored-By", links-only lines, headings, over-long lines (300 characters), duplicates and anything beyond 12 per source are skipped with a diagnostic. Each criterion records the matching rule in its trace, has extractor version `det-extract-summary-v1`, weight 0.5 (low extraction confidence), no hints, and state `proposed`.
2. Provenance stays `author_pr_body`. Because the existing author-trust logic caps only `tests:` hints (and these criteria have none), it would not stop an unconfirmed inferred criterion from being `supported` and the verdict `verified`. So the worker adds the degraded marker `unconfirmed_inferred_intent` whenever a live criterion with a `det-extract-summary` version is neither confirmed nor edited, and R2d treats it as blocking: the verdict is at best `insufficient_evidence` until a human confirms or edits the criterion in the intent panel. Rules R1 and R3 still apply, so `failed` and `needs_review` are unaffected. The marker never appears in `sections` mode, so sections behaviour and the 8 fixtures are unchanged.  R2e is unaffected: a PR with zero in-scope criteria has no inferred criterion, so the marker is absent and R2e decides.
3. Not a research result: recall and precision on this repository's own, author-written PR text are in `docs/research/evaluation/EXTRACTION_SUMMARY_MODE.md` with their limits.

| Option | Trade-off |
| --- | --- |
| Do nothing | Intent layer stays empty on ordinary PRs. |
| Make `bullets` the product behaviour | High recall, unknown and visibly low precision. |
| **Opt-in `summary` plus a verified block** | Modest recall, higher precision, cannot inflate a verdict; cost: summary mode yields no `verified` without human confirmation. |

Consequences: no migration and no contract field (the marker is an existing-format degraded string). Default off. Revisit after IN-09/IN-10 gold data exists.

## DEC-033: A human decision on a criterion recomputes the stored verdict (Stage A refresh from criterion state, via the outbox)

Context: a browser test showed that Confirm in the intent panel changed the criterion state but not the stored verdict. The Stage A bundle (criteria with lifecycle and provenance, hint edges, degraded markers) is frozen at analysis time, so the author-hint cap (DEC-030) and the `unconfirmed_inferred_intent` block (DEC-032) stayed, although `docs/verdict-v2.md` says confirming lifts them.

Decision:

1. **Trigger.** A successful confirm, edit, reject or reopen through the intent API (same auth and `write` scope as before) upserts one row in `verdict_v2_requests` (reason `intent_changed`, `available_at` 3 s ahead: trailing debounce; the row is keyed by analysis, so bursts and CI uploads coalesce). No-op with the flag `off`. Any failure to enqueue is logged and swallowed; the criterion change is never rolled back or failed. Adding a criterion, submitting a source and rebuilding are not triggers (they change the criterion set, which needs a new analysis).
2. **Recompute.** `StageBRecomputer` (the existing outbox consumer path) now refreshes the stored Stage A with the current criterion states (`intent_refresh.refresh_stage_a_intent`) before scoring: confirmed/edited become provenance `human_confirmed` for the criterion and its hint edges, rejected criteria and their edges are removed, reopened ones lose `human_confirmed` (back to `author_pr_body`, capped), and the blocking marker is recomputed with the DEC-032 rule. The result goes through the normal store (identical inputs, no new revision) and the normal publish (comment and Check Run edited in place, stale heads never published). If the criteria cannot be read the recompute raises and the outbox retries with backoff.
3. **Provenance integrity.** The request carries no provenance and the body schema forbids extra fields. `human_confirmed` is derived only from the stored lifecycle `confirmed` or `edited`, which only the authenticated API can set. Attributes on the stored criteria objects are not trusted for provenance.
4. **Staleness is visible.** While a row is queued, `GET .../verdict-v2` adds `meta.refresh_pending` (and reason, attempts, `refresh_failed`) and the ETag covers it; the dashboard shows an out-of-date notice and, after its own confirm, polls a bounded number of times (about 30 s, 1.5 s to 10 s apart).

| Option | Trade-off |
| --- | --- |
| API recomputes inline | Needs the checkout and GitHub credentials in the API; slows and can fail the confirm. |
| Worker re-runs Stage A from scratch | Correct for new links, but clones the repository per click. |
| **Outbox + Stage A refresh from state** | Cheap, safe, reuses republish; cost: links are not recomputed (documented). |

Consequences: no migration (reason column is `String(16)`, `intent_changed` fits; no constraint). A verdict can lag a confirm by the debounce plus one worker poll. The API and worker share the database, so the worker needs no new credentials. Revisit if manual criteria or hint edits need to be scored without a new analysis.


## DEC-034: Opt-in `llm` intent extraction mode and gated "suggested tests (not run, not evidence)"

Context: the independent review of 2026-11-03 (`docs/research/ALIGNMENT_LOG.md`, entry 3) found no AI workflow visible to a user, and the deterministic extractor finds about 0 criteria on ordinary PR text (DEC-032 added `summary` as a heuristic). The design rule is binding: the LLM proposes, the evidence disposes (DEC-009); the verdict is deterministic and never LLM-computed. An LLM extractor (IN-04, DEC-015) already existed with its guard (`radius_shared.llm_guard`), egress gate, caps and fake provider, but was wired only into the API and never reached the worker that builds the analysis intent.

Decision:

1. **`RADIUS_INTENT_EXTRACTION_MODE=llm`** (worker; default stays `sections`, unknown means `sections`). It is `summary` plus the existing guarded `LlmCriterionExtractor`, restricted by a thin wrapper (`PrTextLlmExtractor`) to the PR title and body, composed in the worker (`build_llm_mode_extractors`). It needs `RADIUS_LLM_INTENT_ENABLED`, the organization in `RADIUS_LLM_INTENT_ORGS` and `ANTHROPIC_API_KEY` (optional extra `llm`, imported lazily); otherwise the worker logs the reason and runs `summary`. Any failure falls back to `summary` the same way and is recorded per call in the log (`intent_llm_trace`: model, usage, latency, drops, degradation reason). Proposals are `proposed`, method `llm`, provenance `llm_proposed`, weight 0.4; `has_unconfirmed_inferred_intent` now also covers method `llm`, so the blocking reason `unconfirmed_inferred_intent` (R2d) keeps `verified` unreachable until a human confirms. Reused guards: nonce-delimited data blocks, strict JSON schema (the guard rejects unknown and verdict-like fields, so "ignore extra fields" is implemented as "drop the item or the reply"), verbatim-quote grounding, wording grounding, dedupe, count/length/token/time caps. The model does not return a behavioural flag: testability stays the deterministic rater's job, so a model cannot influence which criteria gate R2a. Default model stays `claude-haiku-5-5` (DEC-015 rationale: every output is verified against the source); `claude-sonnet-5-5` is one setting away. The Anthropic adapter sends no temperature (current models reject non-default sampling parameters) and uses low effort.
2. **Suggested tests** (`RADIUS_FEATURE_SUGGEST_TESTS`, default off, same egress settings): for up to 3 `unevidenced` or `weak` criteria one pytest snippet is requested after scoring, then gated deterministically (parses; imports only `pytest` and the changed symbols of the PR; calls one; has an assertion rated at least `strong_min` by LK-04 plus the EV-06 table; no `open`, `exec`, `eval`, dunder access, fences or markup). Accepted snippets are carried in the stored bundle and the payload as `suggested_tests` with forced `executed: false`, `evidence: false`, `provenance: llm_proposed`, and rendered in a separate comment block. They are never run, never an input of scoring, never change a state or the verdict.
3. **A bug fixed on the way:** the LLM `extractor_version` embedded the full prompt hash (more than 64 characters), so every LLM criterion failed the storage limit. It is now `intent-extract-llm-v1;model=<18>;sha=<12>`.
4. `scripts/llm_extraction_eval.py` runs the mode over cached PR texts for the owner (needs a key; exits 2 without one).

| Option | Trade-off |
| --- | --- |
| Let the LLM score or confirm | Breaks the design rule; unreviewable verdicts. |
| Run suggested tests in the sandbox and count them | Closer to evidence but makes the model an author of evidence, and needs execution policy. Rejected for now. |
| **Proposals and unrun suggestions behind deterministic gates** | Visible AI workflow with no path to the verdict; cost: more unconfirmed criteria, data leaves the machine when on. |

Consequences: nothing changes with the flags off. The behaviour of a real model was not observed (no key was available): recall, the drop rate and snippet usefulness are unmeasured and must not be claimed. The dashboard panel does not show suggestions yet. Suggestions are regenerated on a Stage B recompute (bounded by an in-process cache), not stored per revision. Revisit with real runs of `scripts/llm_extraction_eval.py` and IN-09/IN-10 gold data.

## DEC-035: Mutation-measured evidence strength in Verdict v2, behind `RADIUS_FEATURE_MUTATION` (EV-04, EV-05, EV-09, EV-10)

Context: the alpha rates a test by the shape of its assertions (`a_static`, capped at `cap_static` 0.60), which is an unverified proxy for "would this test fail if the code were wrong". The merged mutation prototype (`radius_testing.mutation`, `docs/research/design/MUTATION_EVIDENCE.md`) can measure that. The lead took the owner decisions D1 and D2 and this record wires the prototype into the pipeline. The open questions D3 to D10 keep the defaults of the design document unless stated below.

Decision:

1. **Engine (D1).** Our own AST operator set from the prototype. No third-party mutation tool is used or adapted; AGPL tools (for example Mutahunter) are forbidden. The default operator set is the frozen `OPERATOR_IDS`; the post-hoc `CALLX` operator stays opt-in and is not used.
2. **Denominator (D2).** `d_mut(t, c) = killed(t) / N` over the decided, non-equivalent mutants (`killed` or `survived`) of the changed symbols that are linked to criterion `c` **and** were run with test `t`. Timeouts, errors, flaky mutants, mutants skipped for budget and equivalent suspects are excluded and reported (`excluded`), never counted as survivors. At least **5 decided mutants** are needed (`min_decided`), otherwise the pair is unmeasured. `d_reach` (kills given the test executed the mutated line) is **not computed in this slice**: the pipeline has no per-test line coverage, so the payload carries `d_reach: null` with `d_reach_reason: "no_reachability_data"`. It is reported as unavailable, never guessed, and it is not used to score.
3. **`d_eff`.** Measured: the Wilson lower bound (95%) of `killed / N`. Unmeasured: the existing static cap, `min(cap_static, a_static)`. **Unmeasured never gets better than static.** A measured value may be above or below the static one, so mutation can raise support (ten of ten kills give 0.722 against the cap 0.60) and can lower it (a strong static test that kills nothing gets 0 and is gated `zero_quality`). `q(e) = d_eff * i * f * flaky_f * (1 - tamper_p)` is unchanged. Guard added by this slice (decision D4, conservative): a test with `a_static == 0` stays at 0 even when measured, because an assertion-free test can only "kill" by crashing. Quality rows measured by mutation carry `algo_version` `evq-mutation-1`; the others keep `evq-static-1`.
4. **Criterion level.** `D(c)`, the union of mutants killed by any counted test of the criterion (no double counting), is computed and shown (`mutation.d_union`, `d_union_lcb`) with the survivors list. It does **not** cap `S(c)` in this slice (D5 stays a pre-registered ablation). Link granularity stays symbol level (D6): a criterion implemented by part of a function is charged for the mutants of the rest of it; the known limit is documented, not fixed.
5. **Verdict stays deterministic and no LLM is involved.** Survivors, equivalent suspects and unmeasured runs only change support (`S(c)`); they never produce `verified` or `failed`. Failing CI cases and failing linked tests keep deciding `failed`/`contradicted` (rules R1a, R1b) whatever mutation says; a property test checks this on random kill matrices.
6. **Execution: sandbox only.** Mutants are generated code from an untrusted pull request. The worker producer uses only `SandboxMutantRunner` (the F-07 hardened container: no network, read-only root, dropped capabilities, resource limits, one throw-away container per run, a fresh copy of the checkout with the mutated file written into the copy; the checkout is never written). It needs `WORKER_TEST_EXECUTION_MODE=sandbox`; otherwise the analysis records `mutation unmeasured (sandbox_disabled)` and keeps the static cap. `unsafe_in_process` never runs mutants. `SubprocessLocalRunner` stays dev/tests only: it is refused unless `RADIUS_MUTATION_ALLOW_LOCAL=1`, and `measure_mutation` additionally refuses it unless the caller passes `allow_local_runner=True`, which only `scripts/mutation_wired_eval.py` does. The producer builds its sandbox runner without F-11 failure reruns (a failing mutant is a kill) and rejects test ids that could become pytest options.
7. **Budgets and the degradation ladder.** Defaults: 50 mutants (`RADIUS_MUTATION_MAX_MUTANTS`), 600 s wall clock for the stage (`RADIUS_MUTATION_WALL_CLOCK_SECONDS`), per-mutant timeout `3 x median baseline + 2 s` clamped to 5 to 120 s and to `RADIUS_MUTATION_MUTANT_TIMEOUT_SECONDS` (60). Ladder, each step recorded in `mutation.ladder`: full set, seeded stratified sample, Tier A operators only, mutant count cut to what the wall clock affords, then **unmeasured, static cap** (`budget_insufficient`, `too_few_decided_mutants`, ...); mutants not started when the clock expires are `skipped_for_budget`. Baseline runs twice (F-11: failing or flaky tests are excluded and listed), a control run per mutated file (the unparsed, unmutated module) excludes the file's mutants if it breaks a baseline-passing test, survivors are rerun once (a rerun kill is `flaky`, excluded), timeouts are rerun once. Linked tests only; the design's stage 2 (wider set on survival) is not implemented. Equivalent suspects (prototype heuristics) are listed and never run.
8. **Producer failures degrade.** The producer is a Stage A producer like the others: a failure marks `producer_failed:mutation`, a timeout marks `producer_timeout:mutation` (unlike other producers it does **not** add the blocking `truncated` marker, because mutation evidence is optional), an unmeasured result marks `mutation_unmeasured:<reason>`. None of these markers blocks a verdict. The stage runs synchronously inside the analysis job (a documented latency cost; an asynchronous "mutation pending" republish is a follow-up).
9. **Cache (EV-09): a small table, not the artifact store.** Final results only (`killed` with `killed_by`, `survived`), table `mutation_result_cache` (Alembic `20261103_0016`), namespaced by `(organization_id, repository_id)` and keyed by `sha256(mutant hash | linked tests | sandbox image digest | repository context hash)`. The context hash covers the content of every `.py` and configuration file of the checkout, so a changed test body, helper, `conftest.py` or pytest configuration is a miss (conservative: any edit invalidates). Unknown image identity or an oversized tree disables the cache; database errors act as misses. Rows older than 30 days are pruned on write. The existing artifact store would have needed a new blob layer, retention and tenancy handling that a 100-byte keyed row does not. Results from untrusted code are cached under the same trust as the CI results they stand in for; nothing is shared across repositories (D10 default).
10. **Contract 5.** Optional fields only, plus one widened enum: `StageAInput.mutation`; quality rows `basis`, `d_mut`, `d_mut_lcb`, `mutation_n`, `mutation_killed`; per criterion `evidence_basis` (`static_only` | `mutation_measured` | `mutation_partial`) and `mutation` (`n_mutants`, `killed`, `d_union`, `d_union_lcb`, `survivors`, `excluded`, ...); top-level `mutation` run summary; flag `mutation_measured`; and the top-level `evidence_basis` gains `static_and_mutation`, which is the reason for the version bump (`verdict-v2-contract-5`). Nothing is emitted with the flag off, and the `inputs_digest` of flag-off computations is unchanged. The disclaimer, the Check Run title and the presentation text switch to a "static plus sampled mutation testing" wording only when at least one criterion was mutation-measured; the other criteria say "static assertion strength only". No wording claims proof.

11. **Follow-up measured on 2026-11-03 (fixture sanity, not a research result).** The ON-versus-OFF table of the 8 fixtures is in `docs/research/evaluation/MUTATION_WIRED.md`; the sandbox adapter produced the same kill matrix as the local runner on fixture 08 (`docs/security/EXECUTION_ISOLATION.md`). One defect fixed: the mutation stage no longer consumes the shared Stage A budget (it made later producers time out and set `truncated`). Stage 2 (wider test set on survival, `killed_outside_linked`) was open here and is implemented by DEC-036 (it needed no version bump after all: optional fields only); fixture 01 gold moves from `verified` to `insufficient_evidence` ON because of the symbol-level denominator (D6) and the Wilson bound at small N, which is a finding for the pre-registered ablation, not a tuning target.

| Option | Trade-off |
| --- | --- |
| Run mutants with the local runner in the worker | Fast and simple, but executes pull-request code with the worker's credentials. Rejected (F-07, `docs/security/EXECUTION_ISOLATION.md`). |
| Replace the static cap everywhere, mutation or not | Would need a mutation run for every analysis; unmeasured tests would lose their only evidence. Rejected: unmeasured keeps the static cap. |
| Use the point estimate `killed / N` as `d_eff` | Overstates small samples (5 of 5 would be 1.0). Rejected: Wilson lower bound. |
| Cap `S(c)` by `D(c)` now (D5) | Right in principle, unmeasured effect on the 8 fixtures; kept as an ablation. |
| Store results in the artifact store | No generic keyed blob layer exists here; a table is simpler and tenant-scoped. |

Consequences: with the flag off nothing changes (no code is imported, no payload field, same digests). With the flag on and no sandbox the analysis says so. The numbers are fixture sanity, not a research result (`docs/research/evaluation/MUTATION_WIRED.md`); `d_mut` as a predictor of incorrect patches is still the pre-registered RQ2. Open: D3 (timeouts are excluded, not counted as detected), D4 beyond the zero-assertion guard (kills by crash versus assertion), D7 schemata, D8 blocking policy, D9 mutation-aware-test tamper rule.

## DEC-036: Mutation stage 2: wider tests for survivors, `killed_outside_linked` and link gaps (EV-04, EV-05)

Context: DEC-035 item 11 left the design's stage 2 (`MUTATION_EVIDENCE.md` 5.1) open. Stage 1 runs only the tests linked to the mutated symbol, so a mutant that survives it can mean two different things: the code is under-tested (no test notices) or the criterion-to-test links are incomplete (some test in the repository would notice, it just is not linked). Charging the second case to the criterion as weak evidence is unfair and hides the better remedy (add a link or a `tests:` hint).

Decision:

1. **Mechanism (measurement, `radius_testing.mutation.measure`).** Opt-in via `MeasureConfig.stage2` (worker setting `RADIUS_MUTATION_STAGE2`, default off; it only matters when `RADIUS_FEATURE_MUTATION` is on, so flag-off behaviour and the default flag-on behaviour are unchanged). After stage 1, for every `survived` non-equivalent mutant: (a) the test files of the repository that import the mutated module are found by a **static `ast` scan** (nothing is imported or run on the host; import of any dotted suffix of the module path counts, `from pkg import mod` too; test files and `conftest.py` rules as in stage 1; sorted, at most 40 files per module); (b) those files are run once, unmutated, twice (like the stage 1 baseline); only tests that pass in both runs can attribute a kill, failing or flaky ones are excluded; tests already linked to the mutant's symbol are removed; (c) each survivor runs the remaining tests in **sorted order, at most `RADIUS_MUTATION_STAGE2_MAX_TESTS` (60)**, with early exit (`pytest -x`), under the stage 1 per-mutant timeout; (d) a kill must **repeat** in a second run of the killing tests, otherwise it is `unconfirmed` and the mutant stays a plain survivor (a flaky test must not be able to remove a penalty); (e) the whole stage has its own wall clock `RADIUS_MUTATION_STAGE2_WALL_CLOCK_SECONDS` (300); survivors not reached are counted `skipped_for_budget`; a runner timeout or error gives no stage 2 statement for that mutant and never changes stage 1. The result is `MeasuredMutant.killed_outside_linked` (sorted, at most 5 killing test ids; `None` = stage 2 did not run for it, `()` = it ran and nothing killed it) plus a `Stage2Summary`. The mutant's stage 1 status stays `survived`.
2. **Cache.** Stage 2 results are cached with a different key (`sha256(mutant hash | "stage2" + the wider test ids | image digest | repository context hash)`), final values only (`killed` with the confirmed killers, `survived`). Stage 1 keys are untouched and stay valid (a test runs a stage-1-only measurement against the same cache and gets full hits).
3. **Scoring rule (`radius_evidence.domain.mutation`).** For a criterion `c`, a stage 1 survivor is a **link gap** when it has confirmed outside killers and at least one of them is not among the tests linked to `c` (the tests run against the symbols of `c` in stage 1 plus every test of `c` in the IEG, via a symbol or a `tests:` hint). A link gap is **removed from the mutant pool** of `c`: the denominator `N` of `d_mut(t, c)` and of `D(c)` drops by one, the numerator is unchanged. Consequences, all deliberate: the unlinked killers are credited to nobody (no test row, no `killed` count, no `S(c)` term), so support is never raised *by* them; the unfair penalty is dropped, and the result equals "that mutant was never generated" (a test checks this equality). The Wilson bound and the `min_decided` rule apply to the reduced `N`: if removing gaps leaves fewer than 5 decided mutants the pair is unmeasured and the static cap applies (a test covers it). A survivor whose outside killers are all already linked to `c` stays an ordinary survivor (conservative). Mutants killed in stage 1 by a test linked to the symbol but counted for another criterion are not stage 2 cases and are not changed by this decision.
4. **Report.** Per criterion (optional fields of contract 5): `mutation.link_gaps[]` (`mutant_id`, `path`, `line`, `operator`, `tests[]`), `mutation.link_gap_tests[]` (distinct, at most 10), `mutation.excluded.killed_outside_linked`; link gaps are not listed as survivors. Top level: `mutation.stage2` (`enabled`, `survivors`, `run`, `killed_outside_linked`, `unconfirmed`, `no_wider_tests`, `skipped_for_budget`, `errors`, `cache_hits`, `tests_considered`, `ladder`). Quality rows give the reduced `mutation_n` and say "N mutant(s) killed only by unlinked tests left out (link gap)". The next action is fixed text in the renderers (no untrusted text): "Link these tests to the criterion, or add them as `tests:` hints in .radius/intent.yml." The comment line is "Link gaps: N mutants killed only by tests not linked to this criterion: <ids>" followed by "These tests are not counted as evidence for the criterion, and these mutants are left out of its mutation score instead of counting as weak evidence." Ids and paths are escaped code spans; the dashboard renders text only. No new `Flag` value or `next_actions` code was added (that would widen enums); the hint lives in the criterion's mutation block.
5. **Contract.** Stays `verdict-v2-contract-5`: every addition is an optional field that is absent (not `null`, not empty) unless stage 2 ran and found something (`MutantInput.killed_outside_linked` and `MutationInput.stage2` use `omit_none`; the criterion keys appear only with a gap). Flag-off output and flag-on stage-1-only output are byte-identical to before; `scripts/verdict_v2_make_fixtures.py --check` still matches the 8 bundles. Schema JSON, API model (`LinkGapOut`, `stage2`), shared payload reader (passes the dict through), renderer and dashboard model were updated together; settings are in `docs/operations/CONFIGURATION.md` (regenerated).
6. **Verdict stays deterministic.** Stage 2 only removes mutants from a pool; it can lower a penalty, never create evidence, and never touches R1a/R1b, tamper or CI rules. Property tests: with random kill matrices and random link gaps a failing CI case stays `failed`/`contradicted`, stage 2 never creates `failed` or `contradicted`, and per-criterion support is never below the stage-1 value and never above the value with the gap mutants removed.
7. **Execution.** Stage 2 uses the runner that stage 1 uses, so in the worker it runs only through `SandboxMutantRunner` (same F-07 container, copy of the checkout, validated test ids, no option injection). The worker still never constructs `SubprocessLocalRunner`; `measure_mutation` still refuses it without `allow_local_runner=True` with stage 2 on (tested). Not verified against a real container: stage 2 was exercised with fakes, a sandbox-adapter fake and the local runner on trusted fixtures only.
8. **Known limits (honest).** The wider set is limited to test files that statically import the mutated module (tests that reach it only through another module, a fixture or a plugin are not tried), is capped (60 tests, sorted order, so a killer beyond the cap is missed), and the cost is up to one extra container run per survivor plus two baselines of the wider files and one confirmation run per kill, inside its own 300 s budget. A stage 2 kill says an unlinked test notices the fault; it does not say the test is about this criterion.

| Option | Trade-off |
| --- | --- |
| Count link-gap mutants as killed (credit the unlinked test) | Raises support using tests that are not evidence for the criterion. Rejected. |
| Keep them as survivors | Penalises the criterion for incomplete links and hides the cheap remedy. Rejected. |
| Add a `link_gap` flag and a `next_actions` code | Widens enums of contract 5 for no information the optional block does not carry. Rejected; revisit with the next contract bump. |
| Accept a single stage 2 kill | A flaky test could remove a penalty. Rejected: the kill must repeat. |

Consequences: stage 2 can change the support of a mutation-measured criterion only upwards and only back to the "without that mutant" value; fixture 01's drop (DEC-035 item 11) does not come from stage 1 survivors and is not changed by this decision (measured: `docs/research/evaluation/MUTATION_WIRED.md`, stage 2 section). Open: link-gap detection per criterion for mutants that a test linked to another criterion of the same symbol kills (a criterion-level notion not covered here), per-test line coverage to replace the static import scan, a real-sandbox measurement of stage 2 cost.

## DEC-037: Verdict v2 review B fixes: missing or unanalysable evidence never reads as a pass (B-01 to B-20)

Context: an independent review of the Verdict v2 core (`docs/review/CODE_REVIEW_B_VERDICT_V2.md`, 20 findings) found one crash that could leave an old `verified` published, three ways for unanalysed changes to look like "nothing found", and several smaller trust and bookkeeping gaps. Each finding was re-verified against the code before changing it; the response with commit and test per finding is `docs/review/CODE_REVIEW_B_RESPONSE.md`. DEC number 037 is the next free one on this branch; DEC-036 is taken by the mutation stage 2 branch (rename if both land with a different order).

Decision:

1. **Evidence references are lists (B-01).** `Reason` gains the optional `refs` (a tuple, omitted from JSON when absent so every existing digest is unchanged); `ref` is always one id. The failing-linked-test reason sets `refs` only with two or more failing tests; the rules read `refs`. The same applies to the `author_supplied_hint` reason. Payload reasons may carry `refs` (array of strings).
2. **A recompute failure never leaves an old verdict current (B-01, B-04).** `StageBRecomputer.recompute` records an `error` revision (`recompute_failed:<ExceptionName>`, or `stage_a_not_stored` when the stored bundle lost its Stage A) before the exception propagates. The publisher publishes these two reason codes as "verdict unavailable" with conclusion `action_required`; ordinary error rows are still not published.
3. **The 2 MB bundle cap never cuts Stage A in pieces (B-04).** `evidence_items` and `stage_b` go first (they are rebuilt from the uploads); Stage A is kept whole up to 8 MB, above that it is dropped whole with `stage_a_dropped`, and `latest_stage_a` then raises instead of falling back to an older revision.
4. **Unanalysed changed files block `verified` (B-02).** New blocking marker `unanalyzed_files:<n>` (and `unsupported_language:<lang>` for file-level non-Python files) from LK-01 `FileChange` levels `file` and `ignored`, minus an explicit inert allowlist (`rules.is_inert_path`: documentation, images except SVG, licence and changelog names, documentation `.txt`, lockfiles) and minus CI, manifest and build-configuration files, which the tamper catalog analyses. Owner decision recorded here: lockfiles are on the inert allowlist (the review asked for it; the earlier DEC-031 text called them not inert). R2e `not_applicable` now requires no blocking marker. The 8 fixtures are unchanged (`verdict_v2_make_fixtures.py --check` passes; fixture 06 stays `needs_review` because `requirements.txt` is a tamper-analysed manifest).
5. **Incomplete tamper analysis blocks `verified` (B-03).** `tamper_unanalyzed:files=<n>` (unreadable, oversized, binary or unparsable test, conftest, CI, build, manifest or snapshot files) and `tamper_unanalyzed:<note>` for `context_error`, `context_time_budget_exceeded`, `max_files_exceeded`, `base_snapshot_unavailable`, `rule_time_budget_exceeded`.
6. **Author weights and author link hints (B-05, B-06).** Criterion weights count only for `base_spec` and `human_confirmed` criteria (else 1.0). Criterion-to-symbol edges supported only by the `explicit` linker of an untrusted criterion are capped at `link_sat_cs * author_hint_cap` (so `l_cs <= 0.70`), count for intent coverage only when a concrete `path::symbol` hint names the symbol, and do not extend coverage to the rest of the file. No config field was added, so config digests are unchanged.
7. **Who confirmed (B-07).** `CriterionInput.confirmed_by` / `CriterionVerdict.confirmed_by` (optional, omitted when absent) and `criteria[].confirmed_by` in the payload, API model, schema, renderer and dashboard. A label equal to the PR author's login makes the confirmation not count (criterion stays unconfirmed, cap and block stay). Labels are unverified headers, so this is a best-effort guard; the residual risk is in the threat model and the rule is the replaceable `confirm_policy` hook.
8. **Outbox (B-09, B-16).** `add_criterion` enqueues a recompute; criteria the stored analysis never saw add the blocking marker `intent_not_in_analysis:<n>`; a bounded sweep (`reconcile_stale`, 60 s interval, 20 analyses) re-queues analyses whose newest CI upload is newer than their newest verdict and that have no queued request; an identical re-save refreshes `computed_at` so the sweep does not loop. A re-request while a claim is running keeps the claim; `complete_request` releases it for exactly one more pass (no second concurrent worker, no duplicate comment).
9. **Check Run conclusions (B-10).** Unusable base policy: `action_required` (hard failures stay `failure`). `blocking` with R2e `not_applicable`: `neutral`. R2p no longer fires when nothing is in scope (docs-only, no criteria, no blocking marker). Full table in `docs/verdict-v2.md`.
10. **Smaller fixes.** B-08 deny-by-default AST allowlist for suggested tests; B-11 LLM grounding also checks negation and limiter agreement and word order; B-12 `is_inert_path` rewritten (exact names and suffixes); B-13 `removed` instead of `deleted`; B-14 mutation cache context hash covers every file outside tool directories (limit 20000 files / 40 MB, else the cache is off; this supersedes the ".py and configuration files" wording in DEC-035 point 9); B-15 live head from `GET /pulls/{number}`, unknown head means no publish (`live_head_unknown`); B-17 outcomes from quality-row status when `evidence_items` were dropped; B-18 same-digest save updates `mode`, bundle `verdict.revision` equals the row revision; B-19 the stored bundle digest includes the suggestions (the scoring digest inside the verdict does not); B-20 `suggested_tests`, `degraded`, `confirmed_by` and `reasons[].refs` in the schema and API model.
11. **Contract.** Optional fields only, no new required field, `CONTRACT_VERSION` stays `verdict-v2-contract-5`. Updated together: `verdict_v2.schema.json`, `radius_api.schemas.verdict_v2`, `radius_shared.verdict_v2_payload`, `radius_github.verdict_v2.view` and `markdown`, `apps/dashboard/lib/verdict-v2-model.ts`, docs. `ALGO_VERSION` is not bumped (it would change every golden file), so verdicts stored before this change keep their numbers until their inputs change.

| Option | Trade-off |
| --- | --- |
| Make `Reason.ref` a tuple | Breaks every consumer of the contract-1 `ref` string. Rejected: add `refs`, keep `ref` one id. |
| Treat every unknown file as blocking, including CI and manifests | Fixture 06 (a hallucinated dependency in `requirements.txt`) would stop being `needs_review`; the tamper catalog is the analyser for those files. Rejected. |
| Keep lockfiles non-inert | Safer against supply-chain edits but blocks every dependency bump. Rejected by the owner (lockfile allowlist requested in the review brief). |
| Fail every unreadable-policy run | Would redden advisory repositories on a transient read error. Rejected: `action_required` for repositories that have a policy file. |
| Bump `ALGO_VERSION` | Recomputes old verdicts but changes every golden file and fixture digest. Rejected for this branch; revisit with the mutation stage 2 merge. |

Consequences: more analyses end in `Not verified` because of markers (visible in the comment, payload and dashboard); the PR author can no longer shrink the unproven mass or cover the whole change with one glob; a failed recompute shows as unavailable instead of an old pass. Open: per-person identity for confirmations, a separate column for Stage A, Postgres-level tests of the claim handling (SQLite and memory only here), and the confirm-UI change that shows the LLM quote next to the criterion text (B-11, not done).


## DEC-038: Per-analysis git worktrees over a locked object cache (C-03, C-06, C-07)

Context: all analyses of one repository shared a single working tree with no lock (review C, C-03), git ran without time limits (C-06), and the cache was never pruned and could be wedged by a stale `index.lock` or a dirty tree (C-07).

Decision:

1. The per-repository directory stays the **object cache** (cloned with `--no-checkout`). Clone, fetch, PR-ref fetch and worktree creation run under an exclusive OS advisory lock on a sibling `<cache>.lock` file (`fcntl.flock` on Linux, `msvcrt.locking` on Windows, plus an in-process mutex). The kernel releases it when its holder dies, so a crash cannot leave a stale lock; waiting has a timeout (`RADIUS_GIT_LOCK_TIMEOUT_SECONDS`) and fails retryably.
2. Every analysis gets a private `git worktree add --detach` under `<REPOSITORY_CACHE_DIR>/.worktrees/`, whose path is the `repository_path` the whole pipeline (parser, linking, test selection, sandbox copy/mount, verdict v2) uses. It is removed in a `finally` (an `ExitStack` around the job).
3. Every git command has a time limit (`RADIUS_GIT_CLONE_TIMEOUT_SECONDS` 300, `RADIUS_GIT_TIMEOUT_SECONDS` 120) and runs in its own process group (session on POSIX, process tree via `taskkill` on Windows) that is killed on expiry; the error is retryable.
4. Housekeeping every hour: `index.lock` older than `RADIUS_GIT_STALE_LOCK_SECONDS` is removed only while the repository lock is held, `git worktree prune`, `git gc --auto`, orphaned worktree directories older than twice `WORKER_JOB_STALE_AFTER_SECONDS` are deleted, and (opt-in, `RADIUS_GIT_CACHE_MAX_IDLE_DAYS`, else `RADIUS_RETENTION_DAYS`) idle caches are deleted. A locked cache or one with a live worktree is never deleted.

| Option | Trade-off |
| --- | --- |
| One lock held for the whole analysis | Serialises every analysis of a repository (minutes); rejected. |
| A fresh full clone per analysis | Correct but costs bandwidth and time for large repositories. |
| **Locked cache plus per-analysis worktree** | Short critical sections; a worktree is cheap (no object copy). Cost: the lock is advisory and needs a filesystem with working locks (not NFS without lock support); two workers must share the cache directory for the lock to matter, otherwise each has its own cache anyway. |

Consequences: idle pruning is age-based only (no size cap or per-organization quota). Lock files `<cache>.lock` are kept on purpose (deleting a lock file others may wait on is racy). The legacy `LocalGitRepositoryClient.checkout` still exists for private clones and now forces the checkout; the worker uses it only for git clients that cannot make worktrees (test doubles).

## DEC-039: Platform review C fixes: job lease with owner check, early `running`, publish after commit, validated dashboard sessions

Context: the independent platform review (`docs/review/CODE_REVIEW_C_PLATFORM.md`) found that a job running past the stale window was re-claimed by another worker while the first still ran (no lease renewal, no owner check), that one DB transaction wrapped the whole analysis, that retries had no backoff, that the dashboard proxy accepted any non-empty `radius_session` cookie, and that nothing stopped duplicate analyses for one head commit.

Decision:

1. **Lease with an owner.** `analysis_jobs.claimed_by` (worker id: host, pid, random suffix) is set by `claim_next`. A background thread renews `locked_at` every `WORKER_HEARTBEAT_INTERVAL_SECONDS` (default min(60 s, stale/3)) with one conditional UPDATE. `complete`, `fail`, `requeue`, `skip_claimed` and the heartbeat only act on a job that is still `running` and claimed by this worker; otherwise they are a logged no-op returning `False` and the worker discards its result (no publish). The pipeline checks the lease at its stage boundaries; a single long git or test call is not interrupted (the reaper deadline still bounds a hung job).
2. **Retry backoff.** `analysis_jobs.available_at`: a requeued job waits `WORKER_JOB_RETRY_BASE_SECONDS * 2^(attempt-1)` (default 15 s, capped at 900 s, +-25% jitter). The poller may queue a failed head again at most `RADIUS_GITHUB_POLL_FAILED_RETRIES` (default 2) times, spaced from `RADIUS_GITHUB_POLL_FAILED_RETRY_DELAY_SECONDS` (900 s, doubling). Permanent-error classification was not added.
3. **Smaller transactions, publish after commit.** `running` is committed before the pipeline; the artefacts and the job completion commit together; the GitHub result is published only after that commit (publishing never raises and updates the same check run, so it is idempotent). The pipeline still runs in one session; only the status transitions and the publication moved. A requeue returns the analysis to `pending`.
4. **One active analysis per head commit.** Partial unique index `uq_analyses_active_pr_commit` on `(pull_request_id, commit_sha)` where `status IN ('pending','running')`. The store catches the `IntegrityError` in a savepoint and returns the existing analysis. Reruns of finished analyses are unaffected; a rerun of an analysis whose twin is still active returns that active one. The migration cancels (never deletes) existing duplicate active rows first. Not changed: the global `unique` on `repositories.github_repository_id` (security review A-05).
5. **Dashboard sessions are validated.** The Next.js middleware and the proxy route call `GET /api/v1/auth/me` with the cookie (15 s positive and 5 s negative in-memory cache, 5 s timeout, fail closed). `DELETE` needs the `admin` role; the audit actor is the validated e-mail. A deployment is **single-tenant**: all authenticated dashboard users share the one organization of the configured API key.
6. **Operational.** Compose: required `POSTGRES_PASSWORD`, loopback port publishing by default (a variable, so production chooses deliberately), `restart: unless-stopped`, worker `stop_grace_period` 15 m, worker health file. Alembic takes a PostgreSQL transaction advisory lock. The auth tables are created idempotently by a migration (`create_all` stays). Release publishing needs the GitHub environment `release`, a tag on `main`, and pushes by digest before scanning and tagging.

| Option | Trade-off |
| --- | --- |
| Commit every pipeline stage separately | Larger rewrite of the orchestrator; rejected for now, the long transaction no longer holds the analyses row or hides `running`. |
| Fencing token column instead of `claimed_by` | Equivalent here (the worker id is unique per process start); a counter would also survive id reuse. Not needed. |
| Per-user organization routing in the dashboard | Real multi-tenancy; needs per-user keys and routing. Documented as single-tenant instead. |
| Remove `alembic upgrade head` from the API image | Breaks non-Compose deployments; the advisory lock makes concurrent starts safe. |

Consequences: PostgreSQL behaviour (advisory lock, `FOR UPDATE`, the partial index, concurrent savepoints) was exercised on SQLite only. A job killed hard is recovered after the stale window, not instantly. Listing endpoints now return at most `limit` (default 100) items.

## DEC-040: Review partials finished: verified confirmer, source quote, one payload builder, verify-page password, uniform signup, bounded runner units, lease-based reaper

Context: seven items of the three independent reviews were left PARTIAL (B-07, B-11, B-20, A-07, A-12, C-04, C-18; see the response documents). This decision finishes them, or states exactly what stays open and why.

Decision:

1. **Confirmer identity (B-07).** The audit actor of an intent write comes from the authenticated principal. The dashboard proxy forwards the session it just validated in `X-Radius-Session` (server to server, never forwarded from a browser, not in the CORS allow list); the API validates it like the cookie and writes `org:<id>/user=<user id>[/gh=<login>]`, the login read from `auth_accounts.provider_login` (new nullable column, migration `20261104_0021`, refreshed at every GitHub sign-in). Without a session the actor is `/key=<prefix>` (managed key) or `/legacy-env-key`; `X-Radius-Actor` is honoured only in the insecure development mode and then marked `/dev=<label>`. `=` cannot occur in an old label, so a label cannot forge the structured form. The worker parses the actor and applies `confirm_policy`: a confirmer linked to the PR author's login is never counted; a linked other account counts; an unlinked confirmer (or an unknown author) counts and is labelled `unverified confirmer` under `allow_unverified` (default), and does not count under `require_second_person` (`RADIUS_VERDICT_V2_CONFIRM_POLICY`, validated at start). The note is part of `confirmed_by`, so it reaches the comment, the API and the dashboard. Old rows (`org:<id>/<label>`) are read as declared labels: still refused when equal to the author, otherwise unverified.
2. **Source quote (B-11).** `CriterionView.source_quote` / `source_quote_truncated`: the span of an LLM-proposed criterion is, by construction, the verbatim quote the model had to cite; the API returns that slice of the stored source (500 characters at most) and the intent panel renders it as a text node.
3. **One builder (B-20).** `scoring.build_payload` wraps the final bundle in a `StoredVerdict` and calls the shared builder; the duplicated item/reason/next-action code was deleted. The bundle format is unchanged and old rows read. The one visible difference: an empty `degraded` list is omitted, as the API always did.
4. **Verify page password (A-07).** `POST /auth/verify-email/check` (token peek, not consumed) tells the page whether a password is required (uat/production and an address unverified until now). `POST /auth/verify-email` accepts `password`; when required and missing it answers 400 before the link is spent. The password is stored only for the holder of the mailbox link; the signup password is still discarded. Development and test: nothing is asked.
5. **Uniform signup (A-12).** In uat/production, signup for a registered address answers 201 with the same shape, no session, the same hashing work and a background mail ("you already have an account", or a fresh verification link for an unverified owner); development keeps 409. Login throttling stays per process: no table in the shared PostgreSQL is a rate-limit store (`idempotency_keys` is organisation-scoped), a new table was not added, and the deployment recommendation is documented.
6. **Bounded runner units (C-04, narrowed).** Reading the installation / token, the in-progress check, clone / fetch / worktree, intent ingestion and every publication run with no transaction open: read-only steps call `_end_read_transaction` (which refuses to commit pending changes) before the network or git call. The analysis pipeline stays one transaction.
7. **Lease-based reaper (C-18).** A job with `claimed_by` and a `locked_at` renewed within the stale window is never reaped for being long; a job without heartbeat is recovered by stale recovery; the deadline counts from the job's last change (`updated_at`, `created_at`, `available_at`, `locked_at`), or from `analysis.started_at` when there is no job.

| Option | Trade-off |
| --- | --- |
| Trust `X-Radius-Actor` and compare it with the PR author | The behaviour before; an author with the key picks any label. Rejected. |
| Per-person API keys | The real fix for the unlinked case; a product change (key ownership, UI). Not done; the policy hook covers it meanwhile. |
| Compare GitHub numeric ids instead of logins | More robust against renames, but the PR author is stored as a login only. Left as a refinement. |
| Commit the pipeline in stages to free the connection during tests | Leaves partial artefacts and repository-level test history after a crash unless every store gets a replay-safe write path or a purge; rejected for now. |
| A new login-throttle table | Would make the limit shared, but adds a write on every failed login and a lock-out surface; deferred. |
| Run the heavy DB-free steps (parse, discover) before the first pipeline write | Small gain, changes orchestrator ordering that many tests pin; not done. |

Consequences: the dashboard needs no new configuration; an API deployed behind a proxy must not let a browser set `X-Radius-Session`. Users who signed in with GitHub before this release have `provider_login = NULL` (treated as unlinked) until their next GitHub sign-in. A reaper deadline no longer stops a job whose heartbeat is alive but whose pipeline hangs; only the sandbox timeouts bound it. Not verified: PostgreSQL, a real GitHub OAuth sign-in, real SMTP delivery.
