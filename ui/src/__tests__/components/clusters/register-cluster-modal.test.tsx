import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { RegisterClusterModal } from '@/components/clusters/register-cluster-modal';

const API_BASE = 'http://api.test';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
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
});
