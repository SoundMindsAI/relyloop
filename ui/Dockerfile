# syntax=docker/dockerfile:1.7
#
# RelyLoop UI — multi-stage Next.js 16 build (chore_tutorial_polish Story 2.2).
#
# NEXT_PUBLIC_API_BASE_URL must be passed as a build ARG because Next.js bakes
# NEXT_PUBLIC_* into the client bundle at `pnpm build`. A Compose
# `environment:` var would have NO effect on the built bundle. See
# docs/02_product/planned_features/chore_tutorial_polish/feature_spec.md §3
# (decision log entry 2026-05-12 M3) for the rationale.
#
# Node base: node:26-bookworm-slim. Node 26 is the current major (released
# 2026-04, on the LTS track — even-numbered Node releases enter LTS in
# October of the year they were released as current). Bumped from Node 24
# in PR #290 (chore_docker_image_bumps) to track latest. The repo's
# `.nvmrc` pins Node 22 for host development; the runtime image runs
# Node 26 to use the latest engine features without waiting for the
# October LTS transition.

# node:26-bookworm-slim, digest-pinned (PinnedDependencies / OSSF Scorecard).
# The digest is written literally on every FROM (not via an ARG) because
# Scorecard's static parser only credits a pin it can see inline as
# `image@sha256:…`; an ARG-indirected digest reads as "unpinned". Dependabot's
# docker ecosystem bumps every occurrence in lockstep, so the repetition is not
# a sync hazard.
FROM node:26-bookworm-slim@sha256:79723b41edbedf595f62e943a9f8b0ba9af5b1e61045c5f8f59c2c02c1212a16 AS deps
WORKDIR /app
RUN npm install -g pnpm@9
COPY pnpm-lock.yaml package.json ./
RUN pnpm install --frozen-lockfile

FROM node:26-bookworm-slim@sha256:79723b41edbedf595f62e943a9f8b0ba9af5b1e61045c5f8f59c2c02c1212a16 AS builder
WORKDIR /app
RUN npm install -g pnpm@9
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN pnpm build

FROM node:26-bookworm-slim@sha256:79723b41edbedf595f62e943a9f8b0ba9af5b1e61045c5f8f59c2c02c1212a16 AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
RUN groupadd -r relyloop && useradd -r -g relyloop relyloop
COPY --from=builder --chown=relyloop:relyloop /app/.next/standalone ./
COPY --from=builder --chown=relyloop:relyloop /app/.next/static ./.next/static
# Walkthrough guide assets (PNGs + metadata.json + script.md per guide) live
# under public/guides/ and are served by Next.js at /guides/{id}/{file}. Must
# ship in the runtime image or the GuideViewer 404s (the Next.js standalone
# output mode does NOT include `public/` by default).
COPY --from=builder --chown=relyloop:relyloop /app/public ./public
USER relyloop
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"
CMD ["node", "server.js"]
