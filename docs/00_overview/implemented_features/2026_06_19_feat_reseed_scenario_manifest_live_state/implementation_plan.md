# Implementation Plan — Reseed scenario manifest with live per-scenario state

- **Primary spec:** [feature_spec.md](feature_spec.md)
- **Status:** Complete (PR #566, merged 2026-06-19 d36a6916)
- **Release:** MVP2 (`02_mvp2`)
- **Branch:** `feat_reseed_scenario_manifest_live_state`
- **Migration:** none (Redis-only status blob)
- **Cross-model review:** Opus self-review (GPT-5.5 unreachable; Gemini is the live cross-family gate at the PR)

## 1) FR → Story traceability

| FR | Story | AC |
|---|---|---|
| FR-1 (`ScenarioProgress` model) | 1.1 | AC-1, AC-8 |
| FR-2 (`scenarios` field, defaulted) | 1.1 | AC-1, AC-8 |
| FR-3 (copy table + drift guard) | 1.1 | AC-7 |
| FR-4 (build at start, all pending) | 1.2 | AC-2 |
| FR-5 (stamp active) | 1.2 | AC-3 |
| FR-6/6a (stamp done + derive counter) | 1.2 | AC-4 |
| FR-7 (stamp skipped + reason) | 1.2 | AC-5, AC-6 |
| FR-8 (emit through choke point) | 1.2 | AC-1..AC-6 |
| FR-12 (`SCENARIO_STATE_VALUES` mirror) | 2.1 | AC-11 |
| FR-9, FR-11 (checklist UI) | 2.2 | AC-9 |
| FR-10 (graceful fallback) | 2.2 | AC-10 |

All 12 FRs covered; every story traces to ≥1 FR. No endpoints added (the existing `GET /api/v1/_test/demo/reseed/status` gains an additive response field — no new route, no new error code). No audit events (dev-only, non-tenant; spec §7.5).

## 2) Stories

### Epic 1 — Backend: manifest model + worker state stamping

#### Story 1.1 — `ScenarioProgress` model + copy table + additive `scenarios` field

**Outcome:** `ReseedStatusResponse` carries an additive, defaulted `scenarios: list[ScenarioProgress]`; a backend-owned copy table maps each slug → label/description/engine; a drift guard locks the table to `SCENARIOS`.

**Modified files:**
| File | Change |
|---|---|
| [backend/app/services/demo_seeding.py](backend/app/services/demo_seeding.py) | Add `ScenarioState` Literal (beside `_SkipReason`, ~L284); add `ScenarioProgress(BaseModel)`; add `scenarios: list[ScenarioProgress] = Field(default_factory=list)` to `ReseedStatusResponse` (~L332); add `_SCENARIO_COPY` source-of-truth table + `_build_scenario_manifest()` helper |

**Key interfaces:**
```python
ScenarioState = Literal["pending", "active", "done", "skipped"]

class ScenarioProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    label: str
    description: str
    engine: _EngineType
    state: ScenarioState
    skip_reason: _SkipReason | None = None

# Source-of-truth copy, canonical processing order (5 SCENARIOS + rich).
class _ScenarioCopy(NamedTuple):
    label: str
    description: str

_SCENARIO_COPY: Final[dict[str, _ScenarioCopy]] = {
    "acme-products-prod": _ScenarioCopy("Acme product catalog", "E-commerce product search over an electronics catalog"),
    "corp-docs-search": _ScenarioCopy("Corporate knowledge base", "Internal company docs & wiki article search"),
    "news-search-staging": _ScenarioCopy("News article search", "Time-sensitive news/article retrieval"),
    "jobs-marketplace-prod": _ScenarioCopy("Jobs marketplace", "Job-listing search (title + skill matching)"),
    "acme-kb-docs-solr": _ScenarioCopy("Support knowledge base (Solr)", "Help-center / support-article search on Apache Solr"),
    _RICH_SCENARIO_SLUG: _ScenarioCopy("Rich product demo", "1,000-doc ESCI catalog with LLM-generated relevance judgments"),
}

def _build_scenario_manifest(
    engines: list[_EngineType] | None,
) -> list[ScenarioProgress]:
    """All-pending manifest in canonical order. When `engines` excludes a
    scenario's engine, pre-mark it skipped/user_excluded (D-2)."""
    manifest: list[ScenarioProgress] = []
    for sc in SCENARIOS:
        slug = cast("str", sc["slug"])
        etype = cast("_EngineType", sc["engine_type"])
        copy = _SCENARIO_COPY[slug]
        excluded = engines is not None and etype not in engines
        manifest.append(ScenarioProgress(
            slug=slug, label=copy.label, description=copy.description, engine=etype,
            state="skipped" if excluded else "pending",
            skip_reason="user_excluded" if excluded else None,
        ))
    rcopy = _SCENARIO_COPY[_RICH_SCENARIO_SLUG]
    rich_excluded = engines is not None and "elasticsearch" not in engines
    manifest.append(ScenarioProgress(
        slug=_RICH_SCENARIO_SLUG, label=rcopy.label, description=rcopy.description,
        engine="elasticsearch", state="skipped" if rich_excluded else "pending",
        skip_reason="user_excluded" if rich_excluded else None,
    ))
    return manifest
```

**Tasks:**
1. Add `ScenarioState` + `ScenarioProgress` + `_SCENARIO_COPY` + `_build_scenario_manifest`.
2. Add `scenarios` field to `ReseedStatusResponse` (defaulted, so cached `extra="forbid"` blobs without it still parse).
3. Helper to read a manifest entry by slug (`_manifest_entry(progress, slug)`) for stamping in Story 1.2.

**DoD:**
- `ReseedStatusResponse(**legacy_blob_without_scenarios)` parses with `scenarios == []` (AC-8).
- Unit test: `_build_scenario_manifest(None)` → 6 entries, all `pending`, order == `[s["slug"] for s in SCENARIOS] + [_RICH_SCENARIO_SLUG]` (AC-7 drift guard); `_build_scenario_manifest(["elasticsearch"])` → OS scenario `skipped/user_excluded`.
- Unit test: `ScenarioProgress` rejects an unknown `state`/`skip_reason` (extra="forbid" + Literal).
- `make lint`, `make typecheck` (mypy --strict) green.

#### Story 1.2 — Orchestrator stamps live per-scenario state

**Outcome:** `reseed_demo_state` builds the manifest at start and stamps `pending → active → done` / `skipped`, emitting through `_emit_progress`; `scenarios_completed` is derived from the manifest.

**Modified files:**
| File | Change |
|---|---|
| [backend/app/services/demo_seeding.py](backend/app/services/demo_seeding.py) | In `reseed_demo_state` (~L1659): set `progress.scenarios = _build_scenario_manifest(engines)` at build; stamp `active` after both skip gates pass (~L1764, before first per-scenario step) + at rich-scenario start; stamp `skipped` at the user-excluded gate (~L1746) and unreachable gate (~L1761); stamp `done` + recompute `scenarios_completed` at the two completion sites (L2127 loop, L2179 rich) |

**Key interfaces (recompute helper):**
```python
def _recompute_completed(progress: ReseedStatusResponse) -> None:
    progress.scenarios_completed = sum(1 for s in progress.scenarios if s.state == "done")

def _stamp(progress: ReseedStatusResponse, slug: str, state: ScenarioState,
           skip_reason: _SkipReason | None = None) -> None:
    for s in progress.scenarios:
        if s.slug == slug:
            s.state = state
            if skip_reason is not None:
                s.skip_reason = skip_reason
            break
    if state == "done":
        _recompute_completed(progress)
```

**Tasks:**
1. Build manifest at orchestrator start (FR-4): `progress.scenarios = _build_scenario_manifest(engines)` before the first `_emit_progress`.
2. User-excluded gate (L1741-1748): add `_stamp(progress, slug, "skipped", "user_excluded")` (the build already pre-marked it via D-2, but stamping here is idempotent + covers the not-pre-marked path). Keep existing `scenarios_skipped`/`scenarios_skipped_reasons` writes.
3. Unreachable gate (L1756-1763): `_stamp(progress, slug, "skipped", "unreachable")`. Keep existing writes.
4. Active stamp (after L1763, before the `indexing … docs` step at L1765): `_stamp(progress, slug, "active")`. Same for the rich scenario at its start (~the `loading 1000 ESCI products` step).
5. Done stamp: replace `progress.scenarios_completed += 1` at L2127 (loop) and L2179 (rich) with `_stamp(progress, slug, "done")` (which recomputes the counter via `_recompute_completed`).
6. Ensure every `_stamp`/skip is followed by `_emit_progress` (FR-8) — reuse the emit that already fires at each of these sites; add one only where a stamp lands without an adjacent emit (the skip-gate `continue` paths currently `continue` without emitting — add `await _emit_progress(...)` before `continue` so the skip is visible within one poll tick).

**DoD:**
- Integration test (DB-backed; mock engine/API): a run where one engine is unreachable → its manifest entry `skipped`/`unreachable`, completed scenarios `done`, `scenarios_completed == count(done)`, legacy `scenarios_skipped`/`reasons` unchanged (AC-4, AC-5).
- Integration test: `engines=["elasticsearch"]` POST → OS scenario `skipped`/`user_excluded` from the first emitted blob (AC-6, D-2).
- Unit test: `_stamp(..., "done")` recomputes counter; `_stamp` is a no-op for an unknown slug (defensive).
- `make test-unit`, `make test-integration` (the demo-seeding layer), `make lint`, `make typecheck` green.

### Epic 2 — Frontend: enum mirror + checklist

#### Story 2.1 — `SCENARIO_STATE_VALUES` enum mirror + regenerate types

**Outcome:** `ui/src/lib/enums.ts` mirrors the backend `ScenarioState`; the generated OpenAPI types include `scenarios`.

**Modified files:**
| File | Change |
|---|---|
| [ui/src/lib/enums.ts](ui/src/lib/enums.ts) | Add `SCENARIO_STATE_VALUES` + `ScenarioState` type with the source-of-truth comment (after `RESEED_SKIP_REASON_VALUES`, ~L67) |
| [ui/src/lib/api/demo-reseed.ts](ui/src/lib/api/demo-reseed.ts) | Add `ScenarioProgress` interface + `scenarios: ScenarioProgress[]` to the `ReseedStatusResponse` interface (~L38-84) |
| `ui/openapi.json`, `ui/src/lib/types.ts` | Regenerated via `bash scripts/regen-generated-artifacts.sh` |

**Key interfaces:**
```ts
// Values must match backend/app/services/demo_seeding.py ScenarioState.
export const SCENARIO_STATE_VALUES = ['pending', 'active', 'done', 'skipped'] as const;
export type ScenarioState = (typeof SCENARIO_STATE_VALUES)[number];
```
```ts
// in demo-reseed.ts — mirrors backend.app.services.demo_seeding.ScenarioProgress
export interface ScenarioProgress {
  slug: string;
  label: string;
  description: string;
  engine: EngineType;
  state: ScenarioState;
  skip_reason: ReseedSkipReason | null;
}
// add to ReseedStatusResponse:
scenarios: ScenarioProgress[];
```

**Tasks:**
1. Add `SCENARIO_STATE_VALUES` + type with the `// Values must match …` comment.
2. Add `ScenarioProgress` interface + `scenarios` field to the hand-written `ReseedStatusResponse` mirror in `demo-reseed.ts` (import `ScenarioState`, reuse `EngineType`, `ReseedSkipReason`).
3. `bash scripts/regen-generated-artifacts.sh` after the backend `scenarios` field lands (Story 1.1) so `ui/openapi.json` + `types.ts` include it.

**DoD:**
- `enums.ts` Story-4.2 grep gate passes (source-of-truth comment present); `SCENARIO_STATE_VALUES` equals the backend Literal char-for-char (AC-11).
- `cd ui && pnpm typecheck` green; `generated-artifacts-fresh` gate clean (no drift after regen).

#### Story 2.2 — Replace the counter with a labeled checklist

**Outcome:** The running-state progress view renders a per-scenario checklist (label + engine badge + description + state icon + active-row live step), with a graceful fallback to the legacy counter when `scenarios` is empty.

**Modified files:**
| File | Change |
|---|---|
| [ui/src/components/dashboard/reset-demo-state-button.tsx](ui/src/components/dashboard/reset-demo-state-button.tsx) | Replace the `isRunning` "Scenario N of M" block (L360-370) with a checklist + compact summary; add a `ScenarioChecklist` render; keep the legacy line as fallback |
| [ui/src/__tests__/components/dashboard/reset-demo-state-button.test.tsx](ui/src/__tests__/components/dashboard/reset-demo-state-button.test.tsx) | New cases (AC-9, AC-10) |

**Legacy behavior parity** (the modified block is <100 LOC, but enumerate the touched behavior to avoid regressions):
| Behavior (current) | Verdict |
|---|---|
| "Scenario {completed} of {total}" counter line (L364-367) | **Preserved** as the fallback when `scenarios` is empty (FR-10) + as the compact summary "{done} of {total} done" above the checklist |
| `progressPercent()` (L209-212) | **Preserved** — reused in the compact summary |
| `current_step ?? 'Starting…'` (L363) | **Preserved** — shown on the active checklist row (and as the headline before any scenario is active) |
| Step log (L440-458) | **Untouched** — remains below the checklist |
| Partial-completion footer (L382-438) | **Untouched** (D-3 keep) — remains beneath; per-row `skipped` state is the new primary surface |

**Tasks:**
1. Read `status.scenarios`; when non-empty render `<ScenarioChecklist>`; else render the legacy counter line (FR-10).
2. Each row: state icon (`pending` ○ muted / `active` `<Loader2 className="animate-spin">` / `done` `<Check>` success / `skipped` `<Ban>` muted), label (medium), engine label via `ENGINE_LABELS` (import from `@/components/clusters/engine-badge`, [engine-badge.tsx:103](ui/src/components/clusters/engine-badge.tsx#L103)), description (muted `text-xs`), and on the active row the live `current_step`. Skipped rows show the reason ("you excluded" / "engine unreachable") mapping `skip_reason`.
   - **Consolidate the local `ENGINE_DISPLAY_LABELS` dup** ([L37-41](ui/src/components/dashboard/reset-demo-state-button.tsx#L37-L41)) into the shared `ENGINE_LABELS`: it is also used at [L324](ui/src/components/dashboard/reset-demo-state-button.tsx#L324) (the engine-checkbox group), so the consolidation MUST replace that usage too (identical values — `Elasticsearch`/`OpenSearch`/`Apache Solr`). Removing the dup without updating L324 breaks the build.
3. Compact summary above: "{count(done)} of {scenarios.length} done" + `progressPercent()`.
4. Icons from `lucide-react` (existing UI dep — `Check` is already imported in the file; `Loader2`, `Ban`, `Circle` are standard lucide-react exports to add to the import).

**DoD:**
- vitest: a running status with mixed states (done/active/skipped/pending) renders one row per entry with label + engine label + description; the active row shows `current_step` (AC-9). Use `data-testid="reset-demo-scenario-row"` per row + `data-state` attr.
- vitest: `scenarios: []` → legacy "Scenario N of M" line rendered, no checklist, no crash (AC-10).
- vitest: skipped row shows the correct reason text for `user_excluded` vs `unreachable`.
- `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` green.

## 3) Testing workstream (inventory)

| Layer | File | Stories | Asserts |
|---|---|---|---|
| Unit | `backend/tests/unit/services/test_demo_reseed_scenario_manifest.py` (new) | 1.1, 1.2 | manifest build (order/copy/pending), drift guard (AC-7), D-2 user-excluded pre-mark, `_stamp`/`_recompute_completed`, `ScenarioProgress` validation, legacy-blob parse (AC-8) |
| Integration | `backend/tests/integration/test_demo_reseed_scenario_states.py` (new) | 1.2 | drive `reseed_demo_state` w/ stubbed engine/API; assert persisted blob `scenarios` states + derived counter + legacy-field parity (AC-4, AC-5, AC-6) |
| Contract | extend `backend/tests/contract/test_openapi_surface.py` (or a focused `reseed` contract test) | 1.1 | `/reseed/status` response includes `scenarios` w/ documented shape; legacy blob parses (AC-8) |
| Frontend | `ui/src/__tests__/components/dashboard/reset-demo-state-button.test.tsx` (extend) | 2.2 | checklist mixed states (AC-9), empty-`scenarios` fallback (AC-10), skip-reason text |
| Frontend | `enums.ts` grep gate (existing) | 2.1 | source-of-truth comment present (AC-11) |

E2E: not required for merge (spec §14 — covered by integration + vitest; the reset flow's real-backend E2E is behind the opt-in/off smoke job).

## 4) Documentation workstream

| File | Change | Story |
|---|---|---|
| [docs/03_runbooks/demo-reseed-engine-tolerance.md](docs/03_runbooks/demo-reseed-engine-tolerance.md) | Note the per-scenario manifest/checklist (the footer "Why?" link already targets this runbook) | 2.2 |
| `ui/openapi.json`, `ui/src/lib/types.ts` | Regenerate (Story 2.1) | 2.1 |
| `state.md` / `state_history.md` | Finalization | impl-execute Step 8 |

## 5) UI Guidance

**Insertion point:** the `isRunning` block at [reset-demo-state-button.tsx:360-370](ui/src/components/dashboard/reset-demo-state-button.tsx#L360-L370). Everything above (the engine checkbox group, confirm/cancel) and below (step log L440-458, partial footer L382-438) stays. The replaced block is the `<AlertDialogDescription>` that currently holds the counter.

**Analogous markup — current block being replaced:**
```tsx
{isRunning && status && (
  <AlertDialogDescription asChild>
    <div className="space-y-2" data-testid="reset-demo-state-progress">
      <div className="text-sm">{status.current_step ?? 'Starting…'}</div>
      <div className="text-xs text-muted-foreground">
        Scenario {status.scenarios_completed} of {status.scenarios_total}
        {progressPercent() != null && ` (${progressPercent()}%)`}
      </div>
    </div>
  </AlertDialogDescription>
)}
```

**New markup (checklist + fallback):**
```tsx
{isRunning && status && (
  <AlertDialogDescription asChild>
    <div className="space-y-2" data-testid="reset-demo-state-progress">
      {status.scenarios.length > 0 ? (
        <>
          <div className="text-xs text-muted-foreground">
            {status.scenarios.filter((s) => s.state === 'done').length} of{' '}
            {status.scenarios.length} done
            {progressPercent() != null && ` (${progressPercent()}%)`}
          </div>
          <ul className="space-y-1" data-testid="reset-demo-scenario-list">
            {status.scenarios.map((s) => (
              <li
                key={s.slug}
                data-testid="reset-demo-scenario-row"
                data-state={s.state}
                className="flex items-start gap-2 text-sm"
              >
                <ScenarioStateIcon state={s.state} />
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium">{s.label}</span>
                    <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      {ENGINE_LABELS[s.engine]}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {s.state === 'active' && status.current_step
                      ? status.current_step
                      : s.state === 'skipped'
                        ? s.skip_reason === 'user_excluded'
                          ? 'Skipped — you excluded this engine'
                          : 'Skipped — engine unreachable'
                        : s.description}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <>
          <div className="text-sm">{status.current_step ?? 'Starting…'}</div>
          <div className="text-xs text-muted-foreground">
            Scenario {status.scenarios_completed} of {status.scenarios_total}
            {progressPercent() != null && ` (${progressPercent()}%)`}
          </div>
        </>
      )}
    </div>
  </AlertDialogDescription>
)}
```

**`ScenarioStateIcon` helper (same file):**
```tsx
function ScenarioStateIcon({ state }: { state: ScenarioState }) {
  if (state === 'active') return <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-foreground" aria-label="active" />;
  if (state === 'done') return <Check className="mt-0.5 size-4 shrink-0 text-green-600" aria-label="done" />;
  if (state === 'skipped') return <Ban className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-label="skipped" />;
  return <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground/50" aria-label="pending" />;
}
```

**Layout/structure:** vertical list inside the dialog; each row is `[icon] [label + engine tag / detail]`. Compact summary line on top. Step log + partial footer remain below. Responsive: the dialog is fixed-width; `min-w-0` + `break-words` on the detail prevents overflow from a long `current_step`.

**Visual consistency:** reuse `text-sm`/`text-xs text-muted-foreground` (matches the existing block), `ENGINE_LABELS` (matches cluster badges), lucide icons (already used across the UI). No new CSS.

**Component composition:** inline in `reset-demo-state-button.tsx` (the `ScenarioStateIcon` is a small local helper) — the checklist is tightly coupled to this dialog's status shape; no shared component warranted.

**Interaction behavior:** read-only render driven by the 2s `useDemoReseedStatus` poll; no new user action, no new API call. The active row updates as `current_step` changes between polls.

**IA placement:** unchanged — inside the existing reset-to-demo dialog on `/`. No nav change.

**Enumerated-value contract:** `s.state` ∈ `SCENARIO_STATE_VALUES` (Story 2.1; `// Values must match backend/app/services/demo_seeding.py ScenarioState`); `s.engine` ∈ `ENGINE_TYPE_VALUES` (existing); `s.skip_reason` ∈ `RESEED_SKIP_REASON_VALUES ∪ {null}` (existing). No invented values — all three are rendered (icon/label/reason), not sent to the backend.

**Tooltips/glossary:** none new — the `description` is the inline contextual help (spec §11, D-4 defer).

## 6) Execution tracker

- [x] Story 1.1 — `ScenarioProgress` model + copy table + additive field
- [x] Story 1.2 — orchestrator stamps live state
- [x] Story 2.1 — `SCENARIO_STATE_VALUES` mirror + regen types
- [x] Story 2.2 — checklist UI

## 7) Gates

- **Epic 1 gate:** backend `scenarios` field additive + defaulted; manifest builds all-pending; orchestrator stamps pending→active→done/skipped through `_emit_progress`; `scenarios_completed` derived; `make test-unit` + `make test-integration` (demo-seeding) + `make lint` + `make typecheck` green.
- **Epic 2 gate:** `SCENARIO_STATE_VALUES` mirror + comment; checklist renders mixed states + falls back on empty; `ui/openapi.json`+`types.ts` regenerated (freshness gate clean); `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` green.
- **Feature gate:** all `pr.yml` checks green; Gemini findings adjudicated; runbook + state finalized.

## 8) Plan consistency review (self)

- Endpoints: spec adds 0 endpoints (additive field on an existing route) → 0 endpoint rows expected; consistent.
- Error codes: spec §7.3 = none new → no contract error-code tasks; consistent.
- FR coverage: all 12 FRs → stories (§1 table); every story traces to ≥1 FR.
- Test files: 2 new (unit, integration) + 2 extended (contract, vitest) + existing grep gate; each assigned to a story DoD.
- Audit events: none (dev-only, non-tenant) — explicitly justified (spec §7.5).
- Enumerated-value contract: `ScenarioState` new mirror (Story 2.1) with source-of-truth comment; engine + skip_reason reuse existing mirrors. 3-column check (backend Literal == enums.ts == rendered values) holds.
- Cross-model review: Opus self-review (GPT-5.5 unreachable). No High-severity findings.
