/**
 * feat_study_clone_from_previous Story 2.3 — `/studies?clone_from=…` tests.
 *
 * Covers FR-4 / FR-6 / D-11 + ACs 3 / 14 / 17:
 *   (i)   no param → no fetch, no modal auto-open, no toast.
 *   (ii)  empty value → toast, router.replace, modal opens empty.
 *   (iii) garbage (non-36-char) → toast, router.replace, modal opens empty.
 *   (iv)  valid id + 200 → modal opens with prefill, router.replace clears param.
 *   (v)   valid id + 404 → toast, router.replace, modal opens empty.
 */

import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';
import { server } from '../../setup';

const API_BASE = 'http://api.test';
const VALID_SOURCE_ID = '01970000-0000-7000-8000-000000000abc';

const toastErrorMock = vi.fn();
vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), {
    error: (...args: unknown[]) => toastErrorMock(...args),
    success: vi.fn(),
  }),
  Toaster: () => null,
}));

vi.mock('@/components/ui/select', async () => {
  const { mockShadcnSelect } = await import('../../helpers/shadcn-select-mock');
  return mockShadcnSelect();
});

let lastReplace = '';
let mockedSearch = '';

vi.mock('next/navigation', () => ({
  usePathname: () => '/studies',
  useRouter: () => ({
    replace: (url: string) => {
      lastReplace = url;
    },
    push: (_url: string) => {},
  }),
  useSearchParams: () => new URLSearchParams(mockedSearch),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

beforeEach(() => {
  lastReplace = '';
  mockedSearch = '';
  toastErrorMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function seedListEndpoint() {
  server.use(
    http.get(`${API_BASE}/api/v1/studies`, () =>
      HttpResponse.json(
        { data: [], next_cursor: null, has_more: false },
        { headers: { 'X-Total-Count': '0' } },
      ),
    ),
  );
}

function seedValidSource() {
  server.use(
    // feat_study_clone_narrow_bounds Story 1.3 — the modal now calls
    // useStudyDigest unconditionally when cloneSource is set. These v1
    // page.clone tests verify the banner, not Step-4 narrow-bounds —
    // a 404 DIGEST_NOT_READY keeps the FR-1 narrow-bounds gate closed
    // and the surface invisible.
    http.get(`${API_BASE}/api/v1/studies/${VALID_SOURCE_ID}/digest`, () =>
      HttpResponse.json(
        { detail: { error_code: 'DIGEST_NOT_READY', message: 'no digest', retryable: true } },
        { status: 404 },
      ),
    ),
    http.get(`${API_BASE}/api/v1/studies/${VALID_SOURCE_ID}`, () =>
      HttpResponse.json({
        id: VALID_SOURCE_ID,
        name: 'source-study-for-clone',
        cluster_id: 'c1',
        target: 'products',
        template_id: 'tpl1',
        query_set_id: 'qs1',
        judgment_list_id: 'jl1',
        search_space: { params: { boost_title: { type: 'float', low: 1, high: 2 } } },
        objective: { metric: 'ndcg', k: 10, direction: 'maximize' },
        config: { max_trials: 200, parallelism: 4, sampler: 'tpe', pruner: 'median' },
        status: 'completed',
        failed_reason: null,
        optuna_study_name: 'source-study-for-clone',
        parent_study_id: null,
        baseline_metric: 0.4,
        best_metric: 0.55,
        best_trial_id: null,
        created_at: '2026-05-23T00:00:00Z',
        started_at: '2026-05-23T00:01:00Z',
        completed_at: '2026-05-23T00:30:00Z',
        trials_summary: {
          total: 200,
          complete: 195,
          failed: 2,
          pruned: 3,
          best_primary_metric: 0.55,
        },
      }),
    ),
  );
}

function seed404Source() {
  server.use(
    http.get(`${API_BASE}/api/v1/studies/${VALID_SOURCE_ID}`, () =>
      HttpResponse.json(
        {
          detail: {
            error_code: 'STUDY_NOT_FOUND',
            message: 'study not found',
            retryable: false,
          },
        },
        { status: 404 },
      ),
    ),
  );
}

async function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { default: StudiesPage } = await import('@/app/studies/page');
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider delayDuration={0}>
        <StudiesPage />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe('StudiesPage — ?clone_from deep-link (Story 2.3)', () => {
  it('(i) no clone_from param → no toast, no auto-open, no replace', async () => {
    mockedSearch = '';
    seedListEndpoint();
    await renderPage();
    await waitFor(() =>
      expect(screen.getByTestId('data-table-empty-no-rows-exist')).toBeInTheDocument(),
    );
    // Modal is not open: no banner, no form testids visible.
    expect(screen.queryByTestId('cloned-from-banner')).toBeNull();
    expect(screen.queryByTestId('create-study-form')).toBeNull();
    expect(toastErrorMock).not.toHaveBeenCalled();
    expect(lastReplace).toBe('');
  });

  it('(ii) ?clone_from= (empty value) → toast + replace + modal opens empty', async () => {
    mockedSearch = 'clone_from=';
    seedListEndpoint();
    await renderPage();
    await waitFor(() => expect(toastErrorMock).toHaveBeenCalledTimes(1));
    expect(toastErrorMock.mock.calls[0]![0]).toMatch(/invalid clone-from id/i);
    expect(lastReplace).toBe('/studies');
    // Modal opens but with no banner (no cloneSource).
    await waitFor(() => expect(screen.getByTestId('create-study-form')).toBeInTheDocument());
    expect(screen.queryByTestId('cloned-from-banner')).toBeNull();
  });

  it('(iii) ?clone_from=<garbage non-36-char> → toast + replace + modal opens empty', async () => {
    mockedSearch = 'clone_from=garbage';
    seedListEndpoint();
    await renderPage();
    await waitFor(() => expect(toastErrorMock).toHaveBeenCalledTimes(1));
    expect(toastErrorMock.mock.calls[0]![0]).toMatch(/invalid clone-from id/i);
    expect(lastReplace).toBe('/studies');
    await waitFor(() => expect(screen.getByTestId('create-study-form')).toBeInTheDocument());
    expect(screen.queryByTestId('cloned-from-banner')).toBeNull();
  });

  it('(iv) valid 36-char id + 200 → modal opens with prefill banner + replace clears param', async () => {
    mockedSearch = `clone_from=${VALID_SOURCE_ID}`;
    seedListEndpoint();
    seedValidSource();
    await renderPage();
    // Banner renders once the source-study fetch resolves and the effect fires.
    await waitFor(() => expect(screen.getByTestId('cloned-from-banner')).toBeInTheDocument());
    expect(screen.getByTestId('cloned-from-banner')).toHaveTextContent('source-study-for-clone');
    expect(lastReplace).toBe('/studies');
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  it('(v) valid 36-char id but 404 → toast + replace + modal opens empty', async () => {
    mockedSearch = `clone_from=${VALID_SOURCE_ID}`;
    seedListEndpoint();
    seed404Source();
    await renderPage();
    await waitFor(() => expect(toastErrorMock).toHaveBeenCalledTimes(1));
    expect(toastErrorMock.mock.calls[0]![0]).toMatch(/not found/i);
    expect(lastReplace).toBe('/studies');
    await waitFor(() => expect(screen.getByTestId('create-study-form')).toBeInTheDocument());
    expect(screen.queryByTestId('cloned-from-banner')).toBeNull();
  });

  it('(vi) on-close prefill reset — re-render with garbage does NOT carry stale prefill', async () => {
    // First render: valid id → banner appears.
    mockedSearch = `clone_from=${VALID_SOURCE_ID}`;
    seedListEndpoint();
    seedValidSource();
    const { unmount } = await renderPage();
    await waitFor(() => expect(screen.getByTestId('cloned-from-banner')).toBeInTheDocument());
    unmount();

    // Reset mocks + msw.
    server.resetHandlers();
    toastErrorMock.mockReset();
    lastReplace = '';

    // Second render: garbage param → modal opens empty, NO banner.
    mockedSearch = 'clone_from=garbage';
    seedListEndpoint();
    await renderPage();
    await waitFor(() => expect(toastErrorMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId('create-study-form')).toBeInTheDocument());
    expect(screen.queryByTestId('cloned-from-banner')).toBeNull();
    expect(lastReplace).toBe('/studies');
  });

  // Gemini PR #243 review finding #1 — when the user clicks Clone on
  // a SECOND study without closing the modal from a prior clone, the
  // one-shot useRef must re-arm so the prefill for B replaces A's.
  // Guarded by the secondary `useEffect(() => { cloneEffectFired.current = false }, [cloneFromId])`.
  it('(vii) navigation between two valid clone_from ids — second prefill replaces the first', async () => {
    const SECOND_SOURCE_ID = '01970000-0000-7000-8000-0000000def00';
    // First render: clone_from=A → banner with source A's name.
    mockedSearch = `clone_from=${VALID_SOURCE_ID}`;
    seedListEndpoint();
    seedValidSource();
    const { unmount } = await renderPage();
    await waitFor(() => expect(screen.getByTestId('cloned-from-banner')).toBeInTheDocument());
    expect(screen.getByTestId('cloned-from-banner')).toHaveTextContent('source-study-for-clone');
    unmount();

    server.resetHandlers();
    toastErrorMock.mockReset();
    lastReplace = '';

    // Second render: clone_from=B → banner with source B's name.
    // Simulates the Story 2.2 "user clicks Clone on a different study"
    // flow where the URL changes from ?clone_from=A to ?clone_from=B
    // and the page must seed the modal with B's prefill (not stale A).
    mockedSearch = `clone_from=${SECOND_SOURCE_ID}`;
    seedListEndpoint();
    server.use(
      http.get(`${API_BASE}/api/v1/studies/${SECOND_SOURCE_ID}`, () =>
        HttpResponse.json({
          id: SECOND_SOURCE_ID,
          name: 'second-source-study',
          cluster_id: 'c1',
          target: 'products',
          template_id: 'tpl1',
          query_set_id: 'qs1',
          judgment_list_id: 'jl1',
          search_space: { params: {} },
          objective: { metric: 'ndcg', k: 10, direction: 'maximize' },
          config: { max_trials: 100 },
          status: 'completed',
          failed_reason: null,
          optuna_study_name: 'second-source-study',
          parent_study_id: null,
          baseline_metric: 0.3,
          best_metric: 0.4,
          best_trial_id: null,
          created_at: '2026-05-24T00:00:00Z',
          started_at: '2026-05-24T00:01:00Z',
          completed_at: '2026-05-24T00:30:00Z',
          trials_summary: {
            total: 100,
            complete: 100,
            failed: 0,
            pruned: 0,
            best_primary_metric: 0.4,
          },
        }),
      ),
    );
    await renderPage();
    await waitFor(() => expect(screen.getByTestId('cloned-from-banner')).toBeInTheDocument());
    expect(screen.getByTestId('cloned-from-banner')).toHaveTextContent('second-source-study');
    expect(lastReplace).toBe('/studies');
  });
});
