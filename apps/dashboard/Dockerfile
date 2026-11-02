# syntax=docker/dockerfile:1
#
# Radius dashboard image (Next.js standalone output). Hardened per PRD-08 (see
# docs/security/CONTAINERS.md). The base image is pinned by digest; the tag is what
# Dependabot (package-ecosystem: docker) reads and bumps together with the digest.

FROM node:22-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS deps

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH

WORKDIR /app

RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml turbo.json tsconfig.base.json ./
COPY apps/dashboard ./apps/dashboard
COPY packages ./packages

RUN pnpm install --frozen-lockfile

FROM node:22-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS builder

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
ENV NEXT_TELEMETRY_DISABLED=1
# Emit .next/standalone (a traced server.js plus only the node_modules it needs)
# without editing next.config.mjs, which is owned by another task.
ENV NEXT_PRIVATE_STANDALONE=true

WORKDIR /app

RUN corepack enable

COPY --from=deps /app ./

RUN pnpm --filter @radius/dashboard build

FROM node:22-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS runtime

ARG RADIUS_VERSION=0.1.0
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="radius-dashboard" \
      org.opencontainers.image.description="Radius dashboard (Next.js)" \
      org.opencontainers.image.source="https://github.com/Mohith-c7/Radius" \
      org.opencontainers.image.version="${RADIUS_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.base.name="docker.io/library/node:22-slim"

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

# Fixed uid/gid 10001 (the base image's built-in `node` user is 1000). The runtime only
# executes `node server.js`, so npm/corepack/yarn (bundled in the base image) are removed
# to drop their dependency tree from the attack surface and from scans.
RUN groupadd --system --gid 10001 radius \
    && useradd --system --uid 10001 --gid 10001 --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin radius \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
              /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
              /opt/yarn-* /usr/local/bin/yarn /usr/local/bin/yarnpkg

COPY --from=builder /app/apps/dashboard/.next/standalone ./
COPY --from=builder /app/apps/dashboard/.next/static ./apps/dashboard/.next/static

USER 10001:10001

EXPOSE 3000

# /login is public (no session needed) and exercises the middleware and a page render.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:'+(process.env.PORT||3000)+'/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]

CMD ["node", "apps/dashboard/server.js"]
