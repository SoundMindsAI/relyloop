// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TooltipProvider } from '@/components/ui/tooltip';

import { server } from '../../setup';

const API_BASE = 'http://api.test';

let lastReplace = '';
let lastPush = '';
let mockedSearch = '';

vi.mock('next/navigation', () => ({
  usePathname: () => '/test',
  useRouter: () => ({
    replace: (url: string) => {
      lastReplace = url;
    },
    push: (url: string) => {
      lastPush = url;
    },
  }),
  useSearchParams: () => new URLSearchParams(mockedSearch),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

async function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { default: StudiesPage } = await import('@/app/studies/page');
  return render(
    // TooltipProvider mirrors the real app shell (app/layout.tsx wraps the
    // whole tree in one). The studies-table Trials/Convergence columns render
    // an <InfoTooltip> in the column HEADER (via tooltipKey), and Radix's
    // Tooltip throws without a provider ancestor — so this isolated page
    // render needs the provider the layout would otherwise supply.
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <StudiesPage />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  lastReplace = '';
  lastPush = '';
  mockedSearch = '';
});

afterEach(() => {
  vi.restoreAllMocks();
});

function studyRows(count = 2) {
  return Array.from({ length: count }, (_, i) => ({
    id: `s${i}`,
    name: `study ${i}`,
    cluster_id: `c${i}`,
    status: 'running' as const,
    best_metric: 0.5 + i * 0.1,
    direction: 'maximize' as const,
    created_at: '2026-05-12T00:00:00Z',
    completed_at: null,
    // trial_count (required) + convergence_verdict (nullable) are part of
    // the StudySummary wire shape since feat_studies_convergence_visibility
    // (PR #421); the Trials + Convergence list columns
    // (feat_studies_list_trial_convergence_columns) render them, so the mock
    // must carry them or the Trials cell hits undefined.toLocaleString().
    trial_count: i * 3,
    convergence_verdict: null,
  }));
}

describe('StudiesPage', () => {
  it('renders rows from the API', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/studies`, () =>
        HttpResponse.json(
          { data: studyRows(2), next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '2' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('study-row-s0')).toBeInTheDocument();
      expect(screen.getByTestId('study-row-s1')).toBeInTheDocument();
    });
    // Total-count display now lives in the DataTable toolbar (Story 2.5).
    expect(screen.getByTestId('data-table-total-count')).toHaveTextContent('2');
  });

  it('clicking a status filter chip updates the URL via replace()', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/studies`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    await renderPage();
    // Empty state when data is empty + no matcher → no-rows-exist branch.
    await waitFor(() =>
      expect(screen.getByTestId('data-table-empty-no-rows-exist')).toBeInTheDocument(),
    );
    // Filter-chip testids follow the Story 2.3 `filter-chip-<col>-<val>` pattern.
    fireEvent.click(screen.getByTestId('filter-chip-status-running'));
    expect(lastReplace).toContain('status=running');
  });

  // ---------------------------------------------------------------------------
  // feat_index_document_browser Story 3.5 / AC-19 — ?target= filter chip.
  // ---------------------------------------------------------------------------

  it('AC-19: renders the Target filter chip when ?target= is in the URL', async () => {
    mockedSearch = 'target=acme-products';
    let capturedTarget: string | null = null;
    server.use(
      http.get(`${API_BASE}/api/v1/studies`, ({ request }) => {
        const url = new URL(request.url);
        capturedTarget = url.searchParams.get('target');
        return HttpResponse.json(
          { data: studyRows(1), next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '1' } },
        );
      }),
    );
    await renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('studies-target-filter-chip')).toBeInTheDocument();
    });
    const chip = screen.getByTestId('studies-target-filter-chip');
    expect(chip.textContent).toContain('acme-products');
    // Backend received the target param.
    expect(capturedTarget).toBe('acme-products');
  });

  it('AC-19: clicking × on the Target chip drops ?target= from the URL', async () => {
    mockedSearch = 'target=acme-products&cluster_id=cluster-1';
    server.use(
      http.get(`${API_BASE}/api/v1/studies`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() =>
      expect(screen.getByTestId('studies-target-filter-clear')).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('studies-target-filter-clear'));
    // cluster_id preserved; target dropped.
    expect(lastReplace).toContain('cluster_id=cluster-1');
    expect(lastReplace).not.toContain('target=');
  });

  it('AC-19: chip not rendered when ?target= is absent', async () => {
    mockedSearch = 'cluster_id=cluster-1';
    server.use(
      http.get(`${API_BASE}/api/v1/studies`, () =>
        HttpResponse.json(
          { data: [], next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '0' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => expect(screen.queryByTestId('studies-target-filter-chip')).toBeNull());
  });
});
