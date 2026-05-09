# RelyLoop MVP1 / v0.1 — Execution Plan

**Status:** Draft v0.1
**Date:** 2026-05-07
**Companion to:** `relevance-copilot-spec.md` §27 *Phased delivery*
**Audience:** The engineer(s) building MVP1, plus stakeholders tracking progress

---

## Executive summary

MVP1 ships an alpha release that demonstrates the Karpathy loop end-to-end on a developer's laptop. Target: **5 weeks single-engineer**, or **3 weeks with two engineers** working in parallel after week 1. Output: a tagged `v0.1.0` release with Apache 2.0 LICENSE, a worked tutorial, an installable Docker Compose stack supporting Elasticsearch and OpenSearch, and demo material (videos, screenshots, real PRs) to drive design-partner recruitment for MVP2.

The plan is sequenced so each week ends in a working state. If the project pauses at any week boundary, what's been built still functions — no half-broken intermediate states.

---

## Pre-flight checklist (before week 1)

These are admin items that are not engineering work but must be done before the engineer can start. Estimated total: **2–3 days of soundminds.ai operations time**, completed in parallel with engineering kickoff.

| Item | Owner | Done when |
|---|---|---|
| TESS lookup for `RELYLOOP` and `RELY` in software classes 9 + 42 | soundminds.ai legal/ops | Trademark report archived; no blocking conflicts |
| Domain registration: `relyloop.io`, `.com`, `.dev`, `.org` (2-year lock) | soundminds.ai ops | DNS records pointing to a placeholder; auto-renew enabled |
| GitHub organization `relyloop` reserved | soundminds.ai ops | Org created, basic profile, README placeholder |
| Reserve `@relyloop` npm scope and `relyloop-*` PyPI prefix | soundminds.ai ops | Both registered; placeholder packages published |
| Decide on initial maintainer team — minimum two people for emergency response and PR review | soundminds.ai | Names listed in `MAINTAINERS.md` (placeholder) |
| OpenAI API account with $100 budget cap for development + testing | soundminds.ai ops | API key stored in 1Password / org secrets manager |
| GitHub Personal Access Token (or App) for the test config repo | soundminds.ai ops | Token stored in 1Password; scoped to a single test repo |
| Identify 2–3 design-partner candidates for post-MVP1 outreach | soundminds.ai product/business | Names + contact info captured; intro emails drafted |

**The trademark + domain checks gate everything else.** If TESS turns up a conflict, you don't want to discover it after writing 5 weeks of code under the wrong brand name.

---

## Engineer onboarding requirements

The engineer building MVP1 needs:

- **Skills:** Python 3.12+ (FastAPI, asyncpg, Pydantic), TypeScript / Next.js 14+, Docker / Docker Compose, Postgres, basic Optuna familiarity (or willingness to learn — it's not deep), familiarity with one of ES or OpenSearch (the API is the same), GitHub Actions
- **Hardware:** Laptop with 16 GB RAM minimum (32 GB recommended for running ES + OpenSearch + Postgres + Redis + workers concurrently)
- **Access:** GitHub org admin (for image publishing, branch protection); OpenAI API key; the org's test config repo
- **Familiarity with the spec:** Has read `relevance-copilot-spec.md` §1 (Summary), §7 (Architecture), §8 (Adapters), §9 (Data model), §13 (Optuna), §14 (Evaluation), §15 (LLM orchestration), §27 (MVP1 scope), and §28 (OSS positioning). Other sections describe MVP2+ work and don't gate week-1 progress.

---

## Week-by-week plan

### Week 1 — Foundation

**Goal:** A working, empty skeleton that anyone can clone, `docker compose up`, and have running locally with passing CI.

**Deliverables:**

- Repository on GitHub under `relyloop/relyloop` with branch protection on `main`
- Apache 2.0 `LICENSE`, `NOTICE`, minimal `README.md`, `CONTRIBUTING.md` (DCO model), `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1)
- Project skeleton:
  - `backend/` — FastAPI app with health endpoint, structured logging via `structlog`
  - `ui/` — Next.js 14 app with placeholder pages
  - `worker/` — Arq worker scaffolding
  - `migrations/` — Alembic migrations directory
  - `pyproject.toml` (uv-managed) with all backend dependencies pinned
  - `package.json` (pnpm) for UI
- **Postgres schema:** clusters, query_sets, queries, query_templates, judgment_lists, judgments, studies, trials, digests, proposals, users, audit_log, conversations, messages — all without `tenant_id` columns. UUIDv7 primary keys throughout. Lineage columns absent (deferred to MVP2).
- `docker-compose.yml`:
  - Postgres 16, Redis 7, ES 9.0 (single-node, security disabled for local dev), OpenSearch 2.18 (security plugin disabled), the API service, the UI service, an Arq worker service
- GitHub Actions `.github/workflows/pr.yml`: ruff + black + mypy strict + pytest scaffold on Python; eslint + prettier + tsc --noEmit on TypeScript; passes against an empty test suite
- Pre-commit hooks for ruff, mypy, eslint
- Basic structured logging schema implemented (just the foundation; no event catalog yet)

**Demo at end of week 1:** Clone the repo on a fresh laptop, run `docker compose up`, see API at `localhost:8000/health`, UI at `localhost:3000` (placeholder), CI green on a sample PR.

**Definition of done:**

- `docker compose up` works on a fresh laptop with 16 GB RAM in under 5 minutes
- All CI checks green
- A new engineer can complete the local-dev quickstart from `README.md` in under 15 minutes

**If running behind:** Defer pre-commit hooks (push to MVP2). Defer the OpenSearch container (just keep ES; OpenSearch can be added in week 2 when the adapter is being written).

---

### Week 2 — Adapter, Optuna, Evaluation

**Goal:** A single trial runs end-to-end against local ES with a hardcoded query template + judgment list. Metric is computed and persisted.

**Deliverables:**

- `ElasticAdapter` in `backend/adapters/elastic.py` implementing the v1 `SearchAdapter` Protocol — handles both ES and OpenSearch via the `engine_type` flag passed at construction
  - `health_check`, `list_targets`, `get_schema`, `render`, `search_batch`, `explain`
  - Uses `httpx.AsyncClient` for HTTP; `_msearch` for batched queries
- Sample query template — `templates/elasticsearch/product_search.j2` — multi_match with field_boosts, tie_breaker, fuzziness as parameters
- Sample data setup script — `scripts/seed_es.py` — creates a `products` index with ~1,000 sample products and ingests them. Used by the tutorial.
- Optuna integration:
  - `optuna.create_study` with `RDBStorage` pointing at our Postgres
  - TPE sampler default; `MedianPruner` with `n_warmup_steps=10`
  - `relyloop.tracing.optuna` wrapper (no-op for MVP1; placeholder for MVP2's full trace propagation)
- pytrec_eval scoring helper — `backend/eval/scoring.py` — takes (query_id → ranked doc_ids) + judgments, computes nDCG@10, MAP, P@10
- Worker: `run_trial` Arq job that takes (study_id, params), renders the template, calls `search_batch`, scores, writes a `trials` row
- Adapter unit tests against the local ES container — at least 80% coverage on `ElasticAdapter`

**Demo at end of week 2:** Manually enqueue a trial via a Python REPL → see the trial complete in ~200 ms → see the row in the `trials` table with metrics → see the structured log lines in stdout.

**Definition of done:**

- Adapter passes all unit tests against both ES 9 and OpenSearch 2.18 containers
- A single trial runs end-to-end in under 500 ms
- pytrec_eval results match a hand-computed baseline within rounding error (test fixture)

**If running behind:** Skip OpenSearch testing until week 5; just verify the adapter works against ES. Defer `explain` to MVP2 (only `search_batch` + `health_check` + `get_schema` are hot-path for the loop).

---

### Week 3 — Study orchestration + LLM-driven judgments

**Goal:** A study runs with N parallel trials, completes when stop conditions hit, and produces a digest. LLM-generated judgments work for the tutorial's 50-query set.

**Deliverables:**

- Study lifecycle endpoints — `POST /studies`, `GET /studies/{id}`, `POST /studies/{id}/cancel`
- Study runner — orchestrator process that spawns N parallel `run_trial` workers, all sharing an Optuna study via the Postgres backend
- Stop conditions — `max_trials` and `time_budget_min` honored
- Digest generation — single LLM call after study completion that produces a narrative + recommended config + parameter importance (using `optuna.importance.get_param_importances`)
- LLM judgment generation — `POST /judgments/generate`:
  - Input: query_set_id, cluster_id, target, current template, rubric
  - Process: for each query, run the current template, get top-K hits, ask the LLM to rate each (query, doc) on a 0–3 scale with rationale, in a single batched call per query
  - Output: persisted judgment list with `source = "llm"`
- OpenAI client integration via `openai` Python SDK — direct function-calling, no LangGraph
- Tool definitions for the chat agent: `list_clusters`, `list_templates`, `list_query_sets`, `propose_search_space`, `create_study`, `get_study_status`
- Proposal generation from a completed study (digest → proposal row)

**Demo at end of week 3:** Hit `POST /studies` via curl with sample data → watch trials accumulate over a few minutes → study completes → digest is generated → proposal row is written. LLM judgments work for the 50-query tutorial set in under 5 minutes and cost < $1 in OpenAI calls.

**Definition of done:**

- A 100-trial study completes in under 5 minutes against the local ES sample data
- LLM-generated judgments achieve ≥0.6 Cohen's kappa against 20 hand-labeled samples (calibration sanity check)
- Studies UI list page (basic table) shows running and completed studies

**If running behind:** Defer the calibration check (just spot-check manually). Reduce judgment generation to single-shot per (query, doc) instead of batched per query — slower and more expensive but simpler.

---

### Week 4 — UI + chat + GitHub PR creation

**Goal:** End-to-end loop works through the UI: a relevance engineer logs in, chats with the agent, kicks off a study, sees it complete, and opens a PR — all without leaving the browser.

**Deliverables:**

- Studies UI:
  - List view (filter by status)
  - Create form (cluster, target, template, query set, judgment list, search space, objective, config)
  - Detail view with live trial table (refreshes every few seconds via polling — no SSE in MVP1)
  - Digest view (narrative, parameter importance bar chart with Recharts, top-10 trials table)
- Chat interface:
  - Conversation list
  - Single-conversation view with streaming chat (SSE from OpenAI passed through to browser)
  - Tool-call rendering (collapsed by default; expandable to see what the agent did)
  - The agent uses the tools from week 3 to drive the workflow
- Proposal UI:
  - List of proposals (status: pending, pr_opened, pr_merged, rejected)
  - Detail view with config diff and metric delta
  - "Open PR" button — triggers the GitHub PR creation flow
- GitHub PR creation:
  - Worker job: clone (or pull) the configured config repo, create branch `relyloop/study-{id}`, edit `*.params.json`, commit (DCO sign-off), push, open PR via GitHub API
  - PR body template includes link back to the study, top-10 trials, baseline-vs-achieved metrics
  - GitHub PAT-based auth (App-based auth deferred to MVP3)
- GitHub webhook receiver — `POST /webhooks/github` with signature verification — updates `pr_state` on the proposal
- Polling fallback every 15 minutes if the webhook isn't reachable

**Demo at end of week 4:** Open the chat UI → ask "tune the product_search template against `qs_modelnums`" → agent walks through the steps → study runs → digest appears → click "Open PR" → see the PR appear in the test config repo on GitHub. Total wall-clock: under 30 minutes.

**Definition of done:**

- Full flow from chat to opened PR works end-to-end in the UI
- PR includes the structured commit message and the body template
- Webhook receiver verifies signatures correctly (tested with a bad signature → 401)

**If running behind:** Drop the chat interface — a "new study" form is enough for MVP1 demo (chat is sticky for the demo but not strictly required). Defer Recharts charts; show parameter importance as a sorted markdown table.

---

### Week 5 — Tutorial, polish, release

**Goal:** Anyone can clone the repo, follow `docs/tutorial-first-study.md`, and reproduce the demo from week 4 on their own laptop with no tribal knowledge.

**Deliverables:**

- `docs/tutorial-first-study.md`:
  - Prerequisites (Docker, OpenAI key, GitHub PAT)
  - Step 1: Clone and `docker compose up`
  - Step 2: Run `scripts/seed_es.py` to populate the sample data
  - Step 3: Create a query set from `samples/queries.csv` (50 hand-curated queries)
  - Step 4: Generate judgments (or use the pre-baked set in `samples/judgments.json` to skip the OpenAI call)
  - Step 5: Open the chat UI, ask the agent to tune
  - Step 6: Watch the study run, read the digest
  - Step 7: Open the PR
  - Each step has expected output (screenshots / JSON snippets) so users can verify they're on track
- `samples/` directory with the 50-query set + pre-baked judgment list (so first-run users don't pay for OpenAI judgments unless they want to)
- README polish:
  - 5-minute quickstart up top
  - Value proposition (what RelyLoop does, who it's for)
  - "What's in MVP1 / what's coming" honest list (so adopters know it's an alpha)
  - Links to spec, comparison-with-Quepid stub, and CONTRIBUTING
- `docs/install.md` — production-style install walkthrough (TLS, SSO via reverse proxy, secrets in mounted files)
- Bug fixes from end-to-end testing — at minimum a 30-minute smoke run through the tutorial flow on a fresh VM, fixing whatever breaks
- Coverage gate: `coverage.py` reports 80%+ for backend Python; CI fails on regression
- Docker images built and pushed to `ghcr.io/relyloop/api:0.1.0`, `ghcr.io/relyloop/ui:0.1.0`, `ghcr.io/relyloop/worker:0.1.0`. Cosign-signed (deferred from "future polish" — add it now since it's cheap)
- `v0.1.0` git tag with GitHub Release notes summarizing what's in MVP1, what's deferred, who it's for, and how to provide feedback
- Demo recording — 5–7 minute screen recording walking through the tutorial, hosted on YouTube unlisted (or similar). This becomes the primary outbound asset for design-partner recruitment.

**Demo at end of week 5:** v0.1.0 tag pushed; GitHub Release published; demo video posted; design-partner outreach kicked off.

**Definition of done:**

- A new engineer can complete the tutorial from scratch in under 30 minutes
- All CI checks green on the release tag
- Smoke test passes on a fresh Ubuntu 24.04 VM
- 80% backend Python coverage; UI coverage not gated in MVP1
- Tutorial works without internet for the local-dev parts (only LLM calls require network)

**If running behind:** Drop image cosign signing (move to MVP3). Drop the production-style install doc (keep just the tutorial; defer install.md to MVP2). Drop the demo recording (release the tag and circulate the tutorial only).

---

## Two-engineer compression (~3 weeks instead of 5)

After week 1's foundation lands, two engineers can split:

- **Engineer A (backend / data plane):** Adapter, Optuna, evaluation, study orchestration, judgment generation, GitHub PR creation. Owns weeks 2–4 backend deliverables.
- **Engineer B (UI / agent):** Chat interface, studies UI, proposal UI, tool integration, OpenAI client wiring. Owns weeks 3–4 frontend deliverables.

Both join for week 5 (tutorial, polish, release). The compression is real because most week-3 and week-4 work is genuinely independent — backend and frontend are well-separated by the API surface.

Realistic two-engineer timeline:

- Week 1 (jointly, foundation): 1 week
- Weeks 2–4 (parallel): roughly 1.5 weeks
- Week 5 (jointly, polish + release): 0.5 week

Total: **~3 weeks calendar**.

---

## Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| ES + OpenSearch local-container quirks (memory, JVM, version differences) eat 2–3 days | Medium | Medium | Smoke-test both containers in pre-flight or week 1 day 1; document required tweaks in README |
| LLM-generated judgments are noisy, calibration kappa drops below 0.6 | Medium | High | Pre-bake judgments for the tutorial; live LLM generation is "advanced" and gated behind a flag |
| GitHub PR creation flow has auth complexity (App vs PAT, signature verification, webhook reliability) | High | Medium | Start with PAT; use a test repo, not a real config repo; defer App-based auth to MVP3 |
| Coverage gate (80%) is hard to hit on the UI | Low | Low | Scope coverage to backend Python only for MVP1; UI tests are smoke-level |
| 5-week single-engineer plan has zero slack | High | Medium | Each week has explicit "if running behind" deferrable items; be ruthless about cutting scope vs. extending timeline |
| Tutorial doesn't actually work on a fresh laptop | Medium | High | Smoke-test on a fresh VM in week 5 day 1, before anything else; use that experience to fix paper-cuts |
| OpenAI API rate limits or cost spikes during testing | Low | Medium | Budget cap on the API key; use `gpt-4o-mini` for non-judgment calls during dev |
| Postgres / Redis / ES container startup ordering issues | Medium | Low | Health checks + restart policy in docker-compose; document the issue in README |

---

## Critical path

Three things have to work for MVP1 to ship; everything else is supporting:

1. **The Karpathy loop runs end-to-end against ES.** If this doesn't work, there is no MVP. Week 2–3 is where this is proven; if it's not running by end of week 3, escalate immediately.
2. **A study produces a useful digest.** The narrative needs to be informative and the recommended config needs to be correct. Week 3 is where this is proven; the calibration kappa check is the early-warning.
3. **A PR opens against a real GitHub repo.** The whole "Git as source of truth" story falls apart without this. Week 4 is where this is proven.

Anything else — chat polish, UI styling, sample data quality — is meaningful but not blocking.

---

## What's *not* in MVP1 (worth re-stating)

These are deferred to MVP2 and beyond. Don't accept scope creep into MVP1:

- LangGraph orchestrator (use plain OpenAI function calling)
- Langfuse + SigNoz observability
- Event catalog with CI gates
- Audit log immutability triggers
- Lineage columns
- Multi-tenancy
- Multi-LLM provider abstraction
- Multi-Git provider abstraction
- Lucidworks Fusion adapter
- Bearer-token API keys (use simple session cookies for MVP1)
- Full agent-first API surface
- Four-layer test pyramid (just unit tests for MVP1)
- Five GitHub Actions workflows (just `pr.yml` for MVP1)

---

## Open questions before kickoff

These should be resolved before week 1 starts. Each is a 30-minute conversation, not a multi-day research project, but they all affect what gets built.

1. **One engineer or two?** Affects timeline and team setup. Default: one engineer for the full 5 weeks unless soundminds.ai can dedicate a second.
2. **Which sample dataset?** The tutorial needs ~1,000 sample products plus a 50-query set. Use a publicly-licensed dataset (Amazon ESCI? IMDB? a small e-commerce sample?) so adopters can recreate the tutorial without licensing concerns.
3. **Test config repo location?** Probably under the `relyloop` GitHub org as `relyloop/sample-search-configs`. Should be public so the tutorial works without authentication issues for read-only operations.
4. **OpenAI model choice for MVP1?** `gpt-4o-2024-08-06` for judgment generation (quality matters); `gpt-4o-mini` for the chat orchestrator (cost matters, quality is fine). Pinned versions in code.
5. **Who's the alpha-release reviewer?** v0.1.0 should be reviewed by at least one outside person before tagging — fresh eyes catch what builders miss.

---

*End of plan. Update as MVP1 progresses; keep a "Status" line at the top with the current week.*
