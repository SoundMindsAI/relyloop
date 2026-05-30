// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

// Source: scripts/seed_meaningful_demos.py SCENARIOS slugs (lines 129/245/343/456).
// CI guard at scripts/ci/verify_demo_slug_parity.sh enforces parity between this
// file and the seed-script SCENARIOS list. Do NOT add demo slugs to enums.ts —
// these are frontend-only UX hints, not backend wire values.

export const DEMO_CLUSTER_SLUGS = [
  'acme-products-prod',
  'corp-docs-search',
  'news-search-staging',
  'jobs-marketplace-prod',
] as const;

export type DemoClusterSlug = (typeof DEMO_CLUSTER_SLUGS)[number];

// Set built once at module load for O(1) lookup AND for `string` widening —
// the `as const` tuple's `.includes()` method narrows its parameter to the
// literal-union type, which would reject any arbitrary `string` at call sites.
const _DEMO_SET: ReadonlySet<string> = new Set(DEMO_CLUSTER_SLUGS);

export function isDemoClusterName(name: string): boolean {
  return _DEMO_SET.has(name);
}

// Story 3.1 / FR-7: the three demo clusters that receive synthetic UBI
// clickstream from the reseed orchestrator (Stories 2.2 + 2.5).
//
// Values must match backend/app/services/demo_ubi_seed.py
// DEMO_UBI_SCENARIO_ALLOWLIST (first element of each pair). The CI guard
// at scripts/ci/verify_demo_slug_parity.sh pins this tuple against the
// Python frozenset so they cannot drift silently.
//
// news-search-staging is intentionally absent — it is the negative
// case (rung_0 demo cluster) used to keep the on-ramp nudge demoable
// without contradicting it with a synthetic-data chip.
export const DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS = [
  'acme-products-prod',
  'corp-docs-search',
  'jobs-marketplace-prod',
] as const;

export type DemoSyntheticUbiClusterSlug = (typeof DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS)[number];

const _SYNTHETIC_UBI_SET: ReadonlySet<string> = new Set(DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS);

export function isDemoSyntheticUbiClusterName(name: string): boolean {
  return _SYNTHETIC_UBI_SET.has(name);
}
