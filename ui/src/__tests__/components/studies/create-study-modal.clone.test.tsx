/**
 * feat_study_clone_from_previous Story 2.2 — CreateStudyModal clone-mode tests.
 *
 * Covers FR-6 / FR-10 / FR-12 / D-12 + ACs 4 / 5 / 9 / 15 / 16:
 *   (a) parent_study_id set → POST payload includes parent_study_id AND
 *       lacks `cloneSource` as an own property (hasOwnProperty check —
 *       catches both leaked `{ id, name }` AND the subtler `undefined`
 *       leak from a stray `...initialValues` spread).
 *   (b) Banner renders when initialValues.cloneSource is present (FR-12).
 *   (c) Banner absent when cloneSource absent — INCLUDING the synthetic
 *       case where parent_study_id is set but cloneSource is not.
 *   (d) Regression: modal still works when neither parent nor
 *       parent_study_id nor cloneSource is set (existing "New study" flow).
 *   (g) Existing `parent: ParentFollowupRef` lineage preserved (regression
 *       guard against the serializer accidentally dropping the
 *       proposal-followup lineage).
 *   (h) Both lineage axes set simultaneously (clone-of-a-followup-study):
 *       POST payload has BOTH `parent` AND `parent_study_id`; `cloneSource`
 *       is absent (FR-10 + D-12 round-trip at the frontend layer).
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
const CLONE_SOURCE_ID = '01970000-0000-7000-8000-000000000abc';
const CLONE_SOURCE_NAME = 'parent-study-being-cloned';
const PROPOSAL_ID = 'p' + 'a'.repeat(35);

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
  parent_study_id?: string;
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
      return HttpResponse.json({ id: 'st-new', name: 'cloned', status: 'queued' });
    }),
  );
  return { postBodies };
}

const CLONE_PREFILL: PrefillValues = {
  cluster_id: 'c1',
  target: 'products',
  template_id: 'tpl1',
  query_set_id: 'qs1',
  judgment_list_id: 'jl1',
  name: `${CLONE_SOURCE_NAME} (clone)`,
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
  parent_study_id: CLONE_SOURCE_ID,
  cloneSource: { id: CLONE_SOURCE_ID, name: CLONE_SOURCE_NAME },
};

async function walkToFinalStep(): Promise<void> {
  // Step 1 — cluster + target.
  await waitFor(() => expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'c1' } });
  await waitFor(() =>
    expect(screen.queryAllByRole('option', { name: /products/ }).length).toBeGreaterThan(0),
  );
  fireEvent.change(screen.getByLabelText('Target index / collection'), {
    target: { value: 'products' },
  });
  fireEvent.click(screen.getByTestId('step-next'));

  // Step 2 — data sources.
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

  // Step 4 — identity (name + search space).
  await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());
}

describe('CreateStudyModal — clone-mode banner + serializer hygiene', () => {
  afterEach(() => server.resetHandlers());

  // (b) Banner renders when initialValues.cloneSource is present (FR-12).
  it('(b) renders the cloned-from banner when initialValues.cloneSource is set', () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} initialValues={CLONE_PREFILL} />);
    const banner = screen.getByTestId('cloned-from-banner');
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent(CLONE_SOURCE_NAME);
    const viewSourceLink = screen.getByRole('link', { name: /view source/i });
    expect(viewSourceLink).toHaveAttribute('href', `/studies/${CLONE_SOURCE_ID}`);
  });

  // (c) Banner absent when cloneSource absent — even if parent_study_id is set.
  it('(c) omits the banner when cloneSource is absent (even if parent_study_id set)', () => {
    mockBackend();
    const noBannerPrefill: PrefillValues = { ...CLONE_PREFILL };
    delete noBannerPrefill.cloneSource;
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} initialValues={noBannerPrefill} />);
    expect(screen.queryByTestId('cloned-from-banner')).toBeNull();
  });

  // (c) Banner absent in the no-prefill case (existing "New study" flow).
  it('(c) omits the banner when no initialValues is passed', () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    expect(screen.queryByTestId('cloned-from-banner')).toBeNull();
  });

  // (a) + (e) Serializer hygiene: parent_study_id in payload; cloneSource excluded.
  it('(a) POST body carries parent_study_id AND has no cloneSource own property', async () => {
    const { postBodies } = mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} initialValues={CLONE_PREFILL} />);
    await walkToFinalStep();
    fireEvent.click(screen.getByTestId('step-next'));
    await waitFor(() => expect(screen.getByTestId('step-5')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /Create study/i }));

    await waitFor(() => expect(postBodies.length).toBeGreaterThan(0));
    const payload = postBodies[0]!;
    expect(payload).toHaveProperty('parent_study_id', CLONE_SOURCE_ID);
    // hasOwnProperty catches both `cloneSource: {…}` AND `cloneSource: undefined`
    // leaks from a stray ...initialValues spread (D-12).
    expect(Object.prototype.hasOwnProperty.call(payload, 'cloneSource')).toBe(false);
  });

  // (d) Regression: modal still works when no lineage / no prefill set.
  it('(d) POST body omits both lineage fields when initialValues is undefined', async () => {
    const { postBodies } = mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    await walkToFinalStep();
    fireEvent.change(screen.getByLabelText('Study name'), {
      target: { value: 'manual-no-lineage' },
    });
    fireEvent.click(screen.getByTestId('step-next'));
    await waitFor(() => expect(screen.getByTestId('step-5')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /Create study/i }));

    await waitFor(() => expect(postBodies.length).toBeGreaterThan(0));
    const payload = postBodies[0]!;
    expect('parent' in payload).toBe(false);
    expect('parent_study_id' in payload).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(payload, 'cloneSource')).toBe(false);
  });

  // (g) Regression: proposal-followup `parent` lineage preserved through the serializer.
  it('(g) POST body preserves parent {proposal_id, followup_index} when set (regression guard)', async () => {
    const { postBodies } = mockBackend();
    const followupOnly: PrefillValues = {
      ...CLONE_PREFILL,
      parent: { proposal_id: PROPOSAL_ID, followup_index: 0 },
    };
    delete followupOnly.parent_study_id;
    delete followupOnly.cloneSource;
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} initialValues={followupOnly} />);
    await walkToFinalStep();
    fireEvent.click(screen.getByTestId('step-next'));
    await waitFor(() => expect(screen.getByTestId('step-5')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /Create study/i }));

    await waitFor(() => expect(postBodies.length).toBeGreaterThan(0));
    const payload = postBodies[0]!;
    expect(payload.parent).toEqual({ proposal_id: PROPOSAL_ID, followup_index: 0 });
    expect('parent_study_id' in payload).toBe(false);
  });

  // (h) Both lineage axes set simultaneously: parent + parent_study_id; cloneSource excluded.
  it('(h) POST body carries BOTH parent and parent_study_id when both lineage axes are set', async () => {
    const { postBodies } = mockBackend();
    const bothPrefill: PrefillValues = {
      ...CLONE_PREFILL,
      parent: { proposal_id: PROPOSAL_ID, followup_index: 2 },
    };
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} initialValues={bothPrefill} />);
    await walkToFinalStep();
    fireEvent.click(screen.getByTestId('step-next'));
    await waitFor(() => expect(screen.getByTestId('step-5')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /Create study/i }));

    await waitFor(() => expect(postBodies.length).toBeGreaterThan(0));
    const payload = postBodies[0]!;
    expect(payload.parent).toEqual({ proposal_id: PROPOSAL_ID, followup_index: 2 });
    expect(payload.parent_study_id).toBe(CLONE_SOURCE_ID);
    expect(Object.prototype.hasOwnProperty.call(payload, 'cloneSource')).toBe(false);
  });
});
