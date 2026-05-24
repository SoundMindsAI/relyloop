/**
 * feat_digest_executable_followups Story 5.2 — modal prefill flow tests.
 *
 * Covers:
 *   (a) When `initialValues` is provided, the form fields populate from prefill.
 *   (b) Submitting attaches the `parent` lineage payload to the POST body.
 *   (c) When `initialValues` is omitted, the POST body has no `parent` field.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';

import { server } from '../../setup';

vi.mock('@/components/ui/select', async () => {
  const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
  return mockShadcnSelect();
});

vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }),
  Toaster: () => null,
}));

const { CreateStudyModal } = await import('@/components/studies/create-study-modal');
type PrefillValues = import('@/components/studies/create-study-modal').PrefillValues;

const API_BASE = 'http://api.test';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

interface PostBody {
  parent?: { proposal_id: string; followup_index: number };
  [key: string]: unknown;
}

function mockBackend() {
  const postBodies: PostBody[] = [];
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
    http.get(`${API_BASE}/api/v1/clusters/c1/targets`, () =>
      HttpResponse.json({ data: [{ name: 'products', doc_count: 42 }] }),
    ),
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
              name: 'T1',
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
    http.get(`${API_BASE}/api/v1/query-templates/tpl1`, () =>
      HttpResponse.json({
        id: 'tpl1',
        name: 'T1',
        engine_type: 'elasticsearch',
        body: '{}',
        declared_params: { boost_title: 'float' },
        version: 1,
        parent_id: null,
        created_at: '2026-05-12T00:00:00Z',
      }),
    ),
    http.post(`${API_BASE}/api/v1/studies`, async ({ request }) => {
      const body = (await request.json()) as PostBody;
      postBodies.push(body);
      return HttpResponse.json({ id: 'st-new', name: 'demo', status: 'queued' });
    }),
  );
  return { postBodies };
}

const PREFILL: PrefillValues = {
  cluster_id: 'c1',
  target: 'products',
  template_id: 'tpl1',
  query_set_id: 'qs1',
  judgment_list_id: 'jl1',
  name: 'parent-study — followup #1 (narrow)',
  search_space_text: JSON.stringify(
    { params: { boost_title: { type: 'float', low: 1.0, high: 2.0 } } },
    null,
    2,
  ),
  metric: 'ndcg',
  k: 10,
  direction: 'maximize',
  max_trials: 200,
  parallelism: 4,
  sampler: 'tpe',
  pruner: 'median',
  parent: { proposal_id: 'p' + 'a'.repeat(35), followup_index: 0 },
};

/**
 * Walk the wizard from step 1 to step 4 (Search space), assuming all field
 * values are already set (whether by prefill or test seed). Each call to
 * step-next requires the prerequisite-step fields to be populated; we
 * trust the prefill or seed to have done that.
 *
 * After this call, the wizard is at step 4 (search space + objective +
 * config) and the Create study submit button is on-screen.
 */
async function walkToFinalStep(): Promise<void> {
  // Step 1 — pick cluster + target (prefill sets both; the user still has to
  // confirm by clicking through, OR we can fire the change to nudge the
  // controlled values into the DOM).
  await waitFor(() => expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument());
  // The select onChange handler maps to the form, so trigger a change even
  // if the prefill already set the value — confirms the dropdown surfaces the
  // value as selected for the test.
  fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c1' } });
  await waitFor(() =>
    expect(screen.queryAllByRole('option', { name: /products/ }).length).toBeGreaterThan(0),
  );
  fireEvent.change(screen.getByLabelText('Target index / collection'), {
    target: { value: 'products' },
  });
  fireEvent.click(screen.getByTestId('step-next'));

  // Step 2 — data sources (query set + judgment list).
  await waitFor(() => expect(screen.getByTestId('step-2')).toBeInTheDocument());
  await waitFor(() =>
    expect(screen.queryAllByRole('option', { name: 'demo' }).length).toBeGreaterThan(0),
  );
  fireEvent.change(screen.getByLabelText('Query set'), { target: { value: 'qs1' } });
  await waitFor(() => {
    expect(screen.queryAllByRole('option', { name: 'demo' }).length).toBeGreaterThanOrEqual(2);
  });
  fireEvent.change(screen.getByLabelText('Judgment list'), { target: { value: 'jl1' } });
  fireEvent.click(screen.getByTestId('step-next'));

  // Step 3 — template.
  await waitFor(() => expect(screen.getByTestId('step-3')).toBeInTheDocument());
  await waitFor(() => expect(screen.getAllByRole('option').length).toBeGreaterThan(0));
  fireEvent.change(screen.getByLabelText('Query template (filtered by engine)'), {
    target: { value: 'tpl1' },
  });
  fireEvent.click(screen.getByTestId('step-next'));

  // Step 4 — identity (study name).
  await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());
}

describe('CreateStudyModal — followup prefill (Story 5.2)', () => {
  afterEach(() => server.resetHandlers());

  it('renders the prefilled study name when initialValues is passed', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} initialValues={PREFILL} />);
    await walkToFinalStep();
    const nameInput = (await screen.findByLabelText('Study name')) as HTMLInputElement;
    expect(nameInput.value).toBe('parent-study — followup #1 (narrow)');
  });

  it('attaches the parent lineage payload to the POST body on submit', async () => {
    const { postBodies } = mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} initialValues={PREFILL} />);
    await walkToFinalStep();
    fireEvent.click(screen.getByTestId('step-next'));
    await waitFor(() => expect(screen.getByTestId('step-5')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /Create study/i }));

    await waitFor(() => expect(postBodies.length).toBeGreaterThan(0));
    expect(postBodies[0]!.parent).toEqual({
      proposal_id: PREFILL.parent.proposal_id,
      followup_index: 0,
    });
  });

  it('omits the parent field when initialValues is not provided (regression check)', async () => {
    const { postBodies } = mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToFinalStep();
    // The wizard's Step 4 (identity) needs a name when no prefill is set.
    fireEvent.change(screen.getByLabelText('Study name'), {
      target: { value: 'manual-no-parent' },
    });
    fireEvent.click(screen.getByTestId('step-next'));
    await waitFor(() => expect(screen.getByTestId('step-5')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /Create study/i }));

    await waitFor(() => expect(postBodies.length).toBeGreaterThan(0));
    expect('parent' in (postBodies[0] ?? {})).toBe(false);
  });

  it('AC-16 (Story 3.5): autofill suppression preserves the prefilled search_space_text', async () => {
    // Use the canonical PREFILL but verify that the textarea content stays
    // verbatim — the data-testid step-4 panel is where the autofill
    // effect (keyed on templateBody) would normally overwrite the
    // textarea. The FR-14 guard short-circuits it when the prefill
    // carries a non-empty search_space_text.
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} initialValues={PREFILL} />);
    await walkToFinalStep();
    // step-4 contains the textarea (created at step === 3 — 0-based step
    // index, 1-based data-testid).
    const searchSpaceTextarea = (await screen.findByTestId(
      'cs-search-space',
    )) as HTMLTextAreaElement;
    // Must STILL match the prefilled JSON — NOT the auto-generated
    // starter space for template tpl1 (which would have a boost_title
    // float, no surrounding curly-brace structure beyond that).
    expect(searchSpaceTextarea.value).toBe(PREFILL.search_space_text);
  });
});
