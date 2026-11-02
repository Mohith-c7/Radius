# Prompt injection: threat model, controls and test suite (QS-02)

Scope: every Radius feature that sends repository or PR content to an LLM (first consumers: IN-02 criteria extraction, IN-04 guarded extraction, any pruner or classifier). Binding rules come from DEC-009 ("LLM proposes, evidence disposes"), DEC-015 (LLM opt-in, no egress by default) and the security checklist in `docs/research/IMPLEMENTATION_PLAN.md` section 6. A QS-01 threat model should cross-reference this document for the "LLM inputs" entry point (QS-01 is not written yet).

## Threat model for LLM inputs

Untrusted: PR title and body, issue text, commit messages, code comments, file and test names, README, `.radius/intent.yml` values, tool and test output, agent trajectories. Anyone who can open a PR controls all of these.

Attacker goals, in priority order:

1. Change a verdict (mark a PR verified, fake `RADIUS: PASS`, set confidence).
2. Exfiltrate secrets (environment, tokens, the system prompt, other tenants' data).
3. Make the system act (fetch URLs, run commands, call tools).
4. Degrade service (huge inputs, pathological regex or JSON).
5. Hide content from reviewers (zero-width, bidi, HTML comments, ANSI).

Assumption used throughout: **the model is compromised**. It may obey any text it reads. Safety must come from structure and validation outside the model.

## Controls (`radius_shared.llm_guard`)

| Control | Where | What it guarantees |
|---|---|---|
| Sanitiser | `sanitize_untrusted` | Deterministic removal of null bytes, ANSI/OSC escapes, zero-width, bidi, Unicode tag characters, control characters and HTML comments (including unterminated); masks known secrets (exact values) and key=value credentials via `redaction.py`; truncates over-length text with a marker; returns findings. Advisory heuristics (`injection_phrase`, `role_spoof`, `verdict_string`, `exfil_request`, `tool_lure`, `delimiter_lookalike`, `encoded_instruction`) flag but never alter text and are never relied on for safety. |
| `UntrustedText` | `sanitize.py` | Only sealed sanitiser output is accepted by the prompt builder; `str()` does not return the text so it cannot be f-string-ed into instructions by accident. |
| Prompt builder | `build_prompt` | Untrusted text appears only inside `<<<RADIUS_DATA_<nonce> ...>>>` blocks in the user message; the system message holds fixed rules plus trusted task text. The nonce is caller-supplied (`new_nonce()` gives 128 bits), checked for collisions case-insensitively, and never derived from untrusted text. Untrusted text found in the instruction position raises. |
| Output validator | `validate_criteria_output` | Output must be a single strict JSON document with exactly `{"criteria":[{source_id, quote, start, end, text}]}`. `quote` must equal `source.text[start:end]`. Any verdict-like key anywhere (`verdict`, `status`, `score`, `confidence`, `tool_calls`, ...) is rejected. `text` may not contain URLs/markup, command-like strings, fake verdict strings, control characters, secrets (plain, base64, hex, ROT13, reversed), the nonce, or system-prompt fragments. Size, count and depth are capped. Nothing is fetched or executed. |
| Fail closed | feature code | Any `OutputRejected` or `NonceCollision` means: use the deterministic result, discard the model output. |
| Verdict isolation | architecture | Verdict logic consumes evidence only. `Criterion` has no verdict fields, and the suite asserts `FeatureOutcome.verdict_inputs` stays empty. |

Operational rules for features (not enforced by this module): LLM use is opt-in per org, no tools or function-calling are given to the model, temperature 0, redact before egress, log calls to `llm_call_log`, never log full prompts containing customer code at INFO.

## The suite

Location: `tests/security/prompt_injection/` (marker `prompt_injection`, runs in the normal `python -m pytest tests -q` step, about 15 seconds, no services, no network, no API keys).

- `corpus/corpus_v1.jsonl`: versioned attack corpus (98 cases, 14 categories, 14 benign controls). One JSON object per line: `id`, `category`, `where` (which input kind carries the payload), `payload` (or `payload_repeat` for oversize cases), `expected` (`guard`: `sanitized` | `rejected_output` | `pass_through` | `nonce_collision`; `findings`; `forbid_findings`; `rejection_code`; `naive_obeys`). Placeholders `{{NONCE}}`, `{{NONCE_LOWER}}`, `{{FAKE_SECRET}}`, `{{FAKE_SECRET2}}` expand at load time, so no secret value is committed.
- `pi_harness/`: `LlmFeatureUnderTest` protocol, `FeatureOutcome`, planted fake environment (values built by concatenation at runtime), corpus loader, `check_outcome` invariants, stub models, and two reference features.
- Stub models: `WellBehavedModel` (quotes requirement-looking lines, ignores the rest) and `NaiveCompliantModel` (obeys instructions found in the data, including base64/ROT13-encoded ones, and will print the planted secrets or system prompt). The naive model is the worst case; passing against it shows protection does not rely on model manners.
- Reference features: `GuardedCriteriaFeature` (correct wiring, must pass everything) and `NaiveCriteriaFeature` (string concatenation, trusts output; must be caught).

Invariants checked on every case (`check_outcome`): no planted secret (plain or encoded) in any prompt or emitted result; untrusted text only inside data blocks and block structure exactly as supplied; nonce absent from sources; nothing from the LLM path reaches verdict logic; the emitted result itself passes the strict validator. Plus per-case sanitiser findings, expected rejection codes against the naive model, determinism across runs, and unit tests for the nonce, builder refusals, validator rejections and caps.

Run: `PYTHONPATH=<as in ci.yml> python -m pytest tests/security/prompt_injection -q` or `-m prompt_injection`.

### Registering a feature (IN-04 and others)

1. Write an adapter implementing `LlmFeatureUnderTest` (`name`, `run(inputs, *, model, nonce, secrets) -> FeatureOutcome`) that drives your real code with the provided stub `model` (never a network client). Fill `prompts` (system, user, nonce), `emitted` (what goes downstream), `rejection_code`, `verdict_inputs` (must be empty), and `sources`.
2. Add a factory to `REGISTERED_FEATURES` in `tests/security/prompt_injection/pi_registry.py`.
3. Run the suite. `test_registered_feature_contract` runs every corpus case against your feature with both stub models and fails on any violated invariant.

### Adding cases

Add a row to the corpus (keep ids stable, bump `corpus_version` in the `_meta` line when semantics change). Every discovered bypass must get a case before the fix lands (QS-02 acceptance). Payloads must be defensive test data: instruction-override strings, delimiter breakouts, hidden characters, `.invalid` hosts. Never include working exploits or real hosts, keys or tokens. If a case needs a secret, use a placeholder and the planted environment.

## What the suite does NOT prove

- It does not test any real model. Stubs show the guard holds against an obedient model, not that a given provider resists injection. Prompt quality remains unmeasured here (see EP-12).
- Heuristic findings are advisory and incomplete: homoglyph attacks (Cyrillic look-alikes), hex or custom encodings, and other languages beyond the five covered are not detected (cases PI-ML-06 and PI-EN-04 document this). Structural controls still apply to them.
- The sanitiser has a known false positive: ZWJ emoji sequences lose their joiners (PI-HU-09).
- The validator cannot judge semantic correctness of a criterion; a malicious but verbatim-quoted, URL-free, schema-valid proposal is accepted. It is bounded because criteria are proposals checked against evidence, never verdicts.
- It does not cover semantic poisoning of verdict inputs outside the LLM path, multi-turn or tool-using agents, image/PDF inputs, or provider-side data retention. Features that add tools or multi-step agents need new invariants before registering.
- Secret detection is limited to known values (planted or from sensitive-named env vars) plus the patterns in `redaction.py`.
- The suite runs inside the normal CI test step; no separate required check or results tracking dashboard exists yet.
