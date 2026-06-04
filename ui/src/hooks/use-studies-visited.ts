// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * `useStudiesVisited` — feat_overnight_studies_summary_card Story 2.1.
 *
 * Tracks "when did the operator last visit `/studies`" in localStorage so
 * the "Ran while you were away" card can scope its discovery query to
 * chains whose tails completed AFTER that cutoff (FR-5).
 *
 * ## Return shape
 *
 * - `since: string` — ISO-8601 timestamp. On the first visit (no value
 *   in localStorage yet), defaults to `now − 7 days` so the card shows
 *   a sensible week's worth of history rather than every chain ever.
 * - `dismiss(maxTailCompletedAt: string): void` — stores
 *   `maxTailCompletedAt + 1ms` as the new cutoff so the card unmounts
 *   on next refetch. The +1ms exclusive nudge prevents the same chain
 *   from re-appearing if the operator dismisses then reloads (the
 *   endpoint's `since` filter is inclusive — `completed_at >= since`).
 *
 * ## SSR safety
 *
 * The hook reads localStorage in a `useState` lazy initializer guarded
 * by `typeof window`; the first server render emits the default
 * 7-day-ago timestamp, and the first client effect re-syncs from
 * localStorage. Matches the pattern in `useLocalStorageSet`
 * (`ui/src/hooks/use-local-storage-set.ts`).
 */

import { useCallback, useState } from 'react';

const STORAGE_KEY = 'relyloop.last_visited_studies_at';
const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;

function defaultSince(): string {
  return new Date(Date.now() - SEVEN_DAYS_MS).toISOString();
}

function readVisitedAt(): string {
  if (typeof window === 'undefined') return defaultSince();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    // Guard against a corrupt localStorage value (operator manual edit,
    // partial write, stored value from an older release with a different
    // shape). An invalid date would otherwise propagate to
    // GET /api/v1/studies/chains/recent?since=<garbage> → 422 cascade.
    // Per Gemini Code Assist PR-444 finding #4.
    if (raw && !Number.isNaN(Date.parse(raw))) return raw;
  } catch {
    // Private browsing / quota / corrupt — fall back to default.
  }
  return defaultSince();
}

function writeVisitedAt(value: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Quota / private browsing — silently drop the write.
  }
}

export interface UseStudiesVisitedResult {
  since: string;
  dismiss: (maxTailCompletedAt: string) => void;
}

export function useStudiesVisited(): UseStudiesVisitedResult {
  // Hydrate synchronously via the useState initializer — matches the
  // pattern in useLocalStorageSet (no extra render cycle, safe under
  // SSR because readVisitedAt() guards on `typeof window`).
  const [since, setSince] = useState<string>(() => readVisitedAt());

  const dismiss = useCallback((maxTailCompletedAt: string): void => {
    const parsed = Date.parse(maxTailCompletedAt);
    if (Number.isNaN(parsed)) {
      // Defensive: a malformed input MUST NOT throw a render. Skip the
      // dismissal entirely — the card stays visible. Operator can dismiss
      // again on the next refetch.
      return;
    }
    // +1ms exclusive nudge so the inclusive `since` filter doesn't
    // re-show the just-dismissed chain (FR-5).
    const next = new Date(parsed + 1).toISOString();
    writeVisitedAt(next);
    setSince(next);
  }, []);

  return { since, dismiss };
}
