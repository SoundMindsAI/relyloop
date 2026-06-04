// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { mkdtempSync, readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

// `@playwright/test` is a TYPE-ONLY import in demo-cursor.ts (erased at
// runtime), so importing the module here exercises only the Node-safe helpers.
import { loadStepCaptions, writeCaptionsVtt } from '../demo-cursor';
import type { StepTiming } from '../captions-vtt';

// Disposable OS-tmp dirs (no cross-test state; left for the OS to reap).
function freshRoot(): string {
  return mkdtempSync(join(tmpdir(), 'demo-cursor-'));
}

describe('loadStepCaptions (zero / partial / complete)', () => {
  it('returns [] when EVERY screenshot lacks a usable caption', () => {
    expect(loadStepCaptions({ screenshots: [{}, { caption: '' }, { caption: '   ' }] })).toEqual([]);
  });
  it('throws on PARTIAL captions', () => {
    expect(() =>
      loadStepCaptions({ screenshots: [{ caption: 'A' }, {}, { caption: 'C' }] }),
    ).toThrow(/partial captions/);
  });
  it('returns the N trimmed captions when all present', () => {
    expect(
      loadStepCaptions({ screenshots: [{ caption: ' A ' }, { caption: 'B' }] }),
    ).toEqual(['A', 'B']);
  });
});

describe('writeCaptionsVtt', () => {
  it('rejects an unsafe slug', () => {
    expect(() => writeCaptionsVtt([{ startMs: 0, caption: 'x' }], '../evil', freshRoot())).toThrow(
      /unsafe slug/,
    );
  });

  it('writes a valid vtt to <root>/<slug>/captions.vtt', () => {
    const root = freshRoot();
    const timings: StepTiming[] = [
      { startMs: 0, caption: 'A' },
      { startMs: 1500, caption: 'B' },
    ];
    writeCaptionsVtt(timings, '02_review_a_proposal', root);
    const out = join(root, '02_review_a_proposal', 'captions.vtt');
    const text = readFileSync(out, 'utf-8');
    expect(text.startsWith('WEBVTT')).toBe(true);
    expect(text).toContain('00:00:00.000 --> 00:00:01.500');
  });

  it('deletes a pre-existing vtt when timings are empty (zero-captions cleanup)', () => {
    const root = freshRoot();
    const dir = join(root, '08_chat_shell');
    mkdirSync(dir, { recursive: true });
    const out = join(dir, 'captions.vtt');
    writeFileSync(out, 'WEBVTT\n\nstale', 'utf-8');
    expect(existsSync(out)).toBe(true);
    writeCaptionsVtt([], '08_chat_shell', root);
    expect(existsSync(out)).toBe(false);
  });

  it('no-ops (no throw) when timings empty and no vtt exists', () => {
    expect(() => writeCaptionsVtt([], '09_generate_judgments_llm', freshRoot())).not.toThrow();
  });
});
