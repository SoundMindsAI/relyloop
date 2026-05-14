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
      target: 'e2e-target',
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
      declared_params: { boost: 'float', query_text: 'string' },
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
}): Promise<JudgmentListSeed> {
  const { clusterId, querySetId, queryIds, ratingPerQuery = 2 } = args;
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
      target: 'e2e-target',
      rubric: 'e2e-rubric-v1 — rate relevance 0-3.',
      judgments,
    },
  );
  return { id: jl.id, judgmentCount: jl.judgment_count };
}

/**
 * Seed cluster + query-set + N queries + template + imported judgment list —
 * the full chain a study needs as FKs. Useful for studies / proposals tests.
 */
export async function seedFullChain(numQueries = 3): Promise<FullChainSeed> {
  const qs = await seedQuerySet(numQueries);
  const tpl = await seedTemplate();
  const jl = await seedJudgmentList({
    clusterId: qs.clusterId,
    querySetId: qs.querySetId,
    queryIds: qs.queryIds,
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
}): Promise<StudySeed> {
  const { clusterId, querySetId, templateId, judgmentListId, maxTrials = 2 } = args;
  const suffix = randomUUID().slice(0, 8);
  const name = `e2e-study-${suffix}`;
  const study = await post<{ id: string; name: string }>('/api/v1/studies', {
    name,
    cluster_id: clusterId,
    target: 'products',
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
