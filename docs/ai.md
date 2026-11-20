# AI in Radius

Radius decides whether a pull request is verified by evidence. AI never takes part in that
decision. It adds three optional, advisory features on top of the deterministic result:

| Feature | Flag | What leaves the machine | What it can change |
| --- | --- | --- | --- |
| LLM intent extraction (DEC-034) | `RADIUS_INTENT_EXTRACTION_MODE=llm`, `RADIUS_LLM_INTENT_ENABLED`, `RADIUS_LLM_INTENT_ORGS` | PR title and body | Proposes criteria marked `llm_proposed`. They are capped, low weight, and block `verified` until a human confirms them. |
| Suggested tests (DEC-034) | `RADIUS_FEATURE_SUGGEST_TESTS` and the intent egress settings | Criterion text and the names of changed symbols (no code) | Shows gated pytest snippets marked "not run, not evidence". They are never executed. |
| AI merge-readiness review (DEC-041) | `RADIUS_FEATURE_AI_REVIEW` | Radius's computed evidence (file names, counts, test names, gaps), the PR title and diff excerpts | Shows an "AI review (advisory)" panel and PR-comment section. It never changes the verdict, the score or the check conclusion. |

All of these are off by default. With no API key configured, nothing is sent and Radius
behaves exactly as it does without AI.

The legacy semantic pruner (`RADIUS_FEATURE_GEMINI_PRUNER`) is not moved to the new
provider. The live pipeline does not call it, and a pruner removes callers from the blast
radius. That could make a change look safer than it is, which the governance rule forbids
(DEC-009). It stays a legacy opt-in.

## Providers

One provider-neutral layer (`radius_intent.infrastructure.llm.factory`) serves every
feature. It reads these settings:

| Variable | Meaning |
| --- | --- |
| `RADIUS_LLM_PROVIDER` | Either `anthropic` (the default, through the SDK extra `llm`) or `openai_compatible` (plain HTTP chat completions). |
| `RADIUS_LLM_BASE_URL` | Used with `openai_compatible` only. It is the base URL before `/chat/completions`. HTTPS is required; plain HTTP is accepted only for localhost. |
| `RADIUS_LLM_API_KEY` | The provider key. It is never logged. With `anthropic`, `ANTHROPIC_API_KEY` is used when this is unset. |
| `RADIUS_LLM_MODEL` | One model, or a comma-separated fallback list. A 404 (model gone), a 429 (rate limited) or an empty reply moves to the next model. |
| `RADIUS_LLM_JSON_MODE` | `json_object` (the default), `schema` (sends the feature's JSON Schema) or `off`. |
| `RADIUS_LLM_MIN_INTERVAL_S`, `RADIUS_LLM_MAX_CALLS_PER_DAY`, `RADIUS_LLM_MAX_CALLS_PER_ANALYSIS`, `RADIUS_LLM_MAX_ATTEMPTS`, `RADIUS_LLM_TIMEOUT_S`, `RADIUS_LLM_DEADLINE_S` | Pacing, daily cap, per-analysis budget, retries and timeouts. The defaults fit OpenRouter's free tier. |
| `RADIUS_LLM_REASONING_EFFORT`, `RADIUS_LLM_TEMPERATURE` | Sent only when set. |

[CONFIGURATION.md](operations/CONFIGURATION.md) lists every variable with its default.

### OpenRouter (recommended, free, no credit card)

1. Create an account at openrouter.ai and an API key. Models whose id ends in `:free` cost
   nothing.
2. Set these variables on the API and worker service (Render: Environment):

   ```text
   RADIUS_LLM_PROVIDER=openai_compatible
   RADIUS_LLM_BASE_URL=https://openrouter.ai/api/v1
   RADIUS_LLM_API_KEY=<your OpenRouter key>
   RADIUS_LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free,nvidia/nemotron-3.5-super-vl:free,google/gemma-4-31b-it:free
   RADIUS_LLM_JSON_MODE=json_object
   RADIUS_FEATURE_AI_REVIEW=true
   ```

3. Optional: turn on the other features.
   - For LLM intent extraction, set `RADIUS_INTENT_EXTRACTION_MODE=llm`,
     `RADIUS_LLM_INTENT_ENABLED=true` and `RADIUS_LLM_INTENT_ORGS=<organization id>`.
   - For suggested tests, also set `RADIUS_FEATURE_SUGGEST_TESTS=true`. It needs Verdict v2
     `shadow` or `on`.

Free models come and go, and an id that no longer exists returns 404 "no longer available".
Keep two or three models in the list and check the list from time to time. Radius sends
`X-Title: Radius` (and `X-OpenRouter-Title`) for attribution.

Limits: OpenRouter allows 20 requests a minute and 50 requests a day on `:free` models. The
daily limit rises to 1000 after buying 10 credits once. Radius's defaults stay below that:
`RADIUS_LLM_MIN_INTERVAL_S=4` (at most 15 a minute) and `RADIUS_LLM_MAX_CALLS_PER_DAY=45`.
Every HTTP request counts, including model fallbacks and the one JSON re-ask. If you buy
credits, raise `RADIUS_LLM_MAX_CALLS_PER_DAY` to about 900.

### Google Gemini (AI Studio key)

```text
RADIUS_LLM_PROVIDER=openai_compatible
RADIUS_LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
RADIUS_LLM_API_KEY=<AI Studio key>
RADIUS_LLM_MODEL=gemini-3.5-flash-lite
RADIUS_LLM_REASONING_EFFORT=low
```

- `gemini-2.5-flash` is deprecated for new users. From 2026-12-01 its requests route to
  `gemini-3.5-flash-lite`.
- Gemini documents structured output through `json_schema`, so `RADIUS_LLM_JSON_MODE=schema`
  also works.
- Free-tier rate limits are per project. AI Studio shows them under "Rate limit".
- Google may disable a key it finds published (for example, in a public repository). Keep
  the key in the host's secret store only.

### Groq

```text
RADIUS_LLM_PROVIDER=openai_compatible
RADIUS_LLM_BASE_URL=https://api.groq.com/openai/v1
RADIUS_LLM_API_KEY=<Groq key>
RADIUS_LLM_MODEL=openai/gpt-oss-20b
```

- JSON object mode works on all models.
- The developer-plan base limits for `openai/gpt-oss-20b` are 30 requests a minute and 1K a
  day, but only 8K tokens a minute. Keep `RADIUS_AI_REVIEW_MAX_DIFF_CHARS` at 12000 or
  lower.

### GitHub Models (retired)

GitHub's documentation states that GitHub Models was retired on 2026-07-30, including its
inference API at `https://models.github.ai/inference`. The OpenAI-compatible adapter would
still speak its protocol, with a PAT that has `models:read`, if an equivalent endpoint
returns. Do not configure it today.

### Anthropic

```text
RADIUS_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=<key>
```

Install the `llm` extra. This provider is paid.

## How a call is guarded

- **Timeouts.**
  - Every HTTP request has a connect timeout (5 s) and a total budget per call
    (`RADIUS_LLM_TIMEOUT_S`).
  - Each feature has a wall-clock deadline per analysis (`RADIUS_LLM_DEADLINE_S`; for the
    review, `RADIUS_AI_REVIEW_TIMEOUT_S`).
  - The review also runs in a daemon thread joined with a hard timeout, so a hung provider
    cannot hold the job on the 0.1-CPU worker.
- **Retries.** Timeouts, 429 and 5xx are retried with exponential backoff (2 s, 4 s and so
  on) or the provider's `Retry-After`. A wait longer than 20 s, or one that would pass the
  deadline, ends the attempt.
- **Budgets.**
  - A per-analysis call budget applies to each feature.
  - Pacing and a rolling 24-hour cap apply to each process. They are kept in memory, so a
    restart resets them.
- **Size caps.**
  - The review sends at most `RADIUS_AI_REVIEW_MAX_DIFF_CHARS` (12000) characters of diff.
    The largest changed files go first, each file gets at most a quarter of the budget, and
    lock files and binaries are skipped.
  - Evidence is capped at 14000 characters and the title at 300.
- **Structured output.** `response_format` is sent. If the provider rejects it, the request
  is retried once without it. A reply that does not parse as JSON is asked again once, with
  a stricter instruction. Each feature then validates the reply against its own strict
  schema, and anything else is discarded.
- **Fallback.** Any failure (no key, rate limit, timeout, invalid output) leaves the
  deterministic result as it is. For the review, the stored status is `unavailable` with a
  reason code.
- **No secrets in logs.** Logs carry only status codes, reason codes and model ids. They
  never carry prompts, replies, keys or response bodies.

## The AI review and prompt injection

The PR author is the adversary (DEC-030). The title, diff and file names are author
controlled. The review is defended in layers:

1. **Data, not instructions.**
   - Every input is sanitised (hidden characters and secrets are stripped, injection
     phrases are flagged).
   - Every input is wrapped in nonce-delimited data blocks by `radius_shared.llm_guard`.
   - The system prompt says that text in the blocks is data and must never be followed.
     Flagged phrases are reported in the review ("treated as data").
2. **Grounded output.** The reply must match a fixed schema. Every cited file must be one
   Radius computed for this analysis (changed files, selected tests). Risks and tests
   without a valid citation are dropped.
3. **No verdict.**
   - Text that claims a verdict or approval (`verified`, `safe to merge`, `LGTM`, ...) is
     dropped. So is text with links, markup, `@mentions`, commands, secrets, the prompt
     nonce or system-prompt fragments.
   - A summary that does any of this rejects the whole review.
4. **Order of operations.**
   - The verdict, score and check conclusion are computed and committed before the review
     runs.
   - The review is stored in its own table, `analysis_ai_reviews`, which no verdict code
     reads.
   - The PR-comment section is appended to the comment only, never to the Check Run.
5. **Rendering.**
   - The dashboard renders review text as plain text nodes.
   - The PR comment escapes Markdown and writes `<`, `>` and `@` as HTML entities (no tags,
     no mention notifications).

## Privacy

- Turning on an AI feature sends data to the provider you configure. For the review, that
  is diff excerpts, file names, test names and the PR title.
- Free tiers may use your prompts to train or improve their models. Google states this for
  the Gemini free tier, and OpenRouter's free models are served by third parties under
  their own terms.
- Do not enable AI on private code you may not share with that provider.
- **No-AI mode** is the default. Leave `RADIUS_LLM_API_KEY` (and `ANTHROPIC_API_KEY`) unset,
  or keep every AI flag off. Radius then sends nothing and stores no review.

## Where it lives

- **Provider layer:** `packages/intent/src/radius_intent/infrastructure/llm/` (`factory.py`,
  `openai_compatible.py`, `guarded.py`).
- **Review contract and storage:** `packages/shared/src/radius_shared/ai_review.py`. The
  table is `analysis_ai_reviews` (migration `20261120_0025`).
- **Generation:** `apps/worker/src/radius_worker/ai_review.py`.
- **API:** `GET /api/v1/analyses/{analysis_id}/ai-review`.
- **Dashboard:** `apps/dashboard/components/ai-review-panel.tsx`.
- **PR comment:** `packages/github/src/radius_github/ai_review_markdown.py`.
