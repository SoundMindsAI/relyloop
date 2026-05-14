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
  {
    id: '03_create_query_template',
    title: 'Create a query template',
    description:
      "Define the Jinja2 query template — the 'knobs' Optuna will tune across trials — and learn the fork-to-v2 versioning pattern.",
    estimatedTime: '3 minutes',
  },
  {
    id: '04_create_query_set',
    title: 'Create a query set',
    description:
      'Define the benchmark queries you want to tune for — the stable list every study scores against.',
    estimatedTime: '2 minutes',
  },
  {
    id: '05_import_judgments_and_calibrate',
    title: 'Import judgments + calibrate',
    description:
      'Skip LLM generation by importing pre-curated judgments, then run the kappa calibration to measure agreement against human ground truth.',
    estimatedTime: '3 minutes',
  },
  {
    id: '06_create_and_monitor_study',
    title: 'Create and monitor a study',
    description:
      'Configure a study, watch the trials fill in live, and read the terminal state — the core Karpathy loop.',
    estimatedTime: '5 minutes',
  },
  {
    id: '07_browse_proposals',
    title: 'Browse proposals',
    description:
      'Filter the proposal queue by status, source, and cluster — three-axis URL-backed filtering with 30-second pulse-refetch when PRs are open.',
    estimatedTime: '2 minutes',
  },
  {
    id: '08_chat_shell',
    title: 'Chat shell — conversations + composer',
    description:
      'Navigate the chat conversation list, start a new chat, and understand the secrets-warning banner. Message streaming with the agent is covered in a future guide when LLM mocking lands.',
    estimatedTime: '2 minutes',
  },
];

export const GUIDE_MAP: GuideMapEntry[] = [
  { prefix: '/clusters', guideId: '01_register_first_cluster', label: 'Register a cluster' },
  { prefix: '/proposals', guideId: '07_browse_proposals', label: 'Browse + filter proposals' },
  { prefix: '/proposals', guideId: '02_review_a_proposal', label: 'Review a proposal' },
  { prefix: '/templates', guideId: '03_create_query_template', label: 'Create a query template' },
  { prefix: '/query-sets', guideId: '04_create_query_set', label: 'Create a query set' },
  {
    prefix: '/judgments',
    guideId: '05_import_judgments_and_calibrate',
    label: 'Import + calibrate judgments',
  },
  { prefix: '/studies', guideId: '06_create_and_monitor_study', label: 'Create + monitor a study' },
  { prefix: '/chat', guideId: '08_chat_shell', label: 'Chat conversations' },
];

export function guidesForPath(pathname: string): GuideMapEntry[] {
  return GUIDE_MAP.filter((g) => pathname.startsWith(g.prefix));
}
