import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';

// Radix Select crashes inside jsdom's portal handling for this many-Select
// modal — replace it with a thin native <select> shim so the test can drive
// the form via change events. The CreateStudyRequest contract (the thing this
// test is actually verifying) is unchanged.
vi.mock('@/components/ui/select', async () => {
  const React = (await import('react')) as typeof import('react');
  // Find the SelectTrigger inside Select's children and pull its id; pass to <select>.
  function findTriggerId(children: ReactNode): string | undefined {
    let id: string | undefined;
    React.Children.forEach(children, (child) => {
      if (
        React.isValidElement<{ id?: string }>(child) &&
        typeof child.type === 'function' &&
        (child.type as { displayName?: string; name?: string }).name === 'SelectTrigger'
      ) {
        id = child.props.id;
      }
    });
    return id;
  }
  function SelectTrigger() {
    return null;
  }
  return {
    Select: ({
      value,
      onValueChange,
      children,
    }: {
      value?: string;
      onValueChange?: (v: string) => void;
      children: ReactNode;
    }) => (
      <select
        id={findTriggerId(children)}
        value={value ?? ''}
        onChange={(e) => onValueChange?.(e.target.value)}
      >
        <option value="" />
        {children}
      </select>
    ),
    SelectTrigger,
    SelectValue: () => null,
    SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
    SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
      <option value={value}>{children}</option>
    ),
  };
});

const { CreateStudyModal } = await import('@/components/studies/create-study-modal');

const API_BASE = 'http://api.test';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function mockBackend() {
  server.use(
    http.get(`${API_BASE}/api/v1/clusters`, () =>
      HttpResponse.json(
        {
          data: [
            {
              id: 'c1',
              name: 'local-es',
              engine_type: 'elasticsearch',
              environment: 'dev',
              base_url: 'http://localhost:9200',
              auth_kind: 'es_apikey',
              created_at: '2026-05-12T00:00:00Z',
              health_check: {
                status: 'green',
                version: '9.4.0',
                checked_at: '2026-05-12T00:00:00Z',
                error: null,
              },
            },
          ],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '1' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/clusters/c1/schema`, () => HttpResponse.json({ fields: [] })),
    http.get(`${API_BASE}/api/v1/query-sets`, () =>
      HttpResponse.json(
        {
          data: [{ id: 'qs1', name: 'demo', cluster_id: 'c1', created_at: '2026-05-12T00:00:00Z' }],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '1' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/judgment-lists`, () =>
      HttpResponse.json(
        {
          data: [
            {
              id: 'jl1',
              name: 'demo',
              description: null,
              query_set_id: 'qs1',
              cluster_id: 'c1',
              status: 'complete',
              created_at: '2026-05-12T00:00:00Z',
            },
          ],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '1' } },
      ),
    ),
    http.get(`${API_BASE}/api/v1/query-templates`, () =>
      HttpResponse.json(
        {
          data: [
            {
              id: 'tpl1',
              name: 'match-all',
              engine_type: 'elasticsearch',
              version: 1,
              created_at: '2026-05-12T00:00:00Z',
            },
          ],
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': '1' } },
      ),
    ),
  );
}

describe('CreateStudyModal', () => {
  it('walks all 5 steps and POSTs the correct CreateStudyRequest shape', async () => {
    mockBackend();
    let captured: unknown = null;
    server.use(
      http.post(`${API_BASE}/api/v1/studies`, async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({ id: 'st1', name: 'demo', status: 'queued' });
      }),
    );

    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);

    // Step 1 — pick cluster + target
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c1' } });
    fireEvent.change(screen.getByLabelText('Target index / collection'), {
      target: { value: 'products' },
    });
    fireEvent.click(screen.getByTestId('step-next'));

    // Step 2 — query set + judgment list
    await waitFor(() => expect(screen.getByTestId('step-2')).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.queryAllByRole('option', { name: 'demo' }).length).toBeGreaterThan(0),
    );
    fireEvent.change(screen.getByLabelText('Query set'), { target: { value: 'qs1' } });
    // Wait for the judgment-list options to populate (depends on query_set_id).
    await waitFor(() => {
      const opts = screen.queryAllByRole('option', { name: 'demo' });
      // Both query-set 'demo' and judgment-list 'demo' should be options now.
      expect(opts.length).toBeGreaterThanOrEqual(2);
    });
    fireEvent.change(screen.getByLabelText('Judgment list'), { target: { value: 'jl1' } });
    fireEvent.click(screen.getByTestId('step-next'));

    // Step 3 — template
    await waitFor(() => expect(screen.getByTestId('step-3')).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /match-all/ })).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
      target: { value: 'tpl1' },
    });
    fireEvent.click(screen.getByTestId('step-next'));

    // Step 4 — name + search space
    await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Study name'), { target: { value: 'first-run' } });
    fireEvent.change(screen.getByTestId('cs-search-space'), {
      target: { value: '{"boost": {"type": "float", "low": 0.1, "high": 2.0}}' },
    });
    fireEvent.click(screen.getByTestId('step-next'));

    // Step 5 — objective + stop condition + submit
    await waitFor(() => expect(screen.getByTestId('step-5')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Max trials'), { target: { value: '25' } });
    fireEvent.click(screen.getByTestId('create-study-submit'));

    await waitFor(() => expect(captured).not.toBeNull());
    expect(captured).toMatchObject({
      name: 'first-run',
      cluster_id: 'c1',
      target: 'products',
      template_id: 'tpl1',
      query_set_id: 'qs1',
      judgment_list_id: 'jl1',
      search_space: { boost: { type: 'float', low: 0.1, high: 2.0 } },
      objective: { metric: 'ndcg', k: 10, direction: 'maximize' },
      config: {
        max_trials: 25,
        parallelism: 4,
        sampler: 'tpe',
        pruner: 'median',
      },
    });
  });
});
