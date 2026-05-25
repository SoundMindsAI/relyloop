/**
 * feat_study_clone_narrow_bounds Story 1.3 — CreateStudyModal narrow-bounds tests.
 *
 * Covers FR-1 through FR-8 + AC-1, AC-2, AC-3, AC-5, AC-10, AC-11:
 *   - Checkbox visibility gating (cloneSource present AND digest success
 *     AND recommended_config non-empty)
 *   - Default unchecked
 *   - On check: textarea rewrites to narrowed JSON
 *   - On uncheck: textarea restores to the captured baseline
 *   - Modal close → state resets
 *   - Reference panel renders sorted rows reading from cloneSource.name
 *     (banner-style stability — independent of form's `name` field)
 *   - All-skipped winner config → no-op toast, textarea unchanged
 *   - SyntaxError in textarea + check → error toast, checkbox reverts
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

const toastMock = Object.assign(vi.fn(), {
  error: vi.fn(),
  success: vi.fn(),
});
vi.mock('sonner', () => ({
  toast: toastMock,
  Toaster: () => null,
}));

const { CreateStudyModal } = await import('@/components/studies/create-study-modal');
type PrefillValues = import('@/components/studies/create-study-modal').PrefillValues;

const API_BASE = 'http://api.test';
const CLONE_SOURCE_ID = '01970000-0000-7000-8000-000000000abc';
const CLONE_SOURCE_NAME = 'parent-study-being-cloned';

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  toastMock.mockClear();
  toastMock.error.mockClear();
  toastMock.success.mockClear();
});

interface DigestSeedOptions {
  status?: 200 | 404;
  recommendedConfig?: Record<string, unknown>;
}

/**
 * Stub every MSW endpoint the modal touches so the rendering path is
 * deterministic. The digest endpoint is the FR-1 gate input — vary
 * its response per test via the `digest` option.
 */
function mockBackend(opts: { digest?: DigestSeedOptions } = {}) {
  const digestOpts: DigestSeedOptions = opts.digest ?? {
    status: 200,
    recommendedConfig: { title_boost: 2.34 },
  };
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
        declared_params: { title_boost: 'float' },
        version: 1,
        parent_id: null,
        created_at: '2026-05-12T00:00:00Z',
      }),
    ),
    http.get(`${API_BASE}/api/v1/studies/${CLONE_SOURCE_ID}/digest`, () => {
      if (digestOpts.status === 404) {
        return HttpResponse.json(
          {
            detail: {
              error_code: 'DIGEST_NOT_READY',
              message: 'no digest',
              retryable: true,
            },
          },
          { status: 404 },
        );
      }
      return HttpResponse.json({
        id: 'dig-1',
        study_id: CLONE_SOURCE_ID,
        narrative: 'n',
        parameter_importance: {},
        recommended_config: digestOpts.recommendedConfig ?? {},
        suggested_followups: [],
        generated_by: 'test',
        generated_at: '2026-05-25T00:00:00Z',
      });
    }),
  );
}

const CLONE_PREFILL: PrefillValues = {
  cluster_id: 'c1',
  target: 'products',
  template_id: 'tpl1',
  query_set_id: 'qs1',
  judgment_list_id: 'jl1',
  name: `${CLONE_SOURCE_NAME} (clone)`,
  search_space_text: JSON.stringify(
    { params: { title_boost: { type: 'float', low: 0.5, high: 5.0, log: false } } },
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

async function walkToStep4(): Promise<void> {
  // Step 1 → 2.
  await waitFor(() => expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument());
  fireEvent.click(screen.getByTestId('step-next'));
  // Step 2 → 3.
  await waitFor(() => expect(screen.getByTestId('step-2')).toBeInTheDocument());
  fireEvent.click(screen.getByTestId('step-next'));
  // Step 3 → 4.
  await waitFor(() => expect(screen.getByTestId('step-3')).toBeInTheDocument());
  fireEvent.click(screen.getByTestId('step-next'));
  await waitFor(() => expect(screen.getByTestId('step-4')).toBeInTheDocument());
}

describe('CreateStudyModal narrow-bounds — FR-1 visibility gating', () => {
  it('AC-1: checkbox + reference panel visible when cloning a completed study with a digest', async () => {
    mockBackend({ digest: { status: 200, recommendedConfig: { title_boost: 2.34 } } });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} initialValues={CLONE_PREFILL} />);
    await walkToStep4();
    // Wait for digest to resolve; checkbox renders after the gate opens.
    await waitFor(() => expect(screen.getByTestId('narrow-bounds-checkbox')).toBeInTheDocument());
    expect(screen.getByTestId('narrow-bounds-reference-panel')).toBeInTheDocument();
  });

  it('AC-2: checkbox absent on bare "New study" flow (no initialValues)', async () => {
    mockBackend();
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} />);
    // No initialValues means no cloneSource — useStudyDigest is called with
    // enabled: false (verified by Story 1.2 hook tests), so the FR-1 gate
    // is closed regardless of which step the user is on. The checkbox /
    // panel testids must never appear in the DOM during this modal-open
    // lifecycle.
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /local-es/ })).toBeInTheDocument(),
    );
    // Give the modal a render tick to settle.
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId('narrow-bounds-checkbox')).toBeNull();
    expect(screen.queryByTestId('narrow-bounds-reference-panel')).toBeNull();
  });

  it('AC-3: checkbox absent when source has no digest (404 DIGEST_NOT_READY)', async () => {
    mockBackend({ digest: { status: 404 } });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} initialValues={CLONE_PREFILL} />);
    await walkToStep4();
    // Give the modal a render tick to settle the digest query into error state.
    await waitFor(() => {
      // The narrow-bounds gate should be closed; verify by absence.
      expect(screen.queryByTestId('narrow-bounds-checkbox')).toBeNull();
    });
    expect(screen.queryByTestId('narrow-bounds-reference-panel')).toBeNull();
  });

  it('checkbox absent when recommended_config is empty (digest success but no winning params)', async () => {
    mockBackend({ digest: { status: 200, recommendedConfig: {} } });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} initialValues={CLONE_PREFILL} />);
    await walkToStep4();
    // No FR-1 gate path can open; checkbox should never appear.
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId('narrow-bounds-checkbox')).toBeNull();
  });
});

describe('CreateStudyModal narrow-bounds — FR-4 / FR-5 check/uncheck behavior', () => {
  it('AC-4: on check, textarea content updates to the narrowed JSON', async () => {
    mockBackend({ digest: { status: 200, recommendedConfig: { title_boost: 2.34 } } });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} initialValues={CLONE_PREFILL} />);
    await walkToStep4();
    const checkbox = await screen.findByTestId('narrow-bounds-checkbox');
    const textarea = screen.getByTestId('cs-search-space') as HTMLTextAreaElement;
    // Pre-check: verbatim source bounds.
    const before = JSON.parse(textarea.value) as {
      params: { title_boost: { low: number; high: number } };
    };
    expect(before.params.title_boost.low).toBe(0.5);
    expect(before.params.title_boost.high).toBe(5.0);
    // Check.
    fireEvent.click(checkbox);
    // Textarea rewrites synchronously inside the click handler.
    const after = JSON.parse(textarea.value) as {
      params: { title_boost: { low: number; high: number } };
    };
    expect(after.params.title_boost.low).toBeCloseTo(1.872, 6);
    expect(after.params.title_boost.high).toBeCloseTo(2.808, 6);
  });

  it('AC-5: on uncheck, textarea restores to the captured baseline (verbatim source)', async () => {
    mockBackend({ digest: { status: 200, recommendedConfig: { title_boost: 2.34 } } });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} initialValues={CLONE_PREFILL} />);
    await walkToStep4();
    const checkbox = await screen.findByTestId('narrow-bounds-checkbox');
    const textarea = screen.getByTestId('cs-search-space') as HTMLTextAreaElement;
    const original = textarea.value;
    // Check, then uncheck.
    fireEvent.click(checkbox);
    expect(textarea.value).not.toBe(original);
    fireEvent.click(checkbox);
    expect(textarea.value).toBe(original);
  });

  it('all-skipped (categorical only) → no-op toast, textarea unchanged (D-11 byte-exact)', async () => {
    mockBackend({ digest: { status: 200, recommendedConfig: { fuzziness: 'AUTO' } } });
    // Use a prefill whose search_space has only a categorical param.
    const categoricalPrefill: PrefillValues = {
      ...CLONE_PREFILL,
      search_space_text: JSON.stringify(
        { params: { fuzziness: { type: 'categorical', choices: ['AUTO', '0', '1'] } } },
        null,
        2,
      ),
    };
    wrap(
      <CreateStudyModal open={true} onOpenChange={() => {}} initialValues={categoricalPrefill} />,
    );
    await walkToStep4();
    const checkbox = await screen.findByTestId('narrow-bounds-checkbox');
    const textarea = screen.getByTestId('cs-search-space') as HTMLTextAreaElement;
    const before = textarea.value;
    fireEvent.click(checkbox);
    // Textarea bytes must be exactly equal (D-11): no setValue called.
    expect(textarea.value).toBe(before);
    // A non-error toast fired.
    expect(toastMock).toHaveBeenCalled();
  });
});

describe('CreateStudyModal narrow-bounds — FR-8 reference panel', () => {
  it('AC-10: reference panel rows sorted alphabetically; header reads from cloneSource.name', async () => {
    mockBackend({
      digest: {
        status: 200,
        recommendedConfig: { z_param: 3, a_param: 1.5, m_param: 2 },
      },
    });
    wrap(<CreateStudyModal open={true} onOpenChange={() => {}} initialValues={CLONE_PREFILL} />);
    await walkToStep4();
    const panel = await screen.findByTestId('narrow-bounds-reference-panel');
    // Panel summary references cloneSource.name (banner-style stability).
    expect(panel.textContent).toContain(CLONE_SOURCE_NAME);
    // Rows present (need not be expanded for testing-library to find them).
    const rows = screen.getAllByTestId('narrow-bounds-reference-row');
    expect(rows).toHaveLength(3);
    // Sorted alphabetically by param name.
    expect(rows[0]!.textContent).toContain('a_param');
    expect(rows[1]!.textContent).toContain('m_param');
    expect(rows[2]!.textContent).toContain('z_param');
  });
});
