# Walkthrough video polish — synthetic cursor, smoother pacing, on-screen captions

**Date:** 2026-06-04
**Status:** Idea — user request (validated by a live throwaway experiment on deck 02)
**Priority:** P2
**Origin:** User request after `feat_website_walkthrough_guides` (PR #448) shipped and the videos went live on relyloop.com. The user watched the walkthrough videos and asked: "is it possible to make the video transitions smoother? is it possible to show the mouse position? is it possible to add text to the video, similar to how you can see text on the screenshots?" A throwaway experiment re-recorded deck 02 ("Review a proposal") with a synthetic arrow cursor + smoother pacing and the user approved the direction ("i like this"), then asked to make the cursor an arrow mimicking the default browser pointer (also done + approved). This idea captures that proven approach and extends it with the third ask (captions) across all 10 decks.
**Depends on:** `feat_website_walkthrough_guides` (shipped 2026-06-04, PR #448) — its `website/scripts/build_guides.py` emits the `<video>` block this feature adds a `<track>` to; its `ui/public/guides/<slug>/` assets are what get re-recorded.

## Problem

The 10 walkthrough videos are a **byproduct of the Playwright screenshot specs** (`ui/tests/e2e/guides/NN_*.spec.ts` run under `ui/playwright.demo.config.ts` with `video: 'on'` + `slowMo: 350`, then `ui/scripts/promote-videos.mjs` copies `video.webm` → `ui/public/guides/<slug>/walkthrough.webm`). As shipped they have three usability gaps the user flagged:

1. **No mouse cursor.** Playwright's video recording does NOT render the OS cursor (a known Playwright limitation — the trace viewer shows it, the video does not). So actions "teleport" — a filter chip just changes state, a dialog just appears — with no pointer to follow. Hard to tell what's being clicked.
2. **Jerky pacing.** `slowMo: 350` is a flat per-action delay; combined with instant cursor jumps the result feels abrupt, not like a human demoing the product.
3. **No on-screen text.** The screenshots carry rich per-step captions (from each deck's `metadata.json` `screenshots[].caption`), rendered on the website page beneath each image. The videos have none — a viewer watching the video alone gets no narration of what's happening at each step.

## Proposed capabilities

Three slices, validated (1 + 2) or designed (3) — re-record all 10 decks in one pass.

### 1. Synthetic arrow cursor (PROVEN in the experiment)
Inject a visible arrow pointer (mimicking the default OS/browser cursor) via `page.addInitScript`, so it renders into the recorded video and survives navigations. Arrow is tip-anchored (the hotspot is the top-left tip, like a real cursor), white fill + dark outline + drop shadow for visibility on any background, with a soft blue click-pulse ring on `mousedown`. **Proven working** — this exact helper produced the cursor the user approved:

```js
// Injected via page.addInitScript(MOUSE_HELPER) in the shared spec setup.
(() => {
  if (window.__mh) return; window.__mh = true;
  const attach = () => {
    const c = document.createElement('div');
    c.style.cssText = [
      'position:fixed','z-index:2147483647','pointer-events:none',
      'left:0','top:0','width:22px','height:22px',
      'transform-origin:0 0','transition:transform .08s ease'
    ].join(';');
    c.innerHTML =
      '<svg width="22" height="22" viewBox="0 0 12 19" ' +
      'style="display:block;filter:drop-shadow(0 1px 1.5px rgba(0,0,0,0.45))">' +
      '<path d="M0 0 L0 16.5 L4.2 12.8 L7.1 19 L9.6 17.9 L6.6 11.8 L11.9 11.8 Z" ' +
      'fill="#ffffff" stroke="#1b1b1b" stroke-width="1.3" stroke-linejoin="round"/></svg>';
    const ring = document.createElement('div');
    ring.style.cssText = [
      'position:fixed','z-index:2147483646','pointer-events:none',
      'left:0','top:0','width:26px','height:26px','margin:-13px 0 0 -13px',
      'border-radius:50%','border:2px solid rgba(90,130,255,0.9)',
      'opacity:0','transform:scale(0.4)','transition:transform .25s ease,opacity .25s ease'
    ].join(';');
    document.body.appendChild(c); document.body.appendChild(ring);
    const mv = (e) => {
      c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px';
      ring.style.left = e.clientX + 'px'; ring.style.top = e.clientY + 'px';
    };
    document.addEventListener('mousemove', mv, true);
    document.addEventListener('mousedown', () => {
      c.style.transform = 'scale(0.85)';
      ring.style.opacity = '1'; ring.style.transform = 'scale(1)';
    }, true);
    document.addEventListener('mouseup', () => {
      c.style.transform = 'scale(1)';
      ring.style.opacity = '0'; ring.style.transform = 'scale(0.4)';
    }, true);
  };
  if (document.body) attach(); else document.addEventListener('DOMContentLoaded', attach);
})();
```

### 2. Smoother pacing (PROVEN in the experiment)
Drive the cursor with explicit stepped `page.mouse.move(x, y, { steps: 30 })` glides to each target's bounding-box centre, dwell on each step, and type free-text at human speed (`pressSequentially(..., { delay: 55 })`) instead of `fill()`. Lower `slowMo` (the experiment used `slowMo: 0` and drove ALL pacing via explicit glides + `waitForTimeout`), so the micro-step glides stay smooth. **Proven** — produced the smoother motion the user approved. The shared helper:

```ts
const glide = async (loc: Locator, settle = 900) => {
  await loc.scrollIntoViewIfNeeded();
  const b = await loc.boundingBox();
  if (b) await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 30 });
  await page.waitForTimeout(settle);
};
```

### 3. On-screen step captions (NEW — the third ask)
Surface each deck's existing `metadata.json` `screenshots[].caption` text on the video, synced to the moment that step happens. **Recommended: WebVTT caption track** (non-destructive, toggle-able, accessible, no re-encode) over burned-in ffmpeg `drawtext`.

The missing piece is **per-step timing**: the specs must record a timestamp (relative to recording start) at each step so the caption cue spans the right interval. Approach:
- Capture `t0` at the start of the recorded session; at each step, record `Date.now() - t0` as the cue start; the next step's start (or end-of-video) is the cue end.
- After the run, emit `ui/public/guides/<slug>/captions.vtt` from `(timing[], metadata.captions[])`.
- `promote-videos.mjs` (or a sibling) promotes the `.vtt` alongside the `.webm`/`.mp4`.
- `website/scripts/build_guides.py` `build_video_block` adds `<track kind="captions" src="…/captions.vtt" srclang="en" label="Steps" default>` when the `.vtt` exists.
- Optionally the in-app `<GuideViewer>` (`ui/src/components/guides/guide-viewer.tsx`) gains the same `<track>` so the in-app video shows captions too (decide at spec-time — may be a follow-up).

## Scope signals

- **Backend:** None.
- **Frontend (recording pipeline):** Extract a shared `ui/tests/e2e/guides/helpers/demo-cursor.ts` (the `MOUSE_HELPER` + `glide` + step-timing recorder) and wire it into all 10 `NN_*.spec.ts` (or a shared `test.beforeEach`). Lower `slowMo` in `playwright.demo.config.ts`. Each spec gains glide-to-target + dwell + per-step timing capture. **This re-records all 10 videos** (~13 MB of webm/mp4 churn) + emits 10 `.vtt` files.
- **Frontend (in-app, optional):** `<track>` on `ui/src/components/guides/guide-viewer.tsx`'s `<video>` (spec-time decision).
- **Website:** `website/scripts/build_guides.py` `build_video_block` adds the `<track>` element when `captions.vtt` is present; copies the `.vtt` into `website/docs/assets/guides/<slug>/`; the freshness gate scope gains `*.vtt` (PNG/WebM-style, NOT the MP4 best-effort treatment). `promote-videos.mjs` promotes the `.vtt`.
- **Migration:** None.
- **Config:** Lower `slowMo` in `playwright.demo.config.ts`; possibly a longer per-spec `timeout` (glides + dwells lengthen each run).
- **CI:** The `build-guides-freshness` gate already regenerates + checks; adding `.vtt` to its scope keeps captions in sync. Re-recording is a LOCAL operator-path step (needs the live `make up` stack) — videos are non-deterministic, so they are committed artifacts, NOT regenerated in CI (same posture as today's webm/mp4).
- **Audit events:** N/A.

## Why not yet prioritized

P2: high polish value for the public site's evaluation/onboarding story, but not blocking. The underlying surfacing already shipped (PR #448); this is a quality upgrade to the video artifacts. Slices 1 + 2 are proven; slice 3 (captions) is the real new work (per-step timing + WebVTT plumbing through promote-videos + build_guides + the freshness gate).

## Open questions (resolve at spec-time)

- **OQ-1: WebVTT vs burned-in captions.** Recommend WebVTT (toggle-able, accessible, no re-encode, reuses `metadata.json` text). Burned-in `drawtext` is the alternative if a caption must be visible even when the player's caption UI is off. **Recommendation: WebVTT.**
- **OQ-2: In-app GuideViewer captions.** Does the in-app `<GuideViewer>` video also get the `<track>`, or is that a follow-up? The in-app reader already shows the per-step captions in its slides mode, so video captions there are lower-value. **Recommendation: website-only `<track>` in this feature; in-app as a deferred follow-up.**
- **OQ-3: Re-record determinism + freshness gate.** Re-recorded videos differ byte-for-byte each run (timing jitter). Today the webm/mp4 are committed artifacts the gate does NOT diff (mp4 is excluded; webm IS gated but is committed-and-stable because nobody re-runs the recording in CI). Adding `.vtt` to the gate: the `.vtt` IS deterministic (derived from metadata + recorded timings the spec writes to a committed sidecar?) — OR treat `.vtt` like the webm (committed, gated for presence-not-content). **Resolve the exact gate treatment of `.vtt` at spec-time.**
- **OQ-4: Caption timing source.** The per-step timings are captured during the (non-deterministic) recording. Persist them where? A committed `timings.json` sidecar per deck, regenerated with the video, from which `captions.vtt` is deterministically built? Resolve at spec-time.

## Relationship to other work

- Consumes/extends `feat_website_walkthrough_guides` (PR #448) — the `build_video_block` `<video>` emitter, the `ui/public/guides/` assets, the `promote-videos.mjs` promote step, and the `build-guides-freshness` gate.
- The recording pipeline is the `guide-gen` skill's domain (Playwright specs under `ui/tests/e2e/guides/`); this is the first feature to enhance the *video* output of those specs (guide-gen has historically focused on the screenshots).
- A proven throwaway experiment (deck 02, arrow cursor + smoother pacing) validated slices 1 + 2 before this idea was filed; the exact working code is embedded above so the spec/impl can reuse it verbatim.
