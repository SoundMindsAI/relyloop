// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Pure cleanup-core module — types, constants, and pure functions for the
 * Playwright E2E cleanup registry (chore_e2e_test_rows_isolation Story 1.2).
 *
 * No fs or network I/O in the named exports — testable in isolation.
 * `readCleanupEntriesFromDir` accepts an `fsModule` parameter so unit
 * tests can inject a tempdir-backed fs.
 *
 * The orchestration wrapper is at `ui/tests/e2e/global-teardown.ts`.
 */

import type * as fs from 'node:fs';

export type ResourceType =
  | 'proposal'
  | 'digest'
  | 'study'
  | 'judgment_list'
  | 'query_set'
  | 'query_template'
  | 'cluster';

export interface CleanupEntry {
  resource: ResourceType;
  id: string;
}

/**
 * Registry-resource → URL-path mapping. Per spec §FR-7 table.
 *
 * NOTE: `cluster` uses the existing operator-facing soft-delete endpoint,
 * NOT a test-only endpoint. The 6 new test-only endpoints handle the
 * other 6 resources.
 */
export const RESOURCE_PATH_MAP: Record<ResourceType, string> = {
  proposal: '/api/v1/_test/proposals',
  digest: '/api/v1/_test/digests',
  study: '/api/v1/_test/studies',
  judgment_list: '/api/v1/_test/judgment-lists',
  query_set: '/api/v1/_test/query-sets',
  query_template: '/api/v1/_test/query-templates',
  cluster: '/api/v1/clusters',
};

/**
 * FK-safe drain order (children → parents).
 *
 *   proposals → digests → studies (cascades trials)
 *     → judgment_lists (cascades judgments)
 *     → query_sets (cascades queries)
 *     → query_templates
 *     → clusters (existing soft-delete)
 *
 * Out-of-order deletion will hit the 409 HAS_DEPENDENT preflight in the
 * backend; the script logs + counts as `failed` and continues.
 */
export const DRAIN_ORDER: readonly ResourceType[] = [
  'proposal',
  'digest',
  'study',
  'judgment_list',
  'query_set',
  'query_template',
  'cluster',
] as const;

/**
 * Dedupe entries by `(resource, id)`. Preserves first-seen order.
 *
 * Useful when multiple workers register the same cluster (e.g., shared
 * setup spec) — the registry collects every JSONL line but the drain
 * should only fire one DELETE per resource.
 */
export function dedupeEntries(entries: readonly CleanupEntry[]): CleanupEntry[] {
  const seen = new Set<string>();
  const out: CleanupEntry[] = [];
  for (const e of entries) {
    const key = `${e.resource}:${e.id}`;
    if (!seen.has(key)) {
      seen.add(key);
      out.push(e);
    }
  }
  return out;
}

/**
 * Sort entries by `DRAIN_ORDER` resource-group; within a group, preserve
 * insertion order. Cleanup script consumes this directly.
 */
export function orderEntries(entries: readonly CleanupEntry[]): CleanupEntry[] {
  return [...entries].sort(
    (a, b) => DRAIN_ORDER.indexOf(a.resource) - DRAIN_ORDER.indexOf(b.resource),
  );
}

/**
 * Build the absolute DELETE URL for a `(resource, id)` pair.
 *
 * `encodeURIComponent` is applied to the id so UUIDv7 / arbitrary
 * strings don't break the URL. `new URL()` correctly handles both
 * trailing-slash and no-trailing-slash base URLs.
 */
export function buildDeleteUrl(apiBaseUrl: string, entry: CleanupEntry): string {
  const path = RESOURCE_PATH_MAP[entry.resource];
  // URL constructor: if apiBaseUrl ends with `/`, append path; else add `/`.
  // We use a leading `/` on every path so `new URL` treats them as absolute paths.
  return new URL(`${path}/${encodeURIComponent(entry.id)}`, apiBaseUrl).toString();
}

export interface ReadResult {
  raw: CleanupEntry[];
  parseFailures: number;
}

/**
 * Read all `worker-*.jsonl` files under `cleanupDir`, parse JSON-line entries.
 *
 * Returns the raw parsed entries (NOT yet deduped) + a `parseFailures` count
 * for diagnostics. Caller (orchestrator) is expected to count parse failures
 * toward the `failed` invariant so corrupted lines surface in the reporter.
 *
 * The `fsModule` parameter exists for testability — production callers pass
 * `node:fs`; unit tests can inject a tempdir-backed mock.
 */
export function readCleanupEntriesFromDir(
  cleanupDir: string,
  fsModule: typeof fs,
): ReadResult {
  if (!fsModule.existsSync(cleanupDir)) {
    return { raw: [], parseFailures: 0 };
  }
  const files = fsModule
    .readdirSync(cleanupDir)
    .filter((f) => /^worker-.+\.jsonl$/.test(f));
  const raw: CleanupEntry[] = [];
  let parseFailures = 0;
  for (const f of files) {
    const lines = fsModule.readFileSync(`${cleanupDir}/${f}`, 'utf8').split('\n');
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        raw.push(JSON.parse(line) as CleanupEntry);
      } catch {
        parseFailures += 1;
      }
    }
  }
  return { raw, parseFailures };
}
