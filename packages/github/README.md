# Radius GitHub Integration

GitHub App authentication, installation token exchange, PR comments, and Check
Run publishing for Phase 1 analysis results.


## Intent source ingestion (IN-02)

`radius_github.intent_*` fetches the pull request's intent (title, body, linked issues, commit messages, `.radius/intent.yml`) with a budgeted, read-only REST client and merges it into the analysis' intent snapshot. `radius_github.fake_api.FakeGitHub` is a stateful in-memory GitHub used by the tests (recorded-style responses in `tests/fixtures/api/`). Behavior, limits and open points: `packages/intent/README.md` (Source ingestion from GitHub) and `docs/github-app-validation/RUNBOOK.md` (section 6b).

## Verdict v2 renderer (VD-06, VD-08 partial)

`radius_github.verdict_v2` renders a `VerdictV2View` (parsed from the stored payload) to GitHub Markdown. It imports only the standard library and `radius_github`; `publisher.py` (v1) is not touched.

- `markdown.render_comment(view)`: the PR comment (hidden markers, verdict heading, summary line, `Why`, criteria table, next steps, collapsible tamper / unlinked code / per-criterion evidence / legacy v1 sections, footer). At most `MAX_COMMENT_CHARS` (60,000; GitHub allows 65,536). Over budget, optional sections are dropped in reverse priority and a notice is added; details tags always stay balanced.
- `markdown.render_check_run(view)`: `CheckRunPayload(title, summary, text, conclusion, details_url)`. `success` only for a non-pending `verified`; `failure` for `failed`; everything else `neutral` (including pending, `needs_review`, error and skipped).
- `markdown.explain_criterion(criterion, label=..., tau=...)` / `explain_all(view)`: compact, template-based text per criterion; every sentence comes from one field (state, `S`, threshold, items, flag).
- Markers: the first line is the v1 marker (`<!-- radius-confidence-report -->`) so the single PR comment is updated in place between v1 and v2 (decision D10); the second line is the distinct v2 marker `<!-- radius-verdict-v2 rev=N digest=xxxxxxxx -->`. `plan_upsert(comments, body)` returns `create` / `update` / `skip` (same content digest, revision ignored) using the same bot-only lookup as the v1 publisher.
- `escape`: all untrusted text (criterion text, test names, paths, tamper reasons and snippets, ids) goes through `code()` (inline code span), `plain()` (escaped flowing text, mentions / issue refs / URLs wrapped in code) or `token()` (restricted charset). It strips zero-width, bidi and control characters, flattens lines, caps length and entity-encodes `<`, `>`, `&`. Tests include the prompt-injection corpus (`tests/security/prompt_injection/corpus`).

Honesty: the evidence basis is always labelled "static assertion strength only (no mutation testing)", thresholds are called uncalibrated, and the v1 score is shown only inside a collapsed "legacy" section. See [`docs/verdict-v2.md`](../../docs/verdict-v2.md).
