// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { safeLocalStorageGet, safeLocalStorageSet } from '@/lib/safe-local-storage';

const KEY = 'relyloop.test.safe-local-storage';

describe('safeLocalStorageGet', () => {
  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('returns the stored value on the happy path', () => {
    window.localStorage.setItem(KEY, 'hello');
    expect(safeLocalStorageGet(KEY)).toBe('hello');
  });

  it('returns null when the key is absent', () => {
    expect(safeLocalStorageGet('relyloop.test.absent-key')).toBeNull();
  });

  it('returns null when getItem throws', () => {
    // Spy on Storage.prototype rather than window.localStorage directly —
    // jsdom's localStorage is a Storage-instance proxy and spying on the
    // instance method doesn't always intercept reliably (worked for getItem
    // in some setups, not for setItem). Storage.prototype is the canonical
    // mock target for jsdom-backed vitest.
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError: storage disabled');
    });
    expect(safeLocalStorageGet(KEY)).toBeNull();
  });
});

describe('safeLocalStorageSet', () => {
  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('returns true and persists the value on the happy path', () => {
    expect(safeLocalStorageSet(KEY, '1')).toBe(true);
    expect(window.localStorage.getItem(KEY)).toBe('1');
  });

  it('returns false when setItem throws (e.g., QuotaExceededError)', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError', 'QuotaExceededError');
    });
    expect(safeLocalStorageSet(KEY, '1')).toBe(false);
  });
});

describe('SSR safety', () => {
  let originalWindow: typeof globalThis.window | undefined;

  beforeEach(() => {
    originalWindow = globalThis.window;
    // Simulate SSR — delete the window symbol so `typeof window === 'undefined'`.
    // @ts-expect-error: deliberately removing window for the SSR test
    delete globalThis.window;
  });

  afterEach(() => {
    if (originalWindow !== undefined) {
      globalThis.window = originalWindow;
    }
  });

  it('safeLocalStorageGet returns null on SSR', () => {
    expect(safeLocalStorageGet(KEY)).toBeNull();
  });

  it('safeLocalStorageSet returns false on SSR', () => {
    expect(safeLocalStorageSet(KEY, '1')).toBe(false);
  });
});
