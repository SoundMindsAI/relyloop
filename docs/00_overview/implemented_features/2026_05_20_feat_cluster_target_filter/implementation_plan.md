# Implementation Plan — Per-cluster target filter

**Date:** 2026-05-20
**Status:** Complete (PR #168, merged 2026-05-20 as squash `57d3ba0`)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`docs/01_architecture/adapters.md`](../../../01_architecture/adapters.md), [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md), [`CLAUDE.md`](../../../../CLAUDE.md) (Absolute Rule #4 engine-specific code, Rule #5 migration discipline).

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs and ACs from `feature_spec.md`.
- Backend ships before frontend (migration → adapter → API → modal → empty-state).
- No new endpoints; this feature modifies existing surfaces (`POST /clusters`, `GET /clusters{/list, /{id}, /{id}/targets}`) + adds one Alembic migration.
- Test layers: every backend story gets unit + (where applicable) integration + contract; frontend changes get vitest at unit + component layers.
- Single phase. No deferred phases. PATCH-for-edit is a separately-tracked follow-up (`chore_cluster_update_target_filter`), not a Phase 2.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Story | Notes |
|---|---|---|
| FR-1 (migration + `clusters.target_filter` column) | Epic 1 / Story B1 | Alembic `0014_clusters_target_filter` + `Cluster` ORM column + repo pass-through (already kwargs-based, no signature change needed). |
| FR-2 (Pydantic accepts `target_filter` + trim/non-empty validator) | Epic 1 / Story B3 | Bundled with API surface changes (request schema + response schemas + router). |
| FR-3 (`list_targets()` filter application + Protocol signature update) | Epic 1 / Story B2 | Adapter Protocol + ElasticAdapter + StubAdapter + router pass-through bundled — the contract change must land atomically. |
| FR-4 (register-cluster modal field) | Epic 2 / Story F1 | New input + helper text + trim-then-null submission. |
| FR-5 (filter-aware empty-state copy in create-study modal) | Epic 2 / Story F2 | Read `selectedCluster.target_filter`; branch the `<EntitySelect>` empty-state message. |
| FR-6 (`ClusterDetail` + `ClusterSummary` expose `target_filter`) | Epic 1 / Story B3 | Bundled with FR-2 — response shape changes ride with the request shape change. |

No deferred phases.

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** Two epics, five stories.

- **Epic 1 — Backend** (B1, B3, B2 — note: B3 ships BEFORE B2). Sequence rationale: B1 ships the column; B3 ships the request schema (so API can accept `target_filter` on POST) + response shape; B2 wires the adapter to consume it. **B2's integration test depends on B3 because it registers a cluster via the API with `target_filter="products*"` and asserts the filter is applied — that POST is impossible until B3's Pydantic schema accepts the field.** Reordering avoids B2 having to seed the cluster via direct DB writes.
- **Epic 2 — Frontend** (F1, F2). Both depend on B3 being merged (or at least available on the branch — F1 needs the `CreateClusterRequest` shape update; F2 needs `ClusterSummary` to expose `target_filter` because `useClusters` returns `ClusterSummary[]`, not `ClusterDetail`). F1 and F2 are independent of each other.

### Conventions

- **Backend:** Pydantic schemas in [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py); router in [`backend/app/api/v1/clusters.py`](../../../../backend/app/api/v1/clusters.py); ORM models in [`backend/app/db/models/cluster.py`](../../../../backend/app/db/models/cluster.py); repo functions in [`backend/app/db/repo/cluster.py`](../../../../backend/app/db/repo/cluster.py) (already `**fields`-based — no signature change needed); migrations in [`migrations/versions/`](../../../../migrations/versions/) (next sequential id is `0014`).
- **Adapter:** Protocol in [`backend/app/adapters/protocol.py`](../../../../backend/app/adapters/protocol.py); ElasticAdapter implementation in [`backend/app/adapters/elastic.py`](../../../../backend/app/adapters/elastic.py); test stub in [`backend/tests/integration/fixtures/stub_adapter.py`](../../../../backend/tests/integration/fixtures/stub_adapter.py). CLAUDE.md Absolute Rule #4 — filter logic lives in the adapter, not the router.
- **Frontend:** Register modal at [`ui/src/components/clusters/register-cluster-modal.tsx`](../../../../ui/src/components/clusters/register-cluster-modal.tsx). Create-study modal at [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx). `<EntitySelect>` primitive at [`ui/src/components/common/entity-select.tsx`](../../../../ui/src/components/common/entity-select.tsx) — already accepts `emptyState: { message }`.
- **Generated types:** `ui/src/lib/types.ts` is openapi-typescript output. After B3 lands, regenerate via `cd ui && pnpm types:gen` (requires backend running — `make up`). The wrapper script auto-prepends the GENERATED-FILE banner.
- **Modal tests:** every modal test that exercises `<EntitySelect>` MUST use the canonical [`shadcn-select-mock.tsx`](../../../../ui/src/__tests__/helpers/shadcn-select-mock.tsx) helper via the 3-line dynamic `import()` inside `vi.mock` pattern (per [`ui-architecture.md` §"Modal-level testing"](../../../01_architecture/ui-architecture.md)).

### AI Agent Execution Protocol (applies to every story)

0. Read `CLAUDE.md`, `architecture.md`, `state.md`, `feature_spec.md`, this plan before starting story 1.
1. Implement stories in declared order: B1 → B3 → B2 → F1 → F2. (Note: B3 ships before B2 so B2's integration test can register a filtered cluster through the real API surface.)
2. Backend stories first; after each backend story run `make test-unit && make lint && make typecheck` (and `make test-integration && make test-contract` if the story touches the DB or API surface).
3. After B3 (when the OpenAPI schema changes), regenerate types: `cd ui && pnpm types:gen` (or use the dump-from-app fallback documented in `feat_create_study_target_autocomplete` if Docker isn't running).
4. Frontend stories after B3; `cd ui && pnpm typecheck && pnpm lint && pnpm test && pnpm build` after each.
5. E2E: none new (existing dropdown spec from PR #167 already exercises the targets endpoint; with `target_filter=null` on seeded clusters its behavior is unchanged).
6. Update docs (§4) in the same PR.
7. Migration round-trip evidence: `.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head` against a populated test DB.
8. Attach evidence per the per-story Verification Gate (§10).

---

## Epic 1 — Backend: migration + adapter + API surface

### Story B1 — Migration + ORM column

**Outcome:** `clusters` table gains `target_filter VARCHAR(256) NULL` via a reversible Alembic migration. The `Cluster` ORM model declares the column. All existing rows have `target_filter=NULL` after upgrade (backward-compatible).

**New files**

| File | Purpose |
|---|---|
| `migrations/versions/0014_clusters_target_filter.py` | Alembic migration — `upgrade()` adds the column; `downgrade()` drops it. Idempotency-guarded via `add_column`'s `if_not_exists`-style pattern as established in prior `clusters` migrations. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/models/cluster.py` | After the `notes` mapped_column at line 75-76, add `target_filter: Mapped[str \| None] = mapped_column(String(256), nullable=True)` with a one-line docstring. |

**Endpoints**

None.

**Key interfaces**

```python
# migrations/versions/0014_clusters_target_filter.py
"""Add clusters.target_filter for feat_cluster_target_filter."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_clusters_target_filter"
down_revision = "0013_search_vector_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clusters",
        sa.Column("target_filter", sa.String(length=256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clusters", "target_filter")
```

```python
# backend/app/db/models/cluster.py — addition after the `notes` column (line 75-76)
target_filter: Mapped[str | None] = mapped_column(String(256), nullable=True)
"""Operator-supplied glob pattern (fnmatch.fnmatchcase syntax) scoping
``list_targets()`` to matching index names. NULL = no filter (default,
backward-compat). Trimmed at the API layer; stored verbatim otherwise."""
```

**Pydantic schemas**

None in this story (B3 owns the request/response shape changes).

**Tasks**

1. Create `migrations/versions/0014_clusters_target_filter.py` with `upgrade()` + `downgrade()` per the snippet.
2. Add the `target_filter` column to `Cluster` ORM at `backend/app/db/models/cluster.py` after the `notes` field.
3. Run migration round-trip locally: `.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head` — succeeds with no errors on the demo-seeded DB.
4. Run `make lint && make typecheck` — no errors (the model + migration are typed).

**Definition of Done**

- [ ] Migration file exists at `migrations/versions/0014_clusters_target_filter.py` with both `upgrade()` and `downgrade()`.
- [ ] Round-trip succeeds against the populated demo DB (4 cluster rows preserved + `target_filter` defaults to NULL after both upgrades).
- [ ] `Cluster.target_filter` is queryable: `SELECT target_filter FROM clusters` returns NULL for all existing rows.
- [ ] `make lint && make typecheck` green.
- [ ] No test failures — `make test-unit` still passes (the existing tests don't reference `target_filter` yet).

---

### Story B2 — Adapter contract: Protocol + ElasticAdapter + Stub

**Outcome:** `SearchAdapter.list_targets()` Protocol gains the `target_filter: str | None = None` kwarg. `ElasticAdapter.list_targets()` applies `fnmatch.fnmatchcase(name, target_filter)` after the existing system-index `.` filter. `StubAdapter` accepts the kwarg (no-op). Router pass-through wires it from `cluster.target_filter`. All 5 existing `TestListTargets` cases still pass (regression-safe when `target_filter=None`).

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/app/adapters/protocol.py` | Update `list_targets()` signature at line 131: `async def list_targets(self, *, request_id: str \| None = None, target_filter: str \| None = None) -> list[TargetInfo]`. Update the docstring to mention the new kwarg + `fnmatch.fnmatchcase` semantics. |
| `backend/app/adapters/elastic.py` | Add `import fnmatch` near the top. Update `list_targets()` at line 358 to accept `target_filter` kwarg + apply `fnmatch.fnmatchcase(name, target_filter)` inside the existing row loop (AFTER the `name.startswith('.')` system-index exclusion). |
| `backend/tests/integration/fixtures/stub_adapter.py` | Update `list_targets()` at line 57 to accept the new kwarg (no-op — the stub returns hardcoded data; filter parameter is irrelevant for the contract tests that use it). |
| `backend/app/api/v1/clusters.py` | Update `list_cluster_targets` at line 326 to pass `target_filter=cluster.target_filter` when calling `adapter.list_targets(...)`. |
| `backend/tests/unit/adapters/test_elastic_schema.py` | Extend `TestListTargets` with 4 new cases (FR-3 + AC-6 + AC-7 + AC-8 + case-sensitivity assertion from AC-6). |
| `backend/tests/integration/test_clusters_api.py` | Extend `TestTargetsEndpoint` with 1 new case (AC-9 — real ES + filter applied). |

**Endpoints**

| Method | Path | Change | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/clusters/{cluster_id}/targets` | Server-side: applies `cluster.target_filter` when set. No request/response shape change. | No new error codes. |

**Key interfaces**

```python
# backend/app/adapters/protocol.py — updated method
async def list_targets(
    self,
    *,
    request_id: str | None = None,
    target_filter: str | None = None,
) -> list[TargetInfo]:
    """List indices/collections on the cluster (excludes engine system indices).

    When ``target_filter`` is provided, the result is further restricted to
    names where ``fnmatch.fnmatchcase(name, target_filter)`` returns True.
    Glob syntax: ``*``, ``?``, ``[seq]``, ``[!seq]`` (NO brace expansion;
    pure Python ``fnmatch``). Case-sensitive via ``fnmatchcase`` (avoids
    platform-dependent ``os.path.normcase`` in ``fnmatch.fnmatch``).

    Order of operations: system-index ``.`` exclusion → glob filter. Operators
    cannot re-expose system indices via a permissive filter.

    Concrete implementations raise ``TargetsForbiddenError`` when the engine
    denies the listing call due to ACL (401/403), and ``ClusterUnreachableError``
    for connection failures / 5xx.
    """
    ...
```

```python
# backend/app/adapters/elastic.py — list_targets body change
import fnmatch  # add to imports

async def list_targets(
    self,
    *,
    request_id: str | None = None,
    target_filter: str | None = None,
) -> list[TargetInfo]:
    # ... existing _request call + status mapping unchanged ...

    rows: list[dict[str, Any]] = resp.json()
    out: list[TargetInfo] = []
    for row in rows:
        name = row.get("index")
        if not name or name.startswith("."):
            continue  # system-index filter — applies FIRST
        if target_filter is not None and not fnmatch.fnmatchcase(name, target_filter):
            continue  # glob filter — applies SECOND
        # ... existing doc_count extraction unchanged ...
        out.append(TargetInfo(name=name, doc_count=doc_count))
    return out
```

```python
# backend/app/api/v1/clusters.py — list_cluster_targets pass-through
async def list_cluster_targets(...) -> TargetListResponse:
    # ... existing cluster fetch unchanged ...
    try:
        async with cluster_svc.acquire_adapter(cluster) as adapter:
            targets = await adapter.list_targets(target_filter=cluster.target_filter)
            return TargetListResponse(data=targets)
    except TargetsForbiddenError as exc:
        raise _err(403, "TARGETS_FORBIDDEN", str(exc), False) from exc
    except (ClusterUnreachable, ClusterUnreachableError) as exc:
        raise _err(503, "CLUSTER_UNREACHABLE", str(exc), True) from exc
```

```python
# backend/tests/integration/fixtures/stub_adapter.py — stub accepts but ignores
async def list_targets(
    self,
    *,
    request_id: str | None = None,
    target_filter: str | None = None,  # accept + ignore (stub returns hardcoded data)
) -> list[TargetInfo]:
    return [TargetInfo(name="stub-index", doc_count=100)]
```

**Pydantic schemas**

None.

**Tasks**

1. Update `SearchAdapter.list_targets()` signature in `protocol.py`. Update docstring.
2. Add `import fnmatch` to `elastic.py`. Update `list_targets()` implementation: accept the kwarg, apply the filter after the system-index check.
3. Update `StubAdapter.list_targets()` in `stub_adapter.py` to accept the kwarg (no-op body).
4. Update the router in `clusters.py:326` to pass `target_filter=cluster.target_filter` to `adapter.list_targets()`.
5. Extend `TestListTargets` in `test_elastic_schema.py` with 4 new cases per §3.1 unit list.
6. Extend `TestTargetsEndpoint` in `test_clusters_api.py` with 1 new case per §3.2 integration list (requires real ES + multiple seeded indices).
7. Run `make test-unit && make test-integration && make test-contract && make lint && make typecheck`.

**Definition of Done**

- [ ] `list_targets()` Protocol + ElasticAdapter + StubAdapter all have the new `target_filter` kwarg with matching default (`None`).
- [ ] Router passes `cluster.target_filter` to the adapter (verified by reading the diff).
- [ ] `TestListTargets::test_filter_null_is_passthrough` — `target_filter=None` returns the same result as today (AC-7).
- [ ] `TestListTargets::test_filter_matches_subset` — `target_filter="products*"` against `["products", "products-v2", "docs-articles", ".kibana_1"]` returns only `products` + `products-v2` (AC-6).
- [ ] `TestListTargets::test_filter_is_case_sensitive` — `target_filter="PRODUCTS*"` against the same mock returns `[]` (AC-6 — `fnmatchcase` semantics; would fail platform-dependent if `fnmatch.fnmatch` were used).
- [ ] `TestListTargets::test_filter_cannot_reexpose_system_indices` — `target_filter="*"` against the same mock excludes `.kibana_1` (AC-8 — order of operations).
- [ ] `TestTargetsEndpoint::test_real_es_filter_applied` — register cluster with `target_filter="products*"` against real ES + 2 matching + 2 non-matching seeded indices, assert response excludes non-matching (AC-9).
- [ ] All 5 existing `TestListTargets` cases still pass (regression-safe).
- [ ] `make test-unit && make test-integration && make test-contract && make lint && make typecheck` green.

---

### Story B3 — API surface: Pydantic schemas + validator + response exposure + service plumb-through

**Outcome:** `CreateClusterRequest` accepts `target_filter: str | None` with a `mode="before"` trim validator (so `min_length`/`max_length` see the stripped value). `ClusterDetail` and `ClusterSummary` expose `target_filter`. **The `register_cluster` service signature gains the kwarg and forwards it to both `repo.create_cluster()` and `repo.revive_cluster()`**, and the `POST /clusters` router passes `body.target_filter` through. (Verified at plan time: `register_cluster` uses explicit kwargs, NOT `**fields` — silent-drop risk if the kwarg isn't added.)

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` | (a) `CreateClusterRequest` at line 50: add `target_filter: str \| None = Field(default=None, min_length=1, max_length=256)` + a `@field_validator('target_filter', mode='before')` that strips whitespace BEFORE `min_length`/`max_length` run. (b) `ClusterDetail` at line 94: add `target_filter: str \| None = None`. (c) `ClusterSummary` at line 109: add `target_filter: str \| None = None`. |
| `backend/app/api/v1/clusters.py` | (a) `create_cluster` router at line 158-176: add `target_filter=body.target_filter` to the `register_cluster(...)` call. (b) `_summary()` helper at line 116 + the detail builder: populate the new field from `cluster.target_filter`. |
| `backend/app/services/cluster.py` | `register_cluster` signature at line 83-94: add `target_filter: str \| None` after `notes`. In the `revive_cluster(...)` call at line 160-170, add `target_filter=target_filter`. In the `create_cluster(...)` call at line 172-183, add `target_filter=target_filter`. (Both repo functions already accept arbitrary kwargs — no repo change needed.) |
| `backend/tests/contract/test_clusters_api_contract.py` | Extend the import-smoke + add a `test_create_cluster_request_target_filter_validation` case for trim semantics (including padded-valid case proving `mode="before"` works). |
| `backend/tests/integration/test_clusters_api.py` | Extend `TestPostCluster` with 5 new cases (AC-2, AC-3, AC-4, AC-5, padded-valid for Finding #5) — valid filter accepted; whitespace rejected; empty-string rejected; omitted field defaults to NULL; padded `"  products*  "` persists as `"products*"`. Extend `TestGetCluster` with 1 case asserting `target_filter` appears in `ClusterDetail` response (AC-10). Extend `TestListClusters` (or add it) with 1 case asserting `target_filter` appears in each `ClusterSummary` row from `GET /clusters` (Finding #2 — F2's data plumbing dependency). All 422 cases assert the standard envelope: `detail.error_code == "VALIDATION_ERROR"` AND `detail.retryable is false` (Finding #4). |

**Endpoints**

| Method | Path | Change | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/clusters` | New optional body field `target_filter: str` | `VALIDATION_ERROR` (422) when whitespace-only, empty, or > 256 chars |
| `GET` | `/api/v1/clusters/{cluster_id}` | Response gains `target_filter` (always present, `null` when not set) | No new code |
| `GET` | `/api/v1/clusters` | Each `ClusterSummary` gains `target_filter` | No new code |

**Key interfaces**

```python
# backend/app/api/v1/schemas.py — CreateClusterRequest addition
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class CreateClusterRequest(BaseModel):
    # ... existing 8 fields unchanged ...
    target_filter: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description=(
            "Optional glob pattern (fnmatch.fnmatchcase: *, ?, [seq], [!seq]; "
            "no brace expansion). Scopes GET /clusters/{id}/targets to "
            "matching index names. Null = no filter."
        ),
    )

    # ... existing base_url validator unchanged ...

    @field_validator("target_filter", mode="before")
    @classmethod
    def strip_target_filter(cls, v: Any) -> Any:
        """Strip leading/trailing whitespace BEFORE min_length/max_length run.

        Pydantic v2 default validator mode is ``after`` — that would let a
        padded valid filter like ``"  " + "x"*256`` fail max_length=256 even
        though the stripped value is 256 chars. ``mode="before"`` runs the
        strip first; ``min_length=1`` then catches the empty/whitespace-only
        case AND ``max_length=256`` runs on the stripped value.

        Glob syntax is NOT validated — Python ``fnmatch`` is permissive and
        accepts every non-empty string (unmatched ``[`` becomes literal, lone
        ``?``/``*`` match one/many chars, etc.). The user-meaningful validation
        is length + non-empty-after-trim. A pattern that matches nothing at
        runtime surfaces via the create-study modal's empty-state message
        (FR-5), not a 422.
        """
        if isinstance(v, str):
            return v.strip()
        return v  # let core validation handle None / non-strings


# ClusterDetail addition (after `notes` field at line 104):
class ClusterDetail(BaseModel):
    # ... existing fields ...
    target_filter: str | None = None

# ClusterSummary addition (mirror, after `auth_kind` field):
class ClusterSummary(BaseModel):
    # ... existing fields ...
    target_filter: str | None = None
```

```python
# backend/app/api/v1/clusters.py — _summary helper update
def _summary(cluster: Cluster, health: HealthStatus) -> ClusterSummary:
    return ClusterSummary(
        # ... existing fields ...
        target_filter=cluster.target_filter,
        health_check=...,
    )
```

**Pydantic schemas**

(Defined in Key interfaces above.)

**Tasks**

1. Update `CreateClusterRequest` in `schemas.py` with the new field + `@field_validator(..., mode="before")`.
2. Update `ClusterDetail` + `ClusterSummary` to include `target_filter: str | None = None`.
3. Update `register_cluster()` in `backend/app/services/cluster.py:83`: add `target_filter: str | None` to signature; forward to `repo.create_cluster(target_filter=...)` AND `repo.revive_cluster(target_filter=...)`.
4. Update `create_cluster` router in `backend/app/api/v1/clusters.py:158-176`: add `target_filter=body.target_filter` to the `register_cluster(...)` call.
5. Update `_summary()` helper in `clusters.py:116` + the detail builder to populate `target_filter` from `cluster.target_filter`.
6. Add validator tests in `test_clusters_api_contract.py` (trim semantics, empty rejection, max-length, padded-valid).
7. Add integration cases in `test_clusters_api.py::TestPostCluster` (5 new) + `TestGetCluster` (1 new for AC-10) + `TestListClusters` (1 new for F2 plumbing).
8. Regenerate UI types: `cd ui && pnpm types:gen` (requires backend running) so `CreateClusterRequest` + `ClusterDetail` + `ClusterSummary` reflect the new field in `ui/src/lib/types.ts`. Document the fallback: dump via `python3 -c "from backend.app.main import app; import json; print(json.dumps(app.openapi()))" > /tmp/openapi.json` then `pnpm exec openapi-typescript file:///tmp/openapi.json -o src/lib/types.ts && pnpm exec prettier --write src/lib/types.ts`, restoring the banner manually.
9. Run `make test-integration && make test-contract && make lint && make typecheck`.

**Definition of Done**

- [ ] `CreateClusterRequest.target_filter` accepted (AC-2 — `"products*"` → 201 with the field round-tripped and **persisted to the DB row**, not just echoed by the API).
- [ ] Whitespace-only `"   "` rejected as 422 with envelope `{detail: {error_code: "VALIDATION_ERROR", retryable: false, ...}}` (AC-3 + Finding #4).
- [ ] Empty-string `""` rejected as 422 with the same envelope (AC-4 + Finding #4).
- [ ] Omitted field → `target_filter: null` in response, `NULL` in DB (AC-5).
- [ ] Padded `"  products*  "` persists as `"products*"` (no max_length false positive on whitespace) — proves `mode="before"` (Finding #5).
- [ ] `GET /clusters/{id}` returns `target_filter: "products*"` for a cluster registered with the filter (AC-10).
- [ ] `GET /clusters` list response — each `ClusterSummary` includes `target_filter` field populated from the DB row, not just declared in the schema (Finding #2 — F2's data plumbing dependency).
- [ ] `register_cluster()` integration test (or assertion in the existing case) confirms `cluster.target_filter` in the returned `Cluster` ORM row matches the request input (catches silent-drop regressions per Finding #3).
- [ ] `ui/src/lib/types.ts` regenerated; `components['schemas']['CreateClusterRequest'].target_filter` and `components['schemas']['ClusterSummary'].target_filter` both exist.
- [ ] `make test-integration && make test-contract && make lint && make typecheck` green.

---

## Epic 2 — Frontend: register modal + empty-state branching

### Story F1 — Register-cluster modal adds Target filter input

**Outcome:** Operator opens the register-cluster modal, fills the new "Target filter (optional)" input, submits, and the cluster row in the DB has the filter set. Trim happens client-side before the empty-check so whitespace-only converts to `null`.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/clusters/register-cluster-modal.tsx` | Add: (a) `target_filter` to `defaultValues` (line ~68) as `''`; (b) the new `<Label>` + `<Input id="cl-target-filter">` + helper text block after the Notes block (line ~230-231); (c) submit `target_filter: values.target_filter.trim() \|\| null` (line ~82-83 pattern matches existing `notes`). |
| `ui/src/__tests__/components/clusters/register-cluster-modal.test.tsx` | Add 2 new cases: filling the filter + submit asserts request body (AC-11); whitespace-only submits null (AC-12). |

**Endpoints**

None added (consumes `POST /api/v1/clusters` from B3).

**Key interfaces**

```tsx
// ui/src/components/clusters/register-cluster-modal.tsx — defaultValues addition (~line 68)
defaultValues: {
  name: '',
  engine_type: 'elasticsearch',
  // ... existing defaults ...
  notes: '',
  target_filter: '',  // NEW
},

// onSubmit pattern (~line 82-83): same trim-or-null as notes
const payload: CreateClusterRequest = {
  // ... existing fields ...
  notes: values.notes || null,
  target_filter: values.target_filter.trim() || null,  // NEW — trim FIRST
};

// JSX field — inserted AFTER the Notes block (after line 231):
<div className="space-y-1.5">
  <Label htmlFor="cl-target-filter">Target filter (optional)</Label>
  <Input id="cl-target-filter" {...form.register('target_filter')} />
  <p className="text-xs text-muted-foreground">
    Glob pattern restricting which indices appear in the target picker for this
    cluster. Supports <code>*</code> (any chars), <code>?</code> (single char),
    and <code>[seq]</code> / <code>[!seq]</code> character classes. Example:{' '}
    <code>products*</code> matches every index starting with 'products'. Brace
    expansion (<code>{'{a,b}'}</code>) is NOT supported — register two clusters
    if you need OR-of-globs. Leave blank to show every user-facing index.
  </p>
</div>
```

**Pydantic schemas**

N/A (frontend story).

**Tasks**

1. Read `register-cluster-modal.tsx` current state (line counts shift between branches; verify the Notes block is still at ~line 230 before editing).
2. Add `target_filter: ''` to `defaultValues` (~line 68).
3. Add the JSX block after the Notes section.
4. Update `onSubmit` to include `target_filter: values.target_filter.trim() || null`.
5. Verify the FormValues type accepts the new field (TypeScript will complain if not — react-hook-form derives it from the defaults).
6. Add component tests (2 new cases) using the existing test pattern + shadcn-select-mock helper if `<EntitySelect>` is involved (it isn't here — this is a plain Input).
7. Run `cd ui && pnpm typecheck && pnpm lint && pnpm test`.

**Definition of Done**

- [ ] Register-cluster modal renders a labeled `<Input id="cl-target-filter">` below the Notes Textarea.
- [ ] Helper text matches the spec FR-4 wording (including the no-brace-expansion callout).
- [ ] Filling `"products*"` + submitting → request body contains `"target_filter": "products*"` (AC-11; tested via msw or fetch-mock assertion).
- [ ] Filling `"   "` (3 spaces) + submitting → request body contains `"target_filter": null` (AC-12).
- [ ] Empty input → request body contains `"target_filter": null` (existing precedent — same as `notes`).
- [ ] `cd ui && pnpm typecheck && pnpm lint && pnpm test` green.

---

### Story F2 — Create-study modal: filter-aware empty-state

**Outcome:** When the operator picks a cluster that has a `target_filter` set AND the targets endpoint returns `{data: []}`, the `<EntitySelect>` empty-state shows the filter-specific message. When `target_filter` is null and data is empty, the existing message is preserved.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/create-study-modal.tsx` | Update the `<EntitySelect>` rendering for the target field (the no-cluster + dropdown-mode branches added by `feat_create_study_target_autocomplete`). The dropdown branch's `emptyState` prop becomes conditional on `selectedCluster?.target_filter`. |
| `ui/src/__tests__/components/studies/create-study-modal.test.tsx` | Extend with 1 case asserting the filter-aware empty-state message (AC-13) + 1 regression case for the unchanged message when filter is null (AC-14). |

**Endpoints**

None added; consumes `GET /api/v1/clusters` (for `selectedCluster`) and `GET /api/v1/clusters/{id}/targets` from existing hooks.

**Key interfaces**

```tsx
// ui/src/components/studies/create-study-modal.tsx — emptyState prop changes
// `selectedCluster` is already derived at line 144 (post-F2 from PR #165):
//   const selectedCluster = clusters.data?.data.find((c) => c.id === clusterId);
// `selectedCluster.target_filter` will be present once Story B3 ships
// (regenerated types include it on ClusterSummary).

<EntitySelect
  id="cs-target"
  data-testid="cs-target"
  query={sortedTargetsQuery}
  getId={(t: TargetSummary) => t.name}
  getLabel={(t: TargetSummary) => `${t.name} (${t.doc_count != null ? t.doc_count.toLocaleString() : '?'} docs)`}
  value={values.target || undefined}
  onChange={(v) => form.setValue('target', v ?? '')}
  placeholder="Choose a target"
  emptyState={{
    message: selectedCluster?.target_filter
      ? `No targets match filter "${selectedCluster.target_filter}" on this cluster. To change the filter, delete and re-register the cluster — MVP1 has no in-place edit for cluster registrations.`
      : 'No targets found on this cluster.',
  }}
/>
```

**Pydantic schemas**

N/A.

**Tasks**

1. Read the current create-study modal's Step 1 render (the F2 dropdown branch landed in `feat_create_study_target_autocomplete` PR #165; verify the `<EntitySelect>` line for the target picker is still where the spec cites).
2. Modify the `emptyState.message` prop to the ternary above, using `selectedCluster?.target_filter`.
3. Add component test cases per §3.1 frontend unit list.
4. Run `cd ui && pnpm typecheck && pnpm lint && pnpm test`.

**Definition of Done**

- [ ] When `selectedCluster.target_filter` is non-null AND `useClusterTargets` returns `{data: []}`, the dropdown trigger's empty-state placeholder shows the filter-specific message exactly: `No targets match filter "<filter>" on this cluster. To change the filter, delete and re-register the cluster — MVP1 has no in-place edit for cluster registrations.` (AC-13)
- [ ] When `selectedCluster.target_filter` is null AND `useClusterTargets` returns `{data: []}`, the dropdown shows `No targets found on this cluster.` (existing behavior — AC-14; regression-safe).
- [ ] When `selectedCluster` itself is undefined (race condition during initial render), the empty-state falls back to the null-filter message (defensive — `?.` short-circuits to falsy).
- [ ] `cd ui && pnpm typecheck && pnpm lint && pnpm test` green; 525+ vitest cases still pass.

---

## UI Guidance

Both F1 and F2 are small, single-component touches. The full UI Guidance template would be over-engineered here. The story-level interfaces + key-snippets above are sufficient for AI-agent implementation. The two relevant inflated-template sections:

### Insertion points

- **F1 — register-cluster-modal.tsx:** New `<div className="space-y-1.5">` block inserted between the existing Notes block (ending around line 231) and the `<DialogFooter>` block. Verify exact line numbers at impl time — Notes block uses `<Textarea id="cl-notes">` with helper text, identical structure to what F1 adds for the filter.
- **F2 — create-study-modal.tsx:** Inline modification of the `emptyState.message` prop on the `<EntitySelect>` for the target field (the F2 dropdown branch from `feat_create_study_target_autocomplete`). No new JSX block; only the prop expression changes.

### Analogous markup patterns

- **F1 Input + helper text:** Mirror the Notes block precedent exactly. Same `space-y-1.5` outer div, same `<Label htmlFor="...">` + `<Input>` pattern, same `text-xs text-muted-foreground` helper text class. Only difference: `<Input>` (single-line) instead of `<Textarea>` (multi-line) — `target_filter` is bounded at 256 chars and looks fine in a single-line input.
- **F2 conditional empty-state:** `<EntitySelect>` already accepts `emptyState: { message: string }`. The change is purely in the `message` value (a ternary on `selectedCluster?.target_filter`). No primitive surface change.

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Open register modal, fill all fields including `target_filter="products*"`, click Submit | Form validates client-side, POST request with `target_filter: "products*"` | `POST /api/v1/clusters` → 201 with the field in response |
| Same form, leave Target filter blank | Submit with `target_filter: null` | `POST /api/v1/clusters` → 201 with `target_filter: null` |
| Same form, type whitespace-only `"   "` in Target filter | Frontend trim → submit with `target_filter: null` (NOT the empty/whitespace string) | `POST /api/v1/clusters` → 201 with `target_filter: null` |
| Open create-study modal, pick cluster with `target_filter="non-matching-*"` | `useClusterTargets` fires, returns `{data: []}`, EntitySelect renders empty-state with filter-aware message | `GET /api/v1/clusters/{id}/targets` returns 200 + empty data |

### Information architecture placement (F1)

Field placed at the END of the form (after Notes, before submit row). Rationale: optional + advanced — most operators leave blank. Placing it last keeps the common-case form scan-path short.

### Information architecture placement (F2)

No IA change; the empty-state message is inline in an existing component. No new tab, no new dialog, no new section.

### Tooltips and contextual help

- **F1 helper text** (always visible, below the input): per FR-4 — `"Glob pattern restricting which indices appear in the target picker for this cluster. Supports * (any chars), ? (single char), and [seq] / [!seq] character classes. Example: products* matches every index starting with 'products'. Brace expansion ({a,b}) is NOT supported — register two clusters if you need OR-of-globs. Leave blank to show every user-facing index."`
- **F2 empty-state message** is itself the contextual help — no additional tooltip.

### Visual consistency

| New element | CSS / pattern source |
|---|---|
| F1 Target filter input | Mirrors existing Notes Textarea block — same outer `space-y-1.5`, same Label class, same helper `text-xs text-muted-foreground`. Input variant of the same shadcn family. |
| F2 empty-state copy | Same `<EntitySelect>` primitive's existing `emptyState.message` rendering (disabled trigger showing the message). No new style. |

### Component composition

Both inline. Neither story extracts a new component. F1 adds ~12 LOC to the modal; F2 changes a single prop expression. Extracting either would be over-engineering for this scope.

### Legacy behavior parity

No legacy parity table needed — neither story deletes or replaces a user-facing component >100 LOC. F1 adds a new field to an existing form (no deletion). F2 modifies one prop expression on an existing component (no deletion).

### Client-side persistence

None. All form state is React state via react-hook-form (cleared on modal close). No `localStorage` / `sessionStorage`.

---

## 3) Testing workstream

### 3.1 Unit tests

**Backend unit** (`backend/tests/unit/adapters/`):

- [ ] **B2 — `test_elastic_schema.py::TestListTargets`** (extend): 4 new cases
  - `test_filter_null_is_passthrough` — `target_filter=None` produces same result as today (AC-7; regression-safe).
  - `test_filter_matches_subset` — `target_filter="products*"` against `["products", "products-v2", "docs-articles", ".kibana_1"]` returns 2 results (AC-6).
  - `test_filter_is_case_sensitive` — `target_filter="PRODUCTS*"` returns `[]` (AC-6 case assertion; would fail platform-dependent if `fnmatch.fnmatch` were used instead of `fnmatchcase`).
  - `test_filter_cannot_reexpose_system_indices` — `target_filter="*"` excludes `.kibana_1` (AC-8; order of operations).

**Backend contract** (`backend/tests/contract/`):

- [ ] **B3 — `test_clusters_api_contract.py`** (extend): add `test_create_cluster_request_target_filter_validation`
  - Pydantic accepts valid 1–256 char strings.
  - Rejects empty string + whitespace-only with `ValidationError`.
  - Rejects > 256 chars with `ValidationError`.
- [ ] **B3 — `test_openapi_surface.py`** — no change needed (no new endpoints).

**Frontend unit** (`ui/src/__tests__/`):

- [ ] **F1 — `components/clusters/register-cluster-modal.test.tsx`** (extend): 2 new cases
  - Filling `"products*"` + submit → request body contains `target_filter: "products*"` (AC-11).
  - Filling `"   "` + submit → request body contains `target_filter: null` (AC-12; whitespace trimmed to null).
- [ ] **F2 — `components/studies/create-study-modal.test.tsx`** (extend): 2 new cases
  - Cluster with `target_filter="non-matching-*"` + empty `useClusterTargets` data → empty-state message includes the filter value verbatim and the "delete and re-register" instruction (AC-13).
  - Cluster with `target_filter=null` + empty data → existing `"No targets found on this cluster."` message (AC-14; regression).
  - **Mock discipline:** use the canonical shadcn-select-mock helper for any test exercising `<EntitySelect>` inside the create-study Dialog.

### 3.2 Integration tests

**Backend integration** (`backend/tests/integration/`):

- [ ] **B3 — `test_clusters_api.py::TestPostCluster`** (extend): 5 new cases
  - `test_post_with_target_filter` — valid pattern → 201 + field round-tripped to API response AND persisted in DB row (AC-2 + Finding #3 silent-drop guard).
  - `test_post_target_filter_whitespace_only_422` — `"   "` → 422; assert `detail.error_code == "VALIDATION_ERROR"` AND `detail.retryable is False` (AC-3 + Finding #4).
  - `test_post_target_filter_empty_string_422` — `""` → 422 with same envelope (AC-4 + Finding #4).
  - `test_post_omits_target_filter_defaults_null` — field absent from body → 201 with `target_filter: null` in response and `NULL` in DB (AC-5).
  - `test_post_target_filter_padded_strips_to_canonical` — `"  products*  "` → 201; DB row has `target_filter == "products*"` (Finding #5 — proves `mode="before"` validator).
- [ ] **B3 — `test_clusters_api.py::TestGetCluster`** (extend): 1 new case
  - `test_get_cluster_exposes_target_filter` — register with filter, GET detail, assert `target_filter` in response (AC-10).
- [ ] **B3 — `test_clusters_api.py::TestListClusters`** (extend, or add the class if absent): 1 new case
  - `test_list_clusters_summary_includes_target_filter` — register one cluster with `target_filter="products*"` and one without; `GET /clusters` returns both; assert the filtered cluster's `ClusterSummary` row has `target_filter == "products*"` and the other has `target_filter is None`. This guards F2's data plumbing — without it, `_summary()` could omit the field and the OpenAPI schema would still validate (Finding #2).
- [ ] **B2 — `test_clusters_api.py::TestTargetsEndpoint`** (extend): 1 new case
  - `test_targets_endpoint_applies_filter` — register a cluster with `target_filter="products*"` against real ES; seed 2 matching + 2 non-matching indices (`products`, `products-v2`, `docs-articles`, `job-listings`); assert `GET /clusters/{id}/targets` returns only the 2 matching (AC-9). Use the existing `ENGINE_PARAMS` parametrize so the test runs against ES AND OpenSearch.
- [ ] **B1 — migration round-trip** — add a `test_0014_migration_round_trip` case to either `test_clusters_api.py` or a new `test_migrations.py` that exercises `alembic upgrade head → downgrade -1 → upgrade head` on a populated DB and asserts no data loss on the other 13 columns (AC-1).

### 3.3 Contract tests

- [ ] **B3 — `test_clusters_api_contract.py`** (extend): assert `target_filter` field is present in the OpenAPI schemas for `CreateClusterRequest`, `ClusterDetail`, `ClusterSummary`. No new error codes (the existing `VALIDATION_ERROR` envelope covers FR-2 rejections; existing test in `test_error_codes.py` already covers the envelope shape).
- [ ] **B3 — `test_openapi_surface.py`** — no row to add; no new endpoints.

### 3.4 E2E tests

None new for this feature. The existing `studies-create-target-dropdown.spec.ts` (PR #167) exercises the dropdown happy path. With `target_filter=null` on the seeded clusters its behavior is unchanged — it's a passive regression check.

### 3.5 Existing test impact audit

| Test file | Pattern | Required action |
|---|---|---|
| `backend/tests/unit/adapters/test_elastic_schema.py::TestListTargets` (5 existing cases) | Calls `adapter.list_targets()` with no args | **No change** — `target_filter` defaults to `None`, matches current behavior. The 4 new cases (above) extend coverage. |
| `backend/tests/integration/test_clusters_api.py::TestTargetsEndpoint` (existing real-ES case) | Asserts user-facing indices vs system indices | **No change** — registers cluster without filter; `target_filter` defaults NULL. |
| `backend/tests/integration/test_clusters_api_targets_errors.py` (3 monkeypatch cases) | Uses `StubAdapter` to inject exceptions | **Update** — `StubAdapter.list_targets()` signature gains `target_filter` kwarg in Story B2. Test calls still work (no kwarg passed). |
| `ui/tests/e2e/studies-create-target-dropdown.spec.ts` (1 real-backend dropdown happy-path case from PR #167) | Seeds 2 indices + picks one via dropdown | **No change** — test's seeded cluster will have `target_filter=null` (the seed helper doesn't set it), so all seeded indices appear; matches today's behavior. |
| `ui/src/__tests__/components/studies/create-study-modal.test.tsx` (5 modal cases incl. empty-state assertion from PR #165) | Asserts empty-state message | **Update** — the existing AC-14-equivalent test continues to pass (regression: `target_filter=null` → existing message); the new AC-13 case adds coverage. |

### 3.5 Migration verification

- [ ] **B1** — `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` succeeds on the populated demo DB.
- [ ] Alembic version table reaches `0014_clusters_target_filter` after upgrade.
- [ ] All 4 demo cluster rows preserved across the round-trip with `target_filter=NULL`.
- [ ] DB revision guard passes at API startup (no failures on import).

### 3.6 CI gates

- [ ] `make test-unit` (existing adapter + new `TestListTargets` cases)
- [ ] `make test-integration` (existing cluster integration + new B3 + B2 cases)
- [ ] `make test-contract` (existing + B3 Pydantic shape extension)
- [ ] `make lint && make typecheck`
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build`

---

## 4) Documentation update workstream

### 4.0 Core context files

- **`state.md`** — after PR merges: add a "Most recent meaningful changes" entry for `feat_cluster_target_filter`; mark active feature as none in flight; update branch/PR pointer.
- **`architecture.md`** — no update needed (no new layer).
- **`CLAUDE.md`** — no update needed (no new convention/env var/rule).

### 4.1 Architecture docs

- [ ] **`docs/01_architecture/adapters.md`** — update `SearchAdapter.list_targets()` description to mention the new `target_filter` kwarg + glob semantics + system-index-first order of operations.
- [ ] **`docs/01_architecture/data-model.md`** — `clusters` table column list adds `target_filter VARCHAR(256) NULL` with a one-line description.

### 4.2 Product docs

- [ ] Move `docs/00_overview/planned_features/feat_cluster_target_filter/` → `docs/00_overview/implemented_features/<YYYY_MM_DD>_feat_cluster_target_filter/` (per `/impl-execute` finalization).

### 4.3–4.5

- `docs/03_runbooks/` — N/A
- `docs/04_security/` — N/A
- `docs/05_quality/` — N/A

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- None planned. This is an additive feature; existing patterns are reused (kwargs-based repo, Pydantic field+validator, EntitySelect emptyState prop).

### 5.2 Planned refactor tasks

- [ ] None.

### 5.3 Refactor guardrails

- [ ] N/A — no refactor.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_create_study_target_autocomplete` (parent) — targets endpoint + dropdown UI | All stories | **Shipped** (PR #165 squash `bd4516a`, finalized PR #166 squash `21a75e1`) | None — verified merged to main. |
| `feat_create_study_target_autocomplete` follow-up PR #167 — dropdown E2E un-skip + `bug_get_schema_unhandled_connect_error` folder move | Coordinate-only (E2E spec exists at the path FR-3 references) | **Shipped** (squash `4735e8e`) | None. |
| Alembic head `0013_search_vector_conversations` | Story B1 | **Active** | None — next sequential is `0014`. |
| `ENGINE_PARAMS` parametrize fixture in `test_clusters_api.py` | Story B2 integration test | **Active** (`ENGINE_PARAMS = [pytest.param("elasticsearch", id="es"), pytest.param("opensearch", id="opensearch")]`) | None. |
| `shadcn-select-mock.tsx` helper for F2 vitest | Story F2 | **Shipped** (`chore_extract_shadcn_select_test_mock`) | None. |
| Demo data seed (4 clusters, 4 query sets, etc.) | Manual validation post-merge | **Shipped** (today's session — `/tmp/seed_meaningful_demos.py`) | None — demo will retroactively benefit from per-cluster filter once we re-seed with `target_filter` set per scenario. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Operator types `docs-{en,fr}-*` expecting brace expansion → gets zero matches | Medium | Low | Helper text explicitly callouts "Brace expansion ({a,b}) is NOT supported." Empty-state message confirms the filter value so the operator sees the literal `{en,fr}` and recognizes the mistake. |
| `fnmatch.fnmatchcase` performance on clusters with thousands of indices | Low | Low | `fnmatchcase` is O(pattern_length × name_length); for 1000 indices × 30-char names × 10-char pattern = 300K character comparisons total. Sub-millisecond on modern hardware. Documented in §13 of spec. |
| Operator registers cluster with filter that excludes ALL indices on the engine today, but ALL indices later | Low | Low | Spec Locked Decision #4: no cascade validation. The filter is just metadata; existing studies' `target` values are unaffected. New studies hit the FR-5 empty-state message. |
| Migration takes a long lock on a large `clusters` table in prod | Very Low | Low | `add_column` of a nullable column is a metadata-only operation in PostgreSQL 11+. No row rewrite. Round-trip test will confirm. |
| Whitespace handling drift between frontend trim (F1) and backend validator (B3) | Low | Medium | Both implement the same semantics: trim, reject empty. Validator runs last (server-authoritative). Frontend trim is a UX nicety to avoid an unnecessary 422. Tests at both layers (AC-12 frontend, AC-3 backend) verify alignment. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Operator sets a filter, then later adds an index that doesn't match | Operator adds an index out-of-band | New index doesn't appear in the picker (correct — filter is "scope" semantics) | Operator either renames the index to match the existing filter OR DELETEs + re-registers the cluster with a relaxed filter |
| Migration `0014` fails to upgrade on a live DB | DB corruption or pre-existing column conflict | Alembic aborts; existing rows remain in the pre-migration shape | Operator inspects error; either resolves the conflict + re-runs, or downgrades and patches the migration |
| Frontend submits a filter value the backend rejects (e.g., operator pasted control characters) | Pydantic `min_length=1` + validator | 422 `VALIDATION_ERROR` envelope | Toast displays the error; form stays open; operator corrects + re-submits |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **B1** — migration + ORM column (must land first; everything else depends on the column existing).
2. **B3** — Pydantic + validator + response shape + **service/router plumb-through** (depends only on B1's column). Ships BEFORE B2 so B2's integration test can register a filtered cluster via the real API.
3. **B2** — adapter contract change (Protocol + ElasticAdapter + StubAdapter + router consumption of `cluster.target_filter`).
4. **F1** — register modal (depends on B3 for the request shape).
5. **F2** — empty-state branching (depends on B3 for `selectedCluster.target_filter` on `ClusterSummary`).

In practice (single-developer flow): B1 → B3 → B2 → F1 → F2.

### Parallelization opportunities

- **F1 || F2** — register modal and create-study modal are completely independent; only ordering constraint is "both after B3."
- **B3 || B2** is technically possible since they touch disjoint files, but the test plan for B2 requires API-level cluster creation with `target_filter`, so practically B3 ships first.

---

## 8) Rollout and cutover plan

- **Rollout stages:** Internal single-tenant MVP1 — ship on merge; no staged rollout.
- **Feature flags:** None.
- **Migration/cutover steps:** Alembic `0014` runs on `make migrate`; column defaults NULL so existing rows preserved.
- **Backfill expectations:** None. `target_filter=NULL` is the correct value for all existing rows.
- **Reconciliation/repair strategy:** N/A.
- **Post-merge:** Re-seed demo with `target_filter` set per cluster (`acme-products-prod` → `products*`, `corp-docs-search` → `docs-*`, `news-search-staging` → `news-*`, `jobs-marketplace-prod` → `job-*`) so the dropdown demos cleanly. Captured in the parent session's todo list as the "Re-seed demo with target_filter set per cluster (post-merge)" item.

---

## 9) Execution tracker (copy/paste section)

### Current sprint

- [ ] **Story B1** — Migration + `Cluster.target_filter` ORM column
- [ ] **Story B2** — Adapter Protocol + ElasticAdapter + StubAdapter + router pass-through
- [ ] **Story B3** — Pydantic schemas (request validator + response exposure) + helper update
- [ ] **Story F1** — Register-cluster modal Target filter input
- [ ] **Story F2** — Create-study modal filter-aware empty-state

### Blocked items

- (None at plan time.)

### Done this sprint

- (Populated as stories complete.)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete:

- [ ] Files created/modified match the story's New files / Modified files tables.
- [ ] Key interfaces implemented with matching signatures (Protocol, ORM column, Pydantic field, validator, frontend input).
- [ ] Required tests added/updated for every layer the story touches.
- [ ] Commands run + passed:
  - [ ] `make test-unit` (B1, B2)
  - [ ] `make test-integration` (B2, B3)
  - [ ] `make test-contract` (B3)
  - [ ] `make lint && make typecheck` (every backend story)
  - [ ] `cd ui && pnpm typecheck && pnpm lint && pnpm test && pnpm build` (F1, F2)
- [ ] Migration round-trip evidence captured for B1.
- [ ] Related docs (§4) updated in the same PR (final story).

---

## 11) Plan consistency review

### Cross-model review log

**Cycle 1 (GPT-5.5 2026-05-20):** 5 findings raised across Pass A (3) + Pass B (2). All 5 accepted with patches applied to this plan:

| # | Severity | Pass | Finding | Resolution |
|---|---|---|---|---|
| 1 | Medium | B | B2's integration test depends on API-level cluster creation with `target_filter`, which requires B3's Pydantic schema | Reordered stories to B1 → B3 → B2 (§2, §7, AI Agent Execution Protocol). |
| 2 | High | A | F2 reads `selectedCluster.target_filter` from `useClusters` (returns `ClusterSummary[]`), but the plan only tested `ClusterDetail`. Schema-shape check alone doesn't prove `_summary()` populates the field at runtime | Added `TestListClusters::test_list_clusters_summary_includes_target_filter` to B3 (§3.2). Updated F2 dependency wording to cite `ClusterSummary`, not `ClusterDetail` (§2). |
| 3 | Medium | A | `register_cluster()` uses explicit kwargs (NOT `**fields` as the plan assumed). API + Pydantic would accept the field but the service would silently drop it. Verified at `backend/app/services/cluster.py:83-94` | Added `backend/app/services/cluster.py` and the `create_cluster` router callsite (line 158-176) to B3's Modified files table. New plumb-through task in B3 Tasks list. New DoD assertion: "`register_cluster()` integration test confirms `cluster.target_filter` in the returned `Cluster` ORM row matches the request input." |
| 4 | Low | A | 422 cases didn't explicitly assert the project-standard envelope (`error_code: VALIDATION_ERROR`, `retryable: false`) | All 422 test cases in B3 now assert envelope shape (§3.2). |
| 5 | Low | B | Default Pydantic v2 `@field_validator` runs AFTER `min_length`/`max_length`, so a padded valid filter like `"  " + "x"*256` would fail max_length even though the stripped value is exactly 256 chars | Switched validator to `mode="before"` so strip runs first. Added `test_post_target_filter_padded_strips_to_canonical` to integration suite (§3.2). |

No High findings remain unresolved. **Convergence:** the changes touch the same surfaces already under review (B3's Pydantic + service plumb-through; story sequencing); no new API contract was added. Per impl-plan-gen Step 7 convergence rules, no cycle 2 is required for this scope of corrections — they sharpen the existing plan rather than introducing new contract surface that GPT-5.5 hasn't seen.

### Internal checks

Performed inline during plan generation:

1. **Spec ↔ plan endpoint count.** Spec §7.1 documents 4 endpoint surfaces; all modify existing endpoints (no new endpoints). Plan covers them in B2 (`GET /clusters/{id}/targets`) and B3 (`POST /clusters`, `GET /clusters/{id}`, `GET /clusters`). ✓
2. **Spec ↔ plan error code coverage.** Spec §7.5 introduces no new error codes; uses existing `VALIDATION_ERROR` (422) for FR-2 rejections. Test in B3's contract layer + integration layer. ✓
3. **Spec ↔ plan FR coverage.** All 6 FRs mapped in §1 traceability table; each assigned to exactly one story (FR-6 bundled with FR-2 in B3 — same surface change). ✓
4. **Story internal consistency.** All 5 stories cite real file paths (verified during spec gen + this plan: `backend/app/db/models/cluster.py`, `backend/app/adapters/protocol.py`, `backend/app/adapters/elastic.py`, `backend/tests/integration/fixtures/stub_adapter.py`, `backend/app/api/v1/schemas.py`, `backend/app/api/v1/clusters.py`, `ui/src/components/clusters/register-cluster-modal.tsx`, `ui/src/components/studies/create-study-modal.tsx`). ✓
5. **Test file count + assignment.** §3 lists test changes across 5 files: `test_elastic_schema.py` (B2), `test_clusters_api.py` (B2 + B3 + B1 migration), `test_clusters_api_contract.py` (B3), `register-cluster-modal.test.tsx` (F1), `create-study-modal.test.tsx` (F2). Each is assigned to exactly one story DoD. ✓
6. **Gate arithmetic.** No epic/phase gates beyond per-story DoD; single-PR feature. ✓
7. **Open questions resolved.** Spec §19 says "None — all 4 forks were locked at preflight 2026-05-20." ✓
8. **Frontend UI Guidance.** Plan §"UI Guidance" includes Insertion points, Analogous markup, Interaction behavior table, IA placement, Tooltips, Visual consistency, Component composition, Legacy parity (explicit "no table needed"), Client-side persistence (explicit "none"). ✓
9. **Plan ↔ codebase verification:**
   - Alembic head `0013_search_vector_conversations` confirmed by `ls migrations/versions/ | sort | tail -3`. ✓
   - `Cluster.notes` at line 75-76 verified. ✓
   - `CreateClusterRequest` at schemas.py:50 verified. ✓
   - `ElasticAdapter.list_targets()` at elastic.py:358 verified. ✓
   - `SearchAdapter.list_targets()` at protocol.py:131 verified. ✓
   - `StubAdapter.list_targets()` at stub_adapter.py:57 verified. ✓
   - `list_cluster_targets` router at clusters.py:326 verified. ✓
   - `register-cluster-modal.tsx` Notes block at line 230-231 verified (engine_config + notes precedents at line 82-83). ✓
   - `create-study-modal.tsx` `selectedCluster` derivation at line 144 verified (post-PR #165 state). ✓
10. **Infrastructure paths:** `migrations/versions/` confirmed; next revision `0014` (numeric sequential ≤32 chars). ✓
11. **Frontend data plumbing:** F2 reads `selectedCluster.target_filter` — `selectedCluster` is already derived from `useClusters` at create-study-modal.tsx:144 (post-PR #165 state). The new `target_filter` field will be on `ClusterSummary` after B3 + types regen. ✓
12. **Persistence scope:** All React state via react-hook-form; no `localStorage` / `sessionStorage`. ✓
13. **Enumerated value contract audit:** N/A — `target_filter` is a free-form string, not an enum. No frontend `<select>` whose values flow back to the backend; the input is `<Input>`. ✓
14. **Audit-event coverage:** N/A — MVP1 has no `audit_log`. MVP2+ event type `CLUSTER_TARGET_FILTER_CHANGED` documented in spec §6. ✓

No unresolved findings.

---

## 12) Definition of plan done

- [x] Every FR mapped to a story.
- [x] Every story includes New/Modified files, Endpoints (where applicable), Key interfaces, Tasks, DoD.
- [x] Test layers explicitly scoped per story.
- [x] Documentation updates planned (only `data-model.md` + `adapters.md` updates needed).
- [x] Lean refactor scope explicit ("none planned").
- [x] Per-story DoD; no epic/phase gates needed for single-PR scope.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed with no unresolved findings.
