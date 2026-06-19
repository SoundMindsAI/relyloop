# Feature Specification — Reseed scenario manifest with live per-scenario state

- **Feature dir:** `docs/00_overview/planned_features/02_mvp2/feat_reseed_scenario_manifest_live_state`
- **Release:** MVP2 (`02_mvp2`)
- **Type:** `feat_`
- **Depends on:** `feat_selective_engine_startup_and_demo` (the `scenarios_skipped` / `scenarios_skipped_reasons` infra + reset modal), `bug_reset_demo_no_instant_feedback_poll_race` (the responsive progress view + step log this checklist slots into). Both **merged** — hard dependencies satisfied.
- **Cross-model review:** Opus self-review (GPT-5.5 unreachable in this environment — sanctioned fallback per CLAUDE.md). Gemini Code Assist is the live cross-family gate at the PR.

---

## 1) Purpose

The reset-to-demo progress dialog shows only a bare counter — "Scenario {N} of 6" — plus a free-text `current_step` line and a step log. This is actively misleading: the counter only increments when a *whole* scenario finishes, and the first scenario runs a full 50-trial Optuna study before it does, so the dialog reads "Scenario 0 of 6 (0%)" for minutes while genuinely working. Operators read 0 as "nothing is happening" and cannot tell what the six scenarios even are.

This feature replaces the opaque counter with a **per-run scenario manifest** carried in the reseed status response — one labeled entry per scenario, each with a friendly label, one-line description, engine, and a **live state** (`pending` / `active` / `done` / `skipped`) that the worker stamps as it processes. The frontend renders it as a checklist so a long-running scenario shows as "active" (with its live step detail) rather than a frozen "0 of 6".

## 2) Current state audit

- **`ReseedStatusResponse`** ([backend/app/services/demo_seeding.py:287-332](backend/app/services/demo_seeding.py#L287-L332)) — `model_config = ConfigDict(extra="forbid")`. Today exposes `scenarios_total`, `scenarios_completed`, `current_step: str | None`, `steps: list[str]`, `scenarios_skipped: list[str]`, `scenarios_skipped_reasons: dict[str, _SkipReason]`. Persisted to Redis as one JSON blob under `DEMO_RESEED_STATUS_KEY = "demo_reseed:status"`.
- **`_SkipReason`** ([demo_seeding.py:284](backend/app/services/demo_seeding.py#L284)) — `Literal["user_excluded", "unreachable"]`.
- **Orchestrator** `reseed_demo_state()` ([demo_seeding.py:1603](backend/app/services/demo_seeding.py#L1603)) — builds `progress = ReseedStatusResponse(...)` at start with `scenarios_total = len(SCENARIOS) + 1`, loops the 5 `SCENARIOS`, then seeds the rich ESCI scenario (`_RICH_SCENARIO_SLUG = "acme-products-rich-prod"`, [demo_seeding.py:179](backend/app/services/demo_seeding.py#L179)). Two skip gates inside the loop: **user-excluded** ([demo_seeding.py:1741-1748](backend/app/services/demo_seeding.py#L1741-L1748)) and **unreachable** ([demo_seeding.py:1756-1763](backend/app/services/demo_seeding.py#L1756-L1763)), each `append`s the slug to `scenarios_skipped` + sets `scenarios_skipped_reasons[slug]` then `continue`s. Progress is emitted only through `_emit_progress()` ([demo_seeding.py:381](backend/app/services/demo_seeding.py#L381)), the single choke point (it also appends `current_step` to `steps[]`).
- **`SCENARIOS`** (re-exported in `demo_seeding`, defined in `scripts/seed_meaningful_demos.py`) — 5 entries with keys `slug`, `engine_type`, `host_base_url`, `target`, etc. The rich scenario is appended in the orchestrator outside the loop and is always `elasticsearch`.
- **Status persistence** — `status_set(redis, status)` ([demo_seeding.py:854](backend/app/services/demo_seeding.py#L854)) writes the blob; the worker passes a closure callback. `_emit_progress` calls the callback after each mutation.
- **Status endpoint** — `GET /api/v1/_test/demo/reseed/status` ([backend/app/api/v1/_test.py](backend/app/api/v1/_test.py)) returns `ReseedStatusResponse` (`response_model=ReseedStatusResponse`); dev-only (`Depends(_require_development_env)`); returns `{status: "idle"}` when no run exists.
- **Frontend progress view** — `ResetDemoStateButton` ([ui/src/components/dashboard/reset-demo-state-button.tsx:360-370](ui/src/components/dashboard/reset-demo-state-button.tsx#L360-L370)) renders `Scenario {status.scenarios_completed} of {status.scenarios_total}` + `progressPercent()`; the step log at lines 440-458; the partial-completion footer at lines 382-438. Consumes `ReseedStatusResponse` via `useDemoReseedStatus()` ([ui/src/lib/api/demo-reseed.ts:136-174](ui/src/lib/api/demo-reseed.ts#L136-L174)), 2s poll.
- **Frontend type mirror** — `ReseedStatusResponse` interface ([ui/src/lib/api/demo-reseed.ts:38-84](ui/src/lib/api/demo-reseed.ts#L38-L84)); generated `ui/src/lib/types.ts`.
- **Enum mirror pattern** — `RESEED_SKIP_REASON_VALUES` ([ui/src/lib/enums.ts:61-67](ui/src/lib/enums.ts#L61-L67)) with the `// Values must match backend/...` source-of-truth comment; `ENGINE_TYPE_VALUES` ([ui/src/lib/enums.ts:41-44](ui/src/lib/enums.ts#L41-L44)).
- **Engine labels** — `ENGINE_LABELS: Record<EngineType, string>` exported from [ui/src/components/clusters/engine-badge.tsx](ui/src/components/clusters/engine-badge.tsx) (`elasticsearch → Elasticsearch`, `opensearch → OpenSearch`, `solr → Apache Solr`); a local duplicate `ENGINE_DISPLAY_LABELS` exists in `reset-demo-state-button.tsx:37-41` (identical values).
- **Greenfield confirmation** — no `ScenarioProgress` type, `scenario_state` field, or per-scenario state machine exists anywhere in `backend/` or `ui/`. This feature is fully additive.

## 3) Scope

**In scope:**
- New `ScenarioProgress` Pydantic model + `scenarios: list[ScenarioProgress]` field on `ReseedStatusResponse` (additive, defaulted).
- New `ScenarioState = Literal["pending", "active", "done", "skipped"]`.
- A single source-of-truth manifest table (slug → label, description, engine) covering the 5 `SCENARIOS` + the rich scenario, in canonical processing order.
- Orchestrator builds the manifest at run start (all `pending`) and stamps state transitions: `pending → active` at scenario start, `→ done` on completion, `→ skipped` (carrying the existing `user_excluded`/`unreachable` reason) at each skip gate, for both the loop scenarios and the rich scenario.
- Frontend: replace the "Scenario N of 6" line with a labeled checklist (label + engine badge + description + state icon + live `current_step` on the active row); keep a compact "N of 6 done" summary above it.
- `SCENARIO_STATE_VALUES` enum mirror in `ui/src/lib/enums.ts` + source-of-truth comment.
- Regenerate `ui/openapi.json` + `ui/src/lib/types.ts`.
- Tests at every layer touched (unit, integration, contract, frontend vitest; E2E optional per §14).

**Out of scope (non-goals):**
- SSE streaming of manifest updates (tracked separately as `feat_reseed_status_sse_streaming`; this works on the existing 2s poll).
- Per-scenario progress *percentages* / trial-count fields on the manifest entry (the active row's live `current_step` already carries "trials 26/50"; a structured trial-count field is a possible later enhancement, not this feature).
- Changing what the reseed *does* (no orchestration/seeding behavior change) — purely surfacing state.
- Removing the legacy `scenarios_total` / `scenarios_completed` / `scenarios_skipped` / `scenarios_skipped_reasons` fields — they stay for back-compat (the manifest is additive).

## 4) Product principles and constraints

- **Additive, back-compat.** `ReseedStatusResponse` is `extra="forbid"` and cached in Redis across deploys; the new field MUST default (`Field(default_factory=list)`) so a payload written by an older worker (no `scenarios`) still deserializes, and the frontend MUST tolerate an empty/absent `scenarios` (fall back to the legacy counter).
- **Single source of truth for state.** The manifest is the new authoritative per-scenario state; the legacy `scenarios_completed` counter is *derived* from it (count of `done`) so the two never disagree. The legacy `scenarios_skipped` / `scenarios_skipped_reasons` continue to be populated exactly as today (no behavior change) — the manifest carries the same skip reason on its `skipped` entries.
- **No new poll loop / endpoint.** State rides in the existing status blob the 2s poller already reads.
- **Dev-only surface.** The reseed status endpoint is `_require_development_env`-gated and test-only; no auth/tenant/audit surface (MVP2 audit-log does not apply — this is not a tenant-scoped mutation).
- **Enumerated-value discipline.** `ScenarioState` is a wire value the frontend renders → it MUST follow §7.4: backend `Literal` is the source of truth, `enums.ts` mirror carries the `// Values must match …` comment.

## 5) Assumptions and dependencies

- Hard deps (both merged): `feat_selective_engine_startup_and_demo`, `bug_reset_demo_no_instant_feedback_poll_race`.
- The orchestrator already routes every progress mutation through `_emit_progress` — state stamps reuse that choke point (no new persistence path).
- The manifest order is deterministic and matches processing order: the 5 `SCENARIOS` entries (in list order) then the rich scenario appended 6th.
- No migration (Redis-backed, no DB tables).

## 6) Actors and roles

- **Relevance Engineer / operator** (primary) — clicks "Reset to demo state", watches the checklist. Read-only consumer of the manifest.
- No new roles; no Approver/Viewer interaction.

## 7) Functional requirements

- **FR-1 — `ScenarioProgress` model.** Add a `ScenarioProgress(BaseModel)` with fields: `slug: str`, `label: str`, `description: str`, `engine: _EngineType`, `state: ScenarioState`, `skip_reason: _SkipReason | None = None`. `ScenarioState = Literal["pending", "active", "done", "skipped"]` defined beside `_SkipReason`.
- **FR-2 — manifest field.** Add `scenarios: list[ScenarioProgress] = Field(default_factory=list)` to `ReseedStatusResponse`. Defaulted so cached/older payloads deserialize under `extra="forbid"`.
- **FR-3 — source-of-truth copy table.** A module-level `Final[dict[str, ScenarioCopy]]` (or list of `(slug, label, description, engine)`) keyed by slug, covering all 6 slugs (5 `SCENARIOS` + `_RICH_SCENARIO_SLUG`), in processing order. Label/description per §11 copy table. A unit test asserts the manifest table's slug set + order exactly equals `[s["slug"] for s in SCENARIOS] + [_RICH_SCENARIO_SLUG]` (drift guard).
- **FR-4 — build at run start.** `reseed_demo_state` builds `progress.scenarios` from the copy table at start, every entry `state="pending"`, in canonical order, before the first `_emit_progress`.
- **FR-5 — stamp `active`.** When the orchestrator begins seeding a scenario (immediately after both skip gates pass, before the first per-scenario `current_step`), set that scenario's manifest entry `state="active"`. Same for the rich scenario at its start.
- **FR-6 — stamp `done`.** When a scenario finishes, set its manifest entry `state="done"`. There are **two** existing completion sites — the loop-scenario increment at [demo_seeding.py:2127](backend/app/services/demo_seeding.py#L2127) and the rich-scenario increment at [demo_seeding.py:2179](backend/app/services/demo_seeding.py#L2179); both must stamp `done` for their scenario. **FR-6a:** `scenarios_completed` MUST be *derived* as `sum(1 for s in progress.scenarios if s.state == "done")` (replacing both `+= 1` sites) so counter and manifest cannot diverge. Apply the derivation wherever `scenarios_completed` is read/emitted (the increments at 2127/2179 are removed in favor of a `done`-stamp + recompute).
- **FR-7 — stamp `skipped`.** At the **user-excluded** gate, set the entry `state="skipped"`, `skip_reason="user_excluded"`. At the **unreachable** gate, set `state="skipped"`, `skip_reason="unreachable"`. The existing `scenarios_skipped` / `scenarios_skipped_reasons` writes stay unchanged (back-compat).
- **FR-8 — emit through the choke point.** Every state mutation is followed by `_emit_progress(status_callback, progress)` (or batched into the existing emit at that step) so the persisted blob always reflects current per-scenario state within one poll tick.
- **FR-9 — frontend checklist.** Replace the "Scenario {n} of {m}" line ([reset-demo-state-button.tsx:360-370](ui/src/components/dashboard/reset-demo-state-button.tsx#L360-L370)) with a checklist: one row per `status.scenarios` entry showing the **state icon**, **label**, **engine badge** (reuse `ENGINE_LABELS`), and **description** (muted subtitle). The `active` row additionally shows the live `current_step` detail. Keep a compact "{done} of {total} done" summary line above the checklist.
- **FR-10 — graceful fallback.** When `status.scenarios` is empty/absent (older worker payload), the frontend falls back to the existing "Scenario {completed} of {total}" line (no crash, no empty box).
- **FR-11 — skipped rows reuse existing copy.** A `skipped` row shows its reason inline ("you excluded" vs "engine unreachable") consistent with the existing partial-completion footer wording; the end-of-run footer (lines 382-438) MAY remain or be folded into the checklist (decision D-3).
- **FR-12 — enum mirror.** Add `SCENARIO_STATE_VALUES = ['pending','active','done','skipped'] as const` + `ScenarioState` type to `ui/src/lib/enums.ts` with the `// Values must match backend/app/services/demo_seeding.py ScenarioState` comment.

## 8) API and data contract baseline

### 7.1 Endpoint (unchanged shape, additive field)

`GET /api/v1/_test/demo/reseed/status` — `response_model=ReseedStatusResponse`, dev-only (`Depends(_require_development_env)`). No new endpoint, no new method, no path change. `POST /api/v1/_test/demo/reseed` body unchanged.

### 7.2 Response shape (additive `scenarios`)

```jsonc
{
  "status": "running",
  "started_at": "2026-06-18T23:15:28Z",
  "finished_at": null,
  "scenarios_total": 6,
  "scenarios_completed": 2,           // derived = count(state == "done")
  "current_step": "acme-kb-docs-solr: running study 019edd0e (trials 26/50)",
  "failed_reason": null,
  "summary": null,
  "steps": ["wiping demo state", "..."],
  "scenarios_skipped": ["news-search-staging"],          // unchanged
  "scenarios_skipped_reasons": {"news-search-staging": "unreachable"},  // unchanged
  "scenarios": [                                          // NEW (additive, defaulted [])
    {"slug": "acme-products-prod", "label": "Acme product catalog", "description": "E-commerce product search over an electronics catalog", "engine": "elasticsearch", "state": "done", "skip_reason": null},
    {"slug": "corp-docs-search", "label": "Corporate knowledge base", "description": "Internal company docs & wiki article search", "engine": "elasticsearch", "state": "done", "skip_reason": null},
    {"slug": "news-search-staging", "label": "News article search", "description": "Time-sensitive news/article retrieval", "engine": "opensearch", "state": "skipped", "skip_reason": "unreachable"},
    {"slug": "jobs-marketplace-prod", "label": "Jobs marketplace", "description": "Job-listing search (title + skill matching)", "engine": "elasticsearch", "state": "pending", "skip_reason": null},
    {"slug": "acme-kb-docs-solr", "label": "Support knowledge base (Solr)", "description": "Help-center / support-article search on Apache Solr", "engine": "solr", "state": "active", "skip_reason": null},
    {"slug": "acme-products-rich-prod", "label": "Rich product demo", "description": "1,000-doc ESCI catalog with LLM-generated relevance judgments", "engine": "elasticsearch", "state": "pending", "skip_reason": null}
  ]
}
```

### 7.3 Error shape

No new error paths. The endpoint returns 200 with the blob (or `{status:"idle"}`); no field is required of the client. (Verified: the status route has no error envelope — it always 200s with the model.)

### 7.4 Enumerated value contracts

| Field | Wire values | Backend source of truth | Frontend mirror |
|---|---|---|---|
| `ScenarioProgress.state` | `pending`, `active`, `done`, `skipped` | `backend/app/services/demo_seeding.py` `ScenarioState` (`Literal[...]`) — NEW | `ui/src/lib/enums.ts` `SCENARIO_STATE_VALUES` + `// Values must match …` comment (FR-12) |
| `ScenarioProgress.skip_reason` | `user_excluded`, `unreachable`, `null` | `backend/app/services/demo_seeding.py` `_SkipReason` (existing) | `ui/src/lib/enums.ts` `RESEED_SKIP_REASON_VALUES` (existing, reused) |
| `ScenarioProgress.engine` | `elasticsearch`, `opensearch`, `solr` | `backend/app/api/v1/schemas.py` `EngineTypeWire` (existing) / `_EngineType` in demo_seeding | `ui/src/lib/enums.ts` `ENGINE_TYPE_VALUES` (existing) + `ENGINE_LABELS` for display |

All three frontend mirrors already exist except `SCENARIO_STATE_VALUES` (added by FR-12). The manifest `label`/`description` are free-text copy (not enumerated wire values) sourced from the backend copy table (§11), so no allowlist applies — but they ARE backend-owned (single source of truth), not invented in the frontend.

### 7.5 Auth / audit

Endpoint is `_require_development_env`-gated, test-only, no tenant scope. No `audit_log` event (not a tenant-visible mutation; MVP2 audit instrumentation does not apply).

## 9) Data model and state transitions

- **No DB / no migration.** State lives only in the Redis status blob (`demo_reseed:status`).
- **Per-scenario state machine:**
  ```
  pending ──(seeding begins)──▶ active ──(scenario completes)──▶ done
     │
     └──(user-excluded gate | unreachable gate)──▶ skipped (+ skip_reason)
  ```
  Transitions are monotonic and terminal at `done`/`skipped`; a scenario never leaves `done`/`skipped`. `active` is held for at most one scenario at a time (the orchestrator is sequential).
- **Derived invariant (FR-6a):** `scenarios_completed == sum(s.state == "done")`. Write-path audit: the ONLY site that increments `scenarios_completed` is the loop/rich completion point; the spec changes that site to derive the count from the manifest, so no other writer can violate the invariant.

## 10) Security, privacy, and compliance

- No secrets, PII, or tenant data in the manifest (labels/descriptions are static product copy; slugs/engine are non-sensitive). The endpoint is dev-env-gated and not exposed in production. No new attack surface.

## 11) UX flows and edge cases

**IA placement:** unchanged — the checklist lives inside the existing reset-to-demo `AlertDialog` progress view on the dashboard (`/`), replacing the single counter line. No nav/route change.

**Primary flow:** operator clicks "Reset to demo state" → confirms → dialog shows the checklist; rows transition `pending → active → done`; the active row shows the live step ("trials 26/50"); skipped rows show their reason; on completion the summary reads "5 of 6 done" (with 1 skipped) and the existing summary/footer renders.

**Scenario copy (source-of-truth table — backend-owned):**

| Slug | Engine | Label | Description |
|---|---|---|---|
| `acme-products-prod` | Elasticsearch | Acme product catalog | E-commerce product search over an electronics catalog |
| `corp-docs-search` | Elasticsearch | Corporate knowledge base | Internal company docs & wiki article search |
| `news-search-staging` | OpenSearch | News article search | Time-sensitive news/article retrieval |
| `jobs-marketplace-prod` | Elasticsearch | Jobs marketplace | Job-listing search (title + skill matching) |
| `acme-kb-docs-solr` | Solr | Support knowledge base (Solr) | Help-center / support-article search on Apache Solr |
| `acme-products-rich-prod` | Elasticsearch | Rich product demo | 1,000-doc ESCI catalog with LLM-generated relevance judgments |

**Edge cases:**
- **Older worker payload (no `scenarios`)** → FR-10 fallback to the legacy counter line.
- **All engines unreachable** → all loop scenarios `skipped` (reason `unreachable`); status ends `failed` (`all_engines_unreachable`) — checklist shows all-skipped, which is clearer than "0 of 6".
- **User-excluded subset** → excluded scenarios `skipped` (`user_excluded`) from run start? No — the gate fires inside the loop, so they show `pending` until the loop reaches them, then flip to `skipped`. Acceptable (sequential), but D-2 considers pre-marking user-excluded entries `skipped` at build time for immediate clarity.
- **State icons:** `pending` ○ (muted), `active` spinner, `done` ✓ (success), `skipped` ⊘ (muted, with reason). Use existing icon set / lucide icons already in the UI.

**Tooltips / glossary:** the scenario `description` IS the inline contextual help (muted subtitle) — no separate tooltip needed. No new glossary key required (descriptions are run-specific copy, not a reusable defined term). If a reviewer wants a "what is a demo scenario?" glossary entry, that's a D-4 optional add.

## 12) Given/When/Then acceptance criteria

- **AC-1 (manifest present):** *Given* a reseed is running, *when* the operator polls status, *then* `scenarios` has 6 entries in canonical order, each with `slug/label/description/engine/state`.
- **AC-2 (pending at start):** *Given* a reseed just enqueued, *when* the worker builds the manifest, *then* every entry is `state="pending"` before the first scenario starts.
- **AC-3 (active stamp):** *Given* the worker begins seeding scenario X, *when* status is polled, *then* X is `active` and exactly one entry is `active`.
- **AC-4 (done stamp + derived counter):** *Given* scenario X completes, *then* X is `done` and `scenarios_completed == count(state=="done")`.
- **AC-5 (skipped — unreachable):** *Given* an engine is unreachable, *when* the loop reaches its scenario, *then* that entry is `skipped` with `skip_reason="unreachable"` AND the legacy `scenarios_skipped`/`scenarios_skipped_reasons` still contain the slug (back-compat unchanged).
- **AC-6 (skipped — user-excluded):** *Given* a POST `engines` filter excludes an engine, *then* its scenarios are `skipped` with `skip_reason="user_excluded"`.
- **AC-7 (drift guard):** *Given* the manifest copy table, *then* its slug set + order equals `[s["slug"] for s in SCENARIOS] + [_RICH_SCENARIO_SLUG]` (unit test fails if SCENARIOS changes without updating the table).
- **AC-8 (additive deserialize):** *Given* a Redis blob written without `scenarios`, *when* `ReseedStatusResponse` parses it, *then* it succeeds with `scenarios == []` (no `extra="forbid"` rejection).
- **AC-9 (frontend checklist):** *Given* a running status with a mixed manifest (done/active/skipped/pending), *when* the dialog renders, *then* each row shows its label + engine label + description + state icon, and the active row shows `current_step`.
- **AC-10 (frontend fallback):** *Given* a status with empty `scenarios`, *then* the dialog renders the legacy "Scenario N of M" line and does not crash.
- **AC-11 (enum contract):** *Given* `SCENARIO_STATE_VALUES` in `enums.ts`, *then* it equals the backend `ScenarioState` literal char-for-char and carries the source-of-truth comment (Story-4.2 grep gate passes).

## 13) Non-functional requirements

- **Performance:** manifest is ≤6 small objects; negligible blob-size + serialization cost; no extra Redis round-trips (rides the existing `_emit_progress`). No change to the 2s poll cadence.
- **Reliability:** state stamps are monotonic; a worker crash mid-run leaves the last-persisted states intact (the existing stale-status recovery still applies).
- **Back-compat:** additive field + frontend fallback (FR-2, FR-10, AC-8, AC-10).

## 14) Test strategy requirements (spec-level)

- **Unit** (`backend/tests/unit/services/`): manifest build (all pending, correct order/copy); state transitions (active→done; skip gates set skipped+reason); derived-counter invariant; AC-7 drift guard.
- **Integration** (`backend/tests/integration/`): drive `reseed_demo_state` with a stubbed engine/api so scenarios complete/skip, assert the persisted status blob's `scenarios` states + `scenarios_completed` derivation + legacy `scenarios_skipped` parity. (Reuse the existing demo-seeding integration harness; mock external engine/API only.)
- **Contract** (`backend/tests/contract/`): assert `GET …/reseed/status` response includes `scenarios` with the documented shape; assert `ReseedStatusResponse` parses a legacy blob without `scenarios` (AC-8).
- **Frontend vitest** (`ui/src/__tests__/components/dashboard/reset-demo-state-button.test.tsx`): checklist renders mixed states (AC-9); fallback to counter when `scenarios` empty (AC-10); `SCENARIO_STATE_VALUES` enum-contract guard (the existing `enums.ts` grep gate covers the source-of-truth comment).
- **E2E** (optional, real-backend): not required for merge — the reset flow's real-backend E2E is gated behind the smoke job (opt-in/off); a vitest-level checklist test plus the integration test cover the contract. If added, it must use real browser interactions (no `page.route()`), per project policy.

## 15) Documentation update requirements

- `docs/03_runbooks/demo-reseed-engine-tolerance.md` — note the new per-scenario manifest/checklist (the "Why?" link in the footer already points here).
- Regenerate `ui/openapi.json` + `ui/src/lib/types.ts` (the `scenarios` field flows into the generated types). Single command: `bash scripts/regen-generated-artifacts.sh`.
- `state.md` / `state_history.md` at finalization.

## 16) Rollout and migration readiness

- **No migration** (Redis-only). No feature flag needed — additive + frontend-fallback makes the rollout safe even if a stale worker image is running (it just omits `scenarios`, frontend falls back).
- Deploy order is irrelevant: new worker + old frontend → frontend ignores `scenarios`; old worker + new frontend → frontend falls back to the counter.

## 17) Traceability matrix

| FR | AC | Tests |
|---|---|---|
| FR-1, FR-2 | AC-1, AC-8 | unit (model), contract (shape + legacy parse) |
| FR-3 | AC-7 | unit (drift guard) |
| FR-4 | AC-2 | unit, integration |
| FR-5 | AC-3 | unit, integration |
| FR-6/6a | AC-4 | unit (derived counter), integration |
| FR-7 | AC-5, AC-6 | unit, integration |
| FR-8 | AC-1..AC-6 | integration (persisted blob) |
| FR-9, FR-11 | AC-9 | vitest |
| FR-10 | AC-10 | vitest |
| FR-12 | AC-11 | vitest / enums grep gate |

## 18) Definition of feature done

- All FRs implemented; all ACs have passing tests at the specified layers.
- `ReseedStatusResponse.scenarios` additive + defaulted; legacy fields unchanged; `scenarios_completed` derived from the manifest.
- Frontend checklist replaces the counter with graceful fallback; `SCENARIO_STATE_VALUES` mirror + source-of-truth comment; `enums.ts` grep gate green.
- `ui/openapi.json` + `types.ts` regenerated; generated-artifact freshness gate green.
- Runbook updated; state.md/state_history.md finalized.
- `pr.yml` green; Gemini findings adjudicated.

## 19) Open questions and decision log

- **D-1 (resolved):** Manifest is additive; legacy counter/skip fields retained for back-compat; `scenarios_completed` derived from manifest. *Rationale:* zero-risk rollout, no consumer breakage.
- **D-2 (open, recommend pre-mark):** Should user-excluded scenarios be marked `skipped` at *build* time (immediately visible) rather than when the loop reaches them? *Recommend:* yes — pre-mark `user_excluded` entries `skipped` during manifest build (the `engines` filter is known up front), so the checklist is accurate from the first poll. (Unreachable stays runtime — reachability isn't known until probe.)
- **D-3 (open, recommend keep):** Keep the existing end-of-run partial-completion footer (lines 382-438) in addition to the per-row skipped state? *Recommend:* keep the footer (it carries the "Why?" runbook link) but it becomes a summary beneath the checklist; per-row skipped state is the primary surface.
- **D-4 (open, recommend defer):** Add a glossary entry "demo scenario"? *Recommend:* no — descriptions are inline; not a reusable defined term.
- **D-5 (resolved):** Keep `label`/`description` backend-owned (not frontend-invented) so copy has one source of truth and flows through the typed API. *Rationale:* §7.4 discipline + avoids drift.
