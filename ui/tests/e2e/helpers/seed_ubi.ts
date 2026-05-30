// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * UBI seed helpers (feat_ubi_judgments E2E — chore_ubi_e2e_suite).
 *
 * Writes the standardized `ubi_queries` + `ubi_events` index shapes directly
 * to the engine's HTTP API, bypassing RelyLoop's backend. This mirrors the
 * real-world posture: RelyLoop NEVER writes UBI — the operator's application
 * (or, here, the test) populates the indices; RelyLoop only reads them. So
 * the seed helper talks to the engine directly, exactly as
 * `bulkIndexDocsToES` in `seed.ts` does for the products index.
 *
 * The clusters seeded by `seed.ts` are `engine_type=elasticsearch` pointing
 * at `http://elasticsearch:9200` (resolved in-container) — the same engine
 * this helper writes to via the host-forwarded `ES_BASE` (127.0.0.1:9200).
 *
 * Indices are created with EXPLICIT mappings (keyword for the `term`-filtered
 * fields, date for `timestamp`) so the UbiReader's `term`/`range` filters
 * match deterministically — auto-mapped `text` fields would make
 * `{"term": {"application": target}}` brittle.
 *
 * Canonical mappings live in `samples/ubi_index_mappings.json` per
 * feat_demo_ubi_study_comparison FR-1 (the Python synthetic-UBI generator
 * loads the same file). A round-trip unit test at
 * `backend/tests/unit/services/test_demo_ubi_seed.py::
 * test_mapping_file_round_trips_to_seed_ubi_helper_shape` pins the JSON
 * shape against the prior inline shape so neither side can silently drift.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ES_BASE = process.env.PLAYWRIGHT_ES_BASE_URL ?? 'http://127.0.0.1:9200';

const UBI_QUERIES_INDEX = 'ubi_queries';
const UBI_EVENTS_INDEX = 'ubi_events';

// Repo-root-relative path. Playwright runs from the `ui/` working directory
// (see `ui/playwright.config.ts`), so the JSON file is one level up.
const _MAPPINGS_PATH = resolve(process.cwd(), '..', 'samples', 'ubi_index_mappings.json');
const _MAPPINGS = JSON.parse(readFileSync(_MAPPINGS_PATH, 'utf8')) as Record<
  'ubi_queries' | 'ubi_events',
  { mappings: { properties: Record<string, unknown> } }
>;

const UBI_QUERIES_MAPPING = _MAPPINGS.ubi_queries;
const UBI_EVENTS_MAPPING = _MAPPINGS.ubi_events;

async function deleteIndex(index: string): Promise<void> {
  // Tolerate 404 (index may not exist yet).
  await fetch(`${ES_BASE}/${encodeURIComponent(index)}`, { method: 'DELETE' });
}

async function createIndex(index: string, mapping: unknown): Promise<void> {
  const resp = await fetch(`${ES_BASE}/${encodeURIComponent(index)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(mapping),
  });
  // 400 with resource_already_exists is tolerable (concurrent worker); other
  // failures throw so a misconfigured engine surfaces in test setup.
  if (!resp.ok && resp.status !== 400) {
    const text = await resp.text();
    throw new Error(`PUT ${index} mapping failed: ${resp.status} ${text}`);
  }
}

async function bulk(index: string, docs: Array<Record<string, unknown>>): Promise<void> {
  if (docs.length === 0) return;
  const lines: string[] = [];
  for (const doc of docs) {
    lines.push(JSON.stringify({ index: {} }));
    lines.push(JSON.stringify(doc));
  }
  const ndjson = lines.join('\n') + '\n';
  const resp = await fetch(`${ES_BASE}/${encodeURIComponent(index)}/_bulk?refresh=wait_for`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-ndjson' },
    body: ndjson,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`_bulk into ${index} failed: ${resp.status} ${text}`);
  }
  const payload = (await resp.json()) as { errors?: boolean };
  if (payload.errors) {
    throw new Error(
      `_bulk into ${index} reported per-item errors: ${JSON.stringify(payload).slice(0, 400)}`,
    );
  }
}

export interface UbiQueryRow {
  queryId: string;
  userQuery: string;
}

/** Write `ubi_queries` rows for `target`. Recreates the index with a clean mapping. */
export async function seedUbiQueries(target: string, rows: UbiQueryRow[]): Promise<void> {
  await deleteIndex(UBI_QUERIES_INDEX);
  await createIndex(UBI_QUERIES_INDEX, UBI_QUERIES_MAPPING);
  const ts = new Date().toISOString();
  await bulk(
    UBI_QUERIES_INDEX,
    rows.map((r) => ({
      query_id: r.queryId,
      user_query: r.userQuery,
      application: target,
      timestamp: ts,
    })),
  );
}

export interface UbiEventRow {
  queryId: string;
  docId: string;
  action: 'impression' | 'click' | 'dwell';
  position?: number;
  dwellSeconds?: number;
}

/** Write `ubi_events` rows for `target`. Recreates the index with a clean mapping. */
export async function seedUbiEvents(target: string, rows: UbiEventRow[]): Promise<void> {
  await deleteIndex(UBI_EVENTS_INDEX);
  await createIndex(UBI_EVENTS_INDEX, UBI_EVENTS_MAPPING);
  const ts = new Date().toISOString();
  await bulk(
    UBI_EVENTS_INDEX,
    rows.map((r) => {
      const doc: Record<string, unknown> = {
        query_id: r.queryId,
        action_name: r.action,
        object_id: r.docId,
        application: target,
        timestamp: ts,
      };
      if (r.position !== undefined) doc.position = r.position;
      if (r.dwellSeconds !== undefined) doc.dwell_seconds = r.dwellSeconds;
      return doc;
    }),
  );
}

export interface SeedUbiForQuerySetOpts {
  /** UBI `application` filter — must equal the target index name. */
  target: string;
  /** Each ({queryId, userQuery}) maps a UBI query_id to a query_set query's text. */
  queries: UbiQueryRow[];
  /** Doc ids each query has events against. */
  docIds: string[];
  /** Impressions per (query, doc) pair. Tune to hit a readiness rung. */
  impressionsPerPair: number;
  /** Clicks on the FIRST doc of each query (drives a positive CTR rating). */
  clicksPerQuery: number;
  /** Per-click dwell seconds (drives the dwell-time converter). */
  dwellSeconds?: number;
}

/**
 * High-level helper: seed `ubi_queries` + `ubi_events` sized to hit a target
 * readiness rung. Total event count = queries × docs × impressionsPerPair +
 * queries × clicksPerQuery — the readiness classifier counts events for
 * `(application=target, last 30 days)` and thresholds at
 * `min_impressions_threshold` (100) → rung_2, 5× → rung_3.
 *
 * Impressions are spread across ranks (position = doc index + 1) so the
 * Wang-Bendersky position-bias correction has rank signal to work with.
 */
export async function seedUbiForQuerySet(
  opts: SeedUbiForQuerySetOpts,
): Promise<{ eventCount: number }> {
  await seedUbiQueries(opts.target, opts.queries);

  const events: UbiEventRow[] = [];
  for (const q of opts.queries) {
    opts.docIds.forEach((docId, rank) => {
      for (let i = 0; i < opts.impressionsPerPair; i++) {
        events.push({ queryId: q.queryId, docId, action: 'impression', position: rank + 1 });
      }
    });
    // Clicks + dwell on the first doc — gives that pair a high corrected CTR.
    const firstDoc = opts.docIds[0];
    if (firstDoc !== undefined) {
      for (let c = 0; c < opts.clicksPerQuery; c++) {
        events.push({ queryId: q.queryId, docId: firstDoc, action: 'click' });
        if (opts.dwellSeconds !== undefined) {
          events.push({
            queryId: q.queryId,
            docId: firstDoc,
            action: 'dwell',
            dwellSeconds: opts.dwellSeconds,
          });
        }
      }
    }
  }

  await seedUbiEvents(opts.target, events);
  return { eventCount: events.length };
}

/** Tear down both UBI indices (used in afterEach so specs don't leak rung state). */
export async function teardownUbi(): Promise<void> {
  await deleteIndex(UBI_QUERIES_INDEX);
  await deleteIndex(UBI_EVENTS_INDEX);
}
