// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Vitest spec for ``<ResetDemoStateButton />`` after
 * ``bug_demo_reseed_fake_metric_regression`` — the button now POSTs once
 * (returns 202 immediately) and the polling hook drives the progress UI.
 *
 * Module-boundary mocks:
 *   - ``@/lib/api-client``: replace the singleton's ``post`` so each test
 *     controls the POST result.
 *   - ``@/lib/api/demo-reseed``: replace ``useDemoReseedStatus`` so tests
 *     can drive every status state without spinning up real polling.
 *   - ``@tanstack/react-query``: expose ``useQueryClient`` returning a
 *     stub whose ``invalidateQueries`` is a spy.
 *   - ``sonner``: spy on ``toast.success`` / ``toast.error`` / ``toast.info``.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api-errors';
import type { ReseedStatusResponse } from '@/lib/api/demo-reseed';

const mockPost = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiClient: {
    post: (...args: unknown[]) => mockPost(...args),
  },
}));

let mockStatusData: ReseedStatusResponse | undefined;
let mockStatusUpdatedAt = 0;
const mockPostDemoReseed = vi.fn();
vi.mock('@/lib/api/demo-reseed', () => ({
  useDemoReseedStatus: () => ({
    data: mockStatusData,
    dataUpdatedAt: mockStatusUpdatedAt,
    isLoading: mockStatusData === undefined,
    isError: false,
    refetch: vi.fn(),
  }),
  postDemoReseed: (...args: unknown[]) => mockPostDemoReseed(...args),
}));

// feat_selective_engine_startup_and_demo Story 3.1 — capability hook
// powering the reset-modal checkbox group. Returns a default snapshot
// with all three engines reachable; individual tests can override via
// `mockEnginesData`.
let mockEnginesData:
  | { engines: { engine_type: string; reachable: boolean; version?: string | null }[] }
  | undefined = {
  engines: [
    { engine_type: 'elasticsearch', reachable: true },
    { engine_type: 'opensearch', reachable: true },
    { engine_type: 'solr', reachable: true },
  ],
};
let mockEnginesError: Error | null = null;
vi.mock('@/lib/api/demo-engines', () => ({
  useDemoEnginesCapability: () => ({
    data: mockEnginesData,
    error: mockEnginesError,
    isLoading: false,
    isError: mockEnginesError != null,
  }),
}));

const mockInvalidateQueries = vi.fn();
const mockSetQueryData = vi.fn();
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({
    invalidateQueries: mockInvalidateQueries,
    setQueryData: mockSetQueryData,
  }),
}));

const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();
const mockToastInfo = vi.fn();
vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
    info: (...args: unknown[]) => mockToastInfo(...args),
  },
}));

import { ResetDemoStateButton } from '@/components/dashboard/reset-demo-state-button';

const STATUS_IDLE: ReseedStatusResponse = {
  status: 'idle',
  started_at: null,
  finished_at: null,
  scenarios_total: 0,
  scenarios_completed: 0,
  current_step: null,
  failed_reason: null,
  summary: null,
  steps: [],
  scenarios_skipped: [],
  scenarios_skipped_reasons: {},
};

const STATUS_RUNNING: ReseedStatusResponse = {
  status: 'running',
  started_at: '2026-05-27T16:50:00Z',
  finished_at: null,
  scenarios_total: 4,
  scenarios_completed: 2,
  current_step: 'seeding acme-products-prod (trial 7/12)',
  failed_reason: null,
  summary: null,
  steps: [
    'wiping demo state',
    'acme-products-prod: indexing 200 docs',
    'acme-products-prod: creating study (max_trials=12)',
    'seeding acme-products-prod (trial 7/12)',
  ],
  scenarios_skipped: [],
  scenarios_skipped_reasons: {},
};

const STATUS_COMPLETE: ReseedStatusResponse = {
  status: 'complete',
  started_at: '2026-05-27T16:50:00Z',
  finished_at: '2026-05-27T16:53:42Z',
  scenarios_total: 4,
  scenarios_completed: 4,
  current_step: null,
  failed_reason: null,
  summary: {
    clusters_created: 4,
    query_sets_created: 4,
    studies_completed: 4,
    proposals_created: 4,
    duration_ms: 217000,
  },
  steps: ['wiping demo state', 'renaming studies to tutorial names'],
  scenarios_skipped: [],
  scenarios_skipped_reasons: {},
};

// Partial completion — Solr was unreachable (e.g. running in the pr.yml backend
// job with no Solr service container). status stays 'complete'; the skip list is
// non-empty (infra_solr_ci_readiness FR-5 / AC-11).
const STATUS_COMPLETE_PARTIAL: ReseedStatusResponse = {
  status: 'complete',
  started_at: '2026-05-27T16:50:00Z',
  finished_at: '2026-05-27T16:53:42Z',
  scenarios_total: 6,
  scenarios_completed: 5,
  current_step: null,
  failed_reason: null,
  summary: {
    clusters_created: 5,
    query_sets_created: 5,
    studies_completed: 8,
    proposals_created: 8,
    duration_ms: 217000,
  },
  steps: ['wiping demo state', 'renaming studies to tutorial names'],
  scenarios_skipped: ['acme-kb-docs-solr'],
  scenarios_skipped_reasons: { 'acme-kb-docs-solr': 'unreachable' },
};

const STATUS_FAILED: ReseedStatusResponse = {
  status: 'failed',
  started_at: '2026-05-27T16:50:00Z',
  finished_at: '2026-05-27T16:51:00Z',
  scenarios_total: 4,
  scenarios_completed: 1,
  current_step: null,
  failed_reason: 'DemoSeedingError: acme/post_study: HTTP 503',
  summary: null,
  steps: ['wiping demo state', 'acme-products-prod: creating study (max_trials=12)'],
  scenarios_skipped: [],
  scenarios_skipped_reasons: {},
};

describe('<ResetDemoStateButton />', () => {
  beforeEach(() => {
    mockPost.mockReset();
    mockPostDemoReseed.mockReset();
    mockPostDemoReseed.mockResolvedValue({
      status: 'running',
      started_at: new Date().toISOString(),
      finished_at: null,
      scenarios_total: 5,
      scenarios_completed: 0,
      current_step: 'enqueued — waiting for worker',
      failed_reason: null,
      summary: null,
      steps: [],
      scenarios_skipped: [],
      scenarios_skipped_reasons: {},
    });
    mockInvalidateQueries.mockReset();
    mockInvalidateQueries.mockResolvedValue(undefined);
    mockSetQueryData.mockReset();
    mockToastSuccess.mockReset();
    mockToastError.mockReset();
    mockToastInfo.mockReset();
    mockStatusData = STATUS_IDLE;
    mockStatusUpdatedAt = 0;
    // Reset capability data to "all reachable" (the per-suite default).
    mockEnginesData = {
      engines: [
        { engine_type: 'elasticsearch', reachable: true },
        { engine_type: 'opensearch', reachable: true },
        { engine_type: 'solr', reachable: true },
      ],
    };
    mockEnginesError = null;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('clicking the trigger opens the AlertDialog in idle state', async () => {
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    expect(await screen.findByRole('alertdialog')).toBeInTheDocument();
    expect(screen.getByText('Wipe and reseed demo data?')).toBeInTheDocument();
  });

  it('Cancel closes the dialog without firing postDemoReseed', async () => {
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    await user.click(screen.getByTestId('reset-demo-state-cancel'));
    expect(mockPostDemoReseed).not.toHaveBeenCalled();
  });

  it('Confirm fires postDemoReseed exactly once with engines=null (all selected)', async () => {
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    await user.click(screen.getByTestId('reset-demo-state-confirm'));
    expect(mockPostDemoReseed).toHaveBeenCalledTimes(1);
    // All three engines reachable + selected → component passes null
    // (the back-compat sentinel) rather than the full array.
    expect(mockPostDemoReseed.mock.calls[0]?.[0]).toBeNull();
  });

  // bug_reset_demo_no_instant_feedback_poll_race
  it("Confirm seeds the poller cache with the POST's initial running status (instant feedback)", async () => {
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    await user.click(screen.getByTestId('reset-demo-state-confirm'));
    // The component must write the POST's returned status straight into the
    // ['demo-reseed','status'] cache so the running view renders without
    // waiting for a separate status round-trip (and without the start-up race).
    expect(mockSetQueryData).toHaveBeenCalledTimes(1);
    const [key, value] = mockSetQueryData.mock.calls[0] ?? [];
    expect(key).toEqual(['demo-reseed', 'status']);
    expect((value as ReseedStatusResponse).status).toBe('running');
  });

  it('Confirm is disabled + shows "Starting…" while the enqueue POST is in flight', async () => {
    // Hold the POST open so the in-flight (submitting) window is observable.
    let resolvePost: (v: ReseedStatusResponse) => void = () => {};
    mockPostDemoReseed.mockReturnValue(
      new Promise<ReseedStatusResponse>((res) => {
        resolvePost = res;
      }),
    );
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    await user.click(screen.getByTestId('reset-demo-state-confirm'));
    // Mid-flight: button shows the in-progress label and is disabled — a
    // second click can't double-fire the reseed.
    const confirm = screen.getByTestId('reset-demo-state-confirm');
    expect(confirm).toBeDisabled();
    expect(confirm.textContent).toContain('Starting…');
    await user.click(confirm); // must be a no-op while disabled / submitting
    expect(mockPostDemoReseed).toHaveBeenCalledTimes(1);
    // Resolve so the test doesn't leak a pending promise.
    resolvePost({ ...STATUS_RUNNING, status: 'running' });
  });

  it('does NOT enable polling before the POST resolves (no start-up idle race)', async () => {
    // If polling were enabled before the POST returned, the poller could read
    // `idle` and stop. Assert the cache seed (which precedes setPollingEnabled)
    // only happens after the POST resolves — never before.
    let resolvePost: (v: ReseedStatusResponse) => void = () => {};
    mockPostDemoReseed.mockReturnValue(
      new Promise<ReseedStatusResponse>((res) => {
        resolvePost = res;
      }),
    );
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    await user.click(screen.getByTestId('reset-demo-state-confirm'));
    // POST still pending → no cache seed yet.
    expect(mockSetQueryData).not.toHaveBeenCalled();
    resolvePost({ ...STATUS_RUNNING, status: 'running' });
    // After resolution the cache is seeded (microtask flush via findBy).
    await screen.findByTestId('reset-demo-state-confirm').catch(() => null);
    // The seed fires once the POST promise settles.
    await vi.waitFor(() => expect(mockSetQueryData).toHaveBeenCalledTimes(1));
  });

  it('running status: renders the worker current_step verbatim', async () => {
    // Mount in running state so the polling hook returns RUNNING on first render.
    mockStatusData = STATUS_RUNNING;
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    const progress = await screen.findByTestId('reset-demo-state-progress');
    expect(progress.textContent).toContain('seeding acme-products-prod (trial 7/12)');
    expect(progress.textContent).toContain('Scenario 2 of 4');
    expect(progress.textContent).toContain('50%');
  });

  it('complete status: fires the success toast + invalidates 4 query keys', async () => {
    mockStatusData = STATUS_COMPLETE;
    mockStatusUpdatedAt = 1234567890;
    render(<ResetDemoStateButton />);
    // Toast fires from the inline render-effect on terminal state.
    expect(mockToastSuccess).toHaveBeenCalledTimes(1);
    const successMessage = mockToastSuccess.mock.calls[0]?.[0] as string;
    expect(successMessage).toContain('4 studies');
    expect(successMessage).toContain('real metrics');
    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['clusters'] });
    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['judgment-lists'] });
    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['studies'] });
    expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: ['proposals'] });
  });

  it('failed status: fires the error toast with the failed_reason', async () => {
    mockStatusData = STATUS_FAILED;
    mockStatusUpdatedAt = 1234567890;
    render(<ResetDemoStateButton />);
    expect(mockToastError).toHaveBeenCalledTimes(1);
    const errorMessage = mockToastError.mock.calls[0]?.[0] as string;
    expect(errorMessage).toContain('DemoSeedingError');
    expect(errorMessage).toContain('HTTP 503');
  });

  it('partial-complete status: renders the skipped-engine hint + runbook link (AC-11)', async () => {
    mockStatusData = STATUS_COMPLETE_PARTIAL;
    mockStatusUpdatedAt = 1234567890;
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    const hint = await screen.findByTestId('reset-demo-state-partial');
    expect(hint).toHaveTextContent('Partial completion');
    expect(hint).toHaveTextContent('1 scenario skipped');
    expect(hint).toHaveTextContent('acme-kb-docs-solr');
    // "Why?" link points at the engine-tolerance runbook + is keyboard-focusable.
    const why = screen.getByRole('link', { name: 'Why?' });
    expect(why).toHaveAttribute('href', expect.stringContaining('demo-reseed-engine-tolerance'));
  });

  // -------------------------------------------------------------------------
  // feat_selective_engine_startup_and_demo Story 3.2 / FR-9 / AC-13.
  // Partial-completion footer splits skipped slugs by reason.
  // -------------------------------------------------------------------------

  it('partial-complete with user_excluded reason renders the "You excluded" subline', async () => {
    mockStatusData = {
      ...STATUS_COMPLETE,
      scenarios_skipped: ['news-search-staging'],
      scenarios_skipped_reasons: { 'news-search-staging': 'user_excluded' },
    };
    mockStatusUpdatedAt = 1234567890;
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    const userLine = await screen.findByTestId('reset-demo-skipped-user-excluded');
    expect(userLine).toHaveTextContent('You excluded:');
    expect(userLine).toHaveTextContent('news-search-staging');
    // Unreachable subline does NOT render when only user-excluded skips exist.
    expect(screen.queryByTestId('reset-demo-skipped-unreachable')).toBeNull();
  });

  it('partial-complete with mixed reasons renders both sublines (AC-13)', async () => {
    mockStatusData = {
      ...STATUS_COMPLETE,
      scenarios_skipped: ['news-search-staging', 'acme-kb-docs-solr'],
      scenarios_skipped_reasons: {
        'news-search-staging': 'user_excluded',
        'acme-kb-docs-solr': 'unreachable',
      },
    };
    mockStatusUpdatedAt = 1234567890;
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    const userLine = await screen.findByTestId('reset-demo-skipped-user-excluded');
    const unreachableLine = await screen.findByTestId('reset-demo-skipped-unreachable');
    expect(userLine).toHaveTextContent('news-search-staging');
    expect(unreachableLine).toHaveTextContent('acme-kb-docs-solr');
  });

  it('partial-complete with empty scenarios_skipped_reasons falls back to flat unreachable line', async () => {
    // Older Redis-cached payload before the new field landed — the field
    // defaults to {} via Pydantic's default_factory, so the frontend
    // gracefully degrades to today's flat rendering treating every slug
    // as "unreachable" (the historical reason).
    mockStatusData = {
      ...STATUS_COMPLETE,
      scenarios_skipped: ['acme-kb-docs-solr'],
      scenarios_skipped_reasons: {},
    };
    mockStatusUpdatedAt = 1234567890;
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    const unreachableLine = await screen.findByTestId('reset-demo-skipped-unreachable');
    expect(unreachableLine).toHaveTextContent('Engine unreachable:');
    expect(unreachableLine).toHaveTextContent('acme-kb-docs-solr');
    expect(screen.queryByTestId('reset-demo-skipped-user-excluded')).toBeNull();
  });

  it('non-partial complete status: does NOT render the skipped-engine hint', async () => {
    mockStatusData = STATUS_COMPLETE;
    mockStatusUpdatedAt = 1234567890;
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    expect(await screen.findByText('Demo state reset complete')).toBeInTheDocument();
    expect(screen.queryByTestId('reset-demo-state-partial')).not.toBeInTheDocument();
  });

  it('409 SEED_IN_PROGRESS shows info toast + continues polling', async () => {
    mockPostDemoReseed.mockRejectedValueOnce(
      new ApiError({
        status: 409,
        errorCode: 'SEED_IN_PROGRESS',
        message: 'A demo reseed is already running',
        retryable: true,
      }),
    );
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    await user.click(screen.getByTestId('reset-demo-state-confirm'));
    expect(mockToastInfo).toHaveBeenCalledTimes(1);
    expect(mockToastInfo.mock.calls[0]?.[0] as string).toContain('reseed is already running');
    expect(mockToastError).not.toHaveBeenCalled();
  });

  it('POST failure (non-409) shows error toast', async () => {
    mockPostDemoReseed.mockRejectedValueOnce(
      new ApiError({
        status: 503,
        errorCode: 'ARQ_POOL_UNAVAILABLE',
        message: 'Worker pool not initialized',
        retryable: true,
      }),
    );
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    await user.click(screen.getByTestId('reset-demo-state-confirm'));
    expect(mockToastError).toHaveBeenCalledTimes(1);
    expect(mockToastError.mock.calls[0]?.[0] as string).toContain('ARQ_POOL_UNAVAILABLE');
  });

  it('renders running-state title when polling reports running', async () => {
    mockStatusData = STATUS_RUNNING;
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    expect(await screen.findByText('Reseeding demo data…')).toBeInTheDocument();
  });

  it('renders complete-state title when polling reports complete', async () => {
    mockStatusData = STATUS_COMPLETE;
    mockStatusUpdatedAt = 1234567890;
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    expect(await screen.findByText('Demo state reset complete')).toBeInTheDocument();
    expect(screen.getByTestId('reset-demo-state-done')).toBeInTheDocument();
  });

  it('running status: renders the full step history as a scrolling log', async () => {
    mockStatusData = STATUS_RUNNING;
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    const list = await screen.findByTestId('reset-demo-state-log-list');
    const items = list.querySelectorAll('li');
    // One <li> per step, in order, oldest-first.
    expect(items).toHaveLength(STATUS_RUNNING.steps.length);
    expect(items[0]?.textContent).toBe('wiping demo state');
    expect(items[items.length - 1]?.textContent).toBe('seeding acme-products-prod (trial 7/12)');
    // Every step string is rendered.
    for (const step of STATUS_RUNNING.steps) {
      expect(list.textContent).toContain(step);
    }
  });

  it('idle status: omits the step-log panel when there are no steps', async () => {
    mockStatusData = STATUS_IDLE;
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    expect(await screen.findByRole('alertdialog')).toBeInTheDocument();
    expect(screen.queryByTestId('reset-demo-state-log')).toBeNull();
  });

  it('complete status: the step log remains visible after the run terminates', async () => {
    mockStatusData = STATUS_COMPLETE;
    mockStatusUpdatedAt = 1234567890;
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    const list = await screen.findByTestId('reset-demo-state-log-list');
    expect(list.querySelectorAll('li')).toHaveLength(STATUS_COMPLETE.steps.length);
    expect(list.textContent).toContain('renaming studies to tutorial names');
  });

  // -------------------------------------------------------------------------
  // feat_selective_engine_startup_and_demo Story 3.1 / FR-8.
  // Engine-selection checkbox group.
  // -------------------------------------------------------------------------

  it('Engines-to-reseed section renders a checkbox per engine type', async () => {
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    expect(await screen.findByTestId('reset-demo-state-engines')).toBeInTheDocument();
    expect(screen.getByTestId('engine-checkbox-elasticsearch')).toBeInTheDocument();
    expect(screen.getByTestId('engine-checkbox-opensearch')).toBeInTheDocument();
    expect(screen.getByTestId('engine-checkbox-solr')).toBeInTheDocument();
  });

  it('All-reachable engines default to checked + enabled (AC-10)', async () => {
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    const es = (await screen.findByTestId('engine-checkbox-elasticsearch')) as HTMLInputElement;
    const os = (await screen.findByTestId('engine-checkbox-opensearch')) as HTMLInputElement;
    const solr = (await screen.findByTestId('engine-checkbox-solr')) as HTMLInputElement;
    expect(es.checked).toBe(true);
    expect(es.disabled).toBe(false);
    expect(os.checked).toBe(true);
    expect(solr.checked).toBe(true);
  });

  it('Unreachable engine shows disabled + (unreachable) suffix (AC-10)', async () => {
    mockEnginesData = {
      engines: [
        { engine_type: 'elasticsearch', reachable: true },
        { engine_type: 'opensearch', reachable: true },
        { engine_type: 'solr', reachable: false },
      ],
    };
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    const solr = (await screen.findByTestId('engine-checkbox-solr')) as HTMLInputElement;
    expect(solr.disabled).toBe(true);
    expect(solr.checked).toBe(false);
    // The (unreachable) label suffix lives alongside the engine name.
    expect(screen.getByText('(unreachable)')).toBeInTheDocument();
  });

  it('Confirm is disabled when no engines are selected (AC-11)', async () => {
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    // Uncheck all three.
    await user.click(await screen.findByTestId('engine-checkbox-elasticsearch'));
    await user.click(await screen.findByTestId('engine-checkbox-opensearch'));
    await user.click(await screen.findByTestId('engine-checkbox-solr'));
    const confirm = screen.getByTestId('reset-demo-state-confirm');
    expect(confirm).toBeDisabled();
    expect(screen.getByTestId('reset-demo-engines-empty-hint')).toBeInTheDocument();
  });

  it('Confirm sends engines array when a subset is selected (AC-12)', async () => {
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    // Uncheck OpenSearch and Solr — only ES remains selected.
    await user.click(await screen.findByTestId('engine-checkbox-opensearch'));
    await user.click(await screen.findByTestId('engine-checkbox-solr'));
    await user.click(screen.getByTestId('reset-demo-state-confirm'));
    expect(mockPostDemoReseed).toHaveBeenCalledTimes(1);
    expect(mockPostDemoReseed.mock.calls[0]?.[0]).toEqual(['elasticsearch']);
  });

  it('Capability fetch failure falls back to all-checkboxes-enabled', async () => {
    mockEnginesData = undefined;
    mockEnginesError = new Error('Network error');
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    expect(await screen.findByTestId('reset-demo-engines-fallback')).toBeInTheDocument();
    // All three checkboxes still render and are enabled.
    const es = (await screen.findByTestId('engine-checkbox-elasticsearch')) as HTMLInputElement;
    expect(es.disabled).toBe(false);
    expect(es.checked).toBe(true);
  });

  // feat_engine_version_selection Story 3.2 / FR-9
  it('renders version annotation when capability response includes version (AC-8)', async () => {
    mockEnginesData = {
      engines: [
        { engine_type: 'elasticsearch', reachable: true, version: '9.4.1' },
        { engine_type: 'opensearch', reachable: true, version: '3.6.0' },
        { engine_type: 'solr', reachable: true, version: '10.0.0' },
      ],
    };
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    expect(await screen.findByTestId('engine-version-elasticsearch')).toHaveTextContent('— 9.4.1');
    expect(screen.getByTestId('engine-version-opensearch')).toHaveTextContent('— 3.6.0');
    expect(screen.getByTestId('engine-version-solr')).toHaveTextContent('— 10.0.0');
  });

  it('omits version annotation when version is null (AC-9)', async () => {
    mockEnginesData = {
      engines: [
        { engine_type: 'elasticsearch', reachable: true, version: '9.4.1' },
        { engine_type: 'opensearch', reachable: true, version: null },
        { engine_type: 'solr', reachable: true, version: null },
      ],
    };
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    // ES has the annotation; OS + Solr (version null) do not.
    expect(await screen.findByTestId('engine-version-elasticsearch')).toBeInTheDocument();
    expect(screen.queryByTestId('engine-version-opensearch')).toBeNull();
    expect(screen.queryByTestId('engine-version-solr')).toBeNull();
  });

  it('omits version annotation for unreachable engines (AC-9)', async () => {
    mockEnginesData = {
      engines: [
        { engine_type: 'elasticsearch', reachable: true, version: '9.4.1' },
        { engine_type: 'opensearch', reachable: true, version: '3.6.0' },
        // Solr unreachable but version field somehow populated — version
        // annotation MUST still be omitted (the "(unreachable)" suffix
        // is the only signal for an unreachable row).
        { engine_type: 'solr', reachable: false, version: '10.0.0' },
      ],
    };
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    expect(await screen.findByTestId('engine-version-elasticsearch')).toHaveTextContent('— 9.4.1');
    expect(screen.queryByTestId('engine-version-solr')).toBeNull();
    expect(screen.getByText('(unreachable)')).toBeInTheDocument();
  });
});
