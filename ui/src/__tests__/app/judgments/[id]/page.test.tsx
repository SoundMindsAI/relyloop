// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { Suspense, type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TooltipProvider } from '@/components/ui/tooltip';

import { resetDataTableUrlMock } from '../../../helpers/data-table-url-mock';
import { server } from '../../../setup';

const API_BASE = 'http://api.test';

vi.mock('next/navigation', async () => {
  const mod = await import('../../../helpers/data-table-url-mock');
  return mod.makeNextNavigationMock();
});

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

beforeEach(() => {
  resetDataTableUrlMock();
});

afterEach(() => vi.restoreAllMocks());

function makeList() {
  return {
    id: 'list-1',
    name: 'demo list',
    description: null,
    query_set_id: 'qs-1',
    cluster_id: 'c-1',
    target: 'products',
    current_template_id: null,
    rubric: 'r',
    status: 'complete' as const,
    failed_reason: null,
    judgment_count: 12,
    source_breakdown: { llm: 10, human: 2, click: 0 },
    calibration: null,
    created_at: '2026-05-12T00:00:00Z',
  };
}

function makeJudgments(source: 'llm' | 'human' = 'llm') {
  return [
    {
      id: `j-${source}-1`,
      judgment_list_id: 'list-1',
      query_id: 'q1',
      doc_id: 'd1',
      rating: 2,
      source,
      rater_ref: null,
      confidence: 0.7,
      notes: null,
      created_at: '2026-05-12T00:00:00Z',
    },
  ];
}

async function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { JudgmentListView } = await import('@/app/judgments/[id]/page');
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>
        <Suspense fallback={<div data-testid="suspense-fallback">loading</div>}>
          <JudgmentListView listId="list-1" />
        </Suspense>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe('Judgment list page', () => {
  it('renders header counts + judgments table', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/judgment-lists/list-1`, () => HttpResponse.json(makeList())),
      http.get(`${API_BASE}/api/v1/judgment-lists/list-1/judgments`, () =>
        HttpResponse.json(
          { data: makeJudgments('llm'), next_cursor: null, has_more: false },
          { headers: { 'X-Total-Count': '1' } },
        ),
      ),
    );
    await renderPage();
    await waitFor(() => expect(screen.getByTestId('header-count')).toHaveTextContent('12'));
    expect(screen.getByTestId('header-breakdown')).toHaveTextContent('10 / 2');
    expect(screen.getByTestId('judgment-row-j-llm-1')).toBeInTheDocument();
  });

  it('clicking a source filter chip refetches with ?source=human', async () => {
    const capturedUrls: string[] = [];
    server.use(
      http.get(`${API_BASE}/api/v1/judgment-lists/list-1`, () => HttpResponse.json(makeList())),
      http.get(`${API_BASE}/api/v1/judgment-lists/list-1/judgments`, ({ request }) => {
        capturedUrls.push(request.url);
        const url = new URL(request.url);
        const src = url.searchParams.get('source');
        return HttpResponse.json(
          {
            data: makeJudgments(src === 'human' ? 'human' : 'llm'),
            next_cursor: null,
            has_more: false,
          },
          { headers: { 'X-Total-Count': '1' } },
        );
      }),
    );
    await renderPage();
    await waitFor(() => expect(screen.getByTestId('judgment-row-j-llm-1')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('filter-chip-source-human'));
    await waitFor(() => expect(screen.getByTestId('judgment-row-j-human-1')).toBeInTheDocument());
    const last = capturedUrls[capturedUrls.length - 1] ?? '';
    expect(new URL(last).searchParams.get('source')).toBe('human');
  });
});
