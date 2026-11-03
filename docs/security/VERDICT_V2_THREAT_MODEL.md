# Verdict v2 (alpha): threat model for author-controlled evidence

Status: alpha. Applies to `RADIUS_FEATURE_VERDICT_V2` (`shadow` and `on`). Decision: DEC-030. Related: DEC-008, DEC-027, `docs/verdict-v2.md`, `docs/security/PROMPT_INJECTION.md` (text injection is a separate topic and is covered there).

## The adversary

Verdict v2 exists to check work that someone else produced, often a coding agent. The most important adversary is therefore **the pull request author** (a person, or an agent acting for them) who wants a PR to look supported. They are not assumed to have write access to the base branch, the Radius deployment or GitHub settings. They fully control the pull request itself.

## What the author controls

| Input | Where it enters | What it influences |
| --- | --- | --- |
| PR title, description, commit messages | intent ingestion (`pr_title`, `pr_body`, `commit_message` sources) | which criteria exist, how easy they are to satisfy |
| `.radius/intent.yml` at the PR head | intent ingestion (`spec_file` source) | criteria text and weights; `paths:` hints (criterion to code) and `tests:` hints (criterion to test) |
| Test files they add or change | the head checkout | which tests exist, their assertions (`a_static`), names (lexical relevance) |
| Commit trailers | independence (`i`) | a human-looking history gives independence 1.0, an unknown author 0.8, a detected agent trailer 0.6 |
| Which tests CI runs and uploads | `POST /analyses/{id}/tests/results` | outcomes (bound to the head SHA; the uploader must be authorised for the repository) |
| Issues they write and link | `issue` source | criteria, if the PR links an issue they authored |

Before the DEC-030 hardening, a `tests:` hint gave link strength 0.95 to 1.0, so an author could state easy criteria, point them at tests they wrote, and receive `PROVEN` and a green Check Run.

## Mitigations in the alpha

1. **Provenance on every criterion and hint.** Each criterion and each `tests:` / `paths:` hint carries one of `author_pr_body`, `author_head_spec`, `base_spec`, `human_confirmed`, `llm_proposed` in the Stage A input, the bundle, the API payload and the dashboard.
   * a criterion in state `confirmed` or `edited` is `human_confirmed` (the only way to reach those states is the authenticated intent API; Radius itself never confirms);
     the stored verdict picks the decision up through the republish outbox (DEC-033): the request carries no provenance, the worker derives `human_confirmed` only from the stored criterion state, and the API schema rejects extra body fields;
   * a spec-file criterion is `base_spec` only if `.radius/intent.yml` exists on the **base ref** and is byte-identical (ignoring line endings) to the head file, read from the local checkout with `git show <base>:.radius/intent.yml`; if the base ref is unknown, the file is absent from the base, or it differs in any way, it is `author_head_spec`;
   * everything from the PR text, commits, comments and linked issues is `author_pr_body`, because the author may control it (an issue written by someone else is not distinguished yet; see limits);
   * LLM proposals are `llm_proposed`.
2. **The author-hint cap.** The criterion-to-test weight of a `tests:` hint whose provenance is not `base_spec` or `human_confirmed` is capped at `author_hint_cap` (default 0.7, `LinkMapping.author_hint_cap`, part of the config digest). The cap applies in Stage B so a stored Stage A can be re-scored with a different cap. With the alpha defaults a single strong test then cannot lift a criterion to the support threshold on its own link (fixture 01 shows `verified` becoming `insufficient_evidence`).
3. **A visible reason and flag.** A criterion whose counted tests rely on a capped hint gets reason code `author_supplied_hint` and flag `author_supplied_hint`; the comment says `N criteria rely on author-supplied test hints`, the Check Run summary repeats it, and the dashboard shows it.
4. **Intent versus diff.** Intent coverage (the share of behavioral changed symbols that a stated criterion accounts for) already feeds rule R2c (`low_intent_coverage`, minimum 0.50, configurable in `RuleConfig.min_intent_coverage`). The comment now says in the summary line when coverage is below the minimum, whichever rule decided the verdict. A PR whose criteria say little about what the code does cannot reach `verified` on easy criteria alone.
5. **Alpha wording and an advisory check.** The Check Run is `neutral` (never green) unless an operator sets `RADIUS_VERDICT_V2_CHECK_CONCLUSIONS=strict`; a red check needs hard evidence (R1a, R1b, R1c). States read SUPPORTED, not PROVEN. This limits the damage of a wrong `verified`: it cannot satisfy branch protection by default.
6. **Existing controls that bear on this adversary.** Tamper rules (weakened or removed assertions, skipped tests, mock-only tests), static assertion strength (a test that asserts nothing scores near 0), independence discounting for agent-authored tests, freshness binding to the head SHA, and flaky-test discounting.

## What remains (accepted in the alpha, stated plainly)

* **A consistent author still gets SUPPORTED.** An author who writes trivial criteria and strong-looking tests for them (high assertion strength on a function they control) can reach `verified` with no hints at all, via lexical relevance. Nothing in the alpha compares the criteria with an intent the author did not write.
* **PR text is trusted as `author_pr_body`, not verified.** The cap covers `tests:` hints and, since DEC-037, `paths:` hints and path mentions whose only support is the author's own text; criteria text from the description is scored as given. Intent coverage only counts what the criteria mention, and an author-hinted link no longer covers a whole file or directory. Criterion weights set by the author are ignored unless the spec comes from the base branch or a human confirmed the criterion.
* **Unanalysed files are visible, not analysed (B-02, B-03).** A changed file outside the inert allowlist that no analyser understands makes `verified` unreachable (`unanalyzed_files:<n>`); a test, CI, build, manifest or snapshot file the tamper engine could not read (over 1 MB, binary, unparsable) or an incomplete engine run makes it unreachable too (`tamper_unanalyzed:*`). Dependency manifests, CI workflows and build configuration are still only checked by the tamper catalog's own patterns; lockfiles are treated as inert (owner decision, DEC-037).
* **Suggested tests are shown, never run (B-08).** The static gate is a deny-by-default allowlist (only calls to the changed symbols, `pytest.raises/approx/mark.parametrize`, a short list of pure builtins and string/list/dict methods; no dunder names or strings, no `getattr`/`type`/`vars`, no `pytest.importorskip/main/skip`, no loops or lambdas). It is a filter, not a sandbox: an accepted snippet is still model-written code from author-controlled text and should be read before it is run.
* **Independence is a heuristic.** Trailers can be removed; a tests-written-in-this-PR discount (0.8) is mild.
* **The base-spec check is whole-file.** A one-line change to a trusted spec file drops every criterion in it back to `author_head_spec`; adding a criterion to a base spec in the same PR is not distinguished per criterion. This is conservative, not exact.
* **Human confirmation is attributed only by an unverified label (B-07, DEC-037).** The audit trail stores the actor (`org:<id>[/<X-Radius-Actor label>]`); the verdict shows `confirmed by <label>`, and a label equal to the PR author's login is not counted as a confirmation. The label is a request header the caller chooses, and the intent API authenticates an organisation (an API key), not a person. A PR author who holds the organisation's API key can confirm under another label or none, and then lifts the unconfirmed block and the hint cap. Residual risk, accepted: set the label from the authenticated user at the proxy or SSO layer, protect paths with a policy that needs `human_confirmed` plus review, or replace the `confirm_policy` hook (`intent_refresh.refresh_stage_a_intent`, for example a reviewer allowlist). Confirming a criterion also confirms the hint list that came with it; hints are not shown separately, and `edited` keeps the old links for the new wording.
* **Issues by other people are not yet trusted separately.** An issue authored by a third party would deserve a higher trust level than the PR description; the alpha does not look at issue authorship.
* **Outcome uploads.** If an attacker can upload results for the head SHA they can mark tests as passed; this is the existing CI-upload trust boundary (API key scoping, SHA binding), not new.
* **Gold fixtures are not adversarial.** The 8 fixtures were written with the design; none contains a self-consistent adversarial PR.

## Recommended policy

Until calibration and a policy engine exist:

1. Keep the Check Run advisory (default). Do not make `Radius confidence` a required check on `verified` alone.
2. For protected paths (auth, payments, build and release configuration, CI workflows, the `.radius/` directory itself), require that the criteria are **human-confirmed** in the intent panel before relying on `verified`, and keep `.radius/intent.yml` on the base branch so hint changes need a separate reviewed PR.
3. Treat `author_supplied_hint` as "ask a reviewer", not as noise.
4. The policy engine (VD-04, being built on `feature/verdict-v2-policy-waivers`) is intended to enforce item 2: a rule such as "paths matching P require every counted criterion to be `human_confirmed` or `base_spec`" turning the verdict into `needs_review` otherwise. This document does not describe that engine's behaviour; see its own documentation when it lands.

## How to change the defaults

* `author_hint_cap`: `VerdictV2Config(link=LinkMapping(author_hint_cap=...))`. A value of 1.0 removes the cap but the flag and reason are kept.
* `min_intent_coverage`: `RuleConfig.min_intent_coverage` (default 0.50).
* Check Run conclusions: `RADIUS_VERDICT_V2_CHECK_CONCLUSIONS` (`advisory` default, `strict`), worker setting.

## Summary-mode inferred criteria (DEC-032)

With `RADIUS_INTENT_EXTRACTION_MODE=summary`, the PR author's title and bullets become proposed criteria. An author could therefore write easy-to-satisfy bullets ("Adds a retry") that the lexical linker then matches to the PR's own tests. Mitigations: such criteria are `author_pr_body`, weight 0.5, carry no `tests:` hints, and while any is unconfirmed the verdict cannot be `verified` (blocking degraded reason `unconfirmed_inferred_intent`, R2d). Not stopped: the author can still make the verdict worse or noisier with many bullets (capped at 12 per source), and a confirming human still sees only the author's wording. Default mode is `sections`, where none of this applies.

## LLM proposals and suggested tests (DEC-034)

**Data leaves the machine.** With `RADIUS_INTENT_EXTRACTION_MODE=llm` the PR title and body, and with `RADIUS_FEATURE_SUGGEST_TESTS` the criterion text and the names of changed modules and symbols, are sent to a third-party model provider (Anthropic) under your API key. Source code and diffs are not sent. Text is redacted of known secret patterns and of the process's own secret-looking environment values before sending, but PR text can contain anything its author wrote: do not enable these for repositories whose PR text must stay in-house. Egress is gated per organization (`RADIUS_LLM_INTENT_ENABLED`, `RADIUS_LLM_INTENT_ORGS`), off by default, and checked before every call.

**Prompt injection.** The PR author controls the text sent to the model. Defences, none of which relies on the model behaving: the text is sanitised and placed in nonce-delimited data blocks with an instruction to treat them as data; the model has no tools; its reply must be one strict JSON document (unknown fields, verdict-like fields, URLs, commands, the nonce, secrets or system-prompt fragments reject it); every proposal must quote the PR text verbatim and be grounded in its quote, so the model cannot introduce content the author did not write; the output is only ever a `proposed` criterion or a suggested snippet. What injection can still do: make the model propose weak, odd or many criteria (capped; the verdict cannot be `verified` while any is unconfirmed, and a human sees each), waste tokens (per-analysis and per-organization token caps, a circuit breaker), or write a misleading test snippet. A snippet is only displayed after the gate (parse, only changed-symbol imports, no `open`/`exec`/`eval`/dunder access, a strong assertion on a changed symbol) and is rendered in a fenced block with invisible characters removed; it is never executed by Radius, so it cannot run code, but a reader who copies it into their repository is trusting it as they would trust any pasted code. Not stopped: a human who confirms an LLM proposal without reading it; a plausible but wrong snippet that passes the gate.

**Integrity of the verdict.** The scoring, the rules and the states do not take any LLM output as input; the suggestions are attached after scoring and are stripped of any evidence flag by the payload builder. A wrong, absent or hostile model changes at most the list of proposals and the suggestions, which is tested with a fake model.
