import { describe, expect, it } from 'vitest';

import { DEMO_CLUSTER_SLUGS, isDemoClusterName } from '@/lib/demo-data';

describe('DEMO_CLUSTER_SLUGS', () => {
  it('contains exactly the 4 expected slugs in the documented order', () => {
    expect(DEMO_CLUSTER_SLUGS).toEqual([
      'acme-products-prod',
      'corp-docs-search',
      'news-search-staging',
      'jobs-marketplace-prod',
    ]);
  });

  it('has length 4', () => {
    expect(DEMO_CLUSTER_SLUGS).toHaveLength(4);
  });
});

describe('isDemoClusterName', () => {
  it.each(DEMO_CLUSTER_SLUGS)('returns true for the demo slug %s', (slug) => {
    expect(isDemoClusterName(slug)).toBe(true);
  });

  it('returns false for plausible non-demo names', () => {
    expect(isDemoClusterName('acme-products-staging')).toBe(false);
    expect(isDemoClusterName('ACME-PRODUCTS-PROD')).toBe(false);
    expect(isDemoClusterName('local-es')).toBe(false);
    expect(isDemoClusterName('my-cluster')).toBe(false);
  });

  it('returns false for the empty string', () => {
    expect(isDemoClusterName('')).toBe(false);
  });
});
