# Execution isolation (audit A#4 / roadmap P0-5)

Pull-request tests are code written by the PR author. The worker that would run
them holds `DATABASE_URL` (read/write on every tenant's data) and the GitHub App
private key (it can mint installation tokens for every installed org). The rule
from roadmap §E, "Component boundaries", is: **the worker never runs repository
code where its credentials are reachable.**

## Execution modes

`WORKER_TEST_EXECUTION_MODE` (resolved in `apps/worker/src/radius_worker/execution_mode.py`):

| Mode | Runner | When to use |
| --- | --- | --- |
| `disabled` (**default**) | `DisabledTestRunner`: executes nothing and returns `error` if it is ever called | Recommended. Tests run in customer CI and results are ingested (`docs/CI_INTEGRATION_GUIDE.md`). Verdicts read `insufficient_evidence` until results arrive |
| `sandbox` | `ContainerSandboxRunner`: one ephemeral docker/podman container per command | In-worker execution with a container boundary |
| `unsafe_in_process` | `SubprocessTestRunner`: child process of the worker | Local development only. **Refused** when `RADIUS_ENV` is `uat` or `production` unless `RADIUS_ALLOW_UNSAFE_EXECUTION=true`; the worker fails at startup. Every resolution logs a `SECURITY WARNING` |

Backward compatibility: if `WORKER_TEST_EXECUTION_MODE` is unset, `WORKER_EXECUTE_TESTS=true`
maps to `unsafe_in_process` and logs a `DEPRECATED` warning. An explicit mode overrides
the legacy flag. Invalid values are rejected.

Sandbox settings: `WORKER_SANDBOX_RUNTIME` (`docker`/`podman`), `WORKER_SANDBOX_IMAGE`,
`WORKER_SANDBOX_MEMORY`, `WORKER_SANDBOX_CPUS`, `WORKER_SANDBOX_PIDS_LIMIT`,
`WORKER_SANDBOX_TMPFS_SIZE`, and `WORKER_TEST_TIMEOUT_SECONDS`. The image must be pulled
in advance (`--pull never`) and must already contain the test toolchain and the
project's dependencies, because the container has no network.

## Findings: what the in-process path exposes

Investigated on 2026-11-01 (Linux, worker running as uid 0 in the dev container).

1. **Environment.** `SubprocessTestRunner` passes only an allowlist (`PATH`, `HOME`,
   `PYTHONPATH`, `LANG`, `TEMP`/`TMP`, Windows vars). The child's own `os.environ`
   does not contain `DATABASE_URL`. **Tested.**
2. **`/proc/<ppid>/environ`.** The child runs as the worker's uid, so it can read the
   worker's original environment, secrets included. Reproduced: a child launched by
   `SubprocessTestRunner` with a stripped env read `DATABASE_URL` from
   `/proc/{getppid()}/environ`. Settings loaded from `.env` are not in environ, but they
   sit in worker memory (`/proc/<ppid>/mem` and ptrace, same uid) and in the `.env`
   file itself on disk. **Env stripping is not a boundary.**
3. **Network.** The child shares the worker's network namespace: it can reach Postgres,
   the GitHub API, cloud metadata endpoints, and the internet.
4. **Filesystem.** The child can read and write anything the worker uid can: `.env`,
   the whole `REPOSITORY_CACHE_DIR` including **other tenants' checkouts**, and
   `.git/config` of cached clones.
5. **Repository cache.** cwd is the shared cache checkout, reused across analyses. A
   malicious PR can plant files (e.g. a `conftest.py` outside the diff, or git hooks)
   that affect later analyses of the same or other PRs.
6. **Resources.** The only limit is a wall-clock timeout. `subprocess.run` kills the
   direct child on timeout, but grandchildren (forked or daemonised) survive. There is
   no memory or PID limit (fork bombs, OOM-killing the worker).
7. **Library defaults.** `Phase1AnalysisOrchestrator.__init__` defaults to
   `execute_tests=True`, and `create_local_orchestrator()` wires `SubprocessTestRunner`.
   Only tests and `benchmarks/` use these, on Radius-authored fixture repos. The
   production entry point (`run_worker` → `_create_sql_orchestrator`) resolves the mode
   from settings and defaults to `disabled`. Follow-up: flip the constructor default
   once the benchmark harness passes it explicitly.

## Threat model

| Asset | Exposure in `unsafe_in_process` | Control in `sandbox` | Status |
| --- | --- | --- | --- |
| `DATABASE_URL`, `GITHUB_APP_PRIVATE_KEY` in the child env | Stripped by the allowlist | Container env is only the fixed `SANDBOX_ENV` (`KEY=VALUE`; host env is never forwarded). The runtime CLI process also gets only `PATH`/`DOCKER_HOST`/`CONTAINER_HOST`/`XDG_RUNTIME_DIR`/`HOME` | implemented; tested (unit: argv and launcher env contain no fake secrets; real docker: probe sees no `DATABASE_URL`) |
| Worker secrets via `/proc/<ppid>/environ` and memory | **Exposed** (same uid) | Separate PID namespace and uid 65534; the parent is the container init, not the worker | implemented; leak **tested** (`test_unsafe_runner_isolation.py`); real-docker probe confirms no leak |
| Network egress (DB, GitHub, metadata, internet) | **Exposed** | `--network none` | implemented; flag tested. Real-docker egress probe passes, but it is **inconclusive**: the unsandboxed control could not reach 1.1.1.1 on this host either |
| Host filesystem, `.env`, other tenants' checkouts | **Exposed** | Only two bind mounts: a read-only snapshot and a per-command results dir. `--read-only` rootfs, `tmpfs` `/tmp` (nosuid,nodev, size-capped) | implemented; tested (real docker: writes to `/workspace` and `/` fail; control without flags succeeds) |
| Repository cache integrity | **Exposed** (cwd is the cache) | Each run copies the checkout to a fresh temp dir (`.git` excluded; symlinks copied as links, never followed), mounts it read-only, and removes it in `finally` | implemented; tested (cache unchanged, `.git` absent, symlink not followed, temp dir removed even if the launcher raises) |
| Clone credentials in `.git` | Readable | `.git` not copied into the snapshot | implemented; tested |
| Privilege escalation in the container | n/a | `--user 65534:65534`, `--cap-drop ALL`, `--security-opt no-new-privileges`, `--ipc none`, no `--privileged` | implemented; tested (argv; real docker uid == 65534) |
| CPU / memory / fork bomb | Timeout only | `--pids-limit`, `--memory` (= `--memory-swap`), `--cpus` | implemented; flags tested. Limits **not** exercised against a real fork bomb or OOM |
| Runaway / hung tests | Direct child killed; grandchildren may survive | Wall-clock timeout, then `<runtime> kill`, then `rm -f`, which takes the whole container | implemented; tested (fake launcher: kill before rm; real docker: no `radius-sbx-*` container left) |
| Image supply chain at analysis time | n/a | `--pull never`; image reference validated | implemented; argv tested |
| Result integrity | Errors give `error`, never `passed` | Same shared helpers (`pytest_outcome`, `exit_code_outcome`, `build_run_result`). Missing runtime and runtime exit codes 125/126/127 give `error`. JUnit must be a regular file (no symlink) of 20 MB or less | implemented; tested |
| Argument injection into the runtime | n/a | Untrusted command placed after the image; container name validated; argv list, no shell | implemented; tested |
| Kernel escape from the container | n/a | **Not covered.** A container shares the host kernel | not implemented: use gVisor (`runsc`) or a microVM for hostile multi-tenant workloads |
| Docker socket = root on the host | n/a | The worker needs runtime access, and the docker socket is root-equivalent: anyone who compromises the worker owns the host | operational: prefer rootless podman or a dedicated runner host/K8s Job; not implemented |

## Verification

* `packages/testing/tests/test_sandbox_runner.py`: pure argv construction (every
  isolation flag, no host secrets, command after image, config validation); the runner
  with an injected fake launcher (missing runtime, launch failure, timeout → kill and rm,
  runtime exit codes, missing JUnit, snapshot and cleanup); and **three real-docker
  integration tests** (adversarial probe, pytest with JUnit counts, timeout kill with no
  leftover container). The integration tests skip when docker or the image
  `RADIUS_SANDBOX_TEST_IMAGE` (default `radius-sandbox-test:latest` = `python:3.12-slim`
  plus `pytest`) is unavailable, so in most CI they **skip silently**.
* `packages/testing/tests/test_unsafe_runner_isolation.py`: proves the `/proc` leak of
  the in-process path (Linux only).
* `apps/worker/tests/test_execution_mode.py`: defaults are disabled, legacy flag mapping
  and warnings, refusal in uat/production (including at worker startup, before any DB
  engine exists), the explicit override, and sandbox wiring.

Real-runtime runs used docker 29.9.2 (cgroup v1, overlayfs, runc, running as root) in
the development container. Untested: podman, rootless docker, gVisor, cgroup v2, actual
memory/pids-limit enforcement, and egress blocking against a host that has egress.
