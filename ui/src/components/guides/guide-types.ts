/**
 * Shared types + canonical guide registry for RelyLoop walkthroughs.
 *
 * The registry intentionally lives in code (not just metadata.json) so:
 *  - Route → guide mapping (GUIDE_MAP) compiles against the type system
 *  - The /guide catalog page renders without per-mount JSON fetches
 *  - Vitest tests can assert on the registry without filesystem access
 *
 * Per-guide caption text and screenshot ordering still live in each guide's
 * `metadata.json` under `ui/public/guides/<id>/` — this file declares only
 * the title/description/route binding the in-app surface needs.
 */

export interface GuideScreenshot {
  file: string;
  caption: string;
}

export interface GuideMetadata {
  title: string;
  description: string;
  order: number;
  tags: string[];
  estimated_time: string;
  screenshots: GuideScreenshot[];
}

/**
 * Registry entry for in-app guide surfaces (GuideTrigger button + /guide
 * catalog page). Mirrors the `id`, `title`, and `description` keys in each
 * guide's `metadata.json` — kept in sync by convention; vitest test
 * `guide-registry.test.ts` enforces parity by reading both sources.
 */
export interface GuideRegistryEntry {
  id: string;
  title: string;
  description: string;
  estimatedTime: string;
}

/**
 * Map of route prefixes → guide ids. Multiple guides can share a prefix; the
 * GuideTrigger button renders a picker when several match.
 */
export interface GuideMapEntry {
  prefix: string;
  guideId: string;
  label: string;
}

export const GUIDE_REGISTRY: GuideRegistryEntry[] = [
  {
    id: '01_register_first_cluster',
    title: 'Register your first cluster',
    description:
      'Add an Elasticsearch or OpenSearch cluster to RelyLoop and verify the connection probe succeeds.',
    estimatedTime: '2 minutes',
  },
  {
    id: '02_review_a_proposal',
    title: 'Review a proposal',
    description:
      'Open a pending proposal, read the config diff and metric delta, then decide whether to open a PR or reject.',
    estimatedTime: '2 minutes',
  },
];

export const GUIDE_MAP: GuideMapEntry[] = [
  { prefix: '/clusters', guideId: '01_register_first_cluster', label: 'Register a cluster' },
  { prefix: '/proposals', guideId: '02_review_a_proposal', label: 'Review a proposal' },
];

export function guidesForPath(pathname: string): GuideMapEntry[] {
  return GUIDE_MAP.filter((g) => pathname.startsWith(g.prefix));
}
