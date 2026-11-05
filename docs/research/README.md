# Radius Research and Product Plan: Intent-to-Evidence Verification

This folder is the single source of truth for the next phase of Radius: a research-grade, market-facing platform that verifies agent-written code by tying each stated intent to trustworthy evidence.

**Status:** Ratified by the owner on 2026-11-02 (task F-01); decisions are recorded in `docs/decisions.md` (DEC-006 to DEC-025). The provisional items (DEC-011, 012, 014, 015) were finalized by delegation on 2026-11-02 (DEC-018 to DEC-021).
**Branching:** `feature/*`, `fix/*`, `docs/*` -> `develop` -> `dev` (UAT) -> `main` (production). Never commit directly to `dev` or `main`.

## How to use this folder

| If you are... | Read in this order |
|---|---|
| **A human contributor** | `README.md` -> `DESIGN.md` -> `IMPLEMENTATION_PLAN.md` -> your phase file in `tasks/` |
| **An AI coding agent** | `docs/AI_CONTEXT.md` -> `docs/DEVELOPMENT_GUIDE.md` -> `IMPLEMENTATION_PLAN.md` section 1 -> `DESIGN.md` -> your task in `tasks/` (do only that task) |
| **The researcher / paper author** | `EVALUATION_PLAN.md` -> `DESIGN.md` -> the "Research hook" lines in tasks |
| **Product / GTM** | `PRODUCT_AND_GTM.md` -> `tasks/PL-product-launch.md` |

## Files

| File | Purpose |
|---|---|
| `DESIGN.md` | Thesis, glossary, architecture, data model, algorithms, LLM governance, security, reproducibility, open decisions |
| `IMPLEMENTATION_PLAN.md` | Rules for all contributors, definition of done, task template, dependency overview, milestones and gates, task index, risks |
| `EVALUATION_PLAN.md` | Research questions, datasets, baselines, experiments (EP-xx), statistics, threats, paper outline, artifact checklist |
| `preregistration/` | EP-02 pre-registration (`PREREGISTRATION.md`, DRAFT until the owner freezes it), its changelog / freeze mechanism, and `FREEZE_CHECKLIST.md` (what must be true before the freeze; machine-checked part: `scripts/prereg_check.py`) |
| `PRODUCT_AND_GTM.md` | Personas, competitors, positioning, MVP, go-to-market, metrics |
| `tasks/F-foundations.md` | Stabilize the prototype (M0) |
| `tasks/IN-intent.md` | Intent layer (M1) -- research core |
| `tasks/LK-linking.md` | Linking and the Intent-Evidence Graph (M2) |
| `tasks/EV-evidence-quality.md` | Tamper rules, mutation, evidence quality (M2, M4) |
| `tasks/VD-verdict-v2.md` | Support, UIM, verdict v2, policy, publishing (M3) |
| `tasks/PR-process-verification.md` | Agent trajectories and process signals (M5) |
| `tasks/CA-calibration.md` | Outcome labels, calibration, conformal abstention (M5) |
| `tasks/TR-triage.md` | Risk-ranked review triage and re-prompts (M6) |
| `tasks/MG-manager.md` | Manager portfolio, trends, RBAC, exports (M6) |
| `tasks/IT-integrations.md` | GitHub App, CLI, Action, MCP, importers, trackers (M6) |
| `tasks/QS-quality-security-ops.md` | Threat model, injection tests, sandbox pen-test, privacy, SLOs (continuous) |
| `tasks/PL-product-launch.md` | Personas, onboarding, demo, docs, partners, pricing, launch (continuous) |

## The idea in five lines

1. Turn each PR's stated intent into atomic **criteria**.
2. Link criteria to the **symbols** that implement them and the **tests/evidence** that exercise them (the Intent-Evidence Graph).
3. Score each piece of evidence by how likely it would have **failed if the code were wrong** (mutation + assertion strength + independence + freshness), and detect tampering.
4. Combine into per-criterion **support** and a deterministic, explainable **verdict**; calibrate it to real outcomes and **abstain** when unsure.
5. Verify the **process** (agent trajectory), triage human review by risk, and give managers an honest aggregate view.

**The LLM proposes, evidence disposes:** LLMs may help extract criteria and verify links, but never compute the verdict.

## Honesty notes

- Formulas, weights and thresholds are hypotheses to be tested (see `EVALUATION_PLAN.md`).
- Competitor and paper details were gathered from public pages and search results on 2026-11-02; three PDFs could not be text-extracted and several statistics came from search snippets. Verify in EP-01 before citing.
- Repo paths come from the 2026-11-01 audit and an exploratory read; verify before editing.

## Decision log (mirrored in `docs/decisions.md`, DEC-006 to DEC-025)

Also ratified: research core (DEC-006), new packages (DEC-007), verdict v2 states (DEC-008), LLM governance (DEC-009). Rows D3, D4, D6, D7 were provisional and were finalized by delegation on 2026-11-02 (see below).

| # | Decision | Options | Chosen | Date | By |
|---|---|---|---|---|---|
| D1 | GitHub default branch | `dev` (current) / `develop` | `develop` (DEC-010) | 2026-11-02 | Owner |
| D2 | Verdict adds `needs_review` | yes / no | yes, fourth state (DEC-008) | 2026-11-02 | Owner |
| D3 | Allow probe generation (EV-12) | yes / no / later | later; not now (DEC-011), superseded: advisory sandbox-only probe suggestions allowed, never written to user repos (DEC-019) | 2026-11-02 | Owner (delegated) |
| D4 | License / open-source model | open core / fully open / closed | open core, Apache-2.0 for the core, proprietary parts only as separate modules (DEC-018; supersedes DEC-012) | 2026-11-02 | Owner (delegated 2026-11-02) |
| D5 | First languages | Python then TS / other | Python (pytest) then TypeScript (DEC-013) | 2026-11-02 | Owner |
| D6 | Calibration label sources | own + partners / public only | public/benchmark first; partner data only on explicit written opt-in (DEC-020; supersedes DEC-014) | 2026-11-02 | Owner (delegated 2026-11-02) |
| D7 | LLM provider and code-egress policy | | LLM opt-in per org, redacted intent text only, Anthropic first (haiku default), local model before enterprise GA (DEC-021; supersedes DEC-015) | 2026-11-02 | Owner (delegated 2026-11-02) |
| D8 | Handling of stray test commit `c2d5db6` on `dev` | leave / revert via PR | leave (DEC-016) | 2026-11-02 | Owner |

## Decisions made by delegation on 2026-11-02

The owner delegated "complete everything by taking the ideal decisions". The following were decided on that basis (full reasoning in `docs/decisions.md`). **The owner can veto any of them**; a veto is recorded as a new DEC that supersedes it.

| DEC | Decision | Supersedes |
|---|---|---|
| DEC-018 | Apache-2.0 for the open core; `LICENSE`, `NOTICE`; proprietary parts only in separate modules. Publishing a license is effectively irreversible for distributed copies | DEC-012 |
| DEC-019 | No generation into user repos; advisory, labelled, sandbox-only probe suggestions allowed for evidence measurement (flag-gated, not started) | DEC-011 |
| DEC-020 | Calibration labels: public benchmarks, then public real-PR outcomes, own history for dev only, partner data only with written opt-in and no raw code | DEC-014 |
| DEC-021 | LLM: opt-in per org, redacted intent text only, Anthropic first (`claude-haiku-5-5`), sonnet only in experiments, local model before enterprise GA, metadata-only logs, token caps; legacy Gemini pruner flagged | DEC-015 |
| DEC-022 | DCO sign-off, no CLA; inbound = outbound | none (new) |
| DEC-023 | Telemetry opt-in, anonymous, no code or intent text, no phone-home | none (new) |
| DEC-024 | Name/branding "Radius" flagged: trademark clearance not done | none (new) |
| DEC-025 | Pre-registration v0.2-draft: the 11 section 17 choices (still not frozen) | none (new) |

Also added: `datasets/AUTHOR_REQUESTS.md` (email drafts, not sent).

## Changelog

- 2026-11-02: initial draft.
- 2026-11-02: ratified (F-01); decision log filled and mirrored to `docs/decisions.md`.
- 2026-11-02: provisional decisions finalized by delegation (DEC-018 to DEC-025); pre-registration v0.2-draft; author-request drafts.
