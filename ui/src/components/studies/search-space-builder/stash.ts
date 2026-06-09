// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Cross-type stash helpers for `<SearchSpaceBuilder>` (Story 2.1, FR-2).
 *
 * The stash is a `Map<paramName, StashEntry>` held in a `useRef` inside
 * `<SearchSpaceBuilder>` (never persisted to form state, localStorage, or
 * the textarea). When a user switches a row's `ParamSpec.type`, the prior
 * spec is stashed under the prior type so toggling back restores it.
 *
 * Invalidation rules (spec §4):
 *   (a) Textarea-driven `value` change that mutates a row's spec →
 *       `stashClearRow(map, paramName)`.
 *   (b) Template ref change → `stashClearAll(map)`.
 *   (c) Undo (which writes via `form.setValue`) falls under (a).
 *   (d) Modal close = unmount → `useRef` instance destroyed automatically.
 *
 * The builder's `lastBuilderWriteRef` guard ensures builder-originated
 * writes (debounced AND synchronous blur flush) do NOT trigger
 * invalidation; only external textarea/Undo writes do.
 */

import type { ParamSpec } from '@/lib/search-space-defaults';

import type { ParamType, StashEntry, StashMap } from './types';

/** Look up the stashed spec for `(paramName, type)`, or undefined. */
export function stashGet(map: StashMap, paramName: string, type: ParamType): ParamSpec | undefined {
  const entry = map.get(paramName);
  if (entry === undefined) return undefined;
  return entry[type];
}

/** Store a spec under `(paramName, type)`. Idempotent. */
export function stashSet(map: StashMap, paramName: string, type: ParamType, spec: ParamSpec): void {
  const existing: StashEntry = map.get(paramName) ?? {};
  existing[type] = spec;
  map.set(paramName, existing);
}

/** Drop every stashed spec for `paramName`. Used on external row mutation. */
export function stashClearRow(map: StashMap, paramName: string): void {
  map.delete(paramName);
}

/** Empty the entire stash. Used on `templateBody` reference change. */
export function stashClearAll(map: StashMap): void {
  map.clear();
}

/**
 * Target-type-only defaults consumed when no stash entry exists for a
 * `(paramName, nextType)` lookup. Per spec FR-2: ignore `declaredType`
 * (the user has explicitly chosen `nextType` via the selector; the
 * declared-type heuristic would return the wrong discriminator).
 */
export function defaultSpecForType(nextType: ParamType): ParamSpec {
  switch (nextType) {
    case 'float':
      return { type: 'float', low: 0, high: 1 };
    case 'int':
      return { type: 'int', low: 0, high: 5 };
    case 'categorical':
      return { type: 'categorical', choices: ['__placeholder__'] };
    case 'normalizer_pipeline':
      // Intentionally-incomplete starting state (parallels categorical's
      // '__placeholder__' sentinel): the operator fills in ≥1 step. An empty
      // `steps` fails the backend's min_length=1 (INVALID_SEARCH_SPACE), and
      // <RowNormalizerPipeline> flags the row incomplete until filled.
      return { type: 'normalizer_pipeline', steps: [] };
  }
}
