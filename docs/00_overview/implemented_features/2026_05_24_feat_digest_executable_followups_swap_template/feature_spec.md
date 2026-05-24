# Feature Specification — `swap_template` LLM-Suggested Followups (Tier B)

**Date:** 2026-05-24
**Status:** Draft
**Owners:** Eric Starr (product), Eric Starr (engineering)
**Related docs:**
- [`idea.md`](./idea.md) — origin brief (split from Phase-1 `phase2_idea.md` on 2026-05-24)
- [`docs/00_overview/implemented_features/2026_05_24_feat_digest_executable_followups/feature_spec.md`](../../../00_overview/implemented_features/2026_05_24_feat_digest_executable_followups/feature_spec.md) — Tier-A substrate this spec extends
- [`docs/01_architecture/llm-orchestration.md`](../../../01_architecture/llm-orchestration.md)
- [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md)
- Sibling (in-flight backlog): [`backlog_feat_digest_template_edit_followups`](../../../02_product/planned_features/backlog_feat_digest_template_edit_followups/idea.md) — Tier C `edit_template`

---

## 1) Purpose

- **Problem:** Tier A (shipped 2026-05-24 as PR #225) lets the LLM suggest `narrow` / `widen` / `text` followups within the **same query template**. But the LLM sometimes recognizes that a **different template entirely** is the better fit — e.g., parameter-importance is highly skewed (some declared params are dead weight), or winning trials cluster around a sub-set of params that map cleanly onto a different template's `declared_params`. Today the operator has to notice this themselves; the LLM has no structured way to say "try template X instead." The "Run this followup" substrate (`backend/app/domain/study/followups.py`, `ui/src/components/proposals/suggested-followups-panel.tsx`, the `?action=run_followup` modal prefill at `ui/src/app/proposals/[id]/page.tsx:120-184`) is in place — only the `swap_template` variant + its UI surface is missing.
- **Outcome:** The LLM emits a fourth `kind: "swap_template"` variant carrying `{rationale, template_id, search_space}` where `template_id` references a different `query_templates.id` than the parent study used. The proposal-detail UI renders the variant as an actionable card with a side-by-side `declared_params` comparison (parent template vs proposed swap target) before the operator commits. The "Run this followup" button pre-fills `template_id = <swap_target>` (not the parent's template) plus the LLM-proposed `search_space`, with disjoint params filled from the existing heuristic at `backend/app/domain/study/search_space_defaults.py`. Lineage (`studies.parent_proposal_id` + `parent_proposal_followup_index`) is reused unchanged — the cross-template hop is explicit in the data because the child study's `template_id` differs from the parent's.
- **Non-goal:** Auto-running swap-template followups without operator click (already covered for the deterministic narrow-around-winner case by `feat_auto_followup_studies`; cross-template swaps are a much larger trust surface and explicitly stay operator-mediated). LLM-driven template **edits** (Tier C — different surface, tracked at sibling [`backlog_feat_digest_template_edit_followups`](../../../02_product/planned_features/backlog_feat_digest_template_edit_followups/idea.md)). Side-by-side rendering of the **query body** itself (Jinja2 source) — out, only `declared_params` are compared. Auto-discovery of the swap-target template by the worker (the LLM picks; we don't fall back to a similarity search).

## 2) Current state audit

### Existing implementations

- `backend/app/domain/study/followups.py:80-126` — Tier-A `FollowupItem` discriminated union over `NarrowFollowup | WidenFollowup | TextFollowup`. Each is `BaseModel` with `model_config = ConfigDict(extra="forbid")` and a `Literal["narrow"|"widen"|"text"]` discriminator. `FOLLOWUP_KIND_VALUES: tuple[str, ...] = ("narrow", "widen", "text")` at line 123 is the source-of-truth tuple consumed by `scripts/ci/verify_enum_source_of_truth.sh` via the contract-test helper. `FollowupItemAdapter` and `FollowupListAdapter` (lines 125-126) are the `TypeAdapter` wrappers callers use for validation — extending the union automatically updates both adapters. This spec adds `SwapTemplateFollowup` to the union and `"swap_template"` to the tuple.
- `backend/app/domain/study/followups.py:212-310` — `parse_followup_list(raw, *, study_id, proposal_id)` defensive ingest. The seven-row decision table (docstring + impl) routes legacy `list[str]`, valid dicts via `FollowupItemAdapter.validate_python`, validation-failure downgrades, and unparseable items. Adding a fourth kind requires no signature change — the adapter handles dispatch automatically; the downgrade path applies identically (swap-template items failing `SearchSpace` validation downgrade to `text`).
- `backend/app/domain/study/followups.py:313-322` — `serialize_followup_list(items)` calls `item.model_dump(mode="json")` per item, flattening nested `SearchSpace` models. Works unchanged for the new variant.
- `backend/app/domain/study/search_space_defaults.py:144-223` — `build_starter_search_space(declared_params)` returns a `StarterSearchSpace` (validated `SearchSpace` + `cap_aware_fallback_param_names: list[str]`). Heuristic priority: HEURISTIC_RULES → simple_form_spec → `_DEFAULT_FALLBACK` (uniform float `[0, 1]`). Cap-aware fallback fires when cardinality > 10⁶ (converts floats to `int[0, 5]` in priority order). Raises `InvalidSearchSpaceError` on empty `declared_params` or exhausted fallback. This spec **reuses** the helper unchanged to assign default bounds to disjoint params on the swap target.
- `backend/app/domain/study/search_space.py:92-118` — `SearchSpace` Pydantic model (`params: dict[str, ParamSpec]`, `min_length=1`, cardinality cap 10⁶). The new `SwapTemplateFollowup.search_space` field reuses this validator verbatim (Tier-A pattern).
- `backend/app/db/models/digest.py` — `digests.suggested_followups` was migrated to `JSONB NOT NULL DEFAULT '[]'::jsonb` in Alembic revision `0019_digests_suggested_followups_jsonb` (Tier A). **No new migration needed** — the JSONB column accommodates the new `{kind: "swap_template", ...}` shape directly.
- `backend/app/db/models/study.py` — `parent_proposal_id VARCHAR(36) NULL` + `parent_proposal_followup_index INT NULL` exist (added by Tier A's `0018_studies_parent_proposal`). The CHECK constraint, partial index, and `trg_clear_studies_parent_proposal_on_proposal_delete` BEFORE DELETE trigger are in place. No schema change needed.
- `backend/app/api/v1/schemas.py:28` — `from backend.app.domain.study.followups import FollowupItem as FollowupItem`. Adding `SwapTemplateFollowup` to the union widens `FollowupItem`; `DigestResponse.suggested_followups: list[FollowupItem]` (line 981) and `_DigestEmbed.suggested_followups: list[FollowupItem]` (line 1042) pick up the widening with no code change beyond the OpenAPI regen.
- `backend/app/api/v1/schemas.py:614-630` — `ParentFollowupRef` + `CreateStudyRequest.parent: ParentFollowupRef | None = None`. The lineage payload accepts any 36-char `proposal_id` + `followup_index >= 0`; no kind discriminator on the lineage. Validation at `backend/app/api/v1/studies.py:325-373` re-parses the digest's followups via `parse_followup_list(...)` and enforces `followup_index < len(parsed_followups)`. **No spec-required change** — a `swap_template` followup validates identically to a `narrow`/`widen`. (FR-11 in Tier A even calls out: "The API doesn't enforce that the referenced followup is `narrow`/`widen` — operator may run a text item with a manually-authored search_space; same applies here for swap_template.")
- `backend/workers/digest.py:186-216` — `DIGEST_RESPONSE_SCHEMA`. The `suggested_followups` items schema enumerates `"kind": {"type": "string", "enum": ["narrow", "widen", "text"]}` and requires `{kind, rationale, search_space_json}` (no `template_id`). **Must extend** — the enum gains `"swap_template"` and items need a `template_id` field that is **declared on every item AND in `required`** (per GPT-5.5 cycle-2 F1: the schema uses the required-for-all + empty-string-sentinel pattern from FR-5 / D-20, NOT a `oneOf`/`if`/`then` conditional which OpenAI strict mode rejects). The worker pre-cleans the payload (drops `template_id` keys whose value is exactly `""` for non-swap kinds; downgrades non-swap items carrying any non-empty `template_id`) before `FollowupItemAdapter.validate_python`.
- `backend/workers/digest.py:752-756` — `parent_search_space=study.search_space` is already passed to the user prompt. The `<parent_search_space>` block in `prompts/digest_narrative.user.jinja:40-43` renders it. **Must extend** — also pass the parent template's `declared_params` (so the LLM can decide whether the swap is "intersection-heavy enough to be worth proposing") and a **catalogue of available templates** (so the LLM doesn't hallucinate `template_id` strings).
- `prompts/digest_narrative.system.md:62-92` — current followup-kind documentation. **Must extend** — add the `swap_template` kind paragraph with selection criteria (parameter-importance skew OR winning-trial param clustering) plus the cross-template remapping contract ("emit `search_space` covering the swap-target's `declared_params`; the worker fills disjoint params from heuristic defaults").
- `prompts/digest_narrative.user.jinja:40-43` — current `<parent_search_space>` block. **Must extend** — render `<parent_template_declared_params>` + `<available_templates>` blocks so the LLM has the data to pick a swap target.
- `ui/src/components/proposals/suggested-followups-panel.tsx:41-45` — `KIND_LABELS: Record<FollowupKind, string>` currently `{narrow: 'Narrow', widen: 'Widen', text: 'Suggestion'}`. **Must extend** — add `swap_template: 'Swap template'`. The per-card render branch at lines 78-139 currently treats `narrow`/`widen` identically (rationale + collapsible "Show search space" + "Run this followup" button). The new variant needs the same actionable surface PLUS a side-by-side `<declared_params>` comparison; the search-space details + Run button reuse the existing primitives.
- `ui/src/lib/enums.ts:248-249` — `FOLLOWUP_KIND_VALUES = ['narrow', 'widen', 'text'] as const`. **Must extend** to include `'swap_template'`. The source-of-truth comment at line 247 (`// Values must match backend/app/domain/study/followups.py FOLLOWUP_KIND_VALUES`) stays accurate.
- `ui/src/lib/glossary.ts:480-507` — existing tooltip keys `proposal.followup_kind_{narrow,widen,text}` + `proposal.followup_run_button` + `proposal.followup_search_space_diff`. **Must add** keys `proposal.followup_kind_swap_template` + `proposal.followup_declared_params_diff` (see §11 tooltip inventory).
- `ui/src/components/studies/create-study-modal.tsx:165-188` — `PrefillValues` interface. `template_id: string` is already a top-level field (line 168). The `swap_template` flow seeds `template_id = followup.template_id` (the swap target) instead of `parentStudy.template_id` (the parent). **No interface change required** — only the prefill-construction logic in `ui/src/app/proposals/[id]/page.tsx:136-184` widens its `kind` branch from `(narrow | widen)` to `(narrow | widen | swap_template)`. The modal already re-renders the template-dependent downstream pickers (query-sets filter on `cluster_id`, the Step-4 search-space autofill recomputes from `declared_params` per `feat_agent_propose_search_space`) — passing a different `template_id` Just Works through the existing wiring at modal lines 350-456.
- `ui/src/lib/api/query-templates.ts:14-58` — `useTemplate(id)` TanStack Query hook returning `QueryTemplateDetail` (`{id, name, engine_type, body, declared_params: dict[str, str], version, parent_id?, created_at}`). Available for the side-by-side comparison — the panel can lazily fetch both parent + swap-target templates and diff `declared_params` keys client-side.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| _none_ | — | No URL routes change. The new card variant is rendered in-place inside the existing `SuggestedFollowupsPanel` on `/proposals/[id]`. The "Run this followup" button still opens the existing `CreateStudyModal` overlay (no navigation away). |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/unit/domain/study/test_followups.py` | Discriminated-union per-kind validation | TBD at impl time | Add per-kind tests for `SwapTemplateFollowup`: valid `{kind, rationale, template_id, search_space}` round-trips; rejection of swap with `template_id` absent / non-36-char; rejection of swap with `search_space=None`; rejection of `extra="forbid"` field. |
| `backend/tests/unit/workers/test_digest_followup_validation.py` | LLM-payload validation / downgrade-and-drop | TBD at impl time | Add a fixture LLM payload containing one `swap_template` item whose `search_space` exceeds cardinality cap → assert downgrade to `text` with `[validation failed: ...]` rationale prefix + `digest_followup_validation_downgraded` WARN. Add a fixture with `swap_template` carrying a `template_id` for a non-existent template — see §19 D-4 for the worker-side existence check decision. |
| `backend/tests/unit/domain/study/test_template_swap.py` | _new_ | TBD at impl time | Cover the cross-template remap helper introduced in FR-3: intersection-only / disjoint-only / dropped-only / mixed cases; cardinality cap blow-up; empty `swap_search_space`. |
| `backend/tests/integration/test_digest_followup_roundtrip.py` | Worker → DB → API round-trip | TBD at impl time | Extend with a `swap_template` happy-path: stub LLM emits `swap_template` item; assert persisted JSONB shape; assert `GET /api/v1/studies/{id}/digest` returns the structured shape. |
| `backend/tests/integration/test_studies_with_parent_followup.py` | `POST /api/v1/studies` with `body.parent` | TBD at impl time | Add a swap-template lineage case: parent study uses template A; create-study body uses template B AND `parent: {proposal_id, followup_index}`; assert the new row's `template_id = B` AND `parent_proposal_id = <pid>` AND `parent_proposal_followup_index = <i>` (FR-7). |
| `backend/tests/contract/test_digest_response_shape.py` | `DigestResponse.suggested_followups` is `list[FollowupItem]` | TBD at impl time | Add an assertion that the OpenAPI schema's `FollowupItem` oneOf includes the `SwapTemplateFollowup` branch; assert a swap-template item round-trips. |
| `backend/tests/contract/test_proposal_detail_shape.py` | `_DigestEmbed.suggested_followups` shape | TBD at impl time | Same as above — assert the wider union. |
| `ui/src/__tests__/components/proposals/suggested-followups-panel.test.tsx` | Per-kind render assertions | TBD at impl time | Add render tests for the `swap_template` card: badge label "Swap template", side-by-side `<declared_params>` comparison visible, "Run this followup" button with `data-testid="followup-${i}-run"` present, glossary tooltip on `proposal.followup_kind_swap_template`. |
| `ui/src/__tests__/lib/enums.test.ts` (if exists) or new vitest | `FOLLOWUP_KIND_VALUES` length / membership | TBD at impl time | Update length to 4; assert `'swap_template'` is present; the existing source-of-truth grep guard (`scripts/ci/verify_enum_source_of_truth.sh`) catches drift automatically. |
| `ui/tests/e2e/followup_run.spec.ts` | Real-backend Playwright | TBD at impl time | Add a second test (or extend existing) covering swap-template happy path: seed two templates (A + B) sharing one param + B having one extra; seed a study against A with a proposal+digest containing a `swap_template` followup pointing at B; click "Run this followup"; assert modal opens with `template_id=B`; submit; assert new study row has `template_id=B` + lineage columns set. |

### Existing behaviors affected by scope change

- **`FollowupItem` discriminator value space.** Current: `narrow | widen | text` (3 values). New: `narrow | widen | text | swap_template` (4 values). All call sites consume the union via Pydantic's discriminator (Python) or TypeScript narrowing (`if (f.kind === 'swap_template')`). **Decision needed:** No — locked in idea + spec.
- **`SuggestedFollowupsPanel` card-render branching.** Current: `(narrow | widen)` branch renders the actionable card (rationale + search-space details + Run button); `text` branch renders rationale-only. New: a third branch handles `swap_template` — actionable card with rationale + **two** detail expanders (search-space AND declared-params diff) + Run button. **Decision needed:** No — locked in idea.
- **"Run this followup" prefill `template_id` source.** Current: always the parent study's `template_id` (sourced from the lazy `useStudy(parentStudyId)` fetch). New: `template_id = followup.template_id` for `swap_template` items; parent's `template_id` for `narrow`/`widen`. **Decision needed:** No — locked in idea.
- **Digest LLM input prompt content.** Current: `<parent_search_space>` block only. New: adds `<parent_template_declared_params>` + `<available_templates>` blocks so the LLM has the data needed to pick a swap target without hallucinating. **Decision needed:** No — see §19 D-2 for the catalogue-shape decision.
- **Operator's mental model when reading the "Suggested follow-ups" section.** Current: the panel is "tweak this study's search space." New: it can also be "try a different template." We name the variant **"Swap template"** in the UI badge to make the semantic shift visible at a glance. **Decision needed:** No.

---

## 3) Scope

### In scope

- New `SwapTemplateFollowup` Pydantic model and extension of the `FollowupItem` discriminated union + `FOLLOWUP_KIND_VALUES` tuple in `backend/app/domain/study/followups.py` (FR-1).
- New domain helper `backend/app/domain/study/template_swap.py` exporting `remap_search_space_for_swap_target(...)` (pure-domain, no I/O) that computes intersection / disjoint / dropped param sets and produces a validated `SearchSpace` for the swap target by combining the LLM's emitted bounds for intersection params with `build_starter_search_space()` heuristic defaults for disjoint params, dropping params the swap target doesn't declare (FR-2 + FR-3).
- Validator + downgrade behavior at digest-persist time: a `swap_template` item whose `search_space` fails `SearchSpace.model_validate` (cardinality > 10⁶ etc.) OR whose `template_id` is malformed (length != 36) downgrades to `text` via the existing `parse_followup_list()` decision table — same shape, no new code paths required (FR-4).
- LLM schema (`DIGEST_RESPONSE_SCHEMA`) extension: `kind` enum gains `"swap_template"`; per-item shape gains a `template_id` field declared on every item and listed in `required`, with the LLM-emitted value `""` as the non-swap sentinel and the worker pre-cleaning before Pydantic dispatch (FR-5; per GPT-5.5 cycle-2 F1 — no schema-level `oneOf`/`if`/`then` conditional).
- LLM prompt extension (`prompts/digest_narrative.system.md` + `prompts/digest_narrative.user.jinja`) teaching the model when to emit `swap_template` and providing the parent template's `declared_params` + the available-templates catalogue (FR-6).
- Worker-side extension to pass the catalogue + parent template `declared_params` into the user prompt (FR-7).
- Worker-side post-LLM remap call: when the LLM emits a `swap_template` item with a valid `template_id` that resolves to a real template, the worker calls `remap_search_space_for_swap_target(...)` to produce the final stored `search_space` (intersection params take LLM bounds; disjoint params get heuristic defaults; dropped silently dropped with a structlog INFO event) (FR-7).
- Worker-side `template_id` existence check: a `swap_template` item whose `template_id` doesn't resolve to a real `query_templates` row OR resolves to the **same** template as the parent study downgrades to `text` with `[validation failed: swap_template target template not found|same-as-parent: <id>]` rationale prefix (FR-8).
- Frontend extension to `ui/src/lib/enums.ts` `FOLLOWUP_KIND_VALUES` and `KIND_LABELS` in `suggested-followups-panel.tsx` (FR-9).
- Frontend extension to `SuggestedFollowupsPanel` rendering the `swap_template` card with badge, rationale, side-by-side `declared_params` comparison (lazy-fetched via `useTemplate(parent_template_id)` + `useTemplate(swap_template_id)`), collapsible "Show search space" diff, and "Run this followup" button (FR-10).
- Frontend extension to the proposal-detail page's prefill-construction (`ui/src/app/proposals/[id]/page.tsx:136-184`) so the `swap_template` branch seeds `template_id = followup.template_id` instead of `parentStudy.template_id` (FR-11).
- Glossary additions for the two new tooltip keys (FR-12).
- Reuse of the existing `parent_proposal_id` + `parent_proposal_followup_index` lineage from Tier A — no schema change (FR-13 — clarification, not a new requirement).
- Audit events: extend the existing Tier-A `digest.followup_clicked` event's `followup_kind` allowed value space to include `swap_template` (per Tier-A spec §6). All other Tier-A events apply unchanged. **No new event types.** (`audit_log` doesn't exist until MVP2; these are pre-shaped only.)

### Out of scope

- **Tier C — `kind: "edit_template"` followups.** Operator-only today; LLM-suggested template edits are a much larger trust/validation surface and unrelated to this spec's lane. Tracked at sibling backlog folder [`backlog_feat_digest_template_edit_followups`](../../../02_product/planned_features/backlog_feat_digest_template_edit_followups/idea.md).
- **Auto-running swap-template followups without operator click.** Out — operator review is the entire trust mechanism for cross-template hops.
- **Side-by-side rendering of the template's Jinja2 body.** Out — only `declared_params` are compared. The Jinja source is large, hard to diff usefully without a syntax-aware viewer, and most operators making the call don't need it; if they do, the existing template detail page at `/templates/[id]` is one click away.
- **Auto-discovery of the swap-target template.** The LLM picks; we don't fall back to a similarity search or compute the swap target server-side. (Reason: the LLM has the full study-outcome context including parameter-importance distribution + winning-trial cluster; a deterministic similarity search would have to re-derive a much weaker proxy for "which template fits these winning params better.")
- **Swap to a template of a different `engine_type`.** A swap-target template whose `engine_type` differs from the parent study's cluster engine downgrades to `text` (FR-8) — the post-submit `POST /api/v1/studies` would fail with `JUDGMENT_CLUSTER_MISMATCH` or similar anyway; downgrading earlier preserves the rationale visibly.
- **Cross-engine swaps mediated by template body edits.** Out — Tier C territory.
- **Operator-curated short-list of swap candidates.** The catalogue is just "all current templates" filtered by `engine_type`. A future enhancement could let the operator tag a subset as "swap-eligible"; out of scope here.
- **Caching the available-templates catalogue.** The worker fetches at digest time (one extra SELECT). Catalogues at MVP1 scale are small (≤ dozens of templates); a cache is premature.
- **Audit events.** `audit_log` table doesn't exist in MVP1 (Tier A documented the three forthcoming events pre-shaped for MVP2; this spec adds no new event types and only widens the `followup_kind` allowed-value space).

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` for business endpoints — confirmed in `backend/app/api/v1/studies.py` and `backend/app/api/v1/proposals.py`.
- **Router namespace for this feature's endpoints:** **No new router file. No method or path changes.** The feature extends the response shape of `GET /api/v1/studies/{study_id}/digest` (`DigestResponse`) + `GET /api/v1/proposals/{proposal_id}` (`_DigestEmbed`) by widening the `FollowupItem` union. `POST /api/v1/studies` is unchanged — the existing `body.parent` field already accepts any in-range `followup_index` regardless of the underlying kind.
- **HTTP methods for CRUD:** No new methods. The new flow reuses existing `POST /api/v1/studies`.
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` — per `_err()` helper at `backend/app/api/v1/studies.py:75-79`. **No new error codes** — swap-template-specific validation failures emit existing codes (`INVALID_SEARCH_SPACE` at create-study time for the operator's submission; downgrade-to-`text` for worker-side failures, no API error). Auth error shape: N/A in MVP1.

### Phase boundaries

This spec is a **single-phase delivery** of Tier B (`swap_template`). Tier C (`edit_template`) is tracked separately at the sibling backlog folder per the Tier-A spec §3 phase-boundary decision and is not gated by Tier B. No `phase2_idea.md` artifact is required from this folder.

## 4) Product principles and constraints

- **Operator-mediated cross-template hops are the entire trust model.** The LLM proposes; the operator reviews the side-by-side `declared_params` diff + the proposed search space; the operator submits via the existing `POST /api/v1/studies` validation chain. Cross-template autoflow stays out of scope (and out of Tier-C scope) by design.
- **The cross-template remap helper is pure.** No DB access, no I/O, no async. Caller passes parent template `declared_params`, swap-target template `declared_params`, LLM-emitted `search_space`. Helper returns a validated `SearchSpace` plus a `RemapResult` value object enumerating trusted-intersection / disjoint-fill / dropped-parent / ignored-LLM param names. Worker is responsible for logging the diagnostics + persisting; helper is a pure transformation.
- **Disjoint params get heuristic defaults from the existing helper** — never blank, never best-guesses-from-the-LLM (the LLM doesn't know the swap target's bounds preference, only its declared_params). Reusing `build_starter_search_space(disjoint_declared_params)` from `feat_agent_propose_search_space` is the single source of truth for "what bounds does an undiscussed param get."
- **Dropped params are silently dropped** with an INFO-level structlog event — they're declared by the parent but not by the swap target, so they're not meaningful in the swapped context. Not a validation error.
- **A swap-template item that resolves to the parent's own template is a degenerate case** — downgrades to `text` with `[validation failed: same-as-parent template_id: <id>]` because shipping a "swap to template X" card where X is template X is operator-confusing. Tier A's `narrow`/`widen` already handle same-template followups cleanly.
- **A swap-template item that resolves to a template of a different `engine_type`** downgrades to `text` (per §3 out-of-scope). The post-submit `POST /api/v1/studies` would reject anyway via the existing cluster-engine validation; downgrading at digest time keeps the failure visible.
- **No new DB columns, no new migrations.** The Tier-A JSONB column accommodates the new shape; the existing lineage columns + trigger + CHECK constraint apply unchanged.
- **CLAUDE.md Absolute Rules apply.** Feature branch + PR; secrets via mounted files; no hardcoded LLM models (`settings.openai_model` only); the digest worker continues to use the existing budget/capability/advisory-lock infrastructure; all persisted artifacts continue to capture `generated_by`. The new domain helper is pure (Absolute Rule "domain layer = pure business logic — no DB access, no I/O, no async").

### Anti-patterns

- **Do not** introduce a separate Pydantic class hierarchy for `swap_template` outside the existing `FollowupItem` union. The union is the contract; the discriminator is the dispatch mechanism. A parallel hierarchy would split validation, serialization, and the frontend's TypeScript narrowing in two.
- **Do not** require the LLM to emit the disjoint-param bounds. The LLM is asked to emit `search_space` for **intersection** params only (params declared by both templates). The worker fills disjoint params from the heuristic helper. (Reason: the LLM has visibility into the parent study's outcome distribution for intersection params; it has no signal at all for params the parent never used, so its "guess" for disjoint bounds would be a hallucination.)
- **Do not** silently auto-substitute a different template when the LLM emits an unknown `template_id`. The downgrade is intentional and visible — the operator sees `[validation failed: swap_template target template not found: <id>]` and knows the LLM hallucinated.
- **Do not** cross the `engine_type` boundary. A swap-target template whose `engine_type` doesn't match the parent cluster's engine type downgrades to `text`. Letting the operator submit cross-engine and then 400ing at `POST /api/v1/studies` is a worse UX than refusing at digest time.
- **Do not** render the full Jinja2 body in the side-by-side comparison. Templates are large; the visual noise hides the useful comparison (`declared_params`). Link to `/templates/[id]` for the body.
- **Do not** add the `template_id` to lineage. Lineage is `parent_proposal_id` + `parent_proposal_followup_index` — the kind (and thus the swap) is recoverable by re-parsing the digest at `parent_proposal_id`. Adding `parent_swap_template_id` would duplicate.
- **Do not** treat the side-by-side declared-params diff as a security boundary. It's an operator-discovery aid; the validation that matters is server-side `validate_against_template()` at `POST /api/v1/studies` (existing).

## 5) Assumptions and dependencies

- Dependency: **`feat_digest_executable_followups` Phase 1 (Tier A)** — shipped 2026-05-24 as PR #225 squash `83c526f2`. Status: implemented. Risk if missing: blocker — the entire substrate (discriminated union, defensive parser, JSONB column, lineage columns + trigger, "Run this followup" UI scaffolding, lazy `useStudy(parent_study_id)` fetch + prefill construction) is provided here. **N/A — already shipped.**
- Dependency: **`feat_agent_propose_search_space`** — shipped 2026-05-21 as PR #175 squash `5d29355`. Status: implemented. Provides `backend/app/domain/study/search_space_defaults.py` `build_starter_search_space(declared_params)` used by FR-3 for disjoint-param defaults. Risk if missing: blocker — no production code change can implement FR-3 without it. **N/A — already shipped.**
- Dependency: **`feat_digest_proposal`** — shipped 2026-05-11 as PR #41. Status: implemented. Provides the digest worker scaffolding (capability check, budget gate, advisory lock, persist-first then record-cost ordering). All controls preserved.
- Dependency: **`feat_create_study_search_space_builder`** — shipped 2026-05-20. Status: implemented. The row primitives are reused by the existing search-space-diff renderer (Tier A); this spec does not introduce a new search-space renderer.
- Dependency: **OpenAI-compatible endpoint with structured-output (`json_schema`) capability** — same as Tier A. When degraded, the worker persists `suggested_followups=[]` (preserved). The catalogue + parent-declared-params blocks added to the user prompt are inert in the degraded path (no structured response).
- Dependency: **`useTemplate(id)` TanStack Query hook at `ui/src/lib/api/query-templates.ts`** — exists since `feat_studies_ui`. Used to lazy-fetch parent + swap-target `declared_params` for the side-by-side comparison. Risk if missing: N/A — already shipped.
- Dependency: **No new env vars, no new secrets.** Reuses `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` from `Settings`.
- Dependency: **Postgres 16 JSONB.** Tier A already migrated `digests.suggested_followups` to JSONB; this spec ships no migration.

## 6) Actors and roles

- Primary actor(s): **Relevance Engineer** (umbrella spec §6). The operator reviewing a proposal's digest who notices the LLM's "try template X instead" hint and wants a one-click jump-off.
- Role model: **N/A — single-tenant install, no auth surface.** MVP1.
- Permission boundaries: **N/A — single-tenant.** Activates at MVP4 per CLAUDE.md.

### Authorization

N/A — single-tenant install, no auth surface (MVP1).

### Audit events

**N/A in MVP1 — `audit_log` table lands at MVP2** per `docs/01_architecture/data-model.md` §"Reserved for later releases".

**Pre-shaped for MVP2 (forthcoming, do NOT implement now):**

This spec **does not introduce new event types**. The three Tier-A pre-shaped events apply unchanged; per GPT-5.5 cycle-1 F8 + cycle-2 F3, the `followup_kind` field's allowed values widen to `{narrow, widen, text, swap_template}` on `digest.followup_clicked` (Tier A's FR-11 already allows `text`-kind lineage at the API) and `original_kind` widens to `{narrow, widen, text, swap_template}` on `digest.followup_validation_downgraded` (the existing parser emits `original_kind="text"` for malformed text items):

| Event type | Trigger | Visibility | Metadata fields |
|---|---|---|---|
| `digest.followup_clicked` (Tier-A event, **widened**) | UI fires the "Run this followup" button on a `swap_template` card → recorded at the `POST /api/v1/studies` boundary when `body.parent` is set. The Tier-A event's `followup_kind` field carries the **kind the operator actually clicked**, which Tier-A FR-11 already allows to be `"text"` (operators may chain off a `text` followup with a manually authored search_space). | tenant-visible | `proposal_id`, `followup_index`, `followup_kind` ∈ `{narrow, widen, text, swap_template}` (per GPT-5.5 cycle-1 F8: `text` is in the allowed set because Tier-A FR-11 doesn't reject `text`-kind lineage at the API), `created_study_id`. |
| `study.created_from_followup` (Tier-A event, **applies as-is**) | Side-effect of `POST /api/v1/studies` when `parent.proposal_id` is set — atomic with the INSERT. | tenant-visible | `study_id`, `parent_proposal_id`, `parent_proposal_followup_index`, `cluster_id`, `template_id` (now possibly differing from the parent study's `template_id` for `swap_template`-spawned children). |
| `digest.followup_validation_downgraded` (Tier-A event, **widened**) | Digest worker downgrades a `narrow`/`widen`/`text`/`swap_template` item to `text`. Existing parser already emits `original_kind="text"` for malformed text items per `backend/app/domain/study/followups.py:128-156` + `:236-310` (`_try_text_only` records whatever `kind` the raw item carried). | system | `study_id`, `proposal_id`, `followup_index`, `original_kind` ∈ `{narrow, widen, text, swap_template}` (per GPT-5.5 cycle-1 F8), `validation_error` (head-and-tail truncated: first 200 chars + `"...[truncated]..."` marker + last 200 chars when the source exceeds 400 chars, per the canonical `_truncate` helper at `backend/app/domain/study/followups.py:63-77` and `_TRUNCATE_LIMIT = 200` at line 60 — per GPT-5.5 cycle-2 F5; no PII). For worker-side existence/engine/remap downgrades on `swap_template` (FR-7 step 3 + FR-8): additional `reason` sub-field ∈ `{not_found, same_as_parent, engine_type_mismatch, remap_invalid_search_space}` (per GPT-5.5 cycle-2 F4 — `remap_invalid_search_space` covers the case where `remap_search_space_for_swap_target` raises `InvalidSearchSpaceError`). |

No credentials, tokens, or PII beyond display-name strings in metadata.

## 7) Functional requirements

### FR-1: Add `swap_template` to the `FollowupItem` discriminated union

- The system **MUST** add a new `SwapTemplateFollowup` Pydantic model to `backend/app/domain/study/followups.py`, structured identically to the existing variants:
  ```python
  class SwapTemplateFollowup(BaseModel):
      model_config = ConfigDict(extra="forbid")

      kind: Literal["swap_template"]
      rationale: str
      template_id: str = Field(min_length=36, max_length=36)
      search_space: SearchSpace
  ```
  The `template_id` validation matches the existing 36-char UUIDv7 bound used elsewhere (`ParentFollowupRef.proposal_id` at `backend/app/api/v1/schemas.py:629`; `Study.template_id` at `backend/app/db/models/study.py`).
- The system **MUST** widen the `FollowupItem` type alias to include the new variant:
  ```python
  type FollowupItem = Annotated[
      NarrowFollowup | WidenFollowup | TextFollowup | SwapTemplateFollowup,
      Field(discriminator="kind"),
  ]
  ```
- The system **MUST** update `FOLLOWUP_KIND_VALUES: tuple[str, ...] = ("narrow", "widen", "text", "swap_template")` so the CI source-of-truth grep gate (`scripts/ci/verify_enum_source_of_truth.sh`) and frontend mirror (`ui/src/lib/enums.ts`) stay aligned.
- The system **MUST** export `SwapTemplateFollowup` from the module's `__all__`.
- The system **MUST NOT** change the existing variants, `FollowupItemAdapter`, `FollowupListAdapter`, or any helper signature. The adapter dispatch picks up the new variant automatically.

### FR-2: `swap_template` flows through the existing defensive ingest unchanged

- The system **MUST** allow `parse_followup_list(raw, *, study_id, proposal_id)` to handle the new variant via the existing `FollowupItemAdapter.validate_python(...)` dispatch — no new branch, no new code path.
- The system **MUST** apply the existing downgrade-or-drop decision table to `swap_template` items: a `swap_template` whose `search_space` exceeds the cardinality cap, OR whose `template_id` fails `Field(min_length=36, max_length=36)`, OR whose `rationale` is missing, OR which carries `extra="forbid"` fields, downgrades to `TextFollowup` (with the `[validation failed: <truncated error>] ` rationale prefix) when a salvageable `rationale` exists, otherwise drops with `digest_followup_dropped`. The existing structlog event `digest_followup_validation_downgraded` carries `original_kind="swap_template"`.
- The system **MUST** allow `serialize_followup_list(items)` to JSONB-serialize `SwapTemplateFollowup` instances via the existing `item.model_dump(mode="json")` call. The nested `SearchSpace` flattens to plain JSON dicts identically to the `narrow`/`widen` paths.

### FR-3: Cross-template search-space remap helper (`template_swap.py`)

- The system **MUST** add a new pure-domain module `backend/app/domain/study/template_swap.py` with no DB access, no async, no I/O. Co-located with `search_space_defaults.py` (sibling module).
- The system **MUST** export a function with the following signature:
  ```python
  def remap_search_space_for_swap_target(
      *,
      parent_declared_params: dict[str, str],
      swap_target_declared_params: dict[str, str],
      llm_search_space: SearchSpace,
  ) -> RemapResult:
      ...
  ```
  where `RemapResult` is a dataclass (or NamedTuple) with fields:
  ```python
  @dataclass(frozen=True, slots=True)
  class RemapResult:
      search_space: SearchSpace
      trusted_intersection_param_names: list[str]    # sorted; in parent ∩ swap ∩ llm — bounds copied from llm_search_space
      disjoint_fill_param_names: list[str]           # sorted; swap-target params filled from build_starter_search_space defaults
      dropped_parent_param_names: list[str]          # sorted; declared by parent but not swap target
      ignored_llm_param_names: list[str]             # sorted; LLM-emitted but not in trusted intersection (logged for observability)
  ```
- The helper algorithm **MUST**:
  1. Compute `parent_names = set(parent_declared_params)`, `swap_names = set(swap_target_declared_params)`, `llm_names = set(llm_search_space.params)`.
  2. **Trusted intersection** = `parent_names ∩ swap_names ∩ llm_names` — copy each param's `ParamSpec` directly from `llm_search_space.params[name]`. (The LLM has signal ONLY on params the parent study actually used AND that the swap target re-declares. Per GPT-5.5 cycle-1 F1: an LLM-emitted entry for a param that the parent never declared is an LLM hallucination — even if the swap target declares it, the LLM had no parent-side outcome data to ground its bounds; route through heuristic fill instead.)
  3. **Disjoint fill** = `swap_names \ (parent_names ∩ llm_names)` — i.e., every swap-target param NOT in the trusted intersection. When the fill set is non-empty, call `build_starter_search_space({name: swap_target_declared_params[name] for name in disjoint_fill})` and adopt the per-param `ParamSpec` for each. Per GPT-5.5 cycle-1 F2: **when the fill set is empty (every swap-target param landed in the trusted intersection), skip the call entirely** — `build_starter_search_space` raises `InvalidSearchSpaceError` on empty input.
  4. **Dropped parent params** = `parent_names \ swap_names` — params declared by the parent template that the swap target doesn't carry. Returned in `dropped_parent_param_names`; the operator sees these in the side-by-side declared-params diff (grayed out on the parent side).
  5. **Ignored LLM params** = `llm_names \ (parent_names ∩ swap_names)` — LLM-emitted bounds for params that aren't in the trusted intersection. Per GPT-5.5 cycle-1 F3: returned separately in `ignored_llm_param_names` for observability (workers log these so we can tell whether the LLM is hallucinating params often). These bounds are NOT used in the output; if such a param IS declared by the swap target, it falls into the disjoint-fill bucket (step 3) and gets heuristic defaults instead.
  6. Combine trusted intersection (LLM bounds) + disjoint fill (heuristic bounds) into the final `params` dict and construct `SearchSpace(params=...)`. Pydantic validates cardinality cap; on failure, **raise `InvalidSearchSpaceError`** (not the SearchSpace's own `ValidationError`) so the caller can route through the existing downgrade path.
- The helper **MUST** raise `InvalidSearchSpaceError` when `swap_names` is empty (the swap-target template declares no params; can't construct a `SearchSpace` with `min_length=1`).
- The helper **MUST** raise `InvalidSearchSpaceError` when trusted-intersection ∪ disjoint-fill produces an empty `params` dict for any reason. Caller routes through downgrade.
- The helper **MUST** raise `InvalidSearchSpaceError` when the trusted intersection is empty (per GPT-5.5 cycle-3 F1: `Field(min_length=1)` on `SwapTemplateFollowup.search_space.params` means a compliant LLM cannot emit an empty `search_space` for a swap whose parent ∩ swap is empty — the followup item would be rejected by Pydantic before the worker reaches the remap step. To keep the helper's invariants symmetric with the worker contract, the helper itself rejects no-trusted-intersection inputs with the same error type, surfacing as `[validation failed: swap_template has no shared parameters with parent template: ...] ` rationale prefix at the worker downgrade site). FR-6 prompt MUST instruct the LLM to skip `swap_template` when the catalogue contains no template with at least one shared param.
- The helper **MUST NOT** call the LLM, the DB, or any async code. Test fixtures pass plain `dict[str, str]` for `*_declared_params` and a pre-built `SearchSpace` for `llm_search_space`.
- Notes: `build_starter_search_space` already raises `InvalidSearchSpaceError` on empty declared_params and on cap-aware-fallback exhaustion; the remap helper re-raises with the existing error type so the caller's `try/except` shape is identical to the Tier-A `narrow`/`widen` validation path.

### FR-4: Validator + downgrade at digest-persist time (no new code path)

- The system **MUST** route `swap_template` items through the existing `parse_followup_list()` → `FollowupItemAdapter.validate_python()` chain. No new validator wrapper is required at this layer.
- The system **MUST** preserve the Tier-A "never abort the digest write because of a malformed followup" invariant — the narrative + valid items still persist; invalid `swap_template` items downgrade to `text` carrying the original intent (or drop when no rationale is recoverable).
- The system **MUST** emit the existing `digest_followup_validation_downgraded` structlog WARN event with `original_kind="swap_template"` when a downgrade occurs.

### FR-5: Extend the LLM structured-output schema

- The system **MUST** widen `DIGEST_RESPONSE_SCHEMA["properties"]["suggested_followups"]["items"]["properties"]["kind"]["enum"]` from `["narrow", "widen", "text"]` to `["narrow", "widen", "text", "swap_template"]`.
- The system **MUST** add `template_id` to the per-item `properties` map with type `string`. OpenAI strict mode requires every declared property to appear in `required` AND rejects branch-style schemas (`oneOf`/`anyOf`/`if`/`then`) at the items level. Per GPT-5.5 cycle-1 F4: the spec therefore does **NOT** use a JSON-schema conditional. Instead:
  - `template_id` is declared in the items `properties` AND added to `required`. Every emitted item carries the field on the wire.
  - The system prompt instructs the LLM to emit `template_id = ""` (empty string sentinel) for `narrow`/`widen`/`text` items, and the 36-char target template id for `swap_template` items.
  - The worker pre-cleans the payload BEFORE `FollowupItemAdapter.validate_python(...)` deterministically (per GPT-5.5 cycle-2 F1 — the cycle-1 patch's "drop OR fail" prose was ambiguous; the spec now mandates one branch per case):
    - For items where `kind != "swap_template"` AND `template_id == ""` (exactly empty string): **drop** the `template_id` key from the dict and pass through to `FollowupItemAdapter.validate_python(...)` (the non-swap variants have `extra="forbid"` and would reject any `template_id` field).
    - For items where `kind != "swap_template"` AND `template_id != ""` (LLM emitted a non-empty `template_id` on a non-swap kind — protocol violation): **do NOT drop**; pass through, which causes `FollowupItemAdapter.validate_python(...)` to raise `ValidationError` (via `extra="forbid"`), which the existing decision table downgrades to `text`. This makes the protocol violation visible as a downgrade event.
    - For items where `kind == "swap_template"`: pass `template_id` through unchanged; Pydantic enforces `Field(min_length=36, max_length=36)`. An empty-string `template_id` on a swap item fails the length check → downgrades.
  - This mirrors the Tier-A `search_space_json: str` workaround pattern (Tier-A worker comment lines 175-184) — the LLM emits a uniform per-item shape; the worker dispatches per-kind post-clean.
- The system **MUST** keep `maxItems: 5` on the `suggested_followups` array (unchanged).
- The system **MUST NOT** modify the existing `search_space_json: str` workaround — the same string-encoding mechanism applies to all four kinds. The post-parse worker step decodes `search_space_json` per item and dispatches to the appropriate variant constructor.
- Notes: the strict-mode constraint is the same one Tier A worked around. Pydantic validates strictly after the worker pre-cleans the payload.

### FR-6: LLM prompt updates

- The system **MUST** extend `prompts/digest_narrative.system.md` §"Suggested follow-ups — three kinds" (currently the H2 starting at line 73) to add a fourth subsection **`swap_template`** describing:
  - When to emit: parameter-importance distribution is highly skewed (one or two params dominate while others are dead weight), OR winning trials cluster around a sub-set of params that map cleanly onto a different template's declared params, OR the search space's most-important params have a natural home in a different template the operator has registered.
  - What to emit: `kind: "swap_template"`, `template_id` = the swap target's UUIDv7 (must be one of the IDs in the `<available_templates>` block), `rationale`, `search_space` covering the **intersection** of the parent template's `declared_params` and the swap target's `declared_params`. The `search_space` MUST contain at least one param (per GPT-5.5 cycle-3 F1 — the Pydantic constraint `Field(min_length=1)` on `SwapTemplateFollowup.search_space.params` rejects empty). The LLM should NOT try to assign bounds for params declared only by the swap target — the worker fills those from a heuristic. The LLM SHOULD note in the rationale which params it expects the swap target to declare anew (so the operator understands the diff).
  - What to avoid: emitting `template_id` for a template that's not in the `<available_templates>` block (will be downgraded to `text`); emitting a `template_id` that's the same as the parent study's template (degenerate; downgraded); emitting a `template_id` whose `engine_type` differs from the parent cluster's engine type (downgraded; see FR-8); emitting `swap_template` when no template in `<available_templates>` shares at least one declared_param with the parent template (per GPT-5.5 cycle-3 F1 — the LLM would have no intersection to emit bounds for; the prompt MUST instruct skipping `swap_template` in that case).
- The system **MUST** extend `prompts/digest_narrative.user.jinja` to render two new optional blocks:
  - `<parent_template_declared_params>`: the parent study's template `declared_params` (`{name: type-string}` dict), rendered as JSON. Always present.
  - `<available_templates>`: the catalogue of all currently-registered templates whose `engine_type` matches the parent cluster's engine type. Each entry includes `id` (UUIDv7), `name`, `version`, `declared_params` (compact JSON). Present when the catalogue has at least one template other than the parent study's template.
- The system **MUST** preserve the existing prompt blocks (`<study>`, `<baseline_vs_achieved>`, `<top_trials>`, `<parameter_importance>`, `<recommended_config>`, `<dropped_template_params>`, `<confidence>`, `<per_query_outcomes>`, `<parent_search_space>`).
- The system **MUST** preserve the existing capability-degraded path: when `structured_output_enabled=False`, no `swap_template` items are emitted; `suggested_followups` stays `[]`.

### FR-7: Worker — pass catalogue + parent template, remap on persist

- The system **MUST** extend the digest worker (`backend/workers/digest.py`) to fetch the parent template's `declared_params` once per digest call (via `get_query_template(db, study.template_id)`) and pass it into the user prompt as `parent_template_declared_params`.
- The system **MUST** extend the digest worker to fetch the available-templates catalogue once per digest call. The catalogue is the result of a single SELECT against `query_templates` filtered by the parent cluster's `engine_type` and excluding the parent study's own `template_id`. The catalogue is passed into the user prompt as `available_templates`.
  - When the catalogue is empty (no other templates registered for that engine), the worker SKIPS rendering the `<available_templates>` block — the LLM has no swap candidates to choose from, so emitting `swap_template` would always downgrade. The system prompt's `swap_template` subsection MUST instruct the LLM to skip the kind when the block is absent.
- The system **MUST** preserve the existing Step-13 followup-merge ordering with a per GPT-5.5 cycle-1 F7 reordering: drift followup prepended (when applicable), structured items appended, **list truncated to 5 FIRST**, then the per-`swap_template`-item DB existence/engine checks + remap run on the **retained items only**. This avoids spending DB queries + emitting WARN/INFO events for items that will never be persisted because they get truncated.
- The system **MUST**, after the truncation step, iterate the retained followup list and for each `swap_template` item:
  1. Lazily resolve the target template via `get_query_template(db, item.template_id)`. Cache results per worker call (a small dict keyed by `template_id`) so multiple swap-template items pointing at the same target don't re-query.
  2. If the target doesn't exist, OR the target's `id == study.template_id` (same-as-parent), OR the target's `engine_type` doesn't match the parent cluster's `engine_type`, downgrade the item to `text` with the `[validation failed: <reason>: <target_id>]` rationale prefix and emit `digest_followup_validation_downgraded` (FR-8).
  3. Otherwise, call `remap_search_space_for_swap_target(parent_declared_params=parent_template.declared_params, swap_target_declared_params=target.declared_params, llm_search_space=item.search_space)`. On `InvalidSearchSpaceError`, downgrade to `text` with rationale prefix `[validation failed: <truncated error>] ` AND emit `digest_followup_validation_downgraded` with `original_kind="swap_template"`, `reason="remap_invalid_search_space"`, and the truncated `validation_error` (per GPT-5.5 cycle-2 F4 — this is the 4th reason code referenced in §6 / §15 / D-11).
  4. On success, **replace** the item's `search_space` with `RemapResult.search_space` (the helper output). Emit a structlog INFO event `digest_followup_swap_template_remapped` with `study_id`, `proposal_id`, `target_template_id`, `trusted_intersection_param_names`, `disjoint_fill_param_names`, `dropped_parent_param_names`, `ignored_llm_param_names` for observability.
- The system **MUST NOT** call the engine adapter, the LLM, or any other external service during the remap step. All required data (`parent_template.declared_params`, `target.declared_params`) is loaded synchronously inside the worker's transaction.

### FR-8: Worker-side template existence + engine compatibility check

- The system **MUST** downgrade a `swap_template` item to `text` when its `template_id`:
  - doesn't exist (no `query_templates` row) → rationale prefix `[validation failed: swap_template target template not found: <id>] `;
  - resolves to a row whose `id == study.template_id` (same-as-parent) → rationale prefix `[validation failed: swap_template same-as-parent template_id: <id>] `;
  - resolves to a row whose `engine_type != cluster.engine_type` (cross-engine) → rationale prefix `[validation failed: swap_template engine_type mismatch (parent=<parent_engine>, target=<target_engine>): <id>] `.
- The system **MUST** emit `digest_followup_validation_downgraded` with `original_kind="swap_template"` and a `reason` sub-field (`not_found` | `same_as_parent` | `engine_type_mismatch`) for each FR-8 downgrade. The fourth `reason` value (`remap_invalid_search_space`) is owned by FR-7 step 3 (per GPT-5.5 cycle-2 F4) — that path is logged identically but is a separate FR. Per GPT-5.5 cycle-1 F9: the existing canonical domain emitter (`_emit_downgrade_warn` at `backend/app/domain/study/followups.py:128-153`) is private + doesn't carry a `reason` field. The spec's chosen approach is for the **worker** to emit the event directly via the existing structlog logger with the documented field set, rather than extending the domain helper. Rationale: the domain helper's purpose is the Pydantic-validation downgrade path (already covered for `swap_template` via FR-2); the worker's existence/engine/remap checks are separate worker-layer concerns. Keeping the emission at the worker keeps the domain module pure (no extra params for worker-layer concerns) and uses the same canonical event_type so runbook greps work uniformly. The unit test set in §14 MUST cover all 4 reason codes.
- The system **MUST NOT** raise — every downgrade is a soft path. Operator still sees the rationale.

### FR-9: Frontend — extend `FOLLOWUP_KIND_VALUES` and `KIND_LABELS`

- The system **MUST** update `ui/src/lib/enums.ts` `FOLLOWUP_KIND_VALUES` from `['narrow', 'widen', 'text'] as const` to `['narrow', 'widen', 'text', 'swap_template'] as const`. The source-of-truth comment immediately above (`// Values must match backend/app/domain/study/followups.py FOLLOWUP_KIND_VALUES`) stays unchanged.
- The system **MUST** add `swap_template: 'Swap template'` to the `KIND_LABELS: Record<FollowupKind, string>` map in `ui/src/components/proposals/suggested-followups-panel.tsx`.
- The system **MUST** audit every consumer of `FollowupKind` (use `grep -rn "FollowupKind\|FOLLOWUP_KIND_VALUES\|f\.kind\b\|followup\.kind\b" ui/src/`) and update each branch — `Record<FollowupKind, …>` maps are caught by TS automatically; `if/else if` chains on `f.kind` are NOT exhaustively checked by TS unless an explicit `assertNever`/`never` exhaustiveness check is added. Per GPT-5.5 cycle-1 F12: each per-kind branching site MUST either use a `Record<FollowupKind, …>` lookup, OR use a switch statement with a `default` branch that calls a typed `assertNever(f satisfies never)` helper, so a future fifth kind cannot silently fall through. The current `SuggestedFollowupsPanel` lines 78-139 use an `if (f.kind === 'narrow' || f.kind === 'widen')` branch + an implicit `text` fallback — this MUST be refactored to either (a) an exhaustive switch with `assertNever` in `default`, or (b) a `Record<FollowupKind, RenderFunction>` lookup, before the new `swap_template` branch is added.

### FR-10: Frontend — render the `swap_template` card

- The system **MUST** extend `SuggestedFollowupsPanel` to render `swap_template` items with:
  - Kind badge: `"Swap template"` with `aria-label="Swap template"`.
  - Glossary tooltip on the badge: `proposal.followup_kind_swap_template` (FR-12).
  - Rationale text.
  - A **side-by-side `declared_params` comparison panel** showing the parent template's `declared_params` on the left and the swap-target template's `declared_params` on the right. Each side renders as `{name: type-string}` pairs; shared keys are highlighted (e.g., bold or backgrounded); keys only on one side render as plain text. The panel uses `data-testid="followup-${i}-declared-params-diff"` on the wrapping element; per-side wrappers use `followup-${i}-parent-declared-params` and `followup-${i}-swap-declared-params`. The comparison is collapsed inside a `<details>` element matching the existing search-space-diff pattern; the summary text is `"Show declared params"` / `"Hide declared params"`.
  - A collapsible "Show search space" detail (same primitive as `narrow`/`widen`) showing the LLM-proposed `search_space` JSON. **The parent's search space is NOT shown in this card** because the swap-target's bounds aren't directly comparable to the parent's — they're different param spaces. (The card's value is `declared_params` comparison, not search-space comparison.)
  - A primary **"Run this followup"** button with `data-testid="followup-${i}-run"` and the existing `proposal.followup_run_button` glossary tooltip.
- The system **MUST** lazy-fetch both the parent template (`useTemplate(parentStudy.data.template_id)`) and the swap-target template (`useTemplate(followup.template_id)`) for each `swap_template` card. The fetches are gated on at least one actionable `swap_template` followup being present (mirroring the Tier-A parent-study lazy-fetch pattern at `ui/src/app/proposals/[id]/page.tsx:130-134`). Both fetches surface loading + error UI inside the card (loading message in the diff panel; error message replacing the diff panel with "Could not load template details — submitting will still work; the comparison view is unavailable.").
- The system **MUST** keep the existing `data-testid="suggested-followups-list"` on the container and the per-item card / run / search-space-toggle testids.
- The system **MUST** use the existing `InfoTooltip` primitive for all tooltips (no new tooltip component).
- The system **MUST NOT** block the "Run this followup" button on the template-detail fetches — the button is enabled as soon as the `swap_template` item is present; the comparison panel is a discoverability aid, not a gate.

### FR-11: Frontend — extend prefill construction for `swap_template`

- The system **MUST** extend the `prefillValues` `useMemo` at `ui/src/app/proposals/[id]/page.tsx:136-184` so the `swap_template` branch seeds `template_id = followup.template_id` (NOT `parentStudy.data.template_id`).
- The system **MUST** preserve all other prefill fields verbatim — `cluster_id`, `target`, `query_set_id`, `judgment_list_id`, `objective`, `config` (stop conditions, sampler, pruner, seed, trial_timeout_s, max_trials, time_budget_min, parallelism) come from the parent study unchanged. `search_space_text = JSON.stringify(f.search_space, null, 2)` — the worker's remap step has already populated disjoint params, so the LLM's intent + heuristic defaults are baked in.
- The system **MUST** default the study name to `"${truncatedParentName} — followup #${i+1} (swap_template)"` (matching the existing Tier-A pattern). The existing 200-char parent-name truncation cap applies.
- The system **MUST** preserve the existing `parent: {proposal_id, followup_index}` lineage payload — no schema change.
- The system **MUST NOT** require the operator to manually re-pick the cluster, target, query_set, or judgment_list. The swap is a template-only swap; everything else stays from the parent study.

### FR-12: Glossary additions

- The system **MUST** add two new glossary keys to `ui/src/lib/glossary.ts`:
  - `proposal.followup_kind_swap_template`: `"The LLM suggests trying a different query template entirely. The proposed search space covers params shared with the parent template; disjoint params get heuristic defaults you can edit before submitting."`
  - `proposal.followup_declared_params_diff`: `"Compare the parent template's declared params against the proposed swap target's. Shared params take your LLM-proposed bounds; new params get heuristic defaults; dropped params are silently removed."`
- The system **MUST NOT** modify the existing five followup glossary keys (`proposal.followup_kind_narrow`, `proposal.followup_kind_widen`, `proposal.followup_kind_text`, `proposal.followup_run_button`, `proposal.followup_search_space_diff`).

### FR-13: Lineage reuses Tier-A columns unchanged

- The system **MUST** persist `studies.parent_proposal_id` + `studies.parent_proposal_followup_index` on a `swap_template`-spawned study identically to a `narrow`/`widen`-spawned study (Tier-A behavior unchanged).
- The system **MUST NOT** add a `parent_swap_template_id` column — the kind is recoverable by re-parsing the digest at `parent_proposal_id`'s study.
- The system **MUST NOT** add any new column or migration.

### FR-14: Frontend — prefilled `search_space_text` survives template-dependent autofill

- Per GPT-5.5 cycle-1 F10: the existing modal at `ui/src/components/studies/create-study-modal.tsx:420-457` includes a Step-4 search-space autofill effect from `feat_agent_propose_search_space` that recomputes a starter `search_space` whenever the selected template's `declared_params` change. When the operator clicks "Run this followup" on a `swap_template` card, the modal opens with `template_id = followup.template_id` AND `search_space_text = JSON.stringify(followup.search_space, ...)`. The autofill effect MUST NOT overwrite the prefilled `search_space_text` with a freshly-computed starter space for the swap-target template.
- The system **MUST** add an explicit guard to the Step-4 autofill effect: when `initialValues` is non-null AND `initialValues.search_space_text` is non-empty, the autofill is **suppressed** for the lifetime of that modal-open. The existing condition (auto-fill only when the textarea is the default `'{}'` or empty) likely already covers this, but the spec MUST require an explicit guard + a regression test rather than rely on incidental behavior.
- The system **MUST** add a vitest assertion (in `ui/src/__tests__/components/studies/create-study-modal.test.tsx` or a new file) that opens the modal with `initialValues` carrying a non-empty `search_space_text` and a `template_id` that maps to a known template fixture; waits for any template-dependent effects to settle; asserts the textarea still contains the prefilled JSON (not the auto-generated starter space for the target template).
- Notes: applies to all three actionable kinds (`narrow`, `widen`, `swap_template`); Tier A relied on the existing "default-`'{}'`-only autofill" guard implicitly. This FR makes the guard explicit so a future autofill-effect rewrite can't regress.

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/studies` | **Unchanged.** The existing `body.parent` field already accepts a `swap_template` followup's index. `body.template_id` differs from the parent study's `template_id` for swap-spawned studies — validates via the existing `TEMPLATE_NOT_FOUND` / `SEARCH_SPACE_UNKNOWN_PARAM` / `SEARCH_SPACE_MISSING_DECLARED_PARAM` checks at `backend/app/api/v1/studies.py`. No new error codes. |
| `GET` | `/api/v1/studies/{study_id}/digest` | **Response widened.** `DigestResponse.suggested_followups: list[FollowupItem]` now includes `SwapTemplateFollowup` as a oneOf branch. | `DIGEST_NOT_READY` (404, unchanged). |
| `GET` | `/api/v1/proposals/{proposal_id}` | **Response widened.** Inline `digest.suggested_followups` shape pickup the wider `FollowupItem`. | `PROPOSAL_NOT_FOUND` (404, unchanged). |

No new endpoints. No method or path changes. The only API-surface change is widening the discriminated-union response shape.

### 8.2 Contract rules

- Error body **MUST** match the canonical envelope: `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` (per `_err()` helper at `backend/app/api/v1/studies.py:75-79`).
- Status codes **MUST** be deterministic per scenario.
- Cross-tenant access: N/A (single-tenant MVP1).
- The discriminator field `kind` on `FollowupItem` **MUST** appear in every wire payload; the new `swap_template` variant **MUST** include `template_id` on the wire (a 36-char UUIDv7 string).

### 8.3 Response examples

**Success — `GET /api/v1/studies/{id}/digest` with a `swap_template` item:**

```json
{
  "id": "0190a3b4-1234-7abc-9def-000000000001",
  "study_id": "0190a3b4-1234-7abc-9def-000000000002",
  "narrative": "The study converged on `title_boost=2.1` with NDCG@10 = 0.84 (+0.13 vs baseline). The parameter-importance map shows title_boost dominating (0.78) and the other declared params nearly inert (≤0.04 each), suggesting the current template's parameter shape is poorly matched to this corpus — the `match_phrase_with_slop` template carries `title_boost` + `phrase_slop` and might fit better.",
  "parameter_importance": { "title_boost": 0.78, "tie_breaker": 0.04 },
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
      "kind": "swap_template",
      "rationale": "tie_breaker is nearly inert (importance 0.04) and the `match_phrase_with_slop` template declares `phrase_slop` alongside `title_boost`. Swap to that template — your title_boost winners likely combine well with slop tuning. Disjoint params (`phrase_slop`) get heuristic defaults; tie_breaker is dropped.",
      "template_id": "0190a3b4-1234-7abc-9def-0000000000aa",
      "search_space": {
        "params": {
          "title_boost": { "type": "float", "low": 1.8, "high": 2.4 },
          "phrase_slop": { "type": "int", "low": 0, "high": 5 }
        }
      }
    },
    {
      "kind": "text",
      "rationale": "Consider adding a category_boost parameter to the current template — several winning trials suggest category prioritization matters.",
      "search_space": null
    }
  ],
  "generated_by": "openai:gpt-4o-2024-08-06",
  "generated_at": "2026-05-24T18:00:00Z"
}
```

(The `search_space.phrase_slop` bounds in the `swap_template` item came from `build_starter_search_space({"phrase_slop": "int"})` — the LLM emitted only `title_boost` (the intersection param); the worker filled `phrase_slop` from heuristic defaults during the remap step. The persisted `search_space` reflects the merged result so the operator sees what they're submitting.)

**Failure — `POST /api/v1/studies` with the swap_template flow when the operator-submitted `search_space` violates the existing search-space invariants:**

The error envelope is unchanged from Tier A — no new error codes apply to the create-study endpoint. Existing failures (`INVALID_SEARCH_SPACE`, `SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM`, `TEMPLATE_NOT_FOUND`, `PROPOSAL_NOT_FOUND`, `DIGEST_NOT_FOUND`, `FOLLOWUP_INDEX_OUT_OF_RANGE`) surface identically.

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `FollowupItem.kind` | `narrow`, `widen`, `text`, **`swap_template`** | `backend/app/domain/study/followups.py` — the per-class `Literal[...]` discriminator on `NarrowFollowup`/`WidenFollowup`/`TextFollowup`/`SwapTemplateFollowup`; the source-of-truth tuple `FOLLOWUP_KIND_VALUES: tuple[str, ...] = ("narrow", "widen", "text", "swap_template")` at the same module. Mirrored as `FOLLOWUP_KIND_VALUES` + `type FollowupKind` in `ui/src/lib/enums.ts` with the cited source-of-truth comment. | `suggested-followups-panel.tsx` (kind-based card rendering). Forbidden as a dropdown — operators don't pick the kind, the LLM emits it. |
| `SwapTemplateFollowup.template_id` | Any 36-character `query_templates.id` string. Pydantic enforces length only via `Field(min_length=36, max_length=36)`; **no UUIDv7 parser is run** (per GPT-5.5 cycle-1 F5 — matches the project's existing `ParentFollowupRef.proposal_id` discipline). Worker enforces existence + same-cluster-engine + non-same-as-parent at digest persist time; failures downgrade to `text` via FR-8. | `backend/app/domain/study/followups.py` — the `Field(min_length=36, max_length=36)` on `SwapTemplateFollowup.template_id`; `backend/app/db/models/query_template.py` — `id: Mapped[str] = mapped_column(String(36), primary_key=True)`. | "Run this followup" click handler reads `f.template_id` to seed `PrefillValues.template_id`; not user-pickable. |

No frontend dropdown displays `kind` as an option list — the LLM is the producer and the UI only renders.

### 8.5 Error code catalog

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| _none new_ | — | This spec introduces no new error codes. All worker-side validation failures downgrade in-band (no API error); all `POST /api/v1/studies` failures use existing Tier-A or pre-Tier-A codes. |

## 9) Data model and state transitions

### New entities

**None.** The `FollowupItem` discriminated union widens by one Pydantic variant — no DB table or column changes.

### Modified entities

**`digests.suggested_followups` (JSONB column, no schema change)**

The existing JSONB column accommodates the new `{kind, rationale, template_id, search_space}` shape. The repo-layer returns raw `list[dict]`; the API layer / domain reader applies the widened Pydantic discriminated-union validation at the response-serialization boundary.

A `swap_template` payload row looks like:
```json
[
  {
    "kind": "swap_template",
    "rationale": "...",
    "template_id": "0190a3b4-1234-7abc-9def-0000000000aa",
    "search_space": { "params": { ... } }
  }
]
```

**`studies` lineage columns (no schema change)**

`parent_proposal_id` + `parent_proposal_followup_index` from Tier A apply unchanged. A `swap_template`-spawned study row has `parent_proposal_id` + `parent_proposal_followup_index` set AND `template_id != <parent study's template_id>`; the cross-template hop is implicit in the differing `template_id`.

### Required invariants

- The Tier-A `studies_parent_proposal_pair_check` CHECK constraint continues to apply unchanged: `(parent_proposal_id IS NULL AND parent_proposal_followup_index IS NULL) OR (parent_proposal_id IS NOT NULL AND parent_proposal_followup_index IS NOT NULL AND parent_proposal_followup_index >= 0)`.
- The Tier-A `trg_clear_studies_parent_proposal_on_proposal_delete` BEFORE DELETE trigger continues to apply unchanged — hard-deleting the parent proposal still NULLs both lineage columns atomically.
- `SwapTemplateFollowup.search_space` MUST be a valid `SearchSpace` (cardinality cap 10⁶, `min_length=1`, all the existing per-param validators). Items violating any of those constraints downgrade to `text` (FR-2).
- `SwapTemplateFollowup.template_id` MUST be 36 chars (`Field(min_length=36, max_length=36)`). Items violating downgrade to `text` (FR-2).
- After the worker's remap step, the persisted `search_space` for a `swap_template` item MUST have `params.keys() ⊆ swap_target_declared_params.keys()` — the helper guarantees this by construction. Verified by the FR-3 unit tests.
- A persisted `swap_template` item's `template_id` MUST resolve to a real `query_templates` row at the moment of digest persistence (worker enforces; FR-8). After that, the row may be deleted; nothing in this spec re-validates on read. (Operator submitting a stale swap_template followup whose target was deleted post-digest fails at `POST /api/v1/studies` with `TEMPLATE_NOT_FOUND` — existing code path.)

### State transitions

No new states. The existing `study.status` lifecycle is unchanged. The existing `proposal.status` lifecycle is unchanged.

### Idempotency/replay behavior

- `POST /api/v1/studies` with `body.parent` + a `swap_template`-origin payload is not idempotent (matches Tier A; no `Idempotency-Key` in MVP1).
- The digest worker (FR-7 remap step) is idempotent against the existing per-study digest UNIQUE constraint — re-running the worker after a downgrade-and-fix never produces duplicate downgrade WARN events because the per-study digest is written once.

## 10) Security, privacy, and compliance

- **Threats:**
  1. **LLM hallucinates a `template_id` that doesn't exist OR isn't a UUIDv7.** Mitigation: FR-8 existence check at the worker; FR-1 length check via `Field(min_length=36, max_length=36)`. Both paths downgrade to `text` with the failure rationale visible.
  2. **LLM hallucinates a `template_id` that points at a real template but is the wrong `engine_type`.** Mitigation: FR-8 engine-type check at the worker. Cross-engine swaps downgrade.
  3. **LLM proposes a `search_space` that's runaway-large after the remap step.** Mitigation: `remap_search_space_for_swap_target` raises `InvalidSearchSpaceError` on cap-aware-fallback exhaustion; caller downgrades to `text`. (The disjoint-fill heuristic already has a cap-aware fallback per `feat_agent_propose_search_space` — converts floats to `int[0, 5]` until cardinality ≤ 10⁶.)
  4. **Operator clicks "Run this followup" but the swap target was deleted between digest persist and click.** Mitigation: `POST /api/v1/studies` returns 400 `TEMPLATE_NOT_FOUND` (existing code path). The modal surfaces the error; operator can refresh and try again.
  5. **Cross-tenant lineage leak via `swap_template.template_id`.** N/A in MVP1 (single-tenant). For MVP4: both `query_templates` and `studies` will carry `tenant_id`; the worker's catalogue fetch and existence check MUST be tenant-scoped at MVP4 (forward-looking note, not a Tier-B requirement). The discriminator field carries no PII.
  6. **Operator-facing rationale containing PII.** Same as Tier A — the LLM is instructed not to include query text / document IDs / document bodies in narrative or rationale. Out-of-band, no new vector here.
- **Controls:**
  - All Tier-A digest-worker controls preserved: per-study advisory lock, capability check, daily-budget guard, persist-first then record-cost ordering.
  - The catalogue fetch is one bounded SELECT per digest call; cost is negligible.
  - The remap helper is pure and synchronous; no new I/O.
  - No new secrets introduced.
  - No new external services called.
- **Secrets/key handling:** N/A — reuses existing `OPENAI_API_KEY` from `Settings`.
- **Auditability:** §6 catalogs the three Tier-A audit events with their widened value spaces.
- **Data retention/deletion/export impact:**
  - Hard-deleting a parent proposal still triggers the Tier-A `trg_clear_studies_parent_proposal_on_proposal_delete` trigger — applies identically to `swap_template`-spawned children.
  - Hard-deleting the swap-target template after a `swap_template`-spawned child study has been created: the child study's `template_id` is unaffected (it's a separate FK to `query_templates`; the existing `Study.template_id` FK constraint behavior applies). If the existing FK has `ON DELETE` action that blocks deletion of in-use templates, that protection covers this case automatically. (Spec does not introduce a new behavior here.)

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** Same as Tier A — `swap_template` cards live inside the existing `SuggestedFollowupsPanel` on `/proposals/[id]`. No new routes, no new nav links. The "Run this followup" button opens the existing `<CreateStudyModal>` overlay.
- **Labeling taxonomy:**
  - Per-card kind label for the new variant: **"Swap template"** (badge text). Reads naturally — operators in the search-space-tuning vocabulary recognize "swap" as a discrete cross-template action.
  - Primary action button: **"Run this followup"** (unchanged from Tier A).
  - Collapse toggles: **"Show search space"** / **"Hide search space"** (unchanged); plus the new **"Show declared params"** / **"Hide declared params"** for the side-by-side `declared_params` comparison.
- **Content hierarchy:** A `swap_template` card renders top-to-bottom: kind badge + rationale text → **"Show declared params"** toggle (collapsed by default; reveals side-by-side parent-vs-swap-target table) → "Show search space" toggle (collapsed by default; reveals the proposed `search_space` JSON) → primary "Run this followup" button (right-aligned). Two collapsed details by default keeps the card visually consistent with Tier A's single-detail pattern.
- **Progressive disclosure:** Both detail panes hidden by default. Most operators trust the rationale + the kind badge + click Run.
- **Relationship to existing pages:** Extends the proposal-detail page identically to Tier A. No new pages.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---------|-------------------|---------|-----------|
| `Swap template` kind badge (new) | (new glossary key `proposal.followup_kind_swap_template`) "The LLM suggests trying a different query template entirely. The proposed search space covers params shared with the parent template; disjoint params get heuristic defaults you can edit before submitting." | hover | top |
| `Show declared params` toggle (new) | (new glossary key `proposal.followup_declared_params_diff`) "Compare the parent template's declared params against the proposed swap target's. Shared params take your LLM-proposed bounds; new params get heuristic defaults; dropped params are silently removed." | hover | top |
| Existing badges, search-space toggle, and "Run this followup" button | (existing glossary keys from Tier A — unchanged) | hover | top |

Tooltip placement uses the existing `<InfoTooltip glossaryKey="...">` primitive (already imported in `suggested-followups-panel.tsx`).

### Primary flows

1. **Run a `swap_template` followup (happy path).**
   Operator on `/proposals/<pid>` → scrolls to "Suggested follow-ups" → sees a card with a `Swap template` badge + rationale ("tie_breaker is inert; the `match_phrase_with_slop` template is a better fit") → expands "Show declared params" → sees a side-by-side panel: parent template has `{title_boost, tie_breaker}`; swap target has `{title_boost, phrase_slop}`. `title_boost` is highlighted as shared; `tie_breaker` is greyed out (will be dropped); `phrase_slop` is greyed out on the parent side (new — gets heuristic default) → expands "Show search space" → sees the merged proposal with `title_boost: [1.8, 2.4]` (from the LLM) and `phrase_slop: int[0, 5]` (from the heuristic) → clicks "Run this followup" → `CreateStudyModal` opens. Modal pre-fills `cluster_id`, `target`, `query_set_id`, `judgment_list_id`, `objective`, `config` from the parent study; **`template_id` is the swap target's `template_id` (NOT the parent's)**; `search_space_text` is the merged `search_space` JSON. `name` defaults to `"<parent name> — followup #N (swap_template)"`. Operator reviews, optionally edits any field (e.g., overrides `phrase_slop` bounds), submits. `POST /api/v1/studies` includes `body.template_id = <swap target>` + `body.parent: {proposal_id: pid, followup_index: N-1}`. Returns 201. Operator is navigated to `/studies/<new id>`. The new study row has `parent_proposal_id=<pid>` + `parent_proposal_followup_index=N-1` + `template_id=<swap target>` (different from the parent study's `template_id`).
2. **Skip a `swap_template` followup.** Operator reads the rationale, decides the swap isn't worth it, ignores the card. No state change. Other followups remain actionable.

### Edge/error flows

- **LLM emits `swap_template` with an unknown `template_id`.** Worker FR-8 downgrades to `text` with `[validation failed: swap_template target template not found: <id>] ` prefix. Operator sees the failure prefix on a `Suggestion` card.
- **LLM emits `swap_template` with a `template_id` that equals the parent study's `template_id`.** Worker FR-8 downgrades to `text` with the same-as-parent prefix.
- **LLM emits `swap_template` with a `template_id` whose `engine_type` differs from the parent cluster's.** Worker FR-8 downgrades to `text` with the engine-mismatch prefix.
- **LLM emits `swap_template` with a `search_space` whose intersection ∪ disjoint-fill cardinality exceeds 10⁶.** `remap_search_space_for_swap_target` raises `InvalidSearchSpaceError`; worker FR-7 downgrades to `text` with `[validation failed: search-space cardinality estimate exceeds 10^6 ...] ` prefix.
- **LLM emits `swap_template` whose `search_space` is empty (`{params: {}}`).** Pydantic's `min_length=1` rejects at `FollowupItemAdapter.validate_python`; downgrades to `text` per the existing Tier-A decision-table row. (This is the same root cause as "swap target shares no params with parent" — the LLM had no intersection to populate; per GPT-5.5 cycle-3 F1, the system prompt instructs the LLM to skip `swap_template` in that case rather than emit an empty `search_space`.)
- **LLM emits `swap_template` pointing at a swap target whose `declared_params` share NO keys with the parent template.** Worker FR-7 step 3 calls `remap_search_space_for_swap_target(...)` which raises `InvalidSearchSpaceError` (per the helper's no-trusted-intersection guard); downgrades to `text` with `reason="remap_invalid_search_space"` per FR-7 / AC-15b. Per GPT-5.5 cycle-3 F1, the prompt SHOULD have prevented this — if it happens, the LLM didn't follow instructions; the downgrade preserves the rationale visibly.
- **Operator submits the pre-filled form but the swap-target template was deleted between digest persist and submit.** `POST /api/v1/studies` returns 400 `TEMPLATE_NOT_FOUND` (existing code path). Modal surfaces the error; operator can pick a different template manually OR abandon.
- **Operator's `useTemplate(swap_template_id)` fetch fails (network error, 500).** Card replaces the comparison panel with "Could not load template details — submitting will still work; the comparison view is unavailable." The Run button stays enabled (the prefill construction uses `followup.template_id` directly, not the fetched template detail).
- **Operator's `useTemplate(parent_template_id)` fetch fails.** Same — comparison panel shows the error message; submission still works.
- **Catalogue is empty (no other templates registered for the parent cluster's engine).** Worker FR-7 skips rendering the `<available_templates>` block; system prompt instructs the LLM to skip `swap_template`; no swap_template items are emitted. Operator sees only `narrow`/`widen`/`text` cards.
- **Catalogue is large (e.g., 50 templates).** Prompt token cost grows linearly with catalogue size + per-template `declared_params`. MVP1 single-tenant laptop installs have small catalogues; if a future scale concern emerges, the catalogue can be filtered (e.g., to most-recently-modified). Out of scope for this spec; tracked as a forward concern.
- **Operator clicks "Run this followup" before both template fetches resolve.** The Run button is enabled regardless; prefill construction uses `followup.template_id` (already present in the digest payload). Modal opens with `template_id = swap target` even if the comparison panel never rendered.

## 12) Given/When/Then acceptance criteria

### AC-1: `SwapTemplateFollowup` Pydantic round-trip
- Given a dict `{"kind": "swap_template", "rationale": "swap for slop tuning", "template_id": "0190a3b4-1234-7abc-9def-0000000000aa", "search_space": {"params": {"title_boost": {"type": "float", "low": 1.8, "high": 2.4}}}}`
- When `FollowupItemAdapter.validate_python(d)` is called
- Then it returns a `SwapTemplateFollowup` instance with all fields populated; `serialize_followup_list([item])` round-trips to the same JSON shape (deep-equal).

### AC-2: Backend rejects malformed `swap_template` shape via Tier-A downgrade path
- Given `parse_followup_list([{"kind": "swap_template", "rationale": "bad", "template_id": "too-short", "search_space": {"params": {"x": {"type": "float", "low": 0, "high": 1}}}}], study_id="s", proposal_id="p")`
- When the parser runs
- Then the returned list contains one `TextFollowup` with `rationale` starting with `"[validation failed:"`, `search_space=None`, AND a `digest_followup_validation_downgraded` WARN event was emitted with `original_kind="swap_template"`, `study_id="s"`, `proposal_id="p"`.

### AC-3: `remap_search_space_for_swap_target` — trusted intersection + disjoint fill + dropped parent + ignored LLM
- Given `parent_declared_params={"title_boost": "float", "tie_breaker": "float"}`, `swap_target_declared_params={"title_boost": "float", "phrase_slop": "int"}`, `llm_search_space=SearchSpace(params={"title_boost": FloatParam(type="float", low=1.8, high=2.4), "rogue_param": FloatParam(type="float", low=0, high=1)})`
- When `remap_search_space_for_swap_target(...)` is called
- Then the returned `RemapResult` has `trusted_intersection_param_names=["title_boost"]`, `disjoint_fill_param_names=["phrase_slop"]`, `dropped_parent_param_names=["tie_breaker"]`, `ignored_llm_param_names=["rogue_param"]`, AND `search_space.params == {"title_boost": FloatParam(type="float", low=1.8, high=2.4), "phrase_slop": IntParam(type="int", low=0, high=5)}` (the `phrase_slop` bounds match `build_starter_search_space({"phrase_slop": "int"})`'s output; `rogue_param` is NOT in the output even though the LLM emitted bounds for it — the LLM had no parent-side signal to ground those bounds, per the GPT-5.5 cycle-1 F1 fix).

### AC-4: Remap raises `InvalidSearchSpaceError` when swap-target declares no params
- Given `parent_declared_params={"x": "float"}`, `swap_target_declared_params={}`, `llm_search_space=SearchSpace(params={"x": FloatParam(type="float", low=0, high=1)})`
- When `remap_search_space_for_swap_target(...)` is called
- Then it raises `InvalidSearchSpaceError`.

### AC-4b: Remap raises `InvalidSearchSpaceError` when trusted intersection is empty (cycle-3 F1)
- Given `parent_declared_params={"x": "float"}`, `swap_target_declared_params={"y": "int"}` (no shared params), `llm_search_space=SearchSpace(params={"x": FloatParam(type="float", low=0, high=1)})`
- When `remap_search_space_for_swap_target(...)` is called
- Then it raises `InvalidSearchSpaceError` (the helper rejects no-trusted-intersection swaps; the worker's existence/engine-check pipeline routes this through the `remap_invalid_search_space` reason code).

### AC-5: Worker downgrades unknown-template `swap_template` to `text`
- Given a digest stub LLM payload containing one `swap_template` item with `template_id="0000aaaa-bbbb-cccc-dddd-000000000000"` (no matching row) and an otherwise-valid `search_space`
- When the worker persists the digest
- Then the persisted `digests.suggested_followups[i]` has `kind="text"`, `rationale` starts with `"[validation failed: swap_template target template not found:"`, `search_space=None`, AND a `digest_followup_validation_downgraded` WARN was emitted with `original_kind="swap_template"`, `reason="not_found"`.

### AC-6: Worker downgrades same-as-parent `swap_template` to `text`
- Given a digest stub LLM payload containing one `swap_template` item with `template_id == study.template_id`
- When the worker persists the digest
- Then the persisted item is `kind="text"` with `rationale` starting with `"[validation failed: swap_template same-as-parent template_id:"`, AND the WARN has `reason="same_as_parent"`.

### AC-7: Worker downgrades cross-engine `swap_template` to `text`
- Given a parent study against a cluster with `engine_type="opensearch"` and a `swap_template` item whose target template has `engine_type="elasticsearch"`
- When the worker persists the digest
- Then the persisted item is `kind="text"` with `rationale` starting with `"[validation failed: swap_template engine_type mismatch (parent=opensearch, target=elasticsearch):"`, AND the WARN has `reason="engine_type_mismatch"`.

### AC-8: Worker happy-path remap on `swap_template` persists merged `search_space`
- Given a valid `swap_template` item from the LLM (trusted intersection on `title_boost`; swap target also declares `phrase_slop`), passed through the worker remap step
- When the worker persists
- Then the persisted item has `kind="swap_template"`, `template_id` unchanged, `rationale` unchanged, `search_space.params` containing `title_boost` (LLM bounds) AND `phrase_slop` (heuristic-default bounds), AND a structlog INFO `digest_followup_swap_template_remapped` was emitted with fields `study_id`, `proposal_id`, `target_template_id`, `trusted_intersection_param_names`, `disjoint_fill_param_names`, `dropped_parent_param_names`, `ignored_llm_param_names`.

### AC-9: API surfaces the widened `FollowupItem` shape
- Given a `digests.suggested_followups` row containing one `swap_template` item
- When `GET /api/v1/studies/{id}/digest` is called
- Then the response JSON's `suggested_followups[i]` has the four fields `kind="swap_template"`, `rationale`, `template_id`, `search_space`, AND the OpenAPI schema's `FollowupItem` oneOf includes a `SwapTemplateFollowup` branch with the same shape.

### AC-10: UI renders the `swap_template` card with badge + comparison + diff toggles + Run button
- Given a proposal whose digest has one `swap_template` followup at index 0
- When the operator loads `/proposals/<pid>` (with `useTemplate(parent)` and `useTemplate(swap_target)` both resolved)
- Then the card at `data-testid="followup-0-card"` shows: a badge containing "Swap template"; the rationale text; an expandable `<details>` containing `data-testid="followup-0-declared-params-diff"` with parent-side panel `followup-0-parent-declared-params` and swap-side panel `followup-0-swap-declared-params`; an expandable `<details>` for "Show search space" with the proposed-search-space JSON visible when expanded; a "Run this followup" button at `data-testid="followup-0-run"`.

### AC-11: "Run this followup" on a `swap_template` card pre-fills `template_id = followup.template_id`
- Given a parent study `S` with `template_id = "A"`, a proposal `P` referencing `S`, a digest with one `swap_template` followup whose `template_id = "B"` (a different real template, same `engine_type`)
- When the operator clicks the Run button on the `swap_template` card
- Then `CreateStudyModal` opens with `template_id` field pre-filled to `"B"` (not `"A"`); all other prefill fields come from `S` (cluster, target, query_set, judgment_list, objective, config); the `name` field defaults to `"<S.name> — followup #1 (swap_template)"`.

### AC-12: Submitting the swap-template-prefilled form persists the new study with `template_id="B"` AND lineage
- Given the modal pre-filled per AC-11
- When the operator clicks Submit
- Then `POST /api/v1/studies` is called with `body.template_id="B"`, `body.parent={proposal_id: P.id, followup_index: 0}`, returns 201, and the new `studies` row has `template_id="B"`, `parent_proposal_id=P.id`, `parent_proposal_followup_index=0`.

### AC-13: Catalogue-empty path emits no `swap_template`
- Given a digest call where the parent cluster's `engine_type` has only one registered template (the parent study's own template) — catalogue is empty after filtering
- When the worker assembles the user prompt
- Then the rendered user prompt has NO `<available_templates>` block, AND the LLM stub never emits a `swap_template` item, AND the persisted digest contains zero `swap_template` items.

### AC-14: `FOLLOWUP_KIND_VALUES` source-of-truth grep gate stays aligned
- Given the backend `FOLLOWUP_KIND_VALUES` tuple and the frontend `FOLLOWUP_KIND_VALUES` `as const` array
- When `scripts/ci/verify_enum_source_of_truth.sh` runs (in CI or pre-commit)
- Then it passes, confirming both lists are `("narrow", "widen", "text", "swap_template")` and `['narrow', 'widen', 'text', 'swap_template'] as const` respectively.

### AC-15: Worker truncation happens BEFORE swap_template existence/engine checks (cycle-1 F7)
- Given an LLM payload of 6 followups, the 6th of which is a `swap_template` item pointing at a non-existent template; AND the worker's Step-13 merge step (drift followup not prepended in this scenario)
- When the worker assembles the final list
- Then the list is truncated to 5 FIRST (so the 6th `swap_template` item is dropped before any DB lookup); AND no `digest_followup_validation_downgraded` event is emitted for the dropped 6th item (because it never reached the existence-check stage); AND no DB query is issued for its non-existent template_id (verified via a query-count assertion in the integration test fixture).

### AC-15b: Worker emits `reason="remap_invalid_search_space"` on InvalidSearchSpaceError (cycle-2 F4)
- Given a `swap_template` item whose LLM `search_space` + swap-target heuristic fill produces a `SearchSpace` exceeding the 10⁶ cardinality cap
- When the worker calls `remap_search_space_for_swap_target(...)` and it raises `InvalidSearchSpaceError`
- Then the worker emits `digest_followup_validation_downgraded` with `original_kind="swap_template"`, `reason="remap_invalid_search_space"`, AND the persisted item is `kind="text"` with `rationale` starting with `"[validation failed:"`.

### AC-16: Prefilled `search_space_text` survives template-dependent autofill (FR-14)
- Given the modal opens with `initialValues.template_id = "B"` (different from the previously selected template), `initialValues.search_space_text = '{"params":{"phrase_slop":{"type":"int","low":0,"high":5}}}'`, and the template B's `declared_params` are queryable
- When the modal mounts, the form reset runs, and all template-dependent effects settle (template-detail query resolves, query-set list updates, etc.)
- Then the textarea bound to `search_space_text` still contains the prefilled JSON character-for-character. The auto-fill effect from `feat_agent_propose_search_space` does NOT overwrite the prefilled value.

## 13) Non-functional requirements

- **Performance:**
  - The new remap helper is O(n) in param count (n ≤ low double digits in MVP1). Negligible.
  - The worker's added per-digest queries: one parent-template SELECT + one catalogue SELECT + one per-`swap_template`-item template SELECT (cached for duplicates within a call). Bounded by template-registry cardinality (MVP1: ≤ dozens). Adds ≤ 100ms to digest-worker wall-clock at single-laptop scale.
  - Prompt token cost grows by the size of the `<parent_template_declared_params>` block (small — handful of `name: type-string` entries) + the `<available_templates>` block (linear in catalogue size, per-entry small). MVP1 budget gate at `backend/workers/digest.py` continues to enforce the per-day cap; the modest token-cost bump is well within the existing budget.
  - Frontend: two extra `useTemplate(...)` fetches per `swap_template` card (cached by TanStack Query; subsequent renders re-use). No impact on initial render time of the panel (Tier-A loading-state pattern carries forward).
- **Reliability:** No new SLO. The worker's existing best-effort retry / advisory-lock / idempotency-guard infrastructure applies unchanged. The remap helper is pure → never raises non-`InvalidSearchSpaceError` exceptions.
- **Operability:**
  - One new structlog event type: `digest_followup_swap_template_remapped` (INFO) — emitted once per successful remap with `study_id`, `proposal_id`, `target_template_id`, `trusted_intersection_param_names`, `disjoint_fill_param_names`, `dropped_parent_param_names`, `ignored_llm_param_names` (per GPT-5.5 cycle-2 F2 — field names match `RemapResult` exactly; the cycle-1 patch left the older 3-field naming in this section). The existing `digest_followup_validation_downgraded` event picks up `original_kind="swap_template"` and an optional `reason` sub-field per FR-8 (four reason codes — see §6).
  - No new error codes (§8.5).
  - No new metrics in MVP1.
- **Accessibility/usability:**
  - The `Swap template` badge has `aria-label="Swap template"` matching the visible badge text.
  - The new `<details>` for declared-params comparison uses standard semantic HTML with `aria-expanded` (matching the existing search-space `<details>` pattern from Tier A).
  - The side-by-side diff is a two-column responsive layout; on narrow viewports it stacks vertically (parent above swap target). Keyboard nav: tab order is badge → both details (in DOM order) → Run button.

## 14) Test strategy requirements (spec-level)

- **Unit tests (`backend/tests/unit/`):**
  - `backend/tests/unit/domain/study/test_followups.py` (extend existing): per-kind tests for `SwapTemplateFollowup`: valid round-trip; rejection on `template_id` length != 36; rejection on `search_space=None`; rejection on `extra="forbid"` violation; tuple/literal alignment (`FOLLOWUP_KIND_VALUES` has 4 entries).
  - `backend/tests/unit/domain/study/test_followups_backcompat.py` (extend existing): legacy `list[str]` rows still wrap to `text`-only — no false `swap_template` parsing.
  - `backend/tests/unit/domain/study/test_template_swap.py` (new file): cover `remap_search_space_for_swap_target` for: trusted-intersection-only / mixed-intersection-and-disjoint-fill / dropped-only cases; empty swap-target declared_params raises `InvalidSearchSpaceError`; empty trusted intersection raises `InvalidSearchSpaceError` (per GPT-5.5 cycle-3 F1 — the test name should be `test_no_trusted_intersection_raises`; this is the "the LLM picked a swap target with no shared params" case the helper rejects); cardinality-cap blowup via cap-aware-fallback exhaustion raises; assertion that an LLM-emitted param outside `parent_names ∩ swap_names` lands in `ignored_llm_param_names` and NOT in `RemapResult.search_space.params` (GPT-5.5 cycle-1 F1 regression guard); assertion that `disjoint_fill_param_names` is empty when every swap-target param is in the trusted intersection AND `build_starter_search_space` is NOT called in that case (GPT-5.5 cycle-1 F2 regression guard); resulting `RemapResult.search_space` is always `SearchSpace.model_validate`-passing. **No** disjoint-fill-only test (per GPT-5.5 cycle-3 F1: a disjoint-only swap is unreachable on the worker path because the LLM-emitted `SearchSpace.params` must be non-empty AND the helper now requires the trusted intersection to be non-empty). Note (per GPT-5.5 cycle-1 F6): no "empty LLM search_space" test case — the helper signature accepts a validated `SearchSpace` which has `min_length=1`; the empty-params path is exercised at the `parse_followup_list`/worker layer, not the remap helper.
  - `backend/tests/unit/workers/test_digest_followup_validation.py` (extend existing): swap_template fixture with `search_space` exceeding cap at the **parse-followup-list** layer → downgrade to `text` (WARN with `original_kind="swap_template"`); swap_template fixture with unknown `template_id` → downgrade (`reason="not_found"`); swap_template fixture with same-as-parent → downgrade (`reason="same_as_parent"`); swap_template fixture with cross-engine target → downgrade (`reason="engine_type_mismatch"`); swap_template fixture whose **post-remap** `SearchSpace` exceeds the 10⁶ cardinality cap (after disjoint heuristic fill) → downgrade (`reason="remap_invalid_search_space"`, per GPT-5.5 cycle-2 F4); swap_template happy-path remap → persisted item has merged `search_space`. The 4 `reason` codes match the §6 + D-11 set.
- **Integration tests (`backend/tests/integration/`):**
  - `backend/tests/integration/test_digest_followup_roundtrip.py` (extend existing): stub LLM emits one `swap_template` item against a fixture catalogue with one extra template; assert persisted JSONB contains the merged search_space; assert `GET /api/v1/studies/{id}/digest` returns the structured shape with all four fields.
  - `backend/tests/integration/test_studies_with_parent_followup.py` (extend existing): `POST /api/v1/studies` with `body.template_id = <swap target>` + `body.parent` pointing at the parent proposal's swap_template index; assert the persisted row has `template_id = <swap target>` AND lineage columns set.
- **Contract tests (`backend/tests/contract/`):**
  - `backend/tests/contract/test_digest_response_shape.py` (extend existing): assert the OpenAPI `FollowupItem` schema's oneOf includes the `SwapTemplateFollowup` branch with the four required fields.
  - `backend/tests/contract/test_proposal_detail_shape.py` (extend existing): same for `_DigestEmbed.suggested_followups`.
  - `backend/tests/contract/test_enum_source_of_truth_helpers.py` (existing): assert the helper resolves `FOLLOWUP_KIND_VALUES` to a 4-element tuple matching `("narrow", "widen", "text", "swap_template")`.
- **E2E tests (`ui/tests/e2e/`):**
  - `ui/tests/e2e/followup_run.spec.ts` (extend existing): seed two templates A + B sharing one param (e.g., `title_boost`) + B having one extra (e.g., `phrase_slop`); seed a study against A; create a proposal + digest with one `swap_template` followup pointing at B; navigate to `/proposals/<pid>`; click "Run this followup" on the swap_template card; assert modal opens with `template_id=B`; submit; assert navigation to `/studies/<new id>` AND `GET /api/v1/studies/{id}` returns `template_id=B`. **Lineage columns (`parent_proposal_id` + `parent_proposal_followup_index`) are NOT exposed on `StudyDetail` per Tier-A D-5** — per GPT-5.5 cycle-1 F11: the E2E suite asserts only template_id (visible via the API) + the new-study navigation; the lineage-column assertion lives in the integration test `test_studies_with_parent_followup.py` (above) where the test fixture has direct DB-row access. **Real-backend** per CLAUDE.md (no `page.route()` mocking).

## 15) Documentation update requirements

- `docs/01_architecture/data-model.md` — extend the `digests.suggested_followups` JSONB-shape note to include the `swap_template` variant. Add an example payload.
- `docs/01_architecture/llm-orchestration.md` — describe the new `swap_template` kind in the digest LLM output catalogue + the `<available_templates>` + `<parent_template_declared_params>` prompt blocks + the worker's remap step.
- `docs/02_product/planned_features/feat_digest_executable_followups_swap_template/` — this spec lives here; this folder is single-phase (no `phase2_idea.md`).
- `docs/03_runbooks/` — extend any digest-debugging runbook to mention the new structlog event `digest_followup_swap_template_remapped` (INFO, success path) + the four downgrade `reason` codes for `swap_template`.
- `docs/04_security/` — N/A (no new secret or data-flow surface beyond the catalogue SELECT, which is internal-only).
- `docs/05_quality/testing.md` — no change required; new test files follow the existing layer convention.
- `state.md` — update active-work / queued sections to mark `feat_digest_executable_followups_swap_template` as in-progress when the spec is approved and the plan kicks off.
- `CLAUDE.md` — no change. No new conventions or absolute rules.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. MVP1 single-tenant; ship behind no flag.
- **Migration/backfill expectations:** None. The Tier-A JSONB column + lineage columns + trigger + CHECK constraint apply unchanged.
- **Operational readiness gates:** None new.
- **Release gate:**
  - All ACs pass in CI (unit + integration + contract + E2E layers).
  - `make lint`, `make typecheck`, `pnpm lint`, `pnpm typecheck`, `pnpm build` all green.
  - GPT-5.5 cross-model review on the spec and the implementation plan complete (per CLAUDE.md cross-model policy).
  - Gemini Code Assist findings on the PR adjudicated per CLAUDE.md.
  - `scripts/ci/verify_enum_source_of_truth.sh` passes (`FOLLOWUP_KIND_VALUES` 4-tuple aligned between Python and TS).

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks (assigned by impl-plan) | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-14 | Domain — add `SwapTemplateFollowup` + widen tuple/alias | `backend/tests/unit/domain/study/test_followups.py` (extend) | `docs/01_architecture/data-model.md` |
| FR-2 | AC-2 | Defensive parser pickup of new variant | `backend/tests/unit/domain/study/test_followups.py` (extend) | — |
| FR-3 | AC-3, AC-4, AC-4b | New domain module `template_swap.py` + `RemapResult` | `backend/tests/unit/domain/study/test_template_swap.py` (new) | `docs/01_architecture/llm-orchestration.md` |
| FR-4 | AC-2, AC-5–AC-8 | Validator + downgrade (no new code path; covered by FR-2 + worker tests) | `backend/tests/unit/workers/test_digest_followup_validation.py` (extend) | — |
| FR-5 | AC-9, AC-14 | Extend `DIGEST_RESPONSE_SCHEMA` + per-item `template_id` + empty-string sentinel | `backend/tests/integration/test_digest_followup_roundtrip.py` (extend); `backend/tests/contract/test_digest_response_shape.py` (extend) | `docs/01_architecture/llm-orchestration.md` |
| FR-6 | AC-8, AC-13 | LLM prompt updates (system + user.jinja) | (covered via worker integration test) | `prompts/digest_narrative.system.md`, `prompts/digest_narrative.user.jinja` |
| FR-7 | AC-8, AC-13 | Worker — fetch catalogue + parent declared_params + remap step | `backend/tests/integration/test_digest_followup_roundtrip.py` (extend); `backend/tests/unit/workers/test_digest_followup_validation.py` (extend) | `docs/01_architecture/llm-orchestration.md` |
| FR-8 | AC-5, AC-6, AC-7, AC-15b | Worker — template existence + same-as-parent + engine_type + remap-invalid checks | `backend/tests/unit/workers/test_digest_followup_validation.py` (extend) | — |
| FR-9 | AC-10, AC-14 | Frontend — extend `FOLLOWUP_KIND_VALUES` + `KIND_LABELS` | `ui/src/__tests__/components/proposals/suggested-followups-panel.test.tsx` (extend); `ui/src/__tests__/lib/enums.test.ts` (extend or new) | — |
| FR-10 | AC-10 | Frontend — render `swap_template` card with declared-params diff | `ui/src/__tests__/components/proposals/suggested-followups-panel.test.tsx` (extend) | — |
| FR-11 | AC-11, AC-12 | Frontend — extend prefill construction for `swap_template` | `ui/tests/e2e/followup_run.spec.ts` (extend) | — |
| FR-12 | AC-10 | Glossary additions (`proposal.followup_kind_swap_template`, `proposal.followup_declared_params_diff`) | `ui/src/__tests__/lib/glossary.test.ts` (extend) | — |
| FR-13 | AC-12 | Lineage reuses Tier-A columns (no new code, contract clarification) | (covered by AC-12 integration test) | — |
| FR-14 | AC-16 | Frontend — explicit guard against autofill overwriting prefilled `search_space_text` | `ui/src/__tests__/components/studies/create-study-modal.test.tsx` (extend or new) | — |

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1 through AC-16, including AC-4b and AC-15b) pass in CI.
- [ ] All test layers (unit/integration/contract/e2e) are green.
- [ ] Documentation updates across docs/01–05 are merged (§15).
- [ ] Rollout gates from §16 are satisfied.
- [ ] Cross-model review (GPT-5.5) on this spec and the forthcoming implementation plan completed and adjudicated.
- [x] Deferred-phase tracking: N/A (single-phase delivery). Tier C `edit_template` is tracked at sibling [`backlog_feat_digest_template_edit_followups`](../../../02_product/planned_features/backlog_feat_digest_template_edit_followups/idea.md).
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

- **None.** Auto mode operated under §19 D-1 through D-N below; all forks were decided with the most defensible default and documented.

### Decision log

- **D-1 — 2026-05-24 — `kind` discriminator value is `swap_template` (snake_case, single token).** Rationale: matches the project's existing pattern (`narrow`, `widen`, `text` are all single tokens; `swap_template` follows the same convention). Idea brief locked this literal; spec preserves verbatim. Alternative `swap` was rejected because the operator vocabulary needs the `template` suffix to disambiguate from "swap to a different `objective.metric`" (a future Tier-X concern).
- **D-2 — 2026-05-24 — `<available_templates>` catalogue shape: full `declared_params` per template, filtered to parent cluster's `engine_type`, excluding the parent study's own template.** Rationale: the LLM needs `declared_params` to compute the intersection / pick a swap with high overlap; filtering to same `engine_type` prevents cross-engine hallucinations the worker would only downgrade anyway; excluding the parent's own template prevents same-as-parent hallucinations. Per-template payload is small (`{id, name, version, declared_params}`); catalogue scale at MVP1 is low (≤ dozens of templates per laptop install). Caching at the worker layer is premature — `Settings`-level reuse can land later if cost becomes a concern.
- **D-3 — 2026-05-24 — JSON-schema strategy: add `template_id: {"type": "string"}` to every item, require it, AND instruct LLM to emit `""` for non-swap kinds; worker treats empty-string as absent before constructing the `FollowupItem`.** Rationale: OpenAI strict-mode schemas reject `oneOf`/`anyOf` at the items level + reject optional properties (every property in `required`). The Tier-A worker already uses the same empty-string sentinel pattern for `search_space_json` (worker.py:175-184). Mirroring that pattern keeps the worker contract uniform. The Pydantic dispatch via `FollowupItemAdapter.validate_python` enforces the per-kind correctness post-clean. Alternative (per-item `oneOf`) was rejected because strict mode doesn't accept it; alternative (drop strict mode for digest calls) was rejected because the per-call cost-per-token of unstructured output + the loss of guaranteed-shape responses outweighs the schema-shape ugliness.
- **D-4 — 2026-05-24 — Worker enforces `template_id` existence + same-as-parent + engine_type checks; downgrade-to-`text` on any failure.** Rationale: validates at the moment of digest persist (when the worker has cheap SQL access to `query_templates`); downgrades preserve operator-visible rationale. The alternative (rely on `POST /api/v1/studies` to reject at click time) was rejected because the operator's "click → 400" experience is worse than the digest-visible `[validation failed: ...]` prefix; the latter is a debuggable signal that the LLM hallucinated. The check happens **after** Pydantic validation (existence/engine checks need real DB rows) but **before** the persist step.
- **D-5 — 2026-05-24 — `remap_search_space_for_swap_target` lives at `backend/app/domain/study/template_swap.py` as a sibling to `search_space_defaults.py`.** Rationale: pure domain logic, no I/O; co-located with `search_space_defaults.py` which it consumes; matches the project's "one concern per module" pattern for domain helpers. Alternative (folding into `followups.py`) was rejected — `followups.py` is the discriminated-union contract; mixing transformation logic into the contract module would conflate read-shape with write-pipeline.
- **D-6 — 2026-05-24 — Disjoint params get heuristic defaults from `build_starter_search_space`, not from the LLM.** Rationale: the LLM has no signal at all for params the parent study never used (no parameter-importance, no winning-trial cluster, no parent bounds to transform). Asking the LLM to "make up" disjoint bounds invites hallucination. The heuristic helper is the single source of truth for "default bounds for an undiscussed param" and is already proven through `feat_agent_propose_search_space`. Alternative (operator-pick disjoint bounds in a separate step) was rejected — adds a second decision point, defeats the "one click" framing.
- **D-7 — 2026-05-24 — Dropped params are silently dropped (INFO event only); no `text`-followup downgrade for that case.** Rationale: dropping a param the swap target doesn't declare is correct behavior, not a failure. The operator's mental model is "swap to template B; B doesn't care about tie_breaker, so it's not in the new search space." Surfacing as a `text` downgrade would conflate normal-path drop with validation-failure drop and confuse the operator. The INFO event provides observability for ops debugging.
- **D-8 — 2026-05-24 — Side-by-side `declared_params` comparison is in the UI, NOT in the LLM rationale.** Rationale: the LLM rationale is short prose; the UI is where structured comparisons belong. Putting a giant "DROPPED PARAMS / NEW PARAMS / SHARED PARAMS" list in the rationale wastes tokens, fights against the rationale's narrative purpose, and would still need the UI version to be discoverable.
- **D-9 — 2026-05-24 — UI lazy-fetches BOTH `useTemplate(parent_template_id)` and `useTemplate(swap_template_id)` for the comparison panel; both gated on the presence of at least one actionable `swap_template` followup.** Rationale: mirrors Tier-A's `useStudy(parentStudyId)` lazy-fetch pattern (only fetch when an actionable followup is present). Avoids extra fetches on proposals that have no swap-template followups. The Run button doesn't gate on the fetches (prefill uses `followup.template_id` directly).
- **D-10 — 2026-05-24 — No new error codes on `POST /api/v1/studies`.** Rationale: a `swap_template`-spawned submission uses the existing `body.template_id` field with a non-parent template ID; existing validation paths (`TEMPLATE_NOT_FOUND` if the operator-edited target was deleted; `SEARCH_SPACE_UNKNOWN_PARAM` / `SEARCH_SPACE_MISSING_DECLARED_PARAM` if the operator edited the search space to mismatch the swap target's declared_params) all apply unchanged.
- **D-11 — 2026-05-24 — No new audit event types; widen Tier-A event allowed-value spaces only.** Rationale: Tier A pre-shaped three audit events for MVP2 activation. This spec's behavior fits inside those three events with the `followup_kind` allowed-value space widened to include `swap_template` and the `digest.followup_validation_downgraded.reason` sub-field gaining four allowed values. Introducing new event types would fragment the audit catalogue without adding observability.
- **D-12 — 2026-05-24 — Cross-engine swap_template is downgraded at digest time (FR-8), not at click time.** Rationale: the worker has the data (parent cluster's `engine_type`, target template's `engine_type`); the check is cheap; downgrading at digest time preserves rationale visibility. The post-submit `POST /api/v1/studies` cluster-engine validation would also catch this, but late-failure is worse UX.
- **D-13 — 2026-05-24 — Empty catalogue (no other templates of the parent cluster's engine type) skips the `<available_templates>` prompt block AND the system prompt instructs the LLM to skip the kind.** Rationale: emitting `swap_template` with no swap candidates would always downgrade — pointless tokens. The block-presence-as-signal pattern matches the existing optional blocks in `prompts/digest_narrative.user.jinja` (e.g., `{% if confidence %}<confidence>`).
- **D-14 — 2026-05-24 — `RemapResult` is a frozen slots-dataclass, not a Pydantic model.** Rationale: the helper is internal; no need for serialization or external validation; frozen+slots is the lightest-weight value-object pattern. Matches `StarterSearchSpace` (sibling in `search_space_defaults.py:101-112`).
- **D-15 — 2026-05-24 — Swap-target template ID is NOT exposed in lineage as a new column; it's recoverable via the digest at `parent_proposal_id`.** Rationale: the lineage data store is the JSONB digest; adding `parent_swap_template_id` to `studies` would duplicate. The child study's own `template_id` differs from the parent's; the diff is implicit in the existing data.
- **D-16 — 2026-05-24 — No special handling for `swap_template` inside the Tier-A `parse_followup_list` decision table beyond the new kind being recognized.** Rationale: the table's existing rows ("`list[dict]` with valid `kind` + passing `search_space` → adapter validate", "`list[dict]` with valid `kind` but failing `search_space` → downgrade", etc.) generalize naturally. The Pydantic dispatch handles per-kind correctness; downgrades emit `original_kind="swap_template"` automatically.
- **D-17 — 2026-05-24 (cycle-1 F1 accept) — Trusted intersection is `parent_names ∩ swap_names ∩ llm_names`, not `swap_names ∩ llm_names`.** Rationale: the LLM only has signal for params the parent study actually exercised; an LLM-emitted entry for a param the parent never declared is hallucination regardless of whether the swap target re-declares it. Trusted intersection narrows to "params both templates carry AND the LLM saw bounds for"; the rest flow through heuristic fill or get ignored.
- **D-18 — 2026-05-24 (cycle-1 F2 accept) — `remap_search_space_for_swap_target` skips `build_starter_search_space(...)` when the disjoint-fill set is empty.** Rationale: the helper raises `InvalidSearchSpaceError` on empty `declared_params` (line 167-169 of `search_space_defaults.py`). The intersection-only path is legitimate (e.g., swap target's `declared_params` is a strict subset of the parent's intersected with LLM emissions). Guard with an `if disjoint_fill:` branch and skip when empty.
- **D-19 — 2026-05-24 (cycle-1 F3 accept) — `RemapResult` splits diagnostics into `dropped_parent_param_names` + `ignored_llm_param_names`.** Rationale: parent-dropped (declared by parent but not swap target) and LLM-ignored (LLM-emitted but not in trusted intersection) are different concerns operationally: parent-dropped is shown to the operator in the side-by-side declared-params diff; LLM-ignored is observability for "is the LLM hallucinating params often?" Conflating them into one field obscures both signals.
- **D-20 — 2026-05-24 (cycle-1 F4 accept) — No JSON-schema conditional; uniform `template_id: str` field + empty-string sentinel + worker pre-clean.** Rationale: OpenAI strict-mode schemas don't accept `oneOf`/`anyOf`/`if`/`then` at the items level AND require every property in `required`. The "uniform property + worker pre-clean" pattern mirrors Tier-A's `search_space_json: str` workaround (worker comment lines 175-184). Per-kind correctness is enforced by the Pydantic discriminated-union dispatch after the worker drops empty `template_id` keys for non-swap items.
- **D-21 — 2026-05-24 (cycle-1 F5 accept) — `SwapTemplateFollowup.template_id` validated by length only, not UUIDv7 shape.** Rationale: matches the Tier-A `ParentFollowupRef.proposal_id` discipline (`Field(min_length=36, max_length=36)` only — no UUID parser); existence is enforced by the worker's FK lookup. Adding a UUIDv7 pattern validator would diverge from the project's existing conventions for no operational gain.
- **D-22 — 2026-05-24 (cycle-1 F6 accept) — No empty-LLM-search_space test case in `test_template_swap.py`.** Rationale: the helper signature accepts a validated `SearchSpace` which Pydantic guarantees is non-empty (`min_length=1` on `params`). The empty-params path is exercised at `parse_followup_list` / worker tests, not the remap helper. Test scope clarified to avoid asking the suite to verify behavior that the type signature already prevents.
- **D-23 — 2026-05-24 (cycle-1 F7 accept) — Worker truncates to 5 BEFORE running swap_template existence/engine checks + remap.** Rationale: items that get truncated never persist; running DB lookups + emitting WARN/INFO events for them wastes resources and pollutes logs. Reordering Step-13 to `(merge → truncate → per-swap_template existence-and-engine-check-and-remap)` ensures all logging + DB lookups apply only to persisted items. The reordering is observable in AC-15.
- **D-24 — 2026-05-24 (cycle-1 F8 accept) — Pre-shaped audit event allowed-value spaces include `text`.** Rationale: Tier-A FR-11 explicitly allows `body.parent` to point at a `text`-kind followup (operator may chain off a `text` suggestion with a manually authored search_space). The existing parser also emits `original_kind="text"` when a `text` item itself is malformed (`backend/app/domain/study/followups.py:128-156` + `_try_text_only`). Narrowing the event-allowed-value space to exclude `text` would mis-document existing code behavior.
- **D-25 — 2026-05-24 (cycle-1 F9 accept) — Worker emits `digest_followup_validation_downgraded` directly for FR-8 existence/engine checks; domain `_emit_downgrade_warn` is NOT extended.** Rationale: the domain helper's purpose is the Pydantic-validation downgrade path (covered for `swap_template` automatically via FR-2). Worker-layer concerns (existence + engine compatibility) belong in the worker; emitting the same event type + adding a `reason` sub-field keeps the runbook grep working uniformly without polluting the domain helper's signature with worker-layer parameters. Unit test must lock the exact field set.
- **D-26 — 2026-05-24 (cycle-1 F10 accept) — FR-14 added: explicit autofill-suppression guard + regression test.** Rationale: the create-study modal's Step-4 autofill effect from `feat_agent_propose_search_space` could overwrite the prefilled `search_space_text` when `template_id` changes. The existing implicit guard ("autofill only when textarea is default `'{}'`") is probably sufficient but spec must require an explicit guard + test so a future autofill rewrite can't regress. Applies to all actionable kinds, not just `swap_template`.
- **D-27 — 2026-05-24 (cycle-1 F11 accept) — E2E asserts `template_id` via API (visible on `StudyDetail`); lineage-column assertions move to the integration-test layer.** Rationale: Tier-A D-5 explicitly keeps `parent_proposal_id` + `parent_proposal_followup_index` off `StudyDetail`. The E2E suite asserts what the API exposes (`template_id=B`); the integration test has direct DB-row access and asserts lineage columns. This is the right test-layer split per the project's testing convention (real-backend E2E for browser-visible behavior; integration for cross-layer DB invariants).
- **D-28 — 2026-05-24 (cycle-1 F12 accept) — Every `FollowupKind` branching site uses either `Record<FollowupKind, …>` lookup OR explicit switch + `assertNever`.** Rationale: TS discriminated-union narrowing catches missing branches inside `Record<FollowupKind, …>` lookups and exhaustive switches, but NOT inside `if (f.kind === '…') {…} else if (…)` chains with implicit fallback. The current `SuggestedFollowupsPanel` panel uses an `if`/implicit-fallback pattern (line 78 `if (f.kind === 'narrow' || f.kind === 'widen')`); spec mandates refactoring to exhaustive form before adding the `swap_template` branch.
- **D-29 — 2026-05-24 (cycle-2 F1 accept) — FR-5 worker pre-clean is deterministic, not "drop OR fail".** Rationale: the cycle-1 patch used ambiguous "drop the key or treat as a hard validation failure" prose. The deterministic rule is: drop ONLY when `template_id == ""` (the LLM followed protocol); otherwise pass through to `FollowupItemAdapter.validate_python`, which raises `ValidationError` via `extra="forbid"` and downgrades through the existing decision table. This makes "LLM emitted a `template_id` it shouldn't have" a visible downgrade event with the rationale prefix, not a silent drop.
- **D-30 — 2026-05-24 (cycle-2 F2 accept) — All structlog field names match `RemapResult` exactly + replace stale `RemapDiagnostics` reference in §4.** Rationale: cycle-1 added 4-field `RemapResult` but §13 + §4 still used the 3-field naming from before the patch. Field-name drift between FR-3, FR-7, and §13 would cause runbook grep failures and test drift.
- **D-31 — 2026-05-24 (cycle-2 F3 accept) — §6 intro sentence widens both `followup_kind` and `original_kind` to include `text`.** Rationale: cycle-1 patched the table but the introductory sentence still claimed the value space widened to `{narrow, widen, swap_template}` only. The table now states the canonical 4-value sets; the intro sentence matches.
- **D-32 — 2026-05-24 (cycle-2 F4 accept) — Fourth `reason` code `remap_invalid_search_space` is added to FR-7 step 3 emission + §6 + §14 + AC-15b.** Rationale: cycle-1's FR-7 step 3 said "downgrade to `text` with rationale prefix" but didn't require the event emission; §15 + D-11 implied four reason codes but FR-8 only defined three. The fourth case (helper raises `InvalidSearchSpaceError` after the remap step) needs identical event + reason coverage so the operator and runbook see why a remap failed. AC-15b locks the contract.
- **D-33 — 2026-05-24 (cycle-2 F5 accept) — `validation_error` truncation matches the canonical `_truncate` helper (head-and-tail 200+200), not a 500-char hard cut.** Rationale: cycle-1's §6 said "truncated to 500 chars" but the canonical helper at `backend/app/domain/study/followups.py:60-77` uses `_TRUNCATE_LIMIT = 200` with head+marker+tail. Documenting the wrong truncation semantics would force a redundant truncate-different-way implementation or a spec patch. The spec now describes the existing helper.
- **D-34 — 2026-05-24 (cycle-3 F1 accept) — `remap_search_space_for_swap_target` rejects no-trusted-intersection swaps; LLM prompt instructs skipping `swap_template` when no swap candidate shares params with the parent.** Rationale: `SwapTemplateFollowup.search_space.params` has `min_length=1`, so a compliant LLM cannot emit an empty `search_space`. If the LLM picks a swap target sharing zero params with the parent, the trusted intersection is empty and the LLM has nothing to populate — emitting a "rogue" param to fill the slot is hallucination (cycle-1 F1). The helper rejects no-trusted-intersection inputs with `InvalidSearchSpaceError`, which the worker routes through the `remap_invalid_search_space` reason code (D-32). The prompt addition closes the loop on the producer side. Disjoint-only swaps (LLM contributes nothing; everything comes from heuristics) are explicitly OUT of contract — if the operator wants such a swap, they create the study manually via the existing modal.
