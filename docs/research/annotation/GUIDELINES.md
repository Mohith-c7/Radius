# Annotation guidelines: intent criteria and testability (IN-09)

Version **gl-0.1** (draft; revised after the calibration round, see section 9 and the change log at the end).
Serves RQ1 (`../preregistration/PREREGISTRATION.md` section 5) and EP-04. Tooling: `scripts/gold_annotate.py`; file format: `benchmarks/gold/intent/schema.json`; agreement: `scripts/gold_agreement.py`. The examples below are **invented** for illustration; ids like `E3` and `N3` refer to this document only and are not real PRs.

> These guidelines are a hypothesis, like every threshold in this project. They are tested on the pilot (section 9); a kappa below 0.60 means the guidelines are revised, not that the annotators are wrong.

## 0. What you annotate and what you must not look at

You annotate **PR intent sources**: the stored, sanitized texts shown by the tool, of kind `pr_title`, `pr_body`, `issue` (linked issue title plus body), `commit_message`, `spec_file` (`.radius/intent.yml`) and `agent_prompt` (when present). PR comments are not part of the gold set.

You annotate from the text only. Do **not** open the PR, the diff, reviews, CI results, merge state or follow-up commits on GitHub, and do not read the code. Reason: criteria must be recoverable from intent text (that is what the system under test sees), and outcome information would leak into your judgement (`DATA_HYGIENE.md` section 5). If a text is unintelligible without the code, that is data: mark `no_recoverable_intent` (section 8) or annotate what is stated.

## 1. The unit: an atomic criterion

A **criterion** is one statement of what must be true after the change, expressed in the intent text, that a reviewer could in principle check as pass or fail without asking the author what was meant.

A statement is a criterion when **all** hold:

1. **Outcome, not process.** It says what the system, its behavior, its code structure, its configuration or its documentation is or does after the change, or what must not change. Present, future, imperative and modal forms all count ("returns 404", "will return 404", "return 404", "must return 404", "should return 404" when it is a requirement and not a wish by the author about themselves).
2. **Checkable in principle.** A reviewer could look at the diff, run the code, run a test or use a named tool and decide whether it holds. Vagueness does not disqualify a statement ("the UI feels cleaner" is a criterion, labelled `subjective_or_vague`); lack of any outcome does.
3. **Atomic.** One condition and one expected outcome that could pass or fail independently of the other statements (section 3).

A statement is **not** a criterion when it is:

| Kind | Example | Id |
|---|---|---|
| Narration of how the author worked | "I refactored this over the weekend." | N1 |
| Motivation or background without a requirement | "Users were confused by the error page." | N2 |
| Statement about evidence, tests, CI or review rather than the change | "Added tests", "All checks pass", "Ran pytest locally" | N3 |
| Process or PR-template boilerplate | "I have read CONTRIBUTING.md", "Self-review done", `- [ ] Docs updated` | N4 |
| Future work or out of scope | "Follow-up PR will handle pagination." | N5 |
| Instruction to the reviewer with no expected outcome | "Please take a look." | N6 |
| Question, speculation or hedge | "Maybe we should cache this?" | N7 |
| Implementation narration that adds no checkable requirement | "Added a helper function.", "Updated tests." | N8 |
| Logs, stack traces, environment details, quoted output | fenced block with a traceback | N9 |
| Placeholders | `N/A`, `TBD`, `_No response_`, unfilled template comments | N10 |

Counter-intuitive cases: "Rename `getUser` to `fetchUser`" **is** a criterion (structural, checkable by diff); "Added a helper function" is **not** (no requirement beyond existence). "Added tests for the empty-list case" is not a criterion; "an empty list returns `[]`" is. A checkbox's checked or unchecked state is irrelevant: `- [ ] Returns 404 for unknown ids` is a criterion even if unchecked.

## 2. Spans

You mark each explicit criterion with a **span** on one source. Spans use **character offsets into the stored text** shown by the tool (Unicode code points; half-open `[start, end)`, the same semantics as `radius_intent` `Span`). The tool computes offsets; you only select text. The validator rejects a span whose stored text differs from the selected slice.

Rules:

1. **Minimal sufficient text.** Select the smallest contiguous text that states the criterion completely: subject, condition (if any) and outcome. Include modifiers that change the outcome ("only when authenticated").
2. **No markup or whitespace at the edges.** Do not include the list marker (`- `, `* `, `1. `), the checkbox (`[ ]`, `[x]`), table pipes, leading `Given/When/Then` keywords only if they are part of a Gherkin block (see below), or trailing whitespace. The tool trims whitespace for you; it warns about markers. Include the final punctuation of the statement if it is inside the selection.
3. **Multi-line statements.** A statement that continues on following lines (hanging indent or lazy continuation) is one span across the line breaks.
4. **Inline formatting.** Keep backticks and bold markers that sit inside the statement; do not add them at the edges.
5. **Nested lists.** A parent ending with `:` that only introduces its children is not a criterion; each child is. Select the child text only (put the lead-in in `notes` if it matters, e.g. "under: When logged out"). A parent that is a full statement on its own is a criterion in addition to its children.
6. **Tables.** The cell text of a requirement/criteria/expected column is the span; one criterion per cell. Tables without such a column contain no criteria unless a cell is itself a statement under rule 1.
7. **Gherkin.** One `Scenario:` block (from `Scenario:` through its last step) is one criterion, selected as one span. Split it only when the `Then` steps state independent outcomes (section 3). `Background:` steps are not criteria. `Examples:` rows are data of the scenario.
8. **Code fences.** Content inside a fence is not a criterion (except Gherkin). The sentence that introduces expected output is.
9. **One criterion, one source occurrence.** If the same statement appears in several sources (title and body, issue and body), annotate **each occurrence** and add `notes: dup of <id>` on the later ones. Do not search for duplicates across sources to skip them; the evaluation harness merges near-duplicates, you do not.

### Examples

- E1 `- [ ] Login rejects an empty password with an error message` -> span `Login rejects an empty password with an error message`; label behavioral.
- E2 (nested)
  ```
  When the cart is empty:
    - checkout returns HTTP 409
    - the cart page shows "Your cart is empty"
  ```
  -> two criteria, spans `checkout returns HTTP 409` and `the cart page shows "Your cart is empty"`; note `under: When the cart is empty`.
- E3 (continuation) `The importer must skip rows where the id column is\n  blank and report their line numbers.` -> one span including the line break.

## 3. Granularity and compound statements

**Atomic test.** Would a competent tester write separate test cases with separate expected results for the parts? If yes, split; if the parts are conditions or parameters of one expected result, keep together.

| Situation | Decision | Example |
|---|---|---|
| Two independent outcomes joined by "and" | **split** | E4 "The API returns 400 for a missing name **and** logs a warning" -> two criteria |
| Several conditions leading to one outcome | keep | E5 "Return 403 when the user is not an admin **and** the flag is off" -> one |
| Enumerated values of one rule | keep | E6 "Accepts png, jpg and gif uploads" -> one |
| Enumerated cases with different outcomes | split | E7 "Empty list returns `[]`; null raises `ValueError`" -> two |
| Rule plus its rationale ("so that ...") | keep, span covers the capability, `so that` clause optional | E8 "As an admin I want to export users so that I can audit them" -> one (the whole story) |
| Gherkin scenario with several independent `Then` | split per independent outcome | E9 |
| Umbrella statement with sub-items listed below | children are the criteria | E2 |
| Sentence that is a criterion plus an aside | span only the criterion | E10 |

**How to record a split.**

- If each part has its own contiguous text, give each its own span (E7).
- If the parts share words and cannot be separated by contiguous spans (E4), create two criteria on the **same span**: select the criterion and press `d` (split), which duplicates it and gives both the same `compound_group`. Use `notes` to say which part each covers ("part 1: 400", "part 2: log") and label each part separately. The validator allows identical spans only within one `compound_group`. Matching against system output uses span IoU first and text similarity as a tie-break, so keep notes short and accurate.
- Do not split a statement just because it is long.

## 4. Explicit versus implicit criteria

- **Explicit**: a stated criterion you can select (everything above). This is the headline set for RQ1 extraction F1.
- **Implicit**: an expectation not stated as a sentence but so strongly entailed by the text that almost any reader would agree (target: >= 80% of annotators), for example a bug report with "Steps to reproduce" and no "Expected" section implies that the steps no longer fail. Record it with `explicit: false`, your own one-line paraphrase in `text`, and the supporting `evidence` spans (select, then press `i`).

Rules for implicit criteria:

1. Derive them from the **text only**, never from the code or your knowledge of the project.
2. At most **3 per PR**. If you need more, the PR probably has a weak description: use `well_specified = no` and annotate what is stated.
3. Do not invent edge cases ("also handles unicode") or quality attributes the author never implied.
4. Typical legitimate cases: reproduction steps without an expected result (E11); "Fixes #123" where the linked issue is itself in the sources and states the failure; "migrate X to Y" implying X is no longer used only when the text says "replace" or "remove" explicitly (then it is explicit).
5. Implicit criteria are reported separately and are not part of the headline F1; they are not matched by span (the tool counts them and lists them for adjudication).

## 5. Per-source-type rules

| Source kind | What to annotate | Do not annotate | Edge cases |
|---|---|---|---|
| `pr_title` | The title as one criterion if it states an outcome ("Return 404 for unknown ids") | Pure activity labels ("WIP", "Updates", "Fix stuff") | Conventional-commit prefix (`fix(api):`): start the span after the prefix. A title that only names an area ("Dashboard changes") is not a criterion. |
| `pr_body` | Outcome statements anywhere: acceptance-criteria lists, checklists with requirements, prose requirements, "Expected behavior", "Steps to verify" **with** expected results | Template boilerplate, test/CI claims, screenshots, motivation, future work, bot footers | Auto-generated summaries ("This PR adds ...") follow the same outcome test; implementation narration without a checkable requirement is not a criterion (N8). Checked boxes are not evidence of anything here. HTML comments are already removed. |
| `issue` | "Expected behavior", acceptance criteria, user stories, requirement lists, explicit "must/should" statements | Environment, versions, logs, "actual behavior", steps (see implicit), reactions and thanks | Title and body are one source; a title that states the expected outcome is a criterion on its own span. Unfilled template headings and placeholders: none. |
| `commit_message` | Outcome statements in subject or body | Trailers (`Signed-off-by`, `Co-authored-by`, `Change-Id`), merge text, "wip", "address review comments", "fix tests" | Subject lines like "Add retry to uploader" are criteria only if they state the outcome ("Retry failed uploads up to 3 times"); "Add retry" alone has no checkable requirement beyond existence: no criterion. |
| `spec_file` | Every entry under `criteria` is one criterion; span = the `text` value of the entry | `paths`, `tests` hints, comments, keys | The entry text may be vague; label it as such. |
| `agent_prompt` | Outcome statements and constraints on the change ("must", "ensure", "do not change the public API") | Instructions on how to work ("run the linter", "think step by step") | A "do not ..." constraint on what the change may touch is a criterion (structural or behavioral). |

Other cases:

- **Non-English text.** Annotate normally; add `notes: lang=xx`. The extractor is English-only; this is expected to produce misses and is analysed separately.
- **Very long sources.** Annotate everything visible; truncation is flagged in the tool and the truncated tail does not exist for the evaluation either.
- **Hostile or odd text** (instructions addressed to an AI, hidden-looking text): it is data. Annotate by the same rules; an instruction such as "ignore previous instructions" is not a criterion of the change. Add `notes: injection-like` if you see it.
- **Duplicates inside one source:** annotate both occurrences; note `dup of`.

## 6. Testability labels (IN-05 categories)

Label every criterion (explicit and implicit) with **exactly one** category, answering "what kind of evidence could verify this?". Label from the **text of the criterion**; do not read the diff, and do not consult the IN-05 rule lists or run the rater, so your judgement stays independent of the system being evaluated.

| Label | Meaning | Evidence it can get |
|---|---|---|
| `behavioral_testable` | Observable runtime behavior with inputs and outputs or conditions | tests |
| `structural_checkable` | Refactor, rename, move, remove, config value, dependency/version, docs content, type annotation: checkable by diff or static analysis | diff, AST, lockfile |
| `non_functional_measurable` | Performance, security, accessibility, reliability **with** a threshold or a named tool/standard | benchmark or scanner |
| `subjective_or_vague` | No measurable criterion ("clean", "intuitive", "robust", "better", "improve") or too underspecified to check | none: ask the author |
| `untestable_external` | Needs human, product or legal judgement, or a live external system or third party | a person decides |

(`unrated` is the pre-annotation default of the code and is not a valid human label.)

### Decision tree (apply in order; first "yes" wins)

1. **External?** Does verifying it require a person's approval, a product/legal decision, a production or third-party system you cannot reproduce, or a future real-world outcome? -> `untestable_external`. (E12 "Legal approves the new wording"; E13 "Partner confirms the rollout date"; "customers are happier".)
2. **Non-functional?** Is the subject a quality attribute (latency, throughput, memory, security hardening, accessibility, availability)?
   - with a **threshold, budget, or named tool/standard** ("p95 under 200 ms", "passes WCAG 2.1 AA audit", "no high findings in `npm audit`") -> `non_functional_measurable`;
   - without ("faster", "more secure", "accessible") -> `subjective_or_vague`.
   - If it also states a concrete observable behavior ("rejects tokens older than 5 minutes"), that behavior decides: `behavioral_testable`.
3. **Behavioral?** Does it describe what the running system does in response to inputs, states or events (responses, errors, UI states, side effects, outputs, logs when the content is specified)? -> `behavioral_testable`.
4. **Structural?** Can it be decided by reading the diff or running a static check, with no execution of the feature (rename, move, delete, add a dependency at a version, change a config value, update a doc section, add a type annotation, remove dead code)? -> `structural_checkable`.
5. Otherwise -> `subjective_or_vague`.

### Tie-breakers and examples

| Criterion | Label | Why |
|---|---|---|
| E14 "Return HTTP 404 for an unknown id" | behavioral | input -> output |
| E15 "Rename `utils.py` to `helpers.py`" | structural | diff decides |
| E16 "Remove the deprecated `/v1/ping` endpoint" | behavioral if the text implies the route stops answering ("returns 404"); structural if it only says to delete the handler code. When unsure: behavioral. |
| E17 "p95 latency of search stays under 200 ms" | non_functional_measurable | threshold |
| E18 "Search is much faster" | subjective_or_vague | no measure |
| E19 "Passwords are hashed with bcrypt" | structural if the diff shows it (a named algorithm in code); behavioral if worded as observable ("stored passwords are not recoverable") -> follow the wording | |
| E20 "Bump lodash to 4.17.21" | structural | lockfile |
| E21 "The code is cleaner" | subjective_or_vague | no measure |
| E22 "Add logging when a job fails" | subjective_or_vague (what is logged is unspecified); "log the job id and error message at ERROR level when a job fails" -> behavioral | |
| E23 "Update the README with the new flag" | structural | doc content in diff |
| E24 "Works on Windows" | behavioral if it names an observable (e.g. "the CLI runs on Windows"), else vague | |
| E25 "TBD" / "see ticket" | subjective_or_vague | no content |
| E26 "Ship before the conference" | untestable_external | external event |

If two labels seem right, choose the one whose **evidence type** you would actually use first, and write the other in `notes` ("also structural"). Disagreements here are expected and are what adjudication is for.

## 7. Links (LK-07): reserved

Link annotation (criterion -> changed or blast-radius symbol; symbol -> test) is **not part of IN-09** and starts only after the criteria are adjudicated (the criteria set must be fixed first). The gold files already reserve a `links` array (empty now) and the schema fixes the minimum shape: `criterion_id`, `link_type` (`criterion_symbol` or `symbol_test`), `target`, `label`. LK-07 will define symbol and test identifiers, the label set (planned: implements / partial / none and exercises / asserts / none), the candidate list shown to annotators, and the agreement metric (kappa on link labels, as preregistered). The same blinding rules apply: annotators must not see Radius's ranked candidates.

## 8. Per-PR decisions and flags

Set these **before** looking at anything else about the PR's quality (the tool asks first):

- **`well_specified`** (yes/no), per the preregistration: yes iff the sources contain explicit acceptance criteria in a checklist, an "Acceptance Criteria" (or equivalent) heading, Gherkin, or a linked issue with numbered requirements. Decide this from the structure of the sources, **not** from how many criteria you end up marking, and before any system output exists (there is none in your tool).
- **`no_recoverable_intent`**: tick when the sources contain no outcome statement at all (only boilerplate, "fix", a bare link). Then the criteria list is empty. These PRs stay in the all-PR analysis.
- **`notes`** per criterion and per PR for anything unusual. Notes are read at adjudication, never by the system.

## 9. Procedure

**Roles.** Annotator A and annotator B work independently on every PR. A third person C adjudicates. A, B, C are three different people (`gold_agreement.py skeleton` and the tool refuse C = A or B).

1. **Independent pass.** Each annotator runs the tool in its default blinded mode with a personal queue (`gold_sample.py queue` shuffles per annotator). You do not discuss PRs with the other annotator, you do not look at their files, and you do not see Radius output. Save happens automatically; finish a PR with `c`.
2. **Calibration round (10 PRs).** The first 10 PRs of the pilot set are annotated by both annotators independently, then compared with `gold_agreement.py compare --prs calib.txt`. A and B (and C) meet, walk through every disagreement, and agree on guideline clarifications. Revise this document (bump the version, add rows to the change log). Calibration PRs are **discarded** from all analyses (they are in the pilot role, PREREGISTRATION 5.3).
3. **Reliability check (remaining 20 pilot PRs).** Annotated independently under the revised guidelines. Gate: criterion-presence kappa and testability kappa >= 0.60 (PREREGISTRATION 5.4; initial guess). Below 0.60: revise the guidelines and re-annotate a **fresh** pilot of PRs once; if still below, record "annotation reliability insufficient" (PREREGISTRATION stopping rules).
4. **Dev and test annotation.** Same independent procedure. The sample is fixed before annotation and no PR is dropped after seeing system output (PREREGISTRATION 5.6).
5. **Adjudication.** `gold_agreement.py skeleton --adjudicator C` writes `adjudicated.json` with agreed items prefilled and every disagreement as a pending item showing both proposals. C resolves each: take A, take B, merge (edit the span or label), add, or drop. C may consult the two annotators for contested items; if a consensus meeting is used instead of a single adjudicator, record `adjudication_method: consensus meeting` in the batch notes of `benchmarks/gold/README.md`. `--prefill-from-radius` is off by default and, if enabled for C, marks every accepted item `from_radius_suggestion`; it is never available to A and B (section 10).
6. **Time logging.** The tool logs active seconds per PR per annotator (focus plus input within 60 s). Do not leave a PR open while away; use the browser tab normally. Self-reported breaks are not needed. Times are used for the runbook estimate and, if wanted, for an annotation-cost note in the paper.
7. **Order effects.** Use your personal queue order; do not reorder to do easy PRs first.

## 10. Conflict of interest and blinding

Hard rules (violations invalidate that PR's annotation):

1. **No system output during independent annotation.** You must not see the output of the Radius extractors (deterministic or LLM), testability rater, dashboard, CI comments, or any LLM answer for these PRs. The tool refuses prefill in annotate mode. Do not use an AI assistant to annotate.
2. **Annotator independence.** No discussion of a PR with the other annotator before both have completed it, except in the calibration meeting. Do not read the other annotator's files (they live in the same directory; the tool never loads them, you must not open them).
3. **Not your own work.** You must not annotate PRs you authored, reviewed or merged, or PRs in repositories you maintain. Declare these in `benchmarks/gold/intent/conflicts.json`:
   `{"alice": {"repos": ["owner/name", "owner/*"], "login_sha256": ["<sha256 of your lower-cased GitHub login>"]}}`. The tool refuses to open conflicting PRs for you.
4. **Radius developers.** People who wrote or tuned the Radius extractors have seen the rules and are not neutral. They must not be annotator A or B on the **test** role. If the owner has to annotate, this is disclosed in the datasheet and a sensitivity analysis excluding those PRs is reported. The adjudicator should not be the person who tuned the extractors on the dev set.
5. **No outside lookups** (section 0).
6. **Anchoring.** Adjudicators see both annotators' proposals; to limit bias, resolve each item before reading the notes of the other side and do not favour the annotator you know better.

## 11. Data handling

PR text is third-party content. Work only on the local copy under `benchmarks/gold/intent/` (git-ignored). Do not paste PR text into any online service. Annotator ids are pseudonymous (`[a-z0-9_-]`). Author logins are stored only as sha256. Follow `DATA_HYGIENE.md` sections 2 and 6; release only the text-free export (`gold_validate.py export-public`) after owner review.

## Change log

- gl-0.1 (draft, before calibration): initial version.
