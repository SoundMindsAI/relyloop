// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Unit tests for LinkedEntitiesRow (feat_index_document_browser Story 3.5).
 *
 * Asserts the 5th entry "Index" (FR-10 / AC-11) — href points at the index
 * summary page with cluster_id + target URL-encoded.
 */
import { http, HttpResponse } from 'msw';
import { type ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';

import { server } from '../../setup';
import { LinkedEntitiesRow } from '@/components/studies/linked-entities-row';
import type { StudyDetail } from '@/lib/api/studies';

const API_BASE = 'http://api.test';

const STUDY = {
  id: 'study-1',
  name: 'test-study',
  cluster_id: 'cluster-1',
  target: 'acme-products',
  template_id: 'tmpl-1',
  query_set_id: 'qs-1',
  judgment_list_id: 'jl-1',
} as unknown as StudyDetail;

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function happyHandlers() {
  return [
    http.get(`${API_BASE}/api/v1/clusters/cluster-1`, () =>
      HttpResponse.json({
        id: 'cluster-1',
        name: 'acme-prod',
        engine_type: 'elasticsearch',
        environment: 'prod',
        base_url: 'http://es:9200',
        auth_kind: 'es_basic',
        engine_config: null,
        notes: null,
        target_filter: null,
        created_at: '2026-05-27T00:00:00Z',
        health_check: {
          status: 'green',
          version: '9.4.0',
          checked_at: '2026-05-27T00:00:00Z',
          error: null,
        },
      }),
    ),
    http.get(`${API_BASE}/api/v1/query-sets/qs-1`, () =>
      HttpResponse.json({ id: 'qs-1', name: 'my-qs' }),
    ),
    http.get(`${API_BASE}/api/v1/judgment-lists/jl-1`, () =>
      HttpResponse.json({ id: 'jl-1', name: 'my-jl' }),
    ),
    http.get(`${API_BASE}/api/v1/query-templates/tmpl-1`, () =>
      HttpResponse.json({ id: 'tmpl-1', name: 'my-tmpl' }),
    ),
  ];
}

describe('LinkedEntitiesRow', () => {
  it('renders 5 entries — cluster, query set, judgment list, template, index', async () => {
    server.use(...happyHandlers());
    wrap(<LinkedEntitiesRow study={STUDY} />);
    // All 5 testids present.
    await screen.findByTestId('linked-cluster');
    expect(screen.getByTestId('linked-query-set')).toBeInTheDocument();
    expect(screen.getByTestId('linked-judgment-list')).toBeInTheDocument();
    expect(screen.getByTestId('linked-template')).toBeInTheDocument();
    expect(screen.getByTestId('linked-index')).toBeInTheDocument();
  });

  it('linked-index entry points at the index summary route with cluster_id + target encoded', async () => {
    server.use(...happyHandlers());
    wrap(<LinkedEntitiesRow study={STUDY} />);
    const index = await screen.findByTestId('linked-index');
    const anchor = index.querySelector('a');
    expect(anchor?.getAttribute('href')).toBe('/clusters/cluster-1/indices/acme-products');
  });

  it('encodes target with special characters', async () => {
    server.use(...happyHandlers());
    wrap(<LinkedEntitiesRow study={{ ...STUDY, target: 'has/slash' } as unknown as StudyDetail} />);
    const index = await screen.findByTestId('linked-index');
    const anchor = index.querySelector('a');
    expect(anchor?.getAttribute('href')).toBe('/clusters/cluster-1/indices/has%2Fslash');
  });
});
