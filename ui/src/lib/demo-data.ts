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
