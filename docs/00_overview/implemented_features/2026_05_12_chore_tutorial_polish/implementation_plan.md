# Implementation Plan — chore_tutorial_polish

**Date:** 2026-05-12
**Status:** Complete (PR #64 merged 2026-05-12 as `bb95e3f`); Stories 4.6 + 4.7 deferred to maintainer per release-checklist.md
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy sources:**
- [`docs/01_architecture/deployment.md`](../../../01_architecture/deployment.md) — Compose layout + secrets pattern
- [`docs/01_architecture/llm-orchestration.md`](../../../01_architecture/llm-orchestration.md) — local-LLM operator workflow + capability check
- [`docs/01_architecture/tech-stack.md`](../../../01_architecture/tech-stack.md) — canonical release matrix (image-publish deferred to MVP3)
- [`CLAUDE.md`](../../../../CLAUDE.md) — operator-path verification rule, port binding pattern, secrets-via-files convention, `make reset` `FORCE=1` requirement

---

## 0) Planning principles

1. **Single source of truth for the operator path.** Tutorial Steps 1–10 in the spec are the canonical sequence; the smoke job, the runbook, and the README quickstart all point at the same steps in the same order. Any drift between them is a finding.
2. **Runtime alignment is the release-blocking invariant.** The smoke test asserts at least one trial has `primary_metric > 0` after a 10-trial study — proves the LLM-generated judgments and the `samples/products.json`-seeded index intersect. (The earlier draft of this plan added a static `samples/validate.py` doc-id-alignment validator alongside a pre-baked `samples/judgments.json`; both were dropped during cycle-2 review when the no-OpenAI tutorial path was cut. The runtime guard catches the same class of failure with one fewer artifact to maintain.)
3. **The smoke gate runs the LLM-required path.** `OPENAI_API_KEY_TEST` is a hard requirement, not an optional CI variant. Without it, the digest path silently degrades and the chat-agent confirmation flow doesn't exercise tool dispatch — the path design partners actually run is uncovered.
4. **Manual operator steps are explicit.** Several stories have prerequisites a maintainer must complete by hand (curating the ESCI subset, adding the `OPENAI_API_KEY_TEST` GitHub secret, recording the demo, pushing the tag). The plan calls these out at the top of each story so `/impl-execute` escalates them as Manual configuration steps rather than failing partway through.
5. **No new APIs, no schema, no frontend.** This is pure infra + docs + release. The plan must NOT introduce endpoints, migrations, or `ui/src/` changes — anything that would tempts that scope is a finding.

---

## 1) Scope traceability (FR → epics/stories → tests)

Source: spec §17 traceability matrix.

| Spec FR | Epic | Story | Tests |
|---|---|---|---|
| **FR-1** Worked tutorial doc | Epic 4 | Story 4.1 | manual VM walkthrough (release-checklist runbook) + smoke job (Steps 1–8 covered automatically) |
| **FR-2** Sample data + seed script | Epic 1 + Epic 2 | Stories 1.1, 2.1 | `backend/tests/smoke/test_tutorial_path.py` — runtime alignment guard (`primary_metric > 0` after LLM-generated judgments) |
| **FR-3** UI containerization | Epic 2 | Stories 2.2, 2.3 | smoke job AC-9 (curl 127.0.0.1:3000) |
| **FR-4** Smoke-test CI job | Epic 3 | Stories 3.1, 3.2 | the smoke job IS the test; forced-failure dry-run validates the artifact-upload branch |
| **FR-5** README polish | Epic 4 | Story 4.2 | manual checklist review per AC-4 |
| **FR-6** Demo recording | Epic 4 | Story 4.6 | manual (blocking — maintainer records + uploads) |
| **FR-7** Tag + Release | Epic 4 | Story 4.7 | manual (blocking — maintainer pushes tag + writes release notes) |

| Spec AC | Story owner |
|---|---|
| AC-1 (≤30 min fresh-VM tutorial with hosted-OpenAI) | Story 4.1 (writes the tutorial) + Story 4.3 (release-checklist runbook captures the timed walkthrough) |
| AC-2 (smoke passes in CI in ≤15 min) | Story 3.2 |
| AC-3 (80% backend coverage gate fires on merge commit) | Story 4.7 (release-checklist verifies before tag) |
| AC-4 (README content checklist) | Story 4.2 |
| AC-5 (local-LLM tutorial path verified) | Story 4.1 (tutorial documents local-LLM path in Step 0) + Story 4.3 (release-checklist captures the manual local-LLM walkthrough) |
| AC-6 (demo recording linked from README) | Story 4.6 (record + upload) + Story 4.2 (README links it) |
| AC-7 (v0.1.0 GitHub Release published) | Story 4.7 |
| AC-8 (UI container reachable from smoke job) | Story 3.2 (curl assertion in CI step 9) |
| AC-9 (smoke alignment guard fires on positive trial) | Story 3.1 (smoke pytest) + Story 3.2 (CI run that surfaces the assertion failure) |

---

## 2) Delivery structure

**4 epics, 13 stories, ~2 working days end-to-end** (excludes the manual demo-recording + tag-push windows). Stories 1.2 (validator) + 1.3 (pre-baked judgments) were dropped during /pipeline --auto cycle-2 review when the no-OpenAI tutorial path was cut from scope (see spec §19 Decision log 2026-05-12 — the import path required a `BulkQueryItem.id` field that doesn't exist).

- **Epic 1 — Sample data infrastructure** (1 story): the `samples/` directory bootstrap.
- **Epic 2 — Operator-path scripts + UI containerization** (3 stories): `seed_es.py` + `make seed-es`, `ui/Dockerfile`, the `ui` Compose service.
- **Epic 3 — Smoke-test CI gate** (2 stories): the orchestrator script + the GitHub Actions job.
- **Epic 4 — Documentation + release** (7 stories): tutorial, README, release-checklist runbook, deployment.md update, mvp1-user-stories.md flips, demo recording, tag + release.

Sequencing is mostly linear (downstream stories depend on upstream artifacts existing), with two parallelizable seams flagged in §7.

---

## Epic 1 — Sample data infrastructure

### Story 1.1 — `samples/` directory bootstrap (products + queries + template + LICENSE)

**Outcome:** `samples/` at the repo root contains the curated Amazon ESCI subset (~1,000 products + 50 queries) + the canonical demo template + a LICENSE file documenting source/license per file. The runtime alignment between the seeded products + LLM-generated judgments is verified by AC-9 (`primary_metric > 0` in the smoke test), so no static validator is needed.

**Manual prerequisite:** Maintainer downloads the [Amazon ESCI dataset](https://github.com/amazon-science/esci-data) (CC-BY-4.0), subsets to ~1,000 representative `product_id`s spanning all 4 ESCI labels (E/S/C/I), and pulls the matching ~50 `query_id`s. Curation criteria: queries with at least 5 judged products; products with non-empty title + description. Produces the source files for this story to commit.

**New files**

| File | Purpose |
|---|---|
| `samples/products.json` | JSON array (NOT JSONL), ~1000 docs. Each row: `{"id": "<esci_product_id>", "title": "...", "description": "...", "brand": "...", "color": "...", "bullet_points": [...]}`. Schema matches the `product_search.j2` template's expected fields. Validator + seed_es.py both call `json.loads()` and iterate — JSONL would break both. |
| `samples/queries.csv` | Header `query_id,query_text`. 50 rows. `query_id` matches ESCI's `query_id`. |
| `samples/templates/product_search.j2` | Jinja2 template with declared params: `field_boosts.title` (float 0.5–10), `field_boosts.description` (float 0.5–10), `field_boosts.bullet_points` (float 0.5–10), `tie_breaker` (float 0.0–1.0), `fuzziness` (str: `"AUTO" \| "0" \| "1" \| "2"`). Renders to an Elasticsearch `multi_match` query body with these as parameters. |
| `samples/LICENSE` | Per-file license + source: products + queries under CC-BY-4.0 (Amazon ESCI); template MIT (RelyLoop original). (No `judgments` row — pre-baked judgments cut per spec Decision log 2026-05-12.) |

**Modified files** — none yet.

**Tasks**
1. Subset Amazon ESCI per the curation criteria above. Document the exact subsetting script in `samples/LICENSE` for reproducibility.
2. Write `samples/products.json` from the subset. Verify schema by hand-loading 5 random rows.
3. Write `samples/queries.csv` from the subset. Header line + 50 data rows.
4. Author `samples/templates/product_search.j2` — render a `multi_match` query against `title`, `description`, `bullet_points` with the documented declared params. Smoke-test by rendering with default params and pasting the JSON into the Kibana console against a hand-loaded ES instance.
5. Write `samples/LICENSE` covering source + license per file, plus the subsetting script.

**Definition of Done**
- [ ] `samples/products.json` exists with ≥1000 product rows, schema matches the template's expected fields.
- [ ] `samples/queries.csv` exists with 50 rows + header.
- [ ] `samples/templates/product_search.j2` renders to valid ES Query DSL with all declared params.
- [ ] `samples/LICENSE` documents CC-BY-4.0 source + the subsetting script.
- [ ] Manual hand-load of 5 random products into the local ES container succeeds (no schema errors).

---


## Epic 2 — Operator-path scripts + UI containerization

### Story 2.1 — `backend/app/scripts/seed_es.py` + `make seed-es` target

**Outcome:** A new operator script populates the local ES container's `products` index from `samples/products.json` idempotently. `make seed-es` wraps `docker compose exec api python -m backend.app.scripts.seed_es` (matches the existing `seed-clusters` pattern at [`Makefile:126-130`](../../../../Makefile)).

**New files**

| File | Purpose |
|---|---|
| `backend/app/scripts/seed_es.py` | Async script. Connects to `local-es` cluster (resolved via `cluster_repo.get_active_cluster_by_name(db, "local-es")`); creates the `products` index with the documented mapping if absent; bulk-indexes from `samples/products.json` via the ElasticAdapter's underlying httpx client OR `_bulk` API. Idempotent — DELETE + recreate on every run so reruns don't accumulate stale docs. |
| `backend/tests/integration/test_seed_es.py` | Integration test (skips when ES unreachable): seed empty index → assert 1000 docs present; re-seed → assert still 1000 (no duplication, no orphans). |

**Modified files**

| File | Change |
|---|---|
| `Makefile` | New target `seed-es:` after `seed-clusters:` (around `Makefile:126`). One line: `\tdocker compose exec -T api python -m backend.app.scripts.seed_es`. Add to `.PHONY` list (line 9). |

**Key interface**

```python
# backend/app/scripts/seed_es.py
"""Idempotent seed script — populates local-es:products from samples/products.json.

Invocation: `docker compose exec -T api python -m backend.app.scripts.seed_es`
            (or `make seed-es` from the repo root).

Resolves the cluster via cluster_repo.get_active_cluster_by_name(db, "local-es")
— assumes Story 4 of infra_adapter_elastic's seed-clusters has already run.
DELETE+recreates the `products` index every run so judgments stay aligned with
the documented sample data.
"""

import asyncio
import json
from pathlib import Path

import httpx

from backend.app.core.logging import get_logger
from backend.app.db import repo
from backend.app.db.session import async_sessionmaker, create_async_engine
from backend.app.core.settings import get_settings

logger = get_logger(__name__)
SAMPLES_PRODUCTS = Path(__file__).resolve().parents[3] / "samples" / "products.json"
INDEX_NAME = "products"


async def main() -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as db:
        cluster = await repo.get_active_cluster_by_name(db, "local-es")
        if cluster is None:
            logger.error("seed_es: local-es cluster not registered. Run `make seed-clusters` first.")
            return 1
    products = json.loads(SAMPLES_PRODUCTS.read_text())
    logger.info("seed_es: loaded %d products from %s", len(products), SAMPLES_PRODUCTS)

    async with httpx.AsyncClient(base_url=cluster.base_url, timeout=30.0) as client:
        # DELETE existing index (idempotent; ignore 404).
        await client.delete(f"/{INDEX_NAME}")
        # Create with mapping derived from products schema.
        await client.put(
            f"/{INDEX_NAME}",
            json={"mappings": {"properties": {
                "title": {"type": "text"},
                "description": {"type": "text"},
                "brand": {"type": "keyword"},
                "color": {"type": "keyword"},
                "bullet_points": {"type": "text"},
            }}},
        )
        # _bulk-index — chunk into 500-doc batches.
        for i in range(0, len(products), 500):
            chunk = products[i : i + 500]
            body_lines = []
            for p in chunk:
                body_lines.append(json.dumps({"index": {"_index": INDEX_NAME, "_id": p["id"]}}))
                body_lines.append(json.dumps(p))
            resp = await client.post("/_bulk", content="\n".join(body_lines) + "\n",
                                     headers={"Content-Type": "application/x-ndjson"})
            resp.raise_for_status()
        await client.post(f"/{INDEX_NAME}/_refresh")
    logger.info("seed_es: indexed %d products into %s/%s", len(products), cluster.base_url, INDEX_NAME)
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

**Tasks**
1. Write `backend/app/scripts/seed_es.py` per the snippet. Use the existing `cluster_repo.get_active_cluster_by_name` to resolve the cluster URL — do NOT hardcode `http://elasticsearch:9200`.
2. Add the `make seed-es` target to `Makefile`. Update `.PHONY` line.
3. Write the integration test at `backend/tests/integration/test_seed_es.py`. Use the existing `db_session` fixture; pre-register a `local-es` row pointing at the test ES container; run `seed_es.main()`; assert `GET local-es/products/_count` == 1000; re-run; assert still 1000.
4. **Operator-path verification:** run `make up && make migrate && make seed-clusters && make seed-es` end-to-end; verify `curl http://localhost:9200/products/_count` returns 1000.

**Definition of Done**
- [ ] `make seed-es` succeeds end-to-end against `make up` stack; second run is a clean DELETE+recreate (no doc count drift).
- [ ] `make test-integration` includes `test_seed_es.py` and passes.
- [ ] `Makefile` `.PHONY` line updated.

---

### Story 2.2 — `ui/Dockerfile` (Node 20 + pnpm 9, multi-stage, NEXT_PUBLIC_API_BASE_URL build arg)

**Outcome:** `ui/Dockerfile` builds the Next.js app to a small runtime image. The `NEXT_PUBLIC_API_BASE_URL` is accepted as a Docker `ARG` at build time and baked into the client bundle by `pnpm build` — Next.js bakes `NEXT_PUBLIC_*` at build time, NOT runtime, so a Compose `environment:` var would be a no-op (per spec FR-3 + decision log 2026-05-12 M3).

**New files**

| File | Purpose |
|---|---|
| `ui/Dockerfile` | Multi-stage: `deps` (install pnpm + lockfile-frozen deps) → `builder` (accepts `NEXT_PUBLIC_API_BASE_URL` ARG, runs `pnpm build`) → `runner` (minimal Node 20 image, copies `.next/standalone` + `.next/static` + `public/`). |
| `ui/.dockerignore` | Excludes `node_modules`, `.next`, `.turbo`, test artifacts. Keeps the build context small. |

**Modified files**

| File | Change |
|---|---|
| `ui/next.config.mjs` | Add `output: 'standalone'` to the config object. Required for the runner stage's `node server.js` invocation; current config (verified 2026-05-12) does NOT set it. |

**Key interface**

```dockerfile
# ui/Dockerfile
# syntax=docker/dockerfile:1.7
# Multi-stage: deps → builder → runner. NEXT_PUBLIC_API_BASE_URL must be passed
# as a build arg because Next.js bakes NEXT_PUBLIC_* into the client bundle at
# `pnpm build`. A Compose `environment:` var would have NO effect on the built
# bundle — see chore_tutorial_polish §3 + decision log 2026-05-12 M3.

FROM node:20-bookworm-slim AS deps
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9 --activate
COPY pnpm-lock.yaml package.json ./
RUN pnpm install --frozen-lockfile

FROM node:20-bookworm-slim AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9 --activate
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN pnpm build

FROM node:20-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
RUN groupadd -r relyloop && useradd -r -g relyloop relyloop
COPY --from=builder --chown=relyloop:relyloop /app/.next/standalone ./
COPY --from=builder --chown=relyloop:relyloop /app/.next/static ./.next/static
COPY --from=builder --chown=relyloop:relyloop /app/public ./public
USER relyloop
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"
CMD ["node", "server.js"]
```

**Tasks**
1. Author `ui/Dockerfile` per the snippet. Verify `next.config.{js,mjs,ts}` has `output: 'standalone'` set; if not, add it (required for the runner stage's `node server.js` invocation).
2. Author `ui/.dockerignore`: exclude `node_modules`, `.next`, `.turbo`, `coverage`, `tests/e2e/playwright-report`, `*.log`.
3. Build the image locally: `docker build -t relyloop/ui:dev --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 ./ui`. Verify final image size is <500MB (Next.js standalone target should land ~250MB).
4. Run the image standalone: `docker run --rm -p 3000:3000 relyloop/ui:dev`; curl `http://localhost:3000/` returns 200 with `<html` in the body.
5. Verify the build-arg baked correctly: `docker run --rm relyloop/ui:dev grep -r "http://localhost:8000" /app/.next | head -3` returns at least one match in the client bundle (proves the URL is in the JS, not just an env var).

**Definition of Done**
- [ ] `docker build -t relyloop/ui:dev --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 ./ui` succeeds.
- [ ] `docker run` of the resulting image returns 200 on `GET /`.
- [ ] Final image <500MB.
- [ ] `next.config` has `output: 'standalone'` (added if not present).
- [ ] Hand-verified that the build-arg is baked into the client bundle.

---

### Story 2.3 — `docker-compose.yml` `ui` service + `make up` includes UI

**Outcome:** `docker-compose.yml` gains a `ui` service that auto-builds via `build: { context: ./ui, args: { ... } }` on first `make up` (no pre-built image needed locally), depends on `api`, and binds to `127.0.0.1:3000`. Existing `make up` workflow includes the new service with no Makefile changes (it's in the compose file).

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `docker-compose.yml` | Add a new `ui` service block after the `worker` service (around line 92). Pattern matches the existing `api` service at lines 42–66: `image: relyloop/ui:${RELYLOOP_GIT_SHA:-dev}` AND `build: { context: ./ui, args: { NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000" } }`. `depends_on: { api: { condition: service_healthy } }`. `ports: ["127.0.0.1:3000:3000"]`. Healthcheck mirrors the Dockerfile HEALTHCHECK. |

**Key snippet**

```yaml
# docker-compose.yml — appended after the `worker:` block

  ui:
    image: relyloop/ui:${RELYLOOP_GIT_SHA:-dev}
    build:
      context: ./ui
      args:
        # NEXT_PUBLIC_API_BASE_URL is build-time (Next.js bakes NEXT_PUBLIC_*
        # into the client bundle at `pnpm build`). Compose `environment:`
        # would have no effect — see chore_tutorial_polish §3.
        NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000"
    container_name: relyloop-ui-1
    restart: unless-stopped
    depends_on:
      api:
        condition: service_healthy
    ports:
      - "127.0.0.1:3000:3000"
    healthcheck:
      test: ["CMD-SHELL", "node -e \"require('http').get('http://localhost:3000/', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))\""]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 30s
```

**Tasks**
1. Append the `ui` service block to `docker-compose.yml` immediately after the `worker:` service. Match the api service's `restart`, `container_name` naming convention.
2. **Operator-path verification:**
   - `make down && make up` from a fresh checkout (no pre-built `relyloop/ui:dev` image locally).
   - Watch `docker compose ps ui` go from `Created` → `Starting` → `Up (healthy)`.
   - `curl -fsS http://127.0.0.1:3000/` returns 200 + `<html` in the body.
   - Open `http://localhost:3000/` in a browser; the home page renders; click "Studies" — the page loads (proves the baked `NEXT_PUBLIC_API_BASE_URL` resolves to the api container).
3. Update `docker-compose.yml`'s top header comment if it enumerates services, to include `ui`.

**Definition of Done**
- [ ] `make up` brings up 7 containers (postgres + redis + es + opensearch + api + worker + ui) all healthy.
- [ ] `docker compose ps ui` reports `(healthy)` within 90s of cold start.
- [ ] `curl http://127.0.0.1:3000/` returns 200.
- [ ] Browser smoke: home page renders, navigation works, `/clusters` shows the registered clusters.
- [ ] `make down && make up` cleanly recycles the UI container.

---

## Epic 3 — Smoke-test CI gate

### Story 3.1 — `backend/tests/smoke/test_tutorial_path.py` (orchestrator script)

**Outcome:** A Python script that exercises an end-to-end smoke against the running stack via direct API calls. Asserts the doc-id alignment guard (at least one trial has `primary_metric > 0`) AND that the digest is generated with a non-empty narrative. Designed to run inside the CI smoke job (Story 3.2) AND locally via `pytest backend/tests/smoke/test_tutorial_path.py`.

**Departure from spec FR-4 wording (resolves GPT-5.5 cycle-1 finding A4):** the spec said the smoke "kicks off a 10-trial study via the chat-agent's `create_study` tool with confirmation." Driving the chat-agent SSE stream from a smoke test would either need a deterministic LLM mock (defeats the smoke gate's purpose) or a real LLM with a brittle confirmation parser. Pragmatic resolution: the smoke calls `POST /api/v1/studies` directly. The chat-agent path is exercised by (a) `feat_chat_agent`'s integration tests already in CI and (b) the manual fresh-VM walkthrough logged per Story 4.3 release-checklist (covers spec AC-1). Spec FR-4 wording is patched in this same PR to match.

**Smoke + tutorial use the same path (resolves GPT-5.5 cycle-1 finding B7 + cycle-2 finding A3):** both bulk-add 5 queries (subset of CSV), call `POST /api/v1/judgments/generate` against `local-es`, poll until `judgment_list.status='complete'` (~30s, ~$0.01 with `gpt-4o-mini`), then run a 10-trial study. The originally-planned pre-baked `samples/judgments.json` import path was cut from scope per spec §19 Decision log 2026-05-12 — it would have required either extending `BulkQueryItem` with an `id` field OR adding `GET /api/v1/query-sets/{id}/queries`, neither justified by the ~$0.01 saving. Smoke + tutorial sharing one path also means smoke regressions = tutorial regressions; nothing slips through a degraded variant.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/smoke/__init__.py` | Test package marker. |
| `backend/tests/smoke/conftest.py` | One fixture: `api_base_url` reads `RELYLOOP_API_BASE` env var, defaults to `http://127.0.0.1:8000`. |
| `backend/tests/smoke/test_tutorial_path.py` | One pytest function `test_tutorial_completes_with_metric_and_digest` that orchestrates the API calls + asserts. |

**Path note (Pass 2 finding):** `pyproject.toml [tool.pytest.ini_options] testpaths = ["backend/tests"]` — smoke tests must live UNDER that path so local `pytest` discovers them. Repo-root `tests/` would be skipped silently.

**Modified files**

| File | Change |
|---|---|
| `pyproject.toml` | Add a `[tool.pytest.ini_options].markers` entry `smoke: end-to-end smoke against a running stack; not part of the default test layer` (mirrors the existing `integration` marker). |

**Key interface**

```python
# backend/tests/smoke/test_tutorial_path.py
"""Smoke test orchestrating tutorial Steps 5–8 against a running stack.

Designed for CI (Story 3.2) but also runs locally against `make up`. The test:
  1. Creates a query set + bulk-adds 5 queries (subset of samples/queries.csv).
  2. Calls POST /api/v1/judgments/generate (LLM-required) and polls until
     judgment_list.status='complete' (~30s, ~$0.01 with gpt-4o-mini).
  3. Creates a query template from samples/templates/product_search.j2.
  4. Creates a 10-trial study; polls until status='completed' (max 5 min).
  5. Asserts at least one trial has primary_metric > 0 (the doc-id alignment
     guard — proves judgments + index intersect).
  6. Asserts the digest is generated AND its narrative field is non-empty
     (the LLM-required path is fully exercised).

Skipped if RELYLOOP_API_BASE doesn't return 200 on /healthz within 10s.
This is the same path the operator tutorial walks (per spec §3 + Story 4.1)
— smoke + tutorial share one operator path, no degraded variants.
"""

from __future__ import annotations

import csv
import os
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.smoke

# From backend/tests/smoke/test_tutorial_path.py: parents[3] = repo root.
# (parents[0]=smoke, parents[1]=tests, parents[2]=backend, parents[3]=repo.)
SAMPLES = Path(__file__).resolve().parents[3] / "samples"
SMOKE_QUERY_COUNT = 5  # subset of the 50-query CSV — keeps cost ~$0.01


@pytest.fixture
def api_base_url() -> str:
    return os.environ.get("RELYLOOP_API_BASE", "http://127.0.0.1:8000")


def _wait_healthy(client: httpx.Client, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = client.get("/healthz")
            if r.status_code == 200 and r.json().get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(0.5)
    pytest.skip("API not healthy within 10s")


def test_smoke_generation_and_study_with_digest(api_base_url: str) -> None:
    with httpx.Client(base_url=api_base_url, timeout=30.0) as c:
        _wait_healthy(c)

        # Resolve local-es by name explicitly. seed-clusters registers BOTH
        # local-es and local-opensearch; only local-es has the seeded `products`
        # index, so the smoke must pin local-es regardless of return order.
        # (Resolves GPT-5.5 cycle-2 finding B4.)
        clusters = c.get("/api/v1/clusters", params={"limit": 200}).json()["data"]
        matching = [x for x in clusters if x["name"] == "local-es"]
        assert len(matching) == 1, f"expected exactly one local-es cluster, got {matching!r}"
        cluster_id = matching[0]["id"]

        # 1. Create query set + bulk-add a subset of queries.
        qs = c.post("/api/v1/query-sets", json={
            "name": "smoke-tutorial-queries",
            "cluster_id": cluster_id,
            "description": "smoke test fixture",
        }).json()
        with (SAMPLES / "queries.csv").open() as fh:
            all_queries = [{"query_text": row["query_text"]} for row in csv.DictReader(fh)]
        c.post(
            f"/api/v1/query-sets/{qs['id']}/queries",
            json={"queries": all_queries[:SMOKE_QUERY_COUNT]},
        )

        # 2. Generate judgments via LLM (requires OPENAI_API_KEY in CI).
        jg_resp = c.post("/api/v1/judgments/generate", json={
            "name": "smoke-tutorial-judgments",
            "query_set_id": qs["id"],
            "cluster_id": cluster_id,
            "target": "products",
            "current_template_id": _create_smoke_template(c),
            "rubric": "Rate 0-3 by relevance to the query.",
        })
        assert jg_resp.status_code == 202, (
            f"judgment generation rejected: {jg_resp.status_code} {jg_resp.text[:300]} — "
            f"smoke job requires OPENAI_API_KEY_TEST"
        )
        jl_id = jg_resp.json()["judgment_list_id"]

        # Poll for judgment-list completion (~30s with gpt-4o-mini).
        deadline = time.time() + 120
        while time.time() < deadline:
            jl = c.get(f"/api/v1/judgment-lists/{jl_id}").json()
            if jl["status"] == "complete":
                break
            if jl["status"] in ("failed", "partial_llm_failure"):
                pytest.fail(f"judgment generation terminal: {jl['status']} {jl.get('failed_reason')}")
            time.sleep(3)
        else:
            pytest.fail("judgment generation did not complete within 120s")

        # 3. Reuse the smoke template + 4. Create a 10-trial study.
        study = c.post("/api/v1/studies", json={
            "name": "smoke-tutorial-study",
            "cluster_id": cluster_id,
            "target": "products",
            "template_id": jl["current_template_id"],
            "query_set_id": qs["id"],
            "judgment_list_id": jl_id,
            "search_space": {"params": {
                "field_boosts.title": {"type": "float", "low": 0.5, "high": 5.0},
                "field_boosts.description": {"type": "float", "low": 0.5, "high": 5.0},
            }},
            "objective": {"metric": "ndcg", "k": 10},
            "config": {"max_trials": 10},
        }).json()
        deadline = time.time() + 5 * 60
        while time.time() < deadline:
            row = c.get(f"/api/v1/studies/{study['id']}").json()
            if row["status"] == "completed":
                break
            if row["status"] in ("failed", "cancelled"):
                pytest.fail(f"study terminated unexpectedly: {row['status']} reason={row.get('failed_reason')}")
            time.sleep(5)
        else:
            pytest.fail("study did not complete within 5 min")

        # Assertion — doc-id alignment guard. Even with LLM-generated judgments,
        # an unaligned products/queries dataset would still produce primary_metric=0.
        trials = c.get(f"/api/v1/studies/{study['id']}/trials", params={"limit": 50}).json()
        winners = [t for t in trials["data"] if (t.get("primary_metric") or 0) > 0]
        assert winners, (
            f"smoke test misaligned: study completed but no trial has primary_metric > 0; "
            f"check that samples/products.json was seeded into 'products' index AND that "
            f"the LLM judged docs that exist in the seeded index"
        )

        # Digest assertion (LLM-required path) — poll briefly because the digest
        # worker runs after `complete_study` enqueues it. Strengthen beyond
        # status_code==200 to verify the LLM actually filled in the narrative.
        deadline = time.time() + 90
        narrative = ""
        while time.time() < deadline:
            digest = c.get(f"/api/v1/studies/{study['id']}/digest")
            if digest.status_code == 200:
                narrative = (digest.json().get("narrative") or "").strip()
                if narrative:
                    break
            time.sleep(3)
        assert narrative, (
            f"digest narrative empty after 90s — smoke job requires OPENAI_API_KEY_TEST "
            f"AND the digest worker must complete an LLM call. Last response: "
            f"{digest.status_code} {digest.text[:200]}"
        )


def _create_smoke_template(c: httpx.Client) -> str:
    """Helper — creates the smoke-product-search template if not present, returns id."""
    template_body = (SAMPLES / "templates" / "product_search.j2").read_text()
    tmpl = c.post("/api/v1/query-templates", json={
        "name": f"smoke-product-search-{int(time.time())}",
        "engine_type": "elasticsearch",
        "body": template_body,
        "declared_params": {
            "field_boosts.title": "float",
            "field_boosts.description": "float",
            "field_boosts.bullet_points": "float",
            "tie_breaker": "float",
            "fuzziness": "string",
        },
    }).json()
    return tmpl["id"]
```

**Tasks**
1. Author `backend/tests/smoke/test_tutorial_path.py` per the snippet.
2. Author `backend/tests/smoke/conftest.py` with the `api_base_url` fixture.
3. Add the `smoke` pytest marker to `pyproject.toml` (mirrors the existing `integration` marker).
4. Local verification: `make up && make migrate && make seed-clusters && make seed-es`; ensure `OPENAI_API_KEY_FILE` is populated; run `pytest backend/tests/smoke/test_tutorial_path.py -v`. Test should complete in <5 min and exit 0.

**Definition of Done**
- [ ] `pytest backend/tests/smoke/test_tutorial_path.py` runs end-to-end against `make up` stack and passes.
- [ ] Test correctly skips (not fails) when API not reachable on `/healthz`.
- [ ] When `samples/products.json` is deliberately seeded as an empty array (zero docs), the test fails with the `primary_metric > 0` alignment-guard assertion — proves the runtime guard fires when judgments + index don't intersect.
- [ ] When `OPENAI_API_KEY_FILE` is empty, the test fails with the digest-narrative assertion (judgment generation rejects with `OPENAI_NOT_CONFIGURED`, OR digest narrative remains empty) — proves the LLM path is required end-to-end.
- [ ] When `seed-clusters` is skipped, the test fails with the `expected exactly one local-es cluster` assertion — proves the cluster-name pin works.

---

### Story 3.2 — `.github/workflows/pr.yml` `smoke-test` job

**Outcome:** A new `smoke-test` job runs on every PR in parallel with the existing backend/frontend/buildx jobs. Consumes the `OPENAI_API_KEY_TEST` GitHub Action secret; orchestrates `make up` + `make migrate` + `make seed-clusters` + `make seed-es` (clusters BEFORE es because seed_es.py reads `cluster.base_url`) + `pytest backend/tests/smoke/test_tutorial_path.py` + UI curl check. Uploads `docker compose logs` on failure; tears down with `FORCE=1 make reset`. Total wall-clock target: <15 min.

**Manual prerequisite:** Maintainer adds the `OPENAI_API_KEY_TEST` repo secret (Settings → Secrets and variables → Actions → New repository secret). Cost ceiling: ~$0.05 per smoke run.

**New files** — none (test file ships in Story 3.1).

**Modified files**

| File | Change |
|---|---|
| `.github/workflows/pr.yml` | New `smoke-test` job appended after the existing `frontend` job. ~80 lines. |

**Key snippet**

```yaml
# .github/workflows/pr.yml — appended after the `frontend` job

  smoke-test:
    name: smoke (operator-path tutorial flow)
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v6

      # Python + uv setup so `uv run pytest` works on the smoke runner
      # (the smoke job runs in parallel with the backend job and doesn't
      # share its venv) — per GPT-5.5 cycle-1 finding B7.
      - name: Install uv
        uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version-file: "pyproject.toml"
      - name: Install project deps (frozen)
        run: uv sync --frozen

      - name: Write OPENAI_API_KEY secret to mounted file
        run: |
          mkdir -p ./secrets
          echo "${{ secrets.OPENAI_API_KEY_TEST }}" > ./secrets/openai_key
          chmod 600 ./secrets/openai_key
        env:
          OPENAI_API_KEY_TEST: ${{ secrets.OPENAI_API_KEY_TEST }}

      - name: Sanity-check OPENAI_API_KEY_TEST is populated
        run: |
          if [ ! -s ./secrets/openai_key ]; then
            echo "::error::OPENAI_API_KEY_TEST secret is empty — smoke gate requires it (per chore_tutorial_polish §3 + decision log M5)"
            exit 1
          fi

      - name: Bring up the stack
        run: make up

      - name: Wait for /healthz
        run: |
          for i in {1..18}; do
            if curl -fsS http://127.0.0.1:8000/healthz | jq -e '.status == "ok"' > /dev/null; then
              echo "API healthy after ${i}x5s"
              exit 0
            fi
            sleep 5
          done
          echo "::error::API not healthy within 90s"
          curl -s http://127.0.0.1:8000/healthz || true
          exit 1

      - name: Apply migrations
        run: make migrate

      # IMPORTANT order: seed-clusters BEFORE seed-es. seed_es.py reads
      # cluster.base_url via cluster_repo.get_active_cluster_by_name("local-es")
      # — so the cluster row must exist first. (Per GPT-5.5 cycle-1 finding A1.)
      - name: Seed clusters
        run: make seed-clusters

      - name: Seed sample ES index
        run: make seed-es

      - name: Run smoke test (LLM judgment generation + study + alignment guard + digest)
        run: |
          uv run pytest backend/tests/smoke/test_tutorial_path.py -v --tb=short

      - name: Verify UI container reachable
        run: |
          curl -fsS http://127.0.0.1:3000/ | grep -qi "<html" \
            || { echo "::error::UI container did not render Next.js shell"; exit 1; }

      - name: Collect docker compose logs on failure
        if: failure()
        run: |
          docker compose logs --no-color api worker postgres redis elasticsearch ui > smoke-logs.txt 2>&1 || true
          curl -s http://127.0.0.1:8000/healthz | tail -50 >> smoke-logs.txt 2>&1 || true

      - name: Upload failure diagnostics
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: smoke-logs
          path: smoke-logs.txt
          retention-days: 14

      - name: Teardown
        if: always()
        run: FORCE=1 make reset
```

**Tasks**
1. Read `.github/workflows/pr.yml`'s existing job structure (env block, runner, secret-mount pattern). Copy the conventions (e.g., `actions/checkout@v6`, `permissions: contents: read`).
2. Append the `smoke-test` job per the snippet. Verify yaml indentation against the existing jobs.
3. Locally validate the workflow file: `actionlint .github/workflows/pr.yml` (if installed) OR open the file in VS Code with the GitHub Actions extension to lint.
4. **Manual prereq capture:** add a one-line note to the PR description ("Maintainer must add `OPENAI_API_KEY_TEST` repo secret before this PR can merge — smoke job will fail-fast otherwise").
5. **Forced-failure dry-run** (covers spec §13 operability NFR): on a throwaway branch, deliberately empty `samples/products.json` to `[]` (so the smoke's `primary_metric > 0` guard fails); push; verify the smoke job fails AND the `smoke-logs` artifact uploads + contains `docker compose logs` for all 6 services. Revert.

**Definition of Done**
- [ ] `smoke-test` job appears in the PR's Actions tab and runs on every push.
- [ ] Job fails fast (in <30s) if `OPENAI_API_KEY_TEST` is missing.
- [ ] Job completes in <15 min on a warm cache; first run may exceed (cold image pull).
- [ ] `if: failure()` artifact upload validated via the throwaway dry-run.
- [ ] `if: always()` teardown leaves no stuck containers (verified by checking `docker compose ps` after a deliberate failure run).

---

## Epic 4 — Documentation + release

### Story 4.1 — `docs/08_guides/tutorial-first-study.md` (the worked tutorial)

**Outcome:** The canonical operator tutorial. 10 steps per spec §3 + spec FR-1. Each step has command(s), expected output, troubleshooting hint. Single LLM-required path (hosted OpenAI key OR a tool-capable local LLM per Step 0); no degraded variants. Targets <30 min completion on a fresh 16GB Ubuntu 24.04 VM.

**New files**

| File | Purpose |
|---|---|
| `docs/08_guides/tutorial-first-study.md` | The tutorial doc. |
| `docs/08_guides/tutorial-screenshots/` | Directory for the 5–8 screenshots embedded in the tutorial (cluster registration, query-set creation, study running, digest, proposal Open PR). PNG, ≤500KB each, descriptive filenames. |

**Modified files**

| File | Change |
|---|---|
| `docs/08_guides/README.md` | Replace the stub content (currently "Use this section for tutorials...") with an index pointing at `tutorial-first-study.md` plus a placeholder for future guides. |

**Tasks**
1. Author `tutorial-first-study.md`. Required structure:
   - **Title + 1-paragraph intro** ("In this tutorial you will...").
   - **Step 0 — Prerequisites:** Docker (+ `docker compose` v2). One of (OpenAI API key | local LLM via Ollama / LM Studio / vLLM / TGI per [`llm-orchestration.md` §"OpenAI-compatible endpoints"](../01_architecture/llm-orchestration.md)). Optional: GitHub PAT for the apply-PR step. **Local-LLM path:** how to set `OPENAI_BASE_URL` + `OPENAI_MODEL` in `.env` before `make up`. Link to the "tested model matrix" in the llm-orchestration doc so operators know which local models support tool dispatch (chat agent) + structured output (judgment generation).
   - **Steps 1–10** per spec §3. Each step has a command block, expected output (text snippet OR screenshot reference like `![screenshot](tutorial-screenshots/01-cluster-registered.png)`), and a "If something went wrong:" troubleshooting paragraph.
   - **Local-LLM path callout** at Step 0 (NOT a stop point — both LLM paths are first-class). Document `OPENAI_BASE_URL` + `OPENAI_MODEL` configuration with a link to `llm-orchestration.md` §"OpenAI-compatible endpoints" for the tested-model matrix.
   - **Closing section** linking to: `state.md` (what's next), `mvp1-user-stories.md` (full feature list), umbrella spec, GitHub Discussions for feedback.
2. Capture the 5–8 referenced screenshots from a local `make up` run. Optimize PNGs (e.g., `pngquant`) so each is ≤500KB.
3. Update `docs/08_guides/README.md` to link the tutorial.

**Definition of Done**
- [ ] `tutorial-first-study.md` exists with all 10 steps + Step 0 + closing section.
- [ ] All 10 steps have command, expected output, troubleshooting paragraph.
- [ ] No-LLM stop point callout box present at Step 9.
- [ ] Screenshots embedded with relative paths; total tutorial-screenshots/ size <4MB.
- [ ] `docs/08_guides/README.md` indexes the tutorial.
- [ ] Internal cross-links verified (no 404s in `markdownlint` if installed; otherwise hand-walk).

---

### Story 4.2 — README polish (status, quickstart, value prop, links)

**Outcome:** Root `README.md` per spec FR-5 + AC-4 checklist: status badge updated to "alpha (MVP1, v0.1.0)"; 5-minute quickstart above the fold; 2-3 sentence value prop; links to tutorial + spec + architecture index + CONTRIBUTING; "What's in MVP1 / What's coming" section linking to the canonical release matrix; demo recording link (added in Story 4.6 phase).

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `README.md` | Major rewrite per the AC-4 checklist. ~150 LOC delta. |

**Tasks**
1. Re-write the README's first 3 sections per AC-4. Required content:
   - **Header line:** `> **Status: alpha (MVP1, v0.1.0).** Open-source automated relevance tuning for enterprise search platforms.` (Replaces the current `> **Status: MVP1 in progress (private alpha)...** ...currently soundminds.ai-internal` text.)
   - **2–3 sentence value prop** below the header (current "Open-source automated relevance tuning..." paragraph is close — refine for tightness).
   - **5-minute quickstart** as the second `##` section (above any installation detail). Sequence: `git clone` → `make up` → `make migrate` → `make seed-es` → `make seed-clusters` → open `http://localhost:3000/chat`. With expected `make up` cold-start time noted (~90s).
2. Add a **"What it looks like"** section pointing at the demo recording (placeholder URL until Story 4.6 finalizes — wired in once the recording is uploaded).
3. Add a **"What's in MVP1 / What's coming"** section. Brief sentence + a link to [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](docs/01_architecture/tech-stack.md). DO NOT duplicate the matrix table inline — link to source-of-truth.
4. **Links section** at the bottom: tutorial, umbrella spec, architecture docs index, CONTRIBUTING.md.
5. Verify against spec AC-4 checklist by walking the README top-to-bottom and checking each bullet.

**Definition of Done**
- [ ] Status line reads "Status: alpha (MVP1, v0.1.0)" — no "private alpha" or "in progress" wording.
- [ ] 5-minute quickstart appears within the first 2 `##` sections.
- [ ] 2-3 sentence value prop present.
- [ ] All required links present (tutorial, spec, architecture, CONTRIBUTING).
- [ ] "What's in MVP1 / What's coming" section links to `tech-stack.md` (no inline duplication of the matrix).
- [ ] Demo recording link placeholder noted for Story 4.6 wire-up.

---

### Story 4.3 — `docs/03_runbooks/release-checklist.md` (manual VM test + tag + release procedure)

**Outcome:** A maintainer-facing runbook documenting: (a) the manual fresh-VM tutorial walkthrough on the hosted-OpenAI path (logs timing per AC-1), (b) the manual local-LLM walkthrough (logs separately per AC-5), (c) the tag + Release procedure, (d) the 5-consecutive-green-smoke-runs reliability gate (per spec §13 NFR).

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/release-checklist.md` | Step-by-step maintainer runbook. ~100 LOC. |

**Modified files**

| File | Change |
|---|---|
| `docs/03_runbooks/README.md` | If it lists runbooks, add release-checklist.md to the index. |

**Tasks**
1. Author `release-checklist.md` with the following sections:
   - **Pre-flight:** confirm all 11 prior MVP1 features are merged + this feature's PR is merged.
   - **Smoke reliability gate:** verify ≥5 consecutive green smoke runs on `main` (per spec §13 NFR). `gh run list --workflow=pr.yml --branch=main --limit=20 --json conclusion,name | jq '[.[] | select(.name | startswith("smoke"))] | .[0:5] | map(.conclusion) | all(. == "success")'`.
   - **Manual fresh-VM tutorial run (LLM-required path):** spin up a fresh Ubuntu 24.04 VM (16GB, 4 vCPU). Time the walkthrough. Acceptance: ≤30 min. Log the timing in this runbook below the procedure.
   - **Manual local-LLM walkthrough (AC-5):** unset `OPENAI_API_KEY_FILE` and configure `OPENAI_BASE_URL` + `OPENAI_MODEL` against a local Ollama / LM Studio / vLLM / TGI instance. Walk all 10 steps. Verify the local LLM completes judgment generation + the digest narrative renders. Log outcome (model used, completion time, any quality issues).
   - **80% coverage gate verification:** `gh run view <merge-commit-run-id> --log | grep -E "TOTAL|fail_under"` confirms ≥80% on the merge commit.
   - **Demo recording linked:** verify the README's "What it looks like" section links to a working video (per AC-6).
   - **Tag + Release procedure:** `git tag v0.1.0 <merge-commit-sha>`, `git push origin v0.1.0`, `gh release create v0.1.0 --title "RelyLoop v0.1.0 — MVP1 alpha" --notes-file release-notes-v0.1.0.md`. Notes file template included inline (capabilities, audience, install link, feedback channel).
   - **Post-release:** open a feedback-collection GitHub Discussion; tweet/post on relevant channels.
2. Add to runbooks index if applicable.

**Definition of Done**
- [ ] `release-checklist.md` exists with all 7 sections.
- [ ] Tag + Release procedure includes a copy-paste template for release notes.
- [ ] Smoke reliability gate has a runnable `gh run list ... | jq` one-liner.
- [ ] Manual VM run section has space to log timing for both LLM-required + no-LLM paths.

---

### Story 4.4 — `docs/01_architecture/deployment.md` UI service update

**Outcome:** The Compose-layout section of `deployment.md` reflects the new 7-service topology (was 6: postgres + redis + es + opensearch + api + worker; now adds `ui`). Other sections (secrets, healthchecks, port bindings) updated as needed.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `docs/01_architecture/deployment.md` | Add `ui` to the documented Compose service inventory + the port-binding table + the build/runtime image inventory. ~30 LOC delta. Update line 37 (`relyloop/api:latest` example) to reflect that UI builds from `./ui` context, not a published image. |

**Tasks**
1. Read `deployment.md`'s current "Compose layout" section. Identify where the 6-service topology is documented.
2. Add the `ui` service block (matching the format of the existing api/worker entries): image tag, build context, port binding (`127.0.0.1:3000`), depends_on, healthcheck.
3. Update any "service count" prose (e.g., "6 services" → "7 services").
4. Add a brief note at the top about NEXT_PUBLIC_API_BASE_URL being a build arg, not a runtime env (citing the chore_tutorial_polish decision log entry).
5. Verify the spec's deployment.md cross-links from the spec body still resolve.

**Definition of Done**
- [ ] `ui` documented alongside the other 6 services.
- [ ] Port binding table updated.
- [ ] Build/runtime image inventory includes `ui` with correct context path.
- [ ] No broken anchor links from the spec.

---

### Story 4.5 — `docs/02_product/mvp1-user-stories.md` flips (US-30, US-31, US-32 → Implemented)

**Outcome:** US-30, US-31, US-32 marked `*(Implemented — chore_tutorial_polish)*` per the established convention used by US-13 through US-29.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| `docs/02_product/mvp1-user-stories.md` | Three line-level edits adding the implemented marker prefix. |

**Tasks**
1. For US-30, US-31, US-32: add `*(Implemented — `chore_tutorial_polish`)*` after the bold story title, matching the format used by US-29 at `mvp1-user-stories.md:86`.
2. If a "Stories grouped by feature" section exists, verify the chore_tutorial_polish row reflects all three.

**Definition of Done**
- [ ] All three stories have the implemented marker.
- [ ] Format matches existing implemented stories (US-13 through US-29).

---

### Story 4.6 — Demo recording (manual, blocking)

**Outcome:** A 5–7 minute screencast hosted as YouTube unlisted (or Loom). Captures the tutorial flow per spec FR-7. Linked from the README's "What it looks like" section.

**Manual prerequisite:** Maintainer records the demo. Suggested takes: 1 dry-run + 1 final. Editing software: any (QuickTime Pro, ScreenFlow, or unedited if the dry-run lands). Captions optional. Length: 5–7 min strict (a longer demo undermines the "30 min tutorial" promise).

**New files** — none in repo. Demo asset hosted externally.

**Modified files**

| File | Change |
|---|---|
| `README.md` | Wire the demo URL into the "What it looks like" section placeholder added in Story 4.2. |

**Tasks**
1. (Maintainer offline) Record the 5–7 min demo per the script in spec FR-7: clone, `make up`, `make migrate`, `make seed-es`, register cluster (auto via `make seed-clusters`), create study via chat agent, watch trial table fill in, see digest, click Open PR.
2. Upload as YouTube unlisted (or Loom). Verify the link works in a fresh incognito window.
3. Replace the placeholder URL in the README with the live link.

**Definition of Done**
- [ ] Demo URL resolves to a working video.
- [ ] Video length 5–7 min.
- [ ] Captures all 8 demo beats from spec FR-7.
- [ ] README links the live URL (not the placeholder).

---

### Story 4.7 — `v0.1.0` Git tag + GitHub Release

**Outcome:** A `v0.1.0` annotated Git tag pushed against the merge commit. A GitHub Release published at `https://github.com/SoundMindsAI/relyloop/releases/tag/v0.1.0` with the notes structure from spec FR-8.

**Manual prerequisite:** All preceding stories merged + smoke reliability gate passed (per Story 4.3 release-checklist). Maintainer pushes the tag from a clean local checkout.

**New files**

| File | Purpose |
|---|---|
| `release-notes-v0.1.0.md` | (At repo root, gitignored — not committed.) Maintainer's working draft of the release notes pasted into the GitHub Release form. |

**Modified files** — none.

**Tasks**
1. Verify the smoke reliability gate per Story 4.3 release-checklist.
2. From a clean local checkout on the merge commit: `git tag -a v0.1.0 -m "RelyLoop v0.1.0 — MVP1 alpha"`, `git push origin v0.1.0`.
3. Author release notes in `release-notes-v0.1.0.md` (gitignored). Required sections per spec FR-8:
   - **What's in MVP1** — bulleted capabilities (link to `mvp1-user-stories.md` for the full list).
   - **Audience** — "Technical evaluators / Relevance Engineers / search platform teams considering an open-source query-tuning tool."
   - **How to install** — link to `docs/08_guides/tutorial-first-study.md`. **Explicitly note:** "operators build images locally via `make up` (pre-built GHCR images ship at MVP3 per the release matrix)."
   - **How to provide feedback** — link to GitHub Discussions + Issue templates.
4. `gh release create v0.1.0 --title "RelyLoop v0.1.0 — MVP1 alpha" --notes-file release-notes-v0.1.0.md`.
5. Verify the release renders correctly at `github.com/SoundMindsAI/relyloop/releases/tag/v0.1.0`.

**Definition of Done**
- [ ] `git tag --list v0.1.0` shows the annotated tag.
- [ ] `gh release view v0.1.0` returns the published release with the documented notes structure.
- [ ] Release URL accessible without auth (public alpha).
- [ ] Notes explicitly mention "build images locally" install path (no implication of pre-built images).

---

## 3) Testing workstream (required)

### 3.1 Unit tests

No new unit tests — this feature ships infra + scripts + docs; the smoke test (§3.4) is the unit-of-coverage for the operator path.

### 3.2 Integration tests

| Test file | Story | Coverage |
|---|---|---|
| `backend/tests/integration/test_seed_es.py` | 2.1 | seed_es.py against a live local-es cluster: empty index → 1000 docs after one run; re-run → still 1000 (idempotency) |

### 3.3 Contract tests

None — this feature adds no new APIs.

### 3.4 Smoke / E2E tests

| Test file | Story | Coverage |
|---|---|---|
| `backend/tests/smoke/test_tutorial_path.py` | 3.1 | Operator-path smoke against running stack: pin local-es + create query set + bulk-add 5 queries + LLM judgment generation + create template + 10-trial study + alignment guard (`primary_metric > 0`) + digest narrative non-empty assertion |

### 3.5 Coverage gate verification

The 80% backend coverage gate already lives in `pyproject.toml` `[tool.coverage.report].fail_under = 80`. Story 4.7 release-checklist verifies it fires on the merge commit.

---

## 4) Documentation update workstream (required)

| Doc | Story | Change |
|---|---|---|
| `docs/08_guides/tutorial-first-study.md` | 4.1 | NEW — the worked tutorial. |
| `docs/08_guides/tutorial-screenshots/` | 4.1 | NEW — 5-8 PNG screenshots, ≤500KB each. |
| `docs/08_guides/README.md` | 4.1 | Replace stub with index pointing at the tutorial. |
| `README.md` | 4.2 + 4.6 | Polish per AC-4 checklist; wire demo recording URL. |
| `docs/03_runbooks/release-checklist.md` | 4.3 | NEW — manual VM test + tag + release procedure. |
| `docs/03_runbooks/README.md` | 4.3 | Index update if applicable. |
| `docs/01_architecture/deployment.md` | 4.4 | Add `ui` service to documented Compose layout. |
| `docs/02_product/mvp1-user-stories.md` | 4.5 | US-30 / US-31 / US-32 flipped to Implemented. |
| `samples/LICENSE` | 1.1 | NEW — per-file source + license. |
| `state.md` | post-merge finalization | Add to recent changes; flip active-feature pointer. |
| `CLAUDE.md` | post-merge finalization | Feature-status table flips chore_tutorial_polish to Complete. Runbook table adds release-checklist.md. |

---

## 5) Lean refactor workstream (required)

This feature ships no production code refactors. Two minor consolidations land alongside scope:

- **`Makefile` `.PHONY` line:** Story 2.1 adds `seed-es` to the existing list; no other Makefile cleanup. Defer the long-running discussion of restructuring `Makefile` into per-area files to a future `chore_makefile_split` if the file grows beyond ~250 LOC.
- **`docker-compose.yml` healthcheck consolidation:** Story 2.3 introduces a `node -e ...` inline healthcheck for the UI. The existing api healthcheck uses a similar pattern (`curl localhost:8000/healthz`); both are inline `CMD-SHELL` strings. No extraction warranted — they're 3-line idiomatic Compose constructs.

If the smoke job's pytest assertions outgrow `backend/tests/smoke/test_tutorial_path.py` (e.g., adding multi-template runs, multi-cluster scenarios), refactor into a `tests/smoke/conftest.py`-driven fixture set + multiple test files. NOT in scope here.

---

## 6) Dependencies, risks, and mitigations

| Dependency | Type | Risk | Mitigation |
|---|---|---|---|
| `OPENAI_API_KEY_TEST` GitHub repo secret populated | Hard (Story 3.2) | Smoke fails fast on every PR until the secret is set | Maintainer adds secret as a one-time setup step in Story 3.2 manual-prereq. CI fails with a clear `::error::` message pointing at this. |
| Amazon ESCI dataset stays accessible at `github.com/amazon-science/esci-data` | Soft (Story 1.1) | Dataset URL changes break re-curation reproducibility | We commit the curated subset directly into the repo (not a fetch-on-build URL — per spec §11 edge-flow #3). Original URL is documented in `samples/LICENSE` for traceability. |
| `feat_llm_judgments` worker functional for the smoke + tutorial LLM-generation path | Hard (Stories 3.1, 3.2, 4.1) | If `POST /api/v1/judgments/generate` regresses, the smoke gate fails until fixed | All MVP1 features merged + green CI through `feat_chat_agent`. The worker has integration tests in `backend/tests/integration/test_judgment_generate.py` that catch regressions before this feature is exercised. |
| `SoundMindsAI/relyloop-test-configs` repo accessible | Soft (Story 4.1 tutorial Step 10) | Tutorial Step 10 fails if the test-configs repo is unavailable | Repo is public + maintained by SoundMindsAI per `feat_github_pr_worker` decision. Tutorial documents the read-only path so even an offline operator can complete Steps 1–9 |
| YouTube account / equivalent for demo hosting | Soft (Story 4.6) | If host is unavailable, link is dead | Maintainer chooses a stable host. Loom is the documented backup. |

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Smoke job consistently exceeds 15 min on cold runner | Medium | Blocks PR throughput | Profile early; if image build dominates, push the api+worker images to GHCR ahead of MVP1 (would be a new planned feature `infra_release_publishing` per spec §3 out-of-scope) |
| Runtime alignment failure: LLM-generated judgments produce no positive overlap with the seeded `products` index → AC-9 (`primary_metric > 0`) fires | Medium | Blocks the smoke gate until fixed | Two mitigations: (a) `samples/products.json` curation captures real ESCI products that an `ndcg@10` judge can reason about, so any positive-rated doc in the LLM's first-pass output should surface in the index; (b) smoke `if: failure()` artifact upload includes the judgments + trial responses so a maintainer can diagnose without re-running |
| Demo recording outdated within a week of release | Medium | First impression decays | Defer re-record to MVP2 unless a major UI flow breaks. Recording is a snapshot, not a contract |
| Maintainer time budget for manual stories (1.1, 1.3, 3.2 secret, 4.6, 4.7) | High | Blocks feature shipping | Stories explicitly call out "Manual prerequisite" so /impl-execute escalates rather than silently waiting. Maintainer schedules these in advance |

---

## 7) Sequencing and parallelization

```
Foundation ──────────── Story 1.1 (samples bootstrap)
                              │
Operator scripts ────┬─ Story 2.1 (seed_es.py — depends on 1.1)
                     │
                     ├─ Story 2.2 (ui/Dockerfile — independent)
                     │       │
                     │       └─ Story 2.3 (compose ui service — depends on 2.2)
                     │
Smoke gate ──────────┼─ Story 3.1 (smoke pytest — depends on 1.x + 2.x)
                     │       │
                     │       └─ Story 3.2 (CI job — depends on 3.1)
                     │
Docs + release ──────┼─ Story 4.1 (tutorial — depends on all 1.x + 2.x for screenshots)
                     ├─ Story 4.2 (README — depends on 4.1 for tutorial link)
                     ├─ Story 4.3 (release-checklist — depends on 3.2 for smoke gate cmd)
                     ├─ Story 4.4 (deployment.md — depends on 2.3)
                     ├─ Story 4.5 (US flips — independent)
                     │
                     └─ Manual blocking gates (post-merge):
                         Story 4.6 (demo) → Story 4.2 wire-up → Story 4.7 (tag + release)
```

**Parallelizable seams:**
- Story 2.2 (ui/Dockerfile) and Story 1.1 (samples) are fully independent.
- Stories 4.4 (deployment.md) and 4.5 (US flips) can run alongside 4.1 (tutorial doc).

**Strictly serial:**
- 2.1 (seed_es.py) after 1.1 (needs samples/products.json schema).
- 2.3 (compose ui service) after 2.2 (references the Dockerfile).
- 3.2 (CI smoke job) after 3.1 (runs the pytest).
- 4.1 (tutorial) after Stories 1.1 + 2.x for screenshots.
- 4.6 (demo recording) after merge (the demo records the merged flow, not a draft).
- 4.7 (tag + release) after 4.6 (release notes link the demo).

---

## 8) Rollout and cutover plan

- **Feature flags:** None.
- **Migration/backfill:** N/A (no schema changes).
- **Operational readiness gates** (per spec §16 + §13 NFR):
  1. Smoke gate passes on the merge commit.
  2. ≥5 consecutive green smoke runs on `main` (per spec §13 reliability NFR; verified per Story 4.3 procedure).
  3. 80% coverage gate green (per AC-3).
  4. Manual fresh-VM tutorial run logged in release-checklist (LLM-required path ≤30 min — per AC-1).
  5. Manual local-LLM walkthrough logged in release-checklist (per AC-5).
  6. Demo recording uploaded + linked from README (per AC-6).
  7. Release-checklist completion sign-off.
- **Release gate:** Maintainer pushes `v0.1.0` tag; GitHub Release published with notes (per AC-7).
- **Post-release:** Open feedback Discussion; share via design-partner channels.
- **Rollback:** N/A — this is a docs/infra release, not a state-mutating one. Operators continue using `main` if they prefer; the tag is a snapshot, not a forced upgrade.

---

## 9) Execution tracker

### Current sprint

- [x] **Story 1.1** — `samples/` bootstrap (products + queries + template + LICENSE)
- [x] **Story 2.1** — `scripts/seed_es.py` + `make seed-es` + integration test
- [x] **Story 2.2** — `ui/Dockerfile` (Node **24** LTS + pnpm 9 + multi-stage + build arg)
- [x] **Story 2.3** — `docker-compose.yml` `ui` service + verification
- [x] **Story 3.1** — `backend/tests/smoke/test_tutorial_path.py`
- [x] **Story 3.2** — `.github/workflows/pr.yml` `smoke-test` job (operator added `OPENAI_API_KEY_TEST` repo secret 2026-05-12)
- [x] **Story 4.1** — `docs/08_guides/tutorial-first-study.md` + screenshots + guides README
- [x] **Story 4.2** — README polish (status, quickstart, value prop, links)
- [x] **Story 4.3** — `docs/03_runbooks/release-checklist.md`
- [x] **Story 4.4** — `docs/01_architecture/deployment.md` UI service update
- [x] **Story 4.5** — `mvp1-user-stories.md` US-30 / US-31 / US-32 flips
- [ ] **Story 4.6** — Demo recording (5–7 min) **[manual: blocking — maintainer post-merge]**
- [ ] **Story 4.7** — `v0.1.0` Git tag + GitHub Release **[manual: blocking; depends on Story 4.3 release-checklist completion]**

### Blocked items
- 4.6 + 4.7 are blocked on the feature PR being merged (tag is against merge commit; demo records the merged tutorial flow).

### Done this sprint
- (will be populated as stories complete)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables)
- [ ] No new endpoints introduced (this is a no-API feature; any router-touching diff is a finding)
- [ ] No schema changes (no `migrations/versions/000X_*.py` added; any migration is a finding)
- [ ] Required tests added/updated for the touched layer:
  - [ ] `make test-unit` — no new unit tests; ensure existing suite still passes
  - [ ] `make test-integration` (Story 2.1)
  - [ ] `pytest backend/tests/smoke/test_tutorial_path.py -v` (Story 3.1, locally with `make up`)
- [ ] `make fmt && make lint && make typecheck` green
- [ ] Operator-path verification (CLAUDE.md rule):
  - [ ] Story 2.1 — `make seed-es` end-to-end
  - [ ] Story 2.3 — `make up` brings UI healthy + browser smoke
  - [ ] Story 3.2 — push to a throwaway branch + watch the smoke-test job run end-to-end (forced-failure dry-run for the artifact upload branch)
- [ ] Related docs updated as part of the post-merge finalization handled by `/impl-execute` Step 8 (state.md change-log + CLAUDE.md feature-status table flip + folder move from `planned_features/` → `implemented_features/`). No separate story owns this — it runs automatically after the feature PR merges.
- [ ] Manual prerequisites called out at the top of the story are confirmed satisfied before marking [x]

---

## 11) Plan consistency review

### Spec ↔ plan endpoint count

Spec §8 declares `N/A — no new APIs`. Plan ships zero endpoints. ✓

### Spec ↔ plan error code coverage

Spec §8.4 declares `N/A`. Plan ships zero error codes. ✓

### Spec ↔ plan FR coverage

| FR | Story |
|---|---|
| FR-1 (tutorial) | Story 4.1 |
| FR-2 (samples + seed script) | Stories 1.1, 2.1 |
| FR-3 (UI containerization) | Stories 2.2, 2.3 |
| FR-4 (smoke CI job) | Stories 3.1, 3.2 |
| FR-5 (README polish) | Story 4.2 |
| FR-6 (demo recording) | Story 4.6 |
| FR-7 (tag + release) | Story 4.7 |

✓ All 7 FRs covered.

### Spec ↔ plan AC coverage

| AC | Story |
|---|---|
| AC-1 (≤30 min fresh-VM tutorial, hosted-OpenAI) | Stories 4.1 (writes) + 4.3 (logs timing) |
| AC-2 (smoke passes in CI in ≤15 min) | Story 3.2 |
| AC-3 (80% backend coverage gate) | Story 4.7 (release-checklist verification) |
| AC-4 (README content checklist) | Story 4.2 |
| AC-5 (local-LLM tutorial path verified) | Stories 4.1 (Step 0 documents path) + 4.3 (manual local-LLM walkthrough logged) |
| AC-6 (demo recording linked) | Stories 4.6 + 4.2 |
| AC-7 (v0.1.0 GitHub Release) | Story 4.7 |
| AC-8 (UI container reachable from smoke) | Story 3.2 (curl) |
| AC-9 (smoke alignment guard fires on positive trial) | Story 3.1 (`primary_metric > 0` assertion) |

✓ All 9 ACs covered.

### Story internal consistency

- Each story's New files + Modified files tables reference paths that either exist (verified by `ls`/`glob`) or are explicitly marked as new.
- No file is claimed by multiple stories (`Makefile` only modified by 2.1; `docker-compose.yml` only by 2.3; `pr.yml` only by 3.2; `ui/next.config.mjs` only by 2.2).
- Test files traceable to stories: 2 test files in §3 (`test_seed_es.py` in 2.1; `test_tutorial_path.py` in 3.1) ↔ both referenced in their story DoDs.

### Frontend UI Guidance section

N/A — this feature ships zero `ui/src/` changes. No tab/page/component additions, no state changes, no new dropdowns, no enum-shaped option lists. The UI containerization (Stories 2.2, 2.3) is purely infrastructure (Dockerfile + Compose service); the UI itself ships unchanged from `feat_proposals_ui` / `feat_chat_agent`.

### Open questions

None — all resolved per spec §19 Decision log + the 2026-05-12 Review & Patch decisions.

---

## 12) Definition of plan done

- [ ] Plan covers every FR + AC from the spec (verified by §11 traceability).
- [ ] Every story has a clear DoD with measurable assertions.
- [ ] Manual prerequisites flagged at the top of every applicable story.
- [ ] Operator-path verification hooks called out for Stories 2.1, 2.3, 3.2.
- [ ] No story introduces new APIs, new schema, or new `ui/src/` paths.
- [ ] Spec is unchanged by this plan (the spec was the contract; the plan is the execution).
