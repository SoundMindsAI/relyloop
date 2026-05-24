/**
 * Vitest spec for ``<ResetDemoStateButton />`` — covers AC-9 (dialog
 * open/close + cancel-no-POST + confirm-POSTs), AC-11 (toast wording on
 * envelope failure), and the 180s client-side timeout path.
 *
 * Module-boundary mocks (per plan §2.1 task 5):
 *   - ``@/lib/api-client``: replace the singleton's ``post`` so each test
 *     controls the resolved/rejected promise.
 *   - ``@tanstack/react-query``: expose ``useQueryClient`` returning a
 *     stub whose ``invalidateQueries`` is a spy.
 *   - ``sonner``: spy on ``toast.success`` / ``toast.error``.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

import { ApiError } from '@/lib/api-errors';

const mockPost = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiClient: {
    post: (...args: unknown[]) => mockPost(...args),
  },
}));

const mockInvalidateQueries = vi.fn();
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: mockInvalidateQueries }),
}));

const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();
vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

import { ResetDemoStateButton } from '@/components/dashboard/reset-demo-state-button';

const SUMMARY_OK = {
  clusters_created: 4,
  query_sets_created: 4,
  studies_completed: 4,
  proposals_created: 4,
  duration_ms: 7000,
};

function expectMockCalledWith(spy: Mock, ...expected: unknown[]) {
  expect(spy).toHaveBeenCalledWith(...expected);
}

describe('<ResetDemoStateButton />', () => {
  beforeEach(() => {
    mockPost.mockReset();
    mockInvalidateQueries.mockReset();
    mockInvalidateQueries.mockResolvedValue(undefined);
    mockToastSuccess.mockReset();
    mockToastError.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('AC-9: clicking the trigger opens the AlertDialog', async () => {
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    expect(await screen.findByRole('alertdialog')).toBeInTheDocument();
    expect(screen.getByText('Wipe and reseed demo data?')).toBeInTheDocument();
  });

  it('AC-9: Cancel closes the dialog without calling apiClient.post', async () => {
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    await user.click(screen.getByTestId('reset-demo-state-cancel'));
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('AC-9: Confirm posts to the reseed endpoint with an AbortSignal', async () => {
    mockPost.mockResolvedValueOnce({ data: SUMMARY_OK, headers: new Headers() });
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    await user.click(screen.getByTestId('reset-demo-state-confirm'));
    expect(mockPost).toHaveBeenCalledTimes(1);
    const [path, body, init] = mockPost.mock.calls[0] as [string, unknown, { signal: unknown }];
    expect(path).toBe('/api/v1/_test/demo/reseed');
    expect(body).toBeUndefined();
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it('AC-9: 200 success triggers toast.success and invalidates 4 query keys', async () => {
    mockPost.mockResolvedValueOnce({ data: SUMMARY_OK, headers: new Headers() });
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    await user.click(screen.getByTestId('reset-demo-state-confirm'));
    // Toast wording — must include the counts from the response body.
    expect(mockToastSuccess).toHaveBeenCalledTimes(1);
    const successMessage = mockToastSuccess.mock.calls[0]?.[0] as string;
    expect(successMessage).toContain('4 clusters');
    expect(successMessage).toContain('4 query sets');
    expect(successMessage).toContain('4 completed studies');
    // All four TanStack keys invalidated.
    expectMockCalledWith(mockInvalidateQueries, { queryKey: ['clusters'] });
    expectMockCalledWith(mockInvalidateQueries, { queryKey: ['judgment-lists'] });
    expectMockCalledWith(mockInvalidateQueries, { queryKey: ['studies'] });
    expectMockCalledWith(mockInvalidateQueries, { queryKey: ['proposals'] });
  });

  it('AC-11: 503 SEED_FAILED toast carries error code + runbook hint', async () => {
    mockPost.mockRejectedValueOnce(
      new ApiError({
        status: 503,
        errorCode: 'SEED_FAILED',
        message: 'Demo reseed failed mid-flight.',
        retryable: true,
      }),
    );
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    await user.click(screen.getByTestId('reset-demo-state-confirm'));
    expect(mockToastError).toHaveBeenCalledTimes(1);
    const errorMessage = mockToastError.mock.calls[0]?.[0] as string;
    expect(errorMessage).toContain('SEED_FAILED');
    expect(errorMessage).toContain('docker compose restart api');
    expect(mockToastSuccess).not.toHaveBeenCalled();
  });

  it('409 SEED_IN_PROGRESS surfaces the error code in the toast', async () => {
    mockPost.mockRejectedValueOnce(
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
    expect(mockToastError).toHaveBeenCalledTimes(1);
    expect(mockToastError.mock.calls[0]?.[0] as string).toContain('SEED_IN_PROGRESS');
  });

  it('non-envelope failure (REQUEST_ABORTED) shows the unreachable toast', async () => {
    mockPost.mockRejectedValueOnce(
      new ApiError({
        status: 0,
        errorCode: 'REQUEST_ABORTED',
        message: 'Request aborted by caller',
        retryable: false,
      }),
    );
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    await user.click(screen.getByTestId('reset-demo-state-confirm'));
    expect(mockToastError).toHaveBeenCalledTimes(1);
    expect(mockToastError.mock.calls[0]?.[0] as string).toBe(
      'Reseed in progress or unreachable — refresh the page in a moment.',
    );
  });

  it('apiClient SERVICE_UNAVAILABLE (status=0 network wrapper) shows unreachable toast', async () => {
    // apiClient wraps raw fetch/network failures as ApiError with
    // errorCode='SERVICE_UNAVAILABLE' and status=0. That looks like an
    // envelope failure to a naive isApiError check, but the backend
    // never produced an envelope — the request didn't arrive. Should
    // route to the unreachable toast, not the SEED_FAILED-style.
    // Per GPT-5.5 PR #228 final-review Medium #2.
    mockPost.mockRejectedValueOnce(
      new ApiError({
        status: 0,
        errorCode: 'SERVICE_UNAVAILABLE',
        message: 'Backend unreachable',
        retryable: true,
      }),
    );
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    await user.click(screen.getByTestId('reset-demo-state-confirm'));
    expect(mockToastError).toHaveBeenCalledTimes(1);
    expect(mockToastError.mock.calls[0]?.[0] as string).toBe(
      'Reseed in progress or unreachable — refresh the page in a moment.',
    );
  });

  it('non-ApiError network failure shows the unreachable toast', async () => {
    mockPost.mockRejectedValueOnce(new TypeError('Network Error'));
    const user = userEvent.setup();
    render(<ResetDemoStateButton />);
    await user.click(screen.getByTestId('reset-demo-state-trigger'));
    await user.click(screen.getByTestId('reset-demo-state-confirm'));
    expect(mockToastError).toHaveBeenCalledTimes(1);
    expect(mockToastError.mock.calls[0]?.[0] as string).toBe(
      'Reseed in progress or unreachable — refresh the page in a moment.',
    );
  });
});
