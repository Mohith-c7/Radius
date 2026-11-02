# Instructions for AI coding agents

Humans and agents follow the same rules. The binding text is `docs/research/IMPLEMENTATION_PLAN.md` section 1 (read 1.1 to 1.5 before starting) and [CONTRIBUTING.md](CONTRIBUTING.md). Key points:

- Read `docs/AI_CONTEXT.md` and `docs/DEVELOPMENT_GUIDE.md` first. Do not invent facts about repo state; run commands and read files.
- Branch from the latest `origin/develop`; never commit to `dev` or `main`; never push throwaway commits.
- Conventional commits; one task, one branch, one PR; keep it near 600 changed lines or fewer.
- Do not weaken, skip or delete tests to get green. Do not expand scope; note follow-ups instead.
- Never put secrets, tokens, customer code or personal data in code, fixtures, logs or PR text.
- When a task says a decision is needed, stop and ask the owner.
- Record the commands you ran and their results in the PR description, and disclose AI assistance (see CONTRIBUTING, "AI-assisted contributions").
