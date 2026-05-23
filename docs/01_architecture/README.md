# Architecture

System design docs, interface descriptions, and topology overviews. Each topical doc covers all releases (MVP1 → GA v1); per-release scope is annotated on tables (`MVP1 status` / `Activates at` columns), called out inline (`**MVP1 status:** ...`), and consolidated in a `## Reserved for later releases` section near the bottom of each doc.

## Topical docs

- [`system-overview.md`](system-overview.md) — service topology, communication patterns, worker pool detail
- [`tech-stack.md`](tech-stack.md) — backend/frontend/infrastructure stack choices and conventions
- [`api-conventions.md`](api-conventions.md) — URL structure, HTTP methods, error envelope, pagination, idempotency, trace propagation
- [`data-model.md`](data-model.md) — Postgres tables, conventions (UUIDv7, soft-delete, JSONB), MVP1 omissions
- [`adapters.md`](adapters.md) — engine adapter Protocol, ElasticAdapter, cross-engine parameter naming
- [`cluster-lifecycle.md`](cluster-lifecycle.md) — what a "cluster" is, why registration probes, soft-delete + revival, the 6 endpoints mapped to operator intent (read first if the cluster API is unfamiliar)
- [`deployment.md`](deployment.md) — Docker Compose layout, secrets, volumes, network exposure

## Per-MVP navigation summaries

- [`mvp1-overview.md`](mvp1-overview.md) — what's active in MVP1, what's deferred to later releases, per-feature reading guide

## Forthcoming (authored alongside their corresponding feature spec)

- `optimization.md` — Optuna RDBStorage + TPE sampler + ir_measures (with `infra_optuna_eval`)
- `llm-orchestration.md` — OpenAI function-calling pattern, prompts, agent loop (with `feat_llm_judgments` / `feat_chat_agent`)
- `apply-path.md` — Git PR workflow, `*.params.json` editing, webhook state tracking (with `feat_github_pr_worker`)
- `agent-tools.md` — Tool registry, dispatch, request/response shapes (with `feat_chat_agent`)
- `ui-architecture.md` — Next.js App Router layout, TanStack Query patterns, SSE handling (with `feat_studies_ui`)
