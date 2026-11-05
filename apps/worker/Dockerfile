# syntax=docker/dockerfile:1
#
# Radius worker image. Hardened per PRD-08 (see docs/security/CONTAINERS.md).
# Base images are pinned by digest; the tag in each FROM line is what Dependabot
# (package-ecosystem: docker) reads and bumps together with the digest.
#
# Targets:
#   runtime  (default) no container runtime inside; WORKER_TEST_EXECUTION_MODE
#            must be `disabled` (default). Least privilege.
#   sandbox  runtime + docker CLI, for WORKER_TEST_EXECUTION_MODE=sandbox. The
#            CLI talks to a daemon you provide (mounted socket or DOCKER_HOST);
#            see docs/security/EXECUTION_ISOLATION.md and CONTAINERS.md.

FROM ghcr.io/astral-sh/uv:0.12.20@sha256:100047e74f30778ab704942321a09750d6158739573ff58bf3924085cc6cd2d8 AS uv
FROM docker:29-cli@sha256:5e6baf67325a79f64ed3bed6863954d5e05d0f3d4e57cbdb14809346814bbfdb AS docker-cli

FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30 AS builder

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_NO_BUILD=1 \
    UV_HTTP_TIMEOUT=100

WORKDIR /build
COPY pyproject.toml uv.lock ./

# Pass RADIUS_EXTRAS="[observability]" to bundle OpenTelemetry/Prometheus. Other extras:
# "llm" (Anthropic intent extraction), "gemini" (legacy experimental pruner). Comma separated.
ARG RADIUS_EXTRAS=""
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    set -eu; \
    extras=""; \
    for e in $(echo "${RADIUS_EXTRAS}" | tr -d '[]' | tr ',' ' '); do extras="$extras --extra $e"; done; \
    uv sync --frozen --no-dev --no-install-project --python /usr/local/bin/python $extras

FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30 AS base

ARG RADIUS_VERSION=0.1.0
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="radius-worker" \
      org.opencontainers.image.description="Radius analysis worker" \
      org.opencontainers.image.source="https://github.com/Mohith-c7/Radius" \
      org.opencontainers.image.version="${RADIUS_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.base.name="docker.io/library/python:3.12-slim"

ENV PATH=/opt/venv/bin:$PATH \
    HOME=/home/radius \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/worker/src:/app/packages/analysis/src:/app/packages/confidence/src:/app/packages/evidence/src:/app/packages/github/src:/app/packages/graph/src:/app/packages/intent/src:/app/packages/linking/src:/app/packages/parser/src:/app/packages/repository/src:/app/packages/shared/src:/app/packages/testing/src

# git clones the repositories under analysis. Fixed uid/gid so volume ownership is
# predictable. The cache dir is created owned by the app user so a fresh named
# volume mounted there inherits that ownership (compose uses
# REPOSITORY_CACHE_DIR=/var/lib/radius/repositories).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 radius \
    && useradd --system --uid 10001 --gid 10001 --home-dir /home/radius --create-home --shell /usr/sbin/nologin radius \
    && mkdir -p /var/lib/radius/repositories \
    && chown -R 10001:10001 /var/lib/radius

WORKDIR /app

ENV WORKER_HEALTH_FILE=/tmp/radius-worker-health

COPY --from=builder /opt/venv /opt/venv
COPY pyproject.toml alembic.ini ./
COPY infra/database ./infra/database
COPY apps/worker/src ./apps/worker/src
COPY packages ./packages

# ---- sandbox: opt-in, adds the docker CLI only (no daemon).
FROM base AS sandbox
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-m", "radius_worker.healthcheck"]
CMD ["python", "-m", "radius_worker"]

# ---- runtime: default target (must stay last).
FROM base AS runtime
USER 10001:10001

# The worker has no listening port unless RADIUS_WORKER_METRICS_PORT is set (it
# needs the observability extra), so liveness = the worker can reach its database
# AND its loop (or the lease heartbeat of a running job) touched WORKER_HEALTH_FILE
# recently (python -m radius_worker.healthcheck).
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-m", "radius_worker.healthcheck"]

CMD ["python", "-m", "radius_worker"]
