# Phase IT: Integrations and Distribution (Milestone M6, starts earlier where noted)

Goal: be where agent-driven teams already work, so verification happens before and during review, not after. Template and rules: `../IMPLEMENTATION_PLAN.md`.

---

### IT-01 GitHub App polish and install flow   [ ]
- Owner type: pair
- Depends on: F-06
- Branch: `feature/github-app-install`
- Size: L
- Goal: smooth install: select repos, minimal permissions, org mapping to Radius tenants, webhook secret rotation, suspend/uninstall handling, installation token caching with refresh, rate-limit handling with backoff, GitHub Enterprise Server support flag.
- Acceptance: install on a fresh org creates a tenant; uninstall removes tokens and schedules data deletion per retention; documented permission list with justification for each.
- Product hook: "install in 2 minutes".

### IT-02 `radius` CLI   [ ]
- Owner type: agent-ok
- Depends on: VD-03
- Branch: `feature/cli`
- Size: L
- Goal: a single CLI (Python package and/or npm) with commands: `radius login`, `radius verify` (local diff vs base), `radius status`, `radius criteria`, `radius reprompt`, `radius rules`, `radius run -- <cmd>` (PR-03), `radius replay <id>` (QS-09). JSON output mode for scripts; exit codes for CI.
- Acceptance: works offline for rule-only checks; clear errors; installable from a package registry; versioned with the API.
- Note: `scripts/radius_ci.py` exists; migrate it behind the CLI with compatibility.

### IT-03 GitHub Action v2   [ ]
- Owner type: agent-ok
- Depends on: IT-02, VD-06
- Branch: `feature/action-v2`
- Size: M
- Goal: update `.github/actions/radius-verify/action.yml`: uploads JUnit/coverage/SARIF, passes agent trace if present, waits (bounded) for the verdict, sets outputs and exit status per policy (advisory/blocking). Radius uses it on its own repo (dogfooding) as a required check.
- Acceptance: works on forks (documented token limits); example workflows for Python and TS; caching documented.

### IT-04 MCP server for agents (pre-push self-verification)   [ ]
- Owner type: pair
- Depends on: IT-02, TR-04
- Branch: `feature/mcp-server`
- Size: L
- Goal: an MCP server so coding agents (Claude Code, Cursor, others) can call Radius while working: `radius_verify_local` (diff -> criteria/evidence state), `radius_get_reprompt`, `radius_submit_intent`, `radius_submit_trajectory`.
- Acceptance: tools have clear schemas and descriptions; no tool executes arbitrary code on the user's machine beyond running the project's own tests when explicitly requested; auth via scoped token; tested against at least two MCP clients.
- Product hook: this is the answer to TestSprite's MCP distribution: verify *before* the PR exists.
- Security: tool outputs treated as untrusted by the agent; document prompt-injection considerations.

### IT-05 Agent hooks   [ ]
- Owner type: agent-ok
- Depends on: IT-04, PR-04
- Branch: `feature/agent-hooks`
- Size: M
- Goal: example hook configs that stream trajectory events and run quick tamper rules on file edits (e.g. Claude Code hooks); one-command setup (`radius init-agent`).
- Acceptance: documented, tested on a sample project; fail-open by default.

### IT-06 Evidence importers   [ ]
- Owner type: agent-ok
- Depends on: EV-01
- Branch: `feature/evidence-importers`
- Size: M
- Goal: accept JUnit, pytest JSON, Jest/Vitest JSON, coverage (XML/lcov), SARIF, Stryker/mutmut reports, and a generic JSON schema so results from other tools (including AI testing tools such as TestSprite-style reports) can count as evidence, bound to the head SHA.
- Acceptance: each importer has fixtures and size/format limits; imported evidence goes through the same `q(e)` pipeline (not trusted blindly).
- Product hook: Radius complements rather than competes with test generators.

### IT-07 Issue-tracker integrations   [ ]
- Owner type: agent-ok
- Depends on: IN-02
- Branch: `feature/intent-trackers`
- Size: L
- Goal: fetch intent from Plane, Jira, Linear tickets referenced by the PR; map acceptance criteria fields; write back status as a comment/link.
- Acceptance: OAuth/token handling per provider; least-privilege scopes; rate limits.
- Note: the team already uses Plane (MCP server available); start there.

### IT-08 Rule-pack plugin interface   [ ]
- Owner type: pair
- Depends on: EV-02
- Branch: `feature/rule-plugins`
- Size: M
- Goal: stable interface to add tamper/security rules as separate packages; signed/pinned rule packs; sandboxed evaluation; community contribution guide.
- Acceptance: example third-party rule pack; plugins cannot execute arbitrary code outside the rule sandbox; versioned API.

### IT-09 Public API docs and scoped keys   [~] (scoped, rotatable, hashed keys done by PRD-12; published OpenAPI docs and CI-run examples remain)
- Owner type: agent-ok
- Depends on: VD-03
- Branch: `feature/api-public`
- Size: M
- Goal: published OpenAPI docs, API keys with scopes (read, submit-evidence, admin), key rotation, usage limits.
- Acceptance: scope tests; documentation examples run in CI.

### IT-10 GitLab / Bitbucket (later)   [ ]
- Owner type: pair
- Depends on: IT-01
- Branch: `feature/vcs-gitlab`
- Size: XL
- Goal: abstract the VCS port and add GitLab; only after the evaluation shows the product value on GitHub.
- Acceptance: parity test suite across providers for webhook handling and publishing.
