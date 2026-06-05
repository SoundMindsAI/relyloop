# Feature Specification — Walkthrough video polish (synthetic cursor, smoother pacing, on-screen captions)

**Date:** 2026-06-04
**Status:** Draft
**Owners:** Product (soundminds.ai) · Engineering (`@SoundMindsAI/relyloop` maintainers)
**Related docs:**
- [`idea.md`](idea.md) — origin brief (with the proven experiment code embedded)
- [`feat_website_walkthrough_guides`](../../implemented_features/2026_06_04_feat_website_walkthrough_guides/feature_spec.md) — the shipped feature this extends (PR #448)
- [`ui/playwright.demo.config.ts`](../../../../../ui/playwright.demo.config.ts) — the demo recording config
- [`ui/scripts/promote-videos.mjs`](../../../../../ui/scripts/promote-videos.mjs) — video promote step
- [`website/scripts/build_guides.py`](../../../../../website/scripts/build_guides.py) — the `<video>` block emitter
- [`.github/workflows/build-guides-freshness.yml`](../../../../../.github/workflows/build-guides-freshness.yml) — the freshness gate

---

## 1) Purpose

- **Problem:** The 10 walkthrough videos shipped by `feat_website_walkthrough_guides` are silent Playwright screen recordings with three usability gaps the user flagged after they went live on relyloop.com: (1) **no mouse cursor** — Playwright's video recording doesn't render the OS pointer, so actions "teleport"; (2) **jerky pacing** — flat `slowMo: 350` + instant cursor jumps feel abrupt; (3) **no on-screen text** — the screenshots carry rich per-step captions (`metadata.json` `screenshots[].caption`) but the videos have none.
- **Outcome:** All 10 walkthrough videos are re-recorded with (1) a visible **synthetic arrow cursor** that glides to each target and pulses on click, (2) **smoother, human-paced** motion, and (3) **WebVTT step captions** synced to the action, surfaced on the website video player. A reusable demo-cursor helper makes future `guide-gen` re-records produce these automatically.
- **Non-goal:** Burning text into the video pixels (we use a toggle-able WebVTT track instead); narrated audio; changing what the walkthroughs *show* (same flows, same steps); regenerating the screenshots (only the videos + captions change).

## 2) Current state audit

### Existing implementations

| Surface | What it does today | Path | Notes from audit |
|---|---|---|---|
| Demo recording config | `video: 'on'` + `slowMo: 350`, viewport 1440×960, `outputDir: test-results/demo-artifacts` | `ui/playwright.demo.config.ts` | The single config all 10 guide specs run under. No cursor; flat slowMo. |
| Guide specs (×10) | Each drives the app through a flow, takes numbered screenshots into `ui/public/guides/<slug>/`, Playwright auto-records the session video | `ui/tests/e2e/guides/NN_*.spec.ts` | Verified: 10 specs. Each imports seed helpers from `../helpers/seed` → resolves to `ui/tests/e2e/helpers/` (NOT a `guides/helpers/` subdir — the idea's path was off; corrected below). |
| Seed + shared helpers | `seed.ts`, `seed_ubi.ts`, `cleanup-core.ts` | `ui/tests/e2e/helpers/` | The home for a new shared `demo-cursor.ts`. |
| Capture pipeline | `pnpm capture-guides` = `playwright test -c playwright.demo.config.ts && node scripts/promote-videos.mjs` | `ui/package.json:18` | Two-step: record, then promote videos. |
| Video promote | Copies `test-results/demo-artifacts/<spec>--…/video.webm` → `ui/public/guides/<slug>/walkthrough.webm` (matches by `NN_` numeric prefix) | `ui/scripts/promote-videos.mjs` | Verified — only promotes `video.webm`. **Stays WebM-only** — the `.vtt` is written directly by the specs (D-2), NOT promoted. |
| MP4 transcode | `python website/scripts/build_guides.py --transcode` produces `walkthrough.mp4` from the webm | `website/scripts/build_guides.py` `run_transcode_pass` | Best-effort; excluded from the freshness gate. |
| `<video>` block emitter | `build_video_block(slug, has_webm, has_mp4)` emits `<video><source mp4><source webm></video>` + sibling download link | `website/scripts/build_guides.py:387` | No `<track>` today. Raw HTML, root-relative `../../../assets/...` depth (per the just-shipped 404 fix). |
| In-app video player | `<video src={`/guides/${guideId}/${state.metadata.video}`} …>` (single `src`, no `<source>`, no `<track>`) | `ui/src/components/guides/guide-viewer.tsx:305` | The in-app `<GuideViewer>` already shows per-step captions in its *slides* mode; video captions there are lower value. |
| Per-step caption source | Each deck's `metadata.json` `screenshots[].caption` (descriptive sentences) | `ui/public/guides/<slug>/metadata.json` | Verified — every deck has one caption per screenshot, 1:1 with the spec's steps. |
| Freshness gate scope | `git status --porcelain` over `website/docs/guides/`, `website/docs/assets/guides/` (`:!*.mp4` excluded), `website/mkdocs.yml` | `scripts/ci/verify_build_guides_fresh.sh:53` | A `.vtt` copied into `website/docs/assets/guides/` is automatically in scope (not mp4-excluded). |

### Navigation and link impact

None. No URLs change. The website `<video>` block gains a `<track>` child; the asset directory gains `captions.vtt` per deck.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/unit/scripts/test_build_guides.py` | unit tests for `build_video_block` (asserts `<source>` shape + `../../../` depth) | several | Add cases for the `<track>` element (present when a `captions.vtt` exists; absent otherwise). |
| `ui/tests/e2e/guides/NN_*.spec.ts` | the 10 recording specs | 10 | Each adopts the shared `demo-cursor` helper (cursor inject + glide + step-timing capture). These are *demo capture* specs (real backend, run manually via `capture-guides`), NOT part of the CI E2E suite. |
| `scripts/ci/test_verify_build_guides_fresh.sh` | freshness-gate self-test | 1 | Extend the fixture so a deck with a `captions.vtt` exercises the `<track>` emission + the vtt copy. |

### Existing behaviors affected by scope change

- **Recording pacing/length:** videos get longer (glides + dwells). The website player + in-app player are unaffected structurally. Decision needed: **no** (longer is acceptable — these are short demos).
- **`build_video_block` output:** gains a conditional `<track>` line. The freshness gate's committed `.md` files change for every deck once captions exist. Decision needed: **no** (regenerated + committed in the same PR).
- **In-app `<GuideViewer>` video:** unchanged in this feature (captions there deferred — see §3 out-of-scope + §19 OQ-2). Decision needed: **no**.

---

## 3) Scope

### In scope

- A reusable **demo-cursor helper** at `ui/tests/e2e/helpers/demo-cursor.ts` exporting:
  - `installCursor(page)` — injects the synthetic arrow-pointer overlay via `page.addInitScript` (the proven arrow markup from the idea: white-fill/dark-outline SVG, tip-anchored, blue click-pulse ring).
  - `glide(page, locator, settleMs?)` — scrolls the target into view, moves the synthetic cursor to its bounding-box centre with `page.mouse.move(..., { steps: 30 })`, dwells `settleMs` (default 900).
  - `StepTimer` — records `t0` at recording start and a `mark(captionText)` per step, accumulating `{ startMs, caption }[]` for the WebVTT build.
  - `shot(page, ...)` — a screenshot wrapper that no-ops under `DEMO_VIDEO_ONLY=1` and otherwise hides the cursor overlay around `page.screenshot` (per FR-2).
  - `writeCaptionsVtt(timings, slug, guidesRoot)` — validates `slug` (`^[a-zA-Z0-9_-]+$`), calls the pure `buildCaptionsVtt(timings)` (in the Node-safe `captions-vtt.ts`), and writes to `<guidesRoot>/<slug>/captions.vtt` (path constructed internally — no arbitrary `outPath`).
- **All 10 guide specs** adopt the helper: install the cursor, replace instant clicks with glide-then-click, type free-text via `pressSequentially` at human cadence, and `mark()` each step with its caption (sourced from the deck's `metadata.json` so the vtt text matches the screenshots).
- **`ui/playwright.demo.config.ts`** lowers `slowMo` (pacing now driven by explicit glides + dwells, so a high flat slowMo would double-slow the micro-steps).
- **`ui/scripts/promote-videos.mjs` stays WebM-only** (it promotes Playwright's auto-named `video.webm` → `walkthrough.webm`). The `captions.vtt` is **written directly** by the specs to `ui/public/guides/<slug>/captions.vtt` (D-2) — NO vtt promotion path is added (corrects the earlier draft; addresses C2-A1).
- **`website/scripts/build_guides.py`** `build_video_block` emits a `<track kind="captions" srclang="en" label="Steps" default src="…/captions.vtt">` child of `<video>` when the deck has a `captions.vtt`; the generator copies `captions.vtt` into `website/docs/assets/guides/<slug>/` (gated like PNG/WebM).
- **Re-record all 10 decks** once (the operator-path step, needs the live `make up` stack), producing 10 new `walkthrough.webm` + 10 `captions.vtt`; `--transcode` re-produces the 10 `walkthrough.mp4`.
- **Tests:** `build_video_block` `<track>` unit cases; a `writeCaptionsVtt` unit test (valid WebVTT, monotonic cues); the freshness-gate self-test extended for a vtt-bearing deck.

### Out of scope

- **In-app `<GuideViewer>` video captions.** The in-app reader already surfaces per-step captions in slides mode; adding a `<track>` to its `<video>` is a deferred follow-up (§19 OQ-2). This feature only adds the `<track>` to the **website** player.
- **Burned-in (pixel) captions** via ffmpeg `drawtext`. WebVTT is chosen (toggle-able, accessible, no re-encode). Burned-in is the rejected alternative (§19 OQ-1).
- **Narrated audio** on the videos.
- **Regenerating the screenshots.** Only the videos + captions change; the numbered PNGs are untouched — enforced by the video-only re-record mode (FR-2), so the cursor overlay never lands in a PNG and the committed screenshots don't churn.
- **Changing what the walkthroughs demonstrate.** Same flows, same steps, same captions — just cursor + pacing + on-screen caption rendering.
- **Per-step branching / interactive video.** Static linear recordings only.

### API convention check

N/A — no API surface. This feature touches the demo-recording pipeline (Playwright specs + config + promote script), the website generator, and a CI gate.

### Phase boundaries

**Single phase.** All three slices ship together in one re-record pass. Rationale: the per-step caption **timing is captured during the recording**, so captions can't be added without re-recording — and re-recording is exactly what cursor + pacing also require. Splitting into "cursor+pacing now, captions later" would force a second full re-record of all 10 decks. Doing all three in one pass is strictly more efficient and avoids double binary churn. The implementation plan MAY structure this as two epics (helper+re-record; captions plumbing) but there is no deferred phase and no `phase*_idea.md`.

## 4) Product principles and constraints

- **The recording pipeline is the source of truth.** The videos + `captions.vtt` are produced by the Playwright demo specs; the website + in-app players are passive consumers. Never hand-edit a `walkthrough.webm` or `captions.vtt`.
- **Captions reuse the screenshot text.** The WebVTT cue text comes from the deck's `metadata.json` `screenshots[].caption`, so the video captions and the on-page screenshot captions stay in lockstep (one source of truth).
- **WebVTT, not burned-in.** Captions are a `<track>` — toggle-able, accessible, no video re-encode, and they don't bloat the binary.
- **Deterministic generator output.** `build_video_block`'s `<track>` emission is a pure function of "does `captions.vtt` exist for this deck" — no clock, no nondeterminism. The vtt content itself is a committed recording artifact (like the webm).
- **Synthetic cursor, not real.** Playwright cannot record the OS cursor; the injected overlay is the standard workaround. It must be `pointer-events:none` and high z-index so it never interferes with the app under test.
- **Re-recording is local + operator-path.** Videos are non-deterministic binaries; they're committed artifacts, re-recorded by a maintainer with the stack up, never regenerated in CI.

### Anti-patterns

- **Do not** burn captions into the video pixels with ffmpeg `drawtext` — it forces a re-encode, can't be toggled off, and bloats the binary. Use the WebVTT `<track>`.
- **Do not** invent caption text for the vtt — reuse the deck's `metadata.json` captions so the video and screenshot captions can't drift.
- **Do not** make the synthetic cursor capture pointer events — it must be `pointer-events:none` so it never blocks a click on the app under test.
- **Do not** add the `<track>` unconditionally — only when the deck has a `captions.vtt`, so a deck recorded before this feature (or a future deck recorded without captions) still renders a valid `<video>`.
- **Do not** regenerate the videos in CI — they're non-deterministic; the freshness gate must NOT diff video/vtt *content* in a way that a re-record would trip (the vtt is committed; the gate checks the generated `.md` + the copied vtt match the committed source).
- **Do not** raise `slowMo` to slow the demo — that multiplies every micro-step of the cursor glide. Pace via explicit `glide`/`waitForTimeout`.
- **Do not** change the screenshots — only the video + captions are in scope.

## 5) Assumptions and dependencies

- **Dependency:** `feat_website_walkthrough_guides` (PR #448, shipped 2026-06-04). Hard dependency — this extends its `build_video_block`, its `ui/public/guides/` assets, its `promote-videos.mjs`, and its `build-guides-freshness` gate. Status: shipped.
- **Dependency:** The live `make up` stack (UI :3000, API :8000) for the re-record. Status: operator-provided; the maintainer runs `pnpm capture-guides` locally. Risk if missing: can't re-record — the feature can't complete (operator-path gate, escalate).
- **Dependency:** `ffmpeg` on the maintainer's machine for `--transcode`. Status: verified present this session. Risk if missing (addresses C1-B4): **iOS Safari cannot play WebM** — so for iOS, the MP4 is the only playback path, not a "fallback". The generator's MP4 step stays best-effort *in general* (a future deck without an MP4 still ships, just with no iOS playback), BUT for **this feature's release** all 10 MP4s MUST be refreshed (they are — re-transcoded this session) so the post-deploy iOS check (cursor + captions over the MP4) is meaningful. If `--transcode` fails for a deck, that deck's iOS verification is blocked and the release gate is not met for it.
- **Dependency:** Each deck's `metadata.json` `screenshots[].caption`. Status: present for all 10. Risk if missing: a deck with no captions emits no vtt and no `<track>` (graceful).
- **Dependency:** None on backend, DB, or any RelyLoop service.

## 6) Actors and roles

- Primary actor: **Public-site visitor** watching a walkthrough video (anonymous, read-only) — now sees a cursor + captions.
- Secondary actor: **Maintainer** who re-records (`pnpm capture-guides` + `python website/scripts/build_guides.py --transcode`).

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — no state mutation (demo-recording tooling + static site assets).

---

## 7) Functional requirements

### FR-1: Reusable demo-cursor helper
- Requirement:
  - The system **MUST** provide `ui/tests/e2e/helpers/demo-cursor.ts` exporting `installCursor(page)`, `glide(page, locator, settleMs?)`, and `StepTimer`. The **pure WebVTT formatter** `buildCaptionsVtt(timings): string` **MUST** live in a separate Node-safe module `ui/tests/e2e/helpers/captions-vtt.ts` that imports NOTHING from `@playwright/test` (only `node:*` / stdlib), so a vitest can import + unit-test it without browser/app bundling (addresses C1-B1). `demo-cursor.ts` re-exports a thin `writeCaptionsVtt(timings, slug, guidesRoot)` that calls `buildCaptionsVtt` and writes to a path it constructs internally from a **validated** slug (addresses C1-A3 — the write path is built from a safe-slug regex inside the helper, NOT from an arbitrary caller-supplied `outPath`).
  - `installCursor` **MUST** inject (via `page.addInitScript`) the arrow-pointer overlay proven in the experiment: a tip-anchored SVG arrow (white fill, dark outline, drop shadow) + a blue click-pulse ring on `mousedown`, both `pointer-events:none` at `z-index >= 2147483646`. The injected script **MUST** set the `window.__mh` idempotency guard FIRST (so a second `addInitScript` on the same page no-ops) but DEFER the DOM attach until `document.body` exists — `if (document.body) attach(); else addEventListener('DOMContentLoaded', attach)` — so the overlay still appears when the init script runs before body parse, on every navigation (addresses C1-A1). The guard guarding *install registration* (not *successful attach*) is correct because attach is deferred, not skipped.
  - `glide` **MUST** scroll the target into view, move the synthetic cursor to its bounding-box centre via `page.mouse.move(cx, cy, { steps: 30 })`, then `waitForTimeout(settleMs)` (default 900).
- Notes: The helper is the single place future `guide-gen` re-records pull cursor + pacing from, so the 10 specs stay thin. Splitting the pure formatter into `captions-vtt.ts` keeps it unit-testable.

### FR-2: Synthetic arrow cursor + smoother pacing in all 10 specs
- Requirement:
  - Each `ui/tests/e2e/guides/NN_*.spec.ts` **MUST** call `installCursor(page)` once at the start (before the first navigation).
  - Each spec **MUST** replace instant `locator.click()` with `glide(page, locator)` then `locator.click()`, and replace `locator.fill(text)` of free-text inputs with `locator.pressSequentially(text, { delay: 50–60 })` for human cadence.
  - `ui/playwright.demo.config.ts` **MUST** lower `slowMo` (to a small value, e.g. `0`–`80`) so the stepped glides stay smooth; pacing is driven by `glide`/`waitForTimeout`, not flat slowMo.
  - **Screenshots must NOT change (addresses C3-B1).** The synthetic cursor is a DOM overlay, and `page.screenshot` captures the DOM — so a naive re-run would bake the cursor into the committed PNGs (violating the "screenshots unchanged" non-goal). Two guards, both required:
    1. **This feature's re-record runs in a video-only mode** (env-gated, e.g. `DEMO_VIDEO_ONLY=1`) that makes every `page.screenshot(...)` call a no-op via a shared `shot(page, ...)` wrapper. The full navigation (for the video) + `StepTimer.mark` (for captions) still run; the committed numbered PNGs are left **untouched** (no churn). This matches the user's intent — only the videos + captions change.
    2. **Defensively, the shared `shot()` wrapper hides the cursor overlay** (`display:none` on the `__mh` element + the pulse ring) immediately before `page.screenshot` and restores it after — so that ANY future full re-record (e.g. a `guide-gen` screenshot refresh) never captures the cursor in a PNG, even when not in video-only mode.
- Notes: Validated by a throwaway experiment on deck 02 (arrow cursor + glides), approved by the user.

### FR-3: WebVTT step captions
- Requirement:
  - Each spec **MUST** instantiate a `StepTimer` at recording start and `mark(caption)` at each step, sourcing `caption` from the deck's `metadata.json` `screenshots[].caption` (1:1 with the steps), then write `ui/public/guides/<slug>/captions.vtt` on completion (per D-2, written directly — the webm still promotes via `promote-videos.mjs`).
  - **Caption-source validation (addresses C1-B3).** Before writing, the spec/helper **MUST** assert that the number of marked steps equals the number of `metadata.json` screenshots AND every sourced caption is a non-empty string. **Zero captions → skip the vtt entirely AND delete any pre-existing `ui/public/guides/<slug>/captions.vtt`** (addresses C3-A1 — a deck that loses its captions must not leave a stale vtt that the generator would still copy + `<track>`; the generator's `prune_all` then removes the stale website copy since no vtt is copied). **Partial/malformed captions** (some missing, empty, or a step/screenshot count mismatch) → **fail the recording loudly** with a clear error (never emit `undefined`/empty cues or violate the one-cue-per-screenshot invariant).
  - **`buildCaptionsVtt` validity rules (addresses C1-A2 + C1-A7/D-7).** The pure formatter **MUST** emit valid WebVTT:
    - a `WEBVTT` header followed by a blank line;
    - one cue per step; cue starts are **finite, non-negative, and strictly increasing**, so every cue has `end > start` (each cue's end = the next step's start; the last cue's end = its start + a fixed tail, e.g. 4 s); a non-finite/negative/non-increasing timing input is a hard error;
    - timestamps formatted `HH:MM:SS.mmm`;
    - cue bodies **normalized to safe text**: strip the WebVTT cue-separator token `-->`, collapse interior blank lines (a blank line ends a cue), and **escape `<`, `>`, `&`** (WebVTT cue payloads interpret `<…>` as cue markup — so caption text is NOT written fully as-is; it is escaped). This corrects the §10 "plain text" overclaim.
- Notes: The caption text is reused from `metadata.json`, so the video captions and screenshot captions cannot drift. Timing is measured during the (non-deterministic) recording — the vtt is a committed recording artifact, like the webm.

### FR-4: Website `<video>` gains a caption `<track>`
- Requirement:
  - `build_video_block(slug, has_webm, has_mp4, has_vtt)` (signature extended with `has_vtt`) **MUST** emit `<track kind="captions" src="<base>/captions.vtt" srclang="en" label="Steps" default>` as a child of `<video>` when `has_vtt` is true, using the same root-relative `<base>` (`../../../assets/guides/<slug>`) as the existing `<source>` elements.
  - The generator **MUST** copy `ui/public/guides/<slug>/captions.vtt` → `website/docs/assets/guides/<slug>/captions.vtt` when present (so the website serves it), included in `copy_deck_assets`'s returned set.
  - When a deck has no `captions.vtt`, the `<video>` block **MUST** render exactly as today (no `<track>`), so the feature degrades gracefully per-deck.
- Notes: The `.vtt` lands under `website/docs/assets/guides/` which is already in the freshness-gate scope (not mp4-excluded), so a stale/missing vtt copy trips the gate.

### FR-5: Freshness gate + vtt↔metadata consistency check
- Requirement:
  - The `build-guides-freshness` gate's scope **MUST** continue to cover `website/docs/assets/guides/` (it already does) so the copied `captions.vtt` is gated for **copy-drift** (the website copy must match the committed source). The self-test **MUST** be extended so a vtt-bearing deck exercises the `<track>` emission + the vtt copy + the gate's drift detection.
  - **Scope clarification (addresses C1-B2):** the gate proves the website **copy == committed source vtt** — it does NOT and cannot prove the committed vtt's *timing* matches the committed video (both are re-recorded together and committed consistently). To catch the catchable half — caption **text/count** drift between the vtt and `metadata.json` — the generator (or a unit/gate check) **MUST** statically verify, per deck with a vtt, that the cue count equals the screenshot count AND each parsed vtt cue body equals **the same transform** applied to the matching `metadata.json` caption — i.e. compare `cue_body == escapeVttCueText(normalizeCaption(metadata_caption))`, applying the identical `-->`-strip + blank-line-collapse + `<>&`-escape pipeline `buildCaptionsVtt` used (addresses C2-A2 — a raw-vs-escaped comparison would false-fail on captions containing `&`/`<`/`>`/`-->`). Video↔vtt **timing** sync remains a documented operator verification step during re-record review (§16).
  - `backend/tests/unit/scripts/test_build_guides.py` **MUST** assert: `<track>` present when `has_vtt`; absent when not; `captions.vtt` is in the copied-asset set when the source exists; and the vtt↔metadata text/count consistency check fails loudly on a mismatch.
- Notes: No change to the gate script's pathspec — the vtt is already inside the gated `assets/guides/` tree. The new consistency check is deterministic (vtt + metadata are both committed text).

### FR-6: Documentation
- Requirement:
  - `docs/03_runbooks/website-guides-regen.md` **MUST** be updated: how to re-record with the new cursor/captions (`pnpm capture-guides` now also writes `captions.vtt`), how captions are sourced from `metadata.json`, and the `--transcode` MP4 step (unchanged).
  - The `guide-gen` skill reference (or a short note in the runbook) **MUST** mention that re-records now carry cursor + pacing + captions via the shared `demo-cursor` helper.
- Notes: Keeps the operator able to re-record correctly.

## 8) API and data contract baseline

N/A — no API surface.

### 7.4 Enumerated value contracts

N/A — no filter/sort/status/dropdown surface. (The WebVTT `kind="captions"` / `srclang="en"` are fixed HTML attribute values, not a backend-validated allowlist.)

### 7.5 Error code catalog

N/A — no API. The `writeCaptionsVtt` / generator surfaces produce CLI errors (e.g. a malformed-timing guard), not API error codes.

---

## 9) Data model and state transitions

N/A — no DB. No migration. Alembic head stays `0022_solr_engine_auth_check`.

### Required invariants

- For every deck, `ui/public/guides/<slug>/captions.vtt` (when present) has exactly one cue per `metadata.json` screenshot, in order, with strictly-increasing start times (`end > start`).
- `website/docs/assets/guides/<slug>/captions.vtt` is a byte-identical copy of the source `ui/public/guides/<slug>/captions.vtt` (the generator copies, never transforms).
- `build_video_block` emits a `<track>` **iff** the deck has a copied `captions.vtt` (graceful per-deck degradation).
- Each WebVTT cue body equals `escapeVttCueText(normalizeCaption(<metadata caption>))` — the same transform `buildCaptionsVtt` applies (NOT raw equality; addresses C3-A2). `metadata.json` is the single caption source.

### State transitions

N/A.

### Idempotency/replay behavior

- `build_video_block` + the asset copy are idempotent and deterministic given a fixed `ui/public/guides/` tree.
- Re-recording is non-deterministic (timing jitter) — the resulting webm + vtt are committed artifacts, re-committed together on each re-record so the vtt stays in sync with its video.

---

## 10) Security, privacy, and compliance

- **Threats:**
  1. The injected cursor script interferes with the app under test (blocks clicks, mutates state).
  2. A malicious `metadata.json` caption injects markup into the WebVTT or the `<track>`.
  3. Path traversal via a deck slug when writing `captions.vtt`.
- **Controls:**
  1. The cursor overlay is `pointer-events:none`, appended to `document.body`, never intercepts events; `addInitScript` runs it in the page context but it only reads `mousemove`/`mousedown` and renders — no app-state mutation.
  2. WebVTT cue payloads support cue **markup** (`<…>` spans), so caption text is NOT written as-is — `buildCaptionsVtt` **escapes `<`, `>`, `&`** and strips the `-->` cue-separator + interior blank lines (per FR-3). The website `<track>` references a static `.vtt`; no inline injection.
  3. **The first write of `captions.vtt` is UI-side (the Playwright helper), NOT `build_guides.py`** — so the Python slug guards do NOT protect that write (addresses C1-A3). The helper's `writeCaptionsVtt(timings, slug, guidesRoot)` validates `slug` against a shared safe-slug regex (`^[a-zA-Z0-9_-]+$`, mirroring `build_guides.py`'s `SLUG_RE`) and constructs the path internally as `<guidesRoot>/<validated-slug>/captions.vtt` — it does NOT accept an arbitrary caller `outPath`. The Python `build_guides.py` slug guard independently protects the website **copy** path.
- **Secrets/key handling:** N/A.
- **Auditability:** N/A.
- **Data retention/deletion/export:** N/A — public docs assets.

---

## 11) UX flows and edge cases

### Information architecture

No navigation change. On a website walkthrough deck page (`/guides/walkthroughs/<slug>/`), the `<video>` player gains a captions toggle (the browser's native CC button) and shows the step caption synced to playback. The on-page screenshot captions below are unchanged.

### Tooltips and contextual help

N/A — public docs site; the video player uses the browser's native caption controls. No glossary/tooltip surface.

### Primary flows

1. **Visitor watches a deck video with captions.** The arrow cursor glides to each control, clicks (blue pulse), and the step caption appears synced to the action. The viewer can toggle captions via the native CC button.
2. **Maintainer re-records after a UI change.** `pnpm capture-guides` (stack up) re-records all 10 with cursor + pacing + captions, writes 10 `captions.vtt`; `python website/scripts/build_guides.py --transcode` refreshes MP4s + copies the vtt into the website assets; commit.

### Edge/error flows

- **Deck has no captions.json captions:** no vtt written, no `<track>` — valid video, no captions (graceful).
- **Caption text contains `-->`:** `writeCaptionsVtt` sanitizes it so the cue isn't broken.
- **A step's element never appears (spec timeout):** the recording fails loudly (Playwright), same as today — the maintainer fixes the spec and re-records.
- **vtt copied but webm re-recorded separately (out of sync):** the freshness gate diffs both under `assets/guides/`; a committed source vtt that doesn't match its copy trips the gate.
- **iOS Safari:** WebVTT `<track>` is supported; captions render over the MP4 source (the MP4-first ordering from the shipped feature is unchanged).

## 12) Given/When/Then acceptance criteria

### AC-1: Synthetic arrow cursor renders in the re-recorded video
- Given the demo-cursor helper installed in a guide spec,
- When the spec records,
- Then the resulting `walkthrough.webm` shows a visible arrow pointer that moves to each interacted element and pulses on click (verified by extracting a mid-recording frame and confirming the cursor element is present).

### AC-2: Smoother pacing — cursor glides, free-text typed at human speed
- Given a spec using `glide` + `pressSequentially`,
- When it records,
- Then the cursor visibly travels to each target (not teleport) and free-text fields are typed character-by-character; `slowMo` in the demo config is ≤ 80.

### AC-3: WebVTT captions written, valid, one cue per step
- Given a deck with N screenshot captions,
- When the spec records and calls `writeCaptionsVtt`,
- Then `ui/public/guides/<slug>/captions.vtt` exists, parses as valid WebVTT, has exactly N cues with strictly-increasing start times (`end > start`), and each cue body equals `escapeVttCueText(normalizeCaption(<matching metadata caption>))` — the same transform `buildCaptionsVtt` applies, NOT the raw caption (addresses C3-A2).
- Example: a `writeCaptionsVtt` unit test feeds `[{startMs:0,caption:'A'},{startMs:2500,caption:'B'}]` and asserts two cues `00:00:00.000 --> 00:00:02.500` / `00:00:02.500 --> 00:00:06.500` with bodies `A` / `B`.

### AC-4: Caption text reuses metadata.json (no drift)
- Given a deck's `captions.vtt` and its `metadata.json`,
- When both are read,
- Then each ordered vtt cue body equals `escapeVttCueText(normalizeCaption(<ordered screenshots[].caption>))` (the same transform `buildCaptionsVtt` applies — so captions with `&`/`<`/`>`/`-->` compare correctly, addresses C3-A2), and the cue count equals the screenshot count.

### AC-5: `<track>` emitted only when a vtt exists
- Given `build_video_block(slug, has_webm=True, has_mp4=True, has_vtt=True)`,
- When it runs,
- Then the `<video>` block contains `<track kind="captions" src="../../../assets/guides/<slug>/captions.vtt" srclang="en" label="Steps" default>`.
- And with `has_vtt=False`, the block contains no `<track>` (byte-identical to today's output).

### AC-6: Generator copies the vtt + gate covers it
- Given a deck with `ui/public/guides/<slug>/captions.vtt`,
- When the generator runs,
- Then `website/docs/assets/guides/<slug>/captions.vtt` is a byte-identical copy and appears in `copy_deck_assets`'s returned set; the freshness gate's `git status` scope (which includes `assets/guides/`, not mp4-excluded) flags any drift.

### AC-7: Caption `-->` sanitized
- Given a caption containing the literal `-->`,
- When `writeCaptionsVtt` runs,
- Then the emitted cue does not contain a stray `-->` in its body (sanitized), and the file still parses as valid WebVTT.

### AC-8: All 10 decks re-recorded + captioned
- Given the re-record run (`pnpm capture-guides` + `--transcode`),
- When it completes,
- Then all 10 `ui/public/guides/<slug>/{walkthrough.webm,walkthrough.mp4,captions.vtt}` are refreshed and the website assets + generated `.md` (with `<track>`) are regenerated and committed; `mkdocs build --strict` + the freshness gate + the asset-ref guard all pass.

### AC-9: Graceful degradation for a caption-less deck; loud failure on partial captions
- Given a hypothetical deck with a `metadata.json` that has NO captions,
- When the recording runs,
- Then no `captions.vtt` is written, no `<track>` is emitted, and the deck's `<video>` renders normally.
- And given a deck with PARTIAL/malformed captions (some screenshots missing/empty `caption`, or a step↔screenshot count mismatch),
- When the recording runs,
- Then it FAILS LOUDLY with a clear error rather than emitting `undefined`/empty cues (addresses C1-B3).

### AC-10: vtt↔metadata text/count consistency check
- Given a deck with `captions.vtt` whose cue count differs from the screenshot count, OR a cue body that differs from `escapeVttCueText(normalizeCaption(metadata caption))` (the same transform `buildCaptionsVtt` applies),
- When the generator's (or a unit) consistency check runs,
- Then it fails loudly identifying the deck + the mismatch. The freshness gate's copy-drift check (website copy == source) is separate and does NOT cover this semantic check (addresses C1-B2).
- Example: a metadata caption `Boost title & description <strong>2.5×</strong>` matches a vtt cue body `Boost title &amp; description &lt;strong&gt;2.5×&lt;/strong&gt;` (escaped), NOT the raw string (addresses C2-A2).

## 13) Non-functional requirements

- **Performance:** Re-recording all 10 decks takes ~2–5 min locally (glides + dwells lengthen each spec); the website build + generator are unaffected (<3 s). Caption files are tiny (<2 KB each).
- **Reliability:** `build_video_block` + the vtt copy are deterministic; `writeCaptionsVtt` is pure given its inputs. Re-recording is non-deterministic but produces self-consistent webm+vtt pairs.
- **Operability:** The runbook documents the re-record. The freshness gate + asset-ref guard catch a stale/missing vtt or a broken `<track>` path.
- **Accessibility/usability:** WebVTT captions are a genuine a11y win — screen-reader/caption users get the step narration; the native CC toggle is keyboard-accessible. The arrow cursor improves follow-along comprehension for all viewers.

## 14) Test strategy requirements (spec-level)

- **Unit (`backend/tests/unit/scripts/test_build_guides.py`):** `<track>` present iff `has_vtt`; `captions.vtt` in the copied set; the `<track>` uses the `../../../assets/...` depth.
- **Unit (`ui/src/__tests__/lib/captions-vtt.test.ts`, vitest):** imports the **pure** `buildCaptionsVtt` from `ui/tests/e2e/helpers/captions-vtt.ts` (Node-safe, no `@playwright/test` import — addresses C1-B1) and asserts: valid `WEBVTT` header; N cues for N steps; strictly-increasing starts with `end > start`; non-finite/negative/non-increasing input is a hard error; `-->` stripped; `<`/`>`/`&` escaped; interior blank lines collapsed. Also a slug-validation test that `writeCaptionsVtt` rejects an unsafe slug.
- **Freshness self-test (`scripts/ci/test_verify_build_guides_fresh.sh`):** extend a fixture deck with a `captions.vtt` → assert the gate emits the `<track>`, copies the vtt, and flags drift when the vtt is stale.
- **Integration/contract/E2E:** N/A (no API/DB; the website video is not in the Playwright CI scope). The re-record itself is the operator-path "integration" check, plus `mkdocs build --strict` + the asset-ref guard.
- **Manual:** play a re-recorded deck on the local `mkdocs serve` + on relyloop.com post-deploy; confirm the cursor glides, the click pulses, and the captions toggle + sync.

## 15) Documentation update requirements

- `docs/03_runbooks/website-guides-regen.md` — UPDATE: re-record now produces cursor + pacing + `captions.vtt`; captions sourced from `metadata.json`; the `<track>` on the website player.
- `docs/05_quality/testing.md` — no change (the gate scope is unchanged; the self-test gains a sub-case but the section text already describes it generically). Optional: note the vtt is covered.
- `CLAUDE.md` — no new convention. (Optionally note `captions.vtt` as a committed recording artifact alongside the webm under the Generated-artifacts section.)
- `docs/01_architecture` / `02_product` / `04_security` — N/A.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. On merge + deploy, the website videos show the cursor + captions immediately.
- **Migration/backfill:** None.
- **Operational readiness gates:** the re-record is a local operator-path step (stack up); the freshness gate + asset-ref guard + `mkdocs build --strict` gate the website output.
- **Release gate:** `build-guides-freshness` green (incl. the new vtt self-test sub-case), `mkdocs build --strict` exit 0, asset-ref guard green, all 10 decks re-recorded + committed, cross-model review per `/impl-execute`.
- **Post-deploy verification:** play one deck on relyloop.com (Chrome + iOS Safari): cursor glides, click pulses, CC toggle shows synced step captions.

## 17) Traceability matrix

| FR ID | Acceptance Criteria | Planned stories | Test files | Docs |
|---|---|---|---|---|
| FR-1 (demo-cursor helper) | AC-1, AC-2, AC-3 | Epic 1 Story 1.1 | `ui` vitest for `writeCaptionsVtt` | runbook |
| FR-2 (cursor + pacing in 10 specs) | AC-1, AC-2, AC-8 | Epic 1 Story 1.2 + the re-record story | the 10 specs (manual capture) | runbook |
| FR-3 (WebVTT captions) | AC-3, AC-4, AC-7 | Epic 1 Story 1.1 + 1.2 | `writeCaptionsVtt` vitest | runbook |
| FR-4 (website `<track>` + copy) | AC-5, AC-6, AC-9 | Epic 2 Story 2.1 | `test_build_guides.py` | runbook |
| FR-5 (gate + vtt↔metadata check) | AC-6, AC-10 | Epic 2 Story 2.2 | `test_verify_build_guides_fresh.sh`, `test_build_guides.py` (AC-10 check) | testing.md (optional) |
| FR-6 (docs) | AC-8 | Epic 2 Story 2.3 | — | runbook |

## 18) Definition of feature done

- [ ] All ACs (AC-1 … AC-10) pass (unit + self-test in CI; cursor/caption visuals verified manually).
- [ ] `demo-cursor.ts` helper exists with the 4 exports; all 10 specs adopt it.
- [ ] `slowMo` lowered in the demo config.
- [ ] All 10 decks re-recorded: refreshed `walkthrough.webm` + `walkthrough.mp4` + new `captions.vtt`, committed.
- [ ] `build_video_block` emits the `<track>` when a vtt exists; the generator copies the vtt; freshness gate + self-test cover it.
- [ ] `mkdocs build --strict` + the raw-HTML asset-ref guard pass (the `<track src>` resolves).
- [ ] Runbook updated.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

- **OQ-1 (RESOLVED → decision D-1):** WebVTT vs burned-in captions. **Decision: WebVTT `<track>`.**
- **OQ-2:** In-app `<GuideViewer>` video captions. The in-app reader already shows per-step captions in slides mode; adding a `<track>` to its `<video src=…>` (which would need restructuring to `<source>`+`<track>`) is **deferred** to a follow-up. Owner: maintainers. Due: post-merge if requested. **Not blocking** — this feature is website-`<track>`-only.
- **OQ-3 (RESOLVED → decision D-2):** Where the spec writes `captions.vtt` (Playwright output dir + promote, vs directly to `ui/public/guides/<slug>/`). **Decision: the spec writes directly to `ui/public/guides/<slug>/captions.vtt`** (simpler than threading through promote-videos; the webm still goes via promote since Playwright names it). The plan confirms the exact mechanism.
- **OQ-4 (RESOLVED → decision D-3):** Caption timing persistence. **Decision: timings are measured live during the recording and written straight into `captions.vtt`** (no separate `timings.json` sidecar — the vtt IS the persisted artifact, committed alongside the webm). A re-record rewrites both together, keeping them in sync.

### Decision log

- **2026-06-04 — D-0:** Single phase, all three slices, one re-record pass — because caption timing is captured during recording, so captions can't be added without re-recording, which cursor+pacing also require. Splitting would double the re-record.
- **2026-06-04 — D-1:** WebVTT `<track>` over burned-in `drawtext` — toggle-able, accessible, no re-encode, no binary bloat, reuses `metadata.json` text.
- **2026-06-04 — D-2:** The spec writes `captions.vtt` directly to `ui/public/guides/<slug>/` (the webm still promotes via `promote-videos.mjs` because Playwright auto-names it). Avoids extending the promote matcher for the vtt.
- **2026-06-04 — D-3:** Timings measured live → written straight into the committed `captions.vtt`; no `timings.json` sidecar. The vtt is a committed recording artifact like the webm; a re-record rewrites both in sync.
- **2026-06-04 — D-4:** Caption text reuses `metadata.json` `screenshots[].caption` (not a new caption source) so the video captions and on-page screenshot captions cannot drift.
- **2026-06-04 — D-5:** In-app `<GuideViewer>` video captions deferred (OQ-2) — the in-app reader already surfaces captions in slides mode; website-only `<track>` here.
- **2026-06-04 — D-6:** Shared helper at `ui/tests/e2e/helpers/demo-cursor.ts` (corrected from the idea's `guides/helpers/` path — specs import from `../helpers/`, which resolves to `ui/tests/e2e/helpers/`).
- **2026-06-04 — D-7:** `writeCaptionsVtt` sanitizes the WebVTT cue-separator token `-->` out of caption bodies so a caption containing it can't break a cue.
- **2026-06-04 — D-8:** No new freshness-gate pathspec — `captions.vtt` lands under the already-gated `website/docs/assets/guides/` tree (not mp4-excluded), so it's covered automatically; only the self-test gains a sub-case.
- **2026-06-04 — D-9 (from C1-A1):** The cursor init-script sets the `window.__mh` guard up front but DEFERS the DOM attach until `document.body` exists (`DOMContentLoaded` fallback) — the guard guards install *registration*, not *successful attach*, so the overlay still appears after navigations where the init script runs pre-body.
- **2026-06-04 — D-10 (from C1-A2 + C1-A3 + C1-B1):** The pure WebVTT formatter `buildCaptionsVtt` lives in a Node-safe `ui/tests/e2e/helpers/captions-vtt.ts` (no `@playwright/test` import) so a vitest can unit-test it; it enforces finite/non-negative/strictly-increasing starts (`end > start`), strips `-->`, escapes `<`/`>`/`&`, collapses blank lines. The thin `writeCaptionsVtt(timings, slug, guidesRoot)` validates the slug against `^[a-zA-Z0-9_-]+$` and builds the path internally (no arbitrary `outPath`) — the UI-side write is NOT protected by `build_guides.py`'s Python slug guard.
- **2026-06-04 — D-11 (from C1-B2):** The freshness gate catches website-copy-vs-source **copy drift**, NOT video↔vtt **timing** sync. A deterministic vtt↔`metadata.json` **text/count** consistency check (AC-10) catches caption drift; video↔vtt timing sync stays a documented operator re-record-review step.
- **2026-06-04 — D-12 (from C1-B3):** Zero captions → skip the vtt (graceful); partial/malformed captions → fail the recording loudly. Never emit empty/`undefined` cues.
- **2026-06-04 — D-13 (from C1-B4):** iOS Safari can't play WebM, so MP4 is iOS's only path — for THIS feature's release all 10 MP4s must be refreshed (done); the generator's general best-effort MP4 posture is unchanged for future decks, but a failed `--transcode` blocks that deck's iOS verification + release gate.
- **2026-06-04 — D-14 (from C3-B1):** The cursor overlay must NOT appear in the committed screenshots. Two guards: (1) this feature's re-record uses a video-only mode (`DEMO_VIDEO_ONLY=1`) so `page.screenshot` no-ops and the PNGs are untouched (matches the screenshots-unchanged non-goal); (2) the shared `shot()` wrapper hides the overlay around `page.screenshot` so any future full re-record never bakes the cursor into a PNG.
- **2026-06-04 — D-15 (from C3-A1):** A deck transitioning captioned → caption-less must delete its pre-existing source `captions.vtt` (zero-captions cleanup); the generator's `prune_all` then drops the stale website copy. Prevents a stale vtt + `<track>` after captions are removed.
- **2026-06-04 — D-16 (from C3-A2):** All caption-equality language (AC-3/AC-4/§9/FR-5/AC-10) uses `escapeVttCueText(normalizeCaption(...))` — the same transform the formatter applies — never raw equality, so captions containing `&`/`<`/`>`/`-->` compare correctly.
