// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Pure partition helper for the proposal full-parameter-space panel
 * (``feat_proposal_full_param_space_view`` Story 1.2 / FR-1).
 *
 * Given a proposal's ``config_diff``, the source study's
 * ``search_space.params``, and the template's ``declared_params``, this
 * module partitions every declared parameter into three disjoint groups:
 *
 *   - ``tunedChanged``   — the param appears in ``config_diff`` (the study
 *                          tuned it and the digest recorded a value).
 *   - ``tunedUnchanged`` — the param was in the study's search space but
 *                          NOT in ``config_diff`` (considered, not moved).
 *   - ``untuned``        — declared on the template but absent from this
 *                          study's tuning surface entirely.
 *
 * Partition universe is ``declaredParams ∪ configDiff`` (spec D-9): keys
 * present only in ``searchSpaceParams`` (template-evolution drift) are
 * silently dropped because they have no type-tag to display.
 *
 * The module is pure — no I/O, no globals, no Date.now() — so it is the
 * natural unit-test target for the spec's headline domain rule.
 */

import { extractFromTo } from './config-diff';

export type ParamSpaceGroup = 'tuned_changed' | 'tuned_unchanged' | 'untuned';

export interface TunedChangedRow {
  name: string;
  /** Type-tag from declared_params, or '(unknown)' for a config_diff drift key. */
  type: string;
  from: unknown;
  to: unknown;
}

export interface DeclaredRow {
  name: string;
  type: string;
}

export interface PartitionResult {
  tunedChanged: TunedChangedRow[];
  tunedUnchanged: DeclaredRow[];
  untuned: DeclaredRow[];
}

export interface PartitionInput {
  declaredParams: Record<string, string>;
  configDiff: Record<string, unknown>;
  // `null` is reachable at runtime: JSONB `study.search_space.params` may be
  // explicitly null, and the page's `(search_space as {params?})?.params` cast
  // yields null in that case. Widen the type to be honest about it.
  searchSpaceParams?: Record<string, unknown> | null | undefined;
}

const byName = (a: { name: string }, b: { name: string }): number => a.name.localeCompare(b.name);

export function partitionTemplateParams({
  declaredParams,
  configDiff,
  searchSpaceParams,
}: PartitionInput): PartitionResult {
  const tunedChanged: TunedChangedRow[] = [];
  const tunedUnchanged: DeclaredRow[] = [];
  const untuned: DeclaredRow[] = [];

  // Pass 1 — every config_diff key is "tuned by this proposal" (D-10:
  // membership-based, not value-comparison-based; a from===to anomaly still
  // classifies here). Iterate Object.entries to avoid noUncheckedIndexedAccess
  // narrowing issues on `configDiff[key]` (cycle-3 F1).
  for (const [key, raw] of Object.entries(configDiff)) {
    const type = declaredParams[key] ?? '(unknown)'; // drift key → '(unknown)' (AC-6)
    const { from, to } = extractFromTo(raw);
    tunedChanged.push({ name: key, type, from, to });
  }

  // Pass 2 — partition the declared params not already in config_diff.
  // Object.entries yields type-narrowed [string, string] tuples, so `type`
  // is a non-optional string without an index-access narrowing issue.
  const seen = new Set(Object.keys(configDiff));
  for (const [key, type] of Object.entries(declaredParams)) {
    if (seen.has(key)) continue; // already in tunedChanged
    // Truthiness guard (NOT `!== undefined`): `searchSpaceParams` can be null
    // at runtime, and `key in null` throws a TypeError (Gemini G1).
    if (searchSpaceParams && key in searchSpaceParams) {
      tunedUnchanged.push({ name: key, type });
    } else {
      untuned.push({ name: key, type });
    }
  }

  // NOTE: searchSpaceParams is intentionally NOT iterated — keys present only
  // there (template-evolution drift) are silently dropped per D-9.

  tunedChanged.sort(byName);
  tunedUnchanged.sort(byName);
  untuned.sort(byName);

  return { tunedChanged, tunedUnchanged, untuned };
}
