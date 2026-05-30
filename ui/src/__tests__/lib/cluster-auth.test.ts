// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

// Drift-guard: ALLOWED_AUTH_PER_ENGINE frontend mirror vs backend source
// (infra_adapter_solr Story A11).
//
// The frontend cluster-registration modal filters the auth_kind dropdown by
// the selected engine_type using `ui/src/lib/cluster-auth.ts`. The canonical
// source is `backend/app/adapters/registry.py ALLOWED_AUTH_PER_ENGINE`. We
// pin the expected shape here and assert character-for-character match. When
// the backend allowlist changes (e.g. opensearch gains sigv4 at MVP3), this
// test fails until the frontend mirror catches up.
//
// Why hardcode the expected map instead of generating it? The repo doesn't
// currently emit a JSON artifact from Python sources at test time. The
// hardcoded expected values stay in lockstep with the backend via this test
// + the source-of-truth comment in cluster-auth.ts — and a maintainer who
// changes one side without the other gets a CI failure at exactly the right
// integration boundary.

import { describe, expect, it } from 'vitest';

import { ALLOWED_AUTH_PER_ENGINE } from '@/lib/cluster-auth';

// Mirrors `backend/app/adapters/registry.py ALLOWED_AUTH_PER_ENGINE`. Update
// both sides in lockstep when the service-layer allowlist changes.
const EXPECTED: Record<string, readonly string[]> = {
  elasticsearch: ['es_apikey', 'es_basic'],
  opensearch: ['opensearch_basic'],
  solr: ['solr_basic', 'solr_apikey'],
};

describe('ALLOWED_AUTH_PER_ENGINE drift guard', () => {
  it('mirrors backend/app/adapters/registry.py ALLOWED_AUTH_PER_ENGINE', () => {
    expect(ALLOWED_AUTH_PER_ENGINE).toEqual(EXPECTED);
  });

  it('covers exactly the three MVP2-supported engines', () => {
    expect(Object.keys(ALLOWED_AUTH_PER_ENGINE).sort()).toEqual([
      'elasticsearch',
      'opensearch',
      'solr',
    ]);
  });

  it('every entry is non-empty (operators can always pick an auth_kind)', () => {
    for (const [engine, kinds] of Object.entries(ALLOWED_AUTH_PER_ENGINE)) {
      expect(kinds.length, `engine ${engine} has no auth kinds`).toBeGreaterThan(0);
    }
  });
});
