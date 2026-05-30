// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import {
  DEMO_CLUSTER_SLUGS,
  DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS,
  isDemoClusterName,
  isDemoSyntheticUbiClusterName,
} from '@/lib/demo-data';

describe('DEMO_CLUSTER_SLUGS', () => {
  it('contains exactly the 5 expected slugs in the documented order', () => {
    expect(DEMO_CLUSTER_SLUGS).toEqual([
      'acme-products-prod',
      'corp-docs-search',
      'news-search-staging',
      'jobs-marketplace-prod',
      // infra_adapter_solr Story A13 adds the Solr KB scenario.
      'acme-kb-docs-solr',
    ]);
  });

  it('has length 5', () => {
    expect(DEMO_CLUSTER_SLUGS).toHaveLength(5);
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

describe('DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS', () => {
  it('contains exactly the 4 expected slugs in the documented order', () => {
    expect(DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS).toEqual([
      'acme-products-prod',
      'corp-docs-search',
      'jobs-marketplace-prod',
      // infra_adapter_solr Story A13: Solr KB scenario gets UBI rung_2 +
      // hybrid_ubi_llm per spec §19.
      'acme-kb-docs-solr',
    ]);
  });

  it('does NOT contain news-search-staging (rung_0 demo cluster — no synthetic UBI)', () => {
    expect(DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS).not.toContain('news-search-staging');
  });

  it('is a subset of DEMO_CLUSTER_SLUGS (every synthetic-UBI cluster is also a demo cluster)', () => {
    for (const slug of DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS) {
      expect(DEMO_CLUSTER_SLUGS).toContain(slug);
    }
  });
});

describe('isDemoSyntheticUbiClusterName', () => {
  it.each(DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS)(
    'returns true for the synthetic-UBI demo slug %s',
    (slug) => {
      expect(isDemoSyntheticUbiClusterName(slug)).toBe(true);
    },
  );

  it('returns false for news-search-staging (demo cluster, no synthetic UBI)', () => {
    // This is the canonical negative case — the rung_0 on-ramp nudge
    // demo MUST stay demoable without contradiction from a synthetic-
    // data chip.
    expect(isDemoSyntheticUbiClusterName('news-search-staging')).toBe(false);
  });

  it('returns false for plausible non-demo cluster names', () => {
    expect(isDemoSyntheticUbiClusterName('production-real-cluster')).toBe(false);
    expect(isDemoSyntheticUbiClusterName('acme-products-staging')).toBe(false);
    expect(isDemoSyntheticUbiClusterName('ACME-PRODUCTS-PROD')).toBe(false);
    expect(isDemoSyntheticUbiClusterName('')).toBe(false);
  });
});
