import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';

/**
 * Radix Select crashes inside jsdom's portal handling when wrapped in a
 * Dialog (focus-trap + Select focus interplay produces a patched-focus
 * recursion). Same mock pattern as create-study-modal.test.tsx. The
 * CreateQuerySetRequest contract (what this test verifies) is unchanged.
 *
 * The mock also forwards `data-testid` from the SelectTrigger child to the
 * native <select> so the EntitySelect's testid contract round-trips.
 */
vi.mock('@/components/ui/select', async () => {
  const React = (await import('react')) as typeof import('react');
  function findTriggerProp(children: ReactNode, prop: 'id' | 'data-testid'): string | undefined {
    let value: string | undefined;
    React.Children.forEach(children, (child) => {
      if (
        React.isValidElement<{ id?: string; 'data-testid'?: string }>(child) &&
        typeof child.type === 'function' &&
        (child.type as { displayName?: string; name?: string }).name === 'SelectTrigger'
      ) {
        value = child.props[prop];
      }
    });
    return value;
  }
  function SelectTrigger() {
    return null;
  }
  return {
    Select: ({
      value,
      onValueChange,
      children,
      disabled,
    }: {
      value?: string;
      onValueChange?: (v: string) => void;
      children: ReactNode;
      disabled?: boolean;
    }) => (
      <select
        id={findTriggerProp(children, 'id')}
        data-testid={findTriggerProp(children, 'data-testid')}
        value={value ?? ''}
        disabled={disabled}
        onChange={(e) => onValueChange?.(e.target.value)}
      >
        <option value="" />
        {children}
      </select>
    ),
    SelectTrigger,
    SelectValue: () => null,
    SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
    SelectItem: ({
      value,
      children,
      disabled,
    }: {
      value: string;
      children: ReactNode;
      disabled?: boolean;
    }) => (
      <option value={value} disabled={disabled}>
        {children}
      </option>
    ),
  };
});

const { CreateQuerySetModal } = await import('@/components/query-sets/create-query-set-modal');

const API_BASE = 'http://api.test';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function clustersHandler(data: unknown[]) {
  return http.get(`${API_BASE}/api/v1/clusters`, () =>
    HttpResponse.json(
      { data, next_cursor: null, has_more: false },
      { headers: { 'X-Total-Count': String(data.length) } },
    ),
  );
}

const CLUSTER_FIXTURE = {
  id: 'c-1',
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
};

describe('CreateQuerySetModal', () => {
  it('POSTs to /query-sets with the selected cluster_id', async () => {
    let captured: unknown = null;
    server.use(
      clustersHandler([CLUSTER_FIXTURE]),
      http.post(`${API_BASE}/api/v1/query-sets`, async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({
          id: 'qs-1',
          name: 'demo',
          description: null,
          cluster_id: 'c-1',
          query_count: 0,
          created_at: '2026-05-12T00:00:00Z',
        });
      }),
    );
    wrap(<CreateQuerySetModal open={true} onOpenChange={() => {}} />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'demo' } });
    // Wait for the cluster dropdown to load (mocked <select> renders the option).
    await waitFor(() => {
      expect(screen.getByRole('option', { name: /local-es/i })).toBeInTheDocument();
    });
    fireEvent.change(screen.getByTestId('qs-cluster'), { target: { value: 'c-1' } });
    fireEvent.click(screen.getByTestId('create-query-set-submit'));
    await waitFor(() => expect(captured).not.toBeNull());
    expect(captured).toMatchObject({ name: 'demo', cluster_id: 'c-1' });
  });

  it('blocks submit and surfaces a validation error when no cluster is selected', async () => {
    let posted = false;
    server.use(
      clustersHandler([CLUSTER_FIXTURE]),
      http.post(`${API_BASE}/api/v1/query-sets`, async () => {
        posted = true;
        return HttpResponse.json({});
      }),
    );
    wrap(<CreateQuerySetModal open={true} onOpenChange={() => {}} />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'no-cluster' } });
    // Wait for the dropdown to be loaded; do NOT pick a cluster.
    await waitFor(() => {
      expect(screen.getByRole('option', { name: /local-es/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('create-query-set-submit'));
    // Wait a tick for the (potentially async) submit handler to run.
    await new Promise((r) => setTimeout(r, 50));
    expect(posted).toBe(false);
  });

  it('renders the empty-state CTA when no clusters are registered', async () => {
    server.use(clustersHandler([]));
    wrap(<CreateQuerySetModal open={true} onOpenChange={() => {}} />);
    await waitFor(() => {
      const cta = screen.queryByRole('link', { name: 'Register a cluster' });
      expect(cta).not.toBeNull();
    });
    expect(screen.getByRole('link', { name: 'Register a cluster' })).toHaveAttribute(
      'href',
      '/clusters',
    );
  });
});
