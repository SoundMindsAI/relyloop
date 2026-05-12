# Feature Specification — chore_tutorial_polish

**Date:** 2026-05-09 (revised 2026-05-12 after spec-gen Review & Patch)
**Status:** Draft (revised — pipeline-ready)
**Owners:** Maintainer (writes tutorial + records demo + cuts release); peer reviewer for the smoke-test gate.
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-30, US-31, US-32 (current count is 32; US-32 added after this spec was first authored)
- [docs/00_overview/product/relevance-copilot-spec.md §27](../../../00_overview/product/relevance-copilot-spec.md) — MVP1 release definition
- [docs/01_architecture/deployment.md](../../../01_architecture/deployment.md)
- [docs/01_architecture/mvp1-overview.md](../../../01_architecture/mvp1-overview.md)
- Depends on: ALL prior MVP1 features (this is the release-readiness step)

---

## 1) Purpose

- **Problem:** Even with all 11 prior features shipped, the tutorial — the single demo asset for design-partner recruitment — needs to actually work on a fresh laptop in under 30 minutes. Without a deliberate polish pass that validates the end-to-end flow on a clean VM and writes the supporting tutorial doc, MVP1 ships broken for new users.
- **Outcome:** The release tag `v0.1.0` is pushed with: a worked tutorial at `docs/08_guides/tutorial-first-study.md`, sample data (50-query set + pre-baked judgment list + sample ES index of ~1,000 docs), README polish, a containerized UI (`ui` Compose service), 80% backend coverage gate enforced in CI, smoke-test pass on a fresh Ubuntu 24.04 VM, and a 5–7 minute demo screen recording.
- **Non-goal:** No new features. No new endpoints. No schema changes. No image signing (deferred to GA v1 unless cheap). No Helm chart. No production install doc beyond the basic tutorial.

## 2) Current state audit

All 11 prior MVP1 features have shipped (per CLAUDE.md feature status table; `feat_chat_agent` was the last, merged 2026-05-12 via PR #60):
- The full Karpathy loop works end-to-end via the UI; chat agent works.
- `README.md` still says "Status: MVP1 in progress (private alpha) ... currently soundminds.ai-internal" — must be polished per FR-5.
- No tutorial doc at `docs/08_guides/tutorial-first-study.md`. The guides directory is a stub (`docs/08_guides/README.md` is the only file).
- No `samples/` directory in the repo root (the empty path exists; no content) — must be populated.
- `scripts/seed_es.py` does not exist — must be created.
- UI runs via `pnpm dev` (not yet containerized in Compose per [`deployment.md`](../../../01_architecture/deployment.md)). No `ui/Dockerfile` either.
- 80% backend coverage gate is enforced via `[tool.coverage.report].fail_under = 80` in `pyproject.toml` (per `infra_foundation` FR-4); CI runs `uv run pytest --cov=backend --cov-fail-under=80` in `.github/workflows/pr.yml`. No smoke-test job exists.
- No `v0.1.0` tag.
- **Latent regression discovered during `feat_chat_agent` first-run testing:** the Dockerfile didn't `COPY prompts/ /app/prompts/`, silently breaking `feat_llm_judgments` + `feat_digest_proposal` for any operator with `OPENAI_API_KEY` set. Fixed in PR #60 commit `0cb4ad9`. The smoke gate this feature ships will catch the next instance of that class.

## 3) Scope

### In scope

- **Worked tutorial** at `docs/08_guides/tutorial-first-study.md`. The tutorial is dual-path: an LLM-required path (operator has an OpenAI key OR a tool-capable local LLM) and a no-LLM stop point at the digest step. Step list is the canonical operator sequence the smoke test exercises:
  - **Step 0: Prerequisites.** Docker only on the host. One of (OpenAI API key | local LLM via Ollama / LM Studio / vLLM / HuggingFace TGI per [`llm-orchestration.md` §"OpenAI-compatible endpoints"](../../../01_architecture/llm-orchestration.md)). GitHub PAT optional but recommended for the apply step. **Local-LLM alternative:** set `OPENAI_BASE_URL` + `OPENAI_MODEL` in `.env` before `make up` per `deployment.md` §"Local-LLM operator workflow." The tutorial documents both paths side-by-side and links to a "tested model matrix" so operators know which local models support tool dispatch (`feat_chat_agent`) + structured output (`feat_llm_judgments`).
  - **Step 1: Clone + `make up`.** Auto-generates secrets via `scripts/install.sh`, then runs `docker compose up -d` (api + worker + postgres + redis + elasticsearch + opensearch + **ui** containers). Wait until `curl -s http://localhost:8000/healthz | jq .status` returns `"ok"` (typically 60–90s cold).
  - **Step 2: `make migrate`.** Applies the Alembic chain to head (currently `0007_conversations_messages`). Without this, all API calls return 500 with `relation "..." does not exist` — see `bug_dockerfile_missing_prompts/idea.md` for the kind of regression this catches.
  - **Step 3: `make seed-es`.** Wraps `docker compose exec api python -m backend.app.scripts.seed_es` to populate the `products` index from `samples/products.json`. Idempotent — safe to re-run.
  - **Step 4: `make seed-clusters`.** Already exists; registers `local-es` + `local-opensearch` in the `clusters` table. Idempotent. (Or operator can register manually via the UI at `http://localhost:3000/clusters`.)
  - **Step 5: Create a query set from `samples/queries.csv`** (50 hand-curated queries) via the UI at `/query-sets/new` OR `curl -X POST .../api/v1/query-sets` + bulk-add CSV.
  - **Step 6: Import the pre-baked judgments** from `samples/judgments.json` via `POST /api/v1/judgment-lists/import` (per `feat_llm_judgments` Story 3.2 — the tutorial-no-OpenAI path). LLM-required alternative: generate fresh judgments via `POST /api/v1/judgments/generate` (costs ~$0.05 with `gpt-4o-mini`).
  - **Step 7: Create a query template from `samples/templates/product_search.j2`** via the UI at `/templates/new`.
  - **Step 8: Open `/chat`, ask the agent to tune** (e.g., "Tune `product_search v1` against `tutorial_queries` on `local-es:products`, max 10 trials"). Agent proposes `create_study`; operator confirms with "yes" → study queues.
  - **Step 9: Watch the study run at `/studies/{id}` → read the digest at `/studies/{id}#digest`.** **No-LLM stop point:** if `OPENAI_API_KEY_FILE` is empty, the digest worker emits `OPENAI_NOT_CONFIGURED` and the digest section shows a documented placeholder. The tutorial's troubleshooting section explains and recommends adding a key + re-triggering the digest worker.
  - **Step 10: (Optional, requires GitHub PAT) Click "Open PR" on the proposal.** Opens against the public **`SoundMindsAI/relyloop-test-configs`** repo (per `feat_github_pr_worker` Decision log + this spec §5). Operator may fork the repo to demo against their own clone; the default tutorial walk-through uses the public repo read-only.
  - Each step has expected output (screenshots OR JSON snippets) so users can verify they're on track.
- **`samples/` directory** at repo root, all under public licenses (`samples/LICENSE` documents source + license per file):
  - `samples/products.json` — ~1,000 sample products (Amazon ESCI subset, CC-BY-4.0)
  - `samples/queries.csv` — 50 hand-curated queries
  - `samples/judgments.json` — pre-baked judgment list (so first-run users don't pay for OpenAI judgments)
  - `samples/templates/product_search.j2` — Jinja2 template with `multi_match` + `field_boosts` + `tie_breaker` + `fuzziness` as parameters
  - **Doc-id alignment invariant:** every `query_id` in `judgments.json` must reference a row in `queries.csv`, and every `doc_id` in `judgments.json` must reference a product in `products.json`. A `samples/validate.py` script (run in the smoke job and in pre-commit) asserts this — without it the smoke gate would silently pass with `primary_metric=0` on every trial.
  - `scripts/seed_es.py` — populates the local ES container with `samples/products.json`. Designed to run inside the api container (CWD = `/app`); the host invocation goes through `make seed-es`.
- **`ui` Compose service** — containerize the Next.js app:
  - Ship `ui/Dockerfile` (Node 20 + pnpm 9, multi-stage `builder → runner`). The build stage receives `NEXT_PUBLIC_API_BASE_URL` as a Docker `ARG` (default `http://localhost:8000`) and `pnpm build` bakes it into the client bundle. **Do NOT** rely on a Compose `environment:` var — Next.js `NEXT_PUBLIC_*` are build-time, not runtime.
  - Add to `docker-compose.yml`: `image: relyloop/ui:${RELYLOOP_GIT_SHA:-dev}` AND `build: { context: ./ui, args: { NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000" } }` (matching the existing api/worker pattern at `docker-compose.yml:42-44, 92-94`). `depends_on: [api]`. Bind to `127.0.0.1:3000`.
  - Operator changing the API URL (e.g., for a remote backend) re-builds via `docker compose build ui` with `--build-arg NEXT_PUBLIC_API_BASE_URL=https://...`.
  - The `make up` workflow includes the `ui` service automatically (it's in the compose file).
- **README polish**:
  - Replace "Status: MVP1 in progress (private alpha) ... currently soundminds.ai-internal" with "Status: alpha (MVP1, v0.1.0)"
  - 5-minute quickstart at the top (`git clone` → `make up` → `make migrate` → `make seed-es` → open `/chat`)
  - Value-proposition section (2–3 sentences)
  - "What's in MVP1 / what's coming" compact table, sourced from [`tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md) — link out, don't duplicate
  - Links to: tutorial, umbrella spec, architecture index, CONTRIBUTING. (Quepid comparison stub deferred to MVP2 per Decision log.)
- **`pr.yml` extension** — add a `smoke-test` job that runs in parallel with the existing lint/typecheck/test/buildx jobs:
  - Provisions an Ubuntu 24.04 runner (`runs-on: ubuntu-24.04`).
  - Runs `make up`, waits up to 90s for `/healthz` `status == "ok"`.
  - Runs `make migrate` (per Step 2 of the tutorial — without this, the API has no schema).
  - Runs `make seed-es` + `make seed-clusters` (Steps 3 + 4).
  - Runs `tests/smoke/test_tutorial_path.py` which orchestrates Steps 5 + 6 + 7 + 8 (create query set, import judgments, create template, kick off a 10-trial study via the chat-agent's `create_study` tool with confirmation), then waits up to 5 min for completion.
  - Verifies the UI container is reachable: `curl -fsS http://127.0.0.1:3000/ | grep -qi "<html"` (smoke-checks the Next.js shell renders).
  - Asserts at least one trial has `primary_metric is not null AND > 0` (the doc-id alignment guard — proves judgments + index intersect).
  - **LLM path is required for the smoke gate.** The smoke job consumes a GitHub Action secret `OPENAI_API_KEY_TEST` (mounted into `./secrets/openai_key`) so the digest path runs end-to-end and the chat-agent confirmation flow exercises tool dispatch. Asserts the digest is generated. Without this, the smoke would silently rubber-stamp a degraded path that no design-partner would actually run.
  - On step failure: `if: failure()` block runs `docker compose logs --no-color api worker postgres redis elasticsearch ui > smoke-logs.txt && upload-artifact` so failure diagnostics are scoped enough to debug without re-running.
  - Teardown: `if: always()` block runs `FORCE=1 make reset` (the prompt would otherwise block in non-interactive CI per CLAUDE.md).
  - Whole job target: <15 min total (image pull dominates first run).
- **Demo recording** (5–7 min screencast) — record a fresh-laptop run-through; host as YouTube unlisted; link from README.
- **`v0.1.0` Git tag** + GitHub Release with notes summarizing scope + audience + feedback channels.
- **Coverage-gate verification** — `[tool.coverage.report].fail_under = 80` in `pyproject.toml` is the gate (already in place per `infra_foundation` FR-4); CI runs `uv run pytest --cov=backend --cov-fail-under=80` in `pr.yml`. This feature verifies the gate continues to fire on the merge commit.
- **Final issue sweep** — fix any **P0** issue surfaced by the smoke test on a fresh VM. **P0 = blocks the tutorial OR blocks the smoke gate** (e.g., port collision, missing healthcheck retry, confusing error that prevents an operator from completing a step). Non-P0 issues (cosmetic, polish, "would be nice to fix") are captured as `bug_*`, `chore_*`, or `infra_*` idea files per the CLAUDE.md tangential-discoveries protocol — not patched in this feature.

### Out of scope

- **Pre-built published images on GHCR (`ghcr.io/soundmindsai/{api,ui,worker}:0.1.0`)** — deferred to MVP3 per [`tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md) (CLAUDE.md: "Additional workflows (deploy-staging, release, image-publish) ship at MVP3 + GA v1"). MVP1 v0.1.0 operators build locally via `docker compose build` (the smoke gate validates this path). A separate planned feature `infra_release_publishing` will land at MVP3 with the GHCR workflow + namespace conventions.
- **Cosign image signing** — GA v1 per the release matrix. Tracked alongside `infra_release_publishing` for consistency.
- Helm chart, Kubernetes manifests — v1.5+.
- Production install doc with TLS / SSO — MVP3+.
- Container scanning (Trivy), Python deps audit (pip-audit), TS deps audit (npm audit) — GA v1.
- Multi-region / multi-cloud — never (per [`tech-stack.md`](../../../01_architecture/tech-stack.md)).
- WCAG AA / i18n — never.
- New features of any kind — MVP2+ scope.

### API convention check

N/A — release polish, no new APIs.

### Phase boundaries

Single-phase. The MVP1 deliverable: "the `v0.1.0` tag is pushed with passing CI + the smoke test, the README polished, the demo recorded, and the tutorial works on a fresh Ubuntu 24.04 VM in under 30 minutes."

## 4) Product principles and constraints

- **The smoke test on a fresh VM is the gate.** If it doesn't pass, MVP1 is not shipped. No exceptions.
- **Sample data must be public-license.** Per umbrella spec §27 line 2312 and the open scope question. No proprietary or unclear-license content.
- **Tutorial supports a low-friction first-run path** without operator OpenAI cost: pre-baked `samples/judgments.json` is imported via `POST /api/v1/judgment-lists/import` (per `feat_llm_judgments` Story 3.2), so a no-key operator can complete Steps 1–8 (study runs end-to-end) before deciding whether to bring an OpenAI key for the digest narrative + chat-agent tool dispatch. **Step 9 (digest) and Step 10 (chat-agent) require an LLM-capable provider** — either a hosted OpenAI key OR a tool-capable local LLM. The tutorial documents this as the "no-LLM stop point" rather than pretending the full demo runs key-less.
- **The smoke gate runs the LLM-required path** with a CI-secret OpenAI key — that's the path design partners will actually run. A degraded no-LLM smoke would silently rubber-stamp a partial flow.
- **Demo recording is short.** 5–7 min, not 20. Captures: clone, `make up`, `make migrate`, `make seed-es`, register cluster (auto via `make seed-clusters`), create study via chat, watch trial table, see digest, click Open PR.

### Anti-patterns

- **Do not** ship MVP1 with the tutorial flow broken on a fresh VM. The smoke-test gate exists to prevent this.
- **Do not** include any sample data with unclear license. Public-domain or permissive only (Apache, MIT, CC0).
- **Do not** require >5 min of operator time for the "I just want to see what this does" path (the pre-baked judgments make this possible).
- **Do not** add new features in this feature. New scope creates new bugs the smoke test won't catch.

## 5) Assumptions and dependencies

- **Dependency: ALL 11 prior MVP1 features** shipped and merged (verified at the top of §2).
- **Sample dataset license cleared:** Amazon ESCI is CC-BY-4.0 (per Decision log).
- **Public test config repo:** `SoundMindsAI/relyloop-test-configs` (per `feat_github_pr_worker` Decision log + the release-gate workflow that already targets it at `.github/workflows/release-gate-pr-worker.yml` — see `feat_github_pr_worker/implementation_plan.md:754`). Operator forks for hands-on demo or reads in-place for the tutorial walk-through.
- **GitHub Action secret `OPENAI_API_KEY_TEST`** populated in the repo settings — required for the smoke gate's LLM-required path. Cost ceiling: ~$0.05 per smoke run (10-trial study + digest call). Maintainer rotates the key quarterly.
- **YouTube account** for hosting the demo recording (or alternative host like Loom).

## 6) Actors and roles

- **Primary actor:** New Relevance Engineer (clones the repo, follows the tutorial, decides whether to bring RelyLoop to their team).
- **Secondary actor:** the Maintainer (writes the tutorial, records the demo, validates the smoke test, pushes the `v0.1.0` tag).

### Authorization

N/A.

### Audit events

N/A.

## 7) Functional requirements

### FR-1: Worked tutorial doc
- The system **MUST** ship `docs/08_guides/tutorial-first-study.md` with all 10 steps per §3.
- Each step **MUST** include: command(s) to run, expected output (text or screenshot), troubleshooting hint for the most common failure mode.
- The tutorial **MUST** be doable in under 30 min on a fresh 16GB laptop. The no-LLM stop point is at Step 9 (digest); Steps 1–8 do not require an OpenAI key.
- The tutorial **MUST** explicitly document the "no-LLM stop point" with a clear marker so operators understand that Step 9 (digest) and Step 10 (chat-agent confirmation flow) require an LLM-capable provider.

### FR-2: Sample data + seed script + alignment validator
- The system **MUST** ship `samples/products.json` (~1,000 docs), `samples/queries.csv` (50 queries), `samples/judgments.json` (pre-baked LLM judgments for the 50 queries × 50 docs), `samples/templates/product_search.j2` (the canonical demo template).
- The system **MUST** ship `backend/app/scripts/seed_es.py` that populates the local ES container's `products` index from `samples/products.json` idempotently. Invocation: `make seed-es` → `docker compose exec api python -m backend.app.scripts.seed_es` (matches the existing `seed-clusters` pattern).
- The system **MUST** ship `samples/validate.py` that asserts the doc-id alignment invariant: every `query_id` in `judgments.json` exists in `queries.csv`, and every `doc_id` in `judgments.json` exists in `products.json`. This script runs in the smoke job AND as a pre-commit hook on the `samples/` path. Without it, an unaligned dataset would let the smoke gate pass with `primary_metric=0` on every trial.
- All sample content **MUST** be under a public license (Amazon ESCI / CC-BY-4.0 or similar; documented in `samples/LICENSE` and the README).

### FR-3: UI containerization
- The system **MUST** ship `ui/Dockerfile` using Node 20 + pnpm 9, multi-stage build (`builder → runner`). The build stage receives `NEXT_PUBLIC_API_BASE_URL` as a Docker `ARG` (default `http://localhost:8000`) — `pnpm build` bakes the value into the client bundle. Operators changing the API URL re-build via `docker compose build ui --build-arg NEXT_PUBLIC_API_BASE_URL=https://...`.
- The system **MUST** add a `ui` service to `docker-compose.yml` matching the existing api/worker pattern at `docker-compose.yml:42-44`:
  - `image: relyloop/ui:${RELYLOOP_GIT_SHA:-dev}`
  - `build: { context: ./ui, args: { NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000" } }`
  - `depends_on: [api]`
  - `ports: ["127.0.0.1:3000:3000"]`
- The system **MUST NOT** rely on a Compose `environment:` var for `NEXT_PUBLIC_API_BASE_URL` — Next.js public env vars are build-time, not runtime; setting them in `environment:` has no effect on the built bundle. (This is M3 from the spec-gen Review & Patch findings — a Next.js gotcha.)
- The `make up` workflow includes the `ui` service automatically (it's in the compose file). On first run, `docker compose up -d` triggers `docker compose build ui` since no `relyloop/ui:dev` image exists yet locally.

### FR-4: Smoke-test CI job
- `.github/workflows/pr.yml` **MUST** include a `smoke-test` job that runs on every PR (in parallel with the existing lint/typecheck/test/buildx jobs):
  - **Runner:** `runs-on: ubuntu-24.04` (pinned, not `ubuntu-latest`).
  - **Secret:** consumes `OPENAI_API_KEY_TEST` (required); writes to `./secrets/openai_key` before `make up` so the LLM-required path runs end-to-end. Without this secret the job fails fast — no degraded "I'll skip the digest" branch in CI.
  - **Step 1:** `make up`; wait up to 90s for `/healthz` `status == "ok"`.
  - **Step 2:** `make migrate` (Alembic chain to head — current `0007_conversations_messages`).
  - **Step 3:** `make seed-es` (populate `products` index).
  - **Step 4:** `make seed-clusters` (register `local-es` + `local-opensearch`).
  - **Step 5:** `python samples/validate.py` (doc-id alignment invariant).
  - **Step 6:** `pytest tests/smoke/test_tutorial_path.py` — orchestrates Steps 5–8 of the tutorial via the API (create query set + import judgments + create template + chat-agent `create_study` with confirmation), then waits up to 5 min for study completion.
  - **Step 7:** Asserts at least one trial has `primary_metric is not null AND > 0` (proves judgments + index intersect).
  - **Step 8:** Asserts the digest is generated (LLM-required path; OPENAI_API_KEY_TEST funds the call).
  - **Step 9:** UI smoke — `curl -fsS http://127.0.0.1:3000/ | grep -qi "<html"` (Next.js shell renders).
  - **Failure diagnostics (`if: failure()`):** `docker compose logs --no-color api worker postgres redis elasticsearch ui > smoke-logs.txt && actions/upload-artifact` so a CI reviewer can debug without re-running.
  - **Teardown (`if: always()`):** `FORCE=1 make reset` (CLAUDE.md: `make reset` is interactive without `FORCE=1` and would block in CI).
  - **Total wall-clock target:** <15 min (image pull dominates first run; warm runner closer to 6 min).

### FR-5: README polish
- The README **MUST**:
  - Show "Status: alpha (MVP1, v0.1.0)" at the top (replaces "MVP1 in progress (private alpha) ... currently soundminds.ai-internal")
  - Have a 5-minute quickstart section above the fold (`git clone` → `make up` → `make migrate` → `make seed-es` → open `/chat`)
  - Explain the value proposition in 2-3 sentences
  - Link to the tutorial, the umbrella spec, the architecture index, and CONTRIBUTING
  - List "What's in MVP1 / What's coming in MVP2/3/4/GA v1" in a compact table — link to [`tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md) as source-of-truth (don't duplicate)

### FR-6: Demo recording
- A 5-7 minute screen recording **MUST** be produced showing: clone, `make up`, `make migrate`, `make seed-es`, register cluster (auto via `make seed-clusters`), create study via chat agent, watch trial table fill in, see digest, click Open PR.
- The recording **MUST** be hosted (YouTube unlisted, Loom, or similar) and linked from README.

### FR-7: Tag + Release
- A `v0.1.0` Git tag **MUST** be pushed against the merge commit.
- A GitHub Release **MUST** be created with notes summarizing:
  - What's in MVP1 (capabilities)
  - Audience (technical evaluators)
  - How to install (link tutorial; explicitly note "operators build images locally via `make up` — pre-built GHCR images ship at MVP3 per the release matrix")
  - How to provide feedback (link GitHub Discussions / issue template)

## 8) API and data contract baseline

N/A — no new APIs.

## 9) Data model and state transitions

N/A — no schema changes.

## 10) Security, privacy, and compliance

- **Threats:**
  1. Sample data containing PII (e.g., real customer reviews). **Mitigation:** use only public datasets with explicit license.
  2. The pre-baked `samples/judgments.json` contains rationales generated by an OpenAI call on the maintainer's account. **Mitigation:** the maintainer reviews the rationales for sensitivity before committing; rationales are about generic e-commerce queries.
  3. Image publishing without signing → adopters can't verify provenance. **Mitigation:** cosign signing if achievable in <1h; otherwise warn in the README that GA v1 will introduce signed images.
- **Auditability:** N/A.

## 11) UX flows and edge cases

This feature has no in-product UI. The "UX" is the README + tutorial.

### Edge/error flows

- **`make up` fails on the fresh VM** (port conflict, insufficient memory). The smoke test catches and fails the PR; the tutorial step 1 documents the recovery (`docker compose down -v && rm -rf data && make up`).
- **OpenAI key not configured but operator skips the pre-baked judgments path.** The judgment-generate API returns `OPENAI_NOT_CONFIGURED` (per `feat_llm_judgments`); the tutorial's troubleshooting section explains this.
- **Sample dataset URL changes** (e.g., Amazon ESCI moves). Bake the dataset into the repo, not a fetch-on-build URL.

## 12) Given/When/Then acceptance criteria

### AC-1: Tutorial succeeds on fresh VM in <30 min (LLM-required path)

- Given a fresh Ubuntu 24.04 VM (16GB, 4 vCPU) with Docker installed, an OpenAI key (or tool-capable local LLM), and no prior RelyLoop containers.
- When the operator follows `docs/08_guides/tutorial-first-study.md` from clone through "Open PR" (Step 10).
- Then the operator completes all 10 steps in under 30 minutes.

### AC-2: Smoke test passes in CI

- Given a PR is opened AND the `OPENAI_API_KEY_TEST` GitHub secret is populated.
- When the `smoke-test` job runs.
- Then the job completes successfully within 15 minutes (boot + migrate + seed + 10-trial study + digest + teardown).

### AC-3: 80% backend coverage gate

- Given the merged main branch.
- When CI runs `uv run pytest --cov=backend --cov-fail-under=80`.
- Then the gate (`[tool.coverage.report].fail_under = 80` in `pyproject.toml`) passes.

### AC-4: README content checklist

- Given the merge commit's `README.md`.
- When a reviewer walks the README structure top-to-bottom.
- Then ALL of the following are present (objective checklist, not a vibe check):
  - Status badge / line reads `Status: alpha (MVP1, v0.1.0)` — NOT "private alpha" or "MVP1 in progress"
  - 5-minute quickstart appears within the first 2 sections (above the fold on a 1080p browser)
  - 2–3 sentence value-proposition section
  - Linked: tutorial (`docs/08_guides/tutorial-first-study.md`), umbrella spec, architecture index, CONTRIBUTING
  - "What's in MVP1 / What's coming" section linking to `tech-stack.md §"Canonical release matrix"` (no inline duplication of the matrix)
  - Demo recording link (per AC-6) appears in a section titled "What it looks like" or equivalent

### AC-5: No-LLM stop point is documented and verified

- Given a fresh VM with `OPENAI_API_KEY_FILE` empty AND no `OPENAI_BASE_URL` configured.
- When the operator follows the tutorial Steps 1–8 (study runs end-to-end via the pre-baked judgments path).
- Then the study completes with `status='completed'` AND the tutorial's Step 9 section is clearly marked as a "no-LLM stop point" — the operator sees a documented placeholder where the digest narrative would render, with explicit instructions for: (a) populating an OpenAI key + re-triggering the digest worker, OR (b) configuring a local LLM via `OPENAI_BASE_URL`. The smoke gate does NOT cover this AC (smoke runs the LLM-required path); manual verification is logged in the release-checklist runbook.

### AC-6: Demo recording exists and is linked

- Given the `v0.1.0` tag is pushed.
- When the operator opens the README.
- Then a clickable link to a 5–7 minute demo recording is in the "What it looks like" section. The link resolves to a working video.

### AC-7: Tag + Release published

- Given the smoke test passes on the merge commit.
- When the maintainer pushes the tag.
- Then a GitHub Release exists at `github.com/SoundMindsAI/relyloop/releases/tag/v0.1.0` with the documented notes structure.

### AC-8: Doc-id alignment invariant holds for sample data

- Given `samples/products.json` + `samples/queries.csv` + `samples/judgments.json` exist.
- When `python samples/validate.py` runs (in pre-commit AND in the smoke job).
- Then every `query_id` in `judgments.json` is found in `queries.csv` AND every `doc_id` in `judgments.json` is found in `products.json`. Without this gate, an unaligned dataset would let the smoke pass with `primary_metric=0` on every trial.

### AC-9: UI container is reachable from the smoke job

- Given the smoke job has run `make up`.
- When `curl -fsS http://127.0.0.1:3000/` runs.
- Then it returns 200 AND the body matches `<html` (proves the Next.js shell renders, the build-time `NEXT_PUBLIC_API_BASE_URL` was baked correctly, and the container is bound to the documented port).

## 13) Non-functional requirements

- **Performance:** Smoke test completes in <15 min total (image pull + build dominates first run; <6 min on warm runner with cached layers).
- **Reliability:** Smoke test passes deterministically; flaky failures get fixed before merge (no retries-as-feature). Required: at least 5 consecutive green runs on `main` before cutting `v0.1.0`.
- **Operability:** Failed smoke test logs are scoped enough to diagnose without re-running. **Concretely:** the `if: failure()` block of the smoke job MUST upload an artifact `smoke-logs.txt` containing `docker compose logs --no-color api worker postgres redis elasticsearch ui` AND the last 50 lines of `/healthz` response. AC-2 doesn't pass without these artifacts being attached on a forced-failure CI dry-run validation.

## 14) Test strategy requirements

- **Smoke test** (CI-only):
  - `tests/smoke/test_tutorial_path.py` — orchestrates the API calls that mirror the tutorial steps; asserts the study completes and the digest is generated.
- **Manual VM test:**
  - Documented procedure in `docs/03_runbooks/release-checklist.md`: spin up a fresh VM (or local clean Docker state), run the tutorial start-to-finish, time it, file any P0 issues found.
- **No new unit/integration tests** — this feature consumes the existing test surface.

## 15) Documentation update requirements

- `docs/08_guides/tutorial-first-study.md` — NEW (the tutorial).
- `docs/08_guides/README.md` — index pointing at the tutorial.
- `docs/03_runbooks/release-checklist.md` — NEW (manual VM test, tag + release procedure).
- `docs/01_architecture/deployment.md` — UPDATE: add the `ui` service to the documented Compose layout.
- `docs/02_product/mvp1-user-stories.md` — mark US-30 / US-31 / US-32 as "implemented".
- Root `README.md` — major polish per FR-5.

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** N/A.
- **Operational readiness gates:**
  - Smoke test passes on the merge commit
  - 80% coverage gate green
  - Manual fresh-VM tutorial run logged in the release-checklist runbook
  - Demo recording uploaded + linked
- **Release gate:** maintainer pushes `v0.1.0` tag; GitHub Release published with notes.

## 17) Traceability matrix

| FR ID | AC IDs | Stories | Test files | Docs |
|---|---|---|---|---|
| FR-1 (tutorial) | AC-1, AC-5 | filled at plan | (manual VM + smoke) | tutorial.md |
| FR-2 (samples + alignment validator) | AC-1, AC-2, AC-8 | filled at plan | `samples/validate.py`, `tests/smoke/test_tutorial_path.py` | tutorial.md, samples/LICENSE |
| FR-3 (UI containerization) | AC-1, AC-9 | filled at plan | smoke job step 9 (curl 127.0.0.1:3000) | deployment.md |
| FR-4 (smoke-test CI job) | AC-2, AC-8, AC-9 | filled at plan | `.github/workflows/pr.yml` smoke-test job + `tests/smoke/test_tutorial_path.py` | release-checklist.md |
| FR-5 (README polish) | AC-4 | filled at plan | (checklist review during release-checklist run) | README.md |
| FR-6 (demo recording) | AC-6 | filled at plan | (manual) | README.md |
| FR-7 (tag + release) | AC-3, AC-7 | filled at plan | (manual; CI gate on coverage already enforces AC-3) | release-checklist.md |

## 18) Definition of feature done

- [ ] AC-1 through AC-9 pass.
- [ ] Manual fresh-VM tutorial run logged in `docs/03_runbooks/release-checklist.md` with timing (≤30 min for the LLM-required path; the no-LLM stop point at Step 9 is ALSO manually validated and logged).
- [ ] All MVP1 user stories US-1 through US-32 marked "implemented" in `mvp1-user-stories.md` (current count is 32 — US-32 is the air-gapped local-LLM story added after this spec was first authored).
- [ ] At least 5 consecutive green smoke runs on `main` before cutting `v0.1.0` (per §13 reliability NFR).
- [ ] CI smoke `if: failure()` artifact upload validated via a forced-failure dry-run (AC-2 operability gate).
- [ ] `v0.1.0` GitHub Release published with notes.
- [ ] Demo recording uploaded + linked from README.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all resolved (see Decision log).

### Decision log

- 2026-05-09 — The smoke test is the release gate, not optional — per umbrella spec §27 strategic-rationale and the project's "fail loudly" principle.
- 2026-05-09 — Pre-baked `samples/judgments.json` so first-run users don't pay OpenAI cost — adoption-funnel hygiene. Imported via `POST /api/v1/judgment-lists/import` (added to `feat_llm_judgments` FR-3b).
- 2026-05-09 — Tutorial documents two LLM paths: (a) hosted OpenAI with API key, (b) local LLM via Ollama/LM Studio/vLLM/TGI with `OPENAI_BASE_URL` config. Both paths produce a working tutorial; the local path skips OpenAI cost AND demonstrates RelyLoop's air-gap-friendly architecture. Per `feat_chat_agent` and `feat_llm_judgments` capability-check semantics, smaller local models may degrade some features (chat agent without tools; digest narrative-only). Tutorial calls this out in Step 0 with a "tested model matrix" link to [`llm-orchestration.md` §"OpenAI-compatible endpoints"](../../../01_architecture/llm-orchestration.md).
- 2026-05-09 — Container UI as part of MVP1 (not a post-release polish) — `make up` should bring the full stack including UI; running `pnpm dev` is a developer-mode optimization, not the user-facing path.
- 2026-05-09 — Test config repo: **public `SoundMindsAI/relyloop-test-configs`** — same repo serves both `feat_github_pr_worker` integration tests and the tutorial's apply-PR step. Public repo + dedicated test PAT scoped only to it. Operator instructions in the tutorial point at this repo for the demo apply step.
- 2026-05-09 — Sample dataset: **Amazon ESCI subset** (publicly licensed CC-BY-4.0; ~1,000 products + 50 queries subsetted from the upstream 1.5M × 1.8M dataset). Pre-existing ESCI judgments seed `samples/judgments.json` so first-run users get a working tutorial without OpenAI cost.
- 2026-05-09 — Quepid comparison stub: **skip for MVP1**; add at MVP2 once feature parity is more defined.
- 2026-05-09 — Cosign signing: **ship if achievable in <1 hour effort at implementation time**; otherwise defer to GA v1 (empirical decision, not blocking).
- 2026-05-09 — Demo recording host: **YouTube unlisted** (free, ubiquitous, embed-friendly).
- 2026-05-12 — **Image publishing deferred to MVP3** (per spec-gen Review & Patch finding M4). Original FR-6 + AC-8 conflicted with [`tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md) which puts the image-publish workflow at MVP3. MVP1 v0.1.0 alpha operators build locally via `docker compose build` (smoke gate validates this path). Cosign signing remains GA v1 either way. A separate planned feature `infra_release_publishing` will land at MVP3 with the GHCR workflow + `ghcr.io/soundmindsai/...` namespace (the original spec used `ghcr.io/relyloop/...` which doesn't match the actual repo owner). v0.1.0 release notes explicitly call out "build images locally" as the install path.
- 2026-05-12 — **Smoke gate runs the LLM-required path with `OPENAI_API_KEY_TEST` GitHub Action secret** (per spec-gen Review & Patch finding M5). Original spec said "tutorial works without OpenAI on first run" AND "smoke asserts digest is generated" — those contradict because the digest needs an LLM. Resolution: the smoke gate covers the path design partners will actually run; the no-LLM stop point at tutorial Step 9 is manually validated in the release-checklist runbook (AC-5).
- 2026-05-12 — **`NEXT_PUBLIC_API_BASE_URL` is a Docker build arg, not a Compose runtime env** (per spec-gen Review & Patch finding M3). Next.js bakes `NEXT_PUBLIC_*` into the client bundle at `pnpm build`; Compose `environment:` has no effect on the built bundle. FR-3 specifies `build: { args: { ... } }`; operators changing the URL re-build. Runtime injection (e.g., `_document.tsx` script tag reading server env) was considered but rejected as over-engineering for a single-deployment MVP1.
