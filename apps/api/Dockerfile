# syntax=docker/dockerfile:1
#
# Radius API image. Hardened per PRD-08 (see docs/security/CONTAINERS.md).
# Base images are pinned by digest; the tag in each FROM line is what Dependabot
# (package-ecosystem: docker) reads and bumps together with the digest.

FROM ghcr.io/astral-sh/uv:0.12.20@sha256:100047e74f30778ab704942321a09750d6158739573ff58bf3924085cc6cd2d8 AS uv

# ---- builder: install dependencies exactly as locked in uv.lock (uv verifies the
# hashes recorded there). No compiler is needed: UV_NO_BUILD makes the build fail
# instead of compiling any package from source.
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

# ---- runtime
FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30 AS runtime

ARG RADIUS_VERSION=0.1.0
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="radius-api" \
      org.opencontainers.image.description="Radius API (FastAPI)" \
      org.opencontainers.image.source="https://github.com/Mohith-c7/Radius" \
      org.opencontainers.image.version="${RADIUS_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.base.name="docker.io/library/python:3.12-slim"

ENV PATH=/opt/venv/bin:$PATH \
    HOME=/home/radius \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/api/src:/app/apps/worker/src:/app/packages/analysis/src:/app/packages/confidence/src:/app/packages/evidence/src:/app/packages/github/src:/app/packages/graph/src:/app/packages/intent/src:/app/packages/linking/src:/app/packages/parser/src:/app/packages/repository/src:/app/packages/shared/src:/app/packages/testing/src

# git is used by the diff provider. Fixed uid/gid so volume ownership is predictable.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 radius \
    && useradd --system --uid 10001 --gid 10001 --home-dir /home/radius --create-home --shell /usr/sbin/nologin radius

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY pyproject.toml alembic.ini ./
COPY infra/database ./infra/database
COPY apps/api/src ./apps/api/src
COPY apps/worker/src ./apps/worker/src
COPY packages ./packages

# Application code stays root-owned (read-only for the app user).
USER 10001:10001

EXPOSE 8000

# /api/v1/ready checks the database and the job queue (503 when not ready).
# start-period covers `alembic upgrade head` in CMD.
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/api/v1/ready' % os.environ.get('PORT', '8000'), timeout=3)"

CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn radius_api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
