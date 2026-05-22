/**
 * Vitest test for global-teardown.ts orchestration
 * (chore_e2e_test_rows_isolation Story 1.2 plan §3.1 case 2).
 *
 * Uses a tempdir-backed `.cleanup/` directory + mocked global.fetch so
 * the test exercises the full read → dedupe → order → drain → write
 * → cleanup pipeline without touching the real filesystem or network.
 *
 * Key assertions:
 *   - DELETE call sequence matches FK-safe DRAIN_ORDER.
 *   - summary artifact shape matches spec FR-7 (registered,
 *     registered_deduped, attempted, deleted, failed, skipped_404,
 *     parse_failures, details).
 *   - apiBaseUrl resolved from config.metadata.apiBaseUrl.
 *   - .cleanup/ directory removed at exit.
 *   - Top-level errors do NOT reject the promise (best-effort contract).
 */

import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { FullConfig } from '@playwright/test';

import globalTeardown from '../global-teardown';

interface FetchCall {
  url: string;
  method: string;
}

function makeConfig(apiBaseUrl: string): FullConfig {
  // We only use `config.metadata.apiBaseUrl`; the rest of FullConfig is irrelevant.
  return { metadata: { apiBaseUrl } } as unknown as FullConfig;
}

describe('global-teardown.ts', () => {
  let originalCwd: string;
  let tempRoot: string;
  let fetchCalls: FetchCall[];

  beforeEach(() => {
    originalCwd = process.cwd();
    tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'cleanup-teardown-'));
    process.chdir(tempRoot);
    fetchCalls = [];
    // Default mock: every DELETE returns 204.
    vi.spyOn(global, 'fetch').mockImplementation(async (url: string | URL | Request) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      fetchCalls.push({ url: urlStr, method: 'DELETE' });
      return new Response(null, { status: 204 });
    });
  });

  afterEach(() => {
    process.chdir(originalCwd);
    fs.rmSync(tempRoot, { recursive: true, force: true });
    vi.restoreAllMocks();
  });

  function writeCleanupJsonl(entries: Array<{ resource: string; id: string }>): void {
    const dir = path.join(tempRoot, 'test-results', '.cleanup');
    fs.mkdirSync(dir, { recursive: true });
    const lines = entries.map((e) => JSON.stringify(e)).join('\n') + '\n';
    fs.writeFileSync(path.join(dir, 'worker-0.jsonl'), lines);
  }

  function readSummary(): {
    registered: number;
    registered_deduped: number;
    attempted: number;
    deleted: number;
    failed: number;
    skipped_404: number;
    parse_failures: number;
    details: Array<unknown>;
  } {
    const summaryPath = path.join(tempRoot, 'test-results', 'cleanup-summary.json');
    return JSON.parse(fs.readFileSync(summaryPath, 'utf8'));
  }

  it('drains in FK-safe order: proposals → digests → studies → judgment_lists → query_sets → query_templates → clusters', async () => {
    // Write entries in REVERSE FK-safe order on purpose — orchestrator must re-sort.
    writeCleanupJsonl([
      { resource: 'cluster', id: 'c1' },
      { resource: 'query_template', id: 'qt1' },
      { resource: 'query_set', id: 'qs1' },
      { resource: 'judgment_list', id: 'jl1' },
      { resource: 'study', id: 's1' },
      { resource: 'digest', id: 'd1' },
      { resource: 'proposal', id: 'p1' },
    ]);

    await globalTeardown(makeConfig('http://test-api:8000'));

    expect(fetchCalls.map((c) => c.url)).toEqual([
      'http://test-api:8000/api/v1/_test/proposals/p1',
      'http://test-api:8000/api/v1/_test/digests/d1',
      'http://test-api:8000/api/v1/_test/studies/s1',
      'http://test-api:8000/api/v1/_test/judgment-lists/jl1',
      'http://test-api:8000/api/v1/_test/query-sets/qs1',
      'http://test-api:8000/api/v1/_test/query-templates/qt1',
      'http://test-api:8000/api/v1/clusters/c1',
    ]);
  });

  it('writes summary artifact with the spec FR-7 shape', async () => {
    writeCleanupJsonl([
      { resource: 'cluster', id: 'c1' },
      { resource: 'study', id: 's1' },
    ]);

    await globalTeardown(makeConfig('http://test-api:8000'));
    const summary = readSummary();

    expect(summary.registered).toBe(2);
    expect(summary.registered_deduped).toBe(2);
    expect(summary.attempted).toBe(2);
    expect(summary.deleted).toBe(2);
    expect(summary.failed).toBe(0);
    expect(summary.skipped_404).toBe(0);
    expect(summary.parse_failures).toBe(0);
    expect(summary.details).toHaveLength(2);
  });

  it('removes the .cleanup/ directory after successful drain', async () => {
    writeCleanupJsonl([{ resource: 'cluster', id: 'c1' }]);
    const cleanupDir = path.join(tempRoot, 'test-results', '.cleanup');
    expect(fs.existsSync(cleanupDir)).toBe(true);

    await globalTeardown(makeConfig('http://test-api:8000'));

    expect(fs.existsSync(cleanupDir)).toBe(false);
  });

  it('counts 404 responses as skipped_404 (already gone), not failed', async () => {
    writeCleanupJsonl([
      { resource: 'cluster', id: 'c1' },
      { resource: 'study', id: 's1' },
    ]);
    vi.mocked(global.fetch).mockImplementation(async (url: string | URL | Request) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      fetchCalls.push({ url: urlStr, method: 'DELETE' });
      return new Response(null, { status: 404 });
    });

    await globalTeardown(makeConfig('http://test-api:8000'));
    const summary = readSummary();
    expect(summary.deleted).toBe(0);
    expect(summary.skipped_404).toBe(2);
    expect(summary.failed).toBe(0);
    // Invariant: attempted == deleted + failed + skipped_404
    expect(summary.attempted).toBe(summary.deleted + summary.failed + summary.skipped_404);
  });

  it('counts non-2xx-non-404 responses as failed', async () => {
    writeCleanupJsonl([{ resource: 'cluster', id: 'c1' }]);
    vi.mocked(global.fetch).mockImplementation(async () => new Response(null, { status: 500 }));

    await globalTeardown(makeConfig('http://test-api:8000'));
    const summary = readSummary();
    expect(summary.failed).toBe(1);
  });

  it('counts parse failures toward failed (registry corruption surfaces in reporter)', async () => {
    const dir = path.join(tempRoot, 'test-results', '.cleanup');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, 'worker-0.jsonl'),
      '{"resource":"cluster","id":"c1"}\nnot valid json\n',
    );

    await globalTeardown(makeConfig('http://test-api:8000'));
    const summary = readSummary();
    expect(summary.parse_failures).toBe(1);
    expect(summary.failed).toBeGreaterThanOrEqual(1);
  });

  it('still writes a zero-count summary when cleanup dir is absent', async () => {
    // No .cleanup/ directory at all.
    await globalTeardown(makeConfig('http://test-api:8000'));
    const summary = readSummary();
    expect(summary.registered).toBe(0);
    expect(summary.attempted).toBe(0);
    expect(summary.deleted).toBe(0);
  });

  it('dedupes (resource, id) duplicates across workers before draining', async () => {
    const dir = path.join(tempRoot, 'test-results', '.cleanup');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, 'worker-0.jsonl'),
      '{"resource":"cluster","id":"shared"}\n',
    );
    fs.writeFileSync(
      path.join(dir, 'worker-1.jsonl'),
      '{"resource":"cluster","id":"shared"}\n',
    );

    await globalTeardown(makeConfig('http://test-api:8000'));
    expect(fetchCalls).toHaveLength(1);
    const summary = readSummary();
    expect(summary.registered).toBe(2);
    expect(summary.registered_deduped).toBe(1);
    expect(summary.attempted).toBe(1);
  });

  it('resolves apiBaseUrl from config.metadata.apiBaseUrl', async () => {
    writeCleanupJsonl([{ resource: 'cluster', id: 'c1' }]);
    await globalTeardown(makeConfig('http://custom-host:9999'));
    expect(fetchCalls[0]?.url).toBe('http://custom-host:9999/api/v1/clusters/c1');
  });

  it('does NOT throw on fetch errors — best-effort contract', async () => {
    writeCleanupJsonl([{ resource: 'cluster', id: 'c1' }]);
    vi.mocked(global.fetch).mockImplementation(async () => {
      throw new Error('network unreachable');
    });

    // The teardown returns void; expect no rejection.
    await expect(globalTeardown(makeConfig('http://test-api:8000'))).resolves.toBeUndefined();
    const summary = readSummary();
    expect(summary.failed).toBe(1);
  });
});
