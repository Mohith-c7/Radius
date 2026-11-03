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
`WORKER_SANDBOX_TMPFS_SIZE`, `WORKER_SANDBOX_NOFILE_LIMIT` (default 1024),
`WORKER_SANDBOX_MAX_FILE_SIZE_BYTES` (default 64 MiB, `ulimit fsize`),
`WORKER_SANDBOX_MAX_OUTPUT_BYTES` (default 5 MiB host-side stream cap),
`WORKER_SANDBOX_SECCOMP_PROFILE` (optional path; unset keeps the runtime default
profile, `unconfined` is rejected) and `WORKER_TEST_TIMEOUT_SECONDS`. Defaults and
placeholders are in `.env.example`. The image must be pulled
in advance (`--pull never`) and must already contain the test toolchain and the
project's dependencies, because the container has no network.

### Fail-closed behaviour (F-07)

`WORKER_EXECUTE_TESTS` / `WORKER_TEST_EXECUTION_MODE` stay opt-in (default `disabled`).
In `sandbox` mode the sandbox must prove itself usable, otherwise nothing executes:

* **At worker startup** (`require_sandbox_ready`): invalid limits, `unconfined` or empty
  seccomp, a missing runtime binary, an unreachable daemon (`<runtime> version`), a
  missing local image (`<runtime> image inspect`) or a missing seccomp profile file make
  the worker refuse to start (`SandboxMisconfiguredError`). It never falls back to
  another mode.
* **Before every run** (`ContainerSandboxRunner.check_ready`): the same checks; on
  failure the run returns `error` with "sandbox unavailable, refusing to execute" and no
  container is started, so a later outage cannot degrade into execution.
* Classification of contained attacks: wall-clock timeout, output flood and runtime
  failures give `error`; a process killed by SIGKILL/SIGXCPU/SIGXFSZ (exit 137/152/153,
  for example an OOM kill) gives `error`. Nothing a resource attack does can yield
  `passed`.

Additional hardening in this change: `--ulimit nofile/fsize/core`, optional custom
seccomp profile (default profile stays on), and a host-side watchdog that kills the
container when captured stdout/stderr exceed `WORKER_SANDBOX_MAX_OUTPUT_BYTES`.

Tests: `apps/worker/tests/test_execution_mode.py` (startup refusal, invalid limits,
daemon/image unavailable, runtime vanishing after build, configurability) and
`packages/testing/tests/test_sandbox_runner.py` (readiness, signal exit codes, output
flood, ulimit and seccomp flags).

## Mutation evidence runs mutants only in the sandbox (DEC-035, stage 2: DEC-036)

Stage 2 (`RADIUS_MUTATION_STAGE2`, default off) adds no execution path: it calls the same `MutantRunner` as stage 1, so in the worker every stage 2 run is a `SandboxMutantRunner` container run on a fresh copy of the checkout. It discovers the wider test files with a static `ast` scan on the worker (nothing of the repository is imported or run there), validates every test id before it can reach the pytest command line, and its extra runs are bounded by their own wall clock and test cap. The worker still never builds `SubprocessLocalRunner` (tested with stage 2 on). Stage 2 has not been exercised against a real container.

`RADIUS_FEATURE_MUTATION` (default off) makes the Verdict v2 Stage A `mutation` producer
run many **generated variants** of the pull request's own code. A mutant is as untrusted as the
code it came from, and it is executed together with the PR's tests, so the same rule applies:

* Only `SandboxMutantRunner` (an adapter over `ContainerSandboxRunner`) is used in the worker.
  Every run is one throw-away container with the F-07 limits: `--network none`, read-only root,
  `--cap-drop ALL`, `no-new-privileges`, nobody uid, pids/memory/cpu/ulimit caps, `--pull never`,
  a fixed environment allowlist, output watchdog and wall-clock kill. The producer builds the
  runner without F-11 failure reruns (a failing mutant is a kill).
* The mutant is written into a **fresh copy** of the checkout (`.git` excluded, symlinks kept as
  links, path-escape checked); the checkout the worker holds is never modified, and the sandbox
  takes one more snapshot of the copy. The generator itself is pure `ast`: it never imports or
  executes repository code on the worker.
* `WORKER_TEST_EXECUTION_MODE` must be `sandbox`. With `disabled` or `unsafe_in_process` the
  producer does not execute anything and the analysis records `mutation unmeasured
  (sandbox_disabled)`; `unsafe_in_process` is never used for mutants, even when
  `RADIUS_ALLOW_UNSAFE_EXECUTION=true`.
* `SubprocessLocalRunner` (a plain child process) exists for development and for the F-14
  fixtures, which are our own code. It is refused unless `RADIUS_MUTATION_ALLOW_LOCAL=1`, and
  `measure_mutation` refuses it again unless the caller passes `allow_local_runner=True`; the
  worker never does. Do not set `RADIUS_MUTATION_ALLOW_LOCAL` on a worker.
* Test ids reach the command line only after validation (no leading `-`, no `..`, no absolute
  or drive path), so a test id cannot become a pytest option.
* The JUnit report written by the container is evidence from untrusted code with the same trust
  as any CI result: mutation output only changes support and can never create a pass from a
  failing test. A test that reads the source of the code it covers can fake kills (candidate
  tamper rule D9, not built).

**Docker access.** Mutation needs exactly what `sandbox` mode needs, nothing more: a container
runtime reachable from the worker (the `sandbox` target of `apps/worker/Dockerfile` adds the
`docker` CLI; the daemon is the host's, through a mounted socket or `DOCKER_HOST`) and the image
`WORKER_SANDBOX_IMAGE` already present locally with pytest and the project's dependencies.
The default `docker-compose.yml` worker has **no** docker socket and the `runtime` image has no
CLI, so under the default compose mutation reports `sandbox_disabled` and the static result is
used. This change does not widen any container privilege and adds no socket mount; a worker
with a socket is host-root-equivalent (see the residual risks below), so use it only on a
dedicated host, ideally with the gVisor/Firecracker recommendation at the end of this page.

### Measured: sandbox adapter versus local runner (2026-11-03)

`scripts/mutation_sandbox_compare.py 08` ran fixture 08 (gold mode, one target symbol,
23 generated and decided mutants) end to end twice with identical targets, budget and
seed: through the dev-only `SubprocessLocalRunner` and through `SandboxMutantRunner` over
`ContainerSandboxRunner` (image `radius-sandbox-test:latest` = `python:3.12-slim` + pytest,
Docker Desktop 29.7.2 on Windows 11, own `radius-sbx-*` containers only, none left over).

| | local runner | sandbox adapter |
| --- | --- | --- |
| Status | measured | measured |
| Kill matrix (status and killers of each of the 23 mutants, baseline failed/flaky) | reference | **identical, 0 differences** (18 killed, 5 survived) |
| Wall time for the whole measurement | 109.4 s | 116.9 s |
| Resource use | not sampled | at most 85 % of one CPU and 25.1 MiB RSS, from only 4 `docker stats` samples (each call takes about 2 s, so short runs are under-sampled); limits were the defaults 1 CPU, 1 GiB, 256 pids |

About 31 pytest invocations were made per runner (2 baseline, 1 control, 23 mutants, 5
survivor reruns), so roughly 3.5 s (local) and 3.8 s (container) per invocation on a loaded
machine; the container start was therefore not the dominant cost here. One sample on one
fixture; no generalisation to Linux hosts. No adapter defect was found: the command line,
the Windows bind-mount paths, the JUnit path (`/results/junit.xml`, key `0/junit.xml`) and
the per-run timeout all worked. A real timeout (a test sleeping 60 s, mutant timeout 4 s)
returned `timeout` after 8.0 s and left no container. The defect this exercise did find is
not in the adapter but in the Stage A budget (see `MUTATION_WIRED.md`).

**Can the default compose worker run mutation safely?** No. Running mutants needs a
container runtime reachable from the worker, that is a docker/podman CLI in the worker
image and either `/var/run/docker.sock` mounted or `DOCKER_HOST` pointing at a daemon,
plus `WORKER_TEST_EXECUTION_MODE=sandbox`, `RADIUS_FEATURE_MUTATION=true` and the image
`WORKER_SANDBOX_IMAGE` present on that daemon. The default compose `worker` has none of
these, so it reports `mutation unmeasured (sandbox_disabled)`. We found no way to add them
without widening privileges: mounting the socket (or a socket proxy that filters by API
endpoint, which cannot inspect the bind mounts and privileges inside a `containers/create`
body) lets whoever controls the worker start a privileged container with the host root
mounted. The only options that do not widen the default worker are a separate runner host,
a rootless podman socket for a dedicated user, or a Kubernetes Job, all operational
choices, none implemented here. The default stays as it is.

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
| CPU / memory / fork bomb | Timeout only | `--pids-limit`, `--memory` (= `--memory-swap`), `--cpus` | implemented; flags tested. Exercised against a real fork bomb, OOM, disk fill and output flood (see Adversarial verification) |
| Runaway / hung tests | Direct child killed; grandchildren may survive | Wall-clock timeout, then `<runtime> kill`, then `rm -f`, which takes the whole container | implemented; tested (fake launcher: kill before rm; real docker: no `radius-sbx-*` container left) |
| Image supply chain at analysis time | n/a | `--pull never`; image reference validated | implemented; argv tested |
| Result integrity | Errors give `error`, never `passed` | Same shared helpers (`pytest_outcome`, `exit_code_outcome`, `build_run_result`). Missing runtime and runtime exit codes 125/126/127 give `error`. JUnit must be a regular file (no symlink) of 20 MB or less | implemented; tested |
| Argument injection into the runtime | n/a | Untrusted command placed after the image; container name validated; argv list, no shell | implemented; tested |
| Kernel escape from the container | n/a | **Not covered.** A container shares the host kernel | not implemented: use gVisor (`runsc`) or a microVM for hostile multi-tenant workloads |
| Docker socket = root on the host | n/a | The worker needs runtime access, and the docker socket is root-equivalent: anyone who compromises the worker owns the host | operational: prefer rootless podman or a dedicated runner host/K8s Job; not implemented |

## Adversarial verification (F-07)

`packages/testing/tests/test_sandbox_adversarial.py` (marker `sandbox_adversarial`)
runs hostile payloads **only inside the sandbox container** with tight limits
(`pids 64`, `memory 128m` = swap, `cpus 0.5`, tmpfs `16m`, `fsize 1 MiB`, timeouts of
5-60 s). Payloads are written into a throw-away repository snapshot and are never run in
the test process or on the host. After each run the test asserts the container and the
ephemeral workspace are gone and the host checkout is untouched.

Executed on 2026-11-02: Windows 11 host, Docker Desktop engine 29.7.2 (Linux VM, runc
1.3.6, cgroup v2, builtin default seccomp), image `radius-sandbox-test:latest`
(`python:3.12-slim` + pytest). Result: **11 passed, 1 skipped.**

| Case | Payload | Observed (contained) | Runner classification |
| --- | --- | --- | --- |
| Infinite loop | `while True: pass` | killed at the 5 s timeout, container removed | `error`, "timed out after 5 seconds" |
| Fork bomb | unbounded `os.fork()` loop | pids cgroup held; killed at the 10 s timeout | `error`, "timed out after 10 seconds" |
| pids cap | fork up to 256 children with `--pids-limit 64` | `fork` raised `OSError` at or below 64 | payload printed `PIDS: DENIED` |
| Memory bomb | allocate and touch 8 MiB chunks, limit 128 MiB | OOM-killed (exit 137) | `error`, "killed by SIGKILL" |
| Disk fill | many 768 KiB files on a 16 MiB tmpfs; one 4 MiB file with `fsize` 1 MiB | `ENOSPC` at or below 16 MiB; single big file refused | `TMPFS: DENIED`, `FSIZE: DENIED` |
| Output flood | endless stdout, cap 512 KiB | container killed by the host watchdog; retained output bounded | `error`, "output exceeded" |
| Network egress | TCP to 1.1.1.1, 8.8.8.8, 169.254.169.254, 10.0.0.1; DNS | all failed; only `lo` exists | `NETWORK: DENIED` |
| Host env / secrets | scan environ, every `/proc/*/environ`, workspace and rootfs for fake secrets set in the host test process | none found | `ENV: DENIED` |
| Writes outside workspace | write to `/workspace`, `/`, `/etc`, `/usr`, `/root`; mkdir; delete the payload | all refused; only `/tmp` writable | `WRITE: DENIED` |
| /proc and /sys | write `core_pattern`, `sysrq-trigger`, `drop_caches`, `uevent_helper`; read `kcore`, `kmsg`, `/proc/1/mem` | writes refused; masked files read empty; at most 20 PIDs visible (own namespace) | `PROC: DENIED` |
| Privileges | `CapEff`/`CapBnd`, `NoNewPrivs`, `Seccomp`; `mount`, `chroot`, `setuid(0)`, `unshare(NEWUSER)` | uid 65534, no capabilities, `NoNewPrivs=1`, `Seccomp=2`, every privileged syscall failed | `PRIV: DENIED` |
| Symlink escape | symlinks to a host secret file and `../../..` | **skipped here**: creating symlinks needs a privilege this Windows account lacks | n/a |

Negative control (benign commands, default docker flags): `/sys/class/net` shows `eth0`,
the rootfs is writable and the process is uid 0 with `CapEff=a80425fb`, `NoNewPrivs=0`,
so the checks above fail without the sandbox flags.

Timings (wall clock including container start on this host): about 4-5 s for the
confinement probes, 8 s for the memory bomb, 14 s for the 5 s-timeout loop, 19 s for the
fork bomb; the whole file about 63 s.

Not demonstrated: the symlink case (needs a Linux runner), CPU throttling accuracy,
podman, rootless docker, gVisor/Firecracker and cgroup v1. Two older tests
(`test_container_argv_contains_every_isolation_flag`, which compares POSIX paths, and
`test_snapshot_is_a_fresh_copy...`, which creates a symlink) and
`test_subprocess_runner_executes_pytest_plan` also fail on this Windows host on the
unmodified baseline; they are expected to pass on Linux CI.

### CI step to add (`ci.yml` is owned elsewhere)

On a Linux runner with docker, after the existing "Build sandbox test image" step:

```yaml
      - name: Sandbox adversarial suite
        env:
          RADIUS_REQUIRE_SANDBOX_TESTS: "true"
        run: uv run pytest -m sandbox_adversarial packages/testing/tests/test_sandbox_adversarial.py -v
```

`RADIUS_REQUIRE_SANDBOX_TESTS=true` turns a missing docker or image into an error
instead of a silent skip. Locally the suite skips with a reason when docker or the image
is absent. The symlink-escape test only runs on a host that can create symlinks (Linux).

## Residual risks

* **Shared kernel.** Namespaces, cgroups, capabilities and seccomp all rely on the host
  kernel. A kernel or runc vulnerability is a full escape. Not mitigated.
* **Docker socket is root.** The worker that launches containers can effectively become
  host root; compromising the worker compromises the host.
* **Output cap granularity.** The host watchdog polls every 0.2 s, so output can briefly
  exceed the cap; the stream files live on host disk until the run ends.
* **CPU and IO.** `--cpus` throttles but does not stop contention on memory bandwidth;
  there is no block-IO limit.
* **Writable results mount** (`/results`, mode 0777) is host disk; `fsize` bounds each
  file but not the number of files. Only `junit.xml` (regular file, 20 MB or less) is read.
* **Image trust.** The image is operator-provisioned (`--pull never`); pin it by digest
  in production. A compromised image is out of scope.
* **Side channels and speculative execution** are not addressed by a container.
* tmpfs `/tmp` is not `noexec` (pytest and wheels may need it), so payloads can run code
  from `/tmp` as the nobody user within the limits above.

## Recommendation: gVisor / Firecracker for production

Recommendation only; nothing was installed or tested here. For executing code from
untrusted pull requests in a multi-tenant deployment, run the same container spec under
**gVisor** (register `runsc` as a runtime on a dedicated host and add `--runtime runsc`)
so syscalls are served by a user-space kernel instead of the host kernel, or use
**Firecracker** microVMs (one VM per run, for example a dedicated runner fleet or
Kubernetes Jobs with a microVM runtime class) when a hardware-virtualisation boundary is
required. Either way: use dedicated, disposable runner hosts with no worker credentials,
keep egress off, never mount the docker socket into anything that handles tenant data,
and re-run this adversarial suite against the chosen runtime before enabling it. Until
then keep `WORKER_TEST_EXECUTION_MODE=disabled` and run tests in the customer's CI.

## Other verification

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

## Checkout isolation (review C, C-03)

The path handed to the sandbox, the in-process runner, the parser and the verdict v2 mutation
step is a **per-analysis git worktree** (`<REPOSITORY_CACHE_DIR>/.worktrees/<analysis id>-<random>`),
not a directory shared by every analysis of the repository, and it is deleted when the job ends
(also on failure). The sandbox still copies the tree without `.git`. See DEC-038.
