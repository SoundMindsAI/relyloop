# Feature Specification — Executable Digest Follow-ups

**Date:** 2026-05-23
**Status:** Draft
**Owners:** Eric Starr (product), Eric Starr (engineering)
**Related docs:**
- [`idea.md`](./idea.md) — original brief
- [`docs/01_architecture/llm-orchestration.md`](../../../01_architecture/llm-orchestration.md)
- [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md)
- Sibling: [`feat_auto_followup_studies`](../../../00_overview/implemented_features/2026_05_24_feat_auto_followup_studies/) (shipped 2026-05-24)
- Sibling: [`feat_agent_propose_search_space`](../../../00_overview/implemented_features/2026_05_21_feat_agent_propose_search_space/) (shipped)
- Sibling: [`feat_create_study_search_space_builder`](../../../00_overview/implemented_features/2026_05_20_feat_create_study_search_space_builder/) (shipped)

---

## 1) Purpose

- **Problem:** The digest worker LLM produces `suggested_followups` as flat strings (see `backend/workers/digest.py:169-182`, schema `DIGEST_RESPONSE_SCHEMA`). The UI renders them as bullet text with a "Create study from this hypothesis" button that links to `/studies?hypothesis=<urlencoded>` — but `ui/src/app/studies/page.tsx` never reads the `hypothesis` query param (grep returns zero matches for `hypothesis`/`searchParams` apart from a generic Suspense comment). The button silently drops its payload. Operators end up reading the suggestion, mentally translating it to a `search_space` JSON, and re-typing the entire 6-field create-study wizard. The Karpathy-loop equivalent is one click.
- **Outcome:** The LLM emits a discriminated union (`narrow` | `widen` | `text`) for each followup with a structured `search_space` when applicable. The proposal-detail UI renders the actionable kinds as cards with a primary "Run this followup" button that pre-fills the create-study modal with the parent study's cluster/target/template/query_set/judgment_list/objective plus the LLM-proposed `search_space`. Two new nullable columns on `studies` (`parent_proposal_id` + `parent_proposal_followup_index`) provide lineage so the team can measure whether LLM-suggested followups produce wins.
- **Non-goal:** Auto-running followups without operator review (already covered by `feat_auto_followup_studies` for the deterministic narrow-around-winner case). Spanning multiple studies in one followup. LLM-driven template edits (Tier C in the idea — tracked separately in [`../backlog_feat_digest_template_edit_followups/idea.md`](../backlog_feat_digest_template_edit_followups/idea.md); `backlog_` prefix because the template-editor UI prerequisite doesn't exist yet).

## 2) Current state audit

### Existing implementations

- `backend/workers/digest.py:169-182` — `DIGEST_RESPONSE_SCHEMA` constrains `suggested_followups` to `array of string`, `maxItems: 5`. The `_call_openai_for_digest` helper at lines 378-426 parses `parsed.get("suggested_followups", [])` and the capability-degraded path (lines 411-426) wraps the response into `{"narrative": ..., "suggested_followups": []}`. Step 13 at lines 757-775 prepends a drift followup string and caps at 5.
- `backend/workers/digest.py:761-767` — drift followup is currently a plain string (`f"Best trial used {len(dropped)} params no longer declared..."`). Must become a `{kind: "text", rationale: "..."}` entry after the migration.
- `backend/app/db/models/digest.py:49` — `suggested_followups: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("ARRAY[]::TEXT[]"))`. **The column type must change to JSONB.**
- `migrations/versions/0005_digests.py:52-57` — the canonical migration that created the column as `postgresql.ARRAY(sa.Text())`.
- `backend/app/api/v1/schemas.py:941-951` (`DigestResponse`) and `:999-1007` (`_DigestEmbed`) — both expose `suggested_followups: list[str]`. Must become `list[FollowupItem]`.
- `backend/app/api/v1/proposals.py:154-163` — populates `_DigestEmbed.suggested_followups=digest.suggested_followups` from the ORM. Will automatically pass through the new structure once the ORM column type is JSONB and the schema is `list[FollowupItem]`.
- `ui/src/components/proposals/suggested-followups-panel.tsx` — entire file (42 lines). Props are `followups: readonly string[]`. Renders each as a bullet + a `<Link href={`/studies?hypothesis=${encodeURIComponent(f)}`}>` button. **The query param is unread by `/studies` — dead path.**
- `ui/src/app/proposals/[id]/page.tsx:194-197` — call site. Will be rewritten to pass `digest.suggested_followups` as the new structured list.
- `ui/src/app/studies/page.tsx` — does NOT read any `hypothesis` searchParam (`grep -n "hypothesis\|searchParams"` returns 1 line: a generic comment about `useSearchParams` Suspense boundaries). Dead button.
- `ui/src/components/studies/create-study-modal.tsx:159-185` (`CreateStudyModalProps` + form `defaultValues`) — currently `{open, onOpenChange}`. Will gain an optional `initialValues` prop carrying the pre-fill payload (parent study + LLM `search_space` + `parent_proposal_id` + `parent_proposal_followup_index`). The form must seed `cluster_id`, `target`, `template_id`, `query_set_id`, `judgment_list_id`, `objective`, `config` (incl. `max_trials` / `time_budget_min` / `parallelism` / `sampler`) and the `search_space_text` JSON from the prefill.
- `backend/app/db/models/study.py:72-75` — `parent_study_id` self-FK already exists; comment says "for forks (MVP2)" but `feat_auto_followup_studies` (PR #223 squash `20cf183a`, merged 2026-05-24) already uses it for the auto-chain (`backend/app/services/study_state.py:285-299`, `backend/app/db/repo/study.py:167-188`, `backend/tests/integration/test_auto_followup.py:220,425`). The new `parent_proposal_id` and `parent_proposal_followup_index` columns are **orthogonal** — a study can be both auto-followup (parent_study_id set) and LLM-followup (parent_proposal_id set).
- `backend/app/domain/study/search_space.py:92-118` — `SearchSpace` Pydantic model with `params: dict[str, ParamSpec]`, `min_length=1`, cardinality cap 10⁶. Already used by `POST /api/v1/studies` (`backend/app/api/v1/studies.py:200-204`) — reuse verbatim for digest-side validation.
- `prompts/digest_narrative.system.md:42-58` — current system prompt section telling the LLM how to emit `suggested_followups` as JSON array of short strings. Must teach the three kinds (`narrow` / `widen` / `text`).
- `prompts/digest_narrative.user.jinja` — current user template. Add a `<parent_search_space>` block so the LLM can transform it.
- `ui/src/lib/glossary.ts:471-475` — existing glossary key `proposal.suggested_followups`. Copy stays accurate ("LLM-generated next-study hypotheses ... Click to seed a new study.") but new keys are needed for the kind discriminator (see §11 tooltip inventory).

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| `ui/src/components/proposals/suggested-followups-panel.tsx:29` | `/studies?hypothesis=<urlencoded text>` | **Remove.** The "Create study from this hypothesis" button is replaced by an in-place "Run this followup" button that opens the create-study modal with `initialValues` (no navigation). |

No other components link to `/studies?hypothesis=...`. `grep -rn "hypothesis=" ui/src/` returns only the one line in `suggested-followups-panel.tsx`.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `ui/src/__tests__/components/proposals/suggested-followups-panel.test.*` (if any) | `followups: string[]` assertions | TBD at impl time | Update to the discriminated-union shape; cover all three kinds + the legacy-shape backward-compat read path. |
| `backend/tests/unit/workers/test_digest_*` | `suggested_followups` shape assertions | TBD at impl time | Update to assert the new validated structure on the success path AND the kind-downgrade path on Pydantic validation failure. |
| `backend/tests/contract/test_proposals_*` and `test_studies_digest_*` | `DigestResponse.suggested_followups` is `list[str]` | TBD at impl time | Update contract assertions to the new `list[FollowupItem]` shape; ensure the discriminator + nullable `search_space` round-trip cleanly. |
| `backend/tests/integration/test_digest_*` round-trip tests that stub the LLM | LLM stub returns `list[str]` | TBD at impl time | Update the stub to return the new structured list. Add one test covering the legacy-rows-in-DB read path (the column-type migration backfill). |

The implementation plan will enumerate the exact test files at story-decomposition time; the spec records the categories.

### Existing behaviors affected by scope change

- **`suggested_followups` shape on the wire.** Current: `list[str]` everywhere (DB column, ORM model, `DigestResponse`, `_DigestEmbed`, UI prop). New: `list[FollowupItem]` (discriminated union over `narrow` / `widen` / `text`). **Decision needed:** No — locked in idea + this spec. Legacy DB rows (with `ARRAY(Text)` payloads) are wrapped to `[{kind: "text", rationale: <string>, search_space: null}]` by the migration's USING-clause backfill so downstream readers never see a mixed shape.
- **"Create study from this hypothesis" button.** Current: links to `/studies?hypothesis=...` which is silently dropped. New: the button is **removed** (the new flow ships the structured "Run this followup" button driven by `kind=narrow|widen`; `kind=text` items render as plain bullet text with NO button). **Decision needed:** No — locked in idea ("retire as part of this feature" to avoid two buttons with different semantics).
- **`studies` table lineage.** Current: `parent_study_id` self-FK exists and is used by the auto-chain. New: two additional nullable columns `parent_proposal_id` (FK → `proposals(id)` ON DELETE SET NULL) + `parent_proposal_followup_index INT` are added. Both lineage tracks coexist on the same row (auto-chain child of study A AND LLM-suggested followup from proposal B). **Decision needed:** No.

---

## 3) Scope

### In scope (Phase 1 = Tier A from the idea)

- LLM output schema change for `suggested_followups` to a discriminated union over `{kind: "narrow" | "widen" | "text", rationale: str, search_space: SearchSpace | None}` (FR-1).
- Backend Pydantic models for the followup union + a `parse_followup_list()` adapter that wraps legacy `list[str]` rows into `[{kind: "text", rationale, search_space: null}]` (FR-2 + FR-3).
- Validator at digest-persist time: each `narrow` / `widen` item's `search_space` is validated against `backend.app.domain.study.search_space.SearchSpace`; on failure the item is downgraded to `{kind: "text", rationale: "[validation failed: <error>] " + original_rationale, search_space: null}` so the operator still sees the intent (FR-4).
- Two new nullable columns on `studies`: `parent_proposal_id VARCHAR(36) NULL` (FK to `proposals(id)` with no `ON DELETE` action; a `BEFORE DELETE ON proposals` trigger atomically NULLs the lineage pair — see FR-5) and `parent_proposal_followup_index INT NULL` (FR-5). A partial B-tree index `WHERE parent_proposal_id IS NOT NULL` bounds lookups.
- Migration that **changes the column type** of `digests.suggested_followups` from `ARRAY(Text)` to `JSONB`, with a USING-clause backfill that wraps each existing text element as `jsonb_build_object('kind', 'text', 'rationale', value, 'search_space', NULL)` (FR-6).
- Wire-shape change to `DigestResponse.suggested_followups` and `_DigestEmbed.suggested_followups` from `list[str]` to `list[FollowupItem]` (FR-7).
- LLM prompt updates teaching the model the three kinds (FR-8).
- UI: `SuggestedFollowupsPanel` rewritten to render kind-discriminated cards. `narrow` / `widen` cards have a rationale, a collapsible "Show search space" detail (search-space diff vs parent), and a primary "Run this followup" button (FR-9).
- UI: "Run this followup" opens the existing create-study modal with `initialValues` pre-filled from the parent study + the LLM-proposed `search_space`. Operator reviews + submits via the existing `POST /api/v1/studies` (FR-10).
- UI: `CreateStudyRequest` body sent by the new flow carries the parent lineage fields in a new top-level optional `parent` object (`{proposal_id: str, followup_index: int}`) that the backend persists into the new columns (FR-11).
- UI: legacy `?hypothesis=` button removed from `suggested-followups-panel.tsx` (FR-12).
- Glossary additions for the new tooltips (FR-13).

### Out of scope

- **Tier B — `kind: "swap_template"` followups.** Cross-template search-space remapping (`backend/app/domain/study/template_swap.py` per the idea) is its own design surface. Tracked at sibling folder [`../feat_digest_executable_followups_swap_template/`](../feat_digest_executable_followups_swap_template/idea.md) (split out 2026-05-24).
- **Tier C — `kind: "edit_template"` followups.** Operator-only today; LLM-suggested template edits are a much larger trust/validation surface and unrelated to this spec's lane. Tracked at sibling backlog folder [`../backlog_feat_digest_template_edit_followups/`](../backlog_feat_digest_template_edit_followups/idea.md) (split out 2026-05-24; `backlog_` prefix because the template-editor UI prerequisite doesn't exist yet).
- **Auto-running followups without operator click.** Already shipped as `feat_auto_followup_studies` (PR #223). The two features cover orthogonal compounding paths.
- **Followups that span multiple studies** (e.g., "run A.1 and A.2 in parallel"). Needs its own surface — out.
- **Negative-result feedback loop** ("operator tried this followup; it didn't help"). Out — gated on Langfuse (MVP2+).
- **Audit events.** `audit_log` table doesn't exist in MVP1. §6 names the event types pre-shaped per `data-model.md` for the MVP2 activation.

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` for business endpoints — confirmed in `backend/app/api/v1/studies.py` and `backend/app/api/v1/proposals.py`.
- **Router namespace for this feature's endpoints:** No new router file. This feature **extends** `POST /api/v1/studies` (add the optional `parent` body field) and **changes the response shape** of `GET /api/v1/studies/{study_id}/digest` (`DigestResponse`) + `GET /api/v1/proposals/{id}` (`_DigestEmbed`).
- **HTTP methods for CRUD:** No new methods. The new flow reuses existing `POST /api/v1/studies`.
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` — confirmed at `backend/app/api/v1/studies.py:75-79` (the local `_err()` helper). All new error codes use this exact envelope. Auth error shape: N/A in MVP1.

### Phase boundaries

- **Phase 1 (MVP1):** Tier A — `narrow` / `widen` / `text` kinds + UI prefill + new columns + column-type migration. FR-1 through FR-13. Rationale: smallest end-to-end slice that delivers the one-click operator value with all the storage + plumbing in place.
- **Phase 2 (deferred):** Tier B — `swap_template` kind with cross-template search-space remapping. Split out 2026-05-24 to standalone folder at [`../feat_digest_executable_followups_swap_template/`](../feat_digest_executable_followups_swap_template/idea.md) so it ships cleanly through `/pipeline --auto` with standard artifact names. Rationale: needs a new domain helper (`template_swap.py`), additional LLM prompt logic, and a side-by-side template-comparison UI surface; non-trivial and not blocking Phase 1 value.
- **Phase 3 (deferred — stretch):** Tier C — `edit_template` kind. Split out 2026-05-24 to standalone backlog folder at [`../backlog_feat_digest_template_edit_followups/`](../backlog_feat_digest_template_edit_followups/idea.md). Rationale: changes query rendering semantics, much larger trust surface, likely out of scope for MVP1 entirely.

## 4) Product principles and constraints

- LLM-suggested transformations are always operator-mediated: the LLM proposes; the operator clicks; the operator submits. The new flow never bypasses the existing `POST /api/v1/studies` validation chain (search-space cardinality, declared-params consistency, judgment overlap probe).
- Legacy data must remain readable. Pre-migration digests (`list[str]`) are wrapped into the new shape at backfill time AND the read-path adapter is defensive enough to handle a hypothetical row that escaped the backfill.
- Validation failure on an LLM-emitted `search_space` is a **downgrade**, not a rejection — the operator still sees the intent as text. The digest worker never aborts because of a malformed followup.
- The two lineage tracks (`parent_study_id` for the auto-chain, `parent_proposal_id` for the LLM-suggested click) are independent; both can be set on the same study row.
- All persisted LLM outputs continue to capture `generated_by` (existing column) for lineage; the new structured payloads don't change that contract.
- CLAUDE.md Absolute Rules apply: feature branch + PR; secrets via files; no hardcoded LLM models (`settings.openai_model`); migration ships `downgrade()` and round-trips cleanly; LLM-call timeouts and Redis budget guards from `feat_digest_proposal` continue to apply unchanged.

### Anti-patterns

- **Do not** add a second column (`suggested_followups_structured`) and dual-write during a deprecation window. The idea explicitly locks option (a): in-place type change with USING-clause backfill. There is no production data to preserve in MVP1 (single-tenant on laptops), and a dual-column scheme would leak a deprecated path into downstream readers indefinitely.
- **Do not** invent a separate endpoint (`POST /api/v1/studies/from_followup`). The existing `POST /api/v1/studies` is the contract; the new flow extends its body with an optional `parent` object. A new endpoint would duplicate every validation the existing one already runs.
- **Do not** trust the LLM-emitted `search_space` blindly. Run it through the existing `SearchSpace.model_validate()` at digest-persist time. On failure, downgrade — never persist an invalid `search_space` JSONB blob.
- **Do not** read `parent_proposal_followup_index` without `parent_proposal_id`. The index is meaningless without the proposal ID. The two columns are conceptually a pair (enforced by §9 invariant).
- **Do not** mix the legacy `?hypothesis=` button with the new "Run this followup" button — operators would see two buttons with subtly different semantics. Delete the legacy button in the same PR that ships the new one (FR-12).
- **Do not** keep `narrow` / `widen` `search_space` validation logic in the worker module. It belongs in a domain helper alongside `SearchSpace` so unit tests can exercise the validation + downgrade path without the worker fixture chain.

## 5) Assumptions and dependencies

- Dependency: **`feat_auto_followup_studies`** (shipped 2026-05-24 as PR #223 squash `20cf183a`). Status: implemented. Risk if missing: none — the two features are orthogonal. The new `parent_proposal_id` column composes cleanly with the existing `parent_study_id` self-FK without modification.
- Dependency: **`feat_digest_proposal`** (shipped 2026-05-11 as PR #41). Status: implemented. Provides the digest worker, schema, prompts, and the entire LLM-call infrastructure this spec modifies. Risk if missing: blocker — N/A, already shipped.
- Dependency: **`feat_create_study_search_space_builder`** (shipped 2026-05-20). Status: implemented. The create-study modal's search-space row primitive is reused by the "search-space diff" detail view. Risk if missing: soft — could fall back to raw JSON diff.
- Dependency: **`feat_agent_propose_search_space`** (shipped 2026-05-21). Status: implemented. Provides `backend/app/domain/study/search_space_defaults.py` heuristic that would be reused by Tier B's `swap_template` path (Phase 2 only — not Phase 1).
- Dependency: **OpenAI-compatible endpoint with structured-output (`json_schema`) capability.** The digest worker's existing capability check (`backend/app/llm/capability_check.py` → `read_capability_result`) already gates `structured_output_enabled`. When degraded, the worker falls back to narrative-only and persists `suggested_followups=[]` (current behavior, preserved). Risk if missing: graceful degradation already in place.
- Dependency: **No new env vars, no new secrets.** Reuses `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` from `Settings`.

## 6) Actors and roles

- Primary actor(s): **Relevance Engineer** (umbrella spec §6). The operator reviewing a proposal's digest who wants to one-click a followup study.
- Role model: **N/A — single-tenant install, no auth surface.** MVP1.
- Permission boundaries: **N/A — single-tenant.** Activates at MVP4 per CLAUDE.md.

### Authorization

N/A — single-tenant install, no auth surface (MVP1).

### Audit events

**N/A in MVP1 — `audit_log` table lands at MVP2** per `docs/01_architecture/data-model.md` §"Reserved for later releases".

**Pre-shaped for MVP2 (forthcoming, do NOT implement now):**

| Event type | Trigger | Visibility | Metadata fields |
|---|---|---|---|
| `digest.followup_clicked` | UI fires the "Run this followup" button (recorded at the `POST /api/v1/studies` boundary when `body.parent` is set). | tenant-visible | `proposal_id`, `followup_index`, `followup_kind` (`narrow` / `widen`), `created_study_id`. No `search_space` payload (already persisted on `studies.search_space`). |
| `study.created_from_followup` | Side-effect of `POST /api/v1/studies` when `parent.proposal_id` is set — emitted in the same transaction as the `INSERT INTO studies` (atomic). | tenant-visible | `study_id`, `parent_proposal_id`, `parent_proposal_followup_index`, `cluster_id`, `template_id`. |
| `digest.followup_validation_downgraded` | Digest worker downgrades a `narrow`/`widen` item to `text` because `SearchSpace.model_validate` failed. | system | `study_id`, `proposal_id`, `followup_index`, `original_kind`, `validation_error` (truncated to 500 chars; no PII). |

No credentials, tokens, or PII beyond display-name strings in metadata.

## 7) Functional requirements

### FR-1: Discriminated-union followup schema (LLM output)

- The system **MUST** emit `suggested_followups` from the digest LLM as a JSON array of objects where each object has fields `{kind: "narrow" | "widen" | "text", rationale: string, search_space: object | null}`.
- The system **MUST** enforce `maxItems: 5` on the array (preserved from current `DIGEST_RESPONSE_SCHEMA`).
- The system **MUST** require `search_space` to be a JSON object on `kind="narrow"|"widen"` items and `null` on `kind="text"` items at the JSON-schema level.
- The system **MUST** preserve the existing capability-fallback behavior: when `structured_output_enabled` is false, the worker persists `suggested_followups=[]` (**including suppressing the post-LLM drift-followup synthesis** — per GPT-5.5 cycle-3 F1 and matching the current code at `backend/workers/digest.py:757-758` where the drift prepend lives INSIDE the `if structured_output_enabled:` branch). FR-8's drift-synthesis contract therefore applies ONLY to the structured (non-degraded) path.
- Notes: enforced at the `DIGEST_RESPONSE_SCHEMA` JSON-schema level so the OpenAI structured-output API rejects malformed responses before they reach the worker.

### FR-2: Backward-compatible read-path adapter

- The system **MUST** wrap any `digests.suggested_followups` row whose stored payload is a JSON array of strings (legacy shape post-backfill — should not occur, but defensive) into `[{kind: "text", rationale: <string>, search_space: null}]` at read time.
- The system **MUST** treat the post-migration shape (array of objects) as the canonical reader contract.
- Notes: The post-migration backfill (FR-6) eliminates legacy rows in steady state, but the adapter exists so the API never crashes on an unexpected payload.

### FR-3: Pydantic models for the followup union (backend domain)

- The system **MUST** define `FollowupItem` as a Pydantic v2 discriminated-union type alias:
  ```python
  FollowupItem = Annotated[
      NarrowFollowup | WidenFollowup | TextFollowup,
      Field(discriminator="kind"),
  ]
  ```
  Each concrete model (`NarrowFollowup`, `WidenFollowup`, `TextFollowup`) is a `BaseModel` with `model_config = ConfigDict(extra="forbid")` and a `kind: Literal["narrow"|"widen"|"text"]` discriminator. The `narrow` and `widen` variants carry `search_space: SearchSpace` (reusing `backend.app.domain.study.search_space.SearchSpace`); the `text` variant carries `search_space: None` (explicit null).
- The system **MUST** export a module-level `FollowupItemAdapter = TypeAdapter(FollowupItem)` and `FollowupListAdapter = TypeAdapter(list[FollowupItem])` for validation (per GPT-5.5 cycle-1 F3 — a discriminated-union `Annotated` alias is NOT a `BaseModel` and does NOT expose `.model_validate()`; the correct API is `TypeAdapter(FollowupItem).validate_python(...)`).
- The system **MUST** export a `serialize_followup_list(items: list[FollowupItem]) -> list[dict[str, Any]]` helper that returns `[item.model_dump(mode="json") for item in items]` (per GPT-5.5 cycle-2 F4 — SQLAlchemy's JSONB driver does NOT know how to serialize Pydantic `BaseModel` instances; passing them directly would either crash on insert or store a malformed shape. The worker MUST call `serialize_followup_list(...)` before assigning to `digest.suggested_followups`). The `mode="json"` argument ensures nested `SearchSpace` models flatten to plain JSON dicts.
- The system **MUST** locate the models, adapters, and helpers in `backend/app/domain/study/followups.py` (pure-domain, no I/O) so unit tests exercise validation without DB or LLM fixtures.

### FR-4: Validator + downgrade at digest-persist time

- The system **MUST** validate each LLM-emitted followup item via `FollowupItemAdapter.validate_python(item)` (per GPT-5.5 cycle-1 F3) after the LLM call and before the digest row is INSERTed.
- The system **MUST** provide a `parse_followup_list(raw: object, *, study_id: str | None = None, proposal_id: str | None = None) -> list[FollowupItem]` helper in `backend/app/domain/study/followups.py`. Context kwargs are passed-through to the structlog WARN/ERROR events emitted on downgrade/drop paths (per GPT-5.5 cycle-2 F3 — the helper otherwise has no way to populate the required `study_id` / `proposal_id` log fields). Callers MUST pass both when available; either may be `None` on read-path adapter calls where the IDs aren't loaded (in which case the field appears as `study_id=null`/`proposal_id=null` in the event payload — operators can correlate via the surrounding request log).
- The helper handles every malformed-input shape (per GPT-5.5 cycle-1 F8). The complete decision table:

  | Input shape | Behavior |
  |---|---|
  | `list[str]` (legacy `ARRAY(Text)` shape that escaped the migration backfill) | Wrap each string `s` as `TextFollowup(kind="text", rationale=s, search_space=None)`. |
  | `list[dict]` with valid `kind ∈ {"narrow", "widen", "text"}` and the per-variant schema | `FollowupItemAdapter.validate_python(item)`. |
  | `dict` with `kind ∈ {"narrow", "widen"}` whose `search_space` fails `SearchSpace` validation (cardinality, bounds, etc.) | Downgrade to `TextFollowup(kind="text", rationale="[validation failed: <truncated 200-char error>] " + original_rationale, search_space=None)`. |
  | `dict` with `kind ∈ {"narrow", "widen"}` that fails `FollowupItemAdapter.validate_python(...)` for any other reason (missing/non-string `rationale`, missing/null `search_space`, malformed non-dict `search_space`, extra fields rejected by `extra="forbid"`) | If a top-level `rationale` string can be salvaged, downgrade to `TextFollowup(kind="text", rationale="[validation failed: <truncated error>] " + salvaged_rationale, search_space=None)` and emit `digest_followup_validation_downgraded`. Otherwise drop with `digest_followup_dropped`. **All `ValidationError` paths from `FollowupItemAdapter` MUST be caught** — none escape (per GPT-5.5 cycle-3 F2). |
  | `dict` with `kind="text"` but malformed (missing rationale, extra fields, etc.) | If a `rationale` string can be salvaged, emit `TextFollowup(kind="text", rationale=<salvaged>, search_space=None)`; otherwise drop with a WARN. |
  | `dict` with `kind` missing OR `kind` ∉ {`narrow`, `widen`, `text`} | If a top-level `rationale` string exists, salvage it as a `TextFollowup`; otherwise drop with a WARN. |
  | Non-`dict` array element (number, bool, null, nested array) | Drop with a WARN. |
  | Top-level input is not a list (object, scalar, null) | Return `[]` and log an ERROR `digest_followups_top_level_malformed`. |

- The system **MUST NOT** abort the digest write because of a malformed followup. The narrative + valid followups still persist; invalid ones persist as `text` items carrying the original intent (or are silently dropped per the table above when no rationale is recoverable).
- The system **MUST** emit a `digest_followup_validation_downgraded` structlog WARN event for each downgrade with `study_id`, `proposal_id`, `original_kind`, and the truncated validation error.
- The system **MUST** emit a `digest_followup_dropped` structlog WARN event for each drop (no salvageable rationale) with `study_id`, `proposal_id`, and the unparseable item (truncated to 200 chars).

### FR-5: New columns on `studies` for LLM-followup lineage

- The system **MUST** add `parent_proposal_id VARCHAR(36) NULL` to `studies`, with a foreign-key constraint to `proposals(id)` and **NO** `ON DELETE` clause (no cascade, no SET NULL — see the trigger requirement below for the lineage-detach behavior).
- The system **MUST** add `parent_proposal_followup_index INT NULL` to `studies` — 0-based position of the LLM-emitted followup within the parent proposal's structured `suggested_followups` array.
- The system **MUST** create a partial B-tree index on `studies(parent_proposal_id) WHERE parent_proposal_id IS NOT NULL` so future "show all studies spawned from proposal X" queries are bounded.
- The system **MUST** enforce the pair invariant via a CHECK constraint: `(parent_proposal_id IS NULL AND parent_proposal_followup_index IS NULL) OR (parent_proposal_id IS NOT NULL AND parent_proposal_followup_index IS NOT NULL AND parent_proposal_followup_index >= 0)`. The `>= 0` lower bound is defensive against direct DB writes that bypass the API's `Field(ge=0)` validation (per GPT-5.5 cycle-1 F4).
- The system **MUST** install a `BEFORE DELETE ON proposals` trigger (e.g., `trg_clear_studies_parent_proposal_on_proposal_delete`) that, for each `studies` row where `parent_proposal_id = OLD.id`, sets BOTH `parent_proposal_id = NULL` AND `parent_proposal_followup_index = NULL`. This is the mechanism that preserves the CHECK invariant when a parent proposal is hard-deleted — `ON DELETE SET NULL` on the FK alone would clear only the FK column and immediately violate the pair CHECK (per GPT-5.5 cycle-1 F1). The trigger and its function are created in the same migration `upgrade()` and dropped in `downgrade()`.
- The system **MUST NOT** require either column on existing rows or on studies created without a parent followup — both columns are nullable.

### FR-6: `digests.suggested_followups` column-type migration

- The system **MUST** ship one Alembic migration that ALTERs `digests.suggested_followups` from `ARRAY(Text)` to `JSONB`.
- The system **MUST** perform the type change using **migration-local helper functions**, not inline subquery USING expressions. PostgreSQL rejects subqueries in `ALTER COLUMN TYPE ... USING` expressions with `ERROR: cannot use subquery in transform expression` (verified empirically against the project's local Postgres 16, per GPT-5.5 cycle-2 F1). A scalar PL/pgSQL function called from USING is the supported alternative.
- The migration `upgrade()` body MUST follow this shape (function defined, used, dropped):
  ```sql
  CREATE OR REPLACE FUNCTION _fn_wrap_text_array_as_jsonb_followups(arr TEXT[])
  RETURNS jsonb AS $$
  DECLARE
    result jsonb := '[]'::jsonb;
    elem TEXT;
  BEGIN
    IF arr IS NULL THEN
      RETURN '[]'::jsonb;
    END IF;
    FOREACH elem IN ARRAY arr LOOP
      result := result || jsonb_build_array(jsonb_build_object(
        'kind', 'text',
        'rationale', elem,
        'search_space', NULL
      ));
    END LOOP;
    RETURN result;
  END;
  $$ LANGUAGE plpgsql IMMUTABLE;

  ALTER TABLE digests ALTER COLUMN suggested_followups DROP DEFAULT;
  ALTER TABLE digests
    ALTER COLUMN suggested_followups TYPE jsonb
    USING _fn_wrap_text_array_as_jsonb_followups(suggested_followups);
  ALTER TABLE digests
    ALTER COLUMN suggested_followups SET DEFAULT '[]'::jsonb;

  DROP FUNCTION _fn_wrap_text_array_as_jsonb_followups(TEXT[]);
  ```
- The migration `downgrade()` body MUST follow the symmetric shape:
  ```sql
  CREATE OR REPLACE FUNCTION _fn_unwrap_jsonb_followups_as_text_array(payload jsonb)
  RETURNS TEXT[] AS $$
  DECLARE
    result TEXT[] := ARRAY[]::TEXT[];
    elem jsonb;
  BEGIN
    IF payload IS NULL OR jsonb_array_length(payload) = 0 THEN
      RETURN ARRAY[]::TEXT[];
    END IF;
    FOR elem IN SELECT * FROM jsonb_array_elements(payload) LOOP
      result := result || (elem->>'rationale');
    END LOOP;
    RETURN result;
  END;
  $$ LANGUAGE plpgsql IMMUTABLE;

  ALTER TABLE digests ALTER COLUMN suggested_followups DROP DEFAULT;
  ALTER TABLE digests
    ALTER COLUMN suggested_followups TYPE text[]
    USING _fn_unwrap_jsonb_followups_as_text_array(suggested_followups);
  ALTER TABLE digests
    ALTER COLUMN suggested_followups SET DEFAULT ARRAY[]::text[];

  DROP FUNCTION _fn_unwrap_jsonb_followups_as_text_array(jsonb);
  ```
  Downgrade is **lossy by design** — any non-`text` kind reverts to its rationale string. Acceptable in MVP1 (no production data; downgrade is a dev-DB operation).
- The system **MUST** set the new `server_default` to `'[]'::jsonb` (matching the prior `ARRAY[]::TEXT[]` empty-default behavior). The DROP DEFAULT step is required because the old default's type doesn't match the new column type.
- The system **MUST** verify round-trip with `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` per CLAUDE.md Absolute Rule #5, including a fixture with both populated AND empty `suggested_followups` rows so both branches of the helper functions are exercised.
- The system **MUST NOT** require a separate `suggested_followups_structured` column or a dual-write deprecation window (rejected — see §4 anti-patterns).

### FR-7: Wire-shape change to `DigestResponse` and `_DigestEmbed`

- The system **MUST** change `DigestResponse.suggested_followups` (`backend/app/api/v1/schemas.py:949`) from `list[str]` to `list[FollowupItem]`.
- The system **MUST** change `_DigestEmbed.suggested_followups` (`backend/app/api/v1/schemas.py:1006`) from `list[str]` to `list[FollowupItem]`.
- The system **MUST** call `parse_followup_list(digest.suggested_followups, study_id=..., proposal_id=...)` at EVERY response-construction site that exposes the field — both `GET /api/v1/studies/{study_id}/digest` AND `GET /api/v1/proposals/{proposal_id}` (the `_DigestEmbed` construction at `backend/app/api/v1/proposals.py:155-163`). The ORM column returns raw `list[dict]`; raw pass-through would make Pydantic response validation reject defensive legacy `list[str]` rows (per GPT-5.5 cycle-2 F5). The wrapper guarantees both endpoints emit the canonical shape regardless of what's in the database.
- The system **MUST** preserve all other fields on both schemas unchanged.
- Notes: This is a breaking change to the response shape but MVP1 has no external consumers — only the in-repo Next.js frontend reads these endpoints. The frontend lands in the same PR.

### FR-8: LLM prompt updates

- The system **MUST** update `prompts/digest_narrative.system.md` to describe the three followup kinds + when to use each (`narrow` = winner sits in a sub-region of the prior search space → emit narrower bounds; `widen` = winner is at an edge (`= low` or `= high`) → emit broader bounds; `text` = a suggestion that requires operator judgment, e.g., "consider adding a new parameter to the template").
- The system **MUST** update `prompts/digest_narrative.user.jinja` to render the parent study's `search_space` as a structured `<parent_search_space>` block alongside the existing `<top_trials>` / `<parameter_importance>` blocks, so the LLM can transform it into `narrow` / `widen` proposals.
- The system **MUST** preserve the drift-followup contract from the existing worker (when `<dropped_template_params>` is non-empty AND `structured_output_enabled` is true, the first followup mentions the drift). The drift followup is emitted by the worker (post-LLM, as today) as a synthesized `{kind: "text", rationale: <drift message>, search_space: null}` item prepended to the LLM-emitted list, then truncated to 5. In capability-degraded mode (`structured_output_enabled=false`) no drift item is emitted — `suggested_followups` stays `[]` (per FR-1 clarification / GPT-5.5 cycle-3 F1).

### FR-9: UI — kind-discriminated followup cards

- The system **MUST** rewrite `ui/src/components/proposals/suggested-followups-panel.tsx` to render each followup as a kind-discriminated card.
- For `kind="narrow"` and `kind="widen"`: the card **MUST** show the rationale text + a primary "Run this followup" button. The card **SHOULD** include a collapsible "Show search space" detail that renders the diff vs the parent study's `search_space`.
- For `kind="text"`: the card **MUST** render the rationale as bullet text (matching today's behavior for plain-string suggestions). NO "Run this followup" button.
- The system **MUST** preserve the existing `data-testid="suggested-followups-list"` on the container for E2E continuity.
- The system **MUST** use new per-item `data-testid` values: `followup-${i}-run` (button), `followup-${i}-card` (card), `followup-${i}-show-search-space` (collapse toggle).

### FR-10: UI — "Run this followup" pre-fills the create-study modal

- The system **MUST** fetch `GET /api/v1/studies/{parent_study_id}` lazily when "Run this followup" is clicked, since the existing `_StudySummary` embed at `backend/app/api/v1/schemas.py:987-996` (returned by `GET /api/v1/proposals/{id}`) only carries `{id, name, status, best_metric, best_trial_id, query_set, judgment_list}` and does **not** include the `cluster_id`, `target`, `template_id`, `objective`, or `config` fields needed for prefill (per GPT-5.5 cycle-1 F6). The full `StudyDetail` response provides all required fields. The fetch uses the existing `useStudy(studyId)` hook in `ui/src/lib/api/studies.ts` (TanStack Query, cached).
- The system **MUST** open the existing `CreateStudyModal` (`ui/src/components/studies/create-study-modal.tsx`) when the parent-study fetch resolves, passing an `initialValues` prop carrying: parent study's `cluster_id`, `target`, `template_id`, `query_set_id`, `judgment_list_id`, parent's `objective` (metric / k / direction), parent's stop conditions from `config` (`max_trials`, `time_budget_min`, `parallelism`, `sampler`, `pruner`, `seed`, `trial_timeout_s`), the LLM-proposed `search_space` (serialized to JSON in the form's `search_space_text` field), and the lineage pair `{parent_proposal_id, parent_proposal_followup_index}`.
- The system **MUST** call `form.reset(derivedInitialValues)` inside a `useEffect` keyed on `[open, initialValues]` so that clicking different followups within a single page session correctly re-seeds the form (per GPT-5.5 cycle-1 F7 — React Hook Form's `defaultValues` apply only on initial mount; without an explicit `reset`, a second followup click would render stale values from the first). The existing modal-open reset effect (currently at `create-study-modal.tsx:247-251`) is the natural extension point.
- The system **MUST** allow the operator to edit any pre-filled field before submitting (the modal's existing 5-step wizard wiring is preserved — no read-only mode).
- The system **MUST** include the lineage pair in the eventual `POST /api/v1/studies` body via the new optional `parent` field (FR-11).
- The system **MUST** default the new study's `name` to a descriptive value derived from the parent: e.g., `"<parent study name> — followup #<index+1> (<kind>)"`. Operator can override.

### FR-11: API — `POST /api/v1/studies` accepts optional `parent` body field

- The system **MUST** extend `CreateStudyRequest` (`backend/app/api/v1/schemas.py:613-630`) with an optional `parent: ParentFollowupRef | None = None` field, where `ParentFollowupRef` carries `{proposal_id: str (UUIDv7, 36 chars), followup_index: int (>= 0)}`.
- When `body.parent` is set, the system **MUST** validate: (a) the proposal exists (404 `PROPOSAL_NOT_FOUND` if not); (b) the proposal has a digest (404 `DIGEST_NOT_FOUND` if not); (c) `followup_index < len(parsed_followups)` where `parsed_followups = parse_followup_list(digest.suggested_followups, study_id=digest.study_id, proposal_id=proposal.id)` (422 `FOLLOWUP_INDEX_OUT_OF_RANGE` if not). The validation MUST use the **parsed canonical list**, not the raw JSONB array length, so the index always matches the followup the operator saw on the proposal-detail page (per GPT-5.5 cycle-3 F3). Defensive dropped malformed elements would otherwise shift indices between the displayed list and the validation.
- When `body.parent` validates, the system **MUST** persist `parent_proposal_id = body.parent.proposal_id` and `parent_proposal_followup_index = body.parent.followup_index` on the new study row, atomically with the existing INSERT.
- The system **MUST NOT** require `body.parent` — omitting it preserves all existing create-study behavior verbatim.
- The system **MUST NOT** reject a `body.parent` whose referenced followup is `kind="text"` — the operator may have manually populated `search_space` and chosen to record lineage anyway. (The UI only shows the "Run this followup" button on `narrow`/`widen` items, but the API doesn't enforce that.)

### FR-12: Retire the dead `?hypothesis=` button

- The system **MUST** remove the `<Link href={`/studies?hypothesis=${encodeURIComponent(f)}`}>` button from `ui/src/components/proposals/suggested-followups-panel.tsx`.
- The system **MUST NOT** leave a redirect, fallback, or deprecated marker — the path is dead today and the new path replaces it cleanly (per CLAUDE.md user instructions: forward-only, no legacy preservation).

### FR-13: Glossary additions for the new tooltips

- The system **MUST** add the following glossary keys to `ui/src/lib/glossary.ts` (see §11 tooltip inventory for exact text):
  - `proposal.followup_kind_narrow`
  - `proposal.followup_kind_widen`
  - `proposal.followup_kind_text`
  - `proposal.followup_run_button`
  - `proposal.followup_search_space_diff`
- The existing `proposal.suggested_followups` key copy may be left unchanged (still accurate) OR refined to mention the kind discriminator in a follow-up PR — no spec requirement.

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/studies` | **Modified.** Existing endpoint; gains optional `parent` body field for LLM-followup lineage. | `PROPOSAL_NOT_FOUND` (404, new), `DIGEST_NOT_FOUND` (404, new), `FOLLOWUP_INDEX_OUT_OF_RANGE` (422, new). All pre-existing codes preserved (`INVALID_SEARCH_SPACE`, `CLUSTER_NOT_FOUND`, `TEMPLATE_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `JUDGMENT_LIST_NOT_FOUND`, `VALIDATION_ERROR`, `JUDGMENT_CLUSTER_MISMATCH`, `JUDGMENT_TARGET_MISMATCH`, `INSUFFICIENT_JUDGMENT_OVERLAP`, `SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM`). |
| `GET` | `/api/v1/studies/{study_id}/digest` | **Modified.** Response shape change: `suggested_followups` becomes `list[FollowupItem]`. | `DIGEST_NOT_READY` (404, unchanged). |
| `GET` | `/api/v1/proposals/{proposal_id}` | **Modified.** Inline `digest.suggested_followups` shape change. | `PROPOSAL_NOT_FOUND` (404, unchanged). |

No new endpoints. No method or path changes — only body/response shape extensions.

### 8.2 Contract rules

- Error body **MUST** match the canonical envelope: `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` (per `_err()` helper at `backend/app/api/v1/studies.py:75-79`).
- Status codes **MUST** be deterministic per scenario.
- Cross-tenant access: N/A (single-tenant MVP1).
- The discriminator field `kind` on `FollowupItem` **MUST** appear in every wire payload — Pydantic v2 discriminated unions require it for round-trip validation.

### 8.3 Response examples

**Success — `GET /api/v1/studies/{id}/digest` with mixed followup kinds:**

```json
{
  "id": "0190a3b4-1234-7abc-9def-000000000001",
  "study_id": "0190a3b4-1234-7abc-9def-000000000002",
  "narrative": "The study converged on `title_boost=2.1` with NDCG@10 = 0.84 (+0.13 vs baseline)...",
  "parameter_importance": { "title_boost": 0.62, "tie_breaker": 0.18 },
  "recommended_config": { "title_boost": 2.1, "tie_breaker": 0.3 },
  "suggested_followups": [
    {
      "kind": "narrow",
      "rationale": "title_boost winners clustered between 1.8 and 2.4; narrow to that band.",
      "search_space": {
        "params": {
          "title_boost": { "type": "float", "low": 1.8, "high": 2.4 },
          "tie_breaker": { "type": "float", "low": 0.0, "high": 1.0 }
        }
      }
    },
    {
      "kind": "widen",
      "rationale": "tie_breaker hit the upper edge of [0, 1]; try [0, 2].",
      "search_space": {
        "params": {
          "title_boost": { "type": "float", "low": 0.1, "high": 10.0, "log": true },
          "tie_breaker": { "type": "float", "low": 0.0, "high": 2.0 }
        }
      }
    },
    {
      "kind": "text",
      "rationale": "Consider adding a category_boost parameter to the template — several winning trials suggest category prioritization matters.",
      "search_space": null
    }
  ],
  "generated_by": "openai:gpt-4o-2024-08-06",
  "generated_at": "2026-05-23T18:00:00Z"
}
```

**Success — `POST /api/v1/studies` with `parent` lineage:**

Request body:
```json
{
  "name": "Title-boost study — followup #1 (narrow)",
  "cluster_id": "0190a3b4-1234-7abc-9def-000000000010",
  "target": "products_v3",
  "template_id": "0190a3b4-1234-7abc-9def-000000000011",
  "query_set_id": "0190a3b4-1234-7abc-9def-000000000012",
  "judgment_list_id": "0190a3b4-1234-7abc-9def-000000000013",
  "search_space": { "params": { "title_boost": { "type": "float", "low": 1.8, "high": 2.4 } } },
  "objective": { "metric": "ndcg", "k": 10, "direction": "maximize" },
  "config": { "max_trials": 200, "parallelism": 4, "sampler": "tpe", "pruner": "median" },
  "parent": { "proposal_id": "0190a3b4-1234-7abc-9def-000000000020", "followup_index": 0 }
}
```

Response: standard `StudyDetail` (existing shape — `parent_study_id` field already present, lineage to the parent proposal is on the new `parent_proposal_id` + `parent_proposal_followup_index` columns, which are NOT currently exposed on `StudyDetail`; see §19 Decision Log #D-5 for rationale).

**Failure — `POST /api/v1/studies` with out-of-range `parent.followup_index`:**

HTTP 422:
```json
{
  "detail": {
    "error_code": "FOLLOWUP_INDEX_OUT_OF_RANGE",
    "message": "parent.followup_index=7 exceeds the digest's suggested_followups length (3) for proposal 0190a3b4-1234-7abc-9def-000000000020",
    "retryable": false
  }
}
```

**Failure — `POST /api/v1/studies` with unknown `parent.proposal_id`:**

HTTP 404:
```json
{
  "detail": {
    "error_code": "PROPOSAL_NOT_FOUND",
    "message": "proposal 0190a3b4-1234-7abc-9def-000000000020 not found",
    "retryable": false
  }
}
```

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `FollowupItem.kind` | `narrow`, `widen`, `text` | `backend/app/domain/study/followups.py` — the `Literal["narrow", "widen", "text"]` discriminator on the `NarrowFollowup`/`WidenFollowup`/`TextFollowup` Pydantic models (new file added by this spec). Mirrored as a TypeScript `type FollowupKind = 'narrow' \| 'widen' \| 'text'` in `ui/src/lib/enums.ts` with the source-of-truth comment `// Values must match backend/app/domain/study/followups.py FollowupItem.kind`. | `suggested-followups-panel.tsx` (kind-based card rendering). Forbidden as a dropdown — operators don't pick the kind, the LLM emits it. |
| `parent.proposal_id` | Any UUIDv7-shaped string of length 36 (free-form, validated as FK at the API boundary). | `backend/app/db/models/proposal.py` — `id: Mapped[str] = mapped_column(String(36), primary_key=True)`. | "Run this followup" click handler — value is the parent proposal's `id`, not user-pickable. |
| `parent.followup_index` | Any integer `>= 0` and `< len(digest.suggested_followups)`. | `backend/app/domain/study/followups.py` — `FollowupIndex = Annotated[int, Field(ge=0)]`. Upper bound validated at the API boundary against the live digest. | "Run this followup" click handler — value is the array index, not user-pickable. |

No frontend dropdown displays `kind` as an option list — the LLM is the producer and the UI only renders. The discriminator value is asserted on `data-testid` patterns (`followup-${i}-card` per kind) and on inline kind labels ("Narrow" / "Widen" / "Suggestion") for clarity (see §11 tooltip inventory).

### 8.5 Error code catalog

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `PROPOSAL_NOT_FOUND` | 404 | `body.parent.proposal_id` references a proposal that does not exist. |
| `DIGEST_NOT_FOUND` | 404 | The referenced proposal exists but has no digest yet (digest worker hasn't run). |
| `FOLLOWUP_INDEX_OUT_OF_RANGE` | 422 | `body.parent.followup_index` >= `len(digest.suggested_followups)`. |

All other codes used by this feature are pre-existing on `POST /api/v1/studies` and unchanged.

## 9) Data model and state transitions

### Modified table: `digests`

- **CHANGE** column `suggested_followups` from `ARRAY(Text) NOT NULL DEFAULT ARRAY[]::TEXT[]` to `JSONB NOT NULL DEFAULT '[]'::jsonb`.
- Backfill via USING clause (see FR-6): each existing text element wrapped as `{kind: "text", rationale: <text>, search_space: null}`.
- ORM mapping changes from `Mapped[list[str]] = mapped_column(ARRAY(Text), ...)` to `Mapped[list[dict[str, Any]]] = mapped_column(JSONB, ...)`. (The repo-layer returns raw `list[dict]`; the API layer / domain reader applies the Pydantic discriminated-union validation at the response-serialization boundary.)

### Modified table: `studies`

- **ADD** column `parent_proposal_id VARCHAR(36) NULL` with `FOREIGN KEY (parent_proposal_id) REFERENCES proposals(id)` (no `ON DELETE` clause; the BEFORE DELETE trigger below handles cleanup).
- **ADD** column `parent_proposal_followup_index INT NULL`.
- **ADD** partial B-tree index `ix_studies_parent_proposal_id ON studies (parent_proposal_id) WHERE parent_proposal_id IS NOT NULL`.
- **ADD** CHECK constraint `studies_parent_proposal_pair_check`: `(parent_proposal_id IS NULL AND parent_proposal_followup_index IS NULL) OR (parent_proposal_id IS NOT NULL AND parent_proposal_followup_index IS NOT NULL AND parent_proposal_followup_index >= 0)`.
- **ADD** trigger + trigger function:
  ```sql
  CREATE OR REPLACE FUNCTION fn_clear_studies_parent_proposal_on_proposal_delete()
  RETURNS TRIGGER AS $$
  BEGIN
    UPDATE studies
       SET parent_proposal_id = NULL,
           parent_proposal_followup_index = NULL
     WHERE parent_proposal_id = OLD.id;
    RETURN OLD;
  END;
  $$ LANGUAGE plpgsql;

  CREATE TRIGGER trg_clear_studies_parent_proposal_on_proposal_delete
    BEFORE DELETE ON proposals
    FOR EACH ROW
    EXECUTE FUNCTION fn_clear_studies_parent_proposal_on_proposal_delete();
  ```
  Migration `downgrade()` drops the trigger then the function.
- ORM mapping additions in `backend/app/db/models/study.py`:
  ```python
  parent_proposal_id: Mapped[str | None] = mapped_column(
      String(36), ForeignKey("proposals.id"), nullable=True
  )
  parent_proposal_followup_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
  ```

### Required invariants

- `studies.parent_proposal_id` and `studies.parent_proposal_followup_index` are **set together or NULL together** (DB CHECK constraint enforced).
- `studies.parent_proposal_id` is allowed to reference a proposal whose `status` is anything in `{pending, pr_opened, pr_merged, rejected}` — the operator may chain a followup off any proposal, including rejected ones. The `BEFORE DELETE ON proposals` trigger (FR-5) handles the hard-delete edge case atomically; soft-delete is not currently used on proposals.
- `studies.parent_proposal_followup_index` is **not validated against the live digest array length after creation** — it captures intent at create time. If the digest is later regenerated and shrinks, the index may become stale; this is acceptable (lineage data, not a live pointer).
- A study row MAY have **both** `parent_study_id` (from auto-followup chain) AND `parent_proposal_id` (from LLM-followup click) set simultaneously. The two tracks are independent.
- `digests.suggested_followups` is a JSONB array; each element is a JSON object with at least `kind` ∈ {`narrow`, `widen`, `text`} and `rationale: string`. `search_space` is a JSON object for `narrow`/`widen` and `null` for `text`. Length cap: 5 (enforced by the LLM schema; not enforced by a CHECK constraint — defensive truncation in the worker).

### State transitions

No new states. The existing `study.status` lifecycle (`queued → running → {completed | cancelled | failed}`) is unchanged. The existing `proposal.status` lifecycle (`pending → {pr_opened, rejected}`, `pr_opened → pr_merged`) is unchanged.

### Idempotency/replay behavior

- `POST /api/v1/studies` with `body.parent` set is **not idempotent** — calling it twice creates two studies with the same parent lineage. This matches the existing endpoint contract (no `Idempotency-Key` header in MVP1).
- The UI prevents the operator from double-clicking via React Hook Form's `isSubmitting` state (existing behavior in the create-study modal).
- The digest worker (FR-4 validator) is idempotent against the existing digest UNIQUE-per-study constraint (`backend/app/db/models/digest.py:38`) — re-running the worker after a downgrade-and-fix never produces duplicate downgrade WARN events because the per-study digest is written once.

## 10) Security, privacy, and compliance

- **Threats:**
  1. **LLM-emitted `search_space` causes runaway trial count.** Mitigation: FR-4 validator runs `SearchSpace.model_validate()` which enforces the existing 10⁶ cardinality cap (`backend/app/domain/study/search_space.py:111-118`). Items that exceed the cap downgrade to `text` — never persist as `narrow`/`widen`.
  2. **LLM-emitted `search_space` references parameters not declared by the template.** Mitigation: The downstream `POST /api/v1/studies` runs the existing `validate_against_template()` check (`backend/app/api/v1/studies.py:218-227`) on submit, surfacing `SEARCH_SPACE_UNKNOWN_PARAM` / `SEARCH_SPACE_MISSING_DECLARED_PARAM` at 400. The pre-fill modal exposes this to the operator before they submit.
  3. **Stale `parent.followup_index` after digest regeneration.** Mitigation: FR-11 validates `followup_index < len(digest.suggested_followups)` at submit time. Stale indices produce 422.
  4. **Cross-proposal lineage leak in metadata.** N/A in MVP1 (single-tenant). For MVP4: `parent_proposal_id` is tenant-scoped because both `studies` and `proposals` will carry `tenant_id` — the new FK does not bridge tenants.
  5. **LLM hallucinates `parent_proposal_id` or `followup_index` content into the rationale.** Mitigation: rationale is operator-facing prose only; the actionable data is the `search_space` field which the validator enforces. The "Run this followup" button's payload is sourced from the proposal-detail API response, never from the rationale text.
- **Controls:**
  - Existing digest-worker controls preserved: per-study advisory lock (`backend/workers/digest.py:219-244`), capability check (`backend/workers/digest.py:517-540`), daily-budget guard (`backend/workers/digest.py:554-578`), persist-first then record-cost ordering.
  - No new secrets introduced.
  - No new external services called.
- **Secrets/key handling:** N/A — reuses existing `OPENAI_API_KEY` from `Settings` (mounted-file pattern per CLAUDE.md Absolute Rule #2).
- **Auditability:** §6 catalogs the three forthcoming MVP2 audit events. No `audit_log` table in MVP1.
- **Data retention/deletion/export impact:**
  - Hard-deleting a parent proposal triggers `trg_clear_studies_parent_proposal_on_proposal_delete` (FR-5) which sets BOTH `parent_proposal_id` AND `parent_proposal_followup_index` to NULL on every descendant study row, preserving the pair CHECK invariant. The lineage information is lost; descendant studies remain intact.
  - The new columns and JSONB payload are covered by the existing `chore_e2e_test_rows_isolation` test-only cleanup endpoint (`DELETE /api/v1/_test/digests/{id}`) via the same hard-delete path — no change required.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** The followup cards live inside the existing `SuggestedFollowupsPanel` on `/proposals/[id]` — same location, same card slot. No new routes, no new nav links. The "Run this followup" button opens the existing `<CreateStudyModal>` overlay (no navigation away from the proposal page).
- **Labeling taxonomy:**
  - Panel title: **"Suggested follow-ups"** (unchanged from today).
  - Per-card kind labels: **"Narrow"** (badge, `narrow`), **"Widen"** (badge, `widen`), **"Suggestion"** (badge, `text`). Matches operator mental model: "narrow"/"widen" come from the search-space-tuning vocabulary the operator already uses; "Suggestion" reads naturally for free-form text.
  - Primary action button: **"Run this followup"** (replaces the dead "Create study from this hypothesis" button — same intent, accurate naming).
  - Collapse toggle: **"Show search space"** (when collapsed) / **"Hide search space"** (when expanded).
- **Content hierarchy:** Each card renders top-to-bottom: kind badge + rationale text → "Show search space" toggle (collapsed by default) → primary "Run this followup" button (right-aligned). The card is primary; the search-space detail is progressive disclosure (most operators trust the rationale + just click Run).
- **Progressive disclosure:** Search-space JSON / diff is hidden by default. Operator expands to scrutinize bounds before committing. The diff renderer reuses the row primitive from `feat_create_study_search_space_builder` (`ui/src/components/studies/search-space-builder/`) where feasible; falls back to a syntax-highlighted JSON viewer if the row primitive doesn't compose cleanly (story-time decision).
- **Relationship to existing pages:** Extends the proposal-detail page. The followups panel was already there (current bullet rendering); this spec swaps the rendering for kind-aware cards but keeps the panel container.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---------|-------------------|---------|-----------|
| `Narrow` kind badge | (new glossary key `proposal.followup_kind_narrow`) "The study's winning configuration sits in a sub-region of the prior search space. This followup re-runs with a tighter range to confirm." | hover | top |
| `Widen` kind badge | (new glossary key `proposal.followup_kind_widen`) "The winning configuration hit an edge of the prior search space. This followup re-runs with a broader range to find a possibly-better setting." | hover | top |
| `Suggestion` kind badge | (new glossary key `proposal.followup_kind_text`) "A free-form suggestion from the LLM. Needs operator interpretation — no auto-prefill available." | hover | top |
| `Run this followup` button | (new glossary key `proposal.followup_run_button`) "Opens the create-study wizard pre-filled with this followup's settings. You can review and edit before submitting." | hover | top |
| `Show search space` toggle | (new glossary key `proposal.followup_search_space_diff`) "Compare this followup's proposed search space against the parent study's." | hover | top |
| Existing panel title `Suggested follow-ups` | (existing glossary key `proposal.suggested_followups`, copy unchanged: "LLM-generated next-study hypotheses based on this study's parameter-importance pattern. Click to seed a new study.") | hover | top |

Tooltip placement uses the existing `<InfoTooltip glossaryKey="...">` primitive (see `ui/src/components/common/info-tooltip.tsx`, already imported in `suggested-followups-panel.tsx`).

### Primary flows

1. **Run a `narrow` followup (happy path).**
   Operator on `/proposals/<pid>` → scrolls to "Suggested follow-ups" → sees a card with a `Narrow` badge + rationale → clicks "Show search space" → sees the proposed bounds diff'd against the parent's → clicks "Run this followup" → `CreateStudyModal` opens with `cluster_id`, `target`, `template_id`, `query_set_id`, `judgment_list_id`, `objective`, `config` pre-filled from the parent study, and `search_space_text` pre-filled with the LLM's JSON. `name` defaults to `"<parent name> — followup #1 (narrow)"`. Operator reviews the search space, clicks Submit. `POST /api/v1/studies` includes `parent: {proposal_id: <pid>, followup_index: 0}`. Returns 201 with `StudyDetail`. Operator is navigated to `/studies/<new study id>`. The new study row carries `parent_proposal_id=<pid>` + `parent_proposal_followup_index=0`.
2. **Run a `widen` followup.** Identical to (1) with `Widen` badge + broader bounds.
3. **Read a `text` followup.** Operator sees a card with `Suggestion` badge + rationale text. NO button. Operator manually opens the create-study modal (existing "+ New study" entrypoint) and authors the experiment themselves. No lineage recorded.

### Edge/error flows

- **LLM emits an invalid `search_space` (cardinality > 10⁶, bad bounds, etc.).** The digest worker's validator (FR-4) downgrades the item to `kind: "text"` with `rationale: "[validation failed: <truncated error>] " + original_rationale`. Operator sees the item as a `Suggestion` card with the validation prefix making the failure visible. No data lost.
- **Operator submits the pre-filled form but the parent proposal was hard-deleted between page load and submit.** `POST /api/v1/studies` returns 404 `PROPOSAL_NOT_FOUND`. The modal surfaces the error; operator can either remove the `parent` payload (manual workaround — refresh the proposal page is the user-visible recovery) or abandon.
- **Operator submits the pre-filled form but the parent proposal's digest was regenerated (operator ran the runbook escape hatch `DELETE FROM digests` + re-enqueue between page load and submit) and the new digest has fewer followups.** `POST /api/v1/studies` returns 422 `FOLLOWUP_INDEX_OUT_OF_RANGE`. Same recovery as above.
- **LLM emits 5 valid `narrow`/`widen` items AND the worker prepends a drift followup.** Per FR-8, drift followups are synthesized post-LLM as `kind: "text"` and prepended; the combined list is then truncated to 5 (matching the existing worker contract at `backend/workers/digest.py:774-775`). The dropped tail (an LLM-emitted item, never a drift item) is logged at INFO; no error.
- **Capability-degraded digest (structured output unavailable).** The worker writes `suggested_followups=[]` (preserved from today — see `backend/workers/digest.py:757`). UI panel hides itself (existing `if (followups.length === 0) return null` at `suggested-followups-panel.tsx:13`).
- **Zero-trials digest.** The worker writes the `_FAILURE_NARRATIVE` digest with `suggested_followups=[]` (preserved — see `backend/workers/digest.py:339-369`). UI panel hides itself.
- **Operator deletes the parent proposal AFTER spawning a followup study.** The `BEFORE DELETE ON proposals` trigger (FR-5) NULLs both `parent_proposal_id` and `parent_proposal_followup_index` on every descendant study row, then the delete proceeds. The study itself is untouched. Lineage is lost; no other impact.

## 12) Given/When/Then acceptance criteria

### AC-1: LLM returns three valid kinds; UI renders kind-discriminated cards
- Given a digest with `suggested_followups` containing one `narrow`, one `widen`, and one `text` item
- When the operator loads `/proposals/{proposal_id}`
- Then the panel shows three cards in order with the matching badge ("Narrow", "Widen", "Suggestion"); the `narrow` and `widen` cards each show a "Run this followup" button; the `text` card shows no button.
- Example values:
  - Input: a digest fixture with the three-item payload from §8.3.
  - Expected: three cards rendered with `data-testid="followup-0-card"` (Narrow), `followup-1-card` (Widen), `followup-2-card` (Suggestion); `followup-0-run` and `followup-1-run` buttons present; no `followup-2-run`.

### AC-2: "Run this followup" pre-fills the modal with parent + LLM payload
- Given a `narrow` followup at index 0 on proposal `P` with parent study `S` (cluster `C`, target `T`, template `Tpl`, query set `QS`, judgment list `JL`, `objective={metric: "ndcg", k: 10, direction: "maximize"}`, `config={max_trials: 200, parallelism: 4, sampler: "tpe", pruner: "median"}`) and `search_space={params: {title_boost: {type: "float", low: 1.8, high: 2.4}}}`
- When the operator clicks "Run this followup" on the card
- Then the `CreateStudyModal` opens with `cluster_id=C.id`, `target=T`, `template_id=Tpl.id`, `query_set_id=QS.id`, `judgment_list_id=JL.id`, the objective fields pre-set to ndcg/10/maximize, the stop-condition fields pre-set to 200/—/4/tpe/median, the search-space textarea pre-loaded with the LLM's JSON (formatted), and `name="<S.name> — followup #1 (narrow)"`.

### AC-3: Submitting the pre-filled form persists lineage on the new study
- Given the modal pre-filled per AC-2
- When the operator clicks Submit
- Then `POST /api/v1/studies` is called with `body.parent = {proposal_id: P.id, followup_index: 0}` and returns 201 with a `StudyDetail`. The new `studies` row has `parent_proposal_id=P.id` AND `parent_proposal_followup_index=0` AND `parent_study_id=NULL` (this is an LLM-followup, NOT an auto-chain).

### AC-4: Validator downgrades a malformed `narrow` item to `text`
- Given the LLM emits a `narrow` item whose `search_space` has cardinality > 10⁶ (e.g., one float param plus 11 floats — `100^12 > 10^6`)
- When the digest worker validates + persists
- Then the persisted digest's `suggested_followups[i]` has `kind="text"`, `rationale` starts with `"[validation failed: search-space cardinality estimate exceeds 10^6"`, and `search_space` is `null`. A `digest_followup_validation_downgraded` WARN event is logged with `study_id`, `proposal_id`, `original_kind="narrow"`.

### AC-5: Backward-compat read of a legacy `list[str]` row (defensive)
- Given a manually crafted legacy `digests.suggested_followups` row whose JSONB payload is a JSON array of strings (e.g., `["item one", "item two"]` — should not occur post-backfill but exercised defensively)
- When `GET /api/v1/studies/{id}/digest` is called
- Then the response's `suggested_followups` is `[{kind: "text", rationale: "item one", search_space: null}, {kind: "text", rationale: "item two", search_space: null}]`.

### AC-6: Column-type migration round-trips cleanly
- Given a DB with one pre-migration `digests` row whose `suggested_followups = ARRAY['Try widening title_boost', 'Add tie_breaker']`
- When `alembic upgrade head` runs (applying the new migration)
- Then the row's `suggested_followups` is the JSONB array `[{"kind": "text", "rationale": "Try widening title_boost", "search_space": null}, {"kind": "text", "rationale": "Add tie_breaker", "search_space": null}]`.
- When `alembic downgrade -1` runs immediately after
- Then the row's `suggested_followups` is the text array `['Try widening title_boost', 'Add tie_breaker']` (rationale-only; lossy by design).
- When `alembic upgrade head` runs again
- Then the JSONB shape from the first step is restored.

### AC-7: CHECK constraint blocks half-set lineage
- Given an attempt to INSERT a `studies` row with `parent_proposal_id` set but `parent_proposal_followup_index = NULL`
- When the INSERT executes
- Then the DB raises a CHECK violation on `studies_parent_proposal_pair_check`. (Symmetrically: index set + proposal_id NULL also fails.)

### AC-8: 404 PROPOSAL_NOT_FOUND on unknown parent proposal
- Given a `POST /api/v1/studies` request with `parent: {proposal_id: "<non-existent UUID>", followup_index: 0}`
- When the request is processed
- Then the response is HTTP 404 with body `{"detail": {"error_code": "PROPOSAL_NOT_FOUND", "message": "proposal <UUID> not found", "retryable": false}}`.

### AC-8b: 404 DIGEST_NOT_FOUND when the parent proposal has no digest yet
- Given a proposal `P` that exists but whose digest worker hasn't completed (no `digests` row for `P.study_id`), and a `POST /api/v1/studies` request with `parent: {proposal_id: P.id, followup_index: 0}`
- When the request is processed
- Then the response is HTTP 404 with body `{"detail": {"error_code": "DIGEST_NOT_FOUND", "message": "proposal <P.id> has no digest yet", "retryable": true}}`. (Note: `retryable=true` because the operator can wait for the digest worker to finish and resubmit — distinct from `PROPOSAL_NOT_FOUND` which is `retryable=false`.)

### AC-9: 422 FOLLOWUP_INDEX_OUT_OF_RANGE on stale index
- Given proposal `P` whose digest has 3 followups, and a `POST /api/v1/studies` request with `parent: {proposal_id: P.id, followup_index: 7}`
- When the request is processed
- Then the response is HTTP 422 with body `{"detail": {"error_code": "FOLLOWUP_INDEX_OUT_OF_RANGE", "message": "parent.followup_index=7 exceeds the digest's suggested_followups length (3) for proposal <P.id>", "retryable": false}}`.

### AC-10: Dead `?hypothesis=` link is gone
- Given the `SuggestedFollowupsPanel` rendered on `/proposals/<pid>`
- When the test queries the DOM
- Then no `<a>` or `<Link>` element has an `href` matching `/studies?hypothesis=`. (Lint/snapshot guard against regression.)

### AC-11: BEFORE DELETE trigger detaches lineage without destroying the child
- Given a study `Sc` with `parent_proposal_id = P.id` and `parent_proposal_followup_index = 0`, and the parent proposal `P` exists
- When `P` is hard-deleted (via the test-only delete endpoint or a manual DB delete)
- Then the `BEFORE DELETE ON proposals` trigger (FR-5; named `trg_clear_studies_parent_proposal_on_proposal_delete`) fires and sets BOTH `Sc.parent_proposal_id = NULL` AND `Sc.parent_proposal_followup_index = NULL` in the same transaction, preserving the `studies_parent_proposal_pair_check` invariant.
- Expected end state: `Sc.parent_proposal_id IS NULL AND Sc.parent_proposal_followup_index IS NULL`, `Sc` row otherwise unchanged. `P` is gone.
- Note: This explicitly **does not** use `ON DELETE SET NULL` on the FK clause, because that would clear only `parent_proposal_id` and immediately violate the pair CHECK (per GPT-5.5 cycle-1 F1).

### AC-12: A study can have both lineage tracks set
- Given an LLM-followup study `Sc` created from proposal `P` (so `Sc.parent_proposal_id = P.id`) that is ALSO an auto-chain descendant of study `Sp` (so `Sc.parent_study_id = Sp.id`)
- When `Sc` is read via `GET /api/v1/studies/{id}`
- Then `Sc.parent_study_id = Sp.id` (exposed via `StudyDetail.parent_study_id`, existing field at `backend/app/api/v1/schemas.py:659`). The `parent_proposal_id` + `parent_proposal_followup_index` columns are NOT currently exposed on `StudyDetail` (see §19 D-5 decision); they're queryable directly via raw SQL or via a future endpoint extension.

## 13) Non-functional requirements

- **Performance:**
  - The new validator (FR-4) runs in O(n) where n = number of followups (≤ 5) per digest call. Negligible cost vs the LLM call.
  - The new FK + partial index on `studies(parent_proposal_id) WHERE parent_proposal_id IS NOT NULL` is bounded by the proposal cardinality — in MVP1, expect ≤ 10⁴ proposals lifetime per laptop install. Index is partial so it only contains followup studies (a small fraction).
  - `POST /api/v1/studies` with `body.parent` adds at most 2 extra SELECTs (proposal lookup + digest lookup). p95 stays under 500ms.
  - The column-type migration on `digests` runs an `ALTER TABLE ... USING` which rewrites the table. For MVP1 (single-tenant laptop, dozens of digest rows), this completes in well under 1 second. For production (MVP3+ deployment with managed Postgres), the migration is documented as table-rewrite in the release-notes runbook; downtime is expected during deploy. Production scale ≤ 10⁵ rows keeps it under a minute.
- **Reliability:** No new SLO. The digest worker continues to be best-effort with the existing retry / advisory-lock / idempotency-guard infrastructure.
- **Operability:**
  - New structlog event types: `digest_followup_validation_downgraded` (WARN). Existing events preserved.
  - New error codes are listed in §8.5; mirror into `docs/01_architecture/api-conventions.md` error code catalog at doc-update time.
  - No new metrics in MVP1. (MVP2+ Langfuse / SigNoz catalog gains the three audit events from §6.)
- **Accessibility/usability:**
  - Per-card kind badges have `aria-label` matching the badge text ("Narrow", "Widen", "Suggestion").
  - "Run this followup" button has `aria-label="Run this followup — opens the create study form pre-filled with these settings"` so screen readers understand the action without seeing the surrounding card context.
  - "Show search space" toggle uses standard `<details>`/`<summary>` semantics or shadcn `<Collapsible>` (already in the repo) with proper `aria-expanded`.
  - Keyboard nav: cards focusable in DOM order; Enter on "Run this followup" opens the modal; Esc closes the modal (preserves existing modal behavior).

## 14) Test strategy requirements (spec-level)

- **Unit tests (`backend/tests/unit/`):**
  - `backend/tests/unit/domain/study/test_followups.py` (new file): Pydantic discriminated-union validation for each kind; round-trip serialization; rejection of unknown `kind` values; rejection of `narrow`/`widen` with null `search_space`; rejection of `text` with non-null `search_space`.
  - `backend/tests/unit/domain/study/test_followups_backcompat.py` (new file): legacy `list[str]` wrapping into the new shape.
  - `backend/tests/unit/workers/test_digest_followup_validation.py` (new file): given a mocked LLM response with one valid `narrow`, one invalid `narrow` (cardinality > 10⁶), and one `text` → the worker persists the valid + downgrades the invalid + preserves the `text`. Verifies the structlog WARN event.
- **Integration tests (`backend/tests/integration/`):**
  - `backend/tests/integration/test_digest_followup_roundtrip.py` (new file): full digest worker round-trip with the LLM stub returning structured followups; assert the persisted JSONB shape; assert `GET /api/v1/studies/{id}/digest` returns the structured shape.
  - `backend/tests/integration/test_studies_with_parent_followup.py` (new file): `POST /api/v1/studies` with `body.parent` set against a fixture proposal with a real digest; assert the persisted `parent_proposal_id` + `parent_proposal_followup_index`. Cover all three error paths explicitly (per GPT-5.5 cycle-2 F6): (a) unknown `proposal_id` → 404 `PROPOSAL_NOT_FOUND`, (b) existing proposal without a digest → 404 `DIGEST_NOT_FOUND`, (c) stale `followup_index` ≥ digest length → 422 `FOLLOWUP_INDEX_OUT_OF_RANGE`.
  - `backend/tests/integration/test_digest_followups_migration.py` (new file): pre-migration fixture with BOTH a populated `ARRAY(Text)` row AND an empty `ARRAY[]::TEXT[]` row (exercises both COALESCE branches per FR-6); `alembic upgrade head`; assert JSONB backfill correctness on both rows; `alembic downgrade -1`; assert text-array round-trip (lossy).
  - `backend/tests/integration/test_studies_parent_proposal_check.py` (new file): half-set pair INSERT fails on the CHECK constraint; negative-index INSERT fails on the CHECK constraint (per GPT-5.5 cycle-1 F4).
  - `backend/tests/integration/test_studies_parent_proposal_on_delete.py` (new file, per GPT-5.5 cycle-1 F9): create a proposal-linked study; hard-delete the parent proposal; assert the child study row remains; assert BOTH `parent_proposal_id` IS NULL AND `parent_proposal_followup_index` IS NULL (trigger fired correctly).
- **Contract tests (`backend/tests/contract/`):**
  - `backend/tests/contract/test_digest_response_shape.py` (extend existing or add new): assert `DigestResponse.suggested_followups` is `list[FollowupItem]` (discriminated union); assert each kind round-trips through OpenAPI.
  - `backend/tests/contract/test_proposal_detail_shape.py` (extend existing): same for `_DigestEmbed.suggested_followups`.
  - `backend/tests/contract/test_create_study_parent.py` (new file): assert `CreateStudyRequest.parent` is optional; assert the three new error codes appear in the OpenAPI error response schema.
- **E2E tests (`ui/tests/e2e/`):**
  - One happy-path Playwright spec (`ui/tests/e2e/followup_run.spec.ts`, new file): seed a cluster + template + query set + judgment list + parent study + proposal + digest with one `narrow` followup via API helpers; navigate to `/proposals/<pid>`; click "Run this followup"; assert the create-study modal opens with the pre-filled fields; submit; assert navigation to `/studies/<new id>` and the new study row's lineage columns.
  - **Real-backend test** (no `page.route()` mocking — per CLAUDE.md E2E rule).

## 15) Documentation update requirements

- `docs/01_architecture/data-model.md` — extend the `studies` table section to document `parent_proposal_id` + `parent_proposal_followup_index` (alongside the existing `parent_study_id` note). Update the `digests` table section to document `suggested_followups` as JSONB with the discriminated-union shape.
- `docs/01_architecture/api-conventions.md` — add `PROPOSAL_NOT_FOUND`, `DIGEST_NOT_FOUND`, `FOLLOWUP_INDEX_OUT_OF_RANGE` to the error code catalog.
- `docs/01_architecture/llm-orchestration.md` — describe the new digest LLM output shape (discriminated union) and the worker's downgrade behavior.
- `docs/02_product/planned_features/feat_digest_executable_followups/` — this spec lives here. Deferred tiers were split to standalone sibling folders on 2026-05-24: Tier B → [`../feat_digest_executable_followups_swap_template/`](../feat_digest_executable_followups_swap_template/idea.md); Tier C → [`../backlog_feat_digest_template_edit_followups/`](../backlog_feat_digest_template_edit_followups/idea.md).
- `docs/03_runbooks/` — add or extend a digest-debugging runbook entry: "if all followups appear as `text` items, check the worker logs for `digest_followup_validation_downgraded` to see whether the LLM is emitting invalid `search_space` payloads."
- `docs/04_security/` — N/A (no new secret or data-flow surface).
- `docs/05_quality/testing.md` — no change required; new test files follow the existing layer convention.
- `state.md` — update active-work / queued sections to mark `feat_digest_executable_followups` as in-progress when the spec gets approval.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. MVP1 single-tenant; ship behind no flag.
- **Migration/backfill expectations:**
  - The `digests.suggested_followups` column-type migration runs in-place at `alembic upgrade head` time. For MVP1 (dozens of rows on a laptop), this is sub-second.
  - The `studies.parent_proposal_id` + `parent_proposal_followup_index` column-add is purely additive (both NULL by default for existing rows). No backfill.
  - Round-trip verified per CLAUDE.md Absolute Rule #5 (FR-6 + AC-6).
- **Operational readiness gates:** None new. The digest worker's existing operability (budget guard, advisory lock, capability check) is unchanged.
- **Release gate:**
  - All ACs pass in CI (unit + integration + contract + E2E layers).
  - Round-trip migration verified.
  - `make lint`, `make typecheck`, `pnpm lint`, `pnpm typecheck`, `pnpm build` all green.
  - GPT-5.5 cross-model review on the spec and the implementation plan complete (per CLAUDE.md cross-model policy).
  - Gemini Code Assist findings on the PR adjudicated per CLAUDE.md.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks (to be assigned by impl-plan) | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-4 | Worker schema change story | `backend/tests/contract/test_digest_response_shape.py` | `docs/01_architecture/llm-orchestration.md` |
| FR-2 | AC-5 | Backward-compat read-path adapter story | `backend/tests/unit/domain/study/test_followups_backcompat.py` | — |
| FR-3 | AC-1, AC-4 | Domain models story | `backend/tests/unit/domain/study/test_followups.py` | — |
| FR-4 | AC-4 | Validator + downgrade story | `backend/tests/unit/workers/test_digest_followup_validation.py`, `backend/tests/integration/test_digest_followup_roundtrip.py` | — |
| FR-5 | AC-3, AC-7, AC-11, AC-12 | studies-column migration story + ORM update story + BEFORE DELETE trigger story | `backend/tests/integration/test_studies_parent_proposal_check.py`, `backend/tests/integration/test_studies_with_parent_followup.py`, `backend/tests/integration/test_studies_parent_proposal_on_delete.py` | `docs/01_architecture/data-model.md` |
| FR-6 | AC-6 | digests-column-type migration story | `backend/tests/integration/test_digest_followups_migration.py` | `docs/01_architecture/data-model.md` |
| FR-7 | AC-1, AC-5 | Schema wire-shape story | `backend/tests/contract/test_digest_response_shape.py`, `backend/tests/contract/test_proposal_detail_shape.py` | — |
| FR-8 | AC-1, AC-4 | LLM prompt update story | (covered via worker integration test) | `prompts/digest_narrative.system.md`, `prompts/digest_narrative.user.jinja` |
| FR-9 | AC-1, AC-10 | UI panel rewrite story | `ui/src/__tests__/components/proposals/suggested-followups-panel.test.tsx` | — |
| FR-10 | AC-2 | UI prefill flow story | `ui/tests/e2e/followup_run.spec.ts` | — |
| FR-11 | AC-3, AC-8, AC-8b, AC-9 | API `parent` body + validation story | `backend/tests/contract/test_create_study_parent.py`, `backend/tests/integration/test_studies_with_parent_followup.py` | `docs/01_architecture/api-conventions.md` |
| FR-12 | AC-10 | Dead-button removal story (bundled into FR-9 PR) | (snapshot/lint assertion in FR-9 test) | — |
| FR-13 | AC-1 (tooltip rendering observable in panel test) | Glossary additions story | `ui/src/__tests__/lib/glossary.test.ts` | — |

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1 through AC-12) pass in CI.
- [ ] All test layers (unit/integration/contract/e2e) are green.
- [ ] Documentation updates across docs/01–05 are merged (§15).
- [ ] Rollout gates from §16 are satisfied.
- [ ] Cross-model review (GPT-5.5) on this spec and the forthcoming implementation plan completed and adjudicated.
- [x] Deferred-phase tracking: Phase 2 (Tier B `swap_template`) at sibling [`../feat_digest_executable_followups_swap_template/`](../feat_digest_executable_followups_swap_template/idea.md); Phase 3 (Tier C `edit_template`) at sibling [`../backlog_feat_digest_template_edit_followups/`](../backlog_feat_digest_template_edit_followups/idea.md). Both split out from `phase2_idea.md` / `phase3_idea.md` on 2026-05-24 per `impl-execute` Step 8.6 option (a).
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

- **None.** Auto mode operated under §19 D-1 through D-11 below; all forks were decided with the most defensible default and documented.

### Decision log

- **D-1 — 2026-05-23 — `kind` discriminator values are `narrow | widen | text` (not `expand | shrink | hint` or other near-synonyms).** Rationale: "narrow" and "widen" are the operator's existing vocabulary from search-space tuning; "text" is the most neutral name for the free-form fallback. The idea proposed these literals and the spec preserves them verbatim.
- **D-2 — 2026-05-23 — Column-type change (option a) over dual-column dual-write (option b).** Rationale: idea locked option (a) at preflight time. MVP1 has no production data to preserve; single in-place migration with USING-clause backfill is cleaner than carrying a deprecated column indefinitely.
- **D-3 — 2026-05-23 — `studies_parent_proposal_pair_check` is a regular CHECK constraint, not a `DEFERRABLE` one.** Rationale: simpler. **Superseded by D-13** (cycle-1 F1) — the hard-delete edge case is now handled by an explicit `BEFORE DELETE ON proposals` trigger, NOT by deferring the CHECK or using `ON DELETE SET NULL`. The CHECK constraint can remain a regular (non-deferrable) one because the trigger fires first and atomically resolves the lineage pair.
- **D-4 — 2026-05-23 — New API endpoint NOT added.** Extend `POST /api/v1/studies` with optional `parent` body field. Rationale: avoids duplicating the existing validation chain (search_space, FK, judgment overlap probe); the operator's mental model is already "create study from a pre-filled form."
- **D-5 — 2026-05-23 — `parent_proposal_id` + `parent_proposal_followup_index` are NOT exposed on `StudyDetail` in MVP1.** Rationale: minimum viable surface. Lineage is queryable in the DB and visible via the upcoming `auto-followup-chain-panel` evolution (a future concern). Exposing on `StudyDetail` is a small additive change that can land in a follow-up PR if a UI surface needs it.
- **D-6 — 2026-05-23 — The default study `name` is `"<parent name> — followup #<index+1> (<kind>)"`.** Rationale: discoverable + descriptive. The operator can override.
- **D-7 — 2026-05-23 — The drift followup synthesized by the worker becomes a `kind: "text"` item (not `kind: "narrow"`).** Rationale: drift is operator judgment ("re-add the dropped params or treat as stale"), not a deterministic search-space narrowing. Preserves the existing semantics from `backend/workers/digest.py:762-767`.
- **D-8 — 2026-05-23 — Capability-degraded path persists `suggested_followups=[]` (preserved from today).** Rationale: when the LLM endpoint can't do structured output, we don't have a kind discriminator to assign. Returning empty is consistent with the existing AC-11 path in `feat_digest_proposal`.
- **D-9 — 2026-05-23 — Validation downgrade preserves the rationale prefix `[validation failed: <error>]`.** Rationale: makes the failure visible to the operator without aborting the digest. The 200-char truncation cap keeps the rationale display-friendly.
- **D-10 — 2026-05-23 — `parent.followup_index` upper bound IS validated at submit time against the live digest array length.** Rationale: catches stale-pointer cases (digest regenerated between page load and submit). The lower bound (`>= 0`) is Pydantic-enforced via `Field(ge=0)`.
- **D-11 — 2026-05-23 — `parent.proposal_id` does NOT need to reference a proposal whose `status="pending"`.** Rationale: operators may chain followups off rejected proposals (intent: "this idea was rejected, but maybe a narrower variant works"). The API does not enforce a status check.
- **D-12 — 2026-05-23 — No dropdown ever exposes `FollowupItem.kind` to the operator as a selectable value.** Rationale: the LLM is the producer; the operator is the consumer. There is no UI surface that asks the operator to pick a kind, so no §8.4 frontend-dropdown drift risk.
- **D-13 — 2026-05-23 (cycle-1 F1 accept) — `BEFORE DELETE` trigger replaces `ON DELETE SET NULL`.** Rationale: `ON DELETE SET NULL` would clear only `parent_proposal_id`, immediately violating the `studies_parent_proposal_pair_check` invariant. The trigger atomically NULLs both columns. Trigger lives in the same migration as the columns; downgrade drops it.
- **D-14 — 2026-05-23 (cycle-1 F2 accept) — JSONB type-change migration uses `COALESCE(... , '[]'::jsonb)` and DROP DEFAULT / SET DEFAULT bracketing.** Rationale: naive `jsonb_agg(... FROM unnest(empty_array))` returns NULL, violating NOT NULL. COALESCE ensures empty arrays map to `'[]'::jsonb`. DROP DEFAULT before TYPE change is required because the old `ARRAY[]::TEXT[]` default's type can't be auto-cast to JSONB.
- **D-15 — 2026-05-23 (cycle-1 F3 accept) — Pydantic validation uses `TypeAdapter` over the discriminated-union alias, not `.model_validate()`.** Rationale: `FollowupItem = Annotated[Union[...], Field(discriminator="kind")]` is a type alias, not a `BaseModel`. The Pydantic v2 idiom for validating discriminated-union aliases is `TypeAdapter(FollowupItem).validate_python(...)`.
- **D-16 — 2026-05-23 (cycle-1 F4 accept) — Pair CHECK also enforces `parent_proposal_followup_index >= 0`.** Rationale: cheap defensive add. API enforces `Field(ge=0)`; the DB CHECK catches direct writes that bypass the API (migrations, manual fixes, tests).
- **D-17 — 2026-05-23 (cycle-1 F5 reject) — Response example keeps the literal `generated_by: "openai:gpt-4o-2024-08-06"`.** Counter-evidence: CLAUDE.md Absolute Rule #8 explicitly mandates "All persisted artifacts (judgments, digests) capture the exact model identifier (`openai:gpt-4o-2024-08-06`) for lineage." `generated_by` is **persisted lineage data**, not a hardcoded model name in service code. The Rule #8 forbidden pattern is `client.chat.completions.create(model="gpt-4o", ...)` in service code — that does not occur in this spec; all service-side model references go through `settings.openai_model` (already established by `feat_digest_proposal`). The response example shows what an operator would actually see on the wire, and using a real model identifier (matching the Rule #8 canonical example) is more useful than a placeholder.
- **D-18 — 2026-05-23 (cycle-1 F6 accept) — UI fetches `GET /api/v1/studies/{parent_study_id}` lazily on "Run this followup" click rather than extending `_StudySummary` embed.** Rationale: the existing `_StudySummary` only has 7 fields and is missing `cluster_id`, `target`, `template_id`, `objective`, `config` — required for prefill. The lazy fetch leverages the existing endpoint + cache (TanStack Query), avoids bloating every proposal-detail response with parent-study data that's only needed on click, and keeps the change surface minimal (no new schema changes on the proposal endpoint).
- **D-19 — 2026-05-23 (cycle-1 F7 accept) — `CreateStudyModal` must `form.reset(initialValues)` on `[open, initialValues]` change.** Rationale: React Hook Form's `defaultValues` apply only on initial mount; without explicit `reset`, the second followup click in one page session would render stale values from the first. A keyed `useEffect` is the canonical fix.
- **D-20 — 2026-05-23 (cycle-1 F8 accept) — `parse_followup_list()` is contract-specified for every malformed-input shape in FR-4.** Rationale: the digest worker must never abort on a malformed followup; the parser must handle missing kind, unknown kind, non-dict elements, non-list top level, etc., with a defined behavior for each. The decision table in FR-4 is the contract.
- **D-21 — 2026-05-23 (cycle-2 F1 accept) — Migration uses PL/pgSQL helper functions, NOT inline subquery USING expressions.** Rationale: PostgreSQL rejects subqueries in `ALTER COLUMN TYPE ... USING` expressions with `ERROR: cannot use subquery in transform expression` (verified empirically against the project's local Postgres 16). The fix is migration-local helper functions (`_fn_wrap_text_array_as_jsonb_followups` on upgrade, `_fn_unwrap_jsonb_followups_as_text_array` on downgrade) that are created → used in the USING clause → dropped within the same migration body. The functions handle the empty-array case via early-return `IF arr IS NULL OR ... THEN RETURN '[]'::jsonb`, preserving the cycle-1 F2 fix.
- **D-22 — 2026-05-23 (cycle-2 F2 accept) — All `ON DELETE SET NULL` references in the spec narrative are replaced with the trigger contract.** Rationale: cycle-1 patches updated FR-5 + §9 + AC-11 + D-13 but missed §3, §9 invariants, §10 (data retention), §11 (edge flows), and D-3. Stale references would let implementers reintroduce the bug. All call sites now uniformly point at `trg_clear_studies_parent_proposal_on_proposal_delete`.
- **D-23 — 2026-05-23 (cycle-2 F3 accept) — `parse_followup_list()` signature carries `study_id` + `proposal_id` context kwargs.** Rationale: FR-4 mandates structured WARN/ERROR logs with both IDs; without context kwargs the helper has no way to populate them. Both default to `None` so read-path adapter calls (where IDs may not be loaded) still work, with the field appearing as `study_id=null` in the event payload.
- **D-24 — 2026-05-23 (cycle-2 F4 accept) — `serialize_followup_list(items)` helper required before assigning to JSONB column.** Rationale: SQLAlchemy's JSONB driver does not know how to serialize Pydantic `BaseModel` instances. The helper calls `item.model_dump(mode="json")` per item, flattening nested `SearchSpace` models to plain JSON dicts that the driver can persist. Without this step, the INSERT either crashes or stores a malformed shape.
- **D-25 — 2026-05-23 (cycle-2 F5 accept) — `parse_followup_list()` is called at EVERY response-construction site, not just the digest endpoint.** Rationale: `GET /api/v1/proposals/{id}` constructs `_DigestEmbed.suggested_followups` from the raw ORM value (`backend/app/api/v1/proposals.py:161`). Without an explicit wrapper call, defensive legacy `list[str]` rows would crash Pydantic response validation. The wrapper at every site is the single canonical guard.
- **D-26 — 2026-05-23 (cycle-2 F6 accept) — Explicit AC + integration test for `DIGEST_NOT_FOUND`.** Rationale: FR-11 introduces a distinct 404 path (proposal exists but no digest yet) that's behaviorally different from `PROPOSAL_NOT_FOUND` (`retryable=true` vs `false`). Without a dedicated AC + test, the path could regress silently.
- **D-27 — 2026-05-23 (cycle-3 F1 accept) — Capability-degraded mode suppresses BOTH LLM followups AND the drift synthesis.** Rationale: current code (`backend/workers/digest.py:757-758`) keeps the drift prepend inside the `if structured_output_enabled:` branch — `suggested_followups` stays `[]` in degraded mode regardless of `dropped_template_params`. Spec FR-1 + FR-8 now explicitly align with this code behavior (was previously ambiguous between FR-1 saying "[]" and FR-8 saying "drift preserved").
- **D-28 — 2026-05-23 (cycle-3 F2 accept) — `parse_followup_list()` decision table now covers `narrow`/`widen` items that fail validation for non-`SearchSpace` reasons.** Rationale: the cycle-1 table only specified the `SearchSpace`-cardinality-fails path. Items failing for missing rationale / missing search_space / extra forbidden fields could still raise `ValidationError` past the parser. Updated table mandates catching ALL `FollowupItemAdapter.validate_python` `ValidationError` paths and routing them through downgrade-or-drop.
- **D-29 — 2026-05-23 (cycle-3 F3 accept) — `POST /api/v1/studies` validates `parent.followup_index` against the PARSED canonical list, not raw JSONB length.** Rationale: if a defensive malformed JSONB row is wrapped by `parse_followup_list()`, dropped elements shift indices between the response (parsed) and the raw column. Validation must use the same parsed list the UI saw to guarantee lineage integrity.
