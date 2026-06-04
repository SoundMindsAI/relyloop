# Implementation Plan — Walkthrough video polish (synthetic cursor, smoother pacing, on-screen captions)

**Date:** 2026-06-04
**Status:** Draft
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** CLAUDE.md (Generated-artifacts freshness gates; local-stub hygiene), [`feat_website_walkthrough_guides`](../../implemented_features/2026_06_04_website_walkthrough_guides/feature_spec.md) (the `build_video_block` + freshness gate this extends)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs (FR-1 … FR-6).
- **No backend, NO DB, NO API, NO migration, NO in-app frontend.** Alembic head stays `0022_solr_engine_auth_check`. The feature touches: the Playwright demo-recording pipeline (`ui/tests/e2e/`), `ui/playwright.demo.config.ts`, the website generator (`website/scripts/build_guides.py`), the freshness self-test, and a runbook.
- The re-record is an **operator-path** step (live `make up` stack) producing non-deterministic committed binaries — sequenced LAST, after all code is in place.
- Fail-loud: caption validation, vtt validity, vtt↔metadata consistency all hard-error.
- Single phase (spec D-0): no `phase*_idea.md`.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (demo-cursor + captions-vtt helpers) | Epic 1 / Story 1.1 (pure `captions-vtt.ts`), Story 1.2 (`demo-cursor.ts`) | Split per spec D-10 — pure formatter Node-safe + vitest-able |
| FR-2 (cursor + pacing in 10 specs, video-only mode, cursor-hide-on-shot) | Epic 1 / Story 1.3 | Adopt helper in all 10 specs; lower slowMo; `DEMO_VIDEO_ONLY` + `shot()` wrapper |
| FR-3 (WebVTT captions + validation) | Epic 1 / Story 1.1 (formatter) + Story 1.3 (StepTimer marks + write + zero-caption cleanup) | Caption-source validation; `-->`/escape/blank-line rules |
| FR-4 (website `<track>` + vtt copy) | Epic 2 / Story 2.1 | `build_video_block(+has_vtt)`; `copy_deck_assets` copies vtt |
| FR-5 (gate + vtt↔metadata consistency) | Epic 2 / Story 2.2 | Static consistency check; freshness self-test sub-case |
| FR-6 (docs) | Epic 2 / Story 2.3 | runbook update |
| (re-record + regenerate — realizes FR-2/3/4 on the real assets) | Epic 3 / Story 3.1 | Operator-path: `capture-guides` + `--transcode` + regen + commit |

All 6 FRs covered. No deferred phases (single-phase per D-0) — no `phase*_idea.md`.

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** Three epics:
- **Epic 1 — recording pipeline code** (`ui/tests/e2e/helpers/captions-vtt.ts` + `demo-cursor.ts` + the 10 specs + config).
- **Epic 2 — website generator + gate + docs** (`build_guides.py` `<track>`/copy/consistency, self-test, runbook).
- **Epic 3 — re-record + regenerate** (operator-path; the only story that touches the committed video/vtt/asset binaries).

### Conventions (project-specific)

```
- captions-vtt.ts is PURE + Node-safe: imports only node:* (or nothing); NO @playwright/test import,
  so vitest (include covers tests/e2e/**/*.test.ts) can import it. Exports buildCaptionsVtt(timings),
  normalizeCaption(s), escapeVttCueText(s).
- demo-cursor.ts MAY import @playwright/test types (it's a test helper); exports installCursor(page),
  glide(page, locator, settleMs?), StepTimer, shot(page, locator-or-screenshot-opts), and
  writeCaptionsVtt(timings, slug, guidesRoot) which validates slug + writes via node:fs.
- The 10 guide specs stay thin: import the helper, call installCursor once, glide+click, mark each step,
  shot() (no-op under DEMO_VIDEO_ONLY), writeCaptionsVtt at the end.
- build_guides.py stays stdlib-only (per the shipped feature's D-8); the vtt consistency check uses
  re/pathlib only.
- Re-recorded webm/mp4/vtt are committed artifacts (non-deterministic) — Epic 3 is local operator-path,
  never CI.
```

### AI Agent Execution Protocol

0. Read `architecture.md`, `state.md`, the spec, this plan first.
1. Epic 1 + 2 are pure code — implement + unit-test each story, run the relevant gate.
2. After Epic 1 + 2: `uv run pytest backend/tests/unit/scripts/test_build_guides.py -q` + `pnpm --dir ui vitest run` (the captions-vtt test) + `bash scripts/ci/test_verify_build_guides_fresh.sh` + `(cd website && mkdocs build --strict)` + `bash scripts/ci/verify_built_site_asset_refs.sh`.
3. Epic 3 (re-record) is operator-path — requires the live stack; escalate if the stack is down.
4. No migration (assert head still `0022`).
5. Commit per story; the re-record's binary churn is one commit.

---

## Epic 1 — Recording pipeline code

### Story 1.1 — Pure WebVTT formatter (`captions-vtt.ts`) + vitest
**Outcome:** a Node-safe module that turns `{startMs, caption}[]` into valid, escaped WebVTT, unit-tested without any Playwright import. (FR-1, FR-3 formatter half.)

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/helpers/captions-vtt.ts` | `buildCaptionsVtt(timings)`, `normalizeCaption(s)`, `escapeVttCueText(s)` — pure, `node:*`-only. |
| `ui/tests/e2e/helpers/captions-vtt.test.ts` | vitest (covered by `vitest.config` `include: tests/e2e/**/*.test.ts`). |
| `ui/tests/e2e/helpers/captions-vtt-golden.json` | **Shared golden corpus (addresses C3-B1):** `[{input, normalized, escaped}]` cases covering `&`, `<`, `>`, `-->`, multiple blank lines, leading/trailing whitespace. Imported by BOTH the vitest (Story 1.1) AND the pytest (Story 2.2), so the TS `normalizeCaption`/`escapeVttCueText` and their Python mirrors can't drift. |

**Key interfaces**

```ts
export interface StepTiming { startMs: number; caption: string }
// strip the "-->" cue separator + collapse interior blank lines (a blank line ends a cue)
export function normalizeCaption(s: string): string;
// HTML/WebVTT-escape & < > (cue payloads interpret <…> as markup)
export function escapeVttCueText(s: string): string;
// WEBVTT header + one cue per timing; starts must be finite, non-negative, strictly increasing;
// each cue end = next start; last cue end = last start + TAIL_MS (4000). Throws on invalid timings.
export function buildCaptionsVtt(timings: StepTiming[]): string;  // returns the full .vtt text
const TAIL_MS = 4000;
```

**Tasks**
1. Implement `escapeVttCueText` (`&`→`&amp;` first, then `<`→`&lt;`, `>`→`&gt;`), `normalizeCaption` (strip `-->`, collapse blank lines to single spaces/newlines so no blank line appears inside a cue body), `buildCaptionsVtt` (validate finite/non-neg/strictly-increasing; format `HH:MM:SS.mmm`; one cue per timing; cue body = `escapeVttCueText(normalizeCaption(caption))`).
2. vitest cases: valid `WEBVTT` header + blank line; N cues for N timings; strictly-increasing starts with `end > start`; throws on non-finite/negative/non-increasing/empty-timings; **drive `normalizeCaption`/`escapeVttCueText` from `captions-vtt-golden.json`** (the AC-4 example `Boost title & description <strong>2.5×</strong>` → `Boost title &amp; description &lt;strong&gt;2.5×&lt;/strong&gt;` is one golden case); blank-line collapse. The same golden file is asserted by the pytest in Story 2.2 (cross-language parity, C3-B1).

**DoD**
- `pnpm --dir ui vitest run captions-vtt` green; `buildCaptionsVtt` is pure (no fs/Playwright import); AC-3 + AC-7 formatter behavior covered.

### Story 1.2 — Demo-cursor helper (`demo-cursor.ts`)
**Outcome:** the reusable cursor/glide/timer/shot/write helper the 10 specs consume. (FR-1, FR-2, FR-3 write half.)

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/helpers/demo-cursor.ts` | `installCursor`, `glide`, `StepTimer`, `shot`, `writeCaptionsVtt`. |

**Key interfaces**

```ts
import type { Locator, Page } from '@playwright/test';
import { buildCaptionsVtt, type StepTiming } from './captions-vtt';

export async function installCursor(page: Page): Promise<void>;
// MOUSE_HELPER = the proven arrow-pointer addInitScript (idea-embedded): guard window.__mh up front,
// DEFER attach until document.body (DOMContentLoaded fallback), pointer-events:none, z-index high.
export async function glide(page: Page, loc: Locator, settleMs?: number): Promise<void>;
// scrollIntoViewIfNeeded → page.mouse.move(centre, {steps:30}) → waitForTimeout(settleMs ?? 900)
export class StepTimer {
  constructor(startNowMs: number);            // t0
  mark(caption: string): void;                // pushes {startMs: now - t0, caption}
  readonly timings: StepTiming[];
}
// no-op under process.env.DEMO_VIDEO_ONLY; else hide the cursor overlay (display:none on #__mh + ring)
// around page.screenshot(opts), then restore.
export async function shot(page: Page, opts: Parameters<Page['screenshot']>[0]): Promise<void>;
// validate slug (^[a-zA-Z0-9_-]+$); if timings empty -> delete <guidesRoot>/<slug>/captions.vtt if it
// exists and return; else write buildCaptionsVtt(timings) to <guidesRoot>/<slug>/captions.vtt (node:fs).
export function writeCaptionsVtt(timings: StepTiming[], slug: string, guidesRoot: string): void;
// Classify the metadata captions (addresses C1-A2 + C2-A1): returns [] ONLY when EVERY screenshot
// lacks a usable (non-empty) caption (→ caller skips/deletes the vtt, graceful); THROWS on PARTIAL
// (some present, some missing/empty); otherwise returns the N captions IN ORDER. Called FIRST (before
// recording) so the spec marks exactly one step per returned caption — single-arg, no markedSteps.
// A final `if (timer.timings.length !== captions.length) throw` safety assert runs before writeCaptionsVtt.
export function loadStepCaptions(metadata: { screenshots: { caption?: string }[] }): string[];
const VIDEO_ONLY = !!process.env.DEMO_VIDEO_ONLY;
```

**Tasks**
1. Port the proven `MOUSE_HELPER` arrow-pointer + click-ring (from the idea) into `installCursor`; keep `pointer-events:none`, the `window.__mh` guard set up front, attach deferred to `DOMContentLoaded` (D-9).
2. Implement `glide`, `StepTimer`, `shot` (video-only no-op + cursor-hide-around-screenshot per D-14), `loadStepCaptions` (zero-vs-partial classifier per C1-A2), `writeCaptionsVtt` (slug validation + internal path + zero-caption delete per D-12/D-15).
3. vitest (in `captions-vtt.test.ts` or a sibling): `writeCaptionsVtt` slug rejection + zero-caption delete (tmp dir, node:fs); **`loadStepCaptions` zero (all-empty → `[]`), partial (throws), complete (N) cases** (addresses C1-A2). `installCursor`/`glide`/`shot` are Playwright-runtime (exercised by the re-record, not unit-tested).

**DoD**
- Helper exports compile (`pnpm --dir ui typecheck`); `writeCaptionsVtt` rejects an unsafe slug + deletes a stale vtt on zero captions; `loadStepCaptions` classifies zero/partial/complete correctly (vitest); `installCursor` injects the arrow + defers attach (verified visually in Epic 3).

### Story 1.3 — Adopt the helper in all 10 specs + config
**Outcome:** every guide spec uses the cursor/glide/timer/shot helper, sources captions from `metadata.json`, and writes its `captions.vtt`; `slowMo` lowered. (FR-2, FR-3.)

**Modified files**

| File | Change |
|---|---|
| `ui/tests/e2e/guides/NN_*.spec.ts` (×10) | `installCursor(page)` once; replace `locator.click()` with `glide(page, locator)` + click; replace `locator.fill(text)` of free-text with `pressSequentially(text, {delay: 55})`; replace `page.screenshot(...)` with `shot(page, ...)`; instantiate `StepTimer`, `mark(caption)` per step (caption read from the deck's `metadata.json` `screenshots[].caption`, order-matched), `writeCaptionsVtt(timer.timings, '<slug>', guidesRoot)` at the end. Caption-source validation (count match + non-empty) before write. |
| `ui/playwright.demo.config.ts` | Lower `slowMo` `350 → 60` in both the top-level `use.launchOptions` (line 42) and the chromium project (line 50). **60 (not 0)** keeps a little incidental settle for post-click animations/navigation in these non-CI demo specs (addresses C4-B2) while the explicit `glide`/`waitForTimeout` drive the visible pacing; spec FR-2 allows 0–80. |

**Tasks**
1. For each of the 10 specs: import the helper + the deck's `metadata.json`; call `const captions = loadStepCaptions(metadata)` UP FRONT (classifies zero/partial/complete per C1-A2); mark exactly one step per `captions[i]`; thread the cursor/glide/shot/timer through the existing flow without changing what's navigated/captured; before `writeCaptionsVtt`, assert `timer.timings.length === captions.length` (fail loud per D-12).
2. Lower `slowMo` to 60 in the demo config (both locations) — small incidental settle + explicit glides (C4-B2). The Epic 3 all-10 operator dry-run is the hard flakiness gate before any binary is committed.
3. Confirm each spec still type-checks (`pnpm --dir ui typecheck`) and the `metadata.json` path resolves. **The correct path is `../../../public/guides/<slug>/metadata.json`** (3 levels: `ui/tests/e2e/guides/` → `ui/`) — matching the existing specs' `path.resolve(__dirname, '../../../public/guides/<slug>')` for `SCREENSHOTS` (addresses C1-A1; the draft's `../../public/` was one level short). Read captions via `loadStepCaptions(metadata)` (Story 1.2 classifier), not a raw inline read.

**DoD**
- All 10 specs compile; each constructs its `captions.vtt` from `metadata.json` captions via `loadStepCaptions`; `slowMo` is **60** (both config locations, C4-B2/C2-B1); the screenshots are guarded by `shot()` (video-only no-op + cursor-hide). Functional verification is the re-record (Epic 3).

**Epic 1 gate:** `captions-vtt` vitest green; helper + 10 specs + config type-check; `writeCaptionsVtt` slug/zero-caption vitest green. (Visual cursor/caption verification deferred to Epic 3's re-record.)

---

## Epic 2 — Website generator + gate + docs

### Story 2.1 — `build_video_block` emits `<track>`; generator copies the vtt
**Outcome:** the website `<video>` gains a captions `<track>` when a deck has a `captions.vtt`, and the generator copies the vtt into the website assets. (FR-4.)

**Modified files**

| File | Change |
|---|---|
| `website/scripts/build_guides.py` | `build_video_block(slug, has_webm, has_mp4, has_vtt)` — add the `has_vtt` param + a `<track kind="captions" src="{base}/captions.vtt" srclang="en" label="Steps" default>` child (after the `<source>`s, before `</video>`), same `../../../assets/guides/<slug>` base. `copy_deck_assets` copies `captions.vtt` when the source exists (add to the copied set). `generate()` computes `has_vtt = "captions.vtt" in copied` and passes it to `emit_deck_page` → `build_video_block`. `emit_deck_page` gains the `has_vtt` plumb (it already receives `copied`; derive there). |
| `backend/tests/unit/scripts/test_build_guides.py` | Add: `<track>` present when `has_vtt=True`, absent when `False`; `captions.vtt` in `copy_deck_assets`'s returned set when the source exists; the `<track src>` uses the `../../../assets/...` depth. |

**Key interfaces**

```python
def build_video_block(slug: str, has_webm: bool, has_mp4: bool, has_vtt: bool) -> str: ...
    # ...existing <source>s... then (if has_vtt):
    #   <track kind="captions" src="{base}/captions.vtt" srclang="en" label="Steps" default>
```

**Tasks**
1. Extend `build_video_block` signature + `<track>` emission; add `captions.vtt` to `copy_deck_assets`; thread `has_vtt` through `emit_deck_page`/`generate`.
2. Unit tests (above). Run `uv run pytest backend/tests/unit/scripts/test_build_guides.py -q`.

**DoD**
- AC-5 (track iff vtt) + AC-6 (copy + in copied-set) pass; existing `build_video_block` tests updated for the new 4-arg signature.

### Story 2.2 — vtt↔metadata consistency check + freshness self-test sub-case
**Outcome:** a deterministic check that each deck's `captions.vtt` cues match its `metadata.json` captions (count + escaped text); the freshness self-test exercises a vtt-bearing deck. (FR-5.)

**New / modified files**

| File | Change |
|---|---|
| `website/scripts/build_guides.py` | Add `verify_captions_consistency(decks)` — for each deck with a `captions.vtt`, parse the cues, assert cue count == screenshot count and each cue body == the same `escape∘normalize` transform applied to the matching `metadata.json` caption; raise `SystemExit(1)` on mismatch. Call it in `generate()` (or expose for the test). Reuse the Python equivalents of `normalizeCaption`/`escapeVttCueText` (small `re`-based helpers). |
| `backend/tests/unit/scripts/test_build_guides.py` | Add: consistency check passes on a matching vtt; fails loudly on a count mismatch + on a text mismatch; **the Python `normalize`/`escape` mirrors are asserted against the SHARED `ui/tests/e2e/helpers/captions-vtt-golden.json`** (same cases the vitest uses) so the two languages can't drift (AC-10 / D-16 / C3-B1). |
| `scripts/ci/test_verify_build_guides_fresh.sh` | Extend the fixture: one fixture deck carries a `metadata.json` caption + a matching `captions.vtt`; assert the gate emits the `<track>`, copies the vtt, and flags drift when the copied vtt is removed. |

**Tasks**
1. Implement the Python `normalize`/`escape` mirrors + `verify_captions_consistency`; wire into `generate()` so a drifted committed vtt fails the build (and thus the gate).
2. Unit + self-test extensions.

**DoD**
- AC-10 passes (count + escaped-text consistency, fail-loud); self-test's new vtt sub-case green; `bash scripts/ci/test_verify_build_guides_fresh.sh` all sub-cases pass.

### Story 2.3 — Documentation
**Outcome:** the runbook explains the new cursor/captions re-record. (FR-6.)

**Modified files**

| File | Change |
|---|---|
| `docs/03_runbooks/website-guides-regen.md` | Add a "Cursor + captions" subsection: re-record with `DEMO_VIDEO_ONLY=1 pnpm --dir ui capture-guides` (writes `captions.vtt`, preserves screenshots), captions sourced from `metadata.json`, the `<track>` on the website player, the `--transcode` MP4 requirement for iOS. |

**Tasks**
1. Write the subsection.

**DoD**
- Runbook covers the re-record + caption flow.

**Epic 2 gate:** `test_build_guides.py` green (track + copy + consistency); self-test green; `mkdocs build --strict` + asset-ref guard green (no vtt yet → no `<track>`, valid); runbook updated.

---

## Epic 3 — Re-record + regenerate (operator-path)

### Story 3.1 — Re-record all 10 decks, transcode, regenerate, commit
**Outcome:** all 10 `walkthrough.webm` + `walkthrough.mp4` + `captions.vtt` refreshed; website assets + generated `.md` (now with `<track>`) regenerated; everything committed. (FR-2/3/4 realized on the real assets; AC-1, AC-2, AC-8.)

**Operator-path — requires the live `make up` stack (UI :3000, API :8000).**

**Tasks**
1. `DEMO_VIDEO_ONLY=1 pnpm --dir ui capture-guides` — re-records all 10 (cursor + glide + captions), writes 10 `captions.vtt`, promotes the 10 `walkthrough.webm`. **Video-only mode preserves the committed screenshots** (no PNG churn).
2. `python website/scripts/build_guides.py --transcode` — re-produces the 10 `walkthrough.mp4` (iOS), copies the vtt + assets into `website/docs/assets/guides/`, regenerates the deck `.md` (now with `<track>`), splices nav unchanged.
3. Verify: `git status` shows refreshed `ui/public/guides/*/walkthrough.{webm,mp4}` + new `*/captions.vtt` + `website/docs/assets/guides/*` + `website/docs/guides/walkthroughs/*.md` (with `<track>`), and **NO change to `ui/public/guides/*/*.png`** (video-only preserved them).
4. `(cd website && mkdocs build --strict)` + `bash scripts/ci/verify_built_site_asset_refs.sh website/site` + `bash scripts/ci/verify_build_guides_fresh.sh` — all green (the `<track src>` resolves; consistency check passes).
5. Manual: `mkdocs serve`, play one deck — cursor glides, click pulses, CC toggle shows synced captions.
6. Commit the binary churn (webm/mp4/vtt/assets/.md) in one commit.

**DoD**
- All 10 decks refreshed with cursor + captions; screenshots unchanged; `mkdocs build --strict` + asset-ref guard + freshness gate green; AC-1/AC-2/AC-8 verified (cursor in a frame, captions synced).

**Escalation:** if the stack is down or `--transcode`/ffmpeg fails, STOP and escalate (operator-path; can't proceed without the live stack).

---

## UI Guidance (required for frontend-facing work)

**N/A — no in-app frontend (no Next.js page/component/route).** The only "UI" touched is: (a) the synthetic cursor overlay injected into the app-under-test *during recording* (a test artifact, fully specified by the `MOUSE_HELPER` markup in the spec/idea), and (b) the website `<video>`'s `<track>` (a single HTML element). No React component inventory, state analysis, `<select>`/enum surface, tooltip/glossary surface, or legacy-parity table applies.

**No legacy behavior parity table** — no user-facing component >100 LOC is deleted or migrated.

---

## 3) Testing workstream

### 3.1 Unit (vitest — `ui/tests/e2e/helpers/captions-vtt.test.ts`)
- `buildCaptionsVtt`/`normalizeCaption`/`escapeVttCueText`: valid WebVTT, N-cues, strictly-increasing/`end>start`, throws on invalid timings, `-->` strip, `&`/`<`/`>` escape, blank-line collapse (Story 1.1).
- `writeCaptionsVtt`: rejects unsafe slug; deletes stale vtt on zero captions (Story 1.2).

### 3.2 Unit (pytest — `backend/tests/unit/scripts/test_build_guides.py`)
- `<track>` present iff `has_vtt`; `captions.vtt` in the copied set; `<track src>` depth; `verify_captions_consistency` pass + fail-loud (count + escaped-text) (Stories 2.1, 2.2).

### 3.3 Freshness self-test (`scripts/ci/test_verify_build_guides_fresh.sh`)
- New vtt-bearing fixture deck: `<track>` emitted, vtt copied, drift flagged (Story 2.2).

### 3.4 Contract / E2E
- N/A — no API/DB. The website video is not in the Playwright CI scope. The recording specs are *demo-capture* specs (real backend, run manually via `capture-guides`), NOT CI E2E — the re-record (Epic 3) is the operator-path functional check, plus `mkdocs build --strict` + the asset-ref guard.

### 3.5 Existing test impact

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/unit/scripts/test_build_guides.py` | `build_video_block(slug, has_webm, has_mp4)` 3-arg calls | several | **Update** — signature gains `has_vtt`; existing calls pass `has_vtt=False` (output unchanged). |
| `ui/tests/e2e/guides/*.spec.ts` | the 10 demo specs | 10 | **Modify** (Story 1.3) — adopt the helper. Not CI-run. |
| `ui/src/__tests__/scripts/...`, `playwright-config-test-ignore.test.ts` | playwright-config guards | — | **Verify no change** — the demo config `slowMo` edit + `DEMO_VIDEO_ONLY` don't affect the config-ignore guard (read it before editing the config). |

### 3.6 Migration verification — N/A (no schema; head stays `0022`).

### 3.7 CI gates
- [ ] `pnpm --dir ui vitest run` (captions-vtt + writeCaptionsVtt)
- [ ] `pnpm --dir ui typecheck` (helper + 10 specs + config)
- [ ] `uv run pytest backend/tests/unit/scripts/test_build_guides.py -q`
- [ ] `bash scripts/ci/test_verify_build_guides_fresh.sh`
- [ ] `bash scripts/ci/verify_build_guides_fresh.sh`
- [ ] `(cd website && mkdocs build --strict)` + `bash scripts/ci/verify_built_site_asset_refs.sh website/site`
- [ ] `build-guides-freshness` + `pr.yml` green on the PR

---

## 4) Documentation update workstream

- **`state.md`** — finalize: merge one-liner, no Alembic head change, branch context.
- **`architecture.md`** — no change (no new service/layer/flow; extends an existing surface).
- **`CLAUDE.md`** — optional one-line note that `captions.vtt` is a committed recording artifact alongside the webm (Generated-artifacts section). Not required.
- `docs/03_runbooks/website-guides-regen.md` — Story 2.3.
- `docs/05_quality/testing.md` — no change (gate scope unchanged; self-test gains a sub-case the section already describes generically).

## 5) Lean refactor workstream

- **5.1 Goals:** keep the demo specs thin by centralizing cursor/pacing/captions in the shared helper (so future `guide-gen` re-records inherit them).
- **5.2 Tasks:** none beyond the helper extraction (Stories 1.1/1.2 are net-new).
- **5.3 Guardrails:** `pnpm --dir ui typecheck` + `make lint` green; no product-scope expansion.

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_website_walkthrough_guides` (`build_video_block`, gate, assets) | Epic 2, 3 | shipped (PR #448, #450) | hard — this extends it |
| Live `make up` stack | Epic 3 re-record | operator-provided (up this session) | can't re-record → escalate |
| `ffmpeg` | Epic 3 `--transcode` | verified present | iOS decks have no MP4 → release gate not met for them (D-13) |
| `metadata.json` captions ×10 | Story 1.3, 2.2 | present | a caption-less deck skips vtt (graceful) |

### Risks

| Risk | L | I | Mitigation |
|---|---|---|---|
| Cursor overlay leaks into screenshots | M | H | Video-only mode (no screenshots) for the re-record + `shot()` hides the overlay defensively (D-14); Story 3.1 task 3 asserts NO PNG change |
| vtt↔video timing drift (non-deterministic) | M | L | Accepted — vtt + webm re-committed together; timing sync is an operator re-record-review step (D-11) |
| Caption with `&`/`<`/`>`/`-->` breaks the cue or the consistency check | L | M | `escape∘normalize` applied symmetrically in build + check (D-16); unit-tested |
| `slowMo` too low makes a spec flaky (no implicit settle) | M | M | Use `slowMo: 60` (not 0) for incidental settle + explicit `glide`/`waitForTimeout` (C4-B2); the Epic 3 all-10 operator dry-run is reviewed before any binary commit |
| Re-record churns ~13 MB binaries | M | L | Accepted (commit-and-mirror posture, like the shipped feature); large-files pre-commit already excludes the guide media trees |

### Failure mode catalog

| Failure | Trigger | Behavior | Recovery |
|---|---|---|---|
| Zero captions for a deck | metadata has no captions | skip vtt + delete stale vtt; no `<track>` | none needed (graceful) |
| Partial/malformed captions | some captions missing/empty or count mismatch | recording fails loudly | fix metadata + re-record |
| vtt↔metadata text/count mismatch | a stale committed vtt | `verify_captions_consistency` SystemExit(1) → gate red | re-record or fix |
| ffmpeg missing during transcode | dev box without ffmpeg | WARN, no mp4 | install ffmpeg; iOS gate blocked for that deck |
| stack down during re-record | no `make up` | specs error | bring stack up; escalate |

## 7) Sequencing and parallelization

1. Epic 1 Stories 1.1 → 1.2 → 1.3 (1.2 depends on 1.1's pure formatter; 1.3 depends on 1.2's helper).
2. Epic 2 Stories 2.1 → 2.2 → 2.3 (2.2 depends on 2.1's copy; can run in parallel with Epic 1 — they touch disjoint files).
3. Epic 3 Story 3.1 LAST — needs Epics 1 + 2 complete (the specs to record + the generator to emit `<track>`).

Parallel: Epic 1 (ui/) and Epic 2 (website/ + backend tests) are disjoint and can be built in parallel; Epic 3 is the serialization point.

## 8) Rollout and cutover

- Single PR off `main` on `feat/walkthrough-video-cursor-captions`. On merge, `deploy-docs.yml` republishes; the website videos show the cursor + captions immediately.
- No feature flag. No migration. The re-record's binaries land in the same PR.

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — captions-vtt.ts + vitest
- [ ] Story 1.2 — demo-cursor.ts
- [ ] Story 1.3 — adopt helper in 10 specs + lower slowMo
- [ ] Story 2.1 — build_video_block `<track>` + vtt copy
- [ ] Story 2.2 — vtt↔metadata consistency + self-test sub-case
- [ ] Story 2.3 — runbook
- [ ] Story 3.1 — re-record + transcode + regenerate + commit (operator-path)

### Blocked items
- Story 3.1 blocked on the live stack (operator-provided).

## 10) Story-by-Story Verification Gate

- [ ] Files created/modified match story scope
- [ ] Helper exports + signatures match the plan
- [ ] Unit tests added (vitest captions-vtt; pytest track/copy/consistency)
- [ ] Commands pass: `pnpm --dir ui vitest run`, `pnpm --dir ui typecheck`, `uv run pytest …test_build_guides.py`, `bash scripts/ci/test_verify_build_guides_fresh.sh`, `(cd website && mkdocs build --strict)`, asset-ref guard
- [ ] No migration (head still `0022`)
- [ ] Epic 3: screenshots unchanged; cursor + captions verified; binaries committed

## 11) Plan consistency review

1. **Endpoint count:** spec §8 = N/A; plan has zero endpoint tables. ✅
2. **Error codes:** spec §7.5 = N/A. ✅
3. **FR coverage:** all 6 FRs in §1, each ≥1 story. ✅
4. **Story file ownership:** `captions-vtt.ts`/`.test.ts` (1.1), `demo-cursor.ts` (1.2), the 10 specs + config (1.3), `build_guides.py`+`test_build_guides.py` (2.1 add track/copy; 2.2 add consistency — same files, additive, sequential), self-test (2.2), runbook (2.3), binaries (3.1). The `build_guides.py` + `test_build_guides.py` shared between 2.1/2.2 are sequential additive edits, not conflicting ownership. ✅
5. **Test assignment:** captions-vtt vitest → 1.1; writeCaptionsVtt vitest → 1.2; track/copy/consistency pytest → 2.1/2.2; self-test → 2.2. All assigned. ✅
6. **Gate arithmetic:** Epic gates match story sets. ✅
7. **Open questions:** spec §19 OQ-1/3/4 resolved (D-1/2/3); OQ-2 (in-app captions) explicitly deferred, not blocking. ✅
8. **Frontend UI Guidance:** N/A (no in-app frontend) — stated. ✅
9. **Enumerated value contracts:** N/A. ✅
10. **Audit events:** N/A (no mutation). ✅
11. **Infra paths verified:** `ui/tests/e2e/helpers/` (helpers home), vitest `include: tests/e2e/**/*.test.ts` (co-located test works), `build_video_block` at `build_guides.py:387` (3-arg today), `copy_deck_assets`:208, `emit_deck_page`:245 (takes `copied`), demo config `slowMo` at lines 42/50, `test_verify_build_guides_fresh.sh` exists. ✅

---

## 12) Definition of plan done

- [x] Every FR (1–6) mapped to stories/tests/docs.
- [x] Every story has New/Modified files, Key interfaces (where code), Tasks, DoD. (Endpoints/Schemas N/A — no API.)
- [x] Test layers scoped: vitest (formatter/writer) + pytest (generator) + bash self-test + manual re-record/`mkdocs --strict`. Contract/E2E N/A with rationale.
- [x] Docs (runbook, state.md) owned.
- [x] Lean refactor scope explicit (helper extraction).
- [x] Epic gates measurable; Epic 3 operator-path flagged.
- [x] Plan consistency review performed, no unresolved findings.
