# Radius — Phase 3: End-to-End Verification, Reliability & Production Readiness

**Document Type:** Technical and Business Requirements Specification  
**Product:** Radius — AI-Native Software Verification Platform  
**Phase:** Phase 3  
**Status:** Proposed  
**Version:** 1.0  
**Audience:** Founders, Product, Engineering, QA, DevOps, Security, and Future Pilot Customers

---

# 1. Executive Summary

## 1.1 Purpose

Phase 3 will transform Radius from an integrated software verification platform with substantial reported feature coverage into a **validated, reliable, secure, measurable, and production-ready software verification product**.

Radius is designed to answer:

> **Is this Pull Request safe to merge, based on the available verification evidence?**

Radius should understand repository structure, analyze code changes, identify potentially affected components, select relevant tests, execute verification, assess evidence, and provide developers with an explainable assessment of potential risk.

Phase 3 will not primarily focus on adding more features. Its central objective is to establish that the capabilities already implemented in earlier phases work correctly together and provide trustworthy, actionable evidence in real development workflows.

The phase will focus on:

- Validating end-to-end correctness using representative repositories and realistic PR scenarios.
- Improving source parsing, semantic resolution, dependency graphs, and blast-radius accuracy.
- Improving test selection and measuring its fault-detection trade-offs.
- Strengthening AI-assisted semantic pruning with deterministic safeguards.
- Establishing reproducible, isolated, and durable test execution.
- Validating and calibrating the confidence scoring system.
- Completing GitHub integration and the developer-facing workflow.
- Strengthening authentication, authorization, tenant isolation, and platform security.
- Improving observability, recovery, scalability, and operational readiness.
- Conducting controlled pilots to validate Radius's actual business value.

## 1.2 Phase 3 Objective

By the end of Phase 3, Radius should be able to analyze a supported repository's pull request and deliver a traceable verification report that clearly communicates:

1. What changed in the PR.
2. Which symbols, files, modules, services, or tests may be affected.
3. Why those components are considered affected.
4. Which tests were selected and why.
5. Which tests were executed, skipped, failed, or unavailable.
6. What AI-assisted analysis contributed and what its limitations are.
7. What evidence supports the confidence assessment.
8. What uncertainties, unsupported constructs, or verification gaps remain.
9. What the developer should investigate before making a merge decision.

Radius must not guarantee that a PR is defect-free or safe to merge. It should provide explainable evidence that supports the developer's decision.

## 1.3 Phase 3 Success Definition

Phase 3 will be considered successful when Radius:

- Produces reproducible analysis results for supported repositories.
- Demonstrates measured correctness of its parsing, graph, blast-radius, and test-selection components.
- Detects and communicates incomplete analysis rather than silently treating missing evidence as proof of safety.
- Runs tests reliably in isolated environments.
- Maintains analysis and execution state across worker restarts and retries.
- Provides an explainable, evidence-backed confidence assessment.
- Integrates reliably with GitHub PRs and checks.
- Protects repository code, credentials, test environments, and customer data.
- Provides a usable dashboard and complete developer workflow.
- Demonstrates measurable value in controlled real-repository pilots.

---

# 2. Product Context

## 2.1 Product Vision

Radius is an AI-native Software Verification Platform that acts as an intelligence layer between code changes and production.

Traditional CI pipelines commonly execute predefined test suites. Radius aims to understand the change itself, determine its potential impact, and help developers focus verification effort where it is relevant.

Radius combines:

- Static repository intelligence.
- Code dependency analysis.
- Change-impact analysis.
- AI-assisted semantic reasoning.
- Predictive test selection.
- Automated test execution.
- Verification evidence aggregation.
- Explainable confidence assessment.
- GitHub-native developer workflows.

## 2.2 Core Product Goal

**Primary question:**

"Is this PR sufficiently verified for a developer to make an informed merge decision?"

Radius must answer this through evidence, not by treating an arbitrary confidence score as a guarantee.

## 2.3 Product Principles

### Repository intelligence first

Radius must understand repository structure and code relationships before making conclusions about the impact of changes.

### Deterministic analysis before AI

Deterministic parsing, graph analysis, and rules should provide the primary structural evidence. AI can supplement this evidence but must not silently override important deterministic findings.

### Explainability over automation

Every important finding should be traceable to source code, dependency relationships, test results, analysis rules, or clearly attributed AI output.

### Conservative verification

When Radius cannot establish the likely impact of a change, it must communicate the uncertainty and apply an appropriate fallback rather than silently omitting potentially relevant verification.

### Evidence over scores

Confidence must reflect evidence quality, completeness, freshness, and uncertainty. A numerical score alone is insufficient.

### Developer remains in control

Radius supports developer decision-making. It does not make an unconditional merge decision or guarantee the absence of defects.

### Security by design

Customer repositories and test code must be treated as untrusted. Isolation, access control, secrets management, and data protection must be integral to the architecture.

### Incremental intelligence

Radius should reuse repository intelligence where possible, while ensuring that incremental updates do not cause stale or incorrect analysis.

---

# 3. Current State and Phase 3 Scope

## 3.1 Existing Capabilities Reported in the Audit

The current implementation audit reports the following capabilities:

| Capability | Reported status |
|---|---|
| Multi-language CPG for Python and TypeScript/JavaScript using Tree-sitter | Complete |
| Line-precise diff parsing and symbol-level blast radius | Complete |
| Gemini 2.0 Flash semantic pruning | Complete, requires API key |
| Predictive test selection for pytest, Vitest, and Jest | Complete |
| Deterministic and dynamic confidence scoring | Complete |
| GitHub App, Check Runs, and PR comments | Complete |
| PostgreSQL persistence with 15+ domain models and Alembic | Complete |
| JUnit XML and JSON CI report ingestion | Complete |
| Background worker pipeline | Complete |
| FastAPI API, authentication, and idempotency | Complete |
| HMAC-validated GitHub webhooks | Complete |
| Next.js dashboard with 13+ pages | Approximately 90% |
| Signup, login, JWT, email verification, password reset | Complete |
| Docker Compose stack | Complete |
| Durable job queue | Not implemented |
| PR-number-to-UUID backend endpoint | Known gap |
| Email delivery | Not wired |
| E2E browser test stability | Known issue |
| GitHub App installation URL | Placeholder |

These are reported implementation statuses, not independently verified outcomes.

## 3.2 Phase 3 Is Not a Rewrite

Phase 3 should preserve working functionality and existing interfaces wherever practical.

The implementation approach should be:

- Audit before replacing.
- Reuse existing domain models and services when appropriate.
- Preserve established parser, graph, API, and analysis contracts unless a demonstrated defect requires change.
- Introduce changes incrementally.
- Add regression tests before changing critical behavior.
- Avoid duplicating existing functionality.
- Keep backward compatibility where feasible.
- Use benchmark evidence to prioritize changes.

## 3.3 Phase 3 Scope

### In scope

1. End-to-end validation and benchmark infrastructure.
2. Parser and semantic-resolution quality.
3. CPG and dependency-graph correctness.
4. Diff and blast-radius accuracy.
5. AI pruning validation and safeguards.
6. Predictive test-selection quality.
7. Test execution reliability and isolation.
8. CI result ingestion and evidence integrity.
9. Confidence score calibration and explainability.
10. Durable job processing and recovery.
11. GitHub workflow completion.
12. Dashboard workflow completion.
13. Authentication and authorization hardening.
14. Tenant isolation and data protection.
15. Observability and operational readiness.
16. Performance, scalability, and cost measurement.
17. Controlled pilot deployment and product validation.
18. Documentation, release management, and support readiness.

### Out of scope unless separately approved

- Replacing all existing infrastructure without a demonstrated need.
- Supporting every programming language and test framework.
- Guaranteeing defect-free software or fully autonomous merge approval.
- Building a general-purpose IDE.
- Replacing GitHub Actions or all existing CI providers.
- Building a complete SAST, DAST, penetration-testing, or vulnerability-management product.
- Automatically fixing every detected issue.
- Building a custom foundation model.
- Supporting arbitrary cloud providers and deployment topologies in the initial Phase 3 release.

These may become future roadmap items after validating the central product proposition.

---

# 4. Business Requirements

## 4.1 Business Objectives

| ID | Requirement | Priority |
|---|---|---|
| BR-001 | Radius must demonstrate that it can reduce unnecessary verification effort without unacceptable loss of fault detection. | Critical |
| BR-002 | Radius must provide evidence that developers can inspect and understand. | Critical |
| BR-003 | Radius must integrate naturally into existing GitHub pull-request workflows. | Critical |
| BR-004 | Radius must provide measurable value in time, compute usage, and developer effort. | Critical |
| BR-005 | Radius must maintain the integrity and confidentiality of connected repositories and execution environments. | Critical |
| BR-006 | Radius must operate reliably across supported repositories and test frameworks. | Critical |
| BR-007 | Radius must communicate uncertainty and unsupported analysis cases transparently. | Critical |
| BR-008 | Radius must support repeatable analysis and investigation of historical results. | High |
| BR-009 | Radius must provide an operational model suitable for controlled external pilots. | High |
| BR-010 | Radius must establish measurable product-quality metrics for future releases. | High |
| BR-011 | Radius must support customer onboarding and repository configuration without extensive manual engineering intervention. | High |
| BR-012 | Radius must establish a foundation for future language, framework, and CI-provider expansion. | Medium |

## 4.2 Target Users

### Primary users

**Software developers**

- Want to understand the impact of their PR.
- Want faster feedback without losing relevant test coverage.
- Need actionable evidence and clear explanations.
- Want results in the GitHub workflow they already use.

**Tech leads and engineering managers**

- Need visibility into verification quality and risk.
- Want to reduce unnecessary CI execution.
- Need confidence that important tests are not routinely omitted.
- Want consistent verification practices across repositories.

### Secondary users

**QA engineers**

- Need visibility into test selection, execution, failures, and coverage gaps.
- Want to understand how code changes relate to test suites.

**DevOps and platform engineers**

- Need reliable job execution, monitoring, integrations, and operational controls.

**Security and compliance teams**

- Need evidence of access controls, secure execution, traceability, and data handling.

**Repository administrators**

- Need control over installation, permissions, repository onboarding, configuration, and retention.

## 4.3 Business Value Proposition

Radius should validate four central value propositions.

| Value proposition | How it is demonstrated |
|---|---|
| Reduced verification effort | Fewer unnecessary tests or lower execution time, measured against a baseline |
| Improved impact visibility | Developers can inspect changed symbols and potential downstream effects |
| Better verification evidence | Selected tests, outcomes, uncertainty, and analysis explanations are traceable |
| More informed merge decisions | Developers report that Radius findings are useful and understandable |

The product must not claim that a reduced test suite is equivalent to a full test suite unless the evidence supports that claim for the specific supported context.

## 4.4 Business Metrics

The following are proposed initial targets for the controlled benchmark. They are targets to validate, not claims about current performance. They should be refined after baseline measurements.

| Metric | Proposed target | Measurement |
|---|---:|---|
| Benchmark impact-analysis recall | ≥ 95% | Expected affected entities identified |
| Benchmark test-selection recall | ≥ 95% | Relevant tests selected against the benchmark's full relevant test set |
| Test execution reduction | ≥ 30% on suitable benchmark PRs | Compared with the baseline full test suite |
| Verification result attribution | 100% | Results tied to exact repository, PR, commit, and run |
| Duplicate job safety | 100% in defined duplicate-event tests | Duplicate webhook and retry scenarios |
| Durable job recovery | 100% of injected worker-restart scenarios recover or reach an explicit terminal failure | Fault-injection tests |
| Core workflow E2E | 100% of release-blocking scenarios pass | Browser and GitHub integration tests |
| Analysis explainability | 100% of critical findings have traceable evidence or a stated uncertainty | Evidence audit |
| Silent analysis incompleteness | 0 in benchmark scenarios | Incomplete analysis must be explicitly surfaced |
| Pilot onboarding completion | ≥ 90% of supported pilot setups without engineering intervention | Pilot onboarding tracking |
| Pilot developer usefulness | Measured and reviewed against a pre-agreed survey baseline | Pilot feedback |
| Cost per analyzed PR | Establish baseline, then optimize | Compute, model, storage, and execution costs |

A high test-selection recall target must not encourage Radius to label every test as relevant merely to achieve the metric. Precision and execution savings must be measured alongside recall.

## 4.5 Business Constraints

- Initial language support remains Python and TypeScript/JavaScript.
- Initial test-runner support remains pytest, Vitest, and Jest.
- GitHub remains the initial primary source-control integration.
- Gemini remains the initial AI provider unless evaluation justifies an alternative.
- Existing PostgreSQL and FastAPI-based services should be reused where practical.
- Production-readiness claims must be based on verified evidence.
- Customer repository code must not be used for model training without explicit authorization and an appropriate data-use agreement.
- Any external pilot must define repository access, data retention, support expectations, and incident handling.

---

# 5. Technical Requirements

## 5.1 End-to-End System Workflow

The target Phase 3 workflow is:

1. A user installs Radius's GitHub App and authorizes selected repositories.
2. Radius receives and validates GitHub events.
3. Radius identifies the repository, PR, base commit, head commit, and relevant installation.
4. The API validates permissions and creates or updates a verification job.
5. A durable queue stores the job for processing.
6. The worker retrieves the correct repository revision in an isolated workspace.
7. Radius loads or builds repository intelligence for the relevant commit.
8. The diff analyzer identifies changed files, lines, and symbols.
9. The graph analyzer traces potential impact across repository relationships.
10. Deterministic analysis identifies potentially affected components and relevant tests.
11. AI-assisted semantic pruning may refine or annotate the analysis within strict safeguards.
12. Radius selects tests and records selection reasons, uncertainty, and fallbacks.
13. Selected tests execute in a controlled sandbox.
14. Radius ingests test results, logs, and supported CI reports.
15. Evidence is validated and associated with the exact analysis and commit.
16. The confidence engine computes an explainable assessment.
17. The analysis result is persisted.
18. GitHub Checks and PR comments are updated idempotently.
19. The dashboard presents the change impact, selected tests, results, confidence evidence, and limitations.
20. Developers review the evidence and make their own merge decision.

Each stage must have an explicit state, traceable inputs, outputs, failure modes, and retry behavior.

## 5.2 Target Architecture

The existing monorepo architecture should be retained unless the Phase 3 audit establishes that structural changes are necessary.

```text
Radius Monorepo
│
├── apps/
│   ├── dashboard/             # Next.js developer dashboard
│   ├── api/                   # FastAPI REST API and webhooks
│   └── worker/                # Durable background processing
│
├── packages/
│   ├── parser/                # Language parsing and symbol extraction
│   ├── graph/                 # CPG and dependency graph
│   ├── analyzer/              # Diff and impact analysis
│   ├── test-intelligence/     # Test discovery and selection
│   ├── execution/             # Sandboxed test execution
│   ├── confidence/            # Evidence and confidence engine
│   ├── github/                # GitHub App and Check integration
│   ├── database/              # SQLAlchemy models and persistence
│   ├── ai/                    # AI provider and semantic pruning
│   └── shared/                # Shared contracts and utilities
│
├── infrastructure/
│   ├── docker/
│   ├── deployment/
│   ├── monitoring/
│   └── ci/
│
├── benchmarks/
│   ├── repositories/
│   ├── scenarios/
│   ├── ground-truth/
│   └── reports/
│
└── tests/
    ├── unit/
    ├── integration/
    ├── end-to-end/
    ├── security/
    ├── performance/
    └── fault-injection/
```

This is a target logical structure. Phase 3 must first compare it with the actual repository and avoid moving modules simply to match the diagram.

### Core infrastructure

- PostgreSQL for durable application and analysis data.
- A durable Redis-backed queue or equivalent supported job broker.
- FastAPI for API and webhook processing.
- Worker services for analysis and test execution orchestration.
- Isolated execution environments for untrusted repository code.
- Next.js dashboard.
- GitHub App for repository integration.
- Object storage only if needed for large logs, reports, or artifacts.
- Centralized logs, metrics, traces, and operational alerts.

The queue and execution infrastructure must be treated as separate concerns. Redis may coordinate jobs, but the database must retain the authoritative business and analysis state.

---

# 6. Repository Intelligence and Parsing

## 6.1 Objective

Improve the accuracy, completeness, and traceability of repository understanding so that downstream impact analysis and test selection have reliable structural evidence.

## 6.2 Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| PAR-001 | Parse supported Python and TypeScript/JavaScript source files using the existing Tree-sitter-based approach. | Critical |
| PAR-002 | Extract files, modules, classes, functions, methods, imports, exports, and relevant declarations. | Critical |
| PAR-003 | Preserve source locations, including file path and line ranges, for extracted entities. | Critical |
| PAR-004 | Resolve imports, aliases, and re-exports wherever supported. | Critical |
| PAR-005 | Identify unresolved symbols and dependencies explicitly. | Critical |
| PAR-006 | Handle syntax errors and partially valid files without silently discarding the entire repository. | High |
| PAR-007 | Handle file renames, moves, deletions, and additions in repository updates. | Critical |
| PAR-008 | Maintain stable entity identity where feasible across incremental updates. | High |
| PAR-009 | Record language, parser version, parser status, and extraction metadata. | High |
| PAR-010 | Exclude or specially classify generated, vendored, binary, and unsupported files. | High |
| PAR-011 | Support full and incremental repository analysis. | High |
| PAR-012 | Report parsing coverage and limitations to downstream analysis. | Critical |

## 6.3 Semantic Resolution

Tree-sitter provides syntax structure, but Radius must add the semantic logic needed for useful dependency analysis.

Phase 3 must assess and improve:

- Relative and absolute imports.
- Import aliases.
- Namespace and package imports.
- Re-exports and barrel files.
- Python package and module relationships.
- Python decorators and inheritance.
- TypeScript interfaces, types, generics, and inheritance.
- Function and method calls where statically resolvable.
- Constructor and class relationships.
- Framework-specific routing and dependency injection where included in supported scope.
- Dynamic imports and reflective patterns.
- Cross-file symbol references.
- Monorepo package boundaries.
- Test files and test-to-code relationships.

Not all dynamic behavior can be resolved statically. Unsupported or ambiguous relationships must be represented as unresolved or inferred, with their confidence and origin recorded.

## 6.4 Parser Contracts

Before modifying parsers, document the current public interface.

The parser contract must define:

- Input source representation.
- Repository-relative path format.
- Language identification.
- Output node types.
- Output relationship types.
- Source location conventions.
- Error and warning representation.
- Versioning expectations.
- Behavior for unsupported syntax.
- Incremental update semantics.

Parser migration or improvements must preserve downstream interfaces where practical. If a contract changes, all consumers and migration impacts must be identified before implementation.

## 6.5 Graph Requirements

The CPG/dependency graph should represent:

- Repository.
- Commit.
- File.
- Module.
- Package.
- Class.
- Function or method.
- Test.
- Import/export relationships.
- Calls and references where statically resolvable.
- Inheritance and implementation relationships.
- Test-to-code associations.
- Other explicitly supported dependency types.

Each edge must define its meaning, source, resolution method, and reliability.

Graph analysis must distinguish:

- Direct dependencies.
- Transitive dependencies.
- Statically resolved relationships.
- Heuristically inferred relationships.
- Unresolved relationships.
- Historical or stale relationships.

The graph must be scoped to the correct repository and commit. Results from a previous commit must not be presented as current without an explicit freshness status.

## 6.6 Incremental Analysis

Radius should avoid rebuilding all repository intelligence for every small PR where safe incremental processing is possible.

Requirements:

- Identify changed files.
- Invalidate affected graph entities and relationships.
- Reparse changed or dependent files as needed.
- Reconcile incremental graph state with the target commit.
- Detect stale graph data.
- Support full rebuilds for recovery or validation.
- Record graph build version, parser version, commit SHA, and processing timestamp.
- Make incremental results comparable to full-build results in benchmark scenarios.

## 6.7 Acceptance Criteria

- All supported syntax and relationship categories have tests.
- Parser output is validated against labeled source fixtures.
- Unresolved relationships are visible.
- Graph output is deterministic for identical input and analysis versions.
- Renames, moves, and deletions do not leave stale relationships.
- Incremental graph updates match full rebuilds within the defined benchmark tolerance.
- Incomplete parsing is surfaced to blast-radius and confidence components.

---

# 7. Diff Analysis and Blast-Radius Accuracy

## 7.1 Objective

Identify the direct and indirect effects of a PR and provide explainable dependency paths from changed code to potentially affected components.

## 7.2 Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| IMP-001 | Identify added, modified, deleted, and renamed files. | Critical |
| IMP-002 | Map changed lines to symbols when possible. | Critical |
| IMP-003 | Identify changes that cannot be mapped to symbols. | Critical |
| IMP-004 | Trace direct and transitive dependencies. | Critical |
| IMP-005 | Calculate symbol-, file-, module-, and package-level impact. | Critical |
| IMP-006 | Preserve a traceable path explaining why an entity is considered affected. | Critical |
| IMP-007 | Handle deletions and renamed symbols without relying only on current source state. | Critical |
| IMP-008 | Detect configuration and dependency-manifest changes. | High |
| IMP-009 | Represent unresolved or dynamic dependencies. | Critical |
| IMP-010 | Provide impact analysis for multiple changed files in a single PR. | Critical |
| IMP-011 | Prevent stale graph data from being treated as current. | Critical |
| IMP-012 | Support configurable impact depth where appropriate. | Medium |

## 7.3 Impact Analysis Model

For each changed symbol or file, Radius should identify:

- Direct callers or dependents.
- Transitive dependents.
- Affected modules and packages.
- Related tests.
- Relevant configuration and runtime boundaries.
- Unresolved potential relationships.
- Impact paths and the rules that produced them.

The system must distinguish potential impact from confirmed runtime impact.

For example, a reverse dependency path indicates that a component may be affected. It does not prove that the relevant code path will execute in production.

## 7.4 Change Categories

The benchmark and implementation must cover:

- Function body changes.
- Function signature changes.
- Class and method changes.
- Interface and type changes.
- Import and export changes.
- Dependency upgrades and removals.
- File and module renames.
- Deleted code.
- Configuration changes.
- Environment variable changes.
- API route and request/response schema changes.
- Database model and migration changes.
- Test changes.
- Build and package configuration changes.
- Changes affecting dynamically resolved behavior.

## 7.5 Impact Explanation

Every reported affected entity should provide:

- Entity type and name.
- Repository-relative path.
- Relevant line range where available.
- Originating changed symbol or file.
- Dependency path.
- Direct or transitive relationship.
- Relationship resolution type.
- Impact depth.
- Any relevant uncertainty or unsupported behavior.

## 7.6 Acceptance Criteria

- Impact analysis is validated against manually labeled PR scenarios.
- False negatives are measured and investigated.
- The system does not silently exclude entities because a relationship could not be resolved.
- Deleted and renamed entities remain traceable through diff metadata.
- Identical inputs and versions produce deterministic impact results.
- Dashboard and GitHub output use consistent impact data.

---

# 8. AI-Assisted Semantic Pruning

## 8.1 Objective

Use AI to supplement deterministic analysis by interpreting semantic context and potentially reducing unnecessary verification effort, without compromising traceability or silently excluding relevant impact.

## 8.2 Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| AI-001 | Use AI only through a defined provider abstraction. | High |
| AI-002 | Preserve deterministic impact results before AI pruning. | Critical |
| AI-003 | Record AI input context, output, model identifier, and analysis version, subject to privacy controls. | Critical |
| AI-004 | Validate AI output against a strict schema. | Critical |
| AI-005 | Reject malformed, incomplete, or unsupported AI responses safely. | Critical |
| AI-006 | Record the reason for each pruning or prioritization decision. | Critical |
| AI-007 | Support deterministic fallback when the AI provider is unavailable. | Critical |
| AI-008 | Track AI latency, token usage, error rate, and cost. | High |
| AI-009 | Protect against prompt injection from repository content. | Critical |
| AI-010 | Allow AI pruning to be disabled by configuration or policy. | High |
| AI-011 | Evaluate AI decisions against benchmark ground truth. | Critical |
| AI-012 | Prevent AI from changing source code, executing commands, or obtaining unauthorized credentials. | Critical |

## 8.3 AI Decision Boundaries

AI may:

- Interpret code-change context.
- Explain likely semantic impact.
- Classify relationships for review.
- Suggest test prioritization.
- Provide a natural-language explanation of deterministic findings.
- Identify potential areas that require additional verification.

AI must not:

- Override the evidence of failed tests.
- Remove a deterministic impact path without an auditable rule and benchmarked justification.
- Claim a PR is safe solely based on a language-model response.
- Execute arbitrary repository instructions.
- Access secrets or credentials outside its approved context.
- Convert missing evidence into a positive safety claim.

## 8.4 AI Output Contract

AI responses should be validated against a structured contract containing:

- Analysis identifier.
- Entity or dependency reference.
- Classification.
- Explanation.
- Supporting source references.
- Confidence or uncertainty estimate, if used.
- Suggested action.
- Model and prompt version.
- Whether the result affects prioritization, display, or selection.
- Any schema-validation or fallback status.

The output must be treated as untrusted data and must not be executed as code.

## 8.5 Prompt Injection Protection

Repository content is untrusted input. Comments, strings, documentation, test names, and source files may contain adversarial instructions.

Controls must include:

- Clear separation between system instructions and repository data.
- Structured input rather than unrestricted prompt concatenation.
- No tool execution based on repository instructions.
- Strict response schema validation.
- Explicit limits on context size and sensitive content.
- Redaction or exclusion of secrets.
- Monitoring for unexpected or malformed output.
- Deterministic fallback.

## 8.6 AI Evaluation

Benchmark AI against deterministic analysis and manually labeled scenarios.

Measure:

- Precision and recall of AI classifications.
- False-negative pruning rate.
- False-positive retention rate.
- Agreement with expert labels.
- Stability across repeated calls.
- Latency and cost.
- Performance when repository context is incomplete.
- Behavior when the model fails or returns invalid data.

AI should only influence test selection where benchmark results demonstrate an acceptable risk profile.

## 8.7 Acceptance Criteria

- AI decisions are traceable and versioned.
- Invalid AI output cannot corrupt the analysis pipeline.
- AI failure does not prevent deterministic analysis.
- AI pruning does not silently remove required verification.
- Prompt-injection scenarios are included in security tests.
- AI contribution and limitations are visible in the final report.

---

# 9. Predictive Test Selection

## 9.1 Objective

Select tests that are relevant to the changed code while measuring and controlling the risk of omitting tests that could detect a regression.

## 9.2 Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| TST-001 | Discover supported tests for pytest, Vitest, and Jest. | Critical |
| TST-002 | Map tests to source files and symbols where evidence exists. | Critical |
| TST-003 | Use dependency graph information in test selection. | Critical |
| TST-004 | Record why each test was selected. | Critical |
| TST-005 | Record tests not selected and the reason. | High |
| TST-006 | Support full-suite fallback. | Critical |
| TST-007 | Support configurable selection policies. | High |
| TST-008 | Use runtime coverage where available. | High |
| TST-009 | Use historical test outcomes and execution times as prioritization signals. | High |
| TST-010 | Handle test renames, moved tests, and removed tests. | High |
| TST-011 | Identify tests with missing or unreliable mappings. | Critical |
| TST-012 | Track selection metrics against full-suite benchmark runs. | Critical |
| TST-013 | Support manual test-selection overrides where configured. | Medium |
| TST-014 | Distinguish selected, scheduled, started, completed, skipped, failed, and unavailable tests. | Critical |

## 9.3 Test Selection Inputs

- Changed files.
- Changed symbols.
- Dependency graph.
- Test discovery output.
- Test-to-code mapping.
- Coverage data.
- Historical execution records.
- Framework configuration.
- Repository-specific test commands.
- User-defined selection policies.
- Parsing completeness.
- AI-assisted prioritization, when enabled.

## 9.4 Selection Strategy

The selection process should be layered:

1. Identify tests directly associated with changed symbols or files.
2. Identify tests associated with dependent components in the blast radius.
3. Use runtime coverage to strengthen test-to-code associations where available.
4. Use historical test information for prioritization and scheduling.
5. Include tests required by repository-specific policies.
6. Apply AI-assisted recommendations only within validated safeguards.
7. Expand selection or run the full suite when analysis completeness is inadequate.
8. Record every inclusion, exclusion, fallback, and uncertainty.

## 9.5 Selection Modes

Radius should support configurable modes.

**Conservative mode**

- Prioritizes recall.
- Expands selection when analysis is uncertain.
- Uses full-suite fallback for defined high-risk scenarios.
- Suitable as the default during initial pilots.

**Balanced mode**

- Uses validated graph and coverage evidence.
- Prioritizes relevant tests while maintaining defined fallback rules.
- Suitable after benchmark validation.

**Experimental mode**

- Enables testing of new selection algorithms and AI strategies.
- Clearly labels results as experimental.
- Must not be represented as equivalent to validated selection.

The precise policies and thresholds must be configurable and versioned.

## 9.6 Test Selection Metrics

**Recall**

\[
\text{Recall} =
\frac{\text{Relevant tests selected}}
{\text{All relevant tests in the benchmark}}
\]

**Precision**

\[
\text{Precision} =
\frac{\text{Relevant tests selected}}
{\text{All selected tests}}
\]

**Test reduction**

\[
\text{Test Reduction} =
1 -
\frac{\text{Selected tests}}
{\text{Baseline tests}}
\]

The benchmark must define what constitutes a relevant test. Depending on the scenario, relevance may be established through coverage, controlled fault injection, manually reviewed impact, or a combination.

## 9.7 Full-Suite Fallback Triggers

The following cases should be assessed for conservative fallback:

- Incomplete parsing of changed files.
- Significant unresolved dependency relationships.
- Large-scale refactoring.
- Build or test configuration changes.
- Dependency-manifest changes.
- Unknown frameworks or test commands.
- Missing or stale test mappings.
- Graph integrity failures.
- High-impact changes where analysis uncertainty exceeds configured limits.
- AI service failure when a configured policy requires AI-assisted evidence.
- Changes to shared modules with broad downstream dependencies.

The fallback policy must be explicit, configurable, and testable.

## 9.8 Acceptance Criteria

- Selection results are reproducible for identical inputs and versions.
- Benchmark recall, precision, and test reduction are measured.
- Every selected test has an explanation.
- Important selection gaps are surfaced.
- Full-suite fallback works.
- AI cannot bypass selection safeguards.
- Selection results are linked to the exact commit and analysis version.

---

# 10. Test Execution and Isolation

## 10.1 Objective

Execute selected tests safely and reproducibly without allowing untrusted repository code to compromise the Radius platform, other customers, or infrastructure.

## 10.2 Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| EXE-001 | Execute tests in isolated, disposable environments. | Critical |
| EXE-002 | Apply CPU, memory, storage, and execution-time limits. | Critical |
| EXE-003 | Control network access from test environments. | Critical |
| EXE-004 | Prevent unauthorized access to host credentials and environment secrets. | Critical |
| EXE-005 | Support the approved Python and Node.js runtime versions. | Critical |
| EXE-006 | Support repository-specific setup and test commands under an explicit policy. | High |
| EXE-007 | Capture test output, exit codes, durations, and structured results. | Critical |
| EXE-008 | Support timeout, cancellation, and cleanup. | Critical |
| EXE-009 | Record environment metadata for reproducibility. | High |
| EXE-010 | Handle partial execution and partial report generation. | Critical |
| EXE-011 | Associate all test results with exact commit and job identifiers. | Critical |
| EXE-012 | Support retries without duplicating or corrupting final results. | Critical |
| EXE-013 | Ensure workspace and artifact cleanup. | Critical |
| EXE-014 | Prevent cross-tenant workspace or artifact access. | Critical |

## 10.3 Execution Lifecycle

Each execution must follow a defined lifecycle:

```text
QUEUED
  ↓
PREPARING
  ↓
ENVIRONMENT_READY
  ↓
RUNNING
  ↓
COLLECTING_RESULTS
  ↓
VALIDATING_RESULTS
  ↓
COMPLETED
```

Terminal or exceptional states should include:

- FAILED
- TIMED_OUT
- CANCELLED
- RETRY_PENDING
- PARTIAL
- INFRASTRUCTURE_ERROR

State transitions must be validated and persisted.

## 10.4 Sandbox Security

Treat all repository code, test scripts, package lifecycle hooks, and build commands as untrusted.

Controls should include:

- Disposable container or stronger isolation technology.
- Non-root execution.
- Read-only host mounts wherever possible.
- Restricted filesystem access.
- No Docker socket exposure to untrusted workloads.
- No unrestricted host networking.
- Explicit outbound network policies.
- CPU and memory quotas.
- Process count and execution limits.
- Storage limits.
- Restricted environment variables.
- Short-lived, scoped credentials where absolutely required.
- Secret redaction in logs.
- Workspace destruction after execution.
- Security event logging.

The execution isolation design must be reviewed against the actual threat model and deployment environment. Containers alone should not be assumed to provide sufficient isolation for every threat.

## 10.5 Reproducibility

Record:

- Repository identifier.
- Commit SHA.
- Runtime version.
- Dependency lockfile or package metadata.
- Test command.
- Environment configuration version.
- Sandbox image or environment version.
- Selected test identifiers.
- Execution timestamps.
- Exit codes.
- Test results.
- Relevant execution logs.

Reproducibility does not require storing every environment artifact forever. Retention should be policy-driven.

## 10.6 Acceptance Criteria

- Untrusted code cannot access platform secrets through supported execution paths.
- Resource limits are enforced.
- Timeouts and cancellation work.
- Failed workers do not leave uncontrolled execution processes.
- Every test result is associated with the correct run and commit.
- Repeated execution under equivalent conditions produces explainable results.
- Workspace cleanup is verified.

---

# 11. CI Report Ingestion and Evidence Integrity

## 11.1 Objective

Normalize external and internally generated test results into a trustworthy evidence model.

## 11.2 Functional Requirements

- Support the already reported JUnit XML and JSON formats.
- Validate report schema and size limits.
- Reject malformed or unsupported reports with explicit error states.
- Deduplicate repeated ingestion.
- Associate results with repository, commit, PR, analysis, and execution identifiers.
- Distinguish passed, failed, skipped, errored, flaky, and unknown results where supported.
- Track report source and provenance.
- Prevent stale results from updating a newer commit's confidence.
- Support partial reports.
- Track missing test results.
- Preserve permitted raw artifacts for troubleshooting.
- Normalize test names and identifiers consistently.

## 11.3 Evidence Provenance

Each evidence item should include:

- Evidence identifier.
- Evidence type.
- Source system.
- Repository and commit.
- Analysis identifier.
- Execution identifier, where applicable.
- Timestamp.
- Evidence payload or artifact reference.
- Validation status.
- Freshness status.
- Confidence or reliability metadata where appropriate.
- Retention classification.

Evidence must not be silently overwritten by a newer or older run.

## 11.4 Acceptance Criteria

- Duplicate reports do not create duplicate evidence.
- Stale reports cannot update current analysis.
- Invalid reports are rejected safely.
- Partial reports produce partial verification states.
- Evidence provenance is visible in the API and dashboard.

---

# 12. Confidence Scoring and Evidence Engine

## 12.1 Objective

Provide an explainable assessment of verification evidence, completeness, and uncertainty for a specific PR and commit.

## 12.2 Core Requirement

The confidence score must not be presented as a verified probability of a PR being defect-free unless that interpretation is empirically validated through an appropriate calibration process.

The score must be tied to:

- Evidence availability.
- Evidence quality.
- Analysis completeness.
- Test-selection quality.
- Test execution results.
- Freshness of the analysis.
- Unresolved dependencies.
- Unsupported syntax or frameworks.
- AI contribution and limitations.
- Policy requirements.

## 12.3 Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| CON-001 | Preserve deterministic scoring components. | Critical |
| CON-002 | Document score inputs, weights, rules, and version. | Critical |
| CON-003 | Distinguish observations from inferences. | Critical |
| CON-004 | Include analysis completeness and uncertainty. | Critical |
| CON-005 | Identify missing, skipped, failed, or stale evidence. | Critical |
| CON-006 | Prevent incomplete analysis from appearing fully verified. | Critical |
| CON-007 | Provide evidence-level explanations for score components. | Critical |
| CON-008 | Version scoring algorithms and thresholds. | High |
| CON-009 | Support calibration evaluation against benchmark outcomes. | Critical |
| CON-010 | Record score changes and the evidence that caused them. | High |
| CON-011 | Support an explicit insufficient-evidence state. | Critical |
| CON-012 | Ensure score consistency between API, dashboard, and GitHub Checks. | Critical |

## 12.4 Evidence Categories

The confidence engine should account for the following categories.

### Repository understanding

- Parsing coverage.
- Symbol extraction quality.
- Dependency resolution.
- Graph integrity.
- Unresolved relationships.
- Incremental graph freshness.

### Change analysis

- Diff completeness.
- Changed-symbol mapping.
- Unmapped changed lines.
- Change category.
- Potential impact breadth.
- Uncertainty in the impact graph.

### Test selection

- Test discovery completeness.
- Test-to-code mapping quality.
- Selection policy.
- Benchmark-backed selection characteristics.
- Fallback use.
- Selection uncertainty.

### Test execution

- Selected tests completed.
- Tests failed.
- Tests skipped.
- Tests timed out.
- Tests unavailable.
- Execution environment integrity.
- Test-result freshness.
- Flaky-test indicators.

### External evidence

- Validated CI reports.
- Coverage information.
- Existing test outcomes.
- Repository policies.
- Approved external checks.

### AI evidence

- AI provider and model version.
- Whether AI was enabled.
- Whether AI output was valid.
- What AI decisions influenced.
- Whether deterministic fallback occurred.
- Relevant uncertainty.

## 12.5 Score Presentation

The dashboard and GitHub Check should communicate:

- Confidence score, where sufficient evidence supports displaying it.
- Score version.
- Overall verification status.
- Key positive evidence.
- Important negative evidence.
- Missing evidence.
- Analysis limitations.
- Reasons for uncertainty.
- Links to affected entities and test results.

Suggested verification states:

- **Verification complete:** Configured checks and evidence requirements have completed.
- **Verification incomplete:** Required evidence is missing or analysis is incomplete.
- **Issues detected:** Failures or important findings require review.
- **Insufficient evidence:** Available evidence does not support a meaningful confidence assessment.
- **Analysis failed:** The system could not reliably complete the analysis.

These states describe verification outcomes, not automatic merge approval.

## 12.6 Calibration

Evaluate the confidence score using:

- Labeled benchmark scenarios.
- Controlled fault injection.
- Historical defects where appropriate data is available.
- Repeated analysis runs.
- Different repository sizes and structures.
- Different test-selection policies.
- Known incomplete-analysis cases.

Assess:

- Calibration error if a probability interpretation is proposed.
- Correlation with known defects and verification failures.
- Score stability.
- Sensitivity to missing evidence.
- False reassurance cases.
- Score changes when evidence is added, removed, or invalidated.

If evidence is insufficient to validate a probabilistic interpretation, retain the score as a clearly defined heuristic or evidence index and label it accordingly.

## 12.7 Acceptance Criteria

- Score components are documented and versioned.
- The score is reproducible from stored evidence and its algorithm version.
- Missing evidence is visible.
- Incomplete analysis cannot appear fully verified.
- Score calibration is evaluated and documented.
- The final report provides explanations rather than an unexplained number.

---

# 13. Durable Background Processing

## 13.1 Objective

Ensure verification jobs are durable, recoverable, idempotent, and correctly associated with their source events.

## 13.2 Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| JOB-001 | Replace the in-memory queue with a durable job-processing mechanism. | Critical |
| JOB-002 | Persist authoritative job state in PostgreSQL. | Critical |
| JOB-003 | Support safe retry and recovery after worker failure. | Critical |
| JOB-004 | Enforce idempotency for webhook-triggered work. | Critical |
| JOB-005 | Prevent duplicate processing from producing conflicting final results. | Critical |
| JOB-006 | Support job cancellation. | High |
| JOB-007 | Support job priorities and configurable concurrency. | High |
| JOB-008 | Track job attempts, errors, timestamps, and worker assignment. | Critical |
| JOB-009 | Detect stale or abandoned jobs. | Critical |
| JOB-010 | Support queue health and backlog monitoring. | High |
| JOB-011 | Support controlled retry policies and dead-letter handling. | High |
| JOB-012 | Support graceful worker shutdown. | High |

## 13.3 Job Model

A job should contain:

- Job ID.
- Organization ID.
- Repository ID.
- PR number.
- Base SHA.
- Head SHA.
- Webhook delivery ID, where applicable.
- Job type.
- Priority.
- Current state.
- Retry count.
- Creation and update timestamps.
- Worker or execution assignment.
- Analysis ID.
- Failure category.
- Error summary.
- Idempotency key.
- Cancellation state.

## 13.4 Idempotency

Idempotency must cover:

- Webhook delivery.
- Job creation.
- Analysis initialization.
- Test execution scheduling.
- Report ingestion.
- Confidence calculation.
- GitHub Check creation and updates.
- PR comment updates.

The same event must not cause uncontrolled duplicate work or conflicting Check Runs.

## 13.5 Recovery

The system must recover from:

- API restart.
- Worker restart.
- Redis restart.
- Database connection loss.
- Execution sandbox failure.
- AI provider outage.
- GitHub API rate limiting.
- Partial test execution.
- Duplicate webhook delivery.
- Delayed webhook delivery.
- Job timeout.

## 13.6 Acceptance Criteria

- Jobs survive process restarts.
- Recovery behavior is deterministic and documented.
- Duplicate events do not create inconsistent analyses.
- Stuck jobs are detectable.
- Failed jobs have traceable error categories.
- Queue and worker health are observable.

---

# 14. GitHub Integration

## 14.1 Objective

Provide reliable and secure integration with GitHub repositories, PRs, webhooks, Check Runs, and developer feedback.

## 14.2 Functional Requirements

- Complete GitHub App installation URL and setup.
- Support repository selection and installation permissions.
- Validate webhook signatures.
- Handle ping, push, pull request, and installation events.
- Support duplicate, delayed, and out-of-order events.
- Associate all results with the correct installation and repository.
- Handle app uninstallation and permission removal.
- Support PR synchronization and commit updates.
- Create or update Check Runs idempotently.
- Publish concise PR comments where enabled.
- Include dashboard links to detailed analysis.
- Handle API rate limits and transient failures.
- Support rerun or refresh workflows where authorized.
- Avoid publishing stale results to a newer PR commit.

## 14.3 GitHub Check Content

The Check Run should include:

- Analysis status.
- Commit SHA.
- Summary of changed components.
- Important affected components.
- Selected and executed test summary.
- Failed and skipped tests.
- Confidence evidence summary.
- Verification limitations.
- Link to the detailed Radius analysis.

The Check must distinguish successful verification from successful infrastructure execution. For example, an analysis that completes but discovers failed tests must not be reported as an all-clear result.

## 14.4 PR Comments

PR comments should be:

- Concise.
- Updated rather than duplicated where appropriate.
- Linked to a specific analysis.
- Clear about the tested commit.
- Explicit about incomplete evidence.
- Free of secrets and sensitive execution logs.
- Configurable by repository or organization policy.

## 14.5 Acceptance Criteria

- Installation and removal flows work.
- All supported webhook events are tested.
- Duplicate delivery is safe.
- Checks are correctly associated with commit SHAs.
- Stale analyses cannot overwrite current PR results.
- Rate limiting and temporary GitHub failures are handled.
- PR comments are updated idempotently.

---

# 15. Dashboard and Developer Experience

## 15.1 Objective

Provide a coherent interface through which developers can understand Radius's analysis and inspect the evidence behind its conclusions.

## 15.2 Required User Journeys

### Journey A: Signup and onboarding

1. User creates an account.
2. User verifies email where enabled.
3. User signs in.
4. User connects or installs the GitHub App.
5. User authorizes repositories.
6. User configures or confirms supported test settings.
7. Radius performs an initial repository analysis.
8. User views repository readiness and analysis status.

### Journey B: PR analysis

1. Developer opens a PR.
2. GitHub sends an event to Radius.
3. Radius creates a verification job.
4. The dashboard shows the job as queued or processing.
5. Analysis progresses through defined stages.
6. Results appear when available.
7. Developer opens the detailed analysis.
8. Developer inspects impact, tests, results, confidence evidence, and limitations.

### Journey C: Investigating a finding

1. Developer opens an affected entity.
2. Radius displays its source location.
3. Developer reviews the impact path.
4. Developer inspects related tests.
5. Developer reviews test output and evidence provenance.
6. Developer understands why the entity was included and what uncertainty remains.

### Journey D: Rerun and refresh

1. Developer requests an authorized rerun.
2. Radius creates a new run with a new execution identity.
3. The prior analysis remains available.
4. The dashboard shows both runs and their differences.
5. The latest run is clearly identified and associated with its commit.

### Journey E: Organization administration

1. Admin views connected repositories and members.
2. Admin reviews permissions and integration status.
3. Admin manages repository policies.
4. Admin views usage and operational status.
5. Admin removes or disconnects repositories where authorized.

## 15.3 Dashboard Requirements

| ID | Requirement | Priority |
|---|---|---|
| UI-001 | Fix the PR-number-to-UUID navigation issue. | Critical |
| UI-002 | Ensure all core routes are connected to valid API contracts. | Critical |
| UI-003 | Show analysis and execution status in real time or near real time. | High |
| UI-004 | Show repository and PR identity, including exact commit SHA. | Critical |
| UI-005 | Display changed files and symbols. | Critical |
| UI-006 | Display blast-radius graph and impact paths. | Critical |
| UI-007 | Display test selection and selection reasons. | Critical |
| UI-008 | Display test outcomes and execution logs according to access policy. | Critical |
| UI-009 | Display confidence components and uncertainty. | Critical |
| UI-010 | Display parsing and graph completeness. | Critical |
| UI-011 | Display AI involvement and fallback status. | High |
| UI-012 | Support filtering and search for affected entities and tests. | High |
| UI-013 | Support loading, empty, error, partial, and stale states. | Critical |
| UI-014 | Support accessible and responsive layouts. | High |
| UI-015 | Support role-aware organization and repository views. | High |
| UI-016 | Preserve historical analysis results. | High |
| UI-017 | Provide safe rerun and refresh controls. | High |
| UI-018 | Provide an operationally useful repository onboarding view. | High |

## 15.4 User Experience Requirements

- Make the primary PR result understandable at a glance.
- Provide progressive disclosure from summary to technical evidence.
- Use consistent terminology across the dashboard and GitHub Checks.
- Distinguish observed evidence from inferred impact.
- Avoid implying that green indicators prove the absence of defects.
- Make failures and incomplete evidence prominent without exaggeration.
- Keep source navigation and impact paths accessible.
- Ensure visual graph interactions have a textual alternative.
- Make loading, failure, and retry states understandable.
- Avoid exposing raw internal errors or sensitive logs to unauthorized users.

## 15.5 Accessibility and Usability

- Keyboard-accessible navigation.
- Meaningful labels and accessible controls.
- Sufficient contrast.
- Screen-reader support for graph summaries.
- Clear status text beyond color alone.
- Responsive layout.
- Readable code references and line locations.
- Usable empty and error states.

## 15.6 Acceptance Criteria

- All critical user journeys pass browser-level E2E tests.
- PR-number routing works for valid and invalid identifiers.
- UI data matches backend analysis and evidence.
- Authorization is enforced on all relevant views and actions.
- Graph and score information remain understandable without relying solely on visual cues.

---

# 16. Authentication, Authorization, and Tenant Isolation

## 16.1 Objective

Protect users, organizations, repositories, analyses, test results, and administrative functions through verified access-control boundaries.

## 16.2 Functional Requirements

- Validate signup and login workflows.
- Validate JWT issuance, expiration, validation, and revocation strategy.
- Complete email verification delivery if required by product policy.
- Complete password-reset delivery and secure token handling.
- Apply organization-level authorization.
- Apply repository-level authorization where configured.
- Enforce role-based access control.
- Validate user membership on every protected operation.
- Prevent insecure direct object references.
- Enforce tenant boundaries in database queries and background jobs.
- Apply least-privilege GitHub App permissions.
- Audit security-sensitive account and configuration events.
- Protect authentication endpoints against brute-force abuse.
- Implement secure logout and session lifecycle behavior appropriate to the authentication model.

## 16.3 Proposed Roles

| Role | Capabilities |
|---|---|
| Organization Owner | Manage organization, members, integrations, billing or plan settings if applicable, and security policies |
| Organization Admin | Manage repositories, members, and configuration within assigned permissions |
| Developer | View authorized repositories and analyses, and trigger permitted reruns |
| Viewer | Read-only access to authorized analyses |
| Service Worker | Machine identity restricted to explicitly required processing operations |

The actual role model must be checked against existing models and APIs before implementation.

## 16.4 Security Requirements

- Secure password hashing using an established algorithm and configuration.
- Short-lived or appropriately managed access tokens.
- Secure handling of refresh or session tokens if used.
- Protection against token replay and misuse.
- Rate limiting for authentication and sensitive APIs.
- Secure cookie configuration if cookies are used.
- Strict CORS and origin policies.
- CSRF protections where applicable.
- Input validation and output encoding.
- Safe error handling.
- Audit logging.
- Secrets rotation.
- Dependency and vulnerability management.

## 16.5 Tenant Isolation

Tenant isolation must cover:

- API queries.
- Database relationships.
- Background job payloads.
- Repository clones.
- Execution workspaces.
- Test reports and artifacts.
- Logs and monitoring data.
- GitHub tokens and installation credentials.
- Dashboard views.
- Exports and downloads.

Every organization-scoped entity must have a verifiable authorization path.

## 16.6 Acceptance Criteria

- Cross-tenant access tests fail safely.
- Unauthorized repository access is rejected.
- Revoked memberships and permissions take effect according to documented session policy.
- Authentication and password recovery flows pass integration tests.
- Secrets are not exposed through API responses, logs, browser storage, or test environments.
- Security-sensitive actions are auditable.

---

# 17. Data Protection and Privacy

## 17.1 Objective

Establish appropriate data handling for source code, repository metadata, analysis output, test logs, user information, and AI-provider interactions.

## 17.2 Data Classification

| Data category | Examples | Required treatment |
|---|---|---|
| Account data | Email, account ID, role | Access-controlled, encrypted where appropriate |
| Repository metadata | Repository name, URL, commit SHA | Tenant-scoped access |
| Source code | Cloned files and parsed content | Restricted access, limited retention |
| Graph data | Symbols, dependencies, graph edges | Tenant-scoped, versioned |
| Analysis data | Diffs, blast radius, confidence | Tenant-scoped, traceable |
| Execution data | Logs, test outputs, artifacts | Restricted access, retention policy |
| Credentials | GitHub tokens, API keys | Secret storage, least privilege, rotation |
| AI context | Source snippets and analysis context | Minimized, redacted where appropriate, governed by provider policy |
| Operational telemetry | Metrics, logs, traces | Avoid secrets and unnecessary customer code |
| Audit data | Login, configuration and access events | Integrity-protected, access-controlled |

## 17.3 Requirements

- Define data retention by data category.
- Provide deletion behavior for disconnected repositories and removed organizations.
- Define backup retention and deletion implications.
- Minimize source code sent to external AI services.
- Ensure AI provider terms and configuration are appropriate for customer data.
- Do not use customer source code for model training without explicit authorization and appropriate agreements.
- Redact secrets from logs and reports.
- Restrict artifact access by tenant and role.
- Document data locations and subprocessors.
- Define data export and deletion workflows.
- Provide clear customer-facing data-handling documentation.

## 17.4 Acceptance Criteria

- Retention rules are documented and implemented.
- Repository disconnection triggers the defined access and deletion workflow.
- AI data flows are documented.
- Secret redaction is tested.
- Tenant-level access controls apply to all data types.
- Backups and deletion policies have clear, documented semantics.

---

# 18. API and Database Requirements

## 18.1 API Requirements

- Review all existing routes and their contracts.
- Complete the PR-number-to-UUID resolution endpoint.
- Validate authentication and authorization consistently.
- Use structured request and response schemas.
- Validate input sizes, types, and identifiers.
- Return consistent error structures.
- Apply pagination for large result sets.
- Support filtering and sorting where needed.
- Provide clear analysis and job lifecycle states.
- Implement idempotency where appropriate.
- Provide versioning strategy for externally consumed contracts.
- Ensure API documentation matches actual behavior.
- Prevent stale analysis data from being presented as current.
- Provide health and readiness endpoints without exposing sensitive details.

## 18.2 Proposed Core API Domains

The exact routes should be reconciled with existing implementations.

| Domain | Required capabilities |
|---|---|
| Authentication | Signup, login, logout/session lifecycle, verification, reset |
| Users | Profile, organization membership, authorized settings |
| Organizations | Organization details, membership, policy configuration |
| Repositories | List, connect, configure, disconnect, readiness |
| GitHub | Installation, webhook handling, integration status |
| Pull Requests | PR listing, lookup, commit association, analysis history |
| Analysis | Start, retrieve, inspect, rerun, compare |
| Graph | Nodes, edges, impact paths, graph metadata |
| Tests | Discovery, selection, execution, outcomes |
| Confidence | Score, components, evidence, uncertainty |
| Jobs | Status, retries, cancellation, operational metadata |
| Reports | CI report ingestion, validation, provenance |
| Audit | Authorized security and administrative events |

## 18.3 Database Requirements

The audit reports more than 15 domain models. Phase 3 should first map existing models before introducing new ones.

The database must reliably represent:

- Users.
- Organizations.
- Memberships and roles.
- Repositories.
- GitHub installations.
- Pull requests.
- Commits.
- Repository analysis versions.
- Files and symbols.
- Graph nodes and edges.
- Diffs and changed entities.
- Impact paths.
- Test definitions and mappings.
- Test-selection runs.
- Test executions.
- Test results.
- CI reports.
- Evidence items.
- Confidence calculations.
- Jobs and job attempts.
- AI analysis records.
- Audit events.
- Configuration and policy versions.

## 18.4 Persistence Requirements

- Every analysis must be associated with a repository and commit.
- Graph data must be associated with parser and graph versions.
- Test selection must be associated with a specific analysis and policy version.
- Test results must be associated with a specific execution.
- Confidence must be reproducible from stored evidence and scoring version.
- Job state must be durable.
- Historical results must remain immutable or be explicitly versioned.
- Foreign keys and uniqueness constraints must protect integrity.
- Tenant boundaries must be represented and enforced.
- Alembic migrations must be reversible where practical and tested against representative data.
- Large artifacts should not unnecessarily inflate relational tables.

## 18.5 Acceptance Criteria

- Schema relationships and constraints are documented.
- Migrations work from a clean database and supported previous versions.
- Historical analyses remain attributable to exact inputs.
- Duplicate processing does not corrupt records.
- Tenant-scoped queries are tested.
- API and database contracts remain consistent.

---

# 19. Observability and Operations

## 19.1 Objective

Make Radius diagnosable and operable in a controlled production environment.

## 19.2 Observability Requirements

### Logs

Structured logs should include:

- Timestamp.
- Service.
- Environment.
- Correlation ID.
- Job ID.
- Analysis ID.
- Repository identifier in a privacy-safe form.
- Stage.
- Severity.
- Error category.
- Duration.
- Retry attempt.

Logs must not contain credentials, raw secrets, or unnecessary source code.

### Metrics

Collect:

- API request count, latency, and error rate.
- Webhook delivery and validation failures.
- Queue depth and queue age.
- Job throughput.
- Job failure and retry rates.
- Worker utilization.
- Parsing duration and failure rate.
- Graph construction duration.
- Impact analysis duration.
- Test-selection duration.
- Test execution duration.
- AI latency, failures, and usage cost.
- Database latency and connection utilization.
- GitHub API rate-limit events.
- Artifact storage usage.
- Analysis completion rates.

### Tracing

Trace the complete workflow:

Webhook → API → Job → Repository preparation → Parsing → Graph → Impact → Selection → Execution → Evidence → Confidence → GitHub publishing.

The trace should use consistent correlation identifiers and avoid exposing sensitive data.

## 19.3 Operational Requirements

- Service health checks.
- Dependency readiness checks.
- Graceful shutdown.
- Queue backlog alerts.
- Worker failure alerts.
- Database health monitoring.
- AI provider outage handling.
- GitHub API failure handling.
- Resource utilization monitoring.
- Backup and restore procedures.
- Incident response procedures.
- Deployment rollback procedures.
- Runbooks for common failures.

## 19.4 Service-Level Objectives

Initial SLOs should be established through baseline measurement. Suggested objectives for the controlled pilot include:

| Area | Initial proposed objective |
|---|---|
| API availability | ≥ 99.5% monthly during the pilot |
| Webhook acceptance | ≥ 99% of valid events accepted or explicitly rejected with a traceable reason |
| Job recovery | Recover or explicitly fail all tested restart scenarios |
| Analysis attribution | 100% of published results tied to the correct commit |
| Dashboard availability | ≥ 99.5% monthly during the pilot |
| Critical error visibility | 100% of release-blocking failures surfaced in logs/alerts |
| Data recovery | Defined and tested RPO/RTO before external pilot |

These are initial planning targets, not established operational commitments. They must be reviewed after load and failure testing.

---

# 20. Performance, Scalability, and Cost

## 20.1 Objective

Measure how Radius performs across different repository sizes, PR types, and execution workloads, then optimize the most expensive stages.

## 20.2 Performance Requirements

- Measure full and incremental repository analysis.
- Measure graph construction and query latency.
- Measure impact-analysis latency.
- Measure test discovery and selection latency.
- Measure AI latency and cost.
- Measure sandbox provisioning and test execution time.
- Measure end-to-end PR processing time.
- Measure dashboard query performance.
- Measure queue latency under different workloads.
- Identify memory and storage bottlenecks.
- Support configurable worker concurrency.
- Prevent uncontrolled resource consumption from large or adversarial repositories.

## 20.3 Benchmark Dimensions

Use repositories that vary by:

- Number of files.
- Number of symbols.
- Graph size and dependency density.
- Number of tests.
- Language.
- Monorepo structure.
- PR size.
- Change type.
- Test runtime.
- Parsing completeness.
- Dependency-resolution difficulty.

## 20.4 Cost Requirements

Track costs per analysis and per repository, including:

- Worker compute.
- Sandbox execution.
- Database usage.
- Storage and artifact retention.
- AI model usage.
- Network and infrastructure overhead.
- Retry and failure costs.

Provide internal cost reporting first. Customer-facing usage or billing features are only required if included in the commercial product scope.

## 20.5 Acceptance Criteria

- Performance baselines exist for representative repositories.
- Bottlenecks are documented.
- Resource limits prevent uncontrolled workloads.
- Cost per analyzed PR is measurable.
- Optimization is demonstrated against an established baseline without degrading analysis quality.

---

# 21. Security Testing and Threat Modeling

## 21.1 Objective

Identify and mitigate security risks introduced by repository integration, background processing, AI usage, user access, and execution of untrusted code.

## 21.2 Threat Model

The threat model must cover:

- Malicious repositories.
- Malicious pull requests.
- Prompt injection in source code and documentation.
- Compromised GitHub credentials.
- Forged or replayed webhooks.
- Cross-tenant access.
- Insecure object references.
- Malicious dependency install scripts.
- Test command abuse.
- Resource exhaustion.
- Container escape risks.
- SSRF and unauthorized outbound connections.
- Log and artifact data leakage.
- AI provider data exposure.
- Dependency and supply-chain attacks.
- Database compromise.
- Stolen application secrets.
- Misconfigured cloud resources.
- Unauthorized administrative actions.

## 21.3 Security Controls

- Least-privilege GitHub permissions.
- HMAC webhook validation.
- Webhook idempotency.
- Secure secret storage and rotation.
- Strict authentication and authorization.
- Tenant isolation.
- Sandboxed execution.
- Network egress restrictions.
- Resource quotas.
- Dependency scanning.
- Secure container images.
- Audit logging.
- Secret redaction.
- Input and report validation.
- AI prompt-injection defenses.
- Database access restrictions.
- Secure CI/CD pipelines.
- Backup protection.
- Incident response procedures.

## 21.4 Security Testing

Include:

- Authentication and authorization tests.
- Cross-tenant access tests.
- Webhook forgery and replay tests.
- SSRF and path traversal tests.
- Sandbox escape-oriented tests appropriate to the environment.
- Resource exhaustion tests.
- Secret leakage tests.
- Malformed report tests.
- Dependency security checks.
- API fuzzing and validation tests.
- Prompt-injection test cases.
- Security configuration reviews.

## 21.5 Acceptance Criteria

- Threat model is reviewed and approved.
- Critical and high-severity findings are addressed or formally risk-accepted before external pilot.
- Security tests pass.
- No known critical tenant-isolation or secret-exposure defect remains open.
- Security incident handling and credential rotation procedures are documented.

---

# 22. End-to-End Benchmark and Validation Framework

## 22.1 Objective

Create a repeatable evaluation system that measures whether Radius's analytical outputs are correct and whether the platform achieves its intended business value.

## 22.2 Benchmark Structure

The benchmark should contain:

1. Representative repositories.
2. Versioned repository snapshots.
3. PR scenario definitions.
4. Expected changed entities.
5. Manually reviewed impact paths.
6. Expected relevant tests.
7. Full-suite execution baselines.
8. Known or injected faults where appropriate.
9. Expected system behavior under incomplete analysis.
10. Performance and cost records.

## 22.3 Benchmark Scenario Categories

### Parsing scenarios

- Valid syntax.
- Syntax errors.
- Nested functions and classes.
- Aliases and re-exports.
- Inheritance.
- Relative imports.
- TypeScript interfaces and generics.
- Dynamic imports.
- Generated code.
- Monorepo packages.

### Diff scenarios

- Added file.
- Deleted file.
- Renamed file.
- Moved symbol.
- Function implementation change.
- Signature change.
- API schema change.
- Configuration change.
- Dependency upgrade.
- Test-only change.

### Impact scenarios

- Direct dependency.
- Multi-hop dependency.
- Shared utility.
- Shared module.
- Cyclic dependency.
- Unresolved import.
- Dynamic dependency.
- High-impact configuration change.

### Test-selection scenarios

- Directly related test.
- Indirectly related test.
- Coverage-linked test.
- Unmapped test.
- Renamed test.
- Flaky test.
- Slow test.
- No discovered test.
- Test-selection fallback.

### Execution scenarios

- Successful execution.
- Test failure.
- Timeout.
- Worker crash.
- Partial report.
- Malformed report.
- Duplicate report.
- Cancellation.
- Resource exhaustion.
- Network restriction.

### Confidence scenarios

- All evidence available.
- Tests passed but analysis incomplete.
- Tests failed.
- Tests skipped.
- Test selection uncertain.
- AI unavailable.
- Stale CI report.
- Missing coverage.
- Partial execution.
- Unsupported language or construct.

## 22.4 Ground Truth

Ground truth should be established using a documented method.

Possible sources:

- Manual review by experienced developers.
- Known dependency relationships.
- Runtime coverage.
- Controlled fault injection.
- Full-suite test execution.
- Historical regression defects.
- Test ownership and mapping data.

Ground truth must acknowledge that test relevance and runtime impact can be context-dependent. It should record the method used to label each scenario and its limitations.

## 22.5 Benchmark Reports

Each benchmark run should generate:

- Radius version.
- Parser and graph versions.
- AI provider/model and prompt version, if enabled.
- Selection policy version.
- Repository and commit.
- Scenario ID.
- Expected and actual changed symbols.
- Expected and actual impact.
- Expected and actual test selection.
- Full-suite and selected-suite outcomes.
- Recall and precision.
- Test reduction.
- Known fault detection.
- Confidence output.
- Runtime.
- Resource usage.
- Cost.
- Failure classification.
- Regression comparison.

## 22.6 Regression Gates

Changes to the following components must trigger relevant benchmark suites:

- Parser.
- Symbol resolver.
- Graph builder.
- Diff analyzer.
- Blast-radius algorithm.
- Test discovery.
- Test selector.
- AI pruning.
- Test executor.
- Report ingestion.
- Confidence engine.

A change that improves speed but materially worsens critical recall should not be accepted without an explicit and documented product decision.

## 22.7 Acceptance Criteria

- Benchmark scenarios are version-controlled.
- Ground truth has documented provenance.
- Benchmark runs are reproducible.
- Critical quality metrics are tracked over time.
- Regressions trigger investigation.
- Release candidates meet approved quality thresholds.

---

# 23. Testing Strategy

## 23.1 Unit Testing

Test each module independently.

### Parser

- Source extraction.
- Symbol identity.
- Source locations.
- Imports and exports.
- Syntax errors.
- Unsupported constructs.

### Graph

- Node and edge creation.
- Deduplication.
- Relationship direction.
- Graph traversal.
- Incremental updates.
- Stale graph detection.

### Diff and impact

- Changed-line mapping.
- Symbol matching.
- Rename handling.
- Direct and transitive dependencies.
- Unresolved relationships.
- Impact-path explanations.

### Test intelligence

- Test discovery.
- Test-to-code mapping.
- Selection policy.
- Fallback triggers.
- Reason generation.

### Confidence

- Component calculations.
- Missing evidence.
- Uncertainty propagation.
- Versioned score reproducibility.
- Insufficient-evidence behavior.

### API and GitHub

- Validation.
- Authorization.
- Idempotency.
- Webhook verification.
- Error handling.

## 23.2 Integration Testing

Validate interactions between:

- Parser and graph.
- Graph and blast-radius analysis.
- Blast radius and test selection.
- Test selector and executor.
- Executor and report ingestion.
- Evidence and confidence.
- API and worker.
- Worker and durable queue.
- GitHub webhooks and job creation.
- Analysis persistence and dashboard.
- Authentication and organization authorization.

## 23.3 End-to-End Testing

At minimum, validate:

1. New user signup and login.
2. Email verification and password reset, if enabled.
3. GitHub App installation.
4. Repository connection.
5. Repository readiness analysis.
6. PR webhook receipt.
7. Job creation and durable processing.
8. Repository checkout.
9. Parsing and graph construction.
10. Diff and impact analysis.
11. Test selection.
12. Sandboxed test execution.
13. Result ingestion.
14. Confidence calculation.
15. GitHub Check publication.
16. Dashboard analysis inspection.
17. PR rerun.
18. Worker restart and recovery.
19. Permission revocation.
20. Repository disconnection and data handling.

## 23.4 Fault-Injection Testing

Inject failures at each major stage:

- API unavailable.
- Database unavailable.
- Queue unavailable.
- Worker termination.
- Sandbox provisioning failure.
- Parser crash.
- Graph persistence failure.
- AI timeout.
- Test timeout.
- Partial report.
- GitHub API rate limit.
- Duplicate webhook.
- Delayed webhook.
- Dashboard API error.
- Network interruption.

Verify that Radius either recovers or enters a clearly reported failure state without publishing misleading results.

## 23.5 Security Testing

Run the security testing plan defined in Section 21.

## 23.6 Performance Testing

Run:

- Load tests.
- Concurrency tests.
- Large repository tests.
- Large PR tests.
- Long-running test suites.
- Queue backlog tests.
- Database stress tests.
- Resource exhaustion tests.

## 23.7 Acceptance Criteria

- Critical unit and integration tests pass.
- Release-blocking E2E tests pass.
- Fault-injection outcomes are documented.
- Security issues are triaged.
- Performance results meet approved thresholds.
- Test suite can run in a reproducible environment without requiring real customer credentials.

---

# 24. Deployment and Release Engineering

## 24.1 Objective

Make Radius deployable, upgradeable, recoverable, and operable in the environments selected for the pilot and initial release.

## 24.2 Deployment Requirements

- Complete Docker Compose development and controlled pilot configuration.
- Separate development, testing, staging, and production-like environments.
- Use secure environment configuration.
- Keep secrets outside source control.
- Pin critical runtime and container versions.
- Use health and readiness checks.
- Use controlled database migrations.
- Support graceful shutdown.
- Support rollback of application deployments.
- Document worker and queue scaling.
- Configure backups and recovery.
- Establish secure network boundaries.
- Configure observability.
- Define deployment access controls.

## 24.3 CI/CD Requirements

- Linting and formatting.
- Static type checks where applicable.
- Unit and integration tests.
- E2E tests.
- Security and dependency scans.
- Container image validation.
- Migration checks.
- Benchmark regression checks.
- Artifact provenance.
- Release versioning.
- Deployment approval controls.
- Rollback process.

## 24.4 Environment Strategy

| Environment | Purpose |
|---|---|
| Local | Developer iteration |
| CI | Automated validation of changes |
| Staging | Integration, migration, and pre-release testing |
| Pilot | Controlled external or internal customer validation |
| Production | Only after formal readiness approval |

## 24.5 Acceptance Criteria

- Clean setup works from documented instructions.
- Migrations succeed in supported upgrade paths.
- Health checks correctly report service readiness.
- Deployment rollback is tested.
- Backups can be restored in a rehearsal.
- Secrets are not embedded in images or repository files.
- Production-like deployment passes the release checklist.

---

# 25. Pilot and Business Validation

## 25.1 Objective

Validate Radius's usefulness with real development workflows before making broad product claims.

## 25.2 Pilot Selection

Choose a small number of repositories that:

- Use supported languages and test frameworks.
- Have permission for Radius integration.
- Have active PR workflows.
- Have maintainers willing to provide feedback.
- Have a known baseline CI process.
- Represent different repository sizes and dependency patterns.

Do not use customer or employer repositories without explicit authorization.

## 25.3 Pilot Stages

### Stage A: Internal validation

- Use controlled repositories.
- Compare Radius output with manual ground truth.
- Fix correctness and reliability issues.
- Establish performance and cost baselines.

### Stage B: Shadow mode

- Analyze PRs without influencing merge policies.
- Compare selected tests with existing CI execution.
- Review false negatives, false positives, and confidence explanations.
- Gather developer feedback.

### Stage C: Controlled assisted workflow

- Display Radius findings to developers.
- Allow developers to inspect and act on evidence.
- Keep existing CI requirements in place.
- Monitor user behavior, latency, cost, and usefulness.

### Stage D: Pilot review

- Compare results against baseline.
- Identify technical and product gaps.
- Decide whether to broaden the pilot or return to engineering work.

## 25.4 Pilot Metrics

- Setup completion rate.
- Analysis completion rate.
- End-to-end latency.
- Test-selection recall and precision.
- Test execution reduction.
- Full-suite comparison results.
- False-negative incidents.
- Incomplete analysis frequency.
- Confidence evidence quality.
- Developer finding engagement.
- Developer-reported usefulness.
- Retry and failure rates.
- Cost per analyzed PR.
- Support requests and onboarding friction.

## 25.5 Business Validation Questions

- Do developers understand Radius's findings?
- Does Radius save meaningful verification time?
- Do developers trust the explanations?
- Are selected tests sufficiently relevant?
- Are fallback behaviors acceptable?
- Does the dashboard provide value beyond GitHub Checks?
- Is setup manageable without substantial engineering support?
- Is the operating cost acceptable for the observed benefit?
- What repository patterns most frequently cause analysis uncertainty?
- Which features are necessary before wider adoption?

## 25.6 Acceptance Criteria

- Pilot results are documented.
- Developers provide structured feedback.
- Technical metrics are compared with baseline CI.
- Known failures and limitations are disclosed.
- Product claims are restricted to demonstrated capabilities.
- A decision is recorded for broader rollout, further validation, or additional engineering.

---

# 26. Phase 3 Workstreams and Deliverables

| Workstream | Main activities | Key deliverables |
|---|---|---|
| WS-01: Validation baseline | Benchmark design, representative repositories, ground truth, test harness | Benchmark framework and baseline report |
| WS-02: Repository intelligence | Parser audit, semantic resolution, graph accuracy, incremental analysis | Improved parser and graph with quality evidence |
| WS-03: Impact analysis | Diff correctness, blast radius, dependency paths, uncertainty | Validated impact-analysis engine |
| WS-04: AI safeguards | Prompt security, schema validation, fallback, AI evaluation | Auditable AI-assisted pruning |
| WS-05: Test intelligence | Test mapping, coverage integration, selection metrics, fallback | Benchmark-validated test selector |
| WS-06: Execution reliability | Sandboxing, limits, reproducibility, cancellation, cleanup | Secure test-execution service |
| WS-07: Evidence and confidence | Provenance, report ingestion, scoring, calibration | Explainable evidence and confidence engine |
| WS-08: Durable orchestration | Durable queue, retries, idempotency, recovery | Resilient job-processing system |
| WS-09: GitHub and dashboard | PR route, app install, checks, UX, E2E | Complete developer workflow |
| WS-10: Security and privacy | Threat model, RBAC, tenant isolation, data lifecycle | Security and privacy readiness report |
| WS-11: Operations | Observability, alerts, SLOs, backups, deployment | Operationally ready deployment |
| WS-12: Pilot validation | Shadow mode, assisted pilot, feedback, cost analysis | Pilot report and release recommendation |

---

# 27. Proposed Implementation Sequence

Phase 3 should be executed in gated stages. Workstreams may overlap when dependencies allow, but quality gates must remain explicit.

## Stage 1: Baseline and architecture validation

**Activities**

- Inspect actual repository state.
- Compare the audit with source code and existing tests.
- Map current module contracts.
- Identify critical dependencies and technical debt.
- Establish baseline metrics.
- Build benchmark scenarios and ground truth.
- Fix test environment reproducibility.
- Establish initial threat model.

**Deliverables**

- Verified current-state audit.
- Architecture and contract inventory.
- Benchmark framework.
- Initial baseline report.
- Prioritized engineering backlog.

**Exit gate**

The team can reproduce the current end-to-end workflow and identify its known accuracy and reliability limitations.

## Stage 2: Analytical correctness

**Activities**

- Improve parser coverage and semantic resolution.
- Validate graph construction and freshness.
- Improve diff-to-symbol mapping.
- Improve blast-radius correctness.
- Introduce explicit unresolved and incomplete states.
- Establish deterministic test-selection baselines.

**Deliverables**

- Validated parser and graph.
- Impact-analysis benchmark report.
- Test-selection baseline.
- Regression suite.

**Exit gate**

The analytical pipeline meets the approved benchmark requirements or clearly documents unresolved limitations and prevents misleading claims.

## Stage 3: Verification intelligence

**Activities**

- Improve test-to-code mapping.
- Add coverage-informed relationships where feasible.
- Introduce conservative selection policies and fallback.
- Evaluate AI pruning.
- Strengthen evidence provenance.
- Evaluate and calibrate confidence scoring.

**Deliverables**

- Benchmark-validated test selector.
- AI evaluation report.
- Versioned evidence model.
- Confidence calibration report.

**Exit gate**

Test selection and confidence behavior are measurable, explainable, and appropriately conservative when evidence is incomplete.

## Stage 4: Reliability and secure execution

**Activities**

- Introduce durable queue.
- Implement job lifecycle and recovery.
- Isolate repository execution.
- Add resource and network controls.
- Improve report ingestion.
- Validate retries, cancellation, and cleanup.

**Deliverables**

- Durable worker system.
- Sandboxed execution service.
- Recovery and fault-injection results.
- Execution security review.

**Exit gate**

Critical job-recovery and execution-isolation tests pass, and verification results remain correctly attributable.

## Stage 5: Product workflow and platform hardening

**Activities**

- Complete GitHub installation and webhook behavior.
- Fix PR routing.
- Complete core dashboard workflows.
- Validate authentication and authorization.
- Improve tenant isolation.
- Complete email delivery if required.
- Add observability and deployment readiness.

**Deliverables**

- Complete GitHub-to-dashboard workflow.
- E2E suite.
- Security validation report.
- Operational runbooks.
- Staging deployment.

**Exit gate**

Core user journeys work reliably, security controls pass, and staging is observable and recoverable.

## Stage 6: Pilot and release validation

**Activities**

- Run internal validation.
- Run shadow-mode pilot.
- Compare Radius against existing CI.
- Measure value, quality, and cost.
- Fix critical defects.
- Review product positioning and limitations.

**Deliverables**

- Pilot report.
- Release-readiness checklist.
- Known-limitations register.
- Phase 3 completion report.
- Phase 4 recommendation.

**Exit gate**

The team has sufficient evidence to make an informed decision about wider deployment and the next roadmap stage.

---

# 28. Prioritization

## P0 — Must complete before external pilot

- Reproducible end-to-end benchmark.
- Reliable local and CI test environment.
- Critical parser and graph correctness validation.
- Blast-radius correctness measurement.
- Test-selection recall measurement and conservative fallback.
- Secure, isolated test execution.
- Durable job queue and recovery.
- Correct commit attribution.
- Evidence provenance.
- Confidence uncertainty handling.
- Critical GitHub workflow fixes.
- Authentication and tenant-isolation validation.
- Critical security testing.
- Monitoring and error visibility.

## P1 — Must complete for a robust initial product

- Coverage-informed test mapping.
- Improved incremental graph processing.
- Confidence calibration evaluation.
- Comprehensive dashboard workflow.
- Email verification and password recovery delivery, if retained in scope.
- Historical analysis comparison.
- Operational SLOs and alerting.
- Backup and restore rehearsal.
- Pilot cost and performance reporting.
- Customer onboarding diagnostics.

## P2 — Post-pilot improvements

- Additional language support.
- Additional test frameworks.
- Broader CI-provider integrations.
- More advanced historical prediction.
- Advanced organizational policies.
- Expanded security verification capabilities.
- Deeper repository-level learning.
- More advanced analytics and reporting.

P2 items should be prioritized using pilot evidence and actual customer requirements.

---

# 29. Risk Register

| ID | Risk | Impact | Mitigation |
|---|---|---|---|
| R-001 | Incorrect dependency graph | Relevant code or tests may be missed | Benchmark graph accuracy, expose unresolved dependencies, conservative fallback |
| R-002 | False-negative test selection | Regression may escape selected tests | Measure recall, compare against full suite, retain fallback |
| R-003 | AI incorrectly prunes impact | Relevant verification may be omitted | Deterministic safeguards, benchmark validation, AI disable option |
| R-004 | Confidence score creates false assurance | Developers may over-trust results | Evidence transparency, calibration, uncertainty states, no safety guarantee |
| R-005 | Untrusted test code compromises infrastructure | Security breach or service disruption | Isolated execution, resource limits, network restrictions, security review |
| R-006 | In-memory queue loses jobs | Incomplete analysis and lost work | Durable queue, persistent job state, recovery testing |
| R-007 | Duplicate or stale webhooks | Conflicting or incorrect analysis | Idempotency, commit attribution, event validation |
| R-008 | Cross-tenant data leakage | Customer confidentiality breach | Tenant-scoped authorization, security tests, data separation |
| R-009 | AI provider outage or cost increase | Degraded or expensive analysis | Provider abstraction, fallback, usage limits, cost monitoring |
| R-010 | Dashboard and backend disagree | Misleading developer experience | Contract tests, shared identifiers, integration and E2E tests |
| R-011 | Large repositories cause resource exhaustion | Slowdown or service instability | Limits, incremental analysis, concurrency controls |
| R-012 | Incomplete CI report ingestion | Confidence is based on missing evidence | Schema validation, provenance, partial-result states |
| R-013 | Flaky tests distort results | Unstable confidence and developer trust | Flakiness tracking, repeat policies, explicit uncertainty |
| R-014 | Inadequate observability | Failures remain undetected | Structured logs, metrics, traces, alerts |
| R-015 | Unsupported repository patterns | Incorrect or incomplete results | Readiness diagnostics, explicit support boundaries, fallback |
| R-016 | Pilot value is lower than expected | Weak adoption or unclear differentiation | Shadow-mode measurement, developer interviews, product iteration |
| R-017 | Infrastructure cost outweighs savings | Unsustainable unit economics | Cost per PR measurement, workload limits, optimization |
| R-018 | Security and privacy obligations are unclear | Pilot risk and reduced customer trust | Data-flow documentation, retention policies, threat model, review |
| R-019 | Incremental graph becomes stale | Incorrect impact analysis | Freshness metadata, reconciliation, full rebuild validation |
| R-020 | Changes regress analytical quality | Previously valid analyses degrade | Benchmark regression gates and versioned algorithms |

Each risk should be assigned an owner, severity, likelihood, mitigation status, and residual risk during implementation.

---

# 30. Definition of Done

A Phase 3 feature is not complete merely because the code is merged.

Each requirement should satisfy the following applicable criteria:

- Implementation is complete.
- Unit tests cover the intended behavior.
- Integration tests validate relevant service boundaries.
- E2E tests validate critical user-facing behavior.
- Benchmark tests validate analytical correctness where applicable.
- Failure behavior is defined.
- Observability is implemented.
- Security implications are reviewed.
- API and data contracts are documented.
- Migration impacts are addressed.
- User-facing limitations are communicated.
- Operational instructions are available.
- Acceptance criteria are verified.
- Changes are reviewed and merged.
- Release notes and known limitations are updated.

For critical analytical components, benchmark validation is mandatory. For critical infrastructure components, failure and recovery testing is mandatory.

---

# 31. Phase 3 Release Acceptance Checklist

## Analytical correctness

- [ ] Python and TypeScript/JavaScript parser coverage is measured.
- [ ] Symbol and dependency resolution are benchmarked.
- [ ] Graph integrity and freshness are validated.
- [ ] Diff-to-symbol mapping is validated.
- [ ] Blast-radius recall and precision are measured.
- [ ] Unresolved and unsupported relationships are visible.
- [ ] Incremental and full graph analysis are reconciled.

## Test intelligence

- [ ] Supported test frameworks are validated.
- [ ] Test discovery is benchmarked.
- [ ] Test-to-code mapping quality is measured.
- [ ] Selection recall and precision are measured.
- [ ] Test reduction is measured.
- [ ] AI pruning is evaluated.
- [ ] Conservative fallback works.
- [ ] Selection reasons are traceable.

## Execution and evidence

- [ ] Test execution is isolated.
- [ ] Resource limits are enforced.
- [ ] Timeouts and cancellation work.
- [ ] Worker restart recovery is tested.
- [ ] Results are correctly attributed to commits.
- [ ] CI report validation works.
- [ ] Duplicate and stale evidence are handled.
- [ ] Artifact retention and cleanup work.

## Confidence

- [ ] Score components are documented.
- [ ] Score algorithm is versioned.
- [ ] Missing evidence is visible.
- [ ] Incomplete analysis is represented.
- [ ] Calibration is evaluated.
- [ ] Confidence explanations are traceable.
- [ ] No unsupported safety guarantee is presented.

## Platform reliability

- [ ] Durable queue is operational.
- [ ] Job lifecycle is persisted.
- [ ] Retry and idempotency behavior is tested.
- [ ] Stuck jobs are detectable.
- [ ] GitHub rate limits and outages are handled.
- [ ] Database backups and restore are tested.
- [ ] Logs, metrics, traces, and alerts are available.

## Security and privacy

- [ ] Threat model is reviewed.
- [ ] Authentication and authorization are validated.
- [ ] Tenant isolation is tested.
- [ ] GitHub permissions are least-privilege.
- [ ] Webhook signatures and replay behavior are tested.
- [ ] Execution sandbox security is reviewed.
- [ ] Secrets are protected and redacted.
- [ ] AI data flow is documented.
- [ ] Retention and deletion policies are implemented.
- [ ] Critical security findings are resolved or formally accepted.

## Developer experience

- [ ] GitHub App installation works.
- [ ] Repository connection works.
- [ ] PR routing works.
- [ ] Check Runs are correct and idempotent.
- [ ] PR comments are accurate and update correctly.
- [ ] Dashboard core routes work.
- [ ] Impact graph and evidence are understandable.
- [ ] Rerun and history flows work.
- [ ] Critical E2E browser tests pass.
- [ ] Accessibility requirements are checked.

## Business validation

- [ ] Representative repositories are tested.
- [ ] Pilot consent and data handling are documented.
- [ ] Shadow-mode results are evaluated.
- [ ] Test reduction and detection trade-offs are measured.
- [ ] Developer feedback is collected.
- [ ] Cost per analyzed PR is measured.
- [ ] Product limitations are documented.
- [ ] Pilot findings inform the next roadmap.

---

# 32. Phase 3 Deliverables

At completion, Radius should have the following artifacts and product capabilities:

1. **Verified current-state audit** — an evidence-based inventory of implemented and working functionality.
2. **Benchmark framework** — reusable repositories, PR scenarios, ground truth, and regression gates.
3. **Validated repository intelligence** — measured parser, symbol-resolution, graph, and freshness quality.
4. **Validated impact engine** — traceable diff and blast-radius analysis.
5. **Validated AI pruning layer** — audited, measurable, and safely bounded AI assistance.
6. **Validated test intelligence** — benchmarked test discovery, mapping, selection, and fallback.
7. **Secure execution system** — isolated and reproducible test execution.
8. **Reliable orchestration** — durable jobs, retries, idempotency, and recovery.
9. **Evidence system** — validated CI ingestion, provenance, and historical traceability.
10. **Explainable confidence engine** — documented scoring, uncertainty, and calibration evaluation.
11. **Complete GitHub workflow** — installation, webhooks, Check Runs, comments, and reruns.
12. **Complete dashboard workflow** — onboarding, PR analysis, evidence inspection, history, and administration.
13. **Hardened security model** — authentication, authorization, tenant isolation, and secure data handling.
14. **Operationally ready deployment** — monitoring, alerting, backup, restore, and deployment procedures.
15. **Performance and cost report** — representative measurements and optimization findings.
16. **Pilot validation report** — real-workflow feedback and measured business value.
17. **Release-readiness report** — accepted risks, known limitations, quality evidence, and a go/no-go recommendation.

---

# 33. Recommended Phase 3 Governance

## 33.1 Requirement Traceability

Each requirement must be tracked with:

- Requirement ID.
- Description.
- Priority.
- Workstream.
- Dependencies.
- Owner.
- Implementation status.
- Test references.
- Benchmark references, where applicable.
- Acceptance status.
- Known limitations.
- Release impact.

## 33.2 Change Management

Changes to analytical behavior must include:

- Reason for change.
- Expected quality impact.
- Affected contracts.
- Relevant regression tests.
- Benchmark comparison.
- Performance and cost impact.
- Security impact where applicable.
- Rollback or disable strategy.

## 33.3 Release Gates

A release candidate must not pass solely because the build succeeds.

It must satisfy:

1. Build and test gate.
2. Integration and E2E gate.
3. Analytical benchmark gate.
4. Security gate.
5. Reliability and recovery gate.
6. Performance and cost review.
7. Product and pilot-readiness review.

Any exception should be documented with its impact, mitigation, owner, and approval.

---

# 34. Final Phase 3 Outcome

Phase 3 is complete when Radius has moved beyond feature presence to demonstrated verification quality.

The final product should be capable of taking a supported GitHub PR, understanding its changes within the limits of its repository intelligence, tracing potential impact, selecting tests with measured quality, executing them in a controlled environment, interpreting the results, and presenting evidence and uncertainty through GitHub and the dashboard.

Radius should give developers a coherent answer to:

- What changed?
- What could be affected?
- Why does Radius believe it could be affected?
- Which tests were selected?
- Which tests actually ran?
- What did the results show?
- What was not verified?
- How complete and trustworthy is the available evidence?
- What should be reviewed before merging?

**The business outcome is not merely faster CI. It is more efficient, transparent, and evidence-driven software verification that developers can evaluate and use without surrendering their own judgment.**

Phase 3 should therefore be judged by demonstrated analytical accuracy, safe test selection, reliable execution, explainable evidence, platform security, operational resilience, and measurable developer value—not by a feature-completion percentage alone.

**North star: Radius should make the verification evidence behind every supported PR more visible, more targeted, and more trustworthy, while making the limits of that evidence explicit.**