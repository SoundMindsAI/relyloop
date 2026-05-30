// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

/**
 * `useLocalStorageSet` — Set-shaped localStorage hook for
 * feat_data_table_primitive Story 2.10 (column visibility).
 *
 * Stores a string array under the given key. Safe under SSR (no-op on
 * server), Safari Private Browsing (try/catch on write quota), and tabs
 * without localStorage support.
 *
 * ## Return shape (canonical)
 *
 * Returns `{ value: Set<string>, add, remove, toggle, clear, has }`. The
 * shipped shape uses `Set<string>` for O(1) membership checks via `.has()`
 * + ergonomic `.toggle()`, which is what `<DataTable>`'s sole consumer
 * actually uses (`hiddenColumns.has(c.id)` / `hiddenColumns.toggle(id)`).
 *
 * `feat_data_table_primitive/implementation_plan.md` Story 2.10's key-
 * interface block proposed `{ value: string[], add, remove, toggle }` as
 * an early sketch — the consumer pattern that emerged during build-out
 * was Set-shaped. The shipped impl is the canonical contract; the plan
 * proposal is closed via `chore_data_table_columnvisibility_tanstack` item 2.
 */

import { useCallback, useEffect, useState } from 'react';

function readLocalStorageSet(key: string, defaultValue: readonly string[]): Set<string> {
  try {
    const raw = typeof window !== 'undefined' ? window.localStorage.getItem(key) : null;
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return new Set(parsed.map(String));
    }
  } catch {
    // Private browsing / quota / corrupt JSON → fall back to default.
  }
  return new Set(defaultValue);
}

export function useLocalStorageSet(key: string, defaultValue: readonly string[] = []) {
  // Hydrate synchronously via the useState initializer — avoids the
  // react-hooks/set-state-in-effect rule and an extra render cycle.
  // Safe under SSR because the read function checks `typeof window`.
  const [value, setValue] = useState<Set<string>>(() => readLocalStorageSet(key, defaultValue));

  // Persist on every change.
  useEffect(() => {
    try {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(key, JSON.stringify(Array.from(value)));
      }
    } catch {
      // Quota exceeded / private browsing — drop the write silently.
    }
  }, [key, value]);

  const add = useCallback((id: string) => {
    setValue((prev) => {
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  }, []);
  const remove = useCallback((id: string) => {
    setValue((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, []);
  const toggle = useCallback((id: string) => {
    setValue((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);
  const clear = useCallback(() => setValue(new Set()), []);

  return { value, add, remove, toggle, clear, has: (id: string) => value.has(id) };
}
