// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * `useStudiesVisited` hook tests
 * (feat_overnight_studies_summary_card Story 2.1, ACs 8 + 9).
 *
 * Verifies the visited-state contract:
 *   - AC-9: first visit (no value in localStorage) returns `since`
 *     approximately equal to `now − 7d`.
 *   - AC-8: `dismiss(maxTailCompletedAt)` stores `maxTailCompletedAt
 *     + 1ms` and surfaces it on next read (and on re-render).
 *   - Persistence: a freshly-mounted hook (after dismissal) reads the
 *     written value from localStorage, not the 7-days-ago default.
 *   - Defensive: a malformed `dismiss(...)` argument doesn't throw a
 *     render — the `since` value stays where it was.
 */

import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useStudiesVisited } from '@/hooks/use-studies-visited';

const STORAGE_KEY = 'relyloop.last_visited_studies_at';
const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;

describe('useStudiesVisited', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  afterEach(() => {
    window.localStorage.clear();
  });

  it('AC-9: first visit defaults `since` to ~now − 7 days', () => {
    const beforeMount = Date.now();
    const { result } = renderHook(() => useStudiesVisited());
    const afterMount = Date.now();

    const since = Date.parse(result.current.since);
    expect(Number.isFinite(since)).toBe(true);
    // Allow a 100ms render window on each side.
    expect(since).toBeGreaterThanOrEqual(beforeMount - SEVEN_DAYS_MS - 100);
    expect(since).toBeLessThanOrEqual(afterMount - SEVEN_DAYS_MS + 100);
    // First visit must NOT write anything to localStorage — we only
    // write on explicit dismiss.
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('AC-8: dismiss(T) stores T+1ms and updates `since`', () => {
    const { result } = renderHook(() => useStudiesVisited());
    const tailIso = '2026-06-04T12:00:00.000Z';

    act(() => {
      result.current.dismiss(tailIso);
    });

    // `since` now reflects T + 1ms, exclusively past the tail's completion.
    const expected = new Date(Date.parse(tailIso) + 1).toISOString();
    expect(result.current.since).toBe(expected);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe(expected);
  });

  it('subsequent mounts read the stored value (not the 7-day default)', () => {
    const tailIso = '2026-06-04T12:00:00.000Z';
    const { result: first } = renderHook(() => useStudiesVisited());
    act(() => {
      first.current.dismiss(tailIso);
    });

    // Fresh mount — emulates a page reload after dismissal.
    const { result: second } = renderHook(() => useStudiesVisited());
    const expected = new Date(Date.parse(tailIso) + 1).toISOString();
    expect(second.current.since).toBe(expected);
  });

  it('malformed dismiss(...) input is ignored without throwing', () => {
    const { result } = renderHook(() => useStudiesVisited());
    const sinceBefore = result.current.since;

    act(() => {
      result.current.dismiss('not-a-date');
    });

    expect(result.current.since).toBe(sinceBefore);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});
