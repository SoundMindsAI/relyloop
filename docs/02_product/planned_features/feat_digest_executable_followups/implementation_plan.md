# Implementation Plan — Executable Digest Follow-ups

**Date:** 2026-05-23
**Status:** Ready for Execution (GPT-5.5 cross-model review: 1 cycle, 3 accepted / 2 rejected — convergence)
**Primary spec:** [`feature_spec.md`](./feature_spec.md)
**Policy source(s):**
- [`CLAUDE.md`](../../../../CLAUDE.md) (Absolute Rules #1, #5, #8, #10)
- [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md)
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md)
- [`docs/01_architecture/llm-orchestration.md`](../../../01_architecture/llm-orchestration.md)
- Sibling implementations: `feat_auto_followup_studies` (parent-study lineage), `feat_digest_proposal` (digest worker), `feat_create_study_search_space_builder` (search-space row primitive), `chore_study_default_stop_conditions` (form reset patterns)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs.
- Phase gates are hard stops.
- Fail-loud tests: assert explicit status/shape/errors.
- Keep repository patterns consistent with existing digest / studies modules.
- Keep increments narrow enough to verify independently — backend domain → migration → worker → API contract → frontend → E2E.
- **Phase scope:** Phase 1 only (Tier A — `narrow` / `widen` / `text` kinds). Phase 2 (`swap_template`) tracked in [`phase2_idea.md`](./phase2_idea.md); Phase 3 (`edit_template`) tracked in [`phase3_idea.md`](./phase3_idea.md). Both deferred trackers verified present.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 | Epic 2 / Story 2.1 (worker) | LLM JSON-schema change + capability-degraded suppression of drift item. |
| FR-2 | Epic 1 / Story 1.1 (domain) | Backward-compat read-path adapter (legacy `list[str]` wrap to `text` items). |
| FR-3 | Epic 1 / Story 1.1 (domain) | `FollowupItem` + `TypeAdapter` + `serialize_followup_list()` helpers. |
| FR-4 | Epic 1 / Story 1.1 (domain) + Epic 2 / Story 2.1 (worker) | `parse_followup_list()` decision table; downgrade-or-drop with structlog WARN. |
| FR-5 | Epic 3 / Story 3.1 (migration) + Story 3.2 (ORM) | Add `parent_proposal_id` + `parent_proposal_followup_index` + CHECK + partial index + BEFORE DELETE trigger. |
| FR-6 | Epic 3 / Story 3.3 (migration) | JSONB column-type change via PL/pgSQL helper functions. |
| FR-7 | Epic 4 / Story 4.1 (API schemas) | `DigestResponse.suggested_followups` + `_DigestEmbed.suggested_followups` → `list[FollowupItem]`; wrap via `parse_followup_list()` at BOTH response-construction sites. |
| FR-8 | Epic 2 / Story 2.2 (prompts) | `prompts/digest_narrative.system.md` + `.user.jinja` updates teaching three kinds + parent search-space block. |
| FR-9 | Epic 5 / Story 5.1 (UI panel) | `SuggestedFollowupsPanel` rewrite as kind-discriminated cards. |
| FR-10 | Epic 5 / Story 5.2 (UI prefill flow) | "Run this followup" lazy-fetches parent study + opens `CreateStudyModal` with `initialValues`. |
| FR-11 | Epic 4 / Story 4.2 (API endpoint) | `POST /api/v1/studies` accepts optional `parent` body field with three new error codes. |
| FR-12 | Epic 5 / Story 5.1 (UI panel) | Dead `?hypothesis=` button removed in same story as panel rewrite. |
| FR-13 | Epic 5 / Story 5.3 (glossary) | Five new glossary keys for tooltips. |

**Spec endpoint count vs plan:** Spec §8.1 lists 3 modified endpoints. Plan covers all 3:
- `POST /api/v1/studies` — Story 4.2
- `GET /api/v1/studies/{id}/digest` — Story 4.1 (schema change only; existing handler at `backend/app/api/v1/studies.py` digest sub-route untouched apart from wrapper insertion)
- `GET /api/v1/proposals/{id}` — Story 4.1 (`_DigestEmbed` construction wrap)

**Spec error-code coverage vs plan:** Spec §8.5 introduces 3 codes; all covered by Story 4.2 contract tests (`PROPOSAL_NOT_FOUND` / `DIGEST_NOT_FOUND` / `FOLLOWUP_INDEX_OUT_OF_RANGE`).

**Deferred phases verified tracked:**
- `phase2_idea.md` present (Tier B `swap_template`) — `ls` confirmed 2026-05-23.
- `phase3_idea.md` present (Tier C `edit_template`) — `ls` confirmed 2026-05-23.

## 2) Delivery structure

**Hybrid: Epic → Story → Tasks → DoD** (preferred for product-facing work), with Phase 3 (migrations) using **Phase → Checkpoint gate** because migration round-trip is a hard gate independent of story outcomes.

### Story-level conventions for this plan

- **Backend conventions:** repo functions take `db: AsyncSession` first arg, call `db.flush()` (caller commits). Services are `async`. Domain layer is pure (no DB, no async, no I/O). Models use `Mapped[]` typed columns + `String(36)` UUIDv7. Routers raise via the local `_err()` helper (per `backend/app/api/v1/studies.py:75-79`). Settings via `pydantic-settings`; never instantiate `Settings()` directly.
- **Frontend conventions:** Next.js 16 App Router, `'use client'` at top of interactive pages/components, `useStudy(id)` via TanStack Query, shadcn `<Card>` / `<Button>` / `<Dialog>` primitives. All enum wire values import from `ui/src/lib/enums.ts` (no inline `<SelectItem value="...">` for backend wire values — lint guard enforces).
- **No new LLM model hardcodes:** all worker LLM calls continue to read from `Settings.openai_model` (already established by `feat_digest_proposal`). The new `FollowupItem` validation is pure-domain — no LLM API surface to model.

### AI Agent Execution Protocol

0. Load context (architecture.md, state.md, this plan).
1. Read scope (story outcome + endpoints + interfaces + DoD).
2. Implement backend bottom-up: domain → migration → ORM → repo (if any) → service/worker hook → router → schema.
3. Run backend tests (`make test-unit` + targeted integration subset + targeted contract subset for touched endpoints).
4. Implement frontend (if story scope).
5. Run E2E scope for touched UX paths.
6. Update docs in same PR.
7. Verify migration round-trip if schema changed (Story 3.1 + 3.3).
8. Attach evidence in PR description.
9. After final story: update `state.md` + `architecture.md` per §4.

Story completion is invalid if any step is skipped.

---

## Epic 1 — Domain: followup union + parser

### Story 1.1 — `FollowupItem` Pydantic union + `parse_followup_list()` + `serialize_followup_list()`

**Outcome:** A new pure-domain module exposes the discriminated-union `FollowupItem` type alias, two `TypeAdapter`s, a defensive parser that handles every malformed-input shape from FR-4's decision table, and a JSONB-safe serializer. All consumers (worker, API layer) bind to these helpers; no consumer touches raw `dict` payloads directly.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/study/followups.py` | `NarrowFollowup`, `WidenFollowup`, `TextFollowup` Pydantic `BaseModel`s + `FollowupItem` discriminated-union `Annotated` alias + `FollowupItemAdapter` + `FollowupListAdapter` + `parse_followup_list()` + `serialize_followup_list()`. Pure-domain, no I/O. |
| `backend/tests/unit/domain/study/test_followups.py` | Unit tests for the three model variants: round-trip serialization; rejection of unknown `kind`; rejection of `narrow`/`widen` with null `search_space`; rejection of `text` with non-null `search_space`; `extra="forbid"` enforcement. |
| `backend/tests/unit/domain/study/test_followups_backcompat.py` | Unit tests for `parse_followup_list()` covering every row in FR-4's decision table (legacy `list[str]`, valid `list[dict]`, downgrade-on-SearchSpace-fail, downgrade-on-validation-fail-with-salvageable-rationale, drop-on-no-rationale, `text` with malformed extras, unknown `kind`, non-dict array element, non-list top level). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/__init__.py` | Re-export `FollowupItem`, `parse_followup_list`, `serialize_followup_list` if the module currently exports symbols (verify at impl time; current `__init__.py` may be empty per `ls`). |

**Key interfaces**

```python
# backend/app/domain/study/followups.py
from typing import Annotated, Any, Literal, TypeAlias
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from backend.app.domain.study.search_space import SearchSpace


class NarrowFollowup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["narrow"]
    rationale: str
    search_space: SearchSpace


class WidenFollowup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["widen"]
    rationale: str
    search_space: SearchSpace


class TextFollowup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["text"]
    rationale: str
    search_space: None = None


FollowupItem: TypeAlias = Annotated[
    NarrowFollowup | WidenFollowup | TextFollowup,
    Field(discriminator="kind"),
]

FollowupItemAdapter: TypeAdapter[FollowupItem] = TypeAdapter(FollowupItem)
FollowupListAdapter: TypeAdapter[list[FollowupItem]] = TypeAdapter(list[FollowupItem])


def parse_followup_list(
    raw: object,
    *,
    study_id: str | None = None,
    proposal_id: str | None = None,
) -> list[FollowupItem]: ...
"""Per FR-4 decision table. Never raises; downgrades or drops invalid items
with structlog WARN events carrying study_id / proposal_id context."""


def serialize_followup_list(items: list[FollowupItem]) -> list[dict[str, Any]]: ...
"""Calls item.model_dump(mode='json') per item. Required before assigning to
the JSONB column — SQLAlchemy's JSONB driver does not know how to serialize
Pydantic BaseModel instances directly (D-24)."""
```

**Tasks**

1. Create `backend/app/domain/study/followups.py` with the three concrete models + the `Annotated` alias + the two `TypeAdapter` instances.
2. Implement `parse_followup_list()` with explicit branches per FR-4's decision table. Truncate validation error messages to 200 chars before embedding in rationale. Emit `digest_followup_validation_downgraded` (WARN) on each downgrade and `digest_followup_dropped` (WARN) on each drop, both via `structlog.get_logger(__name__)` with `study_id` + `proposal_id` + truncated-item-or-error context.
3. Implement `serialize_followup_list(items)` as `[item.model_dump(mode="json") for item in items]`.
4. Write the two unit test files. The decision-table test must include the empirically-mapped `100^12 > 10^6` cardinality case for the SearchSpace-cardinality-fail downgrade path (cited in AC-4).
5. Verify `mypy --strict` passes on the new module.

**Definition of Done (DoD)**

- `backend/app/domain/study/followups.py` exports `FollowupItem`, `FollowupItemAdapter`, `FollowupListAdapter`, `parse_followup_list`, `serialize_followup_list`.
- `backend/tests/unit/domain/study/test_followups.py` covers per-kind round-trip + rejection paths (unit, no DB).
- `backend/tests/unit/domain/study/test_followups_backcompat.py` covers every row in FR-4's decision table (unit, no DB).
- `mypy --strict` clean.
- All structlog events use canonical field names: `event_type`, `study_id`, `proposal_id`, `original_kind` (downgrade only), `validation_error` (downgrade only), `unparseable_item` (drop only, truncated to 200 chars).

---

## Epic 2 — Worker: structured-output schema + LLM prompts + validator wiring

### Story 2.1 — Worker emits + validates + persists structured followups

**Outcome:** The digest worker emits `suggested_followups` as a JSON array of typed objects via the OpenAI structured-output API; validates each item through `parse_followup_list()`; downgrades invalid `narrow`/`widen` items to `text`; serializes via `serialize_followup_list()` before assigning to the JSONB column; preserves capability-degraded behavior (no LLM followups, no drift synthesis); the drift item synthesized post-LLM in structured mode becomes a `TextFollowup`.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/workers/digest.py` | (1) Replace `DIGEST_RESPONSE_SCHEMA.properties.suggested_followups.items` from `{"type": "string"}` to the structured object schema `{"type": "object", "properties": {"kind": {"enum": ["narrow", "widen", "text"]}, "rationale": {"type": "string"}, "search_space": {"type": ["object", "null"]}}, "required": ["kind", "rationale", "search_space"], "additionalProperties": False}` and keep `maxItems: 5`. (2) Update `_call_openai_for_digest()` parse path to return `list[dict[str, Any]]` (raw) and stop validating field-types at the worker — the parse contract is now "trust the JSON-schema validation; everything downstream goes through `parse_followup_list`". (3) In Step 13 (followup merge, lines 751-775), replace the `list[str]` accumulator with a `list[dict[str, Any]]` accumulator. Build the drift followup as `{"kind": "text", "rationale": <drift message>, "search_space": None}` (was a bare string). Extend with the LLM's parsed list. Then call `parsed_followups = parse_followup_list(combined, study_id=study_id, proposal_id=proposal.id)`. Truncate to first 5 via `parsed_followups[:5]`. (4) In Step 15 (lines 795-807), pass `suggested_followups=serialize_followup_list(parsed_followups)` to `repo.create_digest()`. (5) The `_persist_zero_trials_digest()` path (line 345) still passes `suggested_followups=[]` (empty list — serializer-safe). |
| `backend/app/db/repo/digest.py` (verify exists; otherwise the create_digest helper lives wherever current FR-5 worker imports it) | No signature change — `create_digest(... suggested_followups: list[dict[str, Any]], ...)` accepts the new shape directly because the column type changes (Story 3.3). |

**Key interfaces**

No new public functions. The worker continues to call `parse_followup_list()` and `serialize_followup_list()` from `backend.app.domain.study.followups`.

**Schema change (within `DIGEST_RESPONSE_SCHEMA`)**

```python
DIGEST_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
        "suggested_followups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["narrow", "widen", "text"]},
                    "rationale": {"type": "string"},
                    "search_space": {"type": ["object", "null"]},
                },
                "required": ["kind", "rationale", "search_space"],
                "additionalProperties": False,
            },
            "maxItems": 5,
        },
    },
    "required": ["narrative", "suggested_followups"],
    "additionalProperties": False,
}
```

**Tasks**

1. Edit `DIGEST_RESPONSE_SCHEMA` per the snippet above. The contract test in Story 4.1 will assert the new shape.
2. Edit `_call_openai_for_digest()` at `backend/workers/digest.py:378-426` — keep the existing type/shape check on the top-level dict and `narrative` field but soften the `followups` check to "isinstance(list)" only. Drop the field-level shape check (now enforced by JSON-schema + `parse_followup_list`).
3. In `generate_digest()` Step 13 (worker lines 751-775), refactor the followup-merge loop to build a `list[dict]`, prepend the drift item as a `{"kind": "text", ...}` dict when `structured_output_enabled and dropped`, then `parsed_followups = parse_followup_list(combined, study_id=study_id, proposal_id=proposal.id)` and truncate to `[:5]`.
4. In Step 15 (worker line 805), pass `suggested_followups=serialize_followup_list(parsed_followups)` to `repo.create_digest(...)`.
5. **Confirm capability-degraded path unchanged:** the existing `followups: list[str] = []` at line 757 (already inside `if structured_output_enabled:`) becomes `followups: list[dict[str, Any]] = []` outside the if (initialized empty) and is only mutated when `structured_output_enabled` is true — preserves D-27 (degraded = no LLM followups, no drift synthesis).
6. Update unit / integration tests of the worker (see Story 1.1 + 2.3 / Story 4.1) to reflect the structured shape. Adjust any in-test LLM mock that previously returned `{"narrative": "x", "suggested_followups": ["a"]}` to `{"narrative": "x", "suggested_followups": [{"kind": "text", "rationale": "a", "search_space": None}]}`. Existing tests in `_digest_helpers.py` (the integration fixture, per `ls`) will need parallel updates.
7. Add new structlog field `event_type="digest_followups_persisted"` to the existing `digest_complete` info log including counts per kind: `followups_narrow_count`, `followups_widen_count`, `followups_text_count`.

**Definition of Done (DoD)**

- `DIGEST_RESPONSE_SCHEMA` matches the snippet above; `make test-contract` (Story 4.1) asserts the new shape.
- Worker integration test (Story 2.3) drives the LLM stub through one happy-path `narrow` + one downgrade-from-cardinality case and asserts the persisted JSONB has the expected mixed-kind shape.
- Worker unit test asserts `serialize_followup_list()` is called on the path that writes to the digest row.
- Capability-degraded path persists `suggested_followups=[]`. Existing zero-trials test continues to pass with `suggested_followups=[]`.
- `make lint` + `mypy --strict` clean.

### Story 2.2 — LLM prompt updates teaching three kinds + parent search-space block

**Outcome:** The system prompt teaches the model when to emit each kind; the user prompt template renders the parent study's `search_space` so the LLM can transform it into `narrow`/`widen` proposals.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `prompts/digest_narrative.system.md` | Add a new section "Suggested followups — three kinds" describing `narrow` / `widen` / `text` decision rules per FR-8. Update the structured-path `suggested_followups` description to require objects (not strings). |
| `prompts/digest_narrative.user.jinja` | Add a `<parent_search_space>` block rendering `study.search_space` as a Jinja-formatted JSON object so the LLM can transform it. Placed adjacent to `<top_trials>` / `<parameter_importance>`. |
| `backend/app/llm/digest_prompt.py` | Update `render_digest_user_prompt()` signature to accept a new `parent_search_space: dict[str, Any]` kwarg passed through to the Jinja template. The worker call site at `backend/workers/digest.py:698` adds `parent_search_space=study.search_space` to the kwargs. |

**Key interfaces**

```python
# backend/app/llm/digest_prompt.py — extended signature
def render_digest_user_prompt(
    *,
    study_name: str,
    cluster_name: str,
    target: str,
    query_set_name: str,
    query_count: int,
    judgment_list_name: str,
    rubric_summary: str,
    baseline_metric: float | None,
    achieved_metric: float | None,
    top_trials: list[dict[str, Any]],
    parameter_importance: dict[str, float],
    recommended_config: dict[str, Any],
    dropped_template_params: list[str],
    include_recommendation: bool,
    confidence: dict[str, Any] | None,
    parent_search_space: dict[str, Any],   # NEW (FR-8)
) -> str: ...
```

**Tasks**

1. Edit `prompts/digest_narrative.system.md` to teach the three kinds (narrow when winner sits in a sub-region; widen when winner hits an edge `= low`/`= high`; text for free-form). Update the structured-output JSON shape description to objects.
2. Edit `prompts/digest_narrative.user.jinja` to add a `<parent_search_space>` block (use the existing Jinja `tojson` filter if available, otherwise raw template literal).
3. Extend `render_digest_user_prompt()` to accept and pass `parent_search_space`.
4. Update the worker call at `backend/workers/digest.py:698-714` to pass `parent_search_space=study.search_space`.
5. Add a unit test in `backend/tests/unit/llm/test_digest_prompt.py` (extend existing if present; otherwise create) asserting the `<parent_search_space>` block appears in the rendered output.

**Definition of Done (DoD)**

- `prompts/digest_narrative.system.md` documents the three kinds and the new structured shape.
- `prompts/digest_narrative.user.jinja` renders `<parent_search_space>`.
- `render_digest_user_prompt()` accepts `parent_search_space` kwarg; worker passes `study.search_space`.
- Unit test asserts the new block appears in the rendered prompt.

### Story 2.3 — Integration test: digest worker round-trip with structured followups

**Outcome:** An integration test boots the worker (via the test harness) against a real Postgres + a mocked OpenAI client; the mock returns a structured response with one valid `narrow` + one cardinality-failing `narrow` (downgrades to `text`) + one `text` item; the test asserts the persisted JSONB matches the parse+downgrade contract.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_digest_followup_roundtrip.py` | One integration test driving a full `generate_digest` call through the mocked LLM. Asserts: (a) `digests.suggested_followups` JSONB contains 3 items with the expected kinds; (b) the downgraded item's rationale starts with `"[validation failed: search-space cardinality estimate exceeds 10^6"`; (c) a `digest_followup_validation_downgraded` WARN event was emitted (assert via captured logs). |

**Tasks**

1. Build the test fixture using existing `backend/tests/integration/_digest_helpers.py` helpers — they already set up a study + proposal + capability cache entry. Add a helper variant `seed_digest_worker_state()` if needed; otherwise replicate the existing pattern.
2. Override the OpenAI client mock to return the three-item structured payload (one valid narrow with 2-float `search_space`; one cardinality-busting narrow with 11 floats; one text).
3. Run `generate_digest(ctx, study_id)` directly (the existing pattern in `_digest_helpers.py`).
4. Assert the persisted `digests.suggested_followups` row matches the expected JSONB.
5. Assert the structlog WARN event was emitted using the existing structlog test helper pattern in `_digest_helpers.py` (or `pytest.LogCaptureFixture` if simpler).

**Definition of Done (DoD)**

- Test passes in isolation: `pytest backend/tests/integration/test_digest_followup_roundtrip.py -m integration`.
- Test asserts kind counts + the validation-fail prefix on the downgraded rationale.
- Test asserts the WARN structlog event.

---

## Epic 3 — Migrations + ORM

### Story 3.1 — Migration `0018`: add `parent_proposal_id` + `parent_proposal_followup_index` to `studies` + CHECK + partial index + BEFORE DELETE trigger

**Outcome:** A new Alembic migration adds the two nullable columns, the partial B-tree index, the pair CHECK constraint, and the `BEFORE DELETE ON proposals` trigger that NULLs the lineage pair on parent-proposal hard-delete. Round-trips cleanly.

**Migration directory verification:** `ls /Users/ericstarr/relyloop/migrations/versions/` shows the latest revision is `0017_proposals_last_polled_at.py`. New revision id is `0018`. Migrations live at repo root `migrations/versions/` (NOT `backend/app/db/migrations/`).

**New files**

| File | Purpose |
|---|---|
| `migrations/versions/0018_studies_parent_proposal.py` | Alembic revision adding `parent_proposal_id VARCHAR(36)`, `parent_proposal_followup_index INT`, partial B-tree index, CHECK constraint, BEFORE DELETE trigger + function. |

**Tasks**

1. Create `migrations/versions/0018_studies_parent_proposal.py` with `revision = "0018"`, `down_revision = "0017"`.
2. `upgrade()`:
   - `op.add_column("studies", sa.Column("parent_proposal_id", sa.String(36), sa.ForeignKey("proposals.id"), nullable=True))` — no `ondelete` clause.
   - `op.add_column("studies", sa.Column("parent_proposal_followup_index", sa.Integer(), nullable=True))`.
   - `op.create_index("ix_studies_parent_proposal_id", "studies", ["parent_proposal_id"], postgresql_where=sa.text("parent_proposal_id IS NOT NULL"))`.
   - `op.create_check_constraint("studies_parent_proposal_pair_check", "studies", "(parent_proposal_id IS NULL AND parent_proposal_followup_index IS NULL) OR (parent_proposal_id IS NOT NULL AND parent_proposal_followup_index IS NOT NULL AND parent_proposal_followup_index >= 0)")`.
   - Create the trigger function + trigger via `op.execute(sa.text(...))` using the SQL from spec §9 (`fn_clear_studies_parent_proposal_on_proposal_delete()` + `trg_clear_studies_parent_proposal_on_proposal_delete`).
3. `downgrade()` executes in exactly this order (per GPT-5.5 cycle-1 F1 — make the inverse-order explicit so implementers can't accidentally leak constraints):
   - `op.execute(sa.text("DROP TRIGGER IF EXISTS trg_clear_studies_parent_proposal_on_proposal_delete ON proposals;"))`
   - `op.execute(sa.text("DROP FUNCTION IF EXISTS fn_clear_studies_parent_proposal_on_proposal_delete();"))`
   - `op.drop_constraint("studies_parent_proposal_pair_check", "studies", type_="check")`
   - `op.drop_index("ix_studies_parent_proposal_id", table_name="studies")`
   - `op.drop_column("studies", "parent_proposal_followup_index")`
   - `op.drop_column("studies", "parent_proposal_id")` (Alembic drops the inline FK constraint with the column on Postgres; if the local Postgres version requires an explicit `drop_constraint` for the FK, add it before this line.)
4. Verify round-trip locally with both migrations applied: `.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head` (CLAUDE.md Absolute Rule #5). The round-trip gate explicitly covers BOTH 0018 and 0019 — capture output for both directions in PR evidence.

**Definition of Done (DoD)**

- Migration round-trips locally (capture command output for PR description).
- `0018_studies_parent_proposal.py` includes both upgrade + downgrade.
- New integration tests (Story 3.4, 3.5) pass against the migrated schema.

### Story 3.2 — ORM update: `Study` model adds two new columns

**Outcome:** The `Study` SQLAlchemy ORM model declares the two new nullable columns so the API can read/write them via the ORM.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/models/study.py` | Add `parent_proposal_id: Mapped[str \| None] = mapped_column(String(36), ForeignKey("proposals.id"), nullable=True)` and `parent_proposal_followup_index: Mapped[int \| None] = mapped_column(Integer, nullable=True)` after the existing `parent_study_id` column (line 73). Update the module-level docstring to mention the new lineage columns. |

**Tasks**

1. Edit `backend/app/db/models/study.py` to add the two columns + Integer import.
2. Update the module docstring to note the new columns and that they're set together (CHECK constraint).
3. Run `make typecheck` (mypy --strict on the model module).
4. Run the existing study-CRUD integration tests to confirm no regression.

**Definition of Done (DoD)**

- ORM model declares both columns with correct types and nullability.
- Existing `test_studies_api.py` (or equivalent) still passes — the additive columns shouldn't break any existing test.
- `make typecheck` clean.

### Story 3.3 — Migration `0019`: change `digests.suggested_followups` from `ARRAY(Text)` to `JSONB`

**Outcome:** A new Alembic migration changes the column type in-place using PL/pgSQL helper functions (NOT subquery-in-USING), backfills existing text-array rows to the structured-`text` shape, and ships a symmetric lossy downgrade. Round-trips cleanly.

**Why a separate migration from Story 3.1:** the two changes are orthogonal (one touches `studies`, one touches `digests`); separating keeps each migration small and the downgrade independently testable.

**New files**

| File | Purpose |
|---|---|
| `migrations/versions/0019_digests_suggested_followups_jsonb.py` | Alembic revision changing `digests.suggested_followups` to JSONB via PL/pgSQL helper functions. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/models/digest.py` | Change `suggested_followups: Mapped[list[str]] = mapped_column(ARRAY(Text), ...)` to `suggested_followups: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb"))`. Update the import (drop `ARRAY` + `Text`; the file already imports `JSONB`). Update the docstring. |

**Tasks**

1. Create `migrations/versions/0019_digests_suggested_followups_jsonb.py` with `revision = "0019"`, `down_revision = "0018"`.
2. `upgrade()`: execute the PL/pgSQL helper function SQL from spec FR-6 (`_fn_wrap_text_array_as_jsonb_followups`) — CREATE FUNCTION → ALTER TABLE DROP DEFAULT → ALTER TABLE TYPE jsonb USING helper(suggested_followups) → ALTER TABLE SET DEFAULT '[]'::jsonb → DROP FUNCTION.
3. `downgrade()`: execute the symmetric reverse (`_fn_unwrap_jsonb_followups_as_text_array`) — CREATE FUNCTION → ALTER TABLE DROP DEFAULT → ALTER TABLE TYPE text[] USING helper(suggested_followups) → ALTER TABLE SET DEFAULT ARRAY[]::text[] → DROP FUNCTION. Downgrade is lossy (non-text kinds collapse to their rationale string).
4. Update `backend/app/db/models/digest.py` to the JSONB column declaration.
5. Verify round-trip locally with **two fixture rows**: one with `ARRAY['try widen title_boost', 'add tie_breaker']` and one with `ARRAY[]::TEXT[]` (exercises both helper-function branches). Round-trip command per spec FR-6 + AC-6.

**Definition of Done (DoD)**

- Migration round-trips locally with both populated and empty fixtures (capture command output).
- ORM model declares JSONB column with `'[]'::jsonb` server default.
- The migration body uses PL/pgSQL helper functions (NOT inline subqueries) — verified by inspecting the migration file.
- New integration test (Story 3.6) asserts the JSONB backfill correctness.

### Story 3.4 — Integration test: CHECK constraint blocks half-set lineage + negative index

**Outcome:** Integration test directly INSERTs malformed rows via SQL and asserts the CHECK constraint fires.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_studies_parent_proposal_check.py` | Three test cases: (a) `parent_proposal_id` set + `parent_proposal_followup_index` NULL → IntegrityError; (b) index set + proposal_id NULL → IntegrityError; (c) both set with index = -1 → IntegrityError. |

**Tasks**

1. Seed a fixture proposal + study via existing helpers (`backend/tests/integration/conftest.py` patterns).
2. Use raw `INSERT INTO studies (...)` via `db.execute(text(...))` to bypass the ORM and exercise the CHECK directly.
3. Assert `sqlalchemy.exc.IntegrityError` is raised with the constraint name `studies_parent_proposal_pair_check` in the message.

**Definition of Done (DoD)**

- All three negative-test cases pass against the migrated schema.
- Test marked `@pytest.mark.integration`.

### Story 3.5 — Integration test: BEFORE DELETE trigger detaches lineage atomically

**Outcome:** Integration test creates a parent proposal + a child study with `parent_proposal_id` set; hard-deletes the proposal; asserts the child study row remains with BOTH lineage columns NULL.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_studies_parent_proposal_on_delete.py` | Single test covering AC-11: trigger fires; both columns NULL; child row otherwise unchanged. |

**Tasks**

1. Seed cluster + template + query_set + judgment_list + proposal + child study with `parent_proposal_id = proposal.id`, `parent_proposal_followup_index = 0`.
2. Hard-delete the proposal via `db.execute(delete(Proposal).where(Proposal.id == proposal.id))` + commit.
3. Re-fetch the child study; assert `study.parent_proposal_id is None` AND `study.parent_proposal_followup_index is None`.
4. Assert all other study columns unchanged (compare before/after dict snapshots).

**Definition of Done (DoD)**

- Test passes against the migrated schema.
- Test marked `@pytest.mark.integration`.

### Story 3.6 — Integration test: column-type migration round-trip with populated + empty fixtures

**Outcome:** Integration test drives `alembic upgrade head` against a pre-seeded DB with two fixture rows (one populated text array, one empty); asserts the JSONB backfill correctness on both; then drives `alembic downgrade -1` and asserts the rationale-only text-array round-trip.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_digest_followups_migration.py` | Test the column-type migration's upgrade + downgrade with two fixture row shapes. |

**Tasks**

1. Use the existing test-db fixture (one of `backend/tests/integration/_subprocess_helpers/` or similar — verify at impl time). Pattern: down to revision `0018`, seed two `digests` rows via raw `INSERT INTO digests (suggested_followups, ...) VALUES (ARRAY['try a', 'try b'], ...)` and `ARRAY[]::TEXT[]`. Then `alembic upgrade head` (to 0019).
2. Assert both rows: row 1 has `suggested_followups = [{kind: 'text', rationale: 'try a', search_space: null}, {kind: 'text', rationale: 'try b', search_space: null}]`; row 2 has `suggested_followups = []`.
3. `alembic downgrade -1`. Assert row 1 has `suggested_followups = ['try a', 'try b']` (text array); row 2 has `suggested_followups = []`.
4. Re-upgrade to head; assert row 1's JSONB shape restored.

**Definition of Done (DoD)**

- Test passes against the migrated schema.
- Both populated + empty branches of the PL/pgSQL helpers are exercised (per FR-6 round-trip requirement).
- Test marked `@pytest.mark.integration`.

---

## Epic 4 — API schemas + endpoint

### Story 4.1 — `DigestResponse` + `_DigestEmbed` schemas: `suggested_followups` → `list[FollowupItem]` + wrap-at-response-construction

**Outcome:** Both response schemas declare the new structured shape; both response-construction sites call `parse_followup_list()` so the wire always matches the contract regardless of what's in the JSONB column.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/contract/test_digest_response_shape.py` | Contract test asserting `DigestResponse.suggested_followups` is `list[FollowupItem]` (discriminated union); each kind round-trips through OpenAPI; the new `DIGEST_RESPONSE_SCHEMA` worker JSON-schema matches the spec snippet from FR-1. |
| `backend/tests/contract/test_proposal_detail_shape.py` | Contract test asserting `_DigestEmbed.suggested_followups` is `list[FollowupItem]` on `GET /api/v1/proposals/{id}`. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` | (1) Add a re-export of `FollowupItem` from `backend.app.domain.study.followups`. (2) Line 949: change `suggested_followups: list[str]` to `suggested_followups: list[FollowupItem]` on `DigestResponse`. (3) Line 1006: same change on `_DigestEmbed`. |
| `backend/app/api/v1/proposals.py` | Line 161: change `suggested_followups=digest.suggested_followups` to `suggested_followups=parse_followup_list(digest.suggested_followups, study_id=digest.study_id, proposal_id=proposal.id)`. Import `parse_followup_list` from `backend.app.domain.study.followups`. |
| `backend/app/api/v1/studies.py` (or wherever the `GET /api/v1/studies/{id}/digest` handler lives — verify at impl time; the spec §2 indicates it's under proposals at the new digest endpoint; **actual handler location:** `grep -rn "studies/{study_id}/digest" backend/app/api/v1/` finds the route — read and modify accordingly) | At the `DigestResponse` construction site: wrap `digest.suggested_followups` via `parse_followup_list(...)`. Import path same as above. |

**Endpoints (modified)**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/studies/{study_id}/digest` | — | `200` `DigestResponse` (now with `suggested_followups: list[FollowupItem]`) | `DIGEST_NOT_READY` (404, unchanged) |
| `GET` | `/api/v1/proposals/{proposal_id}` | — | `200` `ProposalDetail` with inline `_DigestEmbed.suggested_followups: list[FollowupItem]` | `PROPOSAL_NOT_FOUND` (404, unchanged) |

**Pydantic schemas**

```python
# Re-exported alias
from backend.app.domain.study.followups import FollowupItem


class DigestResponse(BaseModel):
    id: str
    study_id: str
    narrative: str
    parameter_importance: dict[str, float]
    recommended_config: dict[str, Any]
    suggested_followups: list[FollowupItem]   # was list[str]
    generated_by: str
    generated_at: datetime


class _DigestEmbed(BaseModel):
    id: str
    narrative: str
    parameter_importance: dict[str, float]
    recommended_config: dict[str, Any]
    suggested_followups: list[FollowupItem]   # was list[str]
    generated_at: datetime
```

**Tasks**

1. Add `FollowupItem` re-export at the top of `backend/app/api/v1/schemas.py`.
2. Update both `DigestResponse` + `_DigestEmbed` to use `list[FollowupItem]`.
3. Edit `backend/app/api/v1/proposals.py:161` to wrap via `parse_followup_list(...)`.
4. Locate the `GET /studies/{id}/digest` handler (likely in `backend/app/api/v1/studies.py` or `proposals.py` — verify at impl time) and wrap there too.
5. Write `test_digest_response_shape.py` asserting: (a) the OpenAPI schema for `DigestResponse.suggested_followups` is the discriminated union; (b) constructing `DigestResponse(... suggested_followups=[NarrowFollowup(...)])` round-trips through `.model_dump_json()`.
6. Write `test_proposal_detail_shape.py` asserting the same for `_DigestEmbed`.
7. Add a defensive legacy-row test case: seed a `digests` row whose raw `suggested_followups` JSONB is `["a", "b"]` (array of strings, defensive shape per AC-5); call `GET /api/v1/studies/{study_id}/digest`; assert the response wraps both into `text` items. This guarantees the wrapper-at-response-construction works.

**Definition of Done (DoD)**

- Both schemas use `list[FollowupItem]`.
- Both response-construction sites wrap via `parse_followup_list()`.
- Contract tests pass.
- AC-5 defensive legacy-row test case included and passing.

### Story 4.2 — `POST /api/v1/studies` accepts optional `parent` body field

**Outcome:** The endpoint validates the new `parent` field's references atomically with the existing validation chain; persists the lineage pair on the new study row; raises three new error codes with the canonical envelope; the existing endpoint surface is preserved when `parent` is omitted.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/contract/test_create_study_parent.py` | Contract test: (a) `CreateStudyRequest.parent` is optional in OpenAPI; (b) all three new error codes appear in the route's error response schema; (c) success responds 201. |
| `backend/tests/integration/test_studies_with_parent_followup.py` | Integration test covering: (a) happy path — `POST /studies` with valid `parent` persists `parent_proposal_id` + `parent_proposal_followup_index`; (b) unknown `parent.proposal_id` → 404 `PROPOSAL_NOT_FOUND`; (c) existing proposal without digest → 404 `DIGEST_NOT_FOUND`; (d) stale `followup_index` (>= parsed list length) → 422 `FOLLOWUP_INDEX_OUT_OF_RANGE`. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` | Add `class ParentFollowupRef(BaseModel)` with `proposal_id: str = Field(min_length=36, max_length=36)` + `followup_index: int = Field(ge=0)`. Add `parent: ParentFollowupRef \| None = None` to `CreateStudyRequest` (line 613). |
| `backend/app/api/v1/studies.py` | (1) Import `ParentFollowupRef` (auto-imported with `CreateStudyRequest`). (2) In `create_study()` (line 194): after the existing FK/preflight chain (after line 319) and BEFORE the `repo.create_study(...)` call (line 325), add the parent-validation block — see Endpoints section below. (3) Pass `parent_proposal_id=body.parent.proposal_id if body.parent else None` and `parent_proposal_followup_index=body.parent.followup_index if body.parent else None` to `repo.create_study(...)`. |
| `backend/app/db/repo/study.py` | `create_study(**fields)` already takes `**fields` (line 47) — no signature change needed; the two new columns flow through as kwargs. |

**Endpoints (modified)**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/studies` | `CreateStudyRequest` + optional `parent: {proposal_id: str(36), followup_index: int >= 0}` | `201` `StudyDetail` | `INVALID_SEARCH_SPACE` (400, pre-existing), `CLUSTER_NOT_FOUND` (404, pre-existing), `TEMPLATE_NOT_FOUND` (404, pre-existing), `QUERY_SET_NOT_FOUND` (404, pre-existing), `JUDGMENT_LIST_NOT_FOUND` (404, pre-existing), `JUDGMENT_CLUSTER_MISMATCH` (422, pre-existing), `JUDGMENT_TARGET_MISMATCH` (422, pre-existing), `INSUFFICIENT_JUDGMENT_OVERLAP` (422, pre-existing), `SEARCH_SPACE_UNKNOWN_PARAM` (400, pre-existing), `SEARCH_SPACE_MISSING_DECLARED_PARAM` (400, pre-existing), `VALIDATION_ERROR` (422, pre-existing), **`PROPOSAL_NOT_FOUND` (404, new — `retryable: false`)**, **`DIGEST_NOT_FOUND` (404, new — `retryable: true`)**, **`FOLLOWUP_INDEX_OUT_OF_RANGE` (422, new — `retryable: false`)** |

All errors use the canonical envelope per `_err()` helper at `backend/app/api/v1/studies.py:75-79`. No auth dependency (single-tenant MVP1).

**Pydantic schemas**

```python
class ParentFollowupRef(BaseModel):
    """Optional lineage payload on POST /api/v1/studies (FR-11)."""
    proposal_id: str = Field(min_length=36, max_length=36)
    followup_index: int = Field(ge=0)


class CreateStudyRequest(BaseModel):
    # ... existing fields unchanged ...
    parent: ParentFollowupRef | None = None
```

**Key interfaces (router insertion)**

```python
# In create_study() after the overlap probe (after line 319) and before
# repo.create_study() (line 325):
parent_proposal_id: str | None = None
parent_followup_index: int | None = None
if body.parent is not None:
    proposal = await repo.get_proposal(db, body.parent.proposal_id)
    if proposal is None:
        raise _err(
            404,
            "PROPOSAL_NOT_FOUND",
            f"proposal {body.parent.proposal_id} not found",
            False,
        )
    digest = await repo.get_digest_for_study(db, proposal.study_id)
    if digest is None:
        raise _err(
            404,
            "DIGEST_NOT_FOUND",
            f"proposal {body.parent.proposal_id} has no digest yet",
            True,  # retryable — operator can wait for the digest worker
        )
    parsed_followups = parse_followup_list(
        digest.suggested_followups,
        study_id=digest.study_id,
        proposal_id=proposal.id,
    )
    if body.parent.followup_index >= len(parsed_followups):
        raise _err(
            422,
            "FOLLOWUP_INDEX_OUT_OF_RANGE",
            (
                f"parent.followup_index={body.parent.followup_index} exceeds the "
                f"digest's suggested_followups length ({len(parsed_followups)}) "
                f"for proposal {proposal.id}"
            ),
            False,
        )
    parent_proposal_id = body.parent.proposal_id
    parent_followup_index = body.parent.followup_index

# ... then pass parent_proposal_id + parent_proposal_followup_index to
# repo.create_study(...) on line 326.
```

**Tasks**

1. Add `ParentFollowupRef` to `backend/app/api/v1/schemas.py` and extend `CreateStudyRequest` with the optional `parent` field.
2. Edit `backend/app/api/v1/studies.py:create_study()` to insert the parent-validation block (per snippet above) between the overlap probe and `repo.create_study(...)`. Pass the two lineage values through to the repo call.
2b. **Malformed `parent` body envelope (per GPT-5.5 cycle-1 F3):** confirm FastAPI's existing `RequestValidationError` handler at `backend/app/api/errors.py` (already wired by `infra_foundation`) maps malformed body shapes to the canonical envelope `{"detail": {"error_code": "VALIDATION_ERROR", "message": ..., "retryable": false}}` with HTTP 422. No new handler needed — this is the same envelope FastAPI returns today for any malformed `CreateStudyRequest` field. Add explicit contract test cases per task 4b below.
3. Verify `repo.get_proposal` exists in `backend/app/db/repo/proposal.py`; if not, add it as `async def get_proposal(db: AsyncSession, proposal_id: str) -> Proposal | None`.
4. Write `test_create_study_parent.py` (contract): assert OpenAPI shape + presence of the three new error codes in the route's `responses` mapping.
4b. **Malformed-parent-payload contract tests (per GPT-5.5 cycle-1 F3):** add three test cases asserting the canonical 422 `VALIDATION_ERROR` envelope: (a) `parent: {proposal_id: "short", followup_index: 0}` (proposal_id < 36 chars); (b) `parent: {proposal_id: "<valid-36-char-uuid>", followup_index: -1}` (negative index); (c) `parent: {proposal_id: 123, followup_index: 0}` (proposal_id non-string). Each asserts response body `detail.error_code == "VALIDATION_ERROR"` AND `detail.retryable == false`.
5. Write `test_studies_with_parent_followup.py` (integration): cover all four paths above. Each error case asserts `error_code`, `retryable`, and HTTP status per the canonical envelope.
6. Update `_detail()` (line 120) — no change needed; `parent_proposal_id` is NOT exposed on `StudyDetail` per D-5.

**Definition of Done (DoD)**

- `CreateStudyRequest.parent` field optional, validated.
- Three new error codes raised on the appropriate failure paths with the canonical envelope.
- Integration test covers happy path + all three error paths.
- Contract test asserts the OpenAPI surface.
- Persisted study row has both lineage columns set after happy-path POST.

---

## Epic 5 — Frontend: panel rewrite + prefill flow + glossary

### Story 5.1 — Rewrite `SuggestedFollowupsPanel` as kind-discriminated cards + remove dead `?hypothesis=` link

**Outcome:** The panel renders each followup as a card whose markup branches on `kind`. `narrow`/`widen` cards render a rationale + collapsible search-space detail + primary "Run this followup" button. `text` cards render the rationale as bullet text with no button. The dead `?hypothesis=` link is gone (FR-12).

**Reference: current component structure**

- **File:** `ui/src/components/proposals/suggested-followups-panel.tsx`
- **Current line count:** 42 (full file).
- **Current sections:** single `<Card>` wrapping a `<ul data-testid="suggested-followups-list">` mapping `followups: readonly string[]` to bullet rows with a `<Link href={/studies?hypothesis=...}>` button per row.
- **Current props:** `{ followups: readonly string[] }`.
- **Insertion point:** entire file body is replaced. The export name + container `data-testid` are preserved.

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/components/proposals/suggested-followups-panel.test.tsx` | Vitest component test asserting: (a) `narrow` card renders badge "Narrow" + Run button; (b) `widen` card renders badge "Widen" + Run button; (c) `text` card renders badge "Suggestion" + no Run button; (d) no `<a>` / `<Link>` with `href` matching `/studies?hypothesis=`; (e) per-item data-testids (`followup-${i}-card`, `followup-${i}-run`, `followup-${i}-show-search-space`); (f) clicking Run fires the `onRun(followupIndex)` prop callback. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/proposals/suggested-followups-panel.tsx` | Full rewrite per "Component composition" + "Analogous markup patterns" below. New props: `{ followups: readonly FollowupItem[], onRun: (index: number) => void, parentSearchSpace?: Record<string, unknown> }`. Remove `Link` import; keep `Button`, `Card`, `CardContent`, `CardHeader`, `CardTitle`, `InfoTooltip`. Add `Badge` (shadcn) + `Collapsible` (shadcn — already in repo per spec §13). |
| `ui/src/app/proposals/[id]/page.tsx` (line 194-197) | Pass the new `onRun` prop (lifted to the page component). The parent study's `search_space` is fetched eagerly on this page when at least one followup is `narrow` or `widen` (see Story 5.2 lazy-fetch — extended per GPT-5.5 cycle-1 F2: enable `useStudy(parent_study_id)` whenever the proposal has actionable followups, not only on Run click, so the diff renders when the operator expands "Show search space" without first clicking Run). The query is cached; the Run flow reuses it. Pass `parentSearchSpace={parentStudy.data?.search_space ?? undefined}` and `parentStudyLoading={parentStudy.isLoading}` and `parentStudyError={parentStudy.error ?? null}` to the panel. The panel renders an inline "Loading parent search space..." string while pending and a muted "Could not load parent — showing proposed bounds only" line on error; the proposed `search_space` always renders unconditionally. |
| `ui/src/types/followups.ts` (NEW small file or inline in `ui/src/lib/api/proposals.ts`) | Add the `FollowupKind` TypeScript discriminator type from generated OpenAPI types: `type FollowupKind = 'narrow' \| 'widen' \| 'text'` with source-of-truth comment `// Values must match backend/app/domain/study/followups.py FollowupItem.kind`. Mirror by adding to `ui/src/lib/enums.ts` per CLAUDE.md "Enumerated Value Contract Discipline." |

**Enumerated value contract verification (per CLAUDE.md):**

| Source | Wire values |
|---|---|
| Backend (`backend/app/domain/study/followups.py`) — `Literal["narrow", "widen", "text"]` discriminator | `narrow`, `widen`, `text` |
| Spec §8.4 enumerated value contracts | `narrow`, `widen`, `text` |
| Frontend (`ui/src/lib/enums.ts` new `FOLLOWUP_KIND_VALUES`) | `narrow`, `widen`, `text` |

Match: character-for-character. The frontend NEVER exposes `kind` as an option in any `<select>` — the LLM is the producer (per spec D-12). The values appear only in JSX kind-branch logic and `data-testid` patterns.

**UI element inventory (created)**

| Element | Label/text | Data source | Interactions |
|---|---|---|---|
| `<Card>` panel container | header "Suggested follow-ups" + `InfoTooltip glossaryKey="proposal.suggested_followups"` | always | none |
| `<ul data-testid="suggested-followups-list">` | (container) | `followups` prop | (container) |
| Per-item `<li data-testid="followup-${i}-card">` card | rationale text | `followup.rationale` | (container) |
| Per-item kind badge | "Narrow" / "Widen" / "Suggestion" with `aria-label` matching text + `InfoTooltip glossaryKey="proposal.followup_kind_${kind}"` | `followup.kind` | hover → tooltip |
| Per-item "Show search space" `<Collapsible>` toggle (narrow/widen ONLY) | "Show search space" / "Hide search space" + `InfoTooltip glossaryKey="proposal.followup_search_space_diff"` | `followup.search_space` | click → toggle |
| Per-item "Run this followup" `<Button>` (narrow/widen ONLY) | "Run this followup" + `InfoTooltip glossaryKey="proposal.followup_run_button"` | always | click → `onRun(index)` callback (caller opens modal in Story 5.2) |

**Analogous markup patterns**

```tsx
{/* Card container — current panel structure preserved */}
<Card>
  <CardHeader>
    <CardTitle className="flex items-center gap-1 text-base">
      Suggested follow-ups
      <InfoTooltip glossaryKey="proposal.suggested_followups" />
    </CardTitle>
  </CardHeader>
  <CardContent>
    <ul className="space-y-3" data-testid="suggested-followups-list">
      {followups.map((f, i) => (
        <li
          key={`followup-${i}`}
          data-testid={`followup-${i}-card`}
          className="rounded-md border p-3 space-y-2"
        >
          <div className="flex items-center gap-2">
            <Badge
              variant="outline"
              aria-label={KIND_LABELS[f.kind]}
            >
              {KIND_LABELS[f.kind]}
            </Badge>
            <InfoTooltip glossaryKey={`proposal.followup_kind_${f.kind}` as const} />
          </div>
          <p className="text-sm">{f.rationale}</p>
          {(f.kind === 'narrow' || f.kind === 'widen') && (
            <>
              <Collapsible>
                <CollapsibleTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    data-testid={`followup-${i}-show-search-space`}
                  >
                    Show search space
                    <InfoTooltip glossaryKey="proposal.followup_search_space_diff" />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  {/* Diff vs parent if parentSearchSpace provided; otherwise raw JSON */}
                  <pre className="text-xs bg-muted p-2 rounded overflow-x-auto">
                    {JSON.stringify(f.search_space, null, 2)}
                  </pre>
                </CollapsibleContent>
              </Collapsible>
              <div className="flex justify-end">
                <Button
                  type="button"
                  variant="default"
                  size="sm"
                  data-testid={`followup-${i}-run`}
                  onClick={() => onRun(i)}
                  aria-label="Run this followup — opens the create study form pre-filled with these settings"
                >
                  Run this followup
                  <InfoTooltip glossaryKey="proposal.followup_run_button" />
                </Button>
              </div>
            </>
          )}
        </li>
      ))}
    </ul>
  </CardContent>
</Card>
```

```tsx
{/* KIND_LABELS constant — module-level */}
const KIND_LABELS: Record<FollowupKind, string> = {
  narrow: 'Narrow',
  widen: 'Widen',
  text: 'Suggestion',
};
```

**Layout and structure**

- Container `<Card>` unchanged from current layout.
- Each card uses `border + p-3 + space-y-2` (matches the existing `Card` muted-border style on the proposal-detail page — e.g., `ui/src/components/proposals/pr-panel.tsx` patterns).
- Cards stack vertically with `space-y-3` (preserves current spacing).
- Responsive: no special handling needed (text + small buttons fit any width ≥ 320px).

**Modal pattern**

This story does NOT open the modal — the parent page (Story 5.2) handles that via the `onRun(index)` callback. No `<Dialog>` markup in this component.

**Visual consistency table**

| New element | CSS class | Pattern source |
|---|---|---|
| Card border + padding | `rounded-md border p-3` | `ui/src/components/proposals/pr-panel.tsx` (existing border-card style) |
| Vertical stack inside card | `space-y-2` | shadcn convention |
| Kind badge | shadcn `<Badge variant="outline">` | `ui/src/components/common/status-badge.tsx` |
| Collapsible | shadcn `<Collapsible>` / `<CollapsibleTrigger>` / `<CollapsibleContent>` | shadcn primitive (verified at impl time — alternative is `<details>`/`<summary>` per spec §13) |
| Run button | shadcn `<Button variant="default" size="sm">` | existing primary-button pattern |
| Show search space toggle | shadcn `<Button variant="ghost" size="sm">` | existing tertiary-button pattern |
| Pre-formatted JSON | `text-xs bg-muted p-2 rounded overflow-x-auto` | matches the existing search-space JSON viewer in `ui/src/components/studies/search-space-builder/` |

**Component composition**

- Inline (not extracted): the panel is small enough (~80 LOC after rewrite) that extracting per-kind sub-components adds more imports than it saves. Single file.
- Props: `{ followups, onRun, parentSearchSpace? }`. No internal state.

**Interaction behavior table**

| User action | Frontend behavior | API call |
|---|---|---|
| Click "Show search space" | Toggle `<Collapsible>` open/close | None |
| Click "Run this followup" | Call `onRun(index)` callback prop | None (Story 5.2 handles the modal open + fetch) |
| Hover any `InfoTooltip` icon | Show tooltip with glossary content | None |
| (text-kind item) | Render rationale as bullet text; no interactions | None |

**Information architecture placement**

The panel lives on `/proposals/[id]` inside the existing detail page below the `PrPanel`. No nav-bar / sidebar changes. The Run-followup flow opens the `CreateStudyModal` overlay (no navigation away from the page). Discoverability: operators on `/proposals/[id]` see the panel inline below the proposal status — same as today's bullet rendering.

**Tooltips and contextual help**

| Element | Tooltip text | Glossary key | Trigger | Placement | Source-of-truth comment |
|---|---|---|---|---|---|
| `Narrow` badge | "The study's winning configuration sits in a sub-region of the prior search space. This followup re-runs with a tighter range to confirm." | `proposal.followup_kind_narrow` (new) | hover | top | `// Source-of-truth: backend/app/domain/study/followups.py NarrowFollowup` |
| `Widen` badge | "The winning configuration hit an edge of the prior search space. This followup re-runs with a broader range to find a possibly-better setting." | `proposal.followup_kind_widen` (new) | hover | top | `// Source-of-truth: backend/app/domain/study/followups.py WidenFollowup` |
| `Suggestion` badge | "A free-form suggestion from the LLM. Needs operator interpretation — no auto-prefill available." | `proposal.followup_kind_text` (new) | hover | top | `// Source-of-truth: backend/app/domain/study/followups.py TextFollowup` |
| "Run this followup" button | "Opens the create-study wizard pre-filled with this followup's settings. You can review and edit before submitting." | `proposal.followup_run_button` (new) | hover | top | (UI-only) |
| "Show search space" toggle | "Compare this followup's proposed search space against the parent study's." | `proposal.followup_search_space_diff` (new) | hover | top | (UI-only) |
| Panel title `Suggested follow-ups` (preserved) | (existing copy) | `proposal.suggested_followups` (existing — unchanged) | hover | top | (UI-only) |

Tooltips use the existing `<InfoTooltip glossaryKey="...">` primitive (`ui/src/components/common/info-tooltip.tsx:37`). The new glossary keys are added in Story 5.3.

**Legacy behavior parity** (component is 42 LOC < 100 — legacy parity table NOT strictly required by the rubric, but kept for completeness since FR-12 explicitly retires the `?hypothesis=` link)

| # | Legacy behavior | Location in deleted component | Verdict | Preservation site / rationale |
|---|---|---|---|---|
| 1 | Panel hides when `followups.length === 0` | `suggested-followups-panel.tsx:13` | Preserved | Same `if (followups.length === 0) return null` guard in the rewritten file. |
| 2 | Container `data-testid="suggested-followups-list"` on `<ul>` | `suggested-followups-panel.tsx:23` | Preserved | Kept on the new `<ul>` for E2E continuity. |
| 3 | Per-item `data-testid="followup-${i}-create-study"` on link | `suggested-followups-panel.tsx:30` | Intentionally dropped | Spec FR-12 (D-12 + idea brief): the legacy `?hypothesis=` link is dead today and the new per-kind `data-testid` values supersede it. New testids: `followup-${i}-run`, `followup-${i}-card`, `followup-${i}-show-search-space`. |
| 4 | `<Link href={/studies?hypothesis=...}>` "Create study from this hypothesis" button | `suggested-followups-panel.tsx:28-33` | Intentionally dropped | FR-12 + spec §3 anti-patterns: the link is dead (target `/studies` never reads `?hypothesis=`); operators should use the new in-place modal flow. No redirect/fallback per CLAUDE.md `feedback_no_legacy_preservation`. |
| 5 | `InfoTooltip glossaryKey="proposal.suggested_followups"` on panel title | `suggested-followups-panel.tsx:19` | Preserved | Identical line kept in the rewritten header. |
| 6 | `flex-1 text-sm` on rationale span | `suggested-followups-panel.tsx:26` | Preserved (adapted) | Rationale text now rendered as `<p className="text-sm">` inside the card — same visual size, different containing element. |

**Tasks**

1. Add `FOLLOWUP_KIND_VALUES` to `ui/src/lib/enums.ts` with the source-of-truth comment (per CLAUDE.md discipline). Export `FollowupKind` type.
2. Rewrite `ui/src/components/proposals/suggested-followups-panel.tsx` per the Analogous markup patterns above. Drop `Link` import. Add `Badge`, `Collapsible`, `CollapsibleTrigger`, `CollapsibleContent` imports (verify shadcn `<Collapsible>` exists in `ui/src/components/ui/`; if not, fall back to `<details>`/`<summary>` per spec §13).
3. Update the props type. Generated TypeScript types (from OpenAPI) will produce `FollowupItem` via `components['schemas']['FollowupItem']` once Story 4.1 ships — import from `@/lib/types`.
4. Write the vitest test file. Assert all six rows in the legacy-parity table above (every "Preserved" row needs a test).
5. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test`.

**Definition of Done (DoD)**

- Component renders three kinds correctly (vitest covers all three).
- No `<a>` or `<Link>` with `href` matching `/studies?hypothesis=` exists in the new file (lint snapshot guard via vitest assertion — AC-10).
- All per-item `data-testid` values present (`followup-${i}-card`, `followup-${i}-run`, `followup-${i}-show-search-space`).
- Container `data-testid="suggested-followups-list"` preserved.
- `cd ui && pnpm lint && pnpm typecheck && pnpm test` clean.

### Story 5.2 — "Run this followup" pre-fills the create-study modal via lazy parent-study fetch

**Outcome:** Clicking "Run this followup" on the panel triggers a lazy `useStudy(parent_study_id)` fetch via TanStack Query; when it resolves, the `CreateStudyModal` opens with `initialValues` derived from the parent study + the LLM's proposed `search_space`; submitting POSTs to `/api/v1/studies` with the `parent` lineage payload; on success, the operator is navigated to the new study's detail page.

**Reference: current component structure**

- **File:** `ui/src/components/studies/create-study-modal.tsx`
- **Current line count:** ~1157 (per Bash output earlier).
- **Current props:** `{ open, onOpenChange }` (line 159-162).
- **Modal-open reset effect:** `useEffect(() => { if (open) { setManualMode(false); } }, [open]);` (line 247-251).
- **`useForm` default values:** lines 168-185.

**New files**

None — all changes are in existing files.

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/create-study-modal.tsx` | (1) Extend `CreateStudyModalProps` (line 159) with optional `initialValues?: PrefillValues` field. (2) Define `PrefillValues` type carrying parent-study-derived form-field values + lineage. (3) Add a `useEffect` keyed on `[open, initialValues]` that calls `form.reset(derivedInitialValues)` when both are truthy — adjacent to the existing modal-open reset effect (line 247). (4) Extend the submit handler to attach `parent: { proposal_id, followup_index }` to the `CreateStudyRequest` body when `initialValues?.parent` is set. |
| `ui/src/app/proposals/[id]/page.tsx` | (1) Add state `runFollowupIndex: number \| null` defaulting to `null`. (2) Lazy-call `useStudy(proposal.study_id, { enabled: runFollowupIndex !== null })`. (3) When the study fetch resolves AND `runFollowupIndex !== null`, build `prefillValues` from the parent study + `proposal.digest.suggested_followups[runFollowupIndex]` and open the `CreateStudyModal` with `initialValues={prefillValues}` + `open={true}`. (4) Pass `onRun={setRunFollowupIndex}` to `<SuggestedFollowupsPanel>`. (5) On modal close, clear `runFollowupIndex`. |
| `ui/src/lib/api/studies.ts` | No change — `useStudy(id)` already exists at line 60 and accepts a per-call `options` arg; we'll add an `enabled` option pass-through if not already supported. Verify at impl time. |

**Key types**

```tsx
// In create-study-modal.tsx (or a co-located helper file)
export interface PrefillValues {
  // Form-field values derived from the parent study
  cluster_id: string;
  target: string;
  template_id: string;
  query_set_id: string;
  judgment_list_id: string;
  name: string;        // default: "<parent name> — followup #<index+1> (<kind>)"
  search_space_text: string;  // JSON.stringify(followup.search_space, null, 2)
  metric: ObjectiveMetric;
  k?: ObjectiveK;
  direction: ObjectiveDirection;
  max_trials?: number | '';
  time_budget_min?: number | '';
  parallelism?: number | '';
  trial_timeout_s?: number | '';
  sampler?: SamplerKind;
  pruner?: PrunerKind;
  seed?: number | '';
  // Lineage (sent in POST body, never displayed)
  parent: {
    proposal_id: string;
    followup_index: number;
  };
}
```

**Handler patterns**

```tsx
// Inside CreateStudyModal — adjacent to the line-247 reset effect
useEffect(() => {
  if (open && initialValues) {
    form.reset({
      cluster_id: initialValues.cluster_id,
      target: initialValues.target,
      template_id: initialValues.template_id,
      query_set_id: initialValues.query_set_id,
      judgment_list_id: initialValues.judgment_list_id,
      name: initialValues.name,
      search_space_text: initialValues.search_space_text,
      metric: initialValues.metric,
      k: initialValues.k,
      direction: initialValues.direction,
      max_trials: initialValues.max_trials,
      time_budget_min: initialValues.time_budget_min,
      parallelism: initialValues.parallelism,
      trial_timeout_s: initialValues.trial_timeout_s,
      sampler: initialValues.sampler,
      pruner: initialValues.pruner,
      seed: initialValues.seed,
    });
  }
}, [open, initialValues, form]);

// In the submit handler — extend the existing POST body
const onSubmit: SubmitHandler<FormValues> = async (values) => {
  // ... existing validation + body assembly ...
  const body: CreateStudyRequest = {
    // ... existing fields ...
    ...(initialValues?.parent
      ? { parent: { proposal_id: initialValues.parent.proposal_id, followup_index: initialValues.parent.followup_index } }
      : {}),
  };
  await create.mutateAsync(body);
};
```

```tsx
// Inside proposals/[id]/page.tsx — orchestration
// Per GPT-5.5 cycle-1 F2: enable the parent-study fetch whenever the proposal
// has at least one actionable followup (narrow/widen), not only on Run click,
// so the panel's "Show search space" detail can render a diff vs parent
// before the operator clicks Run. The same cached query feeds the Run flow.
const [runFollowupIndex, setRunFollowupIndex] = useState<number | null>(null);
const parentStudyId = proposal.study_id;
const hasActionableFollowup = (proposal.digest?.suggested_followups ?? []).some(
  (f) => f.kind === 'narrow' || f.kind === 'widen',
);
const parentStudy = useStudy(parentStudyId ?? '', {
  enabled: parentStudyId !== null && hasActionableFollowup,
});

const prefillValues: PrefillValues | undefined = useMemo(() => {
  if (
    runFollowupIndex === null ||
    !parentStudy.data ||
    !proposal.digest?.suggested_followups
  ) {
    return undefined;
  }
  const f = proposal.digest.suggested_followups[runFollowupIndex];
  if (!f || (f.kind !== 'narrow' && f.kind !== 'widen')) return undefined;
  const s = parentStudy.data;
  return {
    cluster_id: s.cluster_id,
    target: s.target,
    template_id: s.template_id,
    query_set_id: s.query_set_id,
    judgment_list_id: s.judgment_list_id,
    name: `${s.name} — followup #${runFollowupIndex + 1} (${f.kind})`,
    search_space_text: JSON.stringify(f.search_space, null, 2),
    metric: s.objective.metric as ObjectiveMetric,
    k: s.objective.k as ObjectiveK | undefined,
    direction: s.objective.direction as ObjectiveDirection,
    max_trials: s.config.max_trials ?? '',
    time_budget_min: s.config.time_budget_min ?? '',
    parallelism: s.config.parallelism ?? '',
    trial_timeout_s: s.config.trial_timeout_s ?? '',
    sampler: (s.config.sampler ?? 'tpe') as SamplerKind,
    pruner: (s.config.pruner ?? 'median') as PrunerKind,
    seed: s.config.seed ?? '',
    parent: { proposal_id: proposal.id, followup_index: runFollowupIndex },
  };
}, [runFollowupIndex, parentStudy.data, proposal]);

// Modal opens when prefillValues is defined; closes by clearing the index
<CreateStudyModal
  open={prefillValues !== undefined}
  onOpenChange={(o) => { if (!o) setRunFollowupIndex(null); }}
  initialValues={prefillValues}
/>
<SuggestedFollowupsPanel
  followups={proposal.digest?.suggested_followups ?? []}
  onRun={setRunFollowupIndex}
/>
```

**Tasks**

1. Extend `CreateStudyModalProps` with optional `initialValues?: PrefillValues`.
2. Add the prefill `useEffect` keyed on `[open, initialValues]` adjacent to the existing line-247 reset effect. **Order matters:** the existing reset runs first (clears `manualMode`); the new effect runs second (calls `form.reset(prefill)`). React effects fire in declaration order — confirm by reading the existing pattern.
3. Extend the submit handler to attach `parent` to the body when `initialValues?.parent` is set.
4. Edit `ui/src/app/proposals/[id]/page.tsx` to wire the prefill state, lazy `useStudy()` fetch, derived `prefillValues`, and `<CreateStudyModal>` instance.
5. Verify `useStudy(id, { enabled })` supports the TanStack `enabled` flag — if not, extend `UseStudyOptions` (line 56 of `studies.ts`) to include it and pass through.
6. Add a vitest test in `ui/src/__tests__/components/studies/create-study-modal.followup-prefill.test.tsx` asserting: (a) when `initialValues` is provided, the form fields populate; (b) when a different `initialValues` is passed (re-render), the form resets to the new values (AC-2 + D-19); (c) submit body includes the `parent` field.

**Definition of Done (DoD)**

- Clicking "Run this followup" triggers `useStudy()` fetch + opens the modal pre-filled (manual smoke test in dev or via E2E in Story 6.1).
- `form.reset(initialValues)` runs on `[open, initialValues]` change (vitest confirms).
- Submit body includes the `parent` lineage payload.
- Existing modal behavior preserved when `initialValues` is omitted (regression test in the existing suite).
- `cd ui && pnpm lint && pnpm typecheck && pnpm test` clean.

### Story 5.3 — Glossary additions for new tooltips

**Outcome:** Five new glossary keys land in `ui/src/lib/glossary.ts` with text matching spec §11 tooltip inventory.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/glossary.ts` | After the existing `proposal.suggested_followups` key (line 471), insert five new keys: `proposal.followup_kind_narrow`, `proposal.followup_kind_widen`, `proposal.followup_kind_text`, `proposal.followup_run_button`, `proposal.followup_search_space_diff`. Copy text per spec §11. The three kind-keys also carry a source-of-truth comment `// Source-of-truth: backend/app/domain/study/followups.py <Variant>` per CLAUDE.md form-dropdown discipline (the keys map 1:1 to the backend enum). |

**Tasks**

1. Insert the five new entries in `ui/src/lib/glossary.ts` with the exact copy from spec §11.
2. Add the source-of-truth comment above the three kind-keys.
3. Update `ui/src/__tests__/lib/glossary.test.ts` (verify exists; if so, extend) — add tests asserting each new key resolves to non-empty `short` text.

**Definition of Done (DoD)**

- All five keys present with matching copy.
- Glossary tests pass.
- `cd ui && pnpm lint && pnpm typecheck` clean.

---

## Epic 6 — E2E test

### Story 6.1 — Playwright happy-path: navigate to proposal → click Run → submit → land on new study

**Outcome:** A new Playwright spec drives the full "Run this followup" flow against the real backend with no `page.route()` mocking.

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/followup_run.spec.ts` | Single happy-path spec: seed a cluster + template + query set + judgment list + parent study (via the existing test helpers) → seed a proposal with a `digests` row containing one structured `narrow` followup (via raw API call to the test-only endpoint or direct DB seed via the integration-test fixture pattern) → navigate to `/proposals/<pid>` → assert the Narrow card renders → click "Run this followup" → assert the modal opens with prefilled fields → click Submit → assert navigation to `/studies/<new id>` → assert the new study's lineage columns via the API. |

**Tasks**

1. Add helper functions in `ui/tests/e2e/helpers/` to seed a digest with a structured followup (extend existing helpers — `ui/tests/e2e/helpers/` already exists per `ls`).
2. Write the spec. Use the existing `signup_flow.spec.ts` pattern as the reference (real-backend setup via API helpers, browser interaction via `page`).
3. Run the spec locally against `make up`-running backend.

**Definition of Done (DoD)**

- `ui/tests/e2e/followup_run.spec.ts` passes with `pnpm test:e2e:stable` (or the project's canonical stable-profile invocation).
- No `page.route()` calls in the spec.
- Assertions use `page.locator(...)` for DOM checks; API used for setup + final verification only.

---

## 3) Testing workstream (required)

Plan testing explicitly by layer and map to stories.

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- Scope: pure-domain Pydantic validation + parser decision table + prompt rendering.
- Files (one owner story each):
  - `backend/tests/unit/domain/study/test_followups.py` — Story 1.1
  - `backend/tests/unit/domain/study/test_followups_backcompat.py` — Story 1.1
  - `backend/tests/unit/llm/test_digest_prompt.py` (extend if exists; create if not) — Story 2.2
- DoD:
  - Every row in FR-4's decision table is covered.
  - Per-kind round-trip + rejection covered.
  - Critical branches deterministic.

### 3.2 Integration tests
- Location: `backend/tests/integration/`
- Scope: DB-backed CHECK + trigger; column-type migration round-trip; worker round-trip; POST /studies parent validation.
- Files (one owner story each):
  - `backend/tests/integration/test_digest_followup_roundtrip.py` — Story 2.3 (worker round-trip with mocked LLM)
  - `backend/tests/integration/test_studies_parent_proposal_check.py` — Story 3.4 (CHECK)
  - `backend/tests/integration/test_studies_parent_proposal_on_delete.py` — Story 3.5 (trigger)
  - `backend/tests/integration/test_digest_followups_migration.py` — Story 3.6 (migration round-trip)
  - `backend/tests/integration/test_studies_with_parent_followup.py` — Story 4.2 (POST /studies parent — all four paths)
- DoD:
  - Happy path + every error / negative path covered.
  - Migration round-trip exercises both populated + empty fixture branches.

### 3.3 Contract tests
- Location: `backend/tests/contract/`
- Scope: response shape + machine-readable error codes per spec §8.5.
- Files (one owner story each):
  - `backend/tests/contract/test_digest_response_shape.py` — Story 4.1
  - `backend/tests/contract/test_proposal_detail_shape.py` — Story 4.1
  - `backend/tests/contract/test_create_study_parent.py` — Story 4.2 (all three new error codes asserted)
- DoD:
  - Every endpoint touched by the plan has a contract test.
  - Every new error code (3) is asserted in at least one contract test.

### 3.4 E2E tests
- Location: `ui/tests/e2e/`
- **Rule: real browser interactions via `page`; no `page.route()` mocking.** API `request` is for test setup only.
- Files (one owner story each):
  - `ui/tests/e2e/followup_run.spec.ts` — Story 6.1
- DoD:
  - Spec passes on the stable Playwright profile.
  - All assertions exercise the browser DOM.

### 3.4b Frontend component tests (vitest)
- Location: `ui/src/__tests__/`
- Files (one owner story each):
  - `ui/src/__tests__/components/proposals/suggested-followups-panel.test.tsx` — Story 5.1
  - `ui/src/__tests__/components/studies/create-study-modal.followup-prefill.test.tsx` — Story 5.2
  - `ui/src/__tests__/lib/glossary.test.ts` (extend existing if present) — Story 5.3

### 3.5 Existing test impact audit

| Test file | Pattern | Required action |
|---|---|---|
| `backend/tests/integration/_digest_helpers.py` | LLM mock returning `{"suggested_followups": ["..."]}` | Update mock to return structured objects per the new schema. |
| `backend/tests/integration/test_digest_*.py` (multiple — verify count at impl time via `grep -rn "suggested_followups" backend/tests/integration/`) | `digest.suggested_followups[i] == "string"` assertions | Update to assert dict shape `{kind, rationale, search_space}` or the wrapped `text`-item form. |
| `backend/tests/contract/test_digest_proposal_api_contract.py` | `suggested_followups: list[str]` assertion in OpenAPI | Update to `list[FollowupItem]`. |
| `ui/src/__tests__/components/proposals/*` | (if any reference `?hypothesis=` link) | Update to assert new per-kind testids; assert no `?hypothesis=` link. |
| `ui/tests/e2e/proposals.spec.ts` | (if it asserts `data-testid="followup-${i}-create-study"`) | Update to the new testids OR confirm no change needed. |

### 3.6 Migration verification (Story 3.1 + Story 3.3)
- [ ] Each new migration includes `downgrade()`.
- [ ] `alembic upgrade head` succeeds for both 0018 and 0019.
- [ ] Round-trip: `alembic downgrade -1 && alembic upgrade head` succeeds for each.
- [ ] No DB revision guard at API startup needed in MVP1 (per state.md known-debt note).

### 3.7 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test`
- [ ] `cd ui && pnpm typecheck`
- [ ] `cd ui && pnpm lint`
- [ ] `cd ui && pnpm test:e2e:stable` (Story 6.1 spec must pass)

---

## 4) Documentation update workstream (required)

### 4.0 Core context files

**`state.md`**
- [ ] After the final story merges: add a new entry to the "Most recent meaningful changes" section noting the feature shipped with its PR # and date.
- [ ] Update Alembic head to `0019` (or whichever the final migration number is).
- [ ] Remove from queued if applicable (not currently in queued list per `state.md:398-417`).

**`architecture.md`**
- [ ] Update the `backend/app/domain/study/` line in the directory map (line 118-127) to include `followups.py`.
- [ ] Update the migrations line (line 189-196) to note 0018 + 0019.
- [ ] Update the `backend/workers/digest.py` description if needed (the structured-followup contract is a notable change worth a brief mention).

**`CLAUDE.md`**
- [ ] No new conventions / rules / env vars / build commands. The feature reuses all existing patterns.
- [ ] No update needed unless a new convention emerges during impl.

### 4.1 Architecture docs (`docs/01_architecture/`)
- [ ] `data-model.md` — extend `studies` table section to document `parent_proposal_id` + `parent_proposal_followup_index` (paired with CHECK + trigger). Extend `digests` table section to document `suggested_followups` as JSONB with the discriminated-union shape.
- [ ] `llm-orchestration.md` — describe the new digest LLM output shape (discriminated union) and the worker's downgrade behavior.
- [ ] `api-conventions.md` — add `PROPOSAL_NOT_FOUND`, `DIGEST_NOT_FOUND`, `FOLLOWUP_INDEX_OUT_OF_RANGE` to the error-code catalog.

### 4.2 Product docs (`docs/02_product/`)
- [ ] No change (this spec lives here; companion phase2/phase3 ideas already present).

### 4.3 Runbooks (`docs/03_runbooks/`)
- [ ] Add an entry to a digest-debugging runbook (or extend the agent-debugging runbook): "If all followups appear as `Suggestion` cards, check the worker logs for `digest_followup_validation_downgraded` to see whether the LLM is emitting invalid `search_space` payloads."

### 4.4 Security docs (`docs/04_security/`)
- [ ] No change (no new secret surface, no new data flow per spec §10).

### 4.5 Quality docs (`docs/05_quality/`)
- [ ] No change (new test files follow the existing layer convention).

**Documentation DoD**
- [ ] `state.md`, `architecture.md` updated.
- [ ] `docs/01_architecture/data-model.md`, `llm-orchestration.md`, `api-conventions.md` updated.
- [ ] Runbook entry added.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- The legacy `?hypothesis=` link is deleted (FR-12) — no deprecation window, no redirect (per `feedback_no_legacy_preservation`).
- The worker's followup-merge loop in Step 13 currently has the drift-followup string-concatenation pattern inline. The rewrite folds it into the structured-list builder cleanly.
- No speculative redesign of the digest worker beyond what's needed for FR-1 / FR-4 / FR-8.

### 5.2 Planned refactor tasks

- [ ] Drop the `flex-1 text-sm` inline `<span>` rationale rendering in the panel; replace with `<p className="text-sm">` inside the new card.
- [ ] Drop the unused `Link` import from `suggested-followups-panel.tsx`.
- [ ] (Backend) None — the existing worker structure is preserved; only the Step-13 followup-merge loop changes.

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven by Story 5.1 vitest + Story 6.1 E2E.
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test` clean.
- [ ] No expansion of product scope (Phase 2 + 3 explicitly deferred via tracking files).

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_digest_proposal` (PR #41) | All stories | Shipped 2026-05-11 | Blocker — the worker + schema this plan extends. Risk = none. |
| `feat_auto_followup_studies` (PR #223) | Story 3.1 (lineage orthogonality) | Shipped 2026-05-24 | Risk = none — the two lineage tracks compose cleanly; only verification that `parent_study_id` continues to work alongside `parent_proposal_id`. |
| `feat_create_study_search_space_builder` | Story 5.2 (modal prefill) | Shipped 2026-05-20 | Soft — the modal's search-space row primitive may be reused for the diff view; fallback to raw JSON viewer if it doesn't compose cleanly. |
| Postgres 16 PL/pgSQL helper functions | Story 3.3 | Available locally + in CI service container | Risk = none. |
| OpenAI-compatible endpoint with structured-output | Story 2.1 worker | Existing capability check gates this | Risk = none — capability-degraded path persists `[]` per D-27. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The structured-output JSON-schema rejection causes the LLM call to fail on edge-case responses | M | M | The schema is `additionalProperties: false` and discriminated by `kind` — a malformed LLM response triggers the existing try/except at `backend/workers/digest.py:725-747` and degrades gracefully. The `parse_followup_list` defensive parser catches anything that slips through. |
| The `_DigestEmbed` wrapper-at-response-construction breaks existing proposal-detail consumers in the UI | L | M | Story 5.1 + 5.2 update the UI in the same PR. The legacy `list[str]` shape is wrapped to `list[FollowupItem]` by the API layer — UI never sees raw strings. Contract test (Story 4.1) asserts the new shape. |
| The column-type migration on a non-empty digests table is slow in production | L | M | MVP1 single-tenant; dozens of rows on a laptop completes sub-second. Production migration documented as table-rewrite in release-notes (no production deployments in MVP1). |
| The BEFORE DELETE trigger fires on test-only proposal hard-deletes and surprises test fixtures | L | L | Story 3.5 explicitly tests this path. Existing tests that delete proposals get a free upgrade (trigger atomically NULLs lineage). |
| The new `FollowupItem` discriminated union confuses Pydantic v2 OpenAPI serializer | L | M | Pydantic v2 has first-class discriminated-union support since 2.0; the `Annotated[Union[...], Field(discriminator='kind')]` pattern is the canonical idiom. Contract test (Story 4.1) asserts the OpenAPI shape. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| LLM returns malformed `search_space` (e.g., cardinality > 10⁶) | LLM hallucination | `parse_followup_list()` downgrades to `text` with `[validation failed: ...]` rationale; WARN log emitted | Automatic — operator sees the item as a Suggestion card |
| LLM returns a non-list `suggested_followups` (e.g., a dict, scalar, null) | LLM hallucination + JSON-schema bypass (e.g. test mock skipping schema) | `parse_followup_list()` returns `[]`; ERROR log `digest_followups_top_level_malformed` | Automatic — operator sees no followups; runbook entry directs them to logs |
| Parent proposal hard-deleted while operator has the modal open | Concurrent delete via test-only endpoint | `POST /studies` returns 404 `PROPOSAL_NOT_FOUND`; UI surfaces the error | Manual — operator refreshes the proposal page |
| Digest regenerated mid-session, shrinking the followup list | Operator ran the runbook escape hatch | `POST /studies` returns 422 `FOLLOWUP_INDEX_OUT_OF_RANGE` | Manual — operator refreshes |
| Capability check is degraded mid-feature | OpenAI endpoint changes capabilities | Worker persists `suggested_followups=[]`; panel hides itself (existing `if (followups.length === 0) return null`) | Automatic |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1 — Domain** (Story 1.1) — pure domain, no DB. Unblocks everything else.
2. **Epic 3 — Migrations + ORM** (Stories 3.1, 3.2, 3.3 in series; 3.4, 3.5, 3.6 once migrations land). Schema is the foundation for API + worker.
3. **Epic 2 — Worker + prompts** (Stories 2.1, 2.2, 2.3) — depends on Epic 1 (domain) + Story 3.3 (JSONB column).
4. **Epic 4 — API** (Stories 4.1, 4.2) — depends on Epic 1 (domain) + Epic 3 (migrations). Story 4.1 is the wire-shape change; Story 4.2 is the parent-validation endpoint extension.
5. **Epic 5 — Frontend** (Stories 5.1, 5.2, 5.3) — depends on Epic 4 (typed OpenAPI surface). Story 5.3 (glossary) has no backend dep — can run earliest.
6. **Epic 6 — E2E** (Story 6.1) — depends on everything.

### Parallelization opportunities

- Story 1.1 (domain) + Story 5.3 (glossary) + Story 3.2 (ORM model — independent of migration execution if local schema is at HEAD already): all independent.
- Story 3.4 / 3.5 / 3.6 (migration verification tests) can run in parallel once 3.1 + 3.3 land.
- Story 4.1 (schemas) + Story 4.2 (endpoint): can be split between two agents if needed; minimal overlap.
- Story 5.1 (panel) + Story 5.2 (prefill flow): can be split — panel ships an `onRun` prop; prefill orchestrates around it.

---

## 8) Rollout and cutover plan

- Rollout stages: single PR; merge to `main` triggers no auto-deploy (MVP1 has no remote staging).
- Feature flag strategy: none. The structured-followup contract replaces the legacy in one PR; no flag.
- Migration/cutover steps: `make migrate` runs the two new migrations in series; round-trip verified locally before push.
- Reconciliation/repair strategy: legacy `digests.suggested_followups` rows backfilled by the migration's USING clause. No external systems involved.

---

## 9) Execution tracker

### Current sprint
- [x] Story 1.1 — followups.py domain module
- [ ] Story 2.1 — worker structured-output schema + validator wiring
- [ ] Story 2.2 — LLM prompts
- [ ] Story 2.3 — worker integration test
- [ ] Story 3.1 — migration 0018 (studies columns + trigger)
- [ ] Story 3.2 — Study ORM update
- [ ] Story 3.3 — migration 0019 (digests JSONB type change)
- [ ] Story 3.4 — CHECK constraint integration test
- [ ] Story 3.5 — BEFORE DELETE trigger integration test
- [ ] Story 3.6 — migration round-trip integration test
- [ ] Story 4.1 — schema wire-shape + wrapper
- [ ] Story 4.2 — POST /studies parent body
- [ ] Story 5.1 — SuggestedFollowupsPanel rewrite
- [ ] Story 5.2 — Create-study modal prefill flow
- [ ] Story 5.3 — Glossary additions
- [ ] Story 6.1 — Playwright E2E happy path

### Blocked items
- None.

### Done this sprint
- (none yet)

---

## 10) Story-by-Story Verification Gate

Before marking any story complete, the executing engineer or agent must attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables)
- [ ] Endpoint contract implemented exactly as documented (method/path/body/status/error code)
- [ ] Key interfaces implemented with compatible signatures
- [ ] Required tests added/updated for all four layers where applicable
- [ ] Commands executed and passed:
    - [ ] `make test-unit`
    - [ ] `make test-integration` (or targeted subset with explanation)
    - [ ] `make test-contract`
    - [ ] `cd ui && pnpm test` (if UI touched)
    - [ ] `cd ui && pnpm test:e2e:stable` (if E2E touched)
- [ ] Migration round-trip evidence included if schema changed (Story 3.1 + 3.3)
- [ ] Related docs updated in same PR when behavior/contract changed

---

## 11) Plan consistency review

Cross-checks performed:

1. **Spec ↔ plan endpoint count:** 3 endpoints in spec §8.1; 3 in plan (Stories 4.1 + 4.2). Match.
2. **Spec ↔ plan error code coverage:** 3 new codes in spec §8.5; all asserted in `test_create_study_parent.py` (contract) + `test_studies_with_parent_followup.py` (integration). Match.
3. **Spec ↔ plan FR coverage:** all 13 FRs assigned to stories in §1 traceability table. Match.
4. **Story internal consistency:** endpoint tables match Pydantic schemas; DoD references correct error codes; no file double-claimed; modified files verified to exist via `Read` + `Bash ls`.
5. **Test file count:** 11 new test files (3 unit + 5 integration + 3 contract + 1 vitest panel + 1 vitest modal-prefill + 1 E2E = 14 if vitest counted; 11 if only backend Python + E2E). Each test file assigned to exactly one story's DoD.
6. **Gate arithmetic:** no per-epic numeric gates declared (epic completes when all its stories' DoDs are satisfied).
7. **Open questions resolved:** spec §19 has no open questions — all D-1 through D-29 are decisions, not questions. Match.
8. **Frontend UI Guidance completeness (Story 5.1 + 5.2):** Insertion point ✓, Analogous markup ✓ (copy-pasteable JSX), Layout ✓, Modal pattern ✓ (deferred to Story 5.2 orchestration), Visual consistency table ✓, Component composition ✓, Interaction behavior table ✓, Handler patterns ✓ (TypeScript snippets for `useEffect` reset + submit body extension + page-level prefill state), IA placement ✓, Tooltips ✓ with glossary keys + source-of-truth comments, Legacy behavior parity ✓ (6 rows on the deleted panel).
9. **Codebase accuracy:** migration directory `migrations/versions/`, current head `0017`, next is `0018`. Router registration via `backend/app/main.py` (verified pattern exists — not modified by this plan since no new router added). `useStudy(id, options)` exists at `ui/src/lib/api/studies.ts:60` — supports the lazy-fetch pattern in Story 5.2.
10. **Enumerated value contract verification:** `FOLLOWUP_KIND_VALUES` cited in Story 5.1 — 3-column compare done (backend `Literal` ↔ spec §8.4 ↔ frontend `enums.ts`) all `narrow|widen|text`. NO frontend `<select>` exposes `kind` (D-12).
11. **Audit-event coverage:** MVP1 — N/A. Spec §6 lists three pre-shaped events for MVP2 activation; no implementation now per CLAUDE.md (audit_log lands at MVP2).
12. **Persistence scope:** no `localStorage` / `sessionStorage` introduced.
13. **Plan ↔ codebase verification:**
    - `digests.suggested_followups` column type `ARRAY(Text)` ✓ at `backend/app/db/models/digest.py:49-58`.
    - `studies.parent_study_id` self-FK ✓ at `backend/app/db/models/study.py:72-74` — confirms orthogonality.
    - `_DigestEmbed.suggested_followups: list[str]` ✓ at `backend/app/api/v1/schemas.py:1006`.
    - `_DigestEmbed` construction at `backend/app/api/v1/proposals.py:154-163` ✓ — wrapper insertion point identified.
    - `DIGEST_RESPONSE_SCHEMA` at `backend/workers/digest.py:169-181` ✓.
    - `_call_openai_for_digest` parse path at `backend/workers/digest.py:411-426` ✓.
    - Followup-merge loop at `backend/workers/digest.py:751-775` ✓.
    - Existing `useEffect(..., [open])` reset pattern at `ui/src/components/studies/create-study-modal.tsx:247-251` ✓.
    - Existing `<Link href={\`/studies?hypothesis=...}\`>` at `ui/src/components/proposals/suggested-followups-panel.tsx:28-33` ✓ (delete target).
    - Existing `InfoTooltip` primitive at `ui/src/components/common/info-tooltip.tsx:37` ✓.
    - Glossary file insertion point after `proposal.suggested_followups` at `ui/src/lib/glossary.ts:471-475` ✓.

No unresolved findings.

---

## 11b) Cross-model review log (GPT-5.5)

### Cycle 1 — 2026-05-23

5 findings. Opus adjudication:

| ID | Severity | Pass | Claim (short) | Verdict | Action |
|---|---|---|---|---|---|
| F1 | Medium | A | Story 3.1 downgrade not explicit | **Accept** | Story 3.1 task 3 now lists the exact ordered drop sequence (trigger → function → CHECK → index → columns). Round-trip gate explicitly named for both 0018 + 0019. |
| F2 | Medium | B | UI search-space diff has no parent data unless modal opens | **Accept** | Story 5.2 `useStudy(parent_study_id)` now `enabled` whenever the proposal has ≥1 actionable (`narrow`/`widen`) followup, so the "Show search space" diff renders pre-Run-click. Panel handles loading + error states gracefully. |
| F3 | Medium | A | Malformed `parent` body → no explicit envelope contract | **Accept** | Story 4.2 task 2b confirms FastAPI's existing `RequestValidationError` handler maps to the canonical `VALIDATION_ERROR` 422 envelope (no new handler needed; same as every other malformed `CreateStudyRequest` field today). Task 4b adds three contract test cases covering short proposal_id, negative followup_index, and non-string proposal_id. |
| F4 | Low | B | §10 spec text mentions future tenant_id activation | **Reject** | Counter-evidence: this is a **spec-level** finding, not a plan-level one. The plan does NOT propagate the tenant assumption — `state.md` and `CLAUDE.md` both explicitly authorize forward-looking tenant references in security sections ("Activates at MVP4: ... every DB write on a tenant-scoped table must include `tenant_id`" — CLAUDE.md). Other shipped specs (e.g., `feat_chat_agent`, `feat_proposals_ui`) carry similar forward-tense tenant notes. No plan changes needed. |
| F5 | Low | A | Spec response example uses literal `gpt-4o-2024-08-06` | **Reject** | Re-raise of spec cycle-1 F5, already adjudicated as spec D-17 with cited counter-evidence: CLAUDE.md Absolute Rule #8 explicitly mandates persisted artifacts capture the exact model identifier (`openai:gpt-4o-2024-08-06`) for lineage. `generated_by` is **persisted lineage data**, not hardcoded service-code model selection. The plan introduces zero new hardcoded model references in code — all worker LLM calls continue to read from `Settings.openai_model`. Spec D-17 stands. |

**Cycle outcome:** 3 accepted (F1 + F2 + F3 applied to plan), 2 rejected with cited counter-evidence. All accepted changes are minor (no scope, sequencing, endpoint, key-interface, or gate-condition changes) — no re-review trigger fired.

### Convergence

Per skill convergence stop rules: accepted changes were all minor (test-task additions + downgrade-task explicitness + UI data-fetch enablement timing). None changed endpoint tables, Pydantic schemas, key interface signatures, migration file paths, gate conditions, or test file assignments. **Cycle 2 was not required** under the "no major accepted change → no re-review trigger" rule (Step 7).

Final tally: 1 cycle, 5 findings (3 accepted, 2 rejected with cited counter-evidence).

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, Endpoints (where applicable), Key interfaces, Tasks, and DoD.
- [x] Test layers (unit/integration/contract/e2e + vitest) are explicitly scoped.
- [x] Documentation updates across docs/01–05 are planned and owned.
- [x] Lean refactor scope and guardrails are explicit.
- [x] Phase/epic gates are measurable (each story's DoD).
- [x] Story-by-Story Verification Gate is included.
- [x] Plan consistency review (§11) has been performed with no unresolved findings.
- [x] Cross-model review (GPT-5.5) on this plan complete and findings adjudicated (§11b — 1 cycle, 3 accepted + 2 rejected with cited counter-evidence; convergence reached, no major accepted changes triggered re-review).

**Status:** Ready for Execution (pending user approval at the pipeline plan gate).
