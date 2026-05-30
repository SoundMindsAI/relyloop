// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Unit tests for the document detail page (feat_index_document_browser Story 3.4 / FR-9).
 *
 * Covers:
 *  - Happy path: pretty-printed JSON + Copy button.
 *  - AC-9: 404 DOCUMENT_NOT_FOUND empty state.
 *  - AC-18: source: null → "_source: false" hint.
 *  - AC-16: doc_id with literal slashes round-trips (route catch-all).
 *  - 403 TARGETS_FORBIDDEN inline state.
 */
import { http, HttpResponse } from 'msw';
import { type ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';

import { server } from '../../../../../../../setup';
import { DocumentDetailView } from '@/app/clusters/[id]/indices/[name]/documents/[...doc_id]/page';
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

describe('DocumentDetailView', () => {
  it('renders pretty-printed JSON for a found document', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets/${INDEX}/documents/doc-001`, () =>
        HttpResponse.json({ doc_id: 'doc-001', source: { title: 'Skyfall', year: 2012 } }),
      ),
    );
    wrap(<DocumentDetailView clusterId={CLUSTER_ID} indexName={INDEX} docId="doc-001" />);
    const pre = await screen.findByTestId('document-detail-json');
    expect(pre.textContent).toContain('"title"');
    expect(pre.textContent).toContain('"Skyfall"');
    // Copy button visible when source is non-null.
    expect(screen.getByTestId('document-detail-copy')).toBeInTheDocument();
  });

  it('AC-9 — renders 404 DOCUMENT_NOT_FOUND empty state', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets/${INDEX}/documents/missing`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'DOCUMENT_NOT_FOUND',
              message: 'no such doc',
              retryable: false,
            },
          },
          { status: 404 },
        ),
      ),
    );
    wrap(<DocumentDetailView clusterId={CLUSTER_ID} indexName={INDEX} docId="missing" />);
    await screen.findByTestId('document-detail-not-found');
  });

  it('AC-18 — renders _source: false hint when source is null', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets/${INDEX}/documents/doc-007`, () =>
        HttpResponse.json({ doc_id: 'doc-007', source: null }),
      ),
    );
    wrap(<DocumentDetailView clusterId={CLUSTER_ID} indexName={INDEX} docId="doc-007" />);
    await screen.findByTestId('document-detail-source-null');
    // No copy button when source is null.
    expect(screen.queryByTestId('document-detail-copy')).toBeNull();
  });

  it('AC-16 — doc_id with literal slashes round-trips', async () => {
    server.use(
      http.get(
        `${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets/${INDEX}/documents/https%3A%2F%2Fexample.com%2Fp%2F123`,
        () => HttpResponse.json({ doc_id: 'https://example.com/p/123', source: { kind: 'url' } }),
      ),
    );
    wrap(
      <DocumentDetailView
        clusterId={CLUSTER_ID}
        indexName={INDEX}
        docId="https://example.com/p/123"
      />,
    );
    const pre = await screen.findByTestId('document-detail-json');
    expect(pre.textContent).toContain('"kind"');
    // Breadcrumb renders the un-encoded doc_id.
    const crumb = screen.getByTestId('document-detail-doc-id');
    expect(crumb.textContent).toBe('https://example.com/p/123');
  });

  it('renders 403 TARGETS_FORBIDDEN inline state', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters/${CLUSTER_ID}/targets/${INDEX}/documents/doc-001`, () =>
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
    wrap(<DocumentDetailView clusterId={CLUSTER_ID} indexName={INDEX} docId="doc-001" />);
    await screen.findByTestId('document-detail-forbidden');
  });
});
