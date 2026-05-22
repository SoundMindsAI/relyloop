import { describe, expect, it } from 'vitest';

import { formatDemoClusterPrefix } from '@/lib/format-demo-cluster-prefix';

describe('formatDemoClusterPrefix', () => {
  it('K=1 uses singular prefix + verb', () => {
    const result = formatDemoClusterPrefix(['acme-products-prod']);
    expect(result.prefix).toBe('One sample cluster — ');
    expect(result.slugs).toEqual(['acme-products-prod']);
    expect(result.suffix).toContain('is pre-loaded');
    expect(result.suffix).toContain('Run your own optimization against any of them.');
  });

  it('K=2 uses numeric prefix + plural verb', () => {
    const result = formatDemoClusterPrefix(['acme-products-prod', 'corp-docs-search']);
    expect(result.prefix).toBe('2 sample clusters — ');
    expect(result.slugs).toHaveLength(2);
    expect(result.suffix).toContain('are pre-loaded');
    expect(result.suffix).toContain('Run your own optimization against any of them.');
  });

  it('K=3 uses numeric prefix + plural verb', () => {
    const result = formatDemoClusterPrefix([
      'acme-products-prod',
      'corp-docs-search',
      'news-search-staging',
    ]);
    expect(result.prefix).toBe('3 sample clusters — ');
    expect(result.slugs).toHaveLength(3);
    expect(result.suffix).toContain('are pre-loaded');
  });

  it('K=4 uses spelled-out "Four" + plural verb', () => {
    const result = formatDemoClusterPrefix([
      'acme-products-prod',
      'corp-docs-search',
      'news-search-staging',
      'jobs-marketplace-prod',
    ]);
    expect(result.prefix).toBe('Four sample clusters — ');
    expect(result.slugs).toHaveLength(4);
    expect(result.suffix).toContain('are pre-loaded');
    expect(result.suffix).toContain('Run your own optimization against any of them.');
  });

  it('returns the slugs array unchanged so the banner can wrap each in <code>', () => {
    const slugs = ['acme-products-prod', 'corp-docs-search'];
    const result = formatDemoClusterPrefix(slugs);
    expect(result.slugs).toEqual(slugs);
  });
});
