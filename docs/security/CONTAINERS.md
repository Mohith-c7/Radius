# Container hardening (PRD-08)

Applies to `apps/api/Dockerfile`, `apps/worker/Dockerfile`, `apps/dashboard/Dockerfile`.
Scanned by `.github/workflows/container-scan.yml`. Measured on 2026-11-02 (Docker 29.7.2,
amd64, Trivy from `aquasec/trivy@sha256:790fd66d...`).

## What changed and why

| Area | Decision |
| --- | --- |
| Base images | Pinned by digest (`python:3.12-slim@sha256:...`, `node:22-slim@sha256:...`, `ghcr.io/astral-sh/uv:0.12.20@sha256:...`, `docker:29-cli@sha256:...`). The readable tag stays on the same `FROM` line, which is the form Dependabot (`package-ecosystem: docker`) understands, so it bumps tag and digest together. |
| Python deps | Installed from `uv.lock` (`uv sync --frozen --no-dev --no-install-project`) in a builder stage; uv verifies the hashes recorded in the lock file and `UV_NO_BUILD=1` forbids compiling from source, so the final image has no compiler and no pip cache. Only the venv (`/opt/venv`) is copied to the runtime stage. `RADIUS_EXTRAS="[observability]"` still works (mapped to `--extra`). |
| User | Fixed `radius` user, **uid/gid 10001:10001**, `USER 10001:10001`, nologin shell. Application code is root-owned and read-only to it. |
| Health | api: `HEALTHCHECK` on `GET /api/v1/ready` (database + queue, honours `PORT`). Worker: opens a DB connection and runs `select 1` (see limits below). Dashboard: `GET /login` (public page; exercises middleware and rendering). |
| Dashboard | Next.js standalone output (`NEXT_PRIVATE_STANDALONE=true` in the build stage, so `next.config.mjs` is untouched). Runtime runs `node apps/dashboard/server.js`; npm/corepack/yarn are removed from the runtime stage. The F-05 proxy route (`/api/radius/*`) was verified in the standalone server. |
| Labels | `org.opencontainers.image.{title,description,source,version,revision,licenses,base.name}`. `licenses` is `Apache-2.0` (DEC-018, `LICENSE`). Pass `--build-arg VCS_REF=$(git rev-parse HEAD)` and `--build-arg RADIUS_VERSION=...`. |
| Secrets | None in layers: no `ENV`/`ARG` secrets; `.dockerignore` excludes `.env*`, `.git`, tests, docs, benchmarks. |
| Fix found on the way | The old API image could not start: `PYTHONPATH` lacked `packages/intent/src` (`ModuleNotFoundError: radius_intent`). Added for api and worker. |

### Measured results

| Image | Before | After | uid before / after |
| --- | --- | --- | --- |
| api | 718 MB | 644 MB | 0 / 10001 |
| worker | 717 MB | 644 MB | 0 / 10001 |
| worker `--target sandbox` | n/a | 708 MB | n/a / 10001 |
| dashboard | 1.32 GB | 435 MB | 0 / 10001 |

Trivy (HIGH+CRITICAL, `--ignore-unfixed`): python images 0 before, 0 after. Dashboard 29
before (26 high, 3 critical), 11 after: npm's bundled dependency tree is gone, the rest are
application dependencies from `pnpm-lock.yaml` (next 15.5.22, postcss 8.4.31, sharp 0.34.5,
nanoid, source-map-js), temporarily waived in `.trivyignore` until the lockfile is bumped.
Dockerfile misconfiguration scan: 0 findings (all severities).

## Writable paths and read-only root

All three images ran healthy with `--read-only --cap-drop ALL --security-opt no-new-privileges`.

| Image | Must be writable | Notes |
| --- | --- | --- |
| api | nothing | `PYTHONDONTWRITEBYTECODE=1`; alembic and uvicorn write nothing. Give `/tmp` a tmpfs anyway if you add libraries that use it. |
| worker | the repository cache volume at `/var/lib/radius/repositories` (owned by 10001) | `git clone`/`fetch` worked with a read-only root and `HOME=/home/radius`. Only `git config --global` needs `/home/radius` writable (the code does not call it). Use `--tmpfs /tmp` for scratch (the unsafe in-process runner and the sandbox runner create temp dirs). |
| dashboard | nothing observed | Standalone server serves a read-only tree. Add `--tmpfs /tmp` if you enable features that write caches. |

```bash
docker run --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  -v radius-repository-cache:/var/lib/radius/repositories \
  -e DATABASE_URL=... radius-worker
```

A named volume created by an older (root) image stays root-owned: recreate it or
`chown -R 10001:10001` its contents. A fresh volume inherits 10001 from the image.

## Worker and the sandbox runtime

The default worker image contains **no container runtime** and runs with
`WORKER_TEST_EXECUTION_MODE=disabled` (the default). Sandbox mode
(`docs/security/EXECUTION_ISOLATION.md`) needs a docker/podman CLI plus a daemon:

```bash
docker build -f apps/worker/Dockerfile --target sandbox -t radius-worker:sandbox .
docker run --group-add "$(stat -c %g /var/run/docker.sock)" \
  -v /var/run/docker.sock:/var/run/docker.sock ... radius-worker:sandbox
```

The `sandbox` target only adds the `docker` CLI binary (no daemon, still uid 10001).
Mounting the host docker socket is root-equivalent on the host: prefer a remote or
rootless daemon via `DOCKER_HOST` (allow-listed by the sandbox runner) and treat that
host as part of the trusted base. The API image gets no runtime and no extra privileges.

## Health check limits

* The worker has no listening port unless `RADIUS_WORKER_METRICS_PORT` is set (needs the
  observability extra), so its check proves database reachability only. A hung poll loop
  is not detected. Follow-up: have the loop touch a heartbeat file or expose `/health`.
* api uses `/ready`, so a database outage marks the container unhealthy; for orchestrators
  with split probes use `/api/v1/health` for liveness and `/api/v1/ready` for readiness.

## How to verify locally

```bash
docker build -f apps/api/Dockerfile -t radius-api --build-arg VCS_REF=$(git rev-parse HEAD) .
docker run --rm --entrypoint id radius-api                 # uid=10001(radius)
docker image inspect radius-api --format '{{json .Config.Labels}}'
docker inspect --format '{{.State.Health.Status}}' <running container>

TRIVY=aquasec/trivy@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock "$TRIVY" image \
  --severity HIGH,CRITICAL --ignore-unfixed --ignorefile .trivyignore --exit-code 1 radius-api
docker run --rm -v "$PWD:/work:ro" -w /work "$TRIVY" config apps
```

The API needs a database to become healthy: start `postgres` (for example
`docker run -d --network n -e POSTGRES_PASSWORD=... postgres:16-alpine`) and pass
`DATABASE_URL`, `STORAGE_BACKEND=sql`.

## CI

`container-scan.yml` runs on PRs that touch Dockerfiles, lock files or `.trivyignore`, on
pushes to `develop` that touch Dockerfiles, and weekly (Monday 04:17 UTC). It builds each
image without pushing, checks uid != 0, writes SARIF and uploads it to code scanning
(non-blocking: skipped for fork PRs, ignored if code scanning is unavailable), then fails
on fixable HIGH/CRITICAL findings. Permissions are `contents: read` plus
`security-events: write` on the image job only.

## Updating pinned digests

Dependabot (needs a `docker` entry per Dockerfile directory in `.github/dependabot.yml`,
not part of PRD-08's ownership) opens PRs that bump `tag@digest` together. By hand:

```bash
docker buildx imagetools inspect python:3.12-slim   # copy the top-level Digest
```

Replace the digest in every `FROM` that uses the image (api and worker share the python
digest, dashboard the node one), rebuild, rerun the scan. The Trivy digest lives in
`TRIVY_IMAGE` in the workflow and in this page. Digests are the multi-arch index digest,
so the same pin works for arm64 (multi-arch builds and signing are PRD-13).

## Ignores policy

`.trivyignore` entries must carry `exp:YYYY-MM-DD` and a justification. Expired entries
stop applying, which turns the gate red again by design.
