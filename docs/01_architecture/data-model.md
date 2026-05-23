# Data Model

**Status:** Adopted for MVP1. Tables shown with their MVP1 shape; deferred columns and tables are flagged.
**Source of truth for product context:** [docs/00_overview/product/relevance-copilot-spec.md §9](../00_overview/product/relevance-copilot-spec.md) ("Data model").

---

## Conventions

Per [`tech-stack.md`](tech-stack.md) §"Database conventions":

- **UUIDv7** primary keys on every table (lexicographically sortable, time-ordered, generated client-side).
- All timestamps `TIMESTAMPTZ`, stored UTC.
- Soft-delete via `deleted_at` on user-facing tables; hard-delete on internal append-only tables (`trials`).
- snake_case table and column names.
- JSONB for flexible structured fields (settings, params, metrics, payloads).
- All foreign keys explicit; no implicit relationships.
- Migrations via Alembic with `--autogenerate`.
- Postgres 16; one logical database `relyloop` for app state; Optuna's RDB schema lives in the same Postgres instance under the `optuna.*` schema.

## Reserved for later releases

The umbrella spec describes a multi-tenant data model; MVP1 ships a strict subset. Per-release timing aligns with the canonical [`tech-stack.md` §"Canonical release matrix"](tech-stack.md):

| Omitted in MVP1 | Activates at | Why deferred |
|---|---|---|
| `audit_log` table + Postgres immutability trigger | **MVP2** ("Observable") | Audit immutability is the MVP2 contract. Schema arrives without FKs (`tenant_id`/`actor_id` nullable, no FK), with `actor_type` ENUM constrained to `system`/`agent`/`anonymous`. FKs added at MVP4 when `users` and `tenants` arrive. |
| Lineage columns (`langfuse_trace_id`, `prompt_version`, `input_hash`) on `judgments` / `digests` / `proposals` | MVP2 | LLM observability is the MVP2 theme; lineage activates with Langfuse. |
| `tenants` table | MVP4 ("Multi-tenant, Multi-LLM") | MVP1 is a single-install evaluation tool; no tenant boundary needed. |
| `tenant_id` column on every user-facing table | MVP4 | Migration adds `tenant_id` everywhere with a backfill auto-creating a `default` tenant. |
| `users`, `tenant_memberships`, `api_keys` tables | MVP4 | No auth in MVP1–3. SSO for humans + Argon2id-hashed API keys for service accounts arrive at MVP4 per umbrella §18. |
| `created_by` (FK to `users.id`) on user-facing tables | MVP4 | No users to attribute creation to before MVP4. |
| FK constraints on `audit_log.actor_id` and `audit_log.tenant_id` | MVP4 | Added when `users` and `tenants` arrive; pre-MVP4 audit rows keep `actor_id = NULL`. `actor_type` ENUM extended with `user`. |

Feature specs that touch these entities mark the deferred columns/tables as `(MVPN+)` and do not include them in MVP1 migrations.

## MVP1 table inventory + migration ownership

13 application tables ship across the MVP1 features. **Each table is owned by exactly one feature spec** — that feature's migration creates the full MVP1 shape (no piecemeal column additions across multiple PRs). Subsequent features consume; they do not extend.

| Table | Owning feature (creates full MVP1 shape) | Consumed by |
|---|---|---|
| `clusters` | `infra_adapter_elastic` | feat_study_lifecycle, feat_llm_judgments, feat_digest_proposal, feat_github_pr_worker |
| `config_repos` | `infra_adapter_elastic` | feat_github_pr_worker, feat_github_webhook (writes `webhook_registration_error`) |
| `query_templates` | `feat_study_lifecycle` | feat_llm_judgments, feat_digest_proposal |
| `query_sets` | `feat_study_lifecycle` | feat_llm_judgments |
| `queries` | `feat_study_lifecycle` | feat_llm_judgments |
| `judgment_lists` | `feat_study_lifecycle` (full shape, including cluster_id/target/current_template_id/status/calibration) | feat_llm_judgments (writes status + calibration + creates child judgments rows) |
| `studies` | `feat_study_lifecycle` (full shape, including failed_reason) | feat_digest_proposal, feat_studies_ui |
| `trials` | `feat_study_lifecycle` | infra_optuna_eval (writes via run_trial), feat_digest_proposal |
| `proposals` | `feat_study_lifecycle` (full shape, including pr_url/pr_state/pr_merged_at/pr_open_error/rejected_reason) | feat_digest_proposal (writes), feat_github_pr_worker (writes pr_url + pr_open_error), feat_github_webhook (writes pr_state + pr_merged_at) |
| `judgments` | `feat_llm_judgments` | (terminal — no consumers in MVP1 beyond ir_measures reads) |
| `digests` | `feat_digest_proposal` | feat_studies_ui, feat_proposals_ui |
| `conversations` | `feat_chat_agent` | (terminal) |
| `messages` | `feat_chat_agent` | (terminal) |

Plus Alembic's internal `alembic_version` (created by `infra_foundation`).

**Migration ordering:** `infra_foundation` → `infra_adapter_elastic` → `feat_study_lifecycle` → `infra_optuna_eval` → all other backend features in any order. The orchestration features (`feat_github_pr_worker`, `feat_github_webhook`) extend pre-existing tables (`webhook_registration_error` on `config_repos`); they do NOT create new tables.

## Detailed schemas (MVP1 shape)

The schemas below show what each table looks like in MVP1 — `tenant_id` and `created_by` columns omitted, lineage columns on judgment/digest/proposal omitted.

### `clusters` (owned by `infra_adapter_elastic`)

```sql
CREATE TABLE clusters (
    id              UUID PRIMARY KEY,                  -- UUIDv7
    name            TEXT NOT NULL UNIQUE,              -- "products-prod-es", "local-es"
    engine_type     TEXT NOT NULL CHECK (engine_type IN ('elasticsearch', 'opensearch')),
    environment     TEXT NOT NULL CHECK (environment IN ('prod', 'staging', 'dev')),
    base_url        TEXT NOT NULL,
    auth_kind       TEXT NOT NULL CHECK (auth_kind IN ('es_apikey', 'es_basic', 'opensearch_basic', 'opensearch_sigv4')),
    credentials_ref TEXT NOT NULL,                     -- key into mounted secrets file
    config_repo_id  UUID REFERENCES config_repos(id),  -- nullable; populated by feat_github_pr_worker
    config_path     TEXT,                              -- nullable; populated by feat_github_pr_worker
    engine_config   JSONB,                             -- e.g., {"api_version": "9"}
    notes           TEXT,
    target_filter   VARCHAR(256),                      -- nullable; fnmatch.fnmatchcase glob scoping list_targets()
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);
```

`auth_kind = opensearch_sigv4` is a reserved enum value but rejected at the API layer with `AUTH_KIND_NOT_SUPPORTED` in MVP1 — AWS managed OpenSearch support lands at MVP3.

`target_filter` (added by [`feat_cluster_target_filter`](../00_overview/implemented_features/<date>_feat_cluster_target_filter/) at Alembic `0014`) is an optional operator-supplied glob pattern that scopes `GET /clusters/{id}/targets` to matching index/collection names. NULL = no filter (default, backward-compat for pre-`0014` rows). Pattern syntax: `*`, `?`, `[seq]`, `[!seq]` via Python `fnmatch.fnmatchcase` — no brace expansion. Trimmed at the API layer; stored verbatim otherwise. MVP1 is create-only: to change the filter, DELETE + re-register (no PATCH endpoint).

### `config_repos` (owned by `infra_adapter_elastic`)

```sql
CREATE TABLE config_repos (
    id                          UUID PRIMARY KEY,
    name                        TEXT NOT NULL UNIQUE,
    provider                    TEXT NOT NULL CHECK (provider IN ('github')),  -- only GitHub in MVP1
    repo_url                    TEXT NOT NULL,
    default_branch              TEXT NOT NULL DEFAULT 'main',
    pr_base_branch              TEXT NOT NULL DEFAULT 'main',
    auth_ref                    TEXT NOT NULL,                 -- mounted secret key for the GitHub PAT
    webhook_secret_ref          TEXT,                          -- mounted secret key for webhook signature verification (nullable; null means polling-only)
    webhook_registration_error  TEXT,                          -- populated by feat_github_webhook if GitHub auto-registration fails; cleared on successful re-registration
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

GitLab and Bitbucket join the `provider` allowlist at MVP3.

### `query_templates`, `query_sets`, `queries` (owned by `feat_study_lifecycle`)

```sql
CREATE TABLE query_templates (
    id              UUID PRIMARY KEY,
    name            TEXT NOT NULL,
    engine_type     TEXT NOT NULL,                     -- "elasticsearch" | "opensearch"
    body            TEXT NOT NULL,                     -- Jinja2 source
    declared_params JSONB NOT NULL,                    -- {param_name: type/range hint}
    version         INT NOT NULL DEFAULT 1,
    parent_id       UUID REFERENCES query_templates(id), -- for forks
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE TABLE query_sets (
    id              UUID PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT,
    cluster_id      UUID REFERENCES clusters(id),      -- judgments are cluster-specific
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE queries (
    id              UUID PRIMARY KEY,
    query_set_id    UUID NOT NULL REFERENCES query_sets(id) ON DELETE CASCADE,
    query_text      TEXT NOT NULL,
    reference_answer TEXT,                             -- optional, for QA-style eval
    metadata        JSONB
);
```

### `judgment_lists` (owned by `feat_study_lifecycle`) and `judgments` (owned by `feat_llm_judgments`)

`judgment_lists` is created by `feat_study_lifecycle` (full MVP1 shape — not a stub) so that `studies.judgment_list_id` FK has a target and `feat_llm_judgments` can author rows immediately. `judgments` (the child table) is created by `feat_llm_judgments`.

```sql
CREATE TABLE judgment_lists (
    id                      UUID PRIMARY KEY,
    name                    TEXT NOT NULL UNIQUE,
    description             TEXT,
    query_set_id            UUID NOT NULL REFERENCES query_sets(id),
    -- Generation context: persisted so the worker can reconstruct what
    -- cluster/index/template the judgments were generated against. Required for
    -- regeneration, calibration audits, and lineage. Set at create-time even for
    -- imported lists (point at the cluster + target the imports correspond to).
    cluster_id              UUID NOT NULL REFERENCES clusters(id),
    target                  TEXT NOT NULL,                     -- index or collection name on the cluster
    current_template_id     UUID REFERENCES query_templates(id),  -- template used at generation time; nullable for imports
    -- Lifecycle:
    rubric                  TEXT NOT NULL,                     -- the rubric used (LLM or human)
    status                  TEXT NOT NULL CHECK (status IN ('generating', 'complete', 'failed')),
    failed_reason           TEXT,                              -- populated when status='failed'
    -- Calibration (advisory; not gating):
    calibration             JSONB,                             -- {cohens_kappa, weighted_kappa, per_class, n_samples}
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE judgments (
    id                  UUID PRIMARY KEY,
    judgment_list_id    UUID NOT NULL REFERENCES judgment_lists(id) ON DELETE CASCADE,
    query_id            UUID NOT NULL REFERENCES queries(id),
    doc_id              TEXT NOT NULL,
    rating              SMALLINT NOT NULL CHECK (rating BETWEEN 0 AND 3),
    source              TEXT NOT NULL CHECK (source IN ('llm', 'human', 'click')),
    rater_ref           TEXT,                          -- model name (e.g., 'openai:gpt-4o-2024-08-06') or 'operator'
    confidence          REAL,
    notes               TEXT,
    -- lineage columns (langfuse_trace_id, prompt_version, input_hash) added at MVP2
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (judgment_list_id, query_id, doc_id)
);
```

### `studies`, `trials` (owned by `feat_study_lifecycle`)

```sql
CREATE TABLE studies (
    id                  UUID PRIMARY KEY,
    name                TEXT NOT NULL,
    cluster_id          UUID NOT NULL REFERENCES clusters(id),
    target              TEXT NOT NULL,                 -- index or collection name
    template_id         UUID NOT NULL REFERENCES query_templates(id),
    query_set_id        UUID NOT NULL REFERENCES query_sets(id),
    judgment_list_id    UUID NOT NULL REFERENCES judgment_lists(id),
    search_space        JSONB NOT NULL,                -- per-parameter range/choice spec
    objective           JSONB NOT NULL,                -- {metric, k, direction}
    config              JSONB NOT NULL,                -- {max_trials, time_budget_min, parallelism, sampler, pruner, seed, trial_timeout_s}
    status              TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'cancelled', 'failed')),
    failed_reason       TEXT,                          -- populated when status='failed'
    optuna_study_name   TEXT NOT NULL UNIQUE,          -- convention: optuna_study_name = str(studies.id)
    parent_study_id     UUID REFERENCES studies(id),   -- for forks (MVP2)
    baseline_metric     REAL,                          -- single non-Optuna trial run before Optuna starts; populated by orchestrator
    best_metric         REAL,
    best_trial_id       UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ
);

CREATE TABLE trials (
    id                  UUID PRIMARY KEY,
    study_id            UUID NOT NULL REFERENCES studies(id) ON DELETE CASCADE,
    optuna_trial_number INT NOT NULL,
    params              JSONB NOT NULL,
    primary_metric      REAL,                          -- denormalized from `metrics` for fast sort
    metrics             JSONB NOT NULL,                -- {ndcg@10: ..., map: ..., p@10: ...}
    per_query_metrics   JSONB,                         -- {qid: {ndcg@10: ..., map@10: ..., ...}} — feat_pr_metric_confidence (0015)
    duration_ms         INT,
    status              TEXT NOT NULL CHECK (status IN ('complete', 'failed', 'pruned')),
    error               TEXT,
    started_at          TIMESTAMPTZ,
    ended_at            TIMESTAMPTZ,
    CONSTRAINT trials_per_query_metrics_object_check
        CHECK (per_query_metrics IS NULL OR jsonb_typeof(per_query_metrics) = 'object')
);

CREATE INDEX trials_study_metric ON trials (study_id, primary_metric DESC NULLS LAST);
```

`trials` is hard-delete only (no `deleted_at`) — when a study is removed, trials cascade-delete with it; trial history is regenerable from Optuna's RDB if needed.

`per_query_metrics` (added by [`feat_pr_metric_confidence`](../00_overview/implemented_features/<date>_feat_pr_metric_confidence/) at Alembic `0015`) carries the per-query ir_measures scores from `backend/app/eval/scoring.py::score()`'s `per_query` dict, keyed by the user-facing metric tokens it emits (e.g. `ndcg@10`, `map@10`, `mrr`). NULL for trials predating the migration or for failed/pruned trials. The DB-level CHECK constraint enforces NULL-or-object at the persistence boundary since the write path is the Arq `run_trial` worker, not a Pydantic-validated HTTP request. Consumed by `backend/app/services/study_confidence.py::fetch_study_confidence` (the FR-2 4-query read pattern) to assemble `ConfidenceShape` on the `StudyDetail` response, the PR body's `## Confidence` section, and the digest narrative's `<confidence>` / `<per_query_outcomes>` Jinja blocks. Per-sub-field FR-7 degradation paths suppress only the per-query-dependent surfaces (`ci_95`, `headline.n_queries`, `per_query_outcomes`) when this column is NULL.

### `digests`, `proposals` (owned by `feat_digest_proposal` + `feat_github_pr_worker`)

```sql
CREATE TABLE digests (
    id                      UUID PRIMARY KEY,
    study_id                UUID NOT NULL REFERENCES studies(id) UNIQUE,
    narrative               TEXT NOT NULL,
    parameter_importance    JSONB NOT NULL,
    recommended_config      JSONB NOT NULL,
    suggested_followups     TEXT[],
    generated_by            TEXT NOT NULL,             -- LLM model name + version
    -- lineage columns added at MVP2
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE proposals (
    id              UUID PRIMARY KEY,
    study_id        UUID REFERENCES studies(id),       -- null if hand-crafted via feat_chat_agent
    study_trial_id  UUID REFERENCES trials(id),        -- the winning trial; null for hand-crafted
    cluster_id      UUID NOT NULL REFERENCES clusters(id),
    template_id     UUID NOT NULL REFERENCES query_templates(id),
    config_diff     JSONB NOT NULL,                    -- {param: {from, to}}
    metric_delta    JSONB,                             -- {ndcg@10: {baseline, achieved, delta_pct}}; null for hand-crafted
    status          TEXT NOT NULL CHECK (status IN ('pending', 'pr_opened', 'pr_merged', 'rejected')),
    pr_url          TEXT,
    pr_state        TEXT CHECK (pr_state IS NULL OR pr_state IN ('open', 'closed', 'merged')),  -- mirrors GitHub
    pr_merged_at    TIMESTAMPTZ,
    pr_open_error   TEXT,                              -- populated when feat_github_pr_worker fails to open the PR; cleared on successful retry
    rejected_reason TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `conversations`, `messages` (owned by `feat_chat_agent`)

```sql
CREATE TABLE conversations (
    id          UUID PRIMARY KEY,
    title       TEXT,                                  -- auto-generated from first message; nullable
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ                            -- soft-delete per CLAUDE.md convention
);

CREATE TABLE messages (
    id              UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content         JSONB NOT NULL,                    -- {text} or {tool_call} or {tool_response}
    tool_calls      JSONB,                             -- function calls the assistant requested
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Soft-delete on `conversations` filters the row out of `GET /api/v1/conversations` and `GET /api/v1/conversations/{id}` (`deleted_at IS NULL` predicate); messages remain joined via the FK so a future hard-purge runbook can drop both atomically. Hard delete cascades to messages via `ON DELETE CASCADE`.

## Full-text search vectors (owned by `feat_data_table_primitive`)

Migrations `0008`–`0013` add a `search_vector tsvector GENERATED ALWAYS AS … STORED` column + a `GIN(search_vector)` index to six tables. The columns are populated by Postgres on every row write (no application code involvement) and are queried via `search_vector @@ plainto_tsquery('english', :q)` from the API's `?q=` parameter.

| Table | Migration | Indexed fields | API endpoint |
|---|---|---|---|
| `clusters` | `0008` | `name + ' ' + base_url` | `GET /api/v1/clusters` |
| `studies` | `0009` | `name` | `GET /api/v1/studies` |
| `query_sets` | `0010` | `name` | `GET /api/v1/query-sets` |
| `query_templates` | `0011` | `name` | `GET /api/v1/query-templates` |
| `judgment_lists` | `0012` | `name` | `GET /api/v1/judgment-lists` |
| `conversations` | `0013` | `title` | `GET /api/v1/conversations` |

**Hard rule:** `search_vector` is **not declared** in the SQLAlchemy ORM models. The columns are read-only from the application's perspective — Postgres maintains them via the `GENERATED ALWAYS AS … STORED` clause. Any attempt to INSERT or UPDATE these columns will fail with a Postgres error. The Story 2.13 lint guard is not the enforcement point here; the database itself is.

**Rank ordering deferred to MVP2** — the `?q=` predicate filters but does not re-order results, so the existing `(created_at, id)` cursor stays valid. See [`docs/02_product/planned_features/feat_fts_rank_ordering_mvp2/idea.md`](../02_product/planned_features/feat_fts_rank_ordering_mvp2/idea.md) for the rank-ordering follow-up; cursor encoding will need to change to include the `ts_rank` score when that lands.

## Forthcoming: `audit_log` (MVP2 + MVP4 evolution)

Documented here so MVP2 authoring has a target. Not in MVP1.

**MVP2 shape (no users / no tenants yet):**

```sql
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY,                  -- UUIDv7
    tenant_id       UUID,                              -- nullable, NO FK in MVP2 (FK added at MVP4)
    actor_id        UUID,                              -- nullable, NO FK in MVP2 (FK added at MVP4)
    actor_type      TEXT NOT NULL,
    action          TEXT NOT NULL,                     -- 'study.start', 'proposal.pr_opened', ...
    object_type     TEXT NOT NULL,
    object_id       UUID NOT NULL,
    payload         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Named CHECK so MVP4 can DROP and re-add it cleanly.
    CONSTRAINT audit_log_actor_type_check
        CHECK (actor_type IN ('system', 'agent', 'anonymous'))
);

-- MVP2: Postgres trigger blocks UPDATE/DELETE
CREATE FUNCTION audit_log_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();

-- MVP2: API connects via a role with INSERT but no UPDATE/DELETE on audit_log
GRANT INSERT, SELECT ON audit_log TO relyloop_api_role;
```

**MVP4 evolution (when `users` and `tenants` arrive):**

```sql
-- Backfill: tenant_id ← default tenant for pre-MVP4 rows
UPDATE audit_log SET tenant_id = (SELECT id FROM tenants WHERE name = 'default') WHERE tenant_id IS NULL;

-- Add FK constraints
ALTER TABLE audit_log
    ADD CONSTRAINT audit_log_tenant_fk FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    ADD CONSTRAINT audit_log_actor_fk  FOREIGN KEY (actor_id)  REFERENCES users(id);

-- Replace the actor_type CHECK to allow 'user'.
-- Postgres CHECK constraints are ADDITIVE — without the explicit DROP, the original
-- ('system','agent','anonymous') constraint would still block actor_type='user'.
ALTER TABLE audit_log DROP CONSTRAINT audit_log_actor_type_check;
ALTER TABLE audit_log
    ADD CONSTRAINT audit_log_actor_type_check
    CHECK (actor_type IN ('system', 'agent', 'anonymous', 'user'));

-- tenant_id becomes NOT NULL after backfill
ALTER TABLE audit_log ALTER COLUMN tenant_id SET NOT NULL;
```

**Pre-MVP4 audit rows keep `actor_id = NULL`.** A row's `actor_type` tells consumers how to interpret a null actor (system action vs. agent action vs. anonymous).

**Why this shape:** MVP2 needs immutability (the umbrella's contract) without forcing the existence of `users` and `tenants`. Nullable UUIDs with no FK constraints let MVP2 record audit events; MVP4 retro-fits the relational integrity once the referenced tables arrive.

## State transitions

The transitionable entities and their allowed transitions:

```
studies.status:    queued → running → completed
                                   → cancelled
                                   → failed

trials.status:     (no initial state — created with status=complete|failed|pruned)

proposals.status:  pending → pr_opened → pr_merged
                          → rejected
```

Guardrails:
- `studies.status` transitions are gated by service-layer validation; direct DB UPDATE is not used.
- `proposals.status = pr_opened` requires `pr_url` to be non-null.
- `proposals.status = pr_merged` requires `pr_merged_at` to be non-null.

## Optuna RDB co-tenant

Optuna's RDB tables live in the same Postgres instance under the `optuna.*` schema. Migrations are managed by Optuna itself (not by Alembic). The application's Alembic migrations are scoped to the default `public` schema.

```python
storage = optuna.storages.RDBStorage(
    url=f"{DATABASE_URL}?options=-csearch_path=optuna",
    engine_kwargs={"pool_pre_ping": True},
)
```

This co-tenancy is intentional — see [`tech-stack.md`](tech-stack.md) §"Infrastructure" — Postgres is sized to handle both.

## Cross-references

- Stack choices (Postgres 16, SQLAlchemy 2.0, Alembic): [`tech-stack.md`](tech-stack.md)
- Adapter `clusters` table consumer: [`adapters.md`](adapters.md)
- API conventions for CRUD endpoints over these tables: [`api-conventions.md`](api-conventions.md)
- MVP1 navigation summary: [`mvp1-overview.md`](mvp1-overview.md)
