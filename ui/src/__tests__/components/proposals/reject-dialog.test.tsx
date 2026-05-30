// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { http, HttpResponse, delay } from 'msw';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { type ReactNode } from 'react';

import { server } from '../../setup';
import { QueryProvider } from '@/components/providers/query-provider';
import { RejectDialog } from '@/components/proposals/reject-dialog';
import { useProposal, type ProposalDetail } from '@/lib/api/proposals';

const API_BASE = 'http://api.test';

const toastSuccessSpy = vi.fn();
const toastErrorSpy = vi.fn();

vi.mock('sonner', () => ({
  toast: {
    success: (msg: string) => toastSuccessSpy(msg),
    error: (msg: string) => toastErrorSpy(msg),
  },
}));

beforeEach(() => {
  toastSuccessSpy.mockClear();
  toastErrorSpy.mockClear();
});
afterEach(() => vi.restoreAllMocks());

function proposal(overrides: Partial<ProposalDetail> = {}): ProposalDetail {
  return {
    id: 'p1',
    study_id: null,
    study_summary: null,
    study_trial_id: null,
    cluster: { id: 'c1', name: 'prod', engine_type: 'elasticsearch', environment: 'prod' },
    template: { id: 't1', name: 'tmpl', version: 1, engine_type: 'elasticsearch' },
    config_diff: {},
    metric_delta: null,
    status: 'pending',
    pr_url: null,
    pr_state: null,
    pr_merged_at: null,
    pr_open_error: null,
    rejected_reason: null,
    digest: null,
    created_at: '2026-05-12T00:00:00Z',
    ...overrides,
  } as ProposalDetail;
}

function renderWithClient(node: ReactNode, qc?: QueryClient) {
  const client = qc ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    qc: client,
    ...render(<QueryClientProvider client={client}>{node}</QueryClientProvider>),
  };
}

describe('RejectDialog', () => {
  it('returns null when status !== pending (no Reject button rendered)', () => {
    renderWithClient(<RejectDialog proposal={proposal({ status: 'pr_opened' })} />);
    expect(screen.queryByTestId('open-reject-dialog')).not.toBeInTheDocument();
  });

  it('AC-2: happy path — reason submits, success toast fires, dialog closes', async () => {
    let postBody: unknown = null;
    server.use(
      http.post(`${API_BASE}/api/v1/proposals/p1/reject`, async ({ request }) => {
        postBody = await request.json();
        return HttpResponse.json(proposal({ status: 'rejected', rejected_reason: 'small delta' }));
      }),
    );
    renderWithClient(<RejectDialog proposal={proposal()} />);
    fireEvent.click(screen.getByTestId('open-reject-dialog'));
    await waitFor(() => expect(screen.getByTestId('reject-reason-input')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('reject-reason-input'), {
      target: { value: 'small delta' },
    });
    fireEvent.click(screen.getByTestId('confirm-reject'));
    await waitFor(() => expect(toastSuccessSpy).toHaveBeenCalledWith('Proposal rejected'));
    expect(postBody).toEqual({ reason: 'small delta' });
    // Dialog closed.
    await waitFor(() =>
      expect(screen.queryByTestId('reject-reason-input')).not.toBeInTheDocument(),
    );
  });

  it('preventDefault + disabled: dialog stays open during in-flight POST; clicking confirm twice does NOT double-submit', async () => {
    let postHits = 0;
    server.use(
      http.post(`${API_BASE}/api/v1/proposals/p1/reject`, async () => {
        postHits += 1;
        await delay(200);
        return HttpResponse.json(proposal({ status: 'rejected', rejected_reason: null }));
      }),
    );
    renderWithClient(<RejectDialog proposal={proposal()} />);
    fireEvent.click(screen.getByTestId('open-reject-dialog'));
    const confirm = await screen.findByTestId('confirm-reject');
    fireEvent.click(confirm);
    // Wait for React to flush the post-click rerender — once `reject.isPending`
    // is true the button is disabled.
    await waitFor(() => expect(screen.getByTestId('confirm-reject')).toBeDisabled());
    // Dialog is still open (preventDefault stopped the Radix auto-close).
    expect(screen.getByTestId('reject-reason-input')).toBeInTheDocument();
    // Double-click attempt during in-flight: button is disabled so onClick
    // does not fire a second time; assert only one POST landed.
    fireEvent.click(screen.getByTestId('confirm-reject'));
    await waitFor(() => expect(toastSuccessSpy).toHaveBeenCalled());
    expect(postHits).toBe(1);
  });

  it('spec §11: on 409 INVALID_STATE_TRANSITION, mutation surfaces error AND invalidates detail query → UI refetches showing pr_merged', async () => {
    let proposalGetHits = 0;
    server.use(
      http.get(`${API_BASE}/api/v1/proposals/p1`, () => {
        proposalGetHits += 1;
        if (proposalGetHits === 1) {
          return HttpResponse.json(proposal({ status: 'pending' }));
        }
        return HttpResponse.json(proposal({ status: 'pr_merged', pr_state: 'merged' }));
      }),
      http.post(`${API_BASE}/api/v1/proposals/p1/reject`, () =>
        HttpResponse.json(
          {
            detail: {
              error_code: 'INVALID_STATE_TRANSITION',
              message: "proposal is in status 'pr_merged'",
              retryable: false,
            },
          },
          { status: 409 },
        ),
      ),
    );
    function Harness() {
      const q = useProposal('p1');
      if (!q.data) return null;
      return (
        <>
          <span data-testid="harness-status">{q.data.status}</span>
          <RejectDialog proposal={q.data} />
        </>
      );
    }
    // Use the real QueryProvider so the MutationCache.onError handler (which
    // toasts via sonner) is wired. The shared QueryClient inside QueryProvider
    // is what makes the 409-fires-global-toast + invalidation behavior testable.
    render(
      <QueryProvider>
        <Harness />
      </QueryProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('harness-status')).toHaveTextContent('pending'));
    expect(proposalGetHits).toBe(1);

    fireEvent.click(screen.getByTestId('open-reject-dialog'));
    const confirm = await screen.findByTestId('confirm-reject');
    await act(async () => {
      fireEvent.click(confirm);
    });
    // 409 fires global toast (we mocked sonner).
    await waitFor(() =>
      expect(toastErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('INVALID_STATE_TRANSITION'),
      ),
    );
    // Invalidation triggered a refetch.
    await waitFor(() => expect(proposalGetHits).toBeGreaterThanOrEqual(2));
    // UI reflects the new state.
    await waitFor(() =>
      expect(screen.getByTestId('harness-status')).toHaveTextContent('pr_merged'),
    );
    // RejectDialog hides itself because status is no longer pending.
    expect(screen.queryByTestId('open-reject-dialog')).not.toBeInTheDocument();
  });
});
