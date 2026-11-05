# EP-01 Literature Review: Method and How to Extend

**Task:** EP-01 (Milestone M1). **Date of search and access:** 2026-11-02 (all "accessed" dates are this day unless stated).
**Goal:** confirm or narrow the novelty claim of "intent-to-evidence verification of AI-generated pull requests" and keep a dated, artifact-aware map of related work.

## Files

| File | Content |
|---|---|
| `related-work.md` | Table of related work by theme (a) to (i), with year, venue/id, artifacts + license, evidence provided, difference from Radius, novelty threat |
| `novelty-assessment.md` | The five claims of `EVALUATION_PLAN.md` section 1: what exists, what is new, how to narrow, baselines to add to EP-06 |
| `reading-list.md` | Prioritized must-read list (<= 25) |
| `references.bib` | BibTeX, verified entries only (each entry carries a `note` with its verification level) |

## Method

**Sources used.** Web search (WebSearch, US-only index) and page fetches (WebFetch) of: arXiv abstract/HTML pages, ICSE/MSR/ICML/NeurIPS conference program pages, PMLR/ICLR/NeurIPS proceedings pages, GitHub repository pages, PyPI project pages, vendor blog posts. No Google Scholar, Semantic Scholar, DBLP or Scopus API was available; no institutional access.

**Search queries (themes and representative strings).**
- (a) `traceability link recovery issue to code LLM`, `Antoniol Recovering traceability links between code and documentation`, `Traceability Transformed BERT`, `acceptance criteria verification pull request LLM`.
- (b) `Coverage is not strongly correlated with test suite effectiveness`, `Are mutants a valid substitute for real faults`, `pseudo-tested methods`, `Mutation-Guided LLM-based Test Generation at Meta`, `EvalPlus`, `test smells detection`, `mutation testing of AI-agent-generated pull requests`.
- (c) `UTBoost`, `PatchDiff SWE-bench`, `SWE-ABS`, `SWE-Bench+`, `patch overfitting automated program repair`, `verifier for SWE-bench patches`, `ImpossibleBench`, `SWT-Bench`.
- (d) `AgentProof`, `Verik`, `SlopGate`, `TestSprite`, `AI code review benchmark`, `AIDev dataset`, `PR-Agent`, `CodeRabbit`, `Mutahunter`.
- (e) `Conformal Risk Control`, `On Calibration of Modern Neural Networks`, `Platt scaling`, `Predicting Good Probabilities`, `Learn then Test`, `selective classification`, `conformal prediction software engineering`, `conformal risk control coding agent patch`.
- (f) `trajectory analysis SWE-agent failure`, `AgentLens`, `process mining LLM agent conformance checking`.
- (g) `just-in-time defect prediction`, `JITLine`, `code review prioritization`.
- (h) `LLM-as-a-judge code failure modes`, `Judging LLM-as-a-Judge`.
- (i) `prompt injection AI code review pull request`, `indirect prompt injection`, `AgentDojo`.

**Date range.** 2002 to 2026-11-02 (foundational traceability and testing work, then emphasis on 2023-2026 for LLM agents).

**Inclusion.** (1) Peer-reviewed or arXiv works directly on one of themes (a)-(i); (2) tools/benchmarks that a reviewer could name as a baseline or competitor; (3) works that supply datasets or labels usable in EP-03; (4) for tools, only those whose repository, package or vendor page was fetched.
**Exclusion.** Vendor marketing used as evidence of effectiveness (only used to record that the product exists and what it claims); blog posts without author or date; works whose bibliographic record could not be located; works not read beyond a title in a search result (these are listed under "Located but not verified" in `related-work.md` and are NOT in `references.bib` and NOT used in claims).

## Verification levels (used in every file)

| Tag | Meaning |
|---|---|
| **P** | Primary record fetched this session (arXiv abstract page, conference program page, proceedings page, repository or PyPI page). Title, authors, date and venue were read there. Numbers quoted from the abstract/page are marked as such. |
| **S** | Bibliographic record located in search results from at least one reputable index (publisher/DOI listing, proceedings or author-hosted PDF, bibtex index) but the primary page was not fetched. Only the venue/year/DOI and abstract-level statements shown in the results are used; no result numbers are quoted from S works. Paywalled originals (ACM DL, IEEE Xplore) were not opened. |
| **UNVERIFIED** | Anything not meeting P or S. Never used in a claim. |

**Rule applied to numbers.** A number is quoted only if it was read on a P-level page (usually the arXiv abstract or the paper's HTML intro). Search-engine summaries of numbers were not trusted; where a summary and the primary page disagreed, the primary page is used and the discrepancy is noted.

## Known limitations

- Search is US-only and snippet-driven; recall is not systematic (no snowballing over full reference lists, no DBLP crawl). The novelty assessment says "we did not find", never "does not exist".
- Fast-moving area: many 2026 items are arXiv preprints without peer review. Re-run the queries before submission (see `EVALUATION_PLAN.md` section 7).
- Repository facts (license, stars) are snapshots of 2026-11-02; stars and "last commit" dates were often not visible on the fetched page.
- Several tools share generic names (notably "AgentProof"); see the disambiguation in `related-work.md` section (d).
- Not accessed: ACM Digital Library, IEEE Xplore and Springer full texts (listed in the final report). Classic papers cited from S-level records were not re-read.

## How to extend

1. Add the work to the correct theme table in `related-work.md`. Fetch its primary page; fill all columns; set the tag P or S. If you cannot fetch it, put it under "Located but not verified".
2. Add a BibTeX entry to `references.bib` only for P/S works; copy fields only from what you read; keep the `note` field (`verification = {P|S}; accessed = {YYYY-MM-DD}`). Do not guess authors' first names, pages or DOIs.
3. If the work affects a claim, update `novelty-assessment.md` and the threat column.
4. If it should be read first, update `reading-list.md` (keep <= 25).
5. Before paper submission: re-run the search queries above, check each tool's repository for changes (competitors move fast), and re-verify numbers in `EVALUATION_PLAN.md`.
6. Add a line to the changelog at the end of `EVALUATION_PLAN.md` for any correction to a plan fact.

## Changelog

- 2026-11-02: initial review (EP-01).
