# RelyLoop Documentation

The repository uses a numbered documentation IA so related material stays grouped and sorts predictably in file browsers.

## Where to start

Pick the path that matches your goal:

| Goal | Read this first |
|---|---|
| **Boot the stack on my laptop** | [`03_runbooks/local-dev.md`](03_runbooks/local-dev.md) — `make up` → `/healthz` → debug |
| **Understand what RelyLoop is + the release roadmap** | [`00_overview/relyloop-spec.md`](00_overview/relyloop-spec.md) (umbrella spec; ~2,800 lines) |
| **Onboard as a contributor** | [`../state.md`](../state.md) (active branch / focus / debt) → [`../architecture.md`](../architecture.md) (navigation) → [`../CLAUDE.md`](../CLAUDE.md) (conventions + absolute rules) |
| **Look up an architectural decision** | [`01_architecture/`](01_architecture/) — topical docs (tech-stack, deployment, adapters, llm-orchestration, etc.) |
| **Find the spec for a planned feature** | [`00_overview/planned_features/<feature>/feature_spec.md`](00_overview/planned_features/) |
| **Add a test / understand the coverage gate** | [`05_quality/testing.md`](05_quality/testing.md) |

## Sections

- `00_overview/` — project-level context, status, the umbrella spec, and `implemented_features/<YYYY_MM_DD>_<slug>/` archives
- `01_architecture/` — system design, ADR-adjacent technical overviews, interfaces, and topology docs (12 topical docs land here)
- `02_product/` — MVP1 user stories + per-feature spec folders under `planned_features/<feature>/`
- `03_runbooks/` — operator and maintainer procedures (boot, debug, deploy, restore)
- `04_security/` — threat models, policies, and security-specific guidance (populates at MVP2 with the `audit_log` work)
- `05_quality/` — testing strategy, quality gates, and validation docs
- `06_vendor_docs/` — vendor- or engine-specific notes (Elasticsearch, OpenSearch, Apache Solr, OpenAI-compatible providers)
- `07_research/` — exploratory notes, comparisons, and background analysis
- `08_guides/` — tenant-facing walkthrough guides (lands later with the UI features)
- `09_decisions/` — ADR-style decision records

## Conventions

- Put each document in the narrowest section that matches its primary audience and purpose.
- Keep vendor-specific behavior out of architecture docs when a `06_vendor_docs/` note is more precise.
- Use `09_decisions/ADR-xxxx-title.md` for durable decisions that should survive refactors.
- Prefer short index files in a section when it starts to accumulate many documents (every section README should list what's in the section + flag what arrives later).
- **Planned-features folder naming:** new folders under `00_overview/planned_features/` use a single-axis work-type prefix: `feat_`, `infra_`, `chore_`, `bug_`, or `epic_`. See [`00_overview/planned_features/feature_templates/README.md`](00_overview/planned_features/feature_templates/README.md).

## Currently shipped (MVP1 in flight)

The bootstrap feature `infra_foundation` is in review (PR #4). It establishes:

- 6-service Docker Compose stack ([`01_architecture/deployment.md`](01_architecture/deployment.md))
- FastAPI + `/healthz` operator probe ([`00_overview/planned_features/infra_foundation/feature_spec.md`](00_overview/planned_features/infra_foundation/feature_spec.md) §7)
- OpenAI capability check at startup ([`01_architecture/llm-orchestration.md`](01_architecture/llm-orchestration.md))
- Alembic baseline migration + `make migrate`
- GitHub Actions CI with 80% coverage gate
- Root context files: [`../state.md`](../state.md), [`../architecture.md`](../architecture.md), [`../CLAUDE.md`](../CLAUDE.md)
- Runbook: [`03_runbooks/local-dev.md`](03_runbooks/local-dev.md)
- Quality doc: [`05_quality/testing.md`](05_quality/testing.md)

The next 11 MVP1 features are spec-approved and queued under [`00_overview/planned_features/`](00_overview/planned_features/). See [`../state.md`](../state.md) for priority order.
