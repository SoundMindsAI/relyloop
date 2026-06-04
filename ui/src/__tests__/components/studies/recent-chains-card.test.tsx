// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * `<RecentChainsCard>` component tests
 * (feat_overnight_studies_summary_card Story 2.2).
 *
 * Covers:
 *   - AC-7: card renders rows from a fixture with correct anchor link
 *     targets; renders NOTHING on pending / error / empty.
 *   - AC-10: every stop_reason wire value maps to a friendly phrase
 *     (never a raw enum value).
 *   - AC-11: a row whose best_metric is null displays the stop-reason
 *     phrase in place of the numeric "Best <metric>: <value>" line —
 *     not "NaN" or "—".
 *   - AC-8: "Got it" calls `dismiss(maxTailCompletedAt)` with the max
 *     tail_completed_at across the rendered rows.
 *   - FR-6: BOTH InfoTooltip affordances render (`recent_chains_card`
 *     on the title + `overnight_autopilot` on the "Overnight" label).
 */

import type { UseQueryResult } from '@tanstack/react-query';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';

import { RecentChainsCard } from '@/components/studies/recent-chains-card';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useStudiesVisited } from '@/hooks/use-studies-visited';
import { useRecentChains, type RecentChainsResponse } from '@/lib/api/studies';
import { CHAIN_STOP_REASON_PHRASE } from '@/lib/chain-stop-reason';

vi.mock('@/lib/api/studies', async (importOriginal) => {
  const mod = await importOriginal<typeof import('@/lib/api/studies')>();
  return { ...mod, useRecentChains: vi.fn() };
});
vi.mock('@/hooks/use-studies-visited', () => ({
  useStudiesVisited: vi.fn(),
}));

const mockedUseRecentChains = vi.mocked(useRecentChains);
const mockedUseStudiesVisited = vi.mocked(useStudiesVisited);

function setRecentChains(result: Partial<UseQueryResult<RecentChainsResponse, never>>): void {
  mockedUseRecentChains.mockReturnValue(result as UseQueryResult<RecentChainsResponse, never>);
}

const dismissSpy = vi.fn();
function setVisited(since = '2026-06-01T00:00:00.000Z'): void {
  dismissSpy.mockReset();
  mockedUseStudiesVisited.mockReturnValue({ since, dismiss: dismissSpy });
}

function makeRow(overrides: Partial<RecentChainsResponse['data'][number]> = {}) {
  return {
    anchor_study_id: 'anchor-1',
    anchor_name: 'My anchor study',
    chain_length: 3,
    best_metric: 0.74,
    objective_metric: 'ndcg',
    cumulative_lift: 0.12,
    direction: 'maximize' as const,
    stop_reason: 'depth_exhausted' as const,
    best_link_proposal_id: null,
    tail_completed_at: '2026-06-03T10:00:00.000Z',
    ...overrides,
  };
}

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>
  );
  return render(<RecentChainsCard />, { wrapper });
}

beforeEach(() => {
  setVisited();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('<RecentChainsCard>', () => {
  it('renders nothing while pending', () => {
    setRecentChains({ isPending: true, isError: false, data: undefined });
    const { container } = renderCard();
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing on error', () => {
    setRecentChains({ isPending: false, isError: true, data: undefined });
    const { container } = renderCard();
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when data is empty', () => {
    setRecentChains({
      isPending: false,
      isError: false,
      data: { data: [], next_cursor: null, has_more: false },
    });
    const { container } = renderCard();
    expect(container.firstChild).toBeNull();
  });

  it('AC-7: renders rows with anchor link, chain length, metric line, and stop phrase', () => {
    const row = makeRow();
    setRecentChains({
      isPending: false,
      isError: false,
      data: { data: [row], next_cursor: null, has_more: false },
    });
    renderCard();

    expect(screen.getByTestId('recent-chains-card')).toBeInTheDocument();
    expect(screen.getByText('Ran while you were away')).toBeInTheDocument();
    const link = screen.getByTestId(`recent-chains-card-anchor-link-${row.anchor_study_id}`);
    expect(link).toHaveAttribute('href', `/studies/${row.anchor_study_id}`);
    expect(link).toHaveTextContent(row.anchor_name);
    expect(screen.getByText(`${row.chain_length} studies`)).toBeInTheDocument();
    // Best metric + lift formatted via shared helpers.
    expect(screen.getByText('0.7400')).toBeInTheDocument();
    expect(screen.getByText('+0.1200')).toBeInTheDocument();
    // Stop-reason phrase — NOT the raw enum value.
    expect(
      screen.getByText(`Stopped: ${CHAIN_STOP_REASON_PHRASE.depth_exhausted}`),
    ).toBeInTheDocument();
    expect(screen.queryByText('depth_exhausted')).not.toBeInTheDocument();
  });

  it('AC-10: every stop_reason wire value maps to a friendly phrase', () => {
    const wireValues = Object.keys(CHAIN_STOP_REASON_PHRASE) as Array<
      keyof typeof CHAIN_STOP_REASON_PHRASE
    >;
    expect(wireValues).toHaveLength(6);
    const rows = wireValues.map((stop, i) =>
      makeRow({
        anchor_study_id: `anchor-${i}`,
        anchor_name: `Anchor ${i}`,
        stop_reason: stop,
        // Stagger tail_completed_at so the rows aren't deduped visually.
        tail_completed_at: new Date(2026, 5, 1 + i).toISOString(),
      }),
    );
    setRecentChains({
      isPending: false,
      isError: false,
      data: { data: rows, next_cursor: null, has_more: false },
    });
    renderCard();

    for (const stop of wireValues) {
      // Every phrase MUST appear at least once. The raw wire value
      // MUST NOT — never ship a render where "no_lift" leaks to the user.
      expect(
        screen.getAllByText(new RegExp(`Stopped: ${CHAIN_STOP_REASON_PHRASE[stop]}`)).length,
      ).toBeGreaterThan(0);
      // "in_flight" never appears as a substring of a phrase, but
      // belt-and-suspenders: assert the raw underscore-form is absent.
      if (stop === 'in_flight') {
        expect(screen.queryByText('Stopped: in_flight')).not.toBeInTheDocument();
      }
    }
  });

  it('AC-11: null best_metric renders the stop phrase in place of the numeric line', () => {
    const row = makeRow({
      best_metric: null,
      cumulative_lift: null,
      stop_reason: 'parent_failed',
    });
    setRecentChains({
      isPending: false,
      isError: false,
      data: { data: [row], next_cursor: null, has_more: false },
    });
    renderCard();

    // Numeric placeholders must NOT appear (no "—", no "NaN", no "Best ndcg:").
    expect(screen.queryByText(/Best ndcg:/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Lift:/i)).not.toBeInTheDocument();
    expect(screen.queryByText('NaN')).not.toBeInTheDocument();
    // Just the phrase.
    expect(
      screen.getByText(`Stopped: ${CHAIN_STOP_REASON_PHRASE.parent_failed}`),
    ).toBeInTheDocument();
  });

  it('AC-8: "Got it" calls dismiss with the max tail_completed_at', () => {
    const rows = [
      makeRow({
        anchor_study_id: 'a-1',
        tail_completed_at: '2026-06-03T10:00:00.000Z',
      }),
      makeRow({
        anchor_study_id: 'a-2',
        anchor_name: 'Anchor 2',
        tail_completed_at: '2026-06-03T14:30:00.000Z', // newer tail
      }),
      makeRow({
        anchor_study_id: 'a-3',
        anchor_name: 'Anchor 3',
        tail_completed_at: '2026-06-02T08:00:00.000Z', // older tail
      }),
    ];
    setRecentChains({
      isPending: false,
      isError: false,
      data: { data: rows, next_cursor: null, has_more: false },
    });
    renderCard();

    fireEvent.click(screen.getByTestId('recent-chains-card-dismiss'));
    expect(dismissSpy).toHaveBeenCalledTimes(1);
    expect(dismissSpy).toHaveBeenCalledWith('2026-06-03T14:30:00.000Z');
  });

  it('FR-6: renders BOTH info affordances (recent_chains_card + overnight_autopilot)', () => {
    const row = makeRow();
    setRecentChains({
      isPending: false,
      isError: false,
      data: { data: [row], next_cursor: null, has_more: false },
    });
    renderCard();

    // Both glossary aria-labels appear (each InfoTooltip emits an
    // aria-labelled trigger), so the test asserts both keys'
    // aria-labels are present in the DOM.
    const cardAffordance = screen.getByLabelText('More information about the recent chains card');
    const overnightAffordance = screen.getByLabelText(
      'More information about the overnight autopilot',
    );
    expect(cardAffordance).toBeInTheDocument();
    expect(overnightAffordance).toBeInTheDocument();
  });
});
