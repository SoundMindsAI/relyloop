import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { ForkTemplateModal } from '@/components/templates/fork-template-modal';
import type { QueryTemplateDetail } from '@/lib/api/query-templates';

const API_BASE = 'http://api.test';

function makeParent(): QueryTemplateDetail {
  return {
    id: 'tpl-parent',
    name: 'match-title',
    engine_type: 'elasticsearch',
    body: '{"match":{"title":"{{q}}"}}',
    declared_params: { boost: 'float' },
    version: 3,
    parent_id: null,
    created_at: '2026-05-12T00:00:00Z',
  };
}

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe('ForkTemplateModal', () => {
  it('POSTs with parent_id and version-suffixed name', async () => {
    let captured: unknown = null;
    server.use(
      http.post(`${API_BASE}/api/v1/query-templates`, async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json(
          {
            id: 'tpl-child',
            name: 'forked',
            engine_type: 'elasticsearch',
            body: '{}',
            declared_params: {},
            version: 4,
            parent_id: 'tpl-parent',
            created_at: '2026-05-13T00:00:00Z',
          },
          { status: 201 },
        );
      }),
    );

    wrap(<ForkTemplateModal open={true} onOpenChange={() => {}} parent={makeParent()} />);

    await waitFor(() => expect(screen.getByTestId('fork-submit')).toBeInTheDocument());
    const nameInput = screen.getByLabelText('Name') as HTMLInputElement;
    expect(nameInput.value).toBe('match-title (v4)');

    fireEvent.click(screen.getByTestId('fork-submit'));
    await waitFor(() => expect(captured).not.toBeNull());
    expect(captured).toMatchObject({
      name: 'match-title (v4)',
      engine_type: 'elasticsearch',
      body: '{"match":{"title":"{{q}}"}}',
      declared_params: { boost: 'float' },
      parent_id: 'tpl-parent',
    });
  });
});
