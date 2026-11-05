# Changelog fragments

Every pull request that changes behaviour adds one small Markdown file here instead of editing `CHANGELOG.md` directly. Fragments avoid merge conflicts in the changelog, and the release step (see [docs/RELEASING.md](../docs/RELEASING.md)) folds them into the next version section.

## When a fragment is needed

The `Conventional Commits` check requires a fragment when the pull request title type is `feat`, `fix` or `perf`, or is marked breaking with `!`. Add the `no-changelog` label to skip it (for example a `fix` that only touches tests). Other types (`docs`, `test`, `ci`, `chore`, `build`, `refactor`, `style`) do not need one.

## File name

`<pull request number>.<category>.md`, for example `123.fixed.md`. If you do not have the number yet, use a short slug, for example `intent-api.added.md`.

Categories follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/): `added`, `changed`, `deprecated`, `removed`, `fixed`, `security`.

## Content

One to three sentences in plain language for a user or operator, not a commit message. Say what changed and, if it needs action, what to do. Do not claim more than the change does.

Illustrative example (not a real change):

```markdown
Worker jobs that fail three times are now marked `failed` instead of being retried forever. Set `WORKER_JOB_MAX_ATTEMPTS` to change the limit.
```

This directory is ignored by the checker apart from the rule above; only files ending in `.md` other than this README count.
