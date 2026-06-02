// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * FR-7 modal-level wiring test for `chore_template_library_expansion`
 * Story 3.1 — verifies the Step-3 template summary actually renders
 * when the operator picks a template registered under a recommended
 * name, and renders nothing (graceful miss) when the registered name
 * is unrecognized.
 *
 * GPT-5.5 final-review cycle-2 finding on PR #416 — accepted: the
 * library-level test at `ui/src/__tests__/lib/template-descriptions.test.ts`
 * verifies the contract of `descriptionFor` / `cheatsheetUrlFor` but
 * does not exercise the JSX wire-up in `create-study-modal.tsx`. A
 * regression that rips out the summary `<p>` block would pass the
 * lib-level test but break the operator UX. This test catches that.
 */

import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { type ReactNode } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';

import { server } from '../../setup';

// Radix Select crashes inside jsdom's portal handling for this many-Select
// modal — replace with the shared native `<select>` shim from the helpers.
vi.mock('@/components/ui/select', async () => {
  const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
  return mockShadcnSelect();
});

const { CreateStudyModal } = await import('@/components/studies/create-study-modal');

const API_BASE = 'http://api.test';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

/** Mock the minimum surface needed to reach Step 3 with a template list. */
function mockMinimalBackend(templates: { id: string; name: string }[]) {
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
    http.get(`${API_BASE}/api/v1/clusters/c1/targets`, () =>
      HttpResponse.json({ data: [{ name: 'products', doc_count: 42 }] }),
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
          data: templates.map((t) => ({
            id: t.id,
            name: t.name,
            engine_type: 'elasticsearch',
            version: 1,
            created_at: '2026-05-12T00:00:00Z',
          })),
          next_cursor: null,
          has_more: false,
        },
        { headers: { 'X-Total-Count': String(templates.length) } },
      ),
    ),
  );
}

/** Drive the modal forward to Step 3 + select a given template id. */
async function advanceToStep3AndPick(templateId: string) {
  await waitFor(() => expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c1' } });
  await waitFor(() =>
    expect(screen.queryAllByRole('option', { name: /products/ }).length).toBeGreaterThan(0),
  );
  fireEvent.change(screen.getByLabelText('Target index / collection'), {
    target: { value: 'products' },
  });
  fireEvent.click(screen.getByTestId('step-next'));

  await waitFor(() => expect(screen.getByTestId('step-2')).toBeInTheDocument());
  await waitFor(() =>
    expect(screen.queryAllByRole('option', { name: 'demo' }).length).toBeGreaterThanOrEqual(1),
  );
  fireEvent.change(screen.getByLabelText('Query set'), { target: { value: 'qs1' } });
  await waitFor(() => {
    const opts = screen.queryAllByRole('option', { name: 'demo' });
    expect(opts.length).toBeGreaterThanOrEqual(2);
  });
  fireEvent.change(screen.getByLabelText('Judgment list'), { target: { value: 'jl1' } });
  fireEvent.click(screen.getByTestId('step-next'));

  await waitFor(() => expect(screen.getByTestId('step-3')).toBeInTheDocument());
  await waitFor(() => expect(screen.queryAllByRole('option').length).toBeGreaterThan(0));
  fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
    target: { value: templateId },
  });
}

describe('CreateStudyModal — FR-7 Step-3 template summary', () => {
  it('renders the one-line summary after picking a template registered under a recommended name', async () => {
    mockMinimalBackend([{ id: 'tpl-mmb', name: 'multi-match-basic-v1' }]);
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);

    await advanceToStep3AndPick('tpl-mmb');

    // The summary <p data-testid="cs-tpl-summary"> renders the
    // `descriptionFor('multi-match-basic-v1')` text.
    const summary = await screen.findByTestId('cs-tpl-summary');
    expect(summary).toBeInTheDocument();
    // Sanity: the summary text is the canonical first-sentence prefix from
    // `ui/src/lib/template-descriptions.ts`. Catches a regression where the
    // JSX wire-up loses its data binding (e.g. someone passes the template
    // id instead of the name into descriptionFor).
    expect(summary.textContent ?? '').toMatch(/Fast lexical baseline/);
  });

  it('renders nothing (graceful miss) when the registered name has no description-map entry', async () => {
    // FR-7 contract: the description map is keyed by the recommended
    // registration name documented in samples/templates/README.md. If the
    // operator registers the template under a custom name, the UI MUST
    // degrade gracefully (no summary rendered) rather than show a wrong
    // summary.
    mockMinimalBackend([{ id: 'tpl-custom', name: 'my-own-template-name-v3' }]);
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);

    await advanceToStep3AndPick('tpl-custom');

    // No `cs-tpl-summary` testid in the DOM.
    expect(screen.queryByTestId('cs-tpl-summary')).not.toBeInTheDocument();
  });
});
