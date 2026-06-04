// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Pure WebVTT formatter for walkthrough-video step captions
 * (feat_walkthrough_video_cursor_captions).
 *
 * STDLIB-ONLY — imports NOTHING (no @playwright/test, no node:fs), so a vitest
 * (vitest.config `include: tests/e2e/**\/*.test.ts`) can import + unit-test it
 * without browser/app bundling. The Playwright-runtime writer (slug validation +
 * fs write) lives in `demo-cursor.ts`, which re-exports from here.
 *
 * The same `normalizeCaption`/`escapeVttCueText` transforms are mirrored in
 * Python by `website/scripts/build_guides.py`'s consistency check; both are
 * driven by the shared `captions-vtt-golden.json` corpus so they cannot drift.
 */

export interface StepTiming {
  startMs: number;
  caption: string;
}

const TAIL_MS = 4000;

/**
 * Strip the WebVTT cue-separator token `-->` (a literal `-->` inside a cue body
 * would break the file) and collapse all interior whitespace/blank-lines to
 * single spaces (a blank line ends a cue). Runs BEFORE `escapeVttCueText`.
 */
export function normalizeCaption(s: string): string {
  // `split('-->').join('->')` is a LITERAL global replace (no RegExp), matching
  // the Python mirror's `str.replace('-->', '->')` exactly and sidestepping
  // CodeQL's js/bad-tag-filter heuristic — which flags any `/-->/`-style regex
  // as incomplete HTML-comment-end filtering. This is WebVTT cue-separator
  // stripping (the cue separator is exactly `-->`; `--!>` has no WebVTT meaning),
  // not HTML sanitization, so the heuristic is a false positive here.
  return s.split('-->').join('->').replace(/\s+/g, ' ').trim();
}

/**
 * Escape the three characters WebVTT cue payloads interpret as markup. `&` is
 * escaped FIRST so the `&` introduced by `<`/`>` escaping isn't double-escaped.
 */
export function escapeVttCueText(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** The canonical per-cue body transform — normalize then escape. */
export function cueBody(caption: string): string {
  return escapeVttCueText(normalizeCaption(caption));
}

function pad(n: number, width: number): string {
  return String(n).padStart(width, '0');
}

/** Format milliseconds as a WebVTT `HH:MM:SS.mmm` timestamp. */
export function formatTimestamp(ms: number): string {
  let rest = ms;
  const h = Math.floor(rest / 3_600_000);
  rest %= 3_600_000;
  const m = Math.floor(rest / 60_000);
  rest %= 60_000;
  const s = Math.floor(rest / 1000);
  const millis = rest % 1000;
  return `${pad(h, 2)}:${pad(m, 2)}:${pad(s, 2)}.${pad(millis, 3)}`;
}

/**
 * Build a full WebVTT document from `{startMs, caption}[]`. Cue end = the next
 * cue's start; the last cue's end = its start + TAIL_MS. Throws on empty input
 * or non-finite / negative / non-strictly-increasing start times — the caller
 * (writeCaptionsVtt) handles the zero-captions case BEFORE calling this.
 */
export function buildCaptionsVtt(timings: StepTiming[]): string {
  if (timings.length === 0) {
    throw new Error('buildCaptionsVtt: empty timings (caller must skip the vtt for zero captions)');
  }
  for (let i = 0; i < timings.length; i++) {
    const { startMs } = timings[i]!;
    if (!Number.isFinite(startMs) || startMs < 0) {
      throw new Error(`buildCaptionsVtt: cue ${i} start ${startMs} is not finite/non-negative`);
    }
    if (i > 0 && startMs <= timings[i - 1]!.startMs) {
      throw new Error(
        `buildCaptionsVtt: cue ${i} start ${startMs} is not strictly greater than the previous`,
      );
    }
  }
  const lines: string[] = ['WEBVTT', ''];
  for (let i = 0; i < timings.length; i++) {
    const { startMs, caption } = timings[i]!;
    const endMs = i + 1 < timings.length ? timings[i + 1]!.startMs : startMs + TAIL_MS;
    lines.push(`${formatTimestamp(startMs)} --> ${formatTimestamp(endMs)}`);
    lines.push(cueBody(caption));
    lines.push('');
  }
  return lines.join('\n');
}
