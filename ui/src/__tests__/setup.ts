// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { setupServer } from 'msw/node';

// jsdom doesn't ship matchMedia. next-themes (used by ThemeProvider/Toaster)
// reads it to detect the OS color scheme; without this stub, ThemeProvider
// crashes in jsdom-based tests with "window.matchMedia is not a function".
if (typeof window !== 'undefined' && !window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

// jsdom 29.1.1 + vitest 4.1.6 + Node 22 have an intermittent race where
// `window.localStorage` becomes undefined during certain test orderings —
// specifically when a `beforeEach`/`afterEach` hook in one file runs after
// the jsdom container of a prior file was partially torn down. Symptom:
//   TypeError: Cannot read properties of undefined (reading 'setItem')
// captured in (now-obsolete) bug ideas
// bug_datatable_col_vis_density_localstorage_undefined_jsdom,
// bug_markdown_doc_localstorage_undefined_jsdom, and
// bug_vitest_jsdom_localstorage_failures (31 failures across 4 files).
//
// The failures stopped reproducing on main between 2026-05-24 (when the
// ideas were captured) and 2026-05-26 (when this shim landed) — likely
// a transitive-dep change in PR #259's lockfile regen healed it. This
// shim is defense-in-depth: if the race returns, the shim catches it
// instead of letting tests fail intermittently.
//
// In-memory backing store; per-spec isolation is the caller's job (the
// same way browser localStorage works — there's no automatic clear between
// page loads either). Tests that need clean state should call
// `window.localStorage.clear()` in beforeEach as they already do.
if (typeof window !== 'undefined' && !window.localStorage) {
  const store: Record<string, string> = {};
  Object.defineProperty(window, 'localStorage', {
    writable: true,
    configurable: true,
    value: {
      getItem(key: string): string | null {
        return Object.prototype.hasOwnProperty.call(store, key) ? store[key]! : null;
      },
      setItem(key: string, value: string): void {
        store[key] = String(value);
      },
      removeItem(key: string): void {
        delete store[key];
      },
      clear(): void {
        for (const k of Object.keys(store)) delete store[k];
      },
      key(index: number): string | null {
        const keys = Object.keys(store);
        return index >= 0 && index < keys.length ? keys[index]! : null;
      },
      get length(): number {
        return Object.keys(store).length;
      },
    } as Storage,
  });
}

// jsdom doesn't ship Element.scrollIntoView / PointerEvent / hasPointerCapture.
// Radix-UI primitives (Select, Popover) call these on focus/keydown when
// scrolling items into view; without the stubs they throw inside an effect
// that React 19 surfaces as an unhandled error in vitest.
if (typeof Element !== 'undefined') {
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => {};
  }
  if (!(Element.prototype as unknown as { hasPointerCapture?: unknown }).hasPointerCapture) {
    (Element.prototype as unknown as { hasPointerCapture: () => boolean }).hasPointerCapture = () =>
      false;
  }
  if (
    !(Element.prototype as unknown as { releasePointerCapture?: unknown }).releasePointerCapture
  ) {
    (Element.prototype as unknown as { releasePointerCapture: () => void }).releasePointerCapture =
      () => {};
  }
}

/**
 * msw server shared across the test suite. Individual tests register
 * handlers via `server.use(http.get(...))` and the global `afterEach`
 * resets the handler list to empty so tests are independent.
 *
 * Tests that need to assert on request headers (e.g., `X-Request-ID`
 * injection) inspect `request.headers` inside their msw handlers.
 */
export const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
