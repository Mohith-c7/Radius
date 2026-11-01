FROM node:22-slim AS deps

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH

WORKDIR /app

RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml turbo.json tsconfig.base.json ./
COPY apps/dashboard ./apps/dashboard
COPY packages ./packages

RUN pnpm install --frozen-lockfile

FROM node:22-slim AS builder

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

RUN corepack enable

COPY --from=deps /app ./

RUN pnpm --filter @radius/dashboard build

FROM node:22-slim AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

WORKDIR /app

RUN corepack enable

COPY --from=builder /app ./

EXPOSE 3000

CMD ["pnpm", "--dir", "apps/dashboard", "exec", "next", "start"]
