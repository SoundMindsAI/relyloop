/**
 * Playwright globalTeardown: drain the cleanup registry against the live
 * backend (chore_e2e_test_rows_isolation Story 1.2 FR-7).
 *
 * Reads all `test-results/.cleanup/worker-*.jsonl` files written by
 * `appendForCleanup` in `helpers/seed.ts`, dedupes + sorts in FK-safe
 * order via `helpers/cleanup-core.ts`, then issues a `fetch DELETE` per
 * row against `/api/v1/_test/<resource>/<id>` (or `/api/v1/clusters/<id>`
 * for clusters — existing operator-facing soft-delete).
 *
 * Safety contract:
 *   - Top-level try/catch/finally: any unexpected error (fs unreadable,
 *     network failure, etc.) MUST NOT reject this promise. Playwright
 *     treats a rejected globalTeardown as a teardown failure and may
 *     alter the exit code, violating the spec's best-effort contract.
 *   - Each fetch has a 5s AbortController timeout so a half-open
 *     connection cannot hang the suite.
 *   - Parse failures count toward the `failed` invariant so corrupted
 *     JSONL lines surface in the reporter.
 *   - `.cleanup/` directory is ALWAYS removed at exit, even on error.
 *   - Writes `test-results/cleanup-summary.json` with the required
 *     {registered, registered_deduped, attempted, deleted, failed,
 *      skipped_404, parse_failures, details} shape — the reporter
 *     reads this in `onEnd` to verify invariants.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import type { FullConfig } from '@playwright/test';

import {
  type CleanupEntry,
  type ResourceType,
  buildDeleteUrl,
  dedupeEntries,
  orderEntries,
  readCleanupEntriesFromDir,
} from './helpers/cleanup-core';

const FETCH_TIMEOUT_MS = 5_000;

/**
 * Resolve the API base URL.
 *
 * Reads `config.metadata.apiBaseUrl` (configured at
 * `ui/playwright.config.ts:45-47`), then falls back to the
 * `PLAYWRIGHT_API_BASE_URL` env var, then to the hardcoded default
 * `http://127.0.0.1:8000`.
 */
function resolveApiBaseUrl(config: FullConfig): string {
  const fromMetadata = (config.metadata as { apiBaseUrl?: string } | undefined)?.apiBaseUrl;
  return (
    fromMetadata ??
    process.env.PLAYWRIGHT_API_BASE_URL ??
    'http://127.0.0.1:8000'
  );
}

interface CleanupSummary {
  registered: number;
  registered_deduped: number;
  attempted: number;
  deleted: number;
  failed: number;
  skipped_404: number;
  parse_failures: number;
  details: Array<{
    resource: ResourceType | 'parse_failure';
    id: string;
    status: number;
    error_type?: 'error' | 'timeout' | 'parse_failure';
  }>;
}

function writeSummary(summary: CleanupSummary): void {
  const summaryPath = path.join(process.cwd(), 'test-results', 'cleanup-summary.json');
  fs.mkdirSync(path.dirname(summaryPath), { recursive: true });
  fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
}

export default async function globalTeardown(config: FullConfig): Promise<void> {
  const cleanupDir = path.join(process.cwd(), 'test-results', '.cleanup');
  try {
    const { raw, parseFailures } = readCleanupEntriesFromDir(cleanupDir, fs);
    const registered = raw.length;
    const entries = orderEntries(dedupeEntries(raw));
    const registered_deduped = entries.length;
    const apiBaseUrl = resolveApiBaseUrl(config);

    // Parse-failed lines count toward `failed` so the reporter catches them.
    let deleted = 0;
    let failed = parseFailures;
    let skipped_404 = 0;
    const details: CleanupSummary['details'] = [];
    // Synthetic detail entries for parse failures so the artifact alone
    // records the issue (the orchestrator-process log is also written).
    for (let i = 0; i < parseFailures; i++) {
      details.push({
        resource: 'parse_failure',
        id: `<malformed-line-${i}>`,
        status: 0,
        error_type: 'parse_failure',
      });
    }

    // Empty-registry path: emit zero-count summary + stdout line + return.
    if (entries.length === 0) {
      writeSummary({
        registered,
        registered_deduped,
        attempted: 0,
        deleted: 0,
        failed,
        skipped_404: 0,
        parse_failures: parseFailures,
        details,
      });
      console.log(
        `cleanup: 0 rows deleted across 0 resources; ${failed} failures, 0 already-gone`,
      );
      return;
    }

    for (const entry of entries) {
      const url = buildDeleteUrl(apiBaseUrl, entry);
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
      try {
        const resp = await fetch(url, { method: 'DELETE', signal: ctrl.signal });
        details.push({ resource: entry.resource, id: entry.id, status: resp.status });
        if (resp.status === 204) {
          deleted += 1;
        } else if (resp.status === 404) {
          skipped_404 += 1;
        } else {
          failed += 1;
          console.warn(`cleanup-teardown: ${url} → ${resp.status}`);
        }
      } catch (e) {
        failed += 1;
        const error_type: 'timeout' | 'error' =
          (e as Error).name === 'AbortError' ? 'timeout' : 'error';
        details.push({ resource: entry.resource, id: entry.id, status: 0, error_type });
        console.warn(
          `cleanup-teardown: ${url} → ${error_type}: ${(e as Error).message}`,
        );
      } finally {
        clearTimeout(timer);
      }
    }

    writeSummary({
      registered,
      registered_deduped,
      attempted: registered_deduped,
      deleted,
      failed,
      skipped_404,
      parse_failures: parseFailures,
      details,
    });
    const resourceCount = new Set(entries.map((e) => e.resource)).size;
    console.log(
      `cleanup: ${deleted} rows deleted across ${resourceCount} resources; ` +
        `${failed} failures, ${skipped_404} already-gone`,
    );
  } catch (e) {
    console.error(`cleanup-teardown: unexpected error — ${(e as Error).message}`);
    // Best-effort: write a failure summary so the reporter sees something.
    try {
      writeSummary({
        registered: 0,
        registered_deduped: 0,
        attempted: 0,
        deleted: 0,
        failed: 1,
        skipped_404: 0,
        parse_failures: 0,
        details: [
          {
            resource: 'cluster' as ResourceType,
            id: '<teardown-crash>',
            status: 0,
            error_type: 'error',
          },
        ],
      });
    } catch {
      /* swallow */
    }
  } finally {
    // ALWAYS remove the .cleanup/ directory, even on unexpected failure.
    try {
      fs.rmSync(cleanupDir, { recursive: true, force: true });
    } catch {
      /* swallow */
    }
  }
}
