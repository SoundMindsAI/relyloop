/**
 * E2E seed helpers — register clusters, query-sets, queries, templates,
 * judgment-lists, studies, proposals, and conversations against the real
 * backend at PLAYWRIGHT_API_BASE_URL.
 *
 * Used by `tests/e2e/*.spec.ts` to set up deterministic state before each
 * test. NOT a Page Object — these are pure HTTP helpers backed by the
 * actual API contract, so the same seed data the UI consumes is what the
 * tests inspect.
 *
 * The local-es credentials_ref maps to `./secrets/cluster_credentials.yaml`
 * under the `local-es:` key (operator-provided).
 */
import { randomUUID } from 'node:crypto';

const API_BASE = process.env.PLAYWRIGHT_API_BASE_URL ?? 'http://127.0.0.1:8000';

async function post<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`POST ${path} failed: ${resp.status} ${text}`);
  }
  return (await resp.json()) as T;
}

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) {
    throw new Error(`GET ${path} failed: ${resp.status}`);
  }
  return (await resp.json()) as T;
}

interface SeedOptions {
  withJudgmentList?: boolean;
}

interface SeedResult {
  clusterId: string;
  querySetId: string;
  queryIds: string[];
  judgmentListId: string | null;
}

interface ClusterSeed {
  id: string;
  name: string;
}

interface TemplateSeed {
  id: string;
  name: string;
  version: number;
}

interface JudgmentListSeed {
  id: string;
  judgmentCount: number;
}

interface StudySeed {
  id: string;
  name: string;
}

interface ProposalSeed {
  id: string;
}

interface ConversationSeed {
  id: string;
  title: string | null;
}

interface CompletedStudySeed {
  studyId: string;
  digestId: string;
  proposalId: string | null;
}

interface FullChainSeed {
  clusterId: string;
  clusterName: string;
  querySetId: string;
  queryIds: string[];
  templateId: string;
  templateName: string;
  judgmentListId: string;
}

/**
 * Seed a single cluster (no query-set, no judgments). Useful for tests that
 * only need a cluster to exist — e.g., the /clusters/[id] delete flow.
 */
export async function seedCluster(): Promise<ClusterSeed> {
  const suffix = randomUUID().slice(0, 8);
  const name = `e2e-c-${suffix}`;
  const cluster = await post<{ id: string }>('/api/v1/clusters', {
    name,
    engine_type: 'elasticsearch',
    environment: 'dev',
    base_url: 'http://elasticsearch:9200',
    auth_kind: 'es_basic',
    credentials_ref: 'local-es',
  });
  return { id: cluster.id, name };
}

/**
 * Seed a cluster + query-set + N queries.
 *
 * Each query gets a deterministic `query_text` ("e2e query 0", "e2e query 1", …).
 * The first query (index 0) gets `query_metadata={"intent":"test"}`; the rest
 * get null metadata. If `withJudgmentList: true`, also import a judgment list
 * with a single judgment referencing query #0 — used by the 409 path test.
 */
export async function seedQuerySet(
  numQueries: number,
  opts: SeedOptions = {},
): Promise<SeedResult> {
  const suffix = randomUUID().slice(0, 8);

  const cluster = await post<{ id: string }>('/api/v1/clusters', {
    name: `e2e-c-${suffix}`,
    engine_type: 'elasticsearch',
    environment: 'dev',
    base_url: 'http://elasticsearch:9200',
    auth_kind: 'es_basic',
    credentials_ref: 'local-es',
  });

  const qs = await post<{ id: string }>('/api/v1/query-sets', {
    name: `e2e-qs-${suffix}`,
    cluster_id: cluster.id,
  });

  const bulk = await post<{ added: number }>(`/api/v1/query-sets/${qs.id}/queries`, {
    queries: Array.from({ length: numQueries }, (_, i) => ({
      query_text: `e2e query ${i}`,
      reference_answer: null,
      query_metadata: i === 0 ? { intent: 'test' } : null,
    })),
  });
  if (bulk.added !== numQueries) {
    throw new Error(`Expected ${numQueries} queries, got ${bulk.added}`);
  }

  // Re-fetch the queries to learn their ids — backend assigns UUIDv7s.
  const listBody = await get<{ data: Array<{ id: string }> }>(
    `/api/v1/query-sets/${qs.id}/queries`,
  );
  const queryIds = listBody.data.map((r) => r.id);

  let judgmentListId: string | null = null;
  if (opts.withJudgmentList) {
    const jl = await post<{ id: string }>(`/api/v1/judgment-lists/import`, {
      name: `e2e-jl-${suffix}`,
      query_set_id: qs.id,
      cluster_id: cluster.id,
      // Must match `seedStudy()`'s default `target` ('products') so the
      // FR-1 JUDGMENT_TARGET_MISMATCH guard at POST /studies doesn't
      // reject the chained create. See
      // `feat_study_target_judgment_mismatch_guard`.
      target: 'products',
      rubric: 'e2e-rubric-v1',
      judgments: [
        {
          query_id: queryIds[0],
          doc_id: 'e2e-doc-1',
          rating: 2,
        },
      ],
    });
    judgmentListId = jl.id;
  }

  return {
    clusterId: cluster.id,
    querySetId: qs.id,
    queryIds,
    judgmentListId,
  };
}

/**
 * Seed a single query template. Defaults to a minimal valid multi_match
 * template with a `boost` numeric parameter, sufficient for studies tests.
 */
export async function seedTemplate(
  opts: { engineType?: 'elasticsearch' | 'opensearch' } = {},
): Promise<TemplateSeed> {
  const suffix = randomUUID().slice(0, 8);
  const name = `e2e-tpl-${suffix}`;
  const tpl = await post<{ id: string; name: string; version: number }>(
    '/api/v1/query-templates',
    {
      name,
      engine_type: opts.engineType ?? 'elasticsearch',
      body: '{ "query": { "match": { "title": { "query": "{{ query_text }}", "boost": {{ boost }} } } } }',
      // declared_params describes TUNABLE search-space params only. The
      // template body references `query_text` too, but render() injects it
      // from the query-set at trial time (after the missing-keys check) —
      // it does NOT belong in declared_params, which is the contract
      // between the search space and the template. The Story 1.1
      // create-time validator (chore_create_study_wizard_polish) enforces
      // that the submitted search_space matches declared_params exactly,
      // so including query_text here would force every caller of
      // seedStudy() to add a placeholder param it doesn't actually tune.
      declared_params: { boost: 'float' },
    },
  );
  return { id: tpl.id, name: tpl.name, version: tpl.version };
}

/**
 * Import a judgment list directly (tutorial path; no LLM call). Maps every
 * provided queryId to one or more doc_id/rating pairs. Defaults to one
 * rating-2 judgment per query against a synthetic doc_id.
 */
export async function seedJudgmentList(args: {
  clusterId: string;
  querySetId: string;
  queryIds: string[];
  ratingPerQuery?: 0 | 1 | 2 | 3;
  /**
   * Target index/collection the judgments are authored against. Defaults to
   * `'products'` so chained `seedStudy()` calls (which also default to
   * `'products'`) pass the FR-1 `JUDGMENT_TARGET_MISMATCH` guard at
   * `POST /api/v1/studies`. Override only when a test deliberately wants
   * to exercise the mismatch rejection.
   */
  target?: string;
}): Promise<JudgmentListSeed> {
  const { clusterId, querySetId, queryIds, ratingPerQuery = 2, target = 'products' } = args;
  const suffix = randomUUID().slice(0, 8);
  const judgments = queryIds.map((qid, i) => ({
    query_id: qid,
    doc_id: `e2e-doc-${i}`,
    rating: ratingPerQuery,
    notes: null,
  }));
  const jl = await post<{ id: string; judgment_count: number }>(
    '/api/v1/judgment-lists/import',
    {
      name: `e2e-jl-${suffix}`,
      query_set_id: querySetId,
      cluster_id: clusterId,
      target,
      rubric: 'e2e-rubric-v1 — rate relevance 0-3.',
      judgments,
    },
  );
  return { id: jl.id, judgmentCount: jl.judgment_count };
}

/**
 * Seed cluster + query-set + N queries + template + imported judgment list —
 * the full chain a study needs as FKs. Useful for studies / proposals tests.
 *
 * `opts.judgmentListTarget` overrides the judgment-list's `target` field
 * (default `'products'` — matches `seedStudy()`'s default so the FR-1
 * `JUDGMENT_TARGET_MISMATCH` guard passes when both helpers are chained).
 * Specs that pick a non-`products` target on the study (e.g.,
 * `studies-create-target-dropdown.spec.ts`) MUST pass the same target here
 * so the chained POST /studies isn't rejected.
 */
export async function seedFullChain(
  numQueries = 3,
  opts: { judgmentListTarget?: string } = {},
): Promise<FullChainSeed> {
  const qs = await seedQuerySet(numQueries);
  const tpl = await seedTemplate();
  const jl = await seedJudgmentList({
    clusterId: qs.clusterId,
    querySetId: qs.querySetId,
    queryIds: qs.queryIds,
    ...(opts.judgmentListTarget !== undefined ? { target: opts.judgmentListTarget } : {}),
  });
  // Re-fetch the cluster name (seedQuerySet doesn't return it).
  const cluster = await get<{ name: string }>(`/api/v1/clusters/${qs.clusterId}`);
  return {
    clusterId: qs.clusterId,
    clusterName: cluster.name,
    querySetId: qs.querySetId,
    queryIds: qs.queryIds,
    templateId: tpl.id,
    templateName: tpl.name,
    judgmentListId: jl.id,
  };
}

interface AcmeProductsChainSeed {
  clusterId: string;
  clusterName: string;
  querySetId: string;
  queryIds: string[];
  templateId: string;
  templateName: string;
  judgmentListId: string;
  judgmentListName: string;
  studyId: string;
  studyName: string;
}

/**
 * Seed the **acme-products-prod** scenario chain (cluster + query-set +
 * queries + template + judgment-list + study) using realistic e-commerce
 * naming from `scripts/seed_meaningful_demos.py` SCENARIOS[0]. Used by
 * guide-06's walkthrough spec so the screenshots look like a real production
 * tuning workflow rather than `e2e-*` dev-test artifacts.
 *
 * Self-contained: does NOT depend on `make seed-demo` having run. Every
 * entity name carries a `randomUUID().slice(0, 6)` suffix to avoid colliding
 * with the canonical `acme-products-prod` rows that `make seed-demo` writes —
 * `query_sets.name` and `judgment_lists.name` carry global unique constraints,
 * and re-running without a suffix on the template would bump its version on
 * every spec invocation. The suffix is the same across all five entities so
 * the relationship is visually obvious in the studies-list screenshot.
 *
 * Does NOT seed the ES index — registers only the Postgres rows. The target
 * picker dropdown on Step 1 of the create-study modal will therefore show
 * an empty state (or whatever ES indices happen to exist) when this
 * cluster is selected; the "Enter manually" toggle is the fallback path
 * the captions teach.
 */
export async function seedAcmeProductsChain(): Promise<AcmeProductsChainSeed> {
  const suffix = randomUUID().slice(0, 6);
  const clusterName = `acme-products-prod-${suffix}`;
  const templateName = `multi-match-title-boost-v1-${suffix}`;
  const querySetName = `top-product-searches-q4-2025-${suffix}`;
  const judgmentListName = `acme-products-relevance-2025-12-${suffix}`;
  const studyName = `tune-product-title-boost-baseline-${suffix}`;

  const cluster = await post<{ id: string }>('/api/v1/clusters', {
    name: clusterName,
    engine_type: 'elasticsearch',
    environment: 'prod',
    base_url: 'http://elasticsearch:9200',
    auth_kind: 'es_basic',
    credentials_ref: 'local-es',
    target_filter: 'products*',
  });

  const qset = await post<{ id: string }>('/api/v1/query-sets', {
    name: querySetName,
    cluster_id: cluster.id,
  });

  const queryTexts = [
    'wireless noise cancelling headphones',
    'womens running shoes',
    'kitchen knife set',
    'sony headphones',
    'noise cancelling over ear',
  ];
  const bulk = await post<{ added: number }>(`/api/v1/query-sets/${qset.id}/queries`, {
    queries: queryTexts.map((t) => ({
      query_text: t,
      reference_answer: null,
      query_metadata: null,
    })),
  });
  if (bulk.added !== queryTexts.length) {
    throw new Error(`Expected ${queryTexts.length} queries, got ${bulk.added}`);
  }
  const listBody = await get<{ data: Array<{ id: string }> }>(
    `/api/v1/query-sets/${qset.id}/queries?limit=50`,
  );
  const queryIds = listBody.data.map((r) => r.id);

  const templateBody = JSON.stringify({
    query: {
      multi_match: {
        query: '{{ query_text }}',
        fields: ['title^{{ title_boost }}', 'description', 'brand^2'],
        type: 'best_fields',
      },
    },
  });
  const tpl = await post<{ id: string; name: string; version: number }>(
    '/api/v1/query-templates',
    {
      name: templateName,
      engine_type: 'elasticsearch',
      body: templateBody,
      declared_params: { title_boost: 'float' },
    },
  );

  // Subset of SCENARIOS[0].judgments_map — ten ratings spanning queries 0-3.
  const judgmentTuples: Array<[number, string, 0 | 1 | 2 | 3]> = [
    [0, 'p1001', 3],
    [0, 'p1002', 3],
    [0, 'p2001', 0],
    [1, 'p2001', 3],
    [1, 'p2002', 3],
    [1, 'p1001', 0],
    [2, 'p3001', 3],
    [2, 'p1001', 0],
    [3, 'p1001', 3],
    [3, 'p1002', 1],
  ];
  const judgments = judgmentTuples.map(([qi, docId, rating]) => {
    const queryId = queryIds[qi];
    if (queryId === undefined) {
      throw new Error(`Query index ${qi} out of bounds (have ${queryIds.length} queries)`);
    }
    return {
      query_id: queryId,
      doc_id: docId,
      rating,
      notes: null,
    };
  });
  const jl = await post<{ id: string }>('/api/v1/judgment-lists/import', {
    name: judgmentListName,
    query_set_id: qset.id,
    cluster_id: cluster.id,
    target: 'products',
    rubric:
      'Rate 0=irrelevant, 1=partial, 2=relevant, 3=highly relevant by intent match (brand, product type, key feature).',
    judgments,
  });

  const study = await post<{ id: string; name: string }>('/api/v1/studies', {
    name: studyName,
    cluster_id: cluster.id,
    target: 'products',
    template_id: tpl.id,
    query_set_id: qset.id,
    judgment_list_id: jl.id,
    search_space: {
      params: {
        title_boost: { type: 'float', low: 0.5, high: 10.0, log: true },
      },
    },
    objective: { metric: 'ndcg', k: 10, direction: 'maximize' },
    config: { max_trials: 2, sampler: 'tpe', pruner: 'none' },
  });

  return {
    clusterId: cluster.id,
    clusterName,
    querySetId: qset.id,
    queryIds,
    templateId: tpl.id,
    templateName: tpl.name,
    judgmentListId: jl.id,
    judgmentListName,
    studyId: study.id,
    studyName: study.name,
  };
}

/**
 * Create a study against an existing chain. Enqueues the orchestrator worker;
 * the study transitions through queued → running → (completed | failed) per
 * normal Optuna behavior. Callers that just need a "queued" study can use the
 * returned id immediately without waiting for the orchestrator.
 */
export async function seedStudy(args: {
  clusterId: string;
  querySetId: string;
  templateId: string;
  judgmentListId: string;
  maxTrials?: number;
  /**
   * Target index/collection the study queries. Defaults to `'products'` so
   * the chained judgment-list (which `seedFullChain` / `seedJudgmentList`
   * also default to `'products'`) passes the FR-1 `JUDGMENT_TARGET_MISMATCH`
   * guard at POST /studies. Override only when the test deliberately sets
   * a non-default target on both the JL and the study.
   */
  target?: string;
}): Promise<StudySeed> {
  const {
    clusterId,
    querySetId,
    templateId,
    judgmentListId,
    maxTrials = 2,
    target = 'products',
  } = args;
  const suffix = randomUUID().slice(0, 8);
  const name = `e2e-study-${suffix}`;
  const study = await post<{ id: string; name: string }>('/api/v1/studies', {
    name,
    cluster_id: clusterId,
    target,
    template_id: templateId,
    query_set_id: querySetId,
    judgment_list_id: judgmentListId,
    search_space: {
      params: {
        boost: { type: 'float', low: 0.5, high: 5.0, log: false },
      },
    },
    objective: { metric: 'ndcg', k: 10, direction: 'maximize' },
    config: { max_trials: maxTrials, sampler: 'tpe', pruner: 'none' },
  });
  return { id: study.id, name: study.name };
}

/**
 * Create a manual proposal (study_id = null). Useful for proposals-list /
 * detail tests where we don't need an actual study completion.
 */
export async function seedProposal(args: {
  clusterId: string;
  templateId: string;
  configDiff?: Record<string, unknown>;
  metricDelta?: Record<string, unknown>;
}): Promise<ProposalSeed> {
  const { clusterId, templateId, configDiff, metricDelta } = args;
  const proposal = await post<{ id: string }>('/api/v1/proposals', {
    cluster_id: clusterId,
    template_id: templateId,
    config_diff: configDiff ?? {
      'title.boost': { before: 1.0, after: 2.5 },
      'description.boost': { before: 1.0, after: 0.8 },
    },
    metric_delta: metricDelta ?? {
      metric: 'ndcg@10',
      baseline: 0.412,
      achieved: 0.487,
      delta_pct: 18.2,
    },
  });
  return { id: proposal.id };
}

/**
 * Drive a study deterministically through queued → running → completed and
 * populate the digest (+ optional pending proposal) so the study-detail
 * page's digest panel renders against real backend rows.
 *
 * Backed by the test-only endpoint at `POST /api/v1/_test/studies/seed-completed`
 * which returns 404 unless `ENVIRONMENT=development` (the CI test environment
 * sets this; staging/production never expose the endpoint).
 *
 * Use this when an E2E test needs:
 *   - the seven InfoTooltip placements on the digest panel
 *   - AC-7 body-content assertions (narrative + recommended config)
 *   - AC-11 Open PR enabled-vs-aria-disabled branch coverage
 *
 * Without this helper the digest panel can only be exercised at the
 * vitest component layer with mocked data — the orchestrator + digest
 * worker can't be reliably driven to completion in a Playwright timeout.
 */
export async function seedStudyCompletedWithDigest(args: {
  clusterId: string;
  querySetId: string;
  templateId: string;
  judgmentListId: string;
  withPendingProposal?: boolean;
}): Promise<CompletedStudySeed> {
  const { clusterId, querySetId, templateId, judgmentListId, withPendingProposal = true } = args;
  const result = await post<{ study_id: string; digest_id: string; proposal_id: string | null }>(
    '/api/v1/_test/studies/seed-completed',
    {
      cluster_id: clusterId,
      query_set_id: querySetId,
      template_id: templateId,
      judgment_list_id: judgmentListId,
      with_pending_proposal: withPendingProposal,
    },
  );
  return {
    studyId: result.study_id,
    digestId: result.digest_id,
    proposalId: result.proposal_id,
  };
}

/**
 * Seed a completed study where the winner + runner-up trials carry
 * realistic per_query_metrics. Drives the `<ConfidencePanel>` happy path
 * on `/studies/[id]` end-to-end.
 *
 * The query_ids passed in must match the queries already seeded under
 * the query_set (the caller is responsible — typically via
 * `seedFullChain` followed by `seedQuerySet(..., numQueries=N)`).
 *
 * Backed by the test-only endpoint at
 * `POST /api/v1/_test/studies/seed-completed` (extended in
 * feat_pr_metric_confidence Story 2.3 to accept `winner_per_query` +
 * `runner_up_per_query`).
 */
export async function seedStudyCompletedWithPerQueryMetrics(args: {
  clusterId: string;
  querySetId: string;
  templateId: string;
  judgmentListId: string;
  queryIds: string[];
  withPendingProposal?: boolean;
}): Promise<CompletedStudySeed> {
  const {
    clusterId,
    querySetId,
    templateId,
    judgmentListId,
    queryIds,
    withPendingProposal = true,
  } = args;
  // Winner: high CI; qid 0 designed to regress vs runner-up.
  const winnerPerQuery: Record<string, Record<string, number>> = {};
  const runnerUpPerQuery: Record<string, Record<string, number>> = {};
  queryIds.forEach((qid, i) => {
    // Use the @k-suffixed key shape that backend.app.eval.scoring.score()
    // actually emits — the orchestrator looks up `ndcg@10` not bare `ndcg`.
    winnerPerQuery[qid] = { 'ndcg@10': i === 0 ? 0.4 : 0.85 - 0.01 * i };
    runnerUpPerQuery[qid] = { 'ndcg@10': i === 0 ? 0.95 : 0.84 - 0.01 * i };
  });
  const result = await post<{ study_id: string; digest_id: string; proposal_id: string | null }>(
    '/api/v1/_test/studies/seed-completed',
    {
      cluster_id: clusterId,
      query_set_id: querySetId,
      template_id: templateId,
      judgment_list_id: judgmentListId,
      with_pending_proposal: withPendingProposal,
      winner_per_query: winnerPerQuery,
      runner_up_per_query: runnerUpPerQuery,
    },
  );
  return {
    studyId: result.study_id,
    digestId: result.digest_id,
    proposalId: result.proposal_id,
  };
}

/**
 * Create a chat conversation. Title is optional; messages are NOT sent —
 * tests can navigate to `/chat/{id}` and exercise the page shell without
 * triggering LLM calls.
 */
export async function seedConversation(title?: string): Promise<ConversationSeed> {
  const conv = await post<{ id: string; title: string | null }>('/api/v1/conversations', {
    title: title ?? `e2e-conv-${randomUUID().slice(0, 8)}`,
  });
  return { id: conv.id, title: conv.title };
}
