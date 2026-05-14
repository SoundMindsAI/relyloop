/**
 * E2E seed helpers — register clusters, query-sets, queries, and (optionally)
 * import a judgment list against the real backend at PLAYWRIGHT_API_BASE_URL.
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

  const bulk = await post<{ added: number }>(
    `/api/v1/query-sets/${qs.id}/queries`,
    {
      queries: Array.from({ length: numQueries }, (_, i) => ({
        query_text: `e2e query ${i}`,
        reference_answer: null,
        query_metadata: i === 0 ? { intent: 'test' } : null,
      })),
    },
  );
  if (bulk.added !== numQueries) {
    throw new Error(`Expected ${numQueries} queries, got ${bulk.added}`);
  }

  // Re-fetch the queries to learn their ids — backend assigns UUIDv7s.
  const list = await fetch(`${API_BASE}/api/v1/query-sets/${qs.id}/queries`);
  if (!list.ok) throw new Error(`GET queries failed: ${list.status}`);
  const listBody = (await list.json()) as { data: Array<{ id: string }> };
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
