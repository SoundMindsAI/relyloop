# CLAUDE.md — RelyLoop

Continue execution without constantly asking for permission to execute tests or code changes or commands. I approve all test executions, all commands, and all code changes scoped to the current feature branch. Stop and ask only for: (a) destructive ops on `main` or shared infra, (b) actions that publish to third parties (PR comments, Slack messages, GitHub Releases), (c) operator-environment changes the agent cannot make on the operator's behalf (`.env` content, mounted secret values, GitHub branch protection — see [implementation_plan.md §7.5](docs/00_overview/implemented_features/2026_05_09_infra_foundation/implementation_plan.md) for the canonical handoff list).

**Never commit directly to main.** Always create a feature branch, push it, and open a PR. CI runs on PRs to main — merging to main triggers staging deploy (when staging exists; MVP1 has no remote staging — local-only).

**After creating or pushing to a PR,** monitor the CI workflow. Use `gh run list --branch={BRANCH}` to find the run, then `gh run watch {RUN_ID}` to monitor. If CI fails, investigate and fix before moving on.

**When a feature/bug/chore PR has a tracking issue,** put `Closes #<tracking-issue>` in the PR body so GitHub auto-closes it on merge. This is surface-independent (it fires no matter which Claude Code surface drove the merge) and is the front-line replacement for the manual close-on-merge step that kept getting skipped. The [`reconcile-tracking-issues.yml`](.github/workflows/reconcile-tracking-issues.yml) workflow is the **server-side backstop**: on every push to `main` + a daily cron it closes any open tracking issue whose slug now lives under `implemented_features/`, and auto-creates a templated issue for any roadmap-active `planned_features/` folder (`02_mvp2`/`03_mvp3`/`04_ga`) that has none. So a missed `Closes #N` self-heals within a day — but include it anyway for instant closure. Run `python scripts/reconcile_tracking_issues.py --dry-run` to preview locally.

**Before merging any non-docs PR,** verify the latest successful `pr.yml` run was produced against the current `main`. If `main` advanced after the last successful run, click "Update branch" on the PR (or rebase locally) to re-trigger CI before merging — this guards against merge-skew (the PR head was validated against an older base) until branch protection becomes available post-public-launch.

**Before considering a PR ready to merge,** check for Gemini Code Assist review comments (`gh api repos/SoundMindsAI/relyloop/pulls/{PR_NUMBER}/comments`) and adjudicate every line-level finding using the four-quadrant rubric in `.claude/skills/impl-execute/SKILL.md` Step 6 (Accept / Reject with cited counter-evidence / Defer as non-regression follow-up). Post one summary comment with the verdict table before merge.

**Cross-model review policy:** Feature specs and implementation plans are reviewed by **GPT-5.5** (model ID: `gpt-5.5`) before being finalized — **Opus creates; GPT-5.5 reviews.** The value comes from a *different model family* reviewing the work, so never substitute another Claude/Opus instance or a same-effort same-family model (gpt-4o etc. are also not substitutes). Resolve the API key from `.env` (`grep '^OPENAI_API_KEY=' .env | cut -d'=' -f2-`).

**Environment-aware fallback (Claude Code remote sandbox).** In environments where GPT-5.5 is unreachable — no `OPENAI_API_KEY` in `.env` AND/OR outbound egress to `api.openai.com` blocked by the network policy (**the default in the Claude Code web/remote sandbox**) — the spec/plan/guide-stage GPT-5.5 review is **not silently skipped**; the **sanctioned fallback is Opus self-review** (the creating model runs the verification passes itself). Treat this as a known standing condition of the sandbox, not a per-run anomaly — but **be honest that it is a degradation**, not an equivalent: a model is weaker at catching its own blind spots, which is the whole reason the cross-family policy exists. The cross-family check that **does** survive in this environment is **Gemini Code Assist** — it is reachable and auto-reviews every PR at the *code* stage, so when GPT-5.5 is down, Gemini is the live cross-family gate and its findings must be adjudicated rigorously (per the four-quadrant rubric). Every skill that runs the review MUST state which reviewer ran — `cross-model review: GPT-5.5` vs `cross-model review: Opus self-review (GPT-5.5 unreachable)`. Precedent: `feat_fts_rank_ordering` (operator-approved substitution).

**Durable fix (restores real cross-model review).** This environment's network policy is **operator-configurable**. To get true GPT-5.5 review on specs/plans, (re)create the environment with egress to `api.openai.com` allowed and `OPENAI_API_KEY` provided (mounted per the secrets convention); the skills already resolve the key + call the API, so **no skill change is needed once it's reachable** — they stop hitting the fallback automatically. This is the preferred posture when the work warrants genuine cross-family review.

## Project Overview

RelyLoop is the only open-source tool that runs **automated Bayesian search-space optimization** (Optuna/TPE, thousands of trials) across the **full query-time search space** on every major OSS search engine — Elasticsearch, OpenSearch, and Apache Solr (all three engines shipped) — and ships winning configurations as **Pull Requests** to a central search-config Git repo for the operator's existing approvers to review and merge. A conversational LLM agent describes the loop and proposes the search space, but the engineering moat is the loop itself, the Git-PR posture, and the three-engine reach. See [`docs/07_research/comparison.md`](docs/07_research/comparison.md) for the citation-backed competitive matrix vs OpenSearch SRW, Quepid, RRE, Chorus, and Elastic's native tooling.

The tool is a single, engine-neutral, provider-neutral system: one UI, one workflow, one schema. Differences between Elasticsearch, OpenSearch, and Apache Solr are isolated behind a thin `SearchAdapter` Protocol. **LLM flexibility is one env var: `OPENAI_BASE_URL` points the `openai` SDK at any OpenAI-compatible endpoint — OpenAI cloud, Ollama (air-gapped), LM Studio, vLLM, HuggingFace TGI, Azure OpenAI's OpenAI-compatible mode, OpenRouter for multi-model routing, or LiteLLM proxy in front of Bedrock / Vertex / Anthropic native. See [`docs/08_guides/llm-endpoint-setup.md`](docs/08_guides/llm-endpoint-setup.md). Native non-OpenAI provider SDKs are in the backlog as an ergonomics upgrade.** Git providers behind a `GitProvider` adapter (GitHub today; GitLab + Bitbucket in the backlog). Multi-tenancy is in the backlog — RelyLoop is single-tenant through GA v1, with SSO via reverse proxy as the recommended path.

**Personas** (per umbrella spec §6):

- **Relevance Engineer** (primary user). Runs studies, reviews digests, opens proposals.
- **Approver.** Subset of relevance engineers (or platform engineers) who hold merge rights on protected branches in the config repo. Cannot be bypassed — the tool delegates approval to the config repo's branch protection (no in-tool approval surface).
- **Viewer.** Read-only on studies, proposals, dashboards (PMs, exec stakeholders).

**The tool's role ends at the PR.** Production search behavior is determined by the configs the operator merges and their CI deploys. RelyLoop never sits on the live search-serving path, never runs online A/B tests, never trains LTR models, and never modifies cluster schema/mapping/analyzer settings — tuning is restricted to query-time parameters surfaced through the engine adapter. See umbrella spec §4 ("Non-goals") for the full constraint list.

**License:** Apache 2.0. Initial maintainer: soundminds.ai, with an explicit transition path to community maintainership over 12–24 months (umbrella spec §29).

**Stack (MVP1):** Python 3.13 + FastAPI · Next.js 16 (React 19, TypeScript App Router, Turbopack) · Tailwind 4 (CSS-first config) · Vitest 4 · Postgres 16 + SQLAlchemy 2.0 async + Alembic · Redis 7 + Arq workers · Optuna with TPE sampler + RDBStorage · `ir_measures` (provider-abstracted IR-evaluation engine wrapping multiple cut-aware-metric backends) · `openai` Python SDK pointed at any OpenAI-compatible endpoint via `OPENAI_BASE_URL` (works against api.openai.com, Ollama, LM Studio, vLLM, HuggingFace TGI) · ElasticAdapter handling both ES 8.11+/9.x and OpenSearch 2.x/3.x · GitHub Git provider · single-tenant, no auth, Docker Compose-only deployment.

**Release matrix** (canonical source: [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](docs/01_architecture/tech-stack.md)):

| Release | Theme | Adds |
|---|---|---|
| MVP1 / v0.1 (shipped) | "The Loop" | ES + OpenSearch adapter, OpenAI-compatible LLM, GitHub provider, single-tenant, no auth, Docker Compose, 80% coverage gate, Optuna/TPE Bayesian loop, Git-PR apply path, conversational agent |
| MVP2 / v0.2 (in progress; Solr + UBI shipped) | "Three-Engine + Real Signals" | Apache Solr adapter (Solr 9.x + 10.x via `edismax` + `{!ltr}` rescore) — **shipped 2026-05-31** — + UBI judgments (`UbiReader` reads `ubi_queries` + `ubi_events` via any `SearchAdapter`) — **shipped 2026-05-29** — + pluggable `SignalsConverter` (position-bias-corrected CTR, dwell-time, **hybrid UBI+LLM**) + `POST /api/v1/judgment-lists/generate-from-ubi` + `generate_judgments_from_ubi` agent tool. `UbiReader` reads the `ubi_queries` + `ubi_events` collections identically on all three engines, so UBI **judgment generation** works everywhere from day one. The live event-capture component (`solr.UBIComponent`) does **not** ship in the stock `solr:10.0` / `solr:9.x` images (verified: no module, no class, no ref-guide page), so on Solr the demo synthesizes UBI events directly into those collections rather than capturing them live; the capability probe accurately reports `ubi_component_present=false`. |
| MVP3 / v0.3 | "Observable" | Langfuse + ClickHouse + SigNoz; canonical event catalog; `audit_log` table + immutability trigger (no users/tenants yet); lineage columns; PII redaction; trace propagation across all three engines + both judgment sources |
| GA v1 / v1.0 | "Production-ready" | LangGraph orchestrator + `PostgresSaver`; full RFC 7807 errors; `Idempotency-Key`; full four-layer test pyramid at 90% coverage; complete CI/CD with security gates; container scanning; image signing; design-partner references; public Optuna-vs-SRW-grid benchmark. **No new product surface** — all six differentiators are GA by MVP3; GA v1 is polish + governance + hardening. |
| Backlog | — | Multi-Git provider abstraction (GitLab, Bitbucket); multi-tenancy + multi-LLM provider abstraction (Anthropic, Bedrock, Vertex, Azure OpenAI); LTR training; Path B (production monitoring, bandits, shadow validation) |

If a CLAUDE.md statement conflicts with the canonical release matrix, the matrix wins — flag the drift in your PR.

## Active Work — Read This First

**Current focus:** See [`state.md`](state.md). Always read `state.md` first to know what branch you're on, what just shipped, what's in flight, and what's queued.

**`state.md` is a one-page snapshot, not a log.** It holds current focus, the **last 5 merges as one-liners**, in-flight/queued work, Alembic head, and known debt — and must stay loadable in a single `Read` call (the Read tool caps at 256 KB; the file is size-gated by a pre-commit hook at 60 KB). The append-only feature-merge narrative + chained execution-context history lives in [`state_history.md`](state_history.md). **New merge entries land in `state_history.md`, NOT `state.md`.** When you finalize a feature: prepend its one-liner to `state.md`'s "Last 5 merges", drop the now-6th row, and add the full reasoning entry to `state_history.md`. The canonical record is always `git log`; `state_history.md` is the human-readable trail.

**Never write a plain-text operator domain, sub-domain, or private-host IP into `state.md` / `state_history.md`** — these are public files. Use a human-readable placeholder (`<operator-es-cluster>`, `<corp-proxy>`, `<internal-host>`) or an RFC-reserved example name (`foo.example`, `bar.test`); **never encode/obfuscate** a real name (reversible encoding is not redaction). This is enforced by the `internal-domains-guard` pre-commit hook + the `internal domains guard` job in [`secrets-defense.yml`](.github/workflows/secrets-defense.yml), which fail the commit/PR if a non-allowlisted domain or private IP appears; genuinely-public domains go in [`scripts/allowed_public_domains.txt`](scripts/allowed_public_domains.txt). Full policy: [`docs/04_security/internal-domain-hygiene.md`](docs/04_security/internal-domain-hygiene.md).

## Compressed Context First

Before starting any task, read these two files first:

- [`architecture.md`](architecture.md) — high-level system design, boundaries, critical flows, and pointers into the topical docs under `docs/01_architecture/`
- [`state.md`](state.md) — current branch reality, last 5 merges, active priorities, Alembic head, known fragility (one-page snapshot; deeper merge history in [`state_history.md`](state_history.md))

Use them as the default fast-path context. Fall back to deeper exploration (`docs/01_architecture/<topic>.md`, individual feature specs in `docs/00_overview/planned_features/`) only when the task requires file-level implementation detail or verification.

After completing a task, evaluate whether documentation needs updating:

- `state.md` — update if: the active branch changed, new features were completed, priorities shifted, new debt was introduced, or the Alembic head moved. Keep it a snapshot: refresh the "Last 5 merges" one-liners (newest-first, drop the oldest) and move the full merge narrative to `state_history.md`. A pre-commit hook fails the commit if `state.md` exceeds 60 KB.
- `architecture.md` — update if: new services/layers were added, new data flows were introduced, design decisions were made, invariants changed, or the topical docs in `docs/01_architecture/` got a new entry
- `CLAUDE.md` — update if: new conventions, rules, environment variables, or build commands were added; or if a release crossed a maturity boundary that activates new rules (e.g., multi-tenancy rules below being activated)
- `docs/03_runbooks/` — add or update if new ops procedures, deployment steps, or troubleshooting needed

## Repository Structure

```
backend/
  app/
    api/          # FastAPI routers — health.py (/healthz), v1/* (/api/v1/<resource>), webhooks/* (/webhooks/github)
    core/         # settings, logging, request-id middleware, error envelope
    db/
      base.py     # Declarative Base
      session.py  # async engine, async_sessionmaker, get_db dependency
      models/     # SQLAlchemy ORM models — none in MVP1; arrive with feature_specs
      repo/       # repository functions (one file per aggregate; arrive with feature_specs)
    services/     # use-case orchestrators (study lifecycle, judgment generation, digest, PR worker)
    domain/       # pure business logic — search-space rules, study state machine, query rendering
    adapters/     # engine adapters (MVP1: ElasticAdapter for ES + OpenSearch)
    llm/          # OpenAI-compatible client + capability check + provider abstraction (backlog: native non-OpenAI provider SDKs)
    git/          # Git provider clients (MVP1: GitHub; MVP3: + GitLab + Bitbucket)
  workers/        # Arq WorkerSettings + job functions (run_trial, generate_digest, open_pr — arrive with their owning features)
  tests/
    unit/         # pure logic, no DB, no network
    integration/  # DB-backed; some require running ES/OpenSearch (use docker compose service containers in CI)
    contract/     # endpoint shape + error code assertions
ui/
  src/app/        # Next.js App Router pages — / (placeholder MVP1; replaced by feat_studies_ui)
  src/__tests__/  # vitest unit/component tests
  tests/e2e/      # Playwright end-to-end (lands with feat_studies_ui)
worker/           # placeholder — RelyLoop's worker code lives in backend/workers/; this dir is a tech-stack convention slot
migrations/
  alembic.ini     # at repo root (script_location = migrations)
  env.py
  script.py.mako
  versions/       # Alembic revision files (0001_baseline.py is the first)
prompts/          # Jinja2 templates for LLM calls (judgment_generation.user.jinja, digest_narrative.user.jinja, orchestrator.system.md)
templates/        # query-template definitions (lands with infra_adapter_elastic)
samples/          # tutorial sample data (lands with chore_tutorial_polish)
scripts/
  install.sh      # auto-generates required + optional secrets, then docker compose up -d
  check-conventional-commit.sh   # commit-msg pre-commit hook
docs/
  00_overview/    # umbrella spec (relyloop-spec.md), implemented_features/<YYYY_MM_DD>_<slug>/
  01_architecture/# topical arch docs: tech-stack, system-overview, data-model, deployment, api-conventions, adapters, llm-orchestration, optimization, ui-architecture, agent-tools, apply-path, mvp1-overview
  02_product/     # mvp1-user-stories.md + planned_features/<feature>/
  03_runbooks/    # local-dev.md (and per-feature runbooks as features ship)
  05_quality/     # testing.md (test-layer convention + coverage gate)
  08_guides/      # tenant-facing walkthrough guides (lands later)
```

**Planned-features folder naming:** new folders under `docs/00_overview/planned_features/` use a single-axis work-type prefix: `feat_`, `infra_`, `chore_`, `bug_`, or `epic_`. See [feature_templates/README.md](docs/00_overview/planned_features/feature_templates/README.md). Existing MVP1 folders already follow this convention.

## Absolute Rules — Never Violate

1. **Never commit directly to main.** Always use a feature branch + PR. CI gates merges; merging to main is the deploy trigger when remote staging exists.

2. **Secrets via mounted files, never bare env vars.** RelyLoop's Pydantic Settings reads `*_FILE`-suffixed env vars (e.g., `OPENAI_API_KEY_FILE=/run/secrets/openai_key`) and resolves the file content. **Bare env vars (`OPENAI_API_KEY=sk-...`) are NOT supported** — they appear in container `inspect`, logs, and `ps` output, defeating the secrets-management purpose. The `.env` file at repo root is for non-secret Compose overrides only (e.g., `OPENAI_BASE_URL`, `ES_HEAP_SIZE`). Real secrets live in `./secrets/<name>` files mounted as Docker secrets. See [`docs/01_architecture/deployment.md` §"Secrets"](docs/01_architecture/deployment.md) and `infra_foundation` FR-3.

3. **Never call OpenAI directly when the LLM abstraction exists.** MVP1 ships a thin `openai` SDK client pointed at `OPENAI_BASE_URL`; once the multi-provider `BaseChatModel` abstraction lands (backlog), every LLM call MUST go through it (no `openai.AsyncClient(...)` in services). MVP1 services may use the SDK directly while the abstraction is still scoped — but always read `OPENAI_BASE_URL` and `OPENAI_MODEL` from `Settings`, never hardcode model names. See [`docs/01_architecture/llm-orchestration.md`](docs/01_architecture/llm-orchestration.md).

4. **Never bypass the engine adapter Protocol.** Engine-specific code lives ONLY in `backend/app/adapters/<engine>.py`. The orchestrator, study runner, evaluator, and UI consume the unified `SearchAdapter` Protocol per [`docs/01_architecture/adapters.md`](docs/01_architecture/adapters.md). No `elasticsearch.AsyncElasticsearch(...)` instances outside the adapter module. This rule activates the moment `infra_adapter_elastic` lands; until then, the adapter Protocol is the spec, not the code.

5. **All Alembic migrations must include `downgrade()` and round-trip cleanly.** Verify with `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` before merging. The MVP1 baseline is `0001_baseline` — the empty migration that registers `alembic_version`; subsequent feature migrations build on it.

6. **`/healthz` is unauthenticated by design.** It's an operator-facing probe, unprefixed (not under `/api/v1/`), and reports subsystem status. Never gate it behind auth. The shape is documented in [`infra_foundation/feature_spec.md`](docs/00_overview/implemented_features/2026_05_09_infra_foundation/feature_spec.md) §7.3 — any change requires a spec patch first. When TLS + auth land (TLS via Caddy is a GA-v1 hardening item; multi-tenant auth is in the backlog), `/healthz` stays open via the reverse proxy's localhost or internal-network ACL.

7. **Conventional Commits format is enforced** (per `infra_foundation` FR-6). Pre-commit `commit-msg` hook validates the message against `^(feat|fix|chore|docs|infra|refactor|test|style|perf|build|ci)(\([a-z0-9-]+\))?(!)?:`. Never bypass with `--no-verify` or `-n`. If a hook fails, fix the message; don't skip. **Every commit MUST also carry a DCO `Signed-off-by:` trailer — always commit with `git commit -s`** (the `commit-msg` hook `scripts/check-dco-signoff.sh` + the `dco.yml` CI gate both reject commits without it; RelyLoop uses DCO instead of a CLA — see [`CONTRIBUTING.md`](CONTRIBUTING.md) §"Developer Certificate of Origin"). `git config format.signoff true` does NOT help — that setting only applies to `git format-patch`, not `git commit`, so `-s` (or `git commit --amend -s --no-edit` to backfill) is the only reliable path. The `/impl-execute` and `/bug-fix` skills already pass `-s`; this rule is the guardrail for manual commits made outside those skills.

8. **Never hardcode LLM model names in service code.** Always read from `Settings.openai_model` (judgments + digest) or `Settings.openai_model_chat` (chat orchestrator). Floating tags like `"gpt-4o"` (no date) are forbidden — CI rejects them. All persisted artifacts (judgments, digests) capture the exact model identifier (`openai:gpt-4o-2024-08-06`) for lineage.

9. **Never implement plan stories manually — always use `/impl-execute`.** When an approved implementation plan exists, execute its stories by invoking `.claude/skills/impl-execute/SKILL.md` (e.g., `/impl-execute path/to/implementation_plan.md --all`). Even after context compaction or conversation resumption — the skill contains mandatory post-implementation steps (test coverage audit, deferred work extraction, tangential observations sweep, guide impact assessment, final cross-model review, finalization) that are silently skipped when stories are implemented manually. If you find yourself about to write code from a plan without having invoked `/impl-execute`, stop and invoke the skill instead.

10. **Never log or expose secrets.** API keys (`openai_api_key`), per-repo GitHub PATs (resolved from `./secrets/<config_repos.auth_ref>` — see `docs/04_security/github-token-handling.md`), Postgres password — never in log lines (including structured `extra={}`), never in API responses, never in error messages. The capability-check WARN logs (FR-7) include the failing endpoint URL but never the key. When MVP2 adds the structlog `SensitiveFieldScrubber`, the canonical key list lives in `backend/app/core/log_scrubber.py`.

11. **Per-route LLM/network calls inside `/healthz` must respect the 200ms timeout.** The health endpoint orchestrates 5 parallel subsystem probes via `asyncio.wait_for(probe(), timeout=0.2)` so total response stays under 500ms p99. Never add a probe that synchronously waits on a slow upstream — wrap it in the timeout, return `down`/`unreachable` on TimeoutError. The OpenAI capability check (FR-7) does NOT run inside `/healthz` — it runs once at startup as a fire-and-forget task and `/healthz` reads the cached result from Redis.

**Activates at MVP3 (Observable):** `audit_log` table + Postgres immutability trigger + canonical event catalog. When MVP3 lands, add an Absolute Rule: every state-mutating endpoint or service function must call `create_audit_event()` in the same transaction as the primary mutation (before `db.commit()`); see [`docs/01_architecture/data-model.md`](docs/01_architecture/data-model.md) §"Forthcoming: audit_log".

**Activates when multi-tenancy is promoted from backlog:** Multi-tenancy. When multi-tenancy ships, add an Absolute Rule: every DB write on a tenant-scoped table must include `tenant_id`; admin endpoints bypass tenant scoping but require explicit role check via `require_role({"platform_admin"})`. Until then, RelyLoop is single-tenant — no `tenants` table, no `tenant_id` column, no membership check.

## Build, Test, and Lint Commands

```bash
# Backend
make fmt                  # ruff format (auto-fix; run before lint)
make lint                 # ruff check
make typecheck            # mypy --strict
make test-unit            # pytest backend/tests/unit/ (no DB, no Docker required)
make test-integration     # pytest -m integration backend/tests/integration/ (requires running Postgres + ES + OpenSearch)
make test-contract        # pytest backend/tests/contract/
make test                 # all three layers in sequence

# Frontend (run from repo root or cd ui)
cd ui && pnpm install
cd ui && pnpm lint        # ESLint Next.js + security
cd ui && pnpm typecheck   # tsc --noEmit --strict --noUncheckedIndexedAccess
cd ui && pnpm test        # vitest run
cd ui && pnpm build       # Next.js production build (catches SSR issues)

# Stack lifecycle (Docker Compose)
make up                   # bash scripts/install.sh — generates secrets, then docker compose up -d
make down                 # docker compose stop
make logs                 # docker compose logs -f api worker
make reset                # docker compose down -v && rm -rf ./data (FORCE=1 to skip prompt)

# Migrations (run from repo root; .venv/bin/alembic ensures the project venv)
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head   # round-trip verify
make migrate              # alembic upgrade head + init optuna schema
make migrate-create name=<slug>   # alembic revision --autogenerate -m "<slug>"

# Pre-commit
.venv/bin/pre-commit install --hook-type commit-msg --hook-type pre-commit
.venv/bin/pre-commit run --all-files
```

**Ports:**
- API: `127.0.0.1:8000`
- UI: `127.0.0.1:3000` (Compose service `ui`, rebuilt by `make up`; for hot-reload during frontend work, stop the service with `docker compose stop ui` and run `cd ui && pnpm dev` instead)
- Postgres: internal only (`postgres:5432` on the Compose network; not bound to host)
- Redis: internal only (`redis:6379`)
- Elasticsearch: `127.0.0.1:9200`
- OpenSearch: `127.0.0.1:9201`
- Apache Solr: `127.0.0.1:8983` (MVP2 — `solr` Compose service, SolrCloud mode w/ embedded ZooKeeper, `SOLR_MODULES=ltr` loads the LTR module. Security is **disabled** for local dev — same posture as the local ES/OpenSearch services per "Common Pitfalls"; Solr's default is no `security.json`, so admin + query calls are unauthenticated. The `SolrAdapter`'s `solr_basic`/`solr_apikey` support is for real operator clusters that DO enable auth.)
- Local LLM (MVP2): OFF by default. `RELYLOOP_LLM=ollama` is **native-first** (`feat_bundled_llm_native_detection`) — install.sh's `resolve_native_ollama` (`scripts/lib/relyloop_native_llm.sh`) probes the host for a native Ollama on `:11434` and, if found, wires api/worker `OPENAI_BASE_URL` at `http://host.docker.internal:11434/v1` (Metal-fast on macOS; api/worker carry `extra_hosts: host.docker.internal:host-gateway` for Linux) + a sentinel `openai_key`; if not found it prints guidance and comes up LLM-free. `RELYLOOP_LLM=ollama-docker` runs the slow in-network `ollama` Compose service (`bundled-llm` profile, no host port, CPU-only on macOS — the shipped `feat_bundled_local_llm` container). An explicit `OPENAI_BASE_URL` always wins (no native wire, no container).

**Install-time env vars** (read from shell or `.env` by `scripts/install.sh`, parsed before any `docker compose` call): `RELYLOOP_ENGINES` (`es,os,solr` subset → `COMPOSE_PROFILES`), `RELYLOOP_{ES,OS,SOLR}_VERSION` (pin engine image tags), `RELYLOOP_LLM` (`ollama` → native-first host-Ollama detection; `ollama-docker` → `bundled-llm` profile), `OLLAMA_MODEL` (model tag). Bare env vars are fine here — these are non-secret Compose overrides (Absolute Rule #2 applies to secrets only).

**DB bootstrap for fresh DB:** `make migrate` (creates `alembic_version` table at the head revision; subsequent feature migrations add their tables).

## Environments

MVP1 has one environment: local development on a developer's laptop or in CI. Production-style install (TLS via Caddy + Let's Encrypt, managed Postgres/Redis, AWS managed OpenSearch) lands with GA v1 hardening; SSO + multi-tenant remain in the backlog.

| Context | `ENVIRONMENT` value | Where it runs | Notes |
|---|---|---|---|
| Local development | `development` (default) | Developer machine via `make up` | All defaults; no auth; no TLS |
| CI (GitHub Actions) | `development` | GitHub Actions runners with service containers | Same toolchain as local; backend tests use a service-container Postgres + ES + OpenSearch |
| Staging (MVP3+) | `staging` | TBD operator deployment | TLS on; trusted-network deployment |
| Production (post-GA) | `production` | TBD operator deployment | TLS + SSO + multi-tenant; arrives with the auth surface |

There is no remote staging in MVP1 — every contributor runs the stack locally. The umbrella spec describes this as "evaluation-only" and the README labels it "alpha."

### CI/CD Workflows

Single workflow in MVP1: `.github/workflows/pr.yml`. See [`docs/03_runbooks/local-dev.md`](docs/03_runbooks/local-dev.md) for branch protection setup.

| Workflow | Trigger | Purpose |
|---|---|---|
| **pr.yml** | `pull_request` to main + `push` to main | Backend: lint + format-check + mypy + pytest (unit/integration/contract) + 80% coverage gate. Frontend: lint + tsc + vitest + Next.js build. Docker: `buildx build` for `relyloop/api` (no push). |

Additional workflows (deploy-staging, release, image-publish) ship at MVP3 + GA v1.

**Release tag format:** `v0.0.1` (placeholder until MVP1 tagged as `v0.1.0`). SemVer 2.0; the leading zero signals pre-1.0 instability.

## Key Conventions

### Settings & Secrets

- Single `Settings` class in [`backend/app/core/settings.py`](backend/app/core/settings.py) using `pydantic-settings` v2.
- Required secret fields use `*_FILE` env vars and `@cached_property` accessors that read the mounted file content. Required secrets raise `SettingsError` on missing/empty content; optional secrets return `None` and the API logs a startup warning.
- Bare env vars are accepted ONLY for non-secret config (`OPENAI_BASE_URL`, `OPENAI_MODEL`, `REDIS_URL`, `ES_HEAP_SIZE`).
- Use `get_settings()` (lru_cache'd) anywhere settings are needed; never instantiate `Settings()` directly.

### Repository Layer (when models land)

- One file per aggregate in `backend/app/db/repo/`.
- All repo functions accept `db: AsyncSession` as first argument.
- `db.flush()` for staging changes; the caller (service or API endpoint) commits.
- Export every new function via `backend/app/db/repo/__init__.py` `__all__`.
- Return `Model | None` for single-fetch by ID; raise `RESOURCE_NOT_FOUND` (or feature-specific code) at the service/router layer.

### Domain Layer

- Pure business logic — no DB access, no I/O, no async.
- Located in `backend/app/domain/` with subdirectories by concern (`adapters/` for the SearchAdapter Protocol shape, `study/` for state machine, `query/` for parameter validation, etc.).
- Functions are deterministic and unit-testable without fixtures.

### Service Layer

- Services are async and accept `db: AsyncSession` + typed arguments.
- Each long-running service creates a `job_run` record at start (when `feat_study_lifecycle` lands the schema); calls `complete_job_run()` or `fail_job_run()` in `try/finally`. Never leave a job run in `running` state.
- Services compose repos + domain logic + integrations (engine adapter, LLM client, Git provider).

### API Layer

- **Business endpoints:** `/api/v1/<resource>` prefix per [`docs/01_architecture/api-conventions.md`](docs/01_architecture/api-conventions.md).
- **Operator endpoints:** unversioned at root (`/healthz`).
- **Webhook endpoints:** `/webhooks/<provider>` (e.g., `/webhooks/github` lands with `feat_github_webhook`). Idempotency required; signature verification before payload processing.
- Standard error envelope: `{ "detail": { "error_code": "<MACHINE_READABLE>", "message": "<human>", "retryable": <bool> } }`. Exception handlers in `backend/app/api/errors.py` translate `HTTPException`, `RequestValidationError`, and generic `Exception` into the envelope.
- Cursor pagination only — no offset/limit. `?cursor=<opaque>&limit=<n>` (default 50, max 200). All list endpoints emit `X-Total-Count` header. See api-conventions.md §"Pagination".

### Migrations

- Sequential numeric revision IDs (`0001_baseline`, `0002_<slug>`, ...). Pin via `alembic revision --rev-id <NNNN>`.
- Every migration has a `downgrade()` implementation. Empty pass is acceptable for the baseline; subsequent migrations must reverse their changes cleanly.
- After writing: `alembic upgrade head`, then `alembic downgrade -1 && alembic upgrade head` to verify round-trip.
- DB revision guard at API startup is **MVP2+** — MVP1 doesn't fail-fast on pending migrations (would crash the dev stack on first boot before `make migrate` runs).
- Revision IDs are ≤32 chars (Alembic's `version_num` column is `VARCHAR(32)`); the `0001_baseline` convention stays well under.

### Generated artifacts

`ui/openapi.json` (offline OpenAPI snapshot), `ui/src/lib/types.ts`
(generated by `openapi-typescript` from the snapshot),
`ui/public/docs/*.md` (copied from `docs/08_guides/`), and the
**website Guides pages** — `website/docs/guides/**` +
`website/docs/assets/guides/**` + the `website/mkdocs.yml` managed
nav fragment (generated by `website/scripts/build_guides.py` from
`ui/public/guides/<slug>/*` + `docs/08_guides/*.md`) — are
**CI-freshness-gated**. The `generated-artifacts-fresh` job in
`pr.yml` + the standalone `copy-docs-freshness` and
`build-guides-freshness` workflows regenerate them on every PR and
fail on `git status --porcelain` drift. The single canonical fix for
ALL four gates:

```bash
bash scripts/regen-generated-artifacts.sh
```

Note: the website Guides `*.mp4` videos are a **best-effort** artifact —
the `build-guides-freshness` gate excludes them (the Python-only deploy
runner cannot transcode); regenerate MP4s locally with
`python website/scripts/build_guides.py --transcode` (needs `ffmpeg`).
Never hand-edit the three generator-owned dirs above — re-running prunes
anything the generator didn't emit. Other generated files are listed in
`ui/.prettierignore` — the generator is the source of truth, do not run
prettier on them. See
[`docs/05_quality/testing.md` §"Generated-artifact freshness gates"](docs/05_quality/testing.md)
and the [website-guides-regen runbook](docs/03_runbooks/website-guides-regen.md).

## Testing Conventions

| Layer | Location | DB? | Notes |
|---|---|---|---|
| Unit | `backend/tests/unit/` | No | Pure functions, mocked externals (httpx, openai, asyncpg); fast |
| Integration | `backend/tests/integration/` | Yes | Marked `@pytest.mark.integration`; DB-backed; some require running ES/OpenSearch |
| Contract | `backend/tests/contract/` | No | Assert response shapes against FastAPI's OpenAPI schema; verify error codes |
| E2E | `ui/tests/e2e/` | Via running stack | Playwright; lands with `feat_studies_ui`; **must use real browser interactions via `page` object — `page.route()` mocking is forbidden** |

- Every new endpoint needs a contract test asserting response shape + error codes.
- Every new service function needs an integration test (DB-backed; LLM mocked via fixture).
- Every new domain function needs unit tests in `backend/tests/unit/domain/`.
- Every new webhook handler needs an integration test asserting idempotency (when webhooks land at `feat_github_webhook`).
- E2E tests for new user-facing flows (when UI lands at `feat_studies_ui`).
- **Test completeness rule:** Unit tests alone are not sufficient for features that touch DB, API, or frontend. A feature is not complete until it has tests at every layer it touches (domain → unit, service → integration, endpoint → contract, UI → E2E).
- Coverage gate: 80% on backend Python (MVP1). Configured via `[tool.coverage.report].fail_under = 80` in `pyproject.toml`.

### Integration Test Mocking Policy

- **Integration tests only mock external services** (OpenAI, GitHub, the engine HTTP API when not exercising a real cluster). Never mock internal code — DB, repos, services, domain logic all run for real against the test database.
- Use `monkeypatch` to replace external client methods (e.g., `openai.AsyncClient.chat.completions.create`).
- The CI test database is a service-container Postgres provisioned in the GHA workflow.

### E2E Testing Rules (when E2E lands)

- **No `page.route()` mocking of backend endpoints.** Tests run against the real backend at `localhost:8000` with the real database.
- **Tests must exercise the browser layer.** Use Playwright's `page` object for real browser interactions (navigate, fill forms, click buttons, assert DOM). API calls via `request` are acceptable for **test setup** (creating clusters, seeding query sets, generating judgments) but **assertions must verify browser-visible behavior**.
- Pattern: setup via API helpers → seed `localStorage` with test config via `page.addInitScript()` → navigate and interact via `page`.

## Data Model — Key Tables

**MVP1 has no business tables yet.** Only `alembic_version` exists after `infra_foundation` ships. Each subsequent feature adds its own tables:

| Feature | Tables it adds | Purpose |
|---|---|---|
| `infra_adapter_elastic` | `clusters`, `config_repos` | Cluster registry + Git repo registry |
| `feat_study_lifecycle` (schema epic) | `query_sets`, `query_templates`, `judgment_lists`, `studies`, `trials`, `proposals` | The full study/trial schema (7 tables) |
| `feat_llm_judgments` | `judgments` (child of `judgment_lists`) | Per-(query, doc) LLM ratings |
| `feat_digest_proposal` | `digests` (1:1 with `studies`) | Study-end summaries |
| `feat_chat_agent` | `conversations`, `messages` | Chat history for the agent UI |

See [`docs/01_architecture/data-model.md`](docs/01_architecture/data-model.md) for column-level detail.

**Database conventions** (apply to every new table):

- **UUIDv7** primary keys (lexicographically sortable, time-ordered, generated client-side).
- All timestamps `TIMESTAMPTZ`, stored UTC.
- snake_case table and column names.
- JSONB for flexible structured fields (settings, params, metrics, payloads).
- Soft delete via `deleted_at` on user-facing tables; hard delete on internal append-only tables (e.g., `trials`).
- All foreign keys explicit; no implicit relationships.
- Indexes on `(tenant_id, created_at)` for tenant-scoped tables — **backlog only**; RelyLoop is single-tenant through GA v1 — no `tenant_id` column.

## Frontend Conventions

### Stack

- Next.js 16 App Router (TypeScript, Turbopack) — pages in `ui/src/app/`
- **shadcn/ui** for UI primitives (components copied into the repo, not an npm dependency — fully customizable)
- **Tailwind CSS** for styling
- **TanStack Query** for server state (caching, retries, optimistic updates, mutations)
- **React Hook Form + Zod** for forms (Zod schemas reusable for API request validation)
- **Recharts** for visualizations (parameter importance bars, trial scatter plots, metric trends)
- **Streaming chat:** native `fetch()` with `ReadableStream` for SSE-framed-body-over-POST; `EventSource` is GET-only and the chat surface POSTs the user message in the body. See [`docs/01_architecture/ui-architecture.md` §"Streaming chat"](docs/01_architecture/ui-architecture.md).
- Dependency manager: pnpm

### Pages and Routing

- `/` — placeholder in MVP1 (`infra_foundation` Story 1.3); replaced by `feat_studies_ui` shell
- `/studies` and `/studies/[id]` — landing in `feat_studies_ui`
- `/proposals` and `/proposals/[id]` — landing in `feat_proposals_ui`
- `/chat` — landing in `feat_chat_agent`
- `/judgments/[id]` — landing in `feat_llm_judgments`
- No admin routes through GA v1 (admin model is in the backlog)

### Common UI Patterns (when UI features land)

- Detail modals (not inline expansion) for row drill-down
- Cursor pagination controls (Prev / Next / page-size selector); never offset/limit
- Filter chips and `<select>` dropdowns with hardcoded option arrays — every option list whose wire value is sent to the backend MUST be grounded in a backend allowlist (enum, `Literal[...]`, `frozenset`, Pydantic `Field(pattern=...)`, or DB CHECK). See "Common Pitfalls" below for the canonical drift failure mode.

### Enumerated Value Contract Discipline

When you add a `<select>`, filter dropdown, status badge, sort control, or any frontend array of options whose values flow to the backend:

1. Identify the backend allowlist: enum, `Literal[...]`, `frozenset`, or `Field(pattern=...)`.
2. `grep` the cited backend file to enumerate the exact wire values.
3. Compare character-for-character: every frontend option value must exist in the backend allowlist; every backend value the user should see must be in the frontend array.
4. Add a source-of-truth comment above the array: `// Values must match backend/app/db/models/<file>.py <Symbol>` so future edits don't silently drift.
5. **For `<DataTable>` columns:** each `filter: { kind: 'enum' | 'fk-select', ... }` entry MUST carry a `sourceOfTruth: 'backend/...'` field pointing at the canonical backend Literal or FK column. The Story 2.13 lint guard at [`ui/src/__tests__/components/common/data-table-column-discipline.test.tsx`](ui/src/__tests__/components/common/data-table-column-discipline.test.tsx) scans every `*.column-config.{ts,tsx}` file and fails the test suite if `sourceOfTruth` is missing, doesn't start with `backend/`, or if `wireValues` is an inline array rather than an identifier imported from `@/lib/enums`. See [`docs/01_architecture/ui-architecture.md` §"DataTable primitive"](docs/01_architecture/ui-architecture.md) for the full discipline.
6. **For form components (`chore_form_dropdown_primitive`, 2026-05-18):** form `*.tsx` files under `ui/src/components/` (excluding `__tests__/`, `common/`, and `*.column-config.{ts,tsx}`) MUST NOT inline `<SelectItem value="<literal>">` for any wire value that exists in `ui/src/lib/enums.ts`. Use the `*_VALUES.map(...)` pattern with an import from `@/lib/enums`. The vitest lint guard at [`ui/src/__tests__/components/common/form-select-discipline.test.tsx`](ui/src/__tests__/components/common/form-select-discipline.test.tsx) catches the regression. Escape hatch (rare, needs reviewer ack): a top-of-file `// no-enum-import: <non-empty reason>` comment. Form-side FK pickers MUST use `<EntitySelect>` from [`ui/src/components/common/entity-select.tsx`](ui/src/components/common/entity-select.tsx) — see [`docs/01_architecture/ui-architecture.md` §"Form dropdown primitive"](docs/01_architecture/ui-architecture.md).

**Why:** Plausible-sounding guesses (e.g., a "drafting" stage that doesn't exist) produce 422 VALIDATION_ERROR or silent zero-result filters that TypeScript, lint, and unit tests don't catch.

## Common Pitfalls

- **Do not** add a CI gate that runs against a real cloud (AWS/GCP) in MVP1. CI must be hermetic — only services CI itself can spin up. ES + OpenSearch run as service containers in the GHA job, not against a managed cluster.
- **Do not** wire Langfuse, ClickHouse, or SigNoz into MVP1 Compose. Per [`docs/01_architecture/deployment.md` §"Reserved for later releases"](docs/01_architecture/deployment.md), those services activate at MVP2.
- **Do not** require an OpenAI key or any per-repo GitHub PAT to boot the stack. The OpenAI key is an optional pre-feature secret — empty mount file is allowed; the API logs a WARN and `/healthz` reports `subsystems.openai: missing_key`. GitHub PATs are configured per `config_repo` (lazy — only when an operator registers a repo), not at boot. Only Postgres password + database URL are boot-blocking.
- **Do not** support raw env vars (`OPENAI_API_KEY=sk-...`) as a fallback for the secrets-via-files pattern. Bare env vars are visible in `docker inspect`, container logs, and `ps` — they defeat the purpose. The `_FILE` mounted-secret pattern is the ONLY supported path. (See Absolute Rule #2.)
- **Do not** install ES + OpenSearch with security plugins enabled in the local Compose. Per deployment.md, local dev disables security; production-mode security configuration is a separate (MVP3+) concern.
- **Do not** add weekly or per-request rate limiting in MVP1. Single-tenant on a laptop = no production load; rate limiting is unwarranted infrastructure. The `RATE_LIMITED` (429) error code is reserved per api-conventions.md but not emitted until multi-tenancy ships (backlog).
- **Do not** add a migration without `downgrade()`. (See Absolute Rule #5.)
- **Do not** call OpenAI from a service when the LLM abstraction exists. (See Absolute Rule #3 — applies once the multi-provider abstraction ships (backlog); in MVP1 services may use the SDK directly but always read model + base URL from `Settings`.)
- **Do not** call engine clients directly from a service. Always go through the adapter Protocol. (See Absolute Rule #4 — activates when `infra_adapter_elastic` lands.)
- **Do not** write frontend option/enum/dropdown values from memory or by guessing. Every `<select>` option list, filter dropdown, status badge variant, and sort-key literal the frontend sends to the backend must be grounded in a concrete backend source file. (See "Enumerated Value Contract Discipline" above.)
- **Do not** edit a file and then `git mv` it in the same commit. `git mv old new` writes the *last-committed blob* of `old` into the index entry for `new` — any prior working-tree edits to `old` end up unstaged at the new path (visible only as the lowercase "M" in `git status`'s `RM` indicator) and `git add <specific-file> && git commit` will silently drop them. **Order:** `git mv` first, then edit at the new path, then `git add <new-path>`. Verify with `git diff --cached --stat` before commit — every file you intended to edit must show non-zero `+`/`-` counts.
- **Do not** suppress the WARN log from a failed OpenAI capability check. The log is the operator's signal that LLM-dependent features (judgment generation, digest narrative, chat tool dispatch) will degrade or refuse. Cache the partial result; surface in `/healthz`; never silently treat the endpoint as healthy.
- **Do not** INSERT or UPDATE the `search_vector` column on any of the six tables that own one (clusters, studies, query_sets, query_templates, judgment_lists, conversations). Postgres maintains it via `GENERATED ALWAYS AS … STORED` — any write attempt fails with `cannot insert into column "search_vector"`. The SQLAlchemy ORM models intentionally do NOT declare the column for this reason. See [`docs/01_architecture/data-model.md` §"Full-text search vectors"](docs/01_architecture/data-model.md).
- **Do not** treat a demo reseed with `status == "complete"` and a non-empty `scenarios_skipped` as a failure — it's a legitimate **partial completion** (an engine was unreachable, so its scenario skipped). Only `status == "failed"` + `failed_reason == "all_engines_unreachable"` (nothing seeded) is the hard-failure case. The reseed probes each engine before dispatch (`is_engine_reachable`) and skips unreachable engines rather than `ConnectError`-ing the whole run — this is what lets `pr.yml`'s backend job stay green without a Solr service container. See [`docs/03_runbooks/demo-reseed-engine-tolerance.md`](docs/03_runbooks/demo-reseed-engine-tolerance.md).

## Working in sibling worktrees

When an autonomous agent works in a sibling git worktree (e.g., `/private/tmp/relyloop-<slug>`) while the operator's main checkout (`/Users/ericstarr/relyloop`) has the Docker Compose stack running, the shared Docker bind mounts defined in [`docker-compose.yml`](docker-compose.yml) all anchor to the **main worktree**, not the sibling. Writes through a running shared container can land bytes in the wrong worktree silently (for writable mounts) or fail with `EROFS` (for read-only mounts). This was surfaced concretely by the `chore_reconciler_terminal_closed_no_poll` agent run ([PR #216](https://github.com/SoundMindsAI/relyloop/pull/216), merged 2026-05-23), where a migration file written via `docker cp` into a shared container's `/app/migrations/` appeared as an untracked file in the operator's main worktree.

### Compose-anchored host paths

The Compose stack at [`docker-compose.yml`](docker-compose.yml) binds these host paths into one or more service containers. Writes through a running shared container to the in-container target resolve to **the main worktree's** host path.

| Host path | Writability | Service(s) | Failure mode (container-mediated write) |
|---|---|---|---|
| `./migrations/` | writable | `migrate` ([docker-compose.yml:76](docker-compose.yml#L76)), `api` ([docker-compose.yml:119](docker-compose.yml#L119)) | bytes silently propagate to main worktree's `./migrations/` |
| `./alembic.ini` | read-only (`:ro`) | `migrate` ([docker-compose.yml:77](docker-compose.yml#L77)), `api` ([docker-compose.yml:120](docker-compose.yml#L120)) | container-mediated writes fail with `EROFS` / read-only filesystem; the file is anchored to the main worktree but cannot be modified through the shared container |
| `./samples/` | read-only (`:ro`) | `api` ([docker-compose.yml:125](docker-compose.yml#L125)) | container-mediated writes fail with `EROFS` / read-only filesystem; the file is anchored to the main worktree but cannot be modified through the shared container |
| `./data/postgres/` | writable | `postgres` ([docker-compose.yml:28](docker-compose.yml#L28)) | bytes silently propagate to main worktree's `./data/postgres/` |
| `./data/redis/` | writable | `redis` ([docker-compose.yml:40](docker-compose.yml#L40)) | bytes silently propagate to main worktree's `./data/redis/` |
| `./data/repo-clones/` | writable | `api` ([docker-compose.yml:112](docker-compose.yml#L112)), `worker` ([docker-compose.yml:167](docker-compose.yml#L167)) | bytes silently propagate to main worktree's `./data/repo-clones/` |

If you edit `docker-compose.yml`, re-verify the line citations above in the same PR. The unit test at [`backend/tests/unit/docs/test_claude_md_sections.py`](backend/tests/unit/docs/test_claude_md_sections.py) does not enforce line-number freshness — it asserts only that the catalog rows for `./migrations/`, `./alembic.ini`, and `./samples/` do not list `worker`, that the row for `./data/repo-clones/` does list `worker`, and that the section contains no bare `DATABASE_URL=...` env var pointing at a database URL.

### Safe paths

**Direct writes from the sibling worktree's filesystem are always safe.** The `Edit`, `Write`, and `git` tools (and any plain Unix command run outside a container) write to the sibling's own copy of the file. This includes paths whose **base name** matches a Compose bind source: `/private/tmp/<slug>/backend/`, `/private/tmp/<slug>/ui/`, `/private/tmp/<slug>/docs/`, `/private/tmp/<slug>/migrations/0042_foo.py`, `/private/tmp/<slug>/samples/products.json`, and `/private/tmp/<slug>/alembic.ini` are all sibling-local. The Compose stack's bind mounts target the **main worktree's** `./migrations/`, not "any worktree's `migrations/`".

**Writes through an already-running shared Compose service container resolve to the main worktree's bind source** — silently for writable mounts, loudly with `EROFS` for read-only mounts. Forbidden command shapes (whether invoked from a sibling worktree or anywhere else):

- `docker cp <local> <container>:<bind-mounted-path>`
- `docker compose cp <local> <service>:<bind-mounted-path>`
- `docker exec <container> sh -c '... > <bind-mounted-path>'`
- `docker compose exec <service> sh -c '... > <bind-mounted-path>'`

The hazard is the bind source the running container resolves to, not the command form. Any debug stubs created during sibling-worktree work are still subject to the "Local-stub hygiene" rule below.

### Shortcut: `make test-worktree`

Most operators don't need to type the full recipe below — `make test-worktree` from inside a sibling worktree wraps it. The Makefile target invokes [`scripts/run-tests-in-worktree.sh`](scripts/run-tests-in-worktree.sh) which auto-detects the main repo path, validates the DB secret, and spins up the one-shot container. Override the command via `CMD=`:

- `make test-worktree` — runs `uv run pytest backend/tests/unit/ -v` inside the container.
- `make test-worktree CMD="pytest backend/tests/integration -v"` — overrides the in-container command. The script prepends `uv run` automatically (the production image is built `--no-dev`, so dev deps install on-demand via `uv run`).
- `bash scripts/run-tests-in-worktree.sh --dry-run` — print the constructed `docker run` argv without executing it.

See the [`parallel-worktrees.md` runbook](docs/03_runbooks/parallel-worktrees.md) for the human-facing operational guide.

### Running tests against a sibling worktree (one-shot container recipe)

The recipe `make test-worktree` wraps is below — useful for understanding what the script does internally, or for one-off invocations where you want to tweak a flag. Honors Absolute Rule #2: never bare `DATABASE_URL=...` env var, always the `*_FILE`-mounted pattern matching `docker-compose.yml` lines 68 / 95 / 153.

The container runs as the image's default `relyloop` user (UID 1000). The earlier `--user root` + `-e PYTHONDONTWRITEBYTECODE=1` workaround was removed after `bug_dockerfile_venv_root_owned_after_user_switch` shipped — the Dockerfile now switches `USER relyloop` BEFORE the runtime-stage `RUN uv sync --frozen --no-dev`, so the project-package install runs as the unprivileged user from the start and writes `relyloop-0.1.0.dist-info/*` with the correct ownership. `PYTHONDONTWRITEBYTECODE=1` is already set in the image's base `ENV` (`Dockerfile:23`), so no `-e` override is needed.

```bash
# Run from the sibling worktree's root (e.g., /private/tmp/relyloop-<slug>).
# $MAIN_REPO is the operator's main checkout, resolved dynamically — `git
# worktree list` always lists the main worktree first.
MAIN_REPO=$(git worktree list | awk '{print $1; exit}')

# Optional: cluster_credentials.yaml is only present when the operator has
# registered an ES cluster (via scripts/install.sh or manually). When present,
# the api / worker compose services mount it at /run/secrets/cluster_credentials
# (docker-compose.yml lines 102, 160); mirror that here for parity so
# acquire_adapter() and the seed_minimum_for_overlap_probe_real_engine() helper
# resolve credentials correctly inside the one-shot container. When absent, the
# array stays empty and the splice contributes nothing — cluster-credential-
# dependent tests fall back to their existing test-side skip gates.
CLUSTER_CREDS_ARGS=()
if [[ -r "$MAIN_REPO/secrets/cluster_credentials.yaml" && -s "$MAIN_REPO/secrets/cluster_credentials.yaml" ]]; then
  CLUSTER_CREDS_ARGS=(
    -e "CLUSTER_CREDENTIALS_FILE=/run/secrets/cluster_credentials"
    -v "$MAIN_REPO/secrets/cluster_credentials.yaml:/run/secrets/cluster_credentials:ro"
  )
fi

docker run --rm \
  --network relyloop_default \
  -e DATABASE_URL_FILE=/run/secrets/database_url \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password \
  -e RELYLOOP_IN_WORKTREE_CONTAINER=1 \
  -v "$MAIN_REPO/secrets/database_url:/run/secrets/database_url:ro" \
  -v "$MAIN_REPO/secrets/postgres_password:/run/secrets/postgres_password:ro" \
  "${CLUSTER_CREDS_ARGS[@]+"${CLUSTER_CREDS_ARGS[@]}"}" \
  -v "$PWD/CLAUDE.md:/app/CLAUDE.md:ro" \
  -v "$PWD/backend:/app/backend" \
  -v "$PWD/migrations:/app/migrations" \
  -v "$PWD/scripts:/app/scripts" \
  -v "$PWD/pyproject.toml:/app/pyproject.toml:ro" \
  -v "$PWD/uv.lock:/app/uv.lock:ro" \
  -v "$PWD/alembic.ini:/app/alembic.ini:ro" \
  -v "$PWD/docker-compose.yml:/app/docker-compose.yml:ro" \
  -v "$PWD/Makefile:/app/Makefile:ro" \
  -v "$PWD/samples:/app/samples:ro" \
  "relyloop/api:${RELYLOOP_GIT_SHA:-dev}" \
  uv run pytest backend/tests/unit/ -v
```

### Worktree lifecycle (cross-reference)

This section covers the **runtime data path** (what's safe to write to from inside a sibling worktree). For worktree **lifecycle** — audit before launching, spawn parallel test agents with `Agent({ isolation: "worktree" })`, and sweep stale worktrees after a feature merges — see [`impl-execute` SKILL.md](.claude/skills/impl-execute/SKILL.md) Step 0a, Step 6b, and Step 9.3. The two coverages are complementary, not redundant.

### Deferred capabilities

One follow-on capability remains tracked as a deferred-phase idea in the feature's planned-features folder, picked up when the friction recurs:

- [`phase3_idea.md`](docs/00_overview/planned_features/99_backlog/infra_agent_sibling_worktree_isolation/phase3_idea.md) — per-worktree `DATABASE_URL_FILE` override following the `*_FILE`-mounted-secret pattern (locked by D-2 in the spec). Picked up on a migration-collision incident between concurrent worktrees sharing the same Postgres. (Moved to `99_backlog/` 2026-05-29 — phases 1+2 shipped; phase3 is defer-until-incident.)

Phase 2 (capability B, the `make test-worktree` automation) shipped on PR #249 alongside Phase 1 — see the Shortcut subsection above and [`docs/03_runbooks/parallel-worktrees.md`](docs/03_runbooks/parallel-worktrees.md).

## Bug Fix Protocol

When fixing a bug, follow this sequence:

1. **Reproduce first.** Confirm the error exists — read logs, check the endpoint, or run the failing test. Understand the exact failure before changing code.
2. **Trace to root cause.** Don't patch symptoms. If the frontend sends the wrong payload, the fix is in the frontend. If the backend requires a parameter it shouldn't, the fix is in the backend. Identify which layer owns the bug.
3. **Fix at the right layer.** Make the minimal change that addresses the root cause. Don't add defensive fallbacks that mask the real problem.
4. **Add a regression test.** Every bug fix must include at least one test that would have caught the bug. Contract test for API shape issues, unit test for domain logic, integration test for cross-layer issues.
5. **Run the full relevant test suite** (`make test-unit`, `make test-contract`, `make lint`) before pushing. Don't rely on CI alone.
6. **Format before pushing.** Run `make fmt` to avoid CI failures on style.

For ad-hoc fixes that don't warrant `/pipeline` scaffolding, use `/impl-execute --ad-hoc` to ship the change through the standard review/merge ceremony (pre-push gate → push → PR → CI watch → Gemini adjudication → optional GPT-5.5 review). See `.claude/skills/impl-execute/SKILL.md` "Ad-hoc mode behavior."

## Tangential discoveries — fix inline by default, defer rarely

When working on any task (feature, bug fix, refactor, doc update), you will routinely notice **other** problems that aren't part of the current scope: a pre-existing test failure that you waved through, a flaky test you re-ran without investigating, an infrastructure gap that forced you to defer coverage, a stale runbook entry, a dead-code branch, etc.

**The default is: fix it inline on the current branch.** Capture-as-idea-file is the exception, reserved for cases where inline fix is genuinely impossible (different subsystem + significant LOC, requires a product decision, requires an operator-environment change you can't make). The historical failure mode at this project has been **over-deferring** — agents file an idea file when the actual fix is one line of YAML or a single-character grep pattern correction, then the idea sits in `02_mvp2/` for weeks while the bug stays live. **Don't do that.** Fix it now and note the tangential discovery in the commit body.

**The ordering of operations when you notice a tangential issue:**

1. **Write down the implementation path in two-three sentences** (which file, which line, what edit). If you can't, you don't understand the issue well enough yet — keep reading code.
2. **Estimate the path in minutes.** If you can't estimate concretely (file count × diff size × verification cycles), the "high overhead" intuition is probably wrong; just try it and abort if you cross 60 minutes.
3. **If <60 minutes AND no cross-subsystem fork AND no product/operator decision → fix inline.** Commit on the current branch with a message that names the tangential discovery (e.g. `fix(scope): tangential — <short description> (noticed during <current-work>)`). Mention it in the PR body as "Also fixes: <one-line>" — that's the audit trail, not an idea file.
4. **Only if inline fix fails one of the gates above → capture as idea file** per the recipe below. Most tangential discoveries do NOT survive these gates; that's the point.

**Canonical example of the right reflex** — during `infra_solr_smoke_stability` PR #383, the first CI run surfaced a Solr filesystem-perms crash that the spec's locked lever cascade never anticipated. The fix was three lines of YAML (`mkdir + chown + make up`). The agent's first instinct was to file `infra_solr_smoke_data_dir_perms/idea.md` as a follow-up. **Wrong reflex.** Deferring would have meant another full PR cycle (idea-preflight → spec-gen → impl-plan-gen → impl-execute) for a fix that took 30 seconds to write. The right move — and what shipped — was the inline commit with a D-log entry on the spec acknowledging the failure-mode discovery. The user's directive when they caught the deferral: "stop pushing off fixing these... fix now."

**Anti-pattern to recognize in yourself:** "I'll just file this for later." The "later" agent has less context than you have right now. They'll have to re-derive what you already know, re-read the same code, re-run the same failing CI to confirm the symptom. That cost is real and almost always larger than the cost of just fixing it now. **Default lean: implement-now.**

When inline fix genuinely doesn't apply (the rubric below sends you to "Idea file"), then file one:

1. Pick a folder name with the right prefix per [`docs/00_overview/planned_features/feature_templates/README.md`](docs/00_overview/planned_features/feature_templates/README.md):
   - `bug_<short-slug>` — pre-existing failure, regression, broken behavior
   - `chore_<short-slug>` — non-feature cleanup (debt, doc rot, naming)
   - `infra_<short-slug>` — tooling, CI, test framework, deploy infra
2. Write `docs/00_overview/planned_features/<bucket>/<folder>/idea.md` following [`feature_templates/idea-template.md`](docs/00_overview/planned_features/feature_templates/idea-template.md). **`<bucket>` defaults to the current active-release bucket** — read the active release from [`state.md`](state.md) ("Where the roadmap sits" / current focus; today **MVP2 → `02_mvp2/`**). A discovery tripped over while building the current MVP is almost always that MVP's concern, so it goes there by default — NOT into `00_unsure/`. Only file elsewhere when the target is clearly a *different* release: GA-hardening → `04_ga/`, Observable/MVP3 → `03_mvp3/`, defer-until-incident → `99_backlog/`. `00_unsure/` is reserved for the genuinely-rare "I truly can't tell which release" case. Include:
   - **Origin**: how you noticed it (which PR / phase gate / story / conversation)
   - **Problem**: what's wrong, with `file:line` citations where you can
   - **Why inline fix wasn't viable**: cite the specific rubric row below that sent you here (NOT "out of scope" — that phrase has been the cover for too many deferrals that should have been inline fixes)
3. Include the idea file in the same commit as the work that surfaced it (or a separate doc commit on the same branch).

The rule's spirit: **inline fix is the discipline; capture is the safety net.** A chat-transcript-only noticing is gone forever, so when inline fix really isn't viable, capture it — but interrogate the "really isn't viable" claim hard before accepting it.

### Inline-fix vs idea-file rubric

The rubric below is the authoritative decision tree. Most rows route to **inline fix** — that's intentional. Only the bottom two rows route to idea-file, and they share the same shape: the work can't be done in the current PR without breaking either the PR's review boundary or the operator's authorization scope.

| Discovery shape | Action |
|---|---|
| Fix is ≤50 LOC AND no new tests needed beyond what the current PR already runs (e.g. docs typo, narrow refactor — NOT a bug fix; bug fixes always need a regression test per the Bug Fix Protocol above) | **Inline.** No new PR, no idea file. Just fix in the same commit (or an adjacent commit on the same branch) and note it in the commit message. |
| Fix is ≤250 LOC + bounded tests AND the work-type fits this PR's intent (backend → backend, frontend → frontend, infra → infra) | **Inline OR same-branch adjacent commit.** Don't capture an idea file. Accept the scope blur — it's cheaper than the context-switch cost of a separate PR later, and reviewers can read related changes together. |
| Fix introduces a new dev dep or new test-infra layer (e.g. first Playwright spec, first contract-test file, first migration of a new shape) | **Usually inline.** Adding a canonical *first instance* of common infra is rarely as expensive as it sounds — that's how every layer in this repo started. Estimate the path in minutes before deferring; if it's <60min of work, implement. Override the spec's "no new deps" rule only when the user authorizes it. |
| Fix would break a CI gate this PR is specifically valued on (e.g., the docs-only paths-ignore filter) AND the fix is bounded | **Adjacent PR off `main`** — not inline (preserves the current PR's gate), not idea file (don't defer a bounded fix). Ship the two PRs in parallel. |
| Fix requires a separate subsystem AND >250 LOC AND no immediate path to inline (different ORM model unrelated to the feature, different service entirely, different UI route family) | **Idea file.** Cross-subsystem mixing in one PR breaks reviewability. |
| Fix requires a product/UX decision, third-party config, or an operator-environment change (env vars, mounted secrets, branch-protection settings, SaaS account) | **Idea file.** Can't be unilaterally implemented. |

**Default lean: implement-now, not capture-as-idea-file.** The cost of a deferred-and-never-fixed idea file is higher than the cost of a slightly mixed-scope PR. If the inline fix surfaces during CI watch (e.g. a smoke job catches a failure mode the spec didn't anticipate), apply the fix to the same branch BEFORE merge — CI will re-run automatically on the new commit. That's exactly how the PR-#383 Solr-perms fix shipped.

### Pre-defer diagnostic: write the path

Before writing an idea file for any tangential discovery, write out the **specific implementation path** in your own working notes — concrete files, concrete steps, concrete tests. If that path is **<60 minutes of work** AND doesn't fork into a separate subsystem AND doesn't need a product/operator decision, just implement it on the current branch.

If you can't estimate in minutes, you haven't thought hard enough about the path yet — finish thinking before deciding to defer.

**Failure-mode words** that should make you re-examine the deferral rather than accept it:

| Surface concern | Why it's usually wrong | What to do instead |
|---|---|---|
| "No infra exists for this" | First instances of common infra (Playwright config, contract test file, new test-helper module) are usually <60min. Every layer started this way. | Add the canonical first instance. |
| "Brittle to X" | Brittle approaches usually have non-brittle alternatives if you think for 30 seconds. EXPLAIN-plan assertions → `pg_indexes` introspection. Time-based polling → event-driven assertion. | Identify the non-brittle alternative; implement that instead. |
| "High overhead" | Vibes, not minutes. If you can't quantify the overhead, it's probably much smaller than you think. | Estimate concretely (files × tests × verification cycles). If unsure, just try — abort if you cross 60min. |
| "Out of scope for current PR" | True for cross-subsystem work, often false otherwise. The reviewer can read related changes together; ten 20-line idea-file commits accumulate worse review debt than one 200-line bundled PR. | Check the rubric table above — only defer if the row above genuinely applies. |

**Hard stop signals** (where deferral IS the right call, even after writing the path):

- Current PR diff is already >1000 LOC AND the new work isn't strictly needed for the feature's stated intent (the marginal PR-review cost outweighs the deferral cost).
- Path requires a separate subsystem and no shared module — the change would land in files no other commit on this branch touches.
- Path requires a product or UX decision you can't make unilaterally.
- Path requires environment changes the operator hasn't authorized (new secret, new env var, new deploy target, new SaaS account).
- The user explicitly directed you to defer (overrides any other signal).

**Anti-pattern: pre-emptive deferral.** "Out of scope" is not self-justifying — the rubric is. If you're about to write an idea file, first ask: did the rubric send me here, or am I taking the easy way out?

## Local-stub hygiene — never leave commit-eligible debug artifacts in the repo

When you need to verify something locally (`docker compose config --quiet`, `alembic --sql`, an install-script dry-run, a temporary YAML for testing), it is tempting to write the stub file directly into the repo path it would eventually live at — `./secrets/database_url`, `./.env`, `./migrations/versions/0002_*.py`, `./data/postgres/`, etc. **Don't.** The next story (or the next operator) inherits that file and treats it as canonical. Idempotency guards (`[[ ! -s ./secrets/database_url ]]` and friends) silently preserve it. The bug surfaces hours or days later, in a different scope, and is much harder to attribute back to the verification step that created it.

**Canonical incident** (infra_foundation Story 4.2 → 4.4 → PR #4 first-run testing): I wrote `postgresql://relyloop:test_pw@postgres/relyloop` to `./secrets/database_url` to test `docker compose config --quiet` — without the `+asyncpg` driver prefix the runtime needs. install.sh's idempotency check kept it. Three commits later (Story 4.4) `make up` succeeded but `/healthz` 500'd because SQLAlchemy fell back to the psycopg2 dialect. Cost: one user-blocking debugging cycle.

**Rules:**

1. **Verify in tmpdir.** For commands that just need *some* file at *some* path (compose config, alembic --sql parse, install-script behavior in isolation), use `mktemp -d` or `/tmp/<scratch>/` — never the repo's canonical paths.
2. **If you must touch a real repo path**, revert it before commit. `git stash` the working tree first, do the verification, `git stash pop`. Or use `git checkout -- <path>` after.
3. **Generated artifacts go to gitignored locations.** `./data/`, `./.venv/`, `./.pytest_cache/` are already gitignored. `./secrets/*` is gitignored except `.gitkeep`. `./.env` is gitignored. If you generate something somewhere else, that's a smell — find the right gitignored home.
4. **The next story's idempotency assumption is your responsibility.** If install.sh / migrate / make up has a "skip if file exists" guard, anything you leave behind alters the next operator's first-run experience. Treat your own debug artifacts as user-facing state.

If you slip and a stub leaks into a committed file, capture it as a `bug_<slug>` idea file the moment you notice (per the tangential-discoveries rule above) — don't silently fix it without acknowledging the failure mode.

## Feature Status

**See [`state.md`](state.md)** for full completion snapshot, recent changes, Alembic head, and active priorities. Do not duplicate feature status here — it goes stale.

**MVP1 features (priority-ordered by dependency):**

| # | Feature | Status |
|---|---|---|
| 1 | [`infra_foundation`](docs/00_overview/implemented_features/2026_05_09_infra_foundation/) | **Complete (PR #4, merged 2026-05-09)** |
| 2 | [`infra_adapter_elastic`](docs/00_overview/implemented_features/2026_05_10_infra_adapter_elastic/) | **Complete (PR #16, merged 2026-05-10)** |
| 3 | [`infra_optuna_eval`](docs/00_overview/implemented_features/2026_05_10_infra_optuna_eval/) | **Complete (PR #23, merged 2026-05-10)** |
| 4 | [`feat_study_lifecycle`](docs/00_overview/implemented_features/2026_05_10_feat_study_lifecycle/) | **Complete — Phase 1 (Schema) PR #18 + Phase 2 (Orchestrator + API) PR #25, both merged 2026-05-10/11** |
| 5 | [`feat_llm_judgments`](docs/00_overview/implemented_features/2026_05_11_feat_llm_judgments/) | **Complete (PR #35, merged 2026-05-11)** |
| 6 | [`feat_digest_proposal`](docs/00_overview/implemented_features/2026_05_11_feat_digest_proposal/) | **Complete (PR #41, merged 2026-05-11)** |
| 7 | [`feat_github_pr_worker`](docs/00_overview/implemented_features/2026_05_12_feat_github_pr_worker/) | **Complete (PR #45, merged 2026-05-12)** |
| 8 | [`feat_github_webhook`](docs/00_overview/implemented_features/2026_05_12_feat_github_webhook/) | **Complete (PR #56, merged 2026-05-12)** |
| 9 | [`feat_studies_ui`](docs/00_overview/implemented_features/2026_05_12_feat_studies_ui/) | **Complete (PR #50, merged 2026-05-11)** |
| 10 | [`feat_chat_agent`](docs/00_overview/implemented_features/2026_05_12_feat_chat_agent/) | **Complete (PR #60, merged 2026-05-12)** |
| 11 | [`feat_proposals_ui`](docs/00_overview/implemented_features/2026_05_12_feat_proposals_ui/) | **Complete (PR #58, merged 2026-05-12)** |
| 12 | [`chore_tutorial_polish`](docs/00_overview/implemented_features/2026_05_12_chore_tutorial_polish/) | **Complete (PR #64, merged 2026-05-12). Story 4.6 (demo) deferred to MVP3 per [chore_demo_recording_mvp3](docs/00_overview/planned_features/chore_demo_recording_mvp3/idea.md) (PR #65). Story 4.7 shipped 2026-05-13 — `v0.1.0` tag on `d099536`, [GitHub Release published](https://github.com/SoundMindsAI/relyloop/releases/tag/v0.1.0).** |

Run `/pipeline status` for the live view from spec dependencies.

## Key Runbooks

| Situation | Reference |
|---|---|
| Local dev start/stop | [`docs/03_runbooks/local-dev.md`](docs/03_runbooks/local-dev.md) (lands in `infra_foundation` Story 5.2) |
| Test layer convention + 80% coverage gate | [`docs/05_quality/testing.md`](docs/05_quality/testing.md) (lands in `infra_foundation` Story 5.2) |
| DB revision mismatch | TBA — lands when `feat_study_lifecycle` ships its first business-table migration |
| GitHub webhook debugging + secret rotation + register_webhook triage | [`docs/03_runbooks/webhook-debugging.md`](docs/03_runbooks/webhook-debugging.md) (`feat_github_webhook`) |
| `open_pr` worker debugging + per-repo PAT rotation + closing orphan branches | [`docs/03_runbooks/pr-open-debugging.md`](docs/03_runbooks/pr-open-debugging.md) (`feat_github_pr_worker`) |
| GitHub PAT storage / rotation / leak prevention | [`docs/04_security/github-token-handling.md`](docs/04_security/github-token-handling.md) (`feat_github_pr_worker`) |
| Local LLM (Ollama / LM Studio / vLLM / TGI) configuration | [`docs/01_architecture/llm-orchestration.md` §"OpenAI-compatible endpoints"](docs/01_architecture/llm-orchestration.md); tutorial walkthrough at [`docs/08_guides/tutorial-first-study.md`](docs/08_guides/tutorial-first-study.md) Step 0 Path B (`chore_tutorial_polish`) |
| Maintainer release procedure (smoke gate + manual VM walkthroughs + tag + Release) | [`docs/03_runbooks/release-checklist.md`](docs/03_runbooks/release-checklist.md) (`chore_tutorial_polish`) |
| Tutorial — clone → first study end-to-end in 30 minutes | [`docs/08_guides/tutorial-first-study.md`](docs/08_guides/tutorial-first-study.md) (`chore_tutorial_polish`) |
| LLM-as-judge worker debugging + calibration / overrides | [`docs/03_runbooks/judgment-generation-debugging.md`](docs/03_runbooks/judgment-generation-debugging.md) (`feat_llm_judgments`) |
| What data leaves the cluster on each judgment-generation call | [`docs/04_security/llm-data-flow.md`](docs/04_security/llm-data-flow.md) (`feat_llm_judgments` §15) |
| Chat-agent debugging — replay a conversation, force a tool dispatch, inspect SSE events | [`docs/03_runbooks/agent-debugging.md`](docs/03_runbooks/agent-debugging.md) (`feat_chat_agent`) |
| Parallel-worktree workflow — sibling checkouts, `make test-worktree`, leak prevention | [`docs/03_runbooks/parallel-worktrees.md`](docs/03_runbooks/parallel-worktrees.md) (`infra_agent_sibling_worktree_isolation` Phase 2) |
| Interpreting the convergence verdict (converged / still_improving / too_few_trials) | [`docs/03_runbooks/convergence-verdict.md`](docs/03_runbooks/convergence-verdict.md) (`feat_study_convergence_indicator`) |
| Demo reseed engine tolerance — partial completion (`scenarios_skipped`), all-engines-unreachable failure, re-seed after starting an engine | [`docs/03_runbooks/demo-reseed-engine-tolerance.md`](docs/03_runbooks/demo-reseed-engine-tolerance.md) (`infra_solr_ci_readiness`) |
| Smoke job Solr stability — lever cascade (heap-cap / start_period / smoke-tolerance) for a red `smoke` CI job, diagnostic workflow from the smoke-logs artifact | [`docs/03_runbooks/smoke-solr-stability.md`](docs/03_runbooks/smoke-solr-stability.md) (`infra_solr_smoke_stability`) |
| Corporate-network `make up` failures — symptom-first FAQ for registry blocks, TLS interception (corp HTTPS proxy + internal CA), HTTP proxy / DNS failures, unhealthy worker after `no_proxy` misses Compose service names, runtime egress | [`docs/03_runbooks/corporate-network-install.md`](docs/03_runbooks/corporate-network-install.md) (`chore_corp_install_dx_improvements`) |
