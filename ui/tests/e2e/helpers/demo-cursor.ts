// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Demo-recording helpers for the walkthrough guides
 * (feat_walkthrough_video_cursor_captions): a synthetic arrow cursor, smoother
 * stepped-glide motion, per-step caption timing, a screenshot wrapper that keeps
 * the cursor out of PNGs (and no-ops under DEMO_VIDEO_ONLY), and the WebVTT
 * writer.
 *
 * The 10 guide specs (`ui/tests/e2e/guides/NN_*.spec.ts`) import these so they
 * stay thin. The pure WebVTT formatter lives in `captions-vtt.ts` (Node-safe,
 * unit-tested by vitest); this module re-uses it and adds the Playwright-runtime
 * + fs glue. `@playwright/test` is a TYPE-ONLY import (erased at runtime), so
 * vitest can import this module to unit-test `loadStepCaptions` / `writeCaptionsVtt`.
 */

import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import type { Locator, Page } from '@playwright/test';

import { buildCaptionsVtt, type StepTiming } from './captions-vtt';

const VIDEO_ONLY = !!process.env.DEMO_VIDEO_ONLY;
const SLUG_RE = /^[a-zA-Z0-9_-]+$/;
const GLIDE_STEPS = 30;
const DEFAULT_SETTLE_MS = 900;

// The proven arrow-pointer overlay (validated in the deck-02 experiment).
// Tip-anchored white-fill/dark-outline SVG + a blue click-pulse ring; both
// pointer-events:none at the top of the z-stack. The window.__mh guard is set
// up FRONT (so a second addInitScript no-ops) but the DOM attach is DEFERRED
// until document.body exists, so the cursor still appears when the init script
// runs before body parse, on every navigation. Elements carry ids so `shot`
// can hide them around screenshots.
const MOUSE_HELPER = `
(() => {
  if (window.__mh) return; window.__mh = true;
  const attach = () => {
    const c = document.createElement('div');
    c.id = '__mh_cursor';
    c.style.cssText = [
      'position:fixed','z-index:2147483647','pointer-events:none',
      'left:0','top:0','width:22px','height:22px','transform-origin:0 0',
      'transition:transform .08s ease'
    ].join(';');
    c.innerHTML =
      '<svg width="22" height="22" viewBox="0 0 12 19" ' +
      'style="display:block;filter:drop-shadow(0 1px 1.5px rgba(0,0,0,0.45))">' +
      '<path d="M0 0 L0 16.5 L4.2 12.8 L7.1 19 L9.6 17.9 L6.6 11.8 L11.9 11.8 Z" ' +
      'fill="#ffffff" stroke="#1b1b1b" stroke-width="1.3" stroke-linejoin="round"/></svg>';
    const ring = document.createElement('div');
    ring.id = '__mh_ring';
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
`;

/** Inject the synthetic arrow cursor; survives navigations via addInitScript. */
export async function installCursor(page: Page): Promise<void> {
  await page.addInitScript(MOUSE_HELPER);
}

/**
 * Glide the synthetic cursor to a locator's centre, then dwell. Resilient: if a
 * fragile element (e.g. a portal-mounted listbox trigger) can't be scrolled into
 * view or has no stable bounding box, the cursor move is skipped (the spec's
 * own click still drives the action) — one finicky element never fails the
 * whole re-record.
 */
export async function glide(page: Page, loc: Locator, settleMs = DEFAULT_SETTLE_MS): Promise<void> {
  try {
    await loc.scrollIntoViewIfNeeded({ timeout: 3000 });
    const box = await loc.boundingBox();
    if (box) {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: GLIDE_STEPS });
    }
  } catch {
    // Non-fatal — skip the visible glide for this target, still dwell below.
  }
  await page.waitForTimeout(settleMs);
}

/** Accumulates {startMs, caption} per step relative to construction time. */
export class StepTimer {
  private readonly t0 = Date.now();
  readonly timings: StepTiming[] = [];
  mark(caption: string): void {
    this.timings.push({ startMs: Date.now() - this.t0, caption });
  }
}

/**
 * Screenshot wrapper that keeps the synthetic cursor out of the committed PNGs.
 * No-ops under DEMO_VIDEO_ONLY (the re-record for this feature is video-only, so
 * screenshots don't churn). Otherwise hides the cursor + ring around the
 * screenshot so any future full re-record never bakes the cursor into a PNG.
 */
export async function shot(page: Page, opts: Parameters<Page['screenshot']>[0]): Promise<void> {
  if (VIDEO_ONLY) return;
  await page.evaluate(() => {
    for (const id of ['__mh_cursor', '__mh_ring']) {
      const el = document.getElementById(id);
      if (el) (el as HTMLElement).style.visibility = 'hidden';
    }
  });
  try {
    await page.screenshot(opts);
  } finally {
    // Restore the cursor even if the screenshot throws, so the rest of the
    // recording (and any debugging frames) still shows the pointer.
    await page.evaluate(() => {
      for (const id of ['__mh_cursor', '__mh_ring']) {
        const el = document.getElementById(id);
        if (el) (el as HTMLElement).style.visibility = 'visible';
      }
    });
  }
}

/**
 * Classify a deck's metadata captions: returns [] ONLY when EVERY screenshot
 * lacks a usable (non-empty) caption (caller skips/deletes the vtt — graceful);
 * THROWS on PARTIAL (some present, some missing/empty); otherwise returns the N
 * captions in order. Called UP FRONT so the spec marks exactly one step per
 * returned caption.
 */
export function loadStepCaptions(metadata: { screenshots: { caption?: string }[] }): string[] {
  const shots = metadata.screenshots ?? [];
  const usable = shots.map((s) => (typeof s.caption === 'string' ? s.caption.trim() : ''));
  const present = usable.filter((c) => c.length > 0);
  if (present.length === 0) return [];
  if (present.length !== usable.length) {
    throw new Error(
      `loadStepCaptions: partial captions — ${present.length}/${usable.length} screenshots have a ` +
        `non-empty caption (all-or-nothing required)`,
    );
  }
  return usable;
}

/**
 * Write `<guidesRoot>/<slug>/captions.vtt` from the recorded timings. Validates
 * the slug (no traversal). Empty timings → delete any pre-existing vtt and
 * return (zero-captions graceful cleanup). The path is constructed internally —
 * no arbitrary caller-supplied output path.
 */
export function writeCaptionsVtt(timings: StepTiming[], slug: string, guidesRoot: string): void {
  if (!SLUG_RE.test(slug)) {
    throw new Error(`writeCaptionsVtt: unsafe slug ${JSON.stringify(slug)} (must match ${SLUG_RE})`);
  }
  const dir = join(guidesRoot, slug);
  const out = join(dir, 'captions.vtt');
  if (timings.length === 0) {
    if (existsSync(out)) rmSync(out);
    return;
  }
  mkdirSync(dir, { recursive: true });
  writeFileSync(out, buildCaptionsVtt(timings), 'utf-8');
}
