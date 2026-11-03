# Response to code review C: checkout findings C-03, C-06, C-07, C-08

Source: `docs/review/CODE_REVIEW_C_PLATFORM.md`. Built on `fix/security-review-a` (A-01/A-02 already in).
Each finding was re-checked against that branch first. Design: DEC-038.

Commit (branch `fix/checkout-isolation-c`, local only): `9400ea7`
`fix(worker): per-analysis git worktrees, repo lock, git timeouts, cache upkeep (C-03,C-06,C-07,C-08)`.

| ID | Status | What changed | Tests |
| --- | --- | --- | --- |
| C-03 | FIXED | Per-repository directory is now an object cache (`--no-checkout`); clone/fetch/PR-ref fetch/worktree creation run under an exclusive file lock (`repo_lock.py`, timeout, kernel-released on crash). Each analysis uses `LocalGitRepositoryClient.analysis_worktree()` (`git worktree add --detach`) under `REPOSITORY_CACHE_DIR/.worktrees`, removed by an `ExitStack` in `_run_claimed_job`; that path is `ExecuteAnalysisCommand.repository_path` for the whole pipeline. | `packages/repository/tests/test_checkout_isolation.py` (three concurrent threads on three SHAs each read their own tree, removal on failure, lock across two processes, lock of a killed process recovered); `apps/worker/tests/test_runner.py` (two open analyses of one repo, cleanup on error, full run through worktrees) |
| C-06 | FIXED | `GitTimeouts` (clone 300 s, others 120 s, lock wait 300 s; clamped); child in its own process group/session, killed on expiry (`killpg` on POSIX, `taskkill /T` on Windows); `GitTimeoutError` (`retryable = True`); half-written clone removed. `_origin_remote_url` has a 30 s limit. Settings `RADIUS_GIT_CLONE_TIMEOUT_SECONDS`, `RADIUS_GIT_TIMEOUT_SECONDS`, `RADIUS_GIT_LOCK_TIMEOUT_SECONDS`. | fake slow git whose grandchild must die (`test_slow_git_is_killed_with_its_children...`), clone vs command limit, clamping, lock wait timeout |
| C-07 | FIXED (age-based only) | Stale `index.lock`/`shallow.lock` removed only when older than `RADIUS_GIT_STALE_LOCK_SECONDS` (900 s) and while holding the repo lock; `git worktree prune` and `git gc --auto` per cache; orphan worktree dirs removed; opt-in idle cache deletion (`RADIUS_GIT_CACHE_MAX_IDLE_DAYS`, else `RADIUS_RETENTION_DAYS`) skipping locked caches and caches with live worktrees; hourly via `SqlAlchemyWorkerRuntime.run_cache_maintenance`. `checkout` is now `--detach --force`; analyses use fresh worktrees so a dirty tree cannot wedge them. Not done: size cap / per-organization quota. | forced checkout over a dirty tree, old vs fresh index.lock, prune idle/busy/in-use, orphan worktrees, worker maintenance wiring |
| C-08 | FIXED-BY-A (A-02: dot-only segments neutralised, per-organization path); additionally worktree paths are resolved and asserted inside their root (`_inside`) | regression test added: owner/name `..`, `.`, `../..`, `...`, empty stay inside the cache dir | `test_repository_cache_path_cannot_leave_the_cache_directory`, `test_worktree_paths_cannot_leave_their_root` |

Interface changes: `LocalGitRepositoryClient(policy, timeouts=None)`; new `add_worktree`, `remove_worktree`,
`analysis_worktree`, `maintain_cache`; `load_persisted_analysis_command(..., cleanup=ExitStack | None)` (without
`cleanup`, or with a client lacking `analysis_worktree`, the legacy shared checkout is used); `_run` now goes
through module function `local_git._exec` (three existing tests patched it instead of `subprocess.run`).

Not verified: lock and worktree behavior on Linux (only run on Windows); real git hosting (tests use local
repositories; clones from GitHub were not exercised); NFS or other filesystems with weak locking; the
`taskkill`/`killpg` paths on the platform they were not run on.
