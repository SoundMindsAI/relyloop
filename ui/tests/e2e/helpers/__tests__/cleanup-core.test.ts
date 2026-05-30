// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Vitest unit tests for the pure cleanup-core module
 * (chore_e2e_test_rows_isolation Story 1.2 plan §3.1).
 *
 * No fs/network access — tests inject a memory-backed fs mock for
 * `readCleanupEntriesFromDir`. The other exports (`dedupeEntries`,
 * `orderEntries`, `buildDeleteUrl`, `RESOURCE_PATH_MAP`, `DRAIN_ORDER`)
 * are pure and tested directly.
 */

import { describe, expect, it } from 'vitest';

import {
  buildDeleteUrl,
  type CleanupEntry,
  dedupeEntries,
  DRAIN_ORDER,
  orderEntries,
  readCleanupEntriesFromDir,
  RESOURCE_PATH_MAP,
  type ResourceType,
} from '../cleanup-core';

describe('RESOURCE_PATH_MAP', () => {
  it('exhaustively maps every ResourceType to a URL path', () => {
    const keys = Object.keys(RESOURCE_PATH_MAP).sort();
    const expected: ResourceType[] = [
      'cluster',
      'digest',
      'judgment_list',
      'proposal',
      'query_set',
      'query_template',
      'study',
    ];
    expect(keys).toEqual(expected);
  });

  it('cluster maps to the existing operator-facing soft-delete endpoint', () => {
    expect(RESOURCE_PATH_MAP.cluster).toBe('/api/v1/clusters');
  });

  it('the 6 non-cluster resources all map under /_test/', () => {
    const nonCluster = Object.entries(RESOURCE_PATH_MAP).filter(([k]) => k !== 'cluster');
    for (const [, path] of nonCluster) {
      expect(path).toMatch(/^\/api\/v1\/_test\//);
    }
    expect(nonCluster).toHaveLength(6);
  });
});

describe('DRAIN_ORDER', () => {
  it('matches FK-safe order: proposals → digests → studies → judgment_lists → query_sets → query_templates → clusters', () => {
    expect(DRAIN_ORDER).toEqual([
      'proposal',
      'digest',
      'study',
      'judgment_list',
      'query_set',
      'query_template',
      'cluster',
    ]);
  });

  it('covers every ResourceType exactly once', () => {
    expect(new Set(DRAIN_ORDER).size).toBe(DRAIN_ORDER.length);
    expect(DRAIN_ORDER.length).toBe(Object.keys(RESOURCE_PATH_MAP).length);
  });
});

describe('dedupeEntries', () => {
  it('removes exact (resource, id) duplicates', () => {
    const entries: CleanupEntry[] = [
      { resource: 'cluster', id: 'a' },
      { resource: 'cluster', id: 'a' },
      { resource: 'study', id: 'b' },
    ];
    expect(dedupeEntries(entries)).toEqual([
      { resource: 'cluster', id: 'a' },
      { resource: 'study', id: 'b' },
    ]);
  });

  it('keeps same-id-different-resource entries (no false positive)', () => {
    const entries: CleanupEntry[] = [
      { resource: 'cluster', id: 'x' },
      { resource: 'study', id: 'x' },
    ];
    expect(dedupeEntries(entries)).toEqual(entries);
  });

  it('preserves first-seen order', () => {
    const entries: CleanupEntry[] = [
      { resource: 'study', id: 's1' },
      { resource: 'cluster', id: 'c1' },
      { resource: 'study', id: 's1' }, // duplicate
      { resource: 'judgment_list', id: 'jl1' },
    ];
    expect(dedupeEntries(entries)).toEqual([
      { resource: 'study', id: 's1' },
      { resource: 'cluster', id: 'c1' },
      { resource: 'judgment_list', id: 'jl1' },
    ]);
  });

  it('returns an empty array for empty input', () => {
    expect(dedupeEntries([])).toEqual([]);
  });
});

describe('orderEntries', () => {
  it('sorts entries by FK-safe resource order', () => {
    const entries: CleanupEntry[] = [
      { resource: 'cluster', id: 'c1' },
      { resource: 'study', id: 's1' },
      { resource: 'proposal', id: 'p1' },
      { resource: 'query_template', id: 'qt1' },
    ];
    const result = orderEntries(entries);
    expect(result.map((e) => e.resource)).toEqual([
      'proposal',
      'study',
      'query_template',
      'cluster',
    ]);
  });

  it('preserves insertion order within the same resource group', () => {
    const entries: CleanupEntry[] = [
      { resource: 'study', id: 's2' },
      { resource: 'cluster', id: 'c1' },
      { resource: 'study', id: 's1' },
    ];
    const result = orderEntries(entries);
    // Within 'study', s2 came before s1.
    expect(result.map((e) => e.id)).toEqual(['s2', 's1', 'c1']);
  });
});

describe('buildDeleteUrl', () => {
  it('builds an absolute URL from base + path + id', () => {
    const url = buildDeleteUrl('http://localhost:8000', {
      resource: 'study',
      id: 'abc-123',
    });
    expect(url).toBe('http://localhost:8000/api/v1/_test/studies/abc-123');
  });

  it('encodes id characters that would break a URL', () => {
    // Per spec: encodeURIComponent applied. (Real IDs are UUIDv7 — no
    // special chars — but the contract should hold for arbitrary strings.)
    const url = buildDeleteUrl('http://localhost:8000', {
      resource: 'cluster',
      id: 'a/b c',
    });
    expect(url).toBe('http://localhost:8000/api/v1/clusters/a%2Fb%20c');
  });

  it('handles base URL with explicit trailing slash', () => {
    // new URL() resolves both forms — verify no double slash.
    const withSlash = buildDeleteUrl('http://localhost:8000/', {
      resource: 'study',
      id: 's1',
    });
    const withoutSlash = buildDeleteUrl('http://localhost:8000', {
      resource: 'study',
      id: 's1',
    });
    expect(withSlash).toBe(withoutSlash);
  });

  it('uses /api/v1/clusters (not /_test/) for cluster', () => {
    const url = buildDeleteUrl('http://localhost:8000', {
      resource: 'cluster',
      id: 'c1',
    });
    expect(url).toBe('http://localhost:8000/api/v1/clusters/c1');
  });
});

describe('readCleanupEntriesFromDir', () => {
  // In-memory fs mock matching the parts of node:fs the function uses.
  function makeFsMock(files: Record<string, string>): {
    existsSync: (p: string) => boolean;
    readdirSync: (p: string) => string[];
    readFileSync: (p: string, _enc: string) => string;
  } {
    return {
      existsSync: (p: string) => p === '/tmp/cleanup' || p in files,
      readdirSync: (_p: string) =>
        Object.keys(files).map((f) => f.replace('/tmp/cleanup/', '')),
      readFileSync: (p: string) => files[p] ?? '',
    };
  }

  it('returns empty result when the dir does not exist', () => {
    const fsMock = {
      existsSync: () => false,
      readdirSync: () => [],
      readFileSync: () => '',
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const result = readCleanupEntriesFromDir('/nonexistent', fsMock as any);
    expect(result).toEqual({ raw: [], parseFailures: 0 });
  });

  it('parses valid JSONL entries from multiple worker files', () => {
    const fsMock = makeFsMock({
      '/tmp/cleanup/worker-0.jsonl': [
        '{"resource":"cluster","id":"c1"}',
        '{"resource":"study","id":"s1"}',
      ].join('\n'),
      '/tmp/cleanup/worker-1.jsonl': '{"resource":"digest","id":"d1"}\n',
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { raw, parseFailures } = readCleanupEntriesFromDir('/tmp/cleanup', fsMock as any);
    expect(raw).toHaveLength(3);
    expect(parseFailures).toBe(0);
    expect(raw).toContainEqual({ resource: 'cluster', id: 'c1' });
    expect(raw).toContainEqual({ resource: 'study', id: 's1' });
    expect(raw).toContainEqual({ resource: 'digest', id: 'd1' });
  });

  it('counts parse failures for malformed lines but continues', () => {
    const fsMock = makeFsMock({
      '/tmp/cleanup/worker-0.jsonl': [
        '{"resource":"cluster","id":"c1"}',
        'not valid json',
        '{"resource":"study","id":"s1"}',
        '',  // empty line — ignored, NOT counted as a parse failure
      ].join('\n'),
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { raw, parseFailures } = readCleanupEntriesFromDir('/tmp/cleanup', fsMock as any);
    expect(raw).toHaveLength(2);
    expect(parseFailures).toBe(1);
  });

  it('ignores non-worker-*.jsonl files in the directory', () => {
    const fsMock = makeFsMock({
      '/tmp/cleanup/worker-0.jsonl': '{"resource":"cluster","id":"c1"}',
      '/tmp/cleanup/README.md': 'this should be ignored',
      '/tmp/cleanup/cleanup-summary.json': '{"deleted":0}',
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { raw } = readCleanupEntriesFromDir('/tmp/cleanup', fsMock as any);
    expect(raw).toEqual([{ resource: 'cluster', id: 'c1' }]);
  });
});
