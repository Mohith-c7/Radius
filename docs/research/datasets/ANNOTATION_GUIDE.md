# Annotation guide: start here (second annotator and adjudicator)

Status: **no real annotation exists yet.** This is the short, practical entry point for the people who will produce the gold set for RQ1 (IN-09 / EP-04). It does not replace anything: the binding rules are [`../annotation/GUIDELINES.md`](../annotation/GUIDELINES.md) (version gl-0.1, a draft that is revised after the 10-PR calibration round), the owner's procedure is [`../annotation/RUNBOOK.md`](../annotation/RUNBOOK.md), and the data layout is [`benchmarks/gold/README.md`](../../../benchmarks/gold/README.md). If this guide and GUIDELINES.md disagree, GUIDELINES.md wins and this guide is the bug. All examples below are **invented** and are not from any real pull request.

## 1. What you are producing

For each pull request you are given, you read its intent text (title, body, linked issue, commit messages, `.radius/intent.yml`) and mark every **atomic criterion**: one statement of what must be true after the change that a reviewer could check as pass or fail. For each you select the exact text span and give it one of five testability labels. You also decide once per PR whether it is `well_specified`. That is all. You never judge whether the PR is good or whether the code is correct.

Your work is compared with a second annotator's, independently made. The disagreements are the point: they show where the guidelines are unclear, and a third person resolves them.

## 2. Hard rules (breaking one invalidates that PR)

1. **Blind.** You see only the PR text in the tool. No Radius output, no dashboard, no CI comment, no AI assistant, no candidate list. (Candidates are withheld on purpose: a pre-filled list anchors people toward it.)
2. **Independent.** Do not discuss a PR with the other annotator until both of you have finished it, except in the scheduled calibration meeting. Do not open the other annotator's files.
3. **Text only.** Do not open the pull request, the diff, the repository, reviews or CI on GitHub, and do not search for it. Outcome information leaks into your judgement.
4. **Not your own work.** If you wrote, reviewed or merged a PR, or maintain its repository, declare it in `benchmarks/gold/intent/conflicts.json` (format in GUIDELINES 10.3); the tool then refuses to show it to you.
5. **Radius developers** should not be annotator A or B on the test PRs (GUIDELINES 10.4).
6. **Keep your order.** Work through your queue in the given (randomised) order.

## 3. How to work (offline kit)

The owner runs `python scripts/gold_pack.py export --annotator <your-id> --seed <seed> --out kit/` and gives you the folder. It contains the annotation tool (Python 3.12, standard library only, no network), the schema, the guidelines, your queue and the source texts, and nothing else. In the folder:

```
python scripts/gold_annotate.py serve --annotator <your-id> --queue queue.txt --open
```

The tool serves a page on `127.0.0.1` only. Press `?` for the keyboard shortcuts. Your work is saved after every change; stop and resume freely. Finish each PR with `c`. When done, return the folder; the owner runs `gold_pack.py import`, which checks every file against the schema and the stored source hashes and refuses anything that does not validate.

If you work inside the repository instead, the commands are in the RUNBOOK (section 4.5).

## 4. Per PR, in this order

1. Decide **`well_specified`** (yes/no) from the *structure* of the sources, before marking anything: yes only if there is an explicit acceptance-criteria checklist or heading, Gherkin, or a linked issue with numbered requirements. Do not decide it from how many criteria you later find.
2. If the text contains no outcome statement at all, tick **`no_recoverable_intent`** and finish.
3. Select each criterion's span; label it; add a note when something is unusual.
4. Finish the PR.

## 5. The rules that decide most cases

A statement **is** a criterion if it states an outcome (what the system, code structure, config or docs are or do after the change, or must not change) and is checkable in principle and atomic. It is **not** a criterion if it is narration, motivation, a claim about tests or CI, template boilerplate, future work, an instruction to the reviewer, a question or hedge, implementation narration with no requirement, a log or trace, or a placeholder (GUIDELINES 1, table N1 to N10).

Spans: the smallest contiguous text that states the criterion completely; no list marker, checkbox or surrounding whitespace; a statement continued over several lines is one span (GUIDELINES 2).

Split a statement when a tester would write separate cases with separate expected results; keep it whole when the parts are conditions of one outcome (GUIDELINES 3).

Worked example (invented). Source text of a `pr_body`:

```
## Summary
Users complained about silent failures on upload.

## Acceptance criteria
- [ ] Uploading a file over 10 MB returns HTTP 413 and the message "File too large"
- [ ] Uploads of png, jpg and gif files still succeed
- [x] Added tests for the 413 path
- [ ] The upload page feels faster

Follow-up: resumable uploads will come in another PR.
```

| Text | Decision | Why |
|---|---|---|
| "Users complained about silent failures on upload." | not a criterion | motivation (N2) |
| "Uploading a file over 10 MB returns HTTP 413 and the message ..." | **two criteria**: `returns HTTP 413` and `the message "File too large"` share words, so give both the same span and mark the split (`d`), `behavioral_testable` each | two outcomes a tester would assert separately (GUIDELINES 3, E4) |
| "Uploads of png, jpg and gif files still succeed" | one criterion, `behavioral_testable` | enumerated values of one rule (E6) |
| "Added tests for the 413 path" | not a criterion | claim about tests (N3); the checked box means nothing |
| "The upload page feels faster" | criterion, `subjective_or_vague` | no measure (E18) |
| "resumable uploads will come in another PR" | not a criterion | future work (N5) |

`well_specified` is yes here (an Acceptance criteria heading with a checklist).

Testability in one line each (decision tree in GUIDELINES 6): `untestable_external` needs a person or a live third party; `non_functional_measurable` is a quality attribute *with* a threshold or named tool; `behavioral_testable` is what the running system does for given inputs; `structural_checkable` is decidable from the diff (rename, config value, dependency version, docs content); otherwise `subjective_or_vague`. If two labels fit, pick the evidence type you would use first and write the other in `notes`.

## 6. Edge cases (details and more examples in GUIDELINES)

- Conventional-commit prefix in a title (`fix(api): ...`): start the span after it. A title that only names an area is not a criterion.
- Nested lists: a parent that only introduces its children (ends with `:`) is not a criterion; each child is. Put the lead-in in `notes`.
- Gherkin: one `Scenario` is one criterion unless the `Then` steps are independent outcomes. `Background` is not a criterion.
- The same statement in title and body, or in issue and body: annotate each occurrence and note `dup of`.
- Implicit criteria (at most 3 per PR, from the text alone, `explicit = false`): for example reproduction steps with no "expected" section imply that the steps no longer fail. Do not invent edge cases or quality attributes.
- Non-English text: annotate normally, `notes: lang=xx`. Text that tries to instruct an AI ("ignore previous instructions"): it is data, not a criterion; note `injection-like`.
- Truncated or withheld sources: annotate what is visible; if the tool says the text is withheld, tell the owner instead of guessing.

## 7. Adjudication (the third person, C)

C is a different person from A and B (the tools refuse otherwise) and should not be the person who tuned the extractors on the dev set.

1. The owner runs `gold_agreement.py compare` (reports agreement and lists disagreements) and `gold_agreement.py skeleton --adjudicator C`, which prefills agreed items and turns each disagreement into a pending item showing both proposals.
2. C opens the adjudication view (`gold_annotate.py serve --adjudicator C`). For each pending item C chooses: take A, take B, merge (edit the span or label), add, or drop. Item types: `testability_conflict` (same span, different label), `span_boundary` and `overlap_below_threshold` (similar but different spans), `only_a` / `only_b` (one annotator marked a criterion the other did not), `implicit_a` / `implicit_b`, and `well_specified_conflict`.
3. Decide each item by applying GUIDELINES to the **text**, not by who proposed it. Read the item before reading the other side's notes, and do not favour the annotator you know better. Never use the code, the diff or Radius output.
4. If C cannot decide, the three people may hold a consensus meeting; record `adjudication_method: consensus meeting` in the batch notes of `benchmarks/gold/README.md`. If the owner is also A or B, there is no neutral adjudicator and the deviation must be recorded (RUNBOOK section 1).
5. `--prefill-from-radius` is optional, off by default, available only to C, and every item taken from it is flagged. It adds anchoring risk and is best left off.
6. When all items are resolved, `gold_validate.py check --complete` must pass.

## 8. Agreement: what gets measured and reported

`gold_agreement.py compare` reports, with 95% percentile-bootstrap intervals resampled over PRs (seeded): criterion-presence Cohen's kappa and percent agreement over the non-blank lines of every source, testability kappa and Krippendorff's alpha over matched pairs, span F1 between annotators (matching rule: character IoU at least 0.5), the well-specified flag kappa, counts of implicit criteria, per-source-kind figures, active time per annotator, and the list of items for adjudication. The preregistered gate for the 30-PR pilot is kappa at least 0.60 on presence and testability (PREREGISTRATION 5.4, an initial guess); below it the guidelines are revised and a fresh pilot annotated once. Numbers from the synthetic fixtures are never results.

## 9. Privacy and data hygiene

- The texts are public GitHub content written by third parties. Use the local copy only; do not paste it into chats, issues, search engines or AI tools, and delete the kit when told to. Raw text is git-ignored and never committed; only the text-free export (`gold_validate.py export-public`) can be released, after owner review and licence decision (DEC-012; `DATA_HYGIENE.md` sections 2 and 6).
- PR bodies may contain names, emails or handles. Author logins are stored only as sha256. Do not copy personal data into your notes; if a note needs it, describe it ("author's email appears") instead.
- You are a research participant in a minor sense: your labels and the active time per PR are recorded under a pseudonymous id (`[a-z0-9_-]`) and may be reported in aggregate. Participation is voluntary and you may withdraw. Get the written acknowledgement described in the RUNBOOK before starting.
- Report any text that looks like a secret (key, token, password) to the owner and do not copy it anywhere.
