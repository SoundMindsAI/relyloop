// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Test helper for `next/navigation` + `useDataTableUrlState` page tests.
 *
 * Factors the ~25-line `searchParamsSubscribers` + `applyUrl` boilerplate
 * that was duplicated across (currently) three test files —
 *   - `ui/src/__tests__/app/proposals/page.test.tsx`
 *   - `ui/src/__tests__/app/judgments/[id]/page.test.tsx`
 *   - `ui/src/__tests__/components/query-sets/queries-table.test.tsx`
 *
 * Origin: `chore_data_table_columnvisibility_tanstack` item 1.
 *
 * ## Usage
 *
 * ```ts
 * import {
 *   makeNextNavigationMock,
 *   resetDataTableUrlMock,
 *   getDataTableUrlMockState,
 *   setMockedSearch,
 * } from '@/__tests__/helpers/data-table-url-mock';
 *
 * vi.mock('next/navigation', () => makeNextNavigationMock({ pathname: '/test' }));
 *
 * beforeEach(() => {
 *   resetDataTableUrlMock();
 * });
 *
 * // After firing an interaction that triggers router.replace(...):
 * expect(getDataTableUrlMockState().lastReplace).toContain('status=completed');
 * ```
 *
 * ## Why a factory function + module state
 *
 * `vi.mock` is hoisted by Vitest's transformer to the top of every test file
 * BEFORE `let`/`const` declarations in the same file. The hoisted factory
 * runs lazily when `next/navigation` is imported by the SUT — so by the time
 * the factory runs, this helper module is already loaded and its exports
 * are callable. Mutable state lives in this module (not in the test file)
 * so the factory can close over it without tripping the hoist trap.
 *
 * The factory ALWAYS returns the same closure shape; the per-test variation
 * is the optional `pathname` override (most tests use `/test` — a few want
 * `/proposals` or `/judgments/<id>` to match the real route).
 */

import { useEffect, useReducer } from 'react';

interface MockState {
  mockedSearch: string;
  lastReplace: string;
  lastPush: string;
  subscribers: Set<() => void>;
}

const state: MockState = {
  mockedSearch: '',
  lastReplace: '',
  lastPush: '',
  subscribers: new Set<() => void>(),
};

function applyUrl(url: string): void {
  // Extract the query string from a path-or-query URL emitted by
  // `useDataTableUrlState`. The hook calls `router.replace('?qs')` for
  // non-empty queries and `router.replace(pathname)` (no `?`) when the
  // URL state is empty.
  if (url.startsWith('?')) state.mockedSearch = url.slice(1);
  else if (url.includes('?')) state.mockedSearch = url.split('?')[1] ?? '';
  else state.mockedSearch = '';
  state.subscribers.forEach((fn) => fn());
}

export interface MakeNextNavigationMockOptions {
  /** Defaults to `'/test'`. Override per test file when the route matters. */
  pathname?: string;
}

/**
 * Factory used by `vi.mock('next/navigation', () => makeNextNavigationMock(...))`.
 *
 * Returns the three hooks the SUT consumes. `usePathname` is a constant;
 * `useRouter` records the last call; `useSearchParams` subscribes to the
 * module-level subscriber set so React re-renders fire when the URL changes.
 */
export function makeNextNavigationMock(options: MakeNextNavigationMockOptions = {}) {
  const pathname = options.pathname ?? '/test';
  return {
    usePathname: () => pathname,
    useRouter: () => ({
      replace: (url: string) => {
        state.lastReplace = url;
        applyUrl(url);
      },
      push: (url: string) => {
        state.lastPush = url;
        applyUrl(url);
      },
    }),
    useSearchParams: () => {
      // `useReducer` here is intentional — it gives us a `force()` function
      // we can register as a subscriber and call to trigger a re-render
      // without owning a piece of state we don't actually use.
      const [, force] = useReducer((x: number) => x + 1, 0);
      useEffect(() => {
        state.subscribers.add(force);
        return () => {
          state.subscribers.delete(force);
        };
      }, []);
      return new URLSearchParams(state.mockedSearch);
    },
  };
}

/** Reset all mock state between tests. Call in `beforeEach`. */
export function resetDataTableUrlMock(): void {
  state.mockedSearch = '';
  state.lastReplace = '';
  state.lastPush = '';
  state.subscribers.clear();
}

/** Read the last `replace()` / `push()` URL + the current mocked search string. */
export function getDataTableUrlMockState(): {
  lastReplace: string;
  lastPush: string;
  mockedSearch: string;
} {
  return {
    lastReplace: state.lastReplace,
    lastPush: state.lastPush,
    mockedSearch: state.mockedSearch,
  };
}

/**
 * Seed the mock's initial URL search string before render. Use this when a
 * test wants the SUT to hydrate from a specific `?status=...` URL on mount.
 * Notifies any subscribers so `useSearchParams` consumers re-read.
 */
export function setMockedSearch(value: string): void {
  state.mockedSearch = value;
  state.subscribers.forEach((fn) => fn());
}
