// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import golden from '../captions-vtt-golden.json';
import {
  buildCaptionsVtt,
  cueBody,
  escapeVttCueText,
  formatTimestamp,
  normalizeCaption,
  type StepTiming,
} from '../captions-vtt';

describe('captions-vtt golden corpus (shared with pytest — cross-language parity)', () => {
  for (const c of golden.cases) {
    it(`normalize+escape: ${JSON.stringify(c.input)}`, () => {
      expect(normalizeCaption(c.input)).toBe(c.normalized);
      expect(escapeVttCueText(c.normalized)).toBe(c.escaped);
      expect(cueBody(c.input)).toBe(c.escaped);
    });
  }
});

describe('formatTimestamp', () => {
  it('formats HH:MM:SS.mmm', () => {
    expect(formatTimestamp(0)).toBe('00:00:00.000');
    expect(formatTimestamp(2500)).toBe('00:00:02.500');
    expect(formatTimestamp(3_661_007)).toBe('01:01:01.007');
  });
});

describe('buildCaptionsVtt', () => {
  it('emits a WEBVTT header + blank line, one cue per timing, monotonic cues', () => {
    const timings: StepTiming[] = [
      { startMs: 0, caption: 'A' },
      { startMs: 2500, caption: 'B' },
    ];
    const vtt = buildCaptionsVtt(timings);
    expect(vtt.startsWith('WEBVTT\n\n')).toBe(true);
    expect(vtt).toContain('00:00:00.000 --> 00:00:02.500');
    // last cue end = start + 4000 tail
    expect(vtt).toContain('00:00:02.500 --> 00:00:06.500');
    expect(vtt.split('-->').length - 1).toBe(2); // two cue timelines (literal count, no regex)
  });

  it('escapes & < > and strips --> in cue bodies', () => {
    const vtt = buildCaptionsVtt([
      { startMs: 0, caption: 'Boost title & description <strong>2.5×</strong>' },
      { startMs: 1000, caption: 'go --> there' },
    ]);
    expect(vtt).toContain('Boost title &amp; description &lt;strong&gt;2.5×&lt;/strong&gt;');
    expect(vtt).toContain('go -&gt; there');
    // No stray cue-separator inside a body.
    expect(vtt).not.toContain('go --> there');
  });

  it('throws on empty timings', () => {
    expect(() => buildCaptionsVtt([])).toThrow(/empty timings/);
  });

  it('throws on non-finite / negative start', () => {
    expect(() => buildCaptionsVtt([{ startMs: -1, caption: 'x' }])).toThrow(/non-negative/);
    expect(() => buildCaptionsVtt([{ startMs: Number.NaN, caption: 'x' }])).toThrow(/finite/);
  });

  it('throws on non-strictly-increasing starts', () => {
    expect(() =>
      buildCaptionsVtt([
        { startMs: 1000, caption: 'a' },
        { startMs: 1000, caption: 'b' },
      ]),
    ).toThrow(/strictly greater/);
  });
});
