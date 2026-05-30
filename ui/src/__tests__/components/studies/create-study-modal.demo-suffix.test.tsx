// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Story 3.3 — verify the create-study-modal cluster picker appends
 * " (Demo)" to demo cluster labels and not to non-demo cluster labels.
 *
 * Uses the shared shadcn-select mock so SelectItem renders as a native
 * <option>, making the label text directly assertable.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { TooltipProvider } from '@/components/ui/tooltip';
import { server } from '../../setup';

vi.mock('@/components/ui/select', async () => {
  const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
  return mockShadcnSelect();
});

const { CreateStudyModal } = await import('@/components/studies/create-study-modal');

const API_BASE = 'http://api.test';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <TooltipProvider>{node}</TooltipProvider>
    </QueryClientProvider>
  );
}

function clusterRow(id: string, name: string) {
  return {
    id,
    name,
    engine_type: 'elasticsearch',
    environment: 'prod',
    base_url: 'http://elasticsearch:9200',
    auth_kind: 'es_basic',
    target_filter: null,
    created_at: '2026-05-21T00:00:00Z',
    health_check: {
      status: 'green',
      version: '9.0.0',
      checked_at: '2026-05-21T00:00:00Z',
      error: null,
    },
  };
}

describe('CreateStudyModal — demo cluster label suffix (Story 3.3)', () => {
  it('appends " (Demo)" to demo cluster labels and not to non-demo ones', async () => {
    server.use(
      http.get(`${API_BASE}/api/v1/clusters`, () =>
        HttpResponse.json({
          data: [clusterRow('c-demo', 'acme-products-prod'), clusterRow('c-own', 'my-own-cluster')],
          next_cursor: null,
          has_more: false,
        }),
      ),
    );

    render(wrap(<CreateStudyModal open onOpenChange={() => {}} />));

    // Wait for the cluster <select> shim to render options.
    await waitFor(() => {
      expect(screen.queryByText(/acme-products-prod/)).toBeInTheDocument();
    });

    // Demo cluster label has the " (Demo)" suffix.
    const demoOption = screen.getByText(/acme-products-prod \(elasticsearch\) \(Demo\)/);
    expect(demoOption).toBeInTheDocument();

    // Non-demo cluster label does NOT have the suffix.
    const ownOption = screen.getByText(/my-own-cluster \(elasticsearch\)$/);
    expect(ownOption).toBeInTheDocument();
    expect(ownOption.textContent).not.toContain('(Demo)');
  });
});
