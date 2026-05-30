// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

// SSR-safe + throw-resistant localStorage wrapper.
//
// Generalizes the bare `typeof window !== 'undefined'` guard found at
// ui/src/components/common/data-table.tsx into a properly throw-resistant
// utility. Safari private mode and disabled-storage browsers can throw on
// either getItem or setItem; this wrapper swallows those errors so callers
// don't have to scatter try/catch.
//
// Consumers MUST treat a null read as "not set" and a false write return
// as "best-effort failed" — never depend on persistence for UI state
// (use component state for visibility, this for durability).

export function safeLocalStorageGet(key: string): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function safeLocalStorageSet(key: string, value: string): boolean {
  if (typeof window === 'undefined') return false;
  try {
    window.localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}
