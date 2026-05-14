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
# Node base: node:24-bookworm-slim. Node 24 is the current Active LTS
# (released 2025-10, supported until 2027-04). The repo's `.nvmrc` pins
# Node 22 for host development, but Node 24 in the runtime image avoids
# bit-rot vs. picking a soon-to-be-EOL'd LTS like Node 20.

FROM node:24-bookworm-slim AS deps
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9 --activate
COPY pnpm-lock.yaml package.json ./
RUN pnpm install --frozen-lockfile

FROM node:24-bookworm-slim AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9 --activate
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN pnpm build

FROM node:24-bookworm-slim AS runner
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
