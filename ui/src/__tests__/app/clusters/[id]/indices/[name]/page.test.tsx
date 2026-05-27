/**
 * Unit tests for the index summary page (feat_index_document_browser Story 3.2 / FR-7).
 *
 * Covers:
 *  - Happy path: header + nav cards + schema table render against mock responses.
 *  - 404 TARGET_NOT_FOUND from /schema → AC-17 empty state.
 *  - Partial-permission state (D-28): /targets 403 + /schema 200 → "document
 *    count unknown" italic.
 *  - Full denial (cycle-2 F8): both 403 → "credentials don't allow inspecting".
 */
import { http, HttpResponse } from 'msw';
import { type ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';

import { server } from '../../../../../setup';
import { IndexSummaryView } from '@/app/clusters/[id]/indices/[name]/page';
import { TooltipProvider } from '@/components/ui/tooltip';

const API_BASE = 'http://api.test';
const CLUSTER_ID = 'cluster-1';
const INDEX = 'acme-products';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

const HAPPY_CLUSTER = {
  id: CLUSTER_ID,
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
};

const HAPPY_TARGETS = {
  data: [
    { name: INDEX, doc_count: 100_000 },
    { name: 'other-index', doc_count: 50 },
  ],
};

const HAPPY_SCHEMA = {
  fields: [
    { name: 'title', type: 'text', analyzer: 'standard', doc_count: 100_000 },
    { name: 'brand', type: 'keyword', analyzer: null, doc_count: 95_000 },
    { name: 'price', type: 'float', analyzer: null, doc_count: 100_000 },
  ],
};

function happyHandlers() {
  return [
    http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}`, () => HttpResponse.json(HAPPY_CLUSTER)),
    http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets`, () =>
      HttpResponse.json(HAPPY_TARGETS),
    ),
    http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/schema`, () =>
      HttpResponse.json(HAPPY_SCHEMA),
    ),
  ];
}

describe('IndexSummaryView', () => {
  it('renders header, nav cards, and schema table on happy path', async () => {
    server.use(...happyHandlers());
    wrap(<IndexSummaryView clusterId={CLUSTER_ID} indexName={INDEX} />);
    await screen.findByTestId('index-summary-header');
    await screen.findByText('100,000 documents');
    await screen.findByTestId('index-summary-browse-link');
    await screen.findByTestId('index-summary-studies-link');
    await screen.findByText('3 fields');
    // Schema rows present.
    await screen.findByText('title');
    await screen.findByText('brand');
  });

  it('renders 404 empty state when /schema returns TARGET_NOT_FOUND', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}`, () => HttpResponse.json(HAPPY_CLUSTER)),
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets`, () =>
        HttpResponse.json(HAPPY_TARGETS),
      ),
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/schema`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'TARGET_NOT_FOUND',
              message: 'no such index',
              retryable: false,
            },
          },
          { status: 404 },
        ),
      ),
    );
    wrap(<IndexSummaryView clusterId={CLUSTER_ID} indexName="missing-index" />);
    await screen.findByTestId('index-summary-not-found');
  });

  it('renders "document count unknown" partial-permission state when /targets is 403 but /schema is 200', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}`, () => HttpResponse.json(HAPPY_CLUSTER)),
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'TARGETS_FORBIDDEN',
              message: 'ACL denied',
              retryable: false,
            },
          },
          { status: 403 },
        ),
      ),
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/schema`, () =>
        HttpResponse.json(HAPPY_SCHEMA),
      ),
    );
    wrap(<IndexSummaryView clusterId={CLUSTER_ID} indexName={INDEX} />);
    await screen.findByText('document count unknown');
  });

  it('renders full-denial state when BOTH /targets and /schema return TARGETS_FORBIDDEN', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}`, () => HttpResponse.json(HAPPY_CLUSTER)),
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'TARGETS_FORBIDDEN',
              message: 'ACL denied',
              retryable: false,
            },
          },
          { status: 403 },
        ),
      ),
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/schema`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'TARGETS_FORBIDDEN',
              message: 'ACL denied',
              retryable: false,
            },
          },
          { status: 403 },
        ),
      ),
    );
    wrap(<IndexSummaryView clusterId={CLUSTER_ID} indexName={INDEX} />);
    const denied = await screen.findByTestId('index-summary-fully-denied');
    expect(denied.textContent).toMatch(/credentials don.t allow/i);
  });
});
