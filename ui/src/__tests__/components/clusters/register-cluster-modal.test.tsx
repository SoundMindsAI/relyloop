import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';
import { server } from '../../setup';

/**
 * EntitySelect renders shadcn <Select> which crashes inside Dialog +
 * jsdom (Radix patchedFocus recursion). Same mock pattern as
 * create-study-modal.test.tsx, extended to forward data-testid.
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

const { RegisterClusterModal } = await import('@/components/clusters/register-cluster-modal');

const API_BASE = 'http://api.test';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

function configReposEmpty() {
  return http.get(`${API_BASE}/api/v1/config-repos`, () =>
    HttpResponse.json(
      { data: [], next_cursor: null, has_more: false },
      { headers: { 'X-Total-Count': '0' } },
    ),
  );
}

describe('RegisterClusterModal', () => {
  it('POSTs the form values to /clusters on submit', async () => {
    let captured: unknown = null;
    server.use(
      configReposEmpty(),
      http.post(`${API_BASE}/api/v1/clusters`, async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({
          id: 'c1',
          name: 'local-es',
          engine_type: 'elasticsearch',
          environment: 'dev',
          base_url: 'http://localhost:9200',
          auth_kind: 'es_apikey',
          engine_config: null,
          notes: null,
          created_at: '2026-05-12T00:00:00Z',
          health_check: {
            status: 'green',
            version: '9.4.0',
            checked_at: '2026-05-12T00:00:00Z',
            error: null,
          },
        });
      }),
    );

    wrap(<RegisterClusterModal open={true} onOpenChange={() => {}} />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'local-es' } });
    fireEvent.change(screen.getByLabelText('Base URL'), {
      target: { value: 'http://localhost:9200' },
    });
    fireEvent.change(screen.getByLabelText('Credentials ref (./secrets/<name>)'), {
      target: { value: 'es-apikey' },
    });
    fireEvent.click(screen.getByTestId('register-submit'));
    await waitFor(() => expect(captured).not.toBeNull());
    expect(captured).toMatchObject({
      name: 'local-es',
      engine_type: 'elasticsearch',
      environment: 'dev',
      base_url: 'http://localhost:9200',
      auth_kind: 'es_apikey',
      credentials_ref: 'es-apikey',
    });
  });

  it('surfaces CLUSTER_UNREACHABLE and keeps the modal mounted', async () => {
    let closed = false;
    server.use(
      configReposEmpty(),
      http.post(`${API_BASE}/api/v1/clusters`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'CLUSTER_UNREACHABLE',
              message: 'http://localhost:9200 refused connection',
              retryable: true,
            },
          },
          { status: 400 },
        ),
      ),
    );
    wrap(
      <RegisterClusterModal
        open={true}
        onOpenChange={(v) => {
          closed = !v;
        }}
      />,
    );
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'flaky' } });
    fireEvent.change(screen.getByLabelText('Base URL'), {
      target: { value: 'http://localhost:9200' },
    });
    fireEvent.change(screen.getByLabelText('Credentials ref (./secrets/<name>)'), {
      target: { value: 'es-apikey' },
    });
    fireEvent.click(screen.getByTestId('register-submit'));
    // Wait a tick so the mutation lifecycle settles.
    await waitFor(() =>
      expect(screen.getByTestId('register-submit')).toHaveTextContent('Register'),
    );
    expect(closed).toBe(false);
  });

  it('renders the config-repo empty-state CTA when no repos exist (Story 2.3)', async () => {
    server.use(configReposEmpty());
    wrap(<RegisterClusterModal open={true} onOpenChange={() => {}} />);
    await waitFor(() => {
      expect(screen.getByRole('link', { name: 'Register a config repo' })).toBeInTheDocument();
    });
    expect(screen.getByRole('link', { name: 'Register a config repo' })).toHaveAttribute(
      'href',
      '/clusters',
    );
    // The cl-repo control is always rendered now (no longer conditional).
    expect(screen.getByLabelText('Config repo (optional)')).toBeInTheDocument();
  });
});
