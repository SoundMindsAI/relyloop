# Changelog

All notable changes to RelyLoop are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The leading `0.` signals pre-1.0 instability — minor versions may carry
breaking changes until `v1.0.0` (GA).

Released versions correspond to git tags and
[GitHub Releases](https://github.com/SoundMindsAI/relyloop/releases). The
`[Unreleased]` section tracks what has landed on `main` since the last tag.

## [Unreleased]

Work toward **MVP2 / v0.2 — "Three-Engine + Real Signals."** Apache Solr and
UBI judgments have shipped; the remaining MVP2 ergonomics and observability
items are in progress. This will be tagged `v0.2.0` once the MVP2 scope closes.

### Added

- **Apache Solr adapter — the third engine.** A single `SolrAdapter` implements
  the `SearchAdapter` Protocol against Solr 9.x and 10.x (SolrCloud and
  standalone) via `edismax` + `{!ltr}` rescore, pivoting on a capability probe
  at construction time. RelyLoop now reaches all three major OSS search engines:
  Elasticsearch, OpenSearch, and Apache Solr. (#336, #338, #348)
- **UBI (User Behavior Insights) judgments.** `UbiReader` reads the
  `ubi_queries` + `ubi_events` collections through any `SearchAdapter`, so
  click-derived judgment generation works on all three engines. Adds a
  pluggable `SignalsConverter` (position-bias-corrected CTR, dwell-time, hybrid
  UBI+LLM), `POST /api/v1/judgment-lists/generate-from-ubi`, and a
  `generate_judgments_from_ubi` agent tool. (#317)
- **Study convergence indicator.** Every completed study carries a
  plain-language verdict — `converged` / `still_improving` / `too_few_trials` —
  backed by a best-metric-so-far curve, answering "did the optimizer finish
  learning, or did I stop it too early?" Surfaced in the UI, the digest
  narrative, and a new runbook. (#352)
- **Overnight autopilot.** Surfaces the auto-followup study-chaining engine as a
  first-class "set it and wake up to results" path: a relabeled create-study
  toggle, a read-only `GET /api/v1/studies/{id}/chain`, and a rolled-up chain
  summary panel. (#343)
- **Demo UBI study comparison + contextual help** across the create-study and
  study-detail surfaces. (#124, #320)
- **MkDocs Material documentation site** scaffolding for relyloop.com, with a
  footer build stamp. (#342, #369)
- **Launch-readiness collateral** — Karpathy-loop Mermaid diagram in the README,
  curated `good first issue` tickets, `engine/*` labels, GitHub Discussions, and
  a license inventory + SPDX-header REUSE gate. (#322, #330, #354)

### Changed

- **Demo reseed is engine-tolerant.** The home-button reseed probes each engine
  before dispatch and skips unreachable ones instead of failing the whole run;
  partial completion reports `status="complete"` with a `scenarios_skipped`
  list. This unblocks the `pr.yml` backend job without a Solr service container.
  (#367)
- **Heavy CI restored.** The full `pr.yml` suite (backend lint/typecheck/tests/
  coverage, frontend, smoke, both Docker builds) runs on every PR again now that
  the repo is public (GitHub-hosted runners are free for public repos).
- **Fusion fully removed.** Lucidworks Fusion is no longer a supported or
  planned engine — Apache Solr took its place. The supported set is exactly
  Elasticsearch, OpenSearch, and Apache Solr. (#332)
- **Release matrix compressed** to four stops: MVP1 → MVP2 (Three-Engine + Real
  Signals) → MVP3 (Observable) → GA v1 (hardening). Multi-tenant, multi-LLM,
  multi-Git, LTR, and production-monitoring are backlog.
- **Solr Compose service** added (SolrCloud + embedded ZooKeeper,
  `SOLR_MODULES=ltr`) on `127.0.0.1:8983`; UI primitive groundwork continued
  (see v0.1.2). Alembic head advanced to `0022_solr_engine_auth_check` (Solr
  `engine_type` + `auth_kind` CHECK-constraint extensions).

### Fixed

- **Backend test-suite order dependence.** `configure_logging()` replaced the
  structlog processor list instance on every call, blinding cached loggers to
  `capture_logs()` and making the full randomized suite nondeterministically
  red; fixed by mutating the list in place. (#364)

## [0.1.3] - 2026-05-29

Docs-only milestone — the MVP1 actionable backlog is fully drained (the
`01_mvp1/` planned-features bucket is empty).

### Changed

- Reclassified the two remaining deferred-by-design MVP1 folders out of
  `01_mvp1/` into `99_backlog/` (defer-until-incident). (#310)
- Refreshed the compressed-context docs (`state.md`, `CLAUDE.md`) for the
  post-MVP1 reality; next stop is the MVP2 bucket. (#311)

_No code or schema changes since v0.1.2; Alembic head unchanged._

## [0.1.2] - 2026-05-19

The shared-UI-primitive wave — the reusable building blocks the later feature
surfaces are composed from.

### Added

- **`<DataTable>` primitive** with TanStack column visibility + an enum/FK
  source-of-truth lint guard. (#126, #132, #150)
- **`<EntitySelect>` form-dropdown primitive** + four modal migrations + a lint
  guard against inline enum literals. (#136)
- **`<DetailPageShell>` primitive** — the third shared primitive. (#155)
- Proposals `?study_id=` filter + restored deferred E2E coverage. (#148)

### Changed

- `make up` now rebuilds everything; `make down` properly removes containers.
  (#146)
- Added a `prettier --check` gate to the `pr.yml` frontend job. (#152)
- Routine Dependabot dependency bumps across `/ui` and GitHub Actions.

## [0.1.1] - 2026-05-14

MVP1 alpha feature-complete — `36/36` scoped items done. Post-launch polish on
top of the v0.1.0 cut.

### Added

- **Inline query CRUD** — PATCH / DELETE / GET on
  `/api/v1/query-sets/{id}/queries` + an inline editable table. (#101)
- **Periodic judgment resume sweep** — an in-worker Arq cron that re-enqueues
  stuck `generating` judgment lists every 15 minutes. (#104)
- **Chat last-message preview** — `last_message_preview` + `last_message_at` on
  the conversation summary, rendered on the `/chat` list. (#117)
- Per-release dashboards + a top-level roadmap roll-up. (#119)

### Changed

- `make backend-*` sub-targets for Node-18 contributors. (#110)
- Shared structlog test helpers (`backend/tests/_log_helpers.py`). (#114)
- Dashboard-regen idempotency + relative-link rewriting. (#108)

### Fixed

- UUIDv7 millisecond-collision flake in query-set seed helpers. (#106)
- Narrowed an over-broad `except` in the digest worker so dependency
  regressions surface at ERROR level. (#112)

## [0.1.0] - 2026-05-13

**MVP1 alpha — "The Loop."** The full Karpathy loop end-to-end on Elasticsearch
and OpenSearch: single-tenant, no auth, Docker Compose.

### Added

- **Engine adapter** — one `SearchAdapter` Protocol covering ES 8.11+/9.x and
  OpenSearch 2.x/3.x. Cluster registration via UI or API.
- **Optuna optimizer** — TPE sampler against a parametrized query template, with
  a per-trial budget guard and cut-aware IR metrics (`ndcg@k`, `map`,
  `precision`, `recall`, `mrr`, `err`).
- **LLM-as-judge** — `POST /api/v1/judgments/generate` rates query–document
  pairs against a rubric, against any OpenAI-compatible endpoint
  (Ollama / LM Studio / vLLM / TGI) via `OPENAI_BASE_URL`.
- **Digest** — an LLM-generated narrative summary per completed study, plus a
  parameter-importance chart and recommended config.
- **GitHub PR worker** — winning configs land as Pull Requests against a central
  search-config Git repo; the operator's CI deploys. RelyLoop never sits on the
  live search-serving path.
- **Chat agent** — describe the problem in chat; the agent introspects the
  cluster, proposes a search space, and queues the study after operator
  confirmation.
- **Operator tutorial + sample data** — 1,000 curated Amazon ESCI products + 48
  queries + a canonical Jinja2 query template; `git clone → Open PR` in under 30
  minutes on a fresh laptop.
- **CI smoke gate** — every PR runs the full loop end-to-end against a fresh
  stack.

### Security

- Apache 2.0 license, DCO sign-off enforcement, secrets-via-mounted-files
  (no bare-env-var secrets), and a full git-history secret scan before the
  visibility flip.

[Unreleased]: https://github.com/SoundMindsAI/relyloop/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/SoundMindsAI/relyloop/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/SoundMindsAI/relyloop/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/SoundMindsAI/relyloop/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/SoundMindsAI/relyloop/releases/tag/v0.1.0
