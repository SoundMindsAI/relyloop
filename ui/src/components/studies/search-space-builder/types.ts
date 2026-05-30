// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Type re-exports + local types for `<SearchSpaceBuilder>` (Story 1.1).
 *
 * Stash types arrive in Story 2.1; declared here so siblings can import
 * `StashEntry` / `StashMap` without re-exporting through `stash.ts` later.
 */

import type { ParamSpec, SearchSpaceJson } from '@/lib/search-space-defaults';

export type { ParamSpec, SearchSpaceJson };

/** `ParamSpec` discriminator wire values (the only three). */
export type ParamType = ParamSpec['type'];

/**
 * Per-row stash of prior specs across type switches (Story 2.1).
 *
 * Map keyed by `paramName` → Partial record of prior specs keyed by their
 * `ParamSpec.type` discriminator. Held in a `useRef` inside
 * `<SearchSpaceBuilder>`; never persisted to form state, localStorage, or
 * the textarea.
 */
export type StashEntry = Partial<Record<ParamType, ParamSpec>>;
export type StashMap = Map<string, StashEntry>;
