/**
 * Unit tests for the documents list page (feat_index_document_browser Story 3.3).
 *
 * Covers:
 *  - Happy paginated render with X-Total-Count parsed from response header.
 *  - Truncation sentinel rendering (AC-13).
 *  - 403 TARGETS_FORBIDDEN inline state (cycle-2 F8).
 *  - 404 TARGET_NOT_FOUND inline state (cycle-2 F8).
 *  - 503 CLUSTER_UNREACHABLE Retry button (AC-20).
 */
import { http, HttpResponse } from 'msw';
import { type ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';

import { server } from '../../../../../../setup';
import { DocumentsListView } from '@/app/clusters/[id]/indices/[name]/documents/page';
import { TooltipProvider } from '@/components/ui/tooltip';
import { DOCUMENT_FIELD_TRUNCATED } from '@/lib/documents-constants';

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

describe('DocumentsListView', () => {
  it('renders rows + X-Total-Count derived from header', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets/${INDEX}/documents`, () =>
        HttpResponse.json(
          {
            data: [
              { doc_id: 'doc-001', source: { title: 'Skyfall', year: 2012 } },
              { doc_id: 'doc-002', source: { title: 'Spectre', year: 2015 } },
            ],
            next_cursor: null,
            has_more: false,
          },
          { headers: { 'X-Total-Count': '8423' } },
        ),
      ),
    );
    wrap(<DocumentsListView clusterId={CLUSTER_ID} indexName={INDEX} />);
    await screen.findByTestId('documents-list-table');
    await screen.findByTestId('documents-row-doc-001');
    await screen.findByTestId('documents-row-doc-002');
    const total = await screen.findByTestId('documents-list-total-count');
    expect(total.textContent).toMatch(/8,423 documents/);
  });

  it('renders the truncation sentinel verbatim with a tooltip', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets/${INDEX}/documents`, () =>
        HttpResponse.json(
          {
            data: [
              {
                doc_id: 'big-doc',
                source: { title: 'ok', description: DOCUMENT_FIELD_TRUNCATED },
              },
            ],
            next_cursor: null,
            has_more: false,
          },
          { headers: { 'X-Total-Count': '1' } },
        ),
      ),
    );
    wrap(<DocumentsListView clusterId={CLUSTER_ID} indexName={INDEX} />);
    await screen.findByText(DOCUMENT_FIELD_TRUNCATED);
  });

  it('renders the empty state when 0 rows', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets/${INDEX}/documents`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    wrap(<DocumentsListView clusterId={CLUSTER_ID} indexName={INDEX} />);
    await screen.findByTestId('documents-list-empty');
  });

  it('renders the 403 TARGETS_FORBIDDEN inline state', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets/${INDEX}/documents`, () =>
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
    wrap(<DocumentsListView clusterId={CLUSTER_ID} indexName={INDEX} />);
    await screen.findByTestId('documents-list-forbidden');
  });

  it('renders the 404 TARGET_NOT_FOUND inline state', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets/${INDEX}/documents`, () =>
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
    wrap(<DocumentsListView clusterId={CLUSTER_ID} indexName={INDEX} />);
    await screen.findByTestId('documents-list-not-found');
  });

  it('renders a Retry button on CLUSTER_UNREACHABLE (non-retryable variant for unit-test isolation)', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets/${INDEX}/documents`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'CLUSTER_UNREACHABLE',
              message: 'HTTP 503',
              retryable: false,
            },
          },
          { status: 503 },
        ),
      ),
    );
    wrap(<DocumentsListView clusterId={CLUSTER_ID} indexName={INDEX} />);
    await screen.findByTestId('documents-list-unreachable');
    expect(screen.getByTestId('documents-list-retry')).toBeInTheDocument();
  });
});
