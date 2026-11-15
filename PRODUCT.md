# Radius — Product Context

## Vision & Purpose
Radius is an AI-native software verification platform that answers one critical question:
**"Can this Pull Request be merged safely?"**

It sits between code changes and production deployment, analyzing repositories as interconnected code property graphs (CPG), predicting which tests are affected by diff hunks, and validating test execution evidence before merging.

## Target Audience
- **Software Engineers**: Writing PRs, needing fast and reliable feedback on test impact, failures, and coverage.
- **Tech Leads & Reviewers**: Assessing blast radius, change risk, and verification confidence before approving.
- **DevOps & Platform Teams**: Integrating test selection into CI pipelines to cut CI runtimes and eliminate flaky test noise.

## Operating Mode: Operate
Radius is an **Operate**-mode developer tool. Its primary job is enabling fast, confident engineering decisions.
- **Scanability over decoration**: High information density without visual clutter.
- **Immediate clarity**: A developer should understand within 3 seconds whether a PR is verified and why.
- **Earned familiarity**: Standard developer navigation, predictable actions, copyable CLI commands, and clean data tables.

## Core User Journeys

### 1. First-Time Experience (FTUX)
- User arrives with zero repositories connected.
- Sees a clear 3-step activation path: Connect Repository -> Install GitHub App / Configure CI -> View First Analysis.
- Actionable empty states replace blank cards.

### 2. Workspace Overview & Repository Health
- High-level health at a glance: Active repositories, recent analyses, overall confidence score, and items needing attention.
- Quick navigation into any repository or recent verification run.

### 3. Pull Request Verification & Analysis Detail
- The central workflow in Radius:
  - **Verdict Header**: Unambiguous status (`Verified`, `Not Verified`, `Failed`) with the exact primary blocker.
  - **Progressive Disclosure**: High-level confidence score and change risk up front; detailed evidence and gap analysis accessible via tabs/collapsible sections.
  - **Blast Radius & Dependency Slicing**: Sliced CPG visualizer showing affected files, functions, and tests without redundant node counts.
  - **Predictive Test Selection**: Clear count of selected vs skipped tests, one-click CLI command for local reproduction, and filterable test table.
  - **CI Ingestion**: Simple drag-and-drop or file upload for JUnit XML / JSON reports with live score updates.

### 4. Flaky Test Detection & Reliability
- Tracking test execution history across commits.
- Distinguishing genuinely failing tests from flaky tests.

## Key UX Constraints & Redundancy Rules
1. **Never repeat the same metric in multiple visual styles** on the same screen (e.g. don't display "Average confidence: 85%" as a number card and a giant radial ring right next to it).
2. **No kickers or eyebrows above headings** (per Impeccable craft rules: the heading carries its own weight).
3. **No nested cards**: Group content with section dividers, clean spacing, or table layouts instead of wrapping cards inside cards.
4. **Developer-centric copy**: Action-oriented buttons ("Run Verification", "Copy Command", "Connect Repository"). Remove internal implementation trivia like backend route endpoints from user-facing screens.
