# Repository policy and waivers (Verdict v2)

Two optional files in the repository tune the Verdict v2 result and let people accept a finding on purpose:

| File | What it does |
| --- | --- |
| `.radius/policy.yml` | thresholds, required criterion states per path, tamper rule severities, minimum evidence, path exclusions, advisory or blocking mode |
| `.radius/waivers.yml` | time-limited, owned, audited acceptance of a tamper finding, a tamper rule inside a path scope, or a criterion |

Both only matter when `RADIUS_FEATURE_VERDICT_V2` is `shadow` or `on`. With the flag `off` (the default) nothing here is read and v1 is unchanged. A sample policy is in `.radius/policy.example.yml` and a sample waivers file in `.radius/waivers.example.yml` (rename to drop `.example`).

## The rule that makes this safe: files are read from the base branch

A pull request must not be able to loosen the rules it is judged by. Radius therefore reads **both files from the base side of the pull request** (the commit the PR targets), never from the PR head:

- A PR that edits `.radius/policy.yml` or adds `.radius/waivers.yml` is judged by the policy and waivers that exist on the base. The edit takes effect for later PRs, after it has been reviewed and merged like any other change. Protect `.radius/` with CODEOWNERS and branch protection.
- If the base commit cannot be resolved in the checkout, the files are reported as **unreadable** (not as absent) and the verdict is `Not verified` with `analysis incomplete (policy_unreadable)`. A missing object can never read as "no policy".
- A base policy that is syntactically broken or has an unsupported `version` marks the analysis incomplete (`policy_invalid`, rule R2d). Fix the file on the base branch. A broken **waivers** file is the safe direction: every waiver is ignored and the error is shown.

### Optional: a head policy that may only tighten

A repository can let PR authors propose stricter rules for their own PR by opting in **in the base policy**:

```yaml
version: 1
head_policy: tighten_only
```

Only then does Radius also read `.radius/policy.yml` from the PR head, and each head setting is accepted only if it is at least as strict as what the base side already gives:

| Head setting | Accepted when |
| --- | --- |
| `tau_support`, `intent_coverage_min`, `link_review_min` | higher than the base value (or the default) |
| `uim_max`, `cap_static` | lower than the base value (or the default) |
| `tamper.fail_on_at_least`, `review_on_at_least` | a lower (stricter) severity |
| `mode` | `blocking` (never `advisory` over `blocking`) |
| `tamper.rules.<id>: <severity>` | the severity is higher than the engine's (it can only raise) |
| `require` entries, `evidence.require_non_agent_test: true` | always (they add requirements) |
| `enabled: false`, `allow_disable`, `exclude` | never |

Everything dropped is listed under "Ignored (head policy may only tighten)" with its line number. Without the opt-in the head file is not even read. `.radius/waivers.yml` is **never** read from the head.

## `.radius/policy.yml`

```yaml
version: 1                  # required; only 1 exists

mode: advisory              # advisory | blocking (see "Mode" below)
head_policy: ignore         # ignore (default) | tighten_only

thresholds:                 # every value has a safe range; outside it the key is ignored with an error
  tau_support: 0.5          # 0.30 to 0.90   support needed for "proven"
  uim_max: 0.2              # 0.00 to 0.40   unproven intent mass allowed
  intent_coverage_min: 0.5  # 0.30 to 1.00   share of behavioral change a criterion must account for
  link_review_min: 0.5      # 0.30 to 0.90   weakest criterion-to-code link a proven criterion may rest on
  cap_static: 0.6           # 0.30 to 0.80   ceiling on what static assertion strength can contribute

tamper:
  fail_on_at_least: high    # medium | high      severity that fails the PR (rule R1c)
  review_on_at_least: medium  # low | medium | high  severity that needs review (rule R3a)
  rules:
    T002: medium            # shorthand: set the severity of rule T002
    T012:unverified_guarded_import:
      severity: low         # a single check of a rule
    T016:
      enabled: false        # disable a rule (medium and low findings only, see below)

require:                    # required criterion states per path
  - paths: ["src/auth/**", "src/payments/**"]
    min_state: proven       # proven | weak

evidence:                   # minimum evidence
  require_non_agent_test: true   # every proven or weak criterion needs a counted test that was not agent-authored
  paths: ["src/auth/**"]         # optional scope; default is every criterion

exclude:                    # "not required": changed code here is not counted as behavioral change
  paths: ["docs/**", "**/*.md"]
```

### Thresholds

Each override replaces one default of the profile (`alpha-static`) and appears in the verdict's `thresholds`, `config_digest` and provenance. The ranges are deliberately narrow: a policy cannot set `uim_max: 1.0` to make the unproven-intent rule unreachable. A value outside its range, or not a number, is reported as an error (with the line) and that key falls back to the default; the rest of the file still applies.

### Tamper rule severities and the `allow_disable` acknowledgement

`tamper.rules` maps a rule (`T002`) or one of its checks (`T012:unverified_guarded_import`) to a severity or to `enabled: false`. A check-specific entry beats a rule-wide one. The allowed severities are `info`, `low`, `medium`, `high`, `critical`.

- **Raising** a severity, or lowering/disabling a finding that the engine reported as `medium` or lower, needs nothing extra.
- **Lowering a `high` or `critical` finding below `high`, or disabling the rule for such a finding, is refused** unless that rule entry carries a reason:

```yaml
tamper:
  rules:
    T005:
      enabled: false
      allow_disable: "Security signed off on this, ticket SEC-12"   # at least 10 characters
```

  The refusal is shown in the comment and API (`policy.tamper.refused`) and the finding stays. When the acknowledgement is present the change is applied **and recorded**: `policy.tamper.acknowledgements` holds the rule, the finding id, the original severity, the reason, the policy line and where it came from. It is also copied into `justification.policy`.
- `tamper.fail_on_at_least` accepts `medium` or `high` (not `critical`), so it cannot be used to quietly stop failing on `high` findings. `review_on_at_least` must be at or below it.

### Required states per path (`require`)

For every `require` entry, each non-excluded criterion linked to code under the paths must reach `min_state`. Changed behavioral code under the paths that **no criterion covers** also counts as unmet, so deleting a criterion cannot dodge the requirement. Unmet requirements fire the new rule **P1** (`policy_requirement_unmet`, verdict `insufficient_evidence`).

Rules P1 and P2 are evaluated after R2d and before R3a, and only exist when the policy has `require` or `evidence` entries; without them the rule list is exactly R1a to R4. A failed CI case (R1b) or a contradicted criterion (R1a) still decides first.

### Minimum evidence (`evidence`)

`require_non_agent_test: true` fires **P2** (`policy_min_evidence`, `insufficient_evidence`) for a proven or weak criterion whose counted tests are all agent-authored (tests added or changed in a PR that carries an agent trailer such as `Co-Authored-By: Claude`). Tests that already existed unchanged at the base count as not agent-authored.

### Exclusions (`exclude`)

Changed behavioral code under `exclude.paths` is left out of the coverage denominator and of the "behavioral code changed" test (rule R2a). It does **not** hide tamper findings, criteria or CI results.

### Mode: advisory vs blocking

`mode` never changes the verdict. It only maps the verdict to the **Check Run conclusion**:

| Verdict | no policy / no `mode` | `advisory` | `blocking` |
| --- | --- | --- | --- |
| verified | success | success | success |
| failed | failure | neutral | failure |
| insufficient_evidence | neutral | neutral | failure |
| needs_review | neutral | neutral | failure |
| pending (awaiting CI) | neutral | neutral | failure (republished when results arrive) |
| verdict unavailable | neutral | neutral | neutral |

GitHub treats a neutral check as passing for branch protection, which is why `blocking` maps every unverified result to `failure`. Start with `advisory`, review the comments for a few weeks, then switch to `blocking` and mark `Radius confidence` as a required check.

### Provenance

The resolved policy is in the verdict (`policy` in the API payload, `justification.policy` in the stored tree): the source file, base ref and SHA-256, the mode, every applied setting with the policy line it came from (`thresholds.tau_support = 0.6, line 5, base`), head settings dropped, tamper changes/acknowledgements/refusals, unmet requirements, and the parse errors and warnings. The comment shows a one-line summary and a collapsible "Policy" section.

### Errors and warnings

The parser is strict and has no dependency on a YAML library. It accepts mappings, `- ` lists, quoted or plain scalars and single-line `[a, b]` lists; it rejects tabs, anchors, aliases, tags, flow mappings (`{}`), block scalars (`|`, `>`), multiple documents and nested lists. Quote values that start with `@` or contain `: `.

- **Unknown keys** are warnings (line shown) and ignored.
- **Bad values** (out of range, wrong type, unknown enum, bad glob) are errors for that key; the default applies and the rest of the file is used.
- **Structural failure** (syntax error, missing or unsupported `version`, file larger than 64 KiB) makes the policy invalid; see the base-branch section above.

Path globs use `*` (within a directory), `**` (any depth, as a whole path segment) and `?`; they are repository-relative and `..` or absolute paths are rejected.

## `.radius/waivers.yml`

```yaml
version: 1
waivers:
  - id: W-2026-001                 # unique, letters/digits/._-
    finding: tf_0e4c6939a63e008c   # a tamper finding id (stable across rebases) ...
    # rule: T002                   # ... or a tamper rule (needs paths), or
    # criterion: crit_9            # ... a criterion id
    reason: "Legacy fixture is regenerated nightly, tracked in SEC-42"   # 20 to 500 characters
    owner: alice                   # required: a GitHub user, "@org/team" (quote it) or e-mail
    created: 2026-10-30            # required ISO date, not in the future
    expires: 2026-12-01            # required ISO date, at most 90 days after created
    paths: ["tests/legacy/**"]     # scope; required for a rule waiver, optional otherwise
```

- **Expiry** is evaluated on the date of scoring (UTC). The expiry day itself still counts; the next day the waiver stops applying and the finding comes back. Recomputing on the same day gives the same result.
- **Invalid, expired and duplicate waivers are ignored and reported** (`waivers.ignored` with a code such as `expired`, `reason`, `lifetime_exceeds_max`, `rule_needs_paths`, `scope_mismatch`, `not_waivable_contradicted`) and listed in the comment. They are never silently dropped. A waiver that matches nothing is recorded as `unused`.
- **Waived tamper findings stay visible.** They are listed as `WAIVED` with the waiver id, owner, expiry and reason, in the comment and in the API (`tamper_findings[].waived`, `.waiver`, `summary.tamper_waived`). They no longer count for R1c/R3a or for the tamper penalty on the evidence.
- **A criterion waiver** sets the criterion to `excluded` with the visible reason code `waived` (owner, expiry, waiver id).
- **What can never be waived:** a `contradicted` criterion (the waiver is ignored with `not_waivable_contradicted`) and a failed CI case. There is no waiver target for CI results, and the failed-case count (R1b) is not an input to any waiver or policy logic. Policies and waivers cannot turn either into a pass.
- **Audit record:** every verdict stores `waivers`: the file source (ref, SHA-256), the waivers applied (with the finding ids or criterion they covered), the ones ignored with codes, the evaluation date and an `audit_digest`. It lives in the stored bundle for that verdict revision, so it can be reconstructed for any past verdict. The file is read from the base branch, so the person who merged the waiver is visible in git history; there is no role check inside Radius, review of changes to `.radius/` is the control.

## What this does not do (yet)

- No organization-level defaults or per-org overrides (the file is per repository), no JSON-schema file, and no `audit_log` row when a policy changes; the git history of `.radius/` is the change record.
- No role check inside Radius for who may create a waiver; it relies on protecting `.radius/` on the base branch.
- No `mutation` or typed-evidence rules (alpha has no such evidence), and no "agent-authored PRs are stricter" switch beyond `require_non_agent_test`.
- The dashboard does not render the policy section yet; the API and the PR comment do.
