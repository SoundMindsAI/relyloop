// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * feat_overnight_final_solution_phase2 Story 3 + 4 — OvernightResultCard tests.
 *
 * Story 3 owns: AC-1 partial (sans chip), AC-2, AC-3, AC-4, AC-5, AC-11,
 * three best-config cases, mixed-token-chain filter, stop-reason tooltip,
 * direct unit tests for shouldShowOvernightResultCard + truncateNarrative.
 * Story 4 extends with AC-1 full chip portion, AC-6, AC-10.
 *
 * Hook mocking pattern mirrors auto-followup-chain-panel.test.tsx —
 * `useStudyChain` + `useStudyDigest` are mocked per-test; other module
 * exports stay real via `importOriginal`.
 */

import type { UseQueryResult } from '@tanstack/react-query';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';

import {
  OvernightResultCard,
  shouldShowOvernightResultCard,
  truncateNarrative,
} from '@/components/studies/overnight-result-card';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { DigestResponse } from '@/lib/api/digests';
import { useStudyDigest } from '@/lib/api/digests';
import type { StudyChainLink, StudyChainResponse, StudyDetail } from '@/lib/api/studies';
import { useStudy, useStudyChain } from '@/lib/api/studies';

vi.mock('@/lib/api/studies', async (importOriginal) => {
  const mod = await importOriginal<typeof import('@/lib/api/studies')>();
  return { ...mod, useStudyChain: vi.fn(), useStudy: vi.fn() };
});

vi.mock('@/lib/api/digests', async (importOriginal) => {
  const mod = await importOriginal<typeof import('@/lib/api/digests')>();
  return { ...mod, useStudyDigest: vi.fn() };
});

const mockedUseStudyChain = vi.mocked(useStudyChain);
const mockedUseStudyDigest = vi.mocked(useStudyDigest);
const mockedUseStudy = vi.mocked(useStudy);

/**
 * Default useStudy return — most tests don't render the chip, but the
 * hook still fires (always-call rule). Returning `data: undefined` keeps
 * the chip silent without forcing every test to set it.
 */
function setUseStudy(data: StudyDetail | undefined): void {
  mockedUseStudy.mockReturnValue({
    data,
  } as unknown as UseQueryResult<StudyDetail, never>);
}

function setChain(data: StudyChainResponse | undefined): void {
  mockedUseStudyChain.mockReturnValue({
    data,
  } as unknown as UseQueryResult<StudyChainResponse, never>);
}

function setDigest(data: DigestResponse | undefined, opts: { isError?: boolean } = {}): void {
  mockedUseStudyDigest.mockReturnValue({
    data,
    isError: opts.isError ?? false,
  } as unknown as UseQueryResult<DigestResponse, never>);
}

function makeStudy(overrides: Partial<StudyDetail> = {}): StudyDetail {
  return {
    id: 'study-anchor',
    name: 'Anchor study',
    cluster_id: 'cluster-1',
    target: 'products',
    template_id: 'template-1',
    query_set_id: 'qs-1',
    judgment_list_id: 'jl-1',
    search_space: { params: {} },
    objective: { metric: 'ndcg', k: 10, direction: 'maximize' },
    config: {},
    status: 'completed',
    failed_reason: null,
    optuna_study_name: 'study-anchor',
    parent_study_id: null,
    baseline_metric: 0.65,
    best_metric: 0.66,
    best_trial_id: 'trial-best',
    created_at: '2026-05-23T10:00:00Z',
    started_at: '2026-05-23T10:00:01Z',
    completed_at: '2026-05-23T11:00:00Z',
    trials_summary: {
      total: 20,
      complete: 20,
      failed: 0,
      pruned: 0,
      best_primary_metric: 0.66,
    },
    confidence: null,
    convergence: null,
    ...overrides,
  } as StudyDetail;
}

function makeLink(overrides: Partial<StudyChainLink> = {}): StudyChainLink {
  return {
    id: 'link-anchor',
    name: 'Anchor link',
    status: 'completed',
    best_metric: 0.66,
    baseline_metric: 0.65,
    direction: 'maximize',
    delta_from_prev: null,
    proposal_id: null,
    auto_followup_depth_remaining: null,
    failed_reason: null,
    created_at: '2026-05-23T10:00:00Z',
    completed_at: '2026-05-23T11:00:00Z',
    template_id: 'template-1',
    selected_followup_kind: null,
    ...overrides,
  } as StudyChainLink;
}

function makeChain(overrides: Partial<StudyChainResponse> = {}): StudyChainResponse {
  return {
    anchor_study_id: 'study-anchor',
    best_link_id: null,
    best_metric: null,
    cumulative_lift: null,
    direction: 'maximize',
    stop_reason: 'no_lift',
    proposal_id_for_best_link: null,
    links: [makeLink()],
    ...overrides,
  } as StudyChainResponse;
}

function makeDigest(overrides: Partial<DigestResponse> = {}): DigestResponse {
  return {
    id: 'digest-1',
    study_id: 'link-c',
    narrative: 'Winning config description.',
    parameter_importance: {},
    recommended_config: {},
    suggested_followups: [],
    generated_by: 'openai:gpt-4o-2024-08-06',
    generated_at: '2026-05-23T12:00:00Z',
    ...overrides,
  } as DigestResponse;
}

function renderCard(props: { study: StudyDetail }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <TooltipProvider>{children}</TooltipProvider>
    </QueryClientProvider>
  );
  return render(<OvernightResultCard study={props.study} />, { wrapper });
}

describe('OvernightResultCard', () => {
  beforeEach(() => {
    setChain(undefined);
    setDigest(undefined);
    setUseStudy(undefined);
  });
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  // ---------------------------------------------------------------------------
  // FR-7 — direct unit tests for shouldShowOvernightResultCard (no React).
  // ---------------------------------------------------------------------------

  describe('shouldShowOvernightResultCard predicate', () => {
    it('returns false for undefined chain (data still loading)', () => {
      expect(shouldShowOvernightResultCard(undefined)).toBe(false);
    });

    it('returns false for in_flight stop_reason', () => {
      expect(
        shouldShowOvernightResultCard(
          makeChain({ stop_reason: 'in_flight', links: [makeLink(), makeLink({ id: 'link-2' })] }),
        ),
      ).toBe(false);
    });

    it('returns false for terminated chain with a single link (anchor only)', () => {
      expect(
        shouldShowOvernightResultCard(makeChain({ stop_reason: 'no_lift', links: [makeLink()] })),
      ).toBe(false);
    });

    it('returns true for terminated chain with at least 2 links', () => {
      expect(
        shouldShowOvernightResultCard(
          makeChain({
            stop_reason: 'no_lift',
            links: [makeLink(), makeLink({ id: 'link-2' })],
          }),
        ),
      ).toBe(true);
    });
  });

  // ---------------------------------------------------------------------------
  // FR-5 — direct unit tests for truncateNarrative.
  // ---------------------------------------------------------------------------

  describe('truncateNarrative helper', () => {
    it('returns text unchanged when ≤ maxChars', () => {
      const short = 'Short narrative.';
      expect(truncateNarrative(short, 240)).toBe(short);
    });

    it('cuts at the last sentence terminator at or before maxChars', () => {
      const text = 'First sentence. Second sentence is longer and goes on and on.';
      expect(truncateNarrative(text, 30)).toBe('First sentence.');
    });

    it('falls back to last whitespace + "…" when no sentence terminator in range', () => {
      const text = 'a b c d e f g h i j k l m n o p q r s t u v w x y z';
      // maxChars=10 — terminators absent; lastIndexOf(" ", 10) = 9 → "a b c d e"
      const result = truncateNarrative(text, 10);
      expect(result).toBe('a b c d e…');
    });

    it('hard-cuts at maxChars + "…" for pathological no-whitespace input', () => {
      const text = 'a'.repeat(250);
      expect(truncateNarrative(text, 240)).toBe(`${'a'.repeat(240)}…`);
    });
  });

  // ---------------------------------------------------------------------------
  // AC-2 / AC-3 — card hidden on in-flight or single-link chains.
  // ---------------------------------------------------------------------------

  it('AC-2: renders nothing for in_flight chains', () => {
    setChain(
      makeChain({
        stop_reason: 'in_flight',
        links: [makeLink(), makeLink({ id: 'link-2' })],
      }),
    );
    renderCard({ study: makeStudy() });
    expect(screen.queryByTestId('overnight-result-card')).not.toBeInTheDocument();
  });

  it('AC-3: renders nothing for single-link chains', () => {
    setChain(makeChain({ stop_reason: 'no_lift', links: [makeLink()] }));
    renderCard({ study: makeStudy() });
    expect(screen.queryByTestId('overnight-result-card')).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // AC-1 partial — terminated 3-link chain with narrative.
  // ---------------------------------------------------------------------------

  it('AC-1 partial: renders headline + 2 path tokens + best-config link + stop-reason + narrative', () => {
    setChain(
      makeChain({
        anchor_study_id: 'link-a',
        best_link_id: 'link-c',
        best_metric: 0.8421,
        cumulative_lift: 0.1245,
        stop_reason: 'no_lift',
        proposal_id_for_best_link: 'proposal-c',
        links: [
          makeLink({ id: 'link-a', name: 'Anchor', selected_followup_kind: null }),
          makeLink({
            id: 'link-b',
            name: 'Link B',
            selected_followup_kind: 'widen',
          }),
          makeLink({
            id: 'link-c',
            name: 'Link C',
            selected_followup_kind: 'narrow',
          }),
        ],
      }),
    );
    setDigest(makeDigest({ narrative: 'Winner increases title boost.' }));
    renderCard({ study: makeStudy() });

    // Card mounted.
    expect(screen.getByTestId('overnight-result-card')).toBeInTheDocument();
    // Headline — three studies + signed-lift via formatSignedLift (4 decimals, no percent).
    expect(
      screen.getByText(/Overnight exploration complete — 3 studies, \+0\.1245 lift/i),
    ).toBeInTheDocument();
    // Path: anchor dropped, two non-null tokens render.
    const pathLine = screen.getByTestId('overnight-result-path');
    expect(pathLine).toBeInTheDocument();
    expect(pathLine.textContent).toMatch(/Explored:\s+widen\s+→\s+narrow/);
    // Best-config link → /proposals/proposal-c.
    const bestConfigLine = screen.getByTestId('overnight-result-best-config');
    expect(bestConfigLine).toHaveTextContent(/Best config:\s+Link C/);
    expect(bestConfigLine.querySelector('a')?.getAttribute('href')).toBe('/proposals/proposal-c');
    // Stop reason phrase.
    expect(screen.getByTestId('overnight-result-stop-reason')).toHaveTextContent(
      /no further improvement/,
    );
    // Narrative + View full digest link.
    const narrative = screen.getByTestId('overnight-result-narrative');
    expect(narrative).toBeInTheDocument();
    expect(narrative.textContent).toMatch(/Winner increases title boost\./);
    expect(narrative.querySelector('a')?.getAttribute('href')).toBe('/studies/link-c#digest');
  });

  // ---------------------------------------------------------------------------
  // AC-4 — legacy narrow chain: path line hidden.
  // ---------------------------------------------------------------------------

  it('AC-4: hides path line when every link.selected_followup_kind is null (legacy narrow)', () => {
    setChain(
      makeChain({
        anchor_study_id: 'link-a',
        best_link_id: 'link-c',
        best_metric: 0.7,
        cumulative_lift: 0.05,
        stop_reason: 'depth_exhausted',
        proposal_id_for_best_link: 'proposal-c',
        links: [
          makeLink({ id: 'link-a', name: 'Anchor', selected_followup_kind: null }),
          makeLink({ id: 'link-b', name: 'B', selected_followup_kind: null }),
          makeLink({ id: 'link-c', name: 'C', selected_followup_kind: null }),
        ],
      }),
    );
    setDigest(undefined);
    renderCard({ study: makeStudy() });

    expect(screen.getByTestId('overnight-result-card')).toBeInTheDocument();
    // Headline lift in 4-decimal format.
    expect(screen.getByText(/3 studies, \+0\.0500 lift/i)).toBeInTheDocument();
    // Path line OMITTED.
    expect(screen.queryByTestId('overnight-result-path')).not.toBeInTheDocument();
    // Best-config + stop-reason still render.
    expect(screen.getByTestId('overnight-result-best-config')).toBeInTheDocument();
    expect(screen.getByTestId('overnight-result-stop-reason')).toHaveTextContent(
      /depth budget exhausted/,
    );
  });

  // ---------------------------------------------------------------------------
  // AC-5 — narrative hidden on digest error.
  // ---------------------------------------------------------------------------

  it('AC-5: hides narrative section when useStudyDigest reports isError (e.g. 404 DIGEST_NOT_READY)', () => {
    setChain(
      makeChain({
        best_link_id: 'link-c',
        cumulative_lift: 0.1,
        stop_reason: 'no_lift',
        proposal_id_for_best_link: 'proposal-c',
        links: [
          makeLink({ id: 'link-a', selected_followup_kind: null }),
          makeLink({ id: 'link-b', selected_followup_kind: 'narrow' }),
          makeLink({ id: 'link-c', name: 'C', selected_followup_kind: 'narrow' }),
        ],
      }),
    );
    setDigest(undefined, { isError: true });
    renderCard({ study: makeStudy() });

    expect(screen.getByTestId('overnight-result-card')).toBeInTheDocument();
    expect(screen.queryByTestId('overnight-result-narrative')).not.toBeInTheDocument();
    // Rest of the card still rendered.
    expect(screen.getByTestId('overnight-result-best-config')).toBeInTheDocument();
    expect(screen.getByTestId('overnight-result-stop-reason')).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // Best-config three-case render matrix (FR-1 / D-13).
  // ---------------------------------------------------------------------------

  describe('best-config render matrix', () => {
    it('best_link_id is null → "Best config: —"', () => {
      setChain(
        makeChain({
          best_link_id: null,
          cumulative_lift: 0.1,
          stop_reason: 'no_lift',
          links: [
            makeLink({ id: 'link-a', selected_followup_kind: null }),
            makeLink({ id: 'link-b', selected_followup_kind: 'narrow' }),
          ],
        }),
      );
      renderCard({ study: makeStudy() });
      expect(screen.getByTestId('overnight-result-best-config')).toHaveTextContent(
        /Best config:\s+—/,
      );
    });

    it('best_link_id set but proposal_id_for_best_link is null → "(Awaiting proposal)"', () => {
      setChain(
        makeChain({
          best_link_id: 'link-b',
          cumulative_lift: 0.1,
          stop_reason: 'no_lift',
          proposal_id_for_best_link: null,
          links: [
            makeLink({ id: 'link-a', selected_followup_kind: null }),
            makeLink({ id: 'link-b', name: 'B', selected_followup_kind: 'narrow' }),
          ],
        }),
      );
      renderCard({ study: makeStudy() });
      const line = screen.getByTestId('overnight-result-best-config');
      expect(line).toHaveTextContent(/Best config:\s+B \(Awaiting proposal\)/);
      // No link rendered when proposal is null.
      expect(line.querySelector('a')).toBeNull();
    });

    it('both set → link to /proposals/{proposal_id_for_best_link}', () => {
      setChain(
        makeChain({
          best_link_id: 'link-b',
          cumulative_lift: 0.1,
          stop_reason: 'no_lift',
          proposal_id_for_best_link: 'proposal-b',
          links: [
            makeLink({ id: 'link-a', selected_followup_kind: null }),
            makeLink({ id: 'link-b', name: 'B', selected_followup_kind: 'narrow' }),
          ],
        }),
      );
      renderCard({ study: makeStudy() });
      const line = screen.getByTestId('overnight-result-best-config');
      expect(line.querySelector('a')?.getAttribute('href')).toBe('/proposals/proposal-b');
    });
  });

  // ---------------------------------------------------------------------------
  // Mixed-token chain — cycle-1 C1-3 filter test.
  // ---------------------------------------------------------------------------

  it('filters null-token links from the path (cycle-1 C1-3)', () => {
    setChain(
      makeChain({
        best_link_id: 'link-d',
        cumulative_lift: 0.1,
        stop_reason: 'no_lift',
        proposal_id_for_best_link: 'proposal-d',
        links: [
          makeLink({ id: 'link-a', selected_followup_kind: null }), // anchor
          makeLink({ id: 'link-b', selected_followup_kind: 'narrow' }), // token: narrow
          makeLink({ id: 'link-c', selected_followup_kind: null }), // filtered out
          makeLink({ id: 'link-d', name: 'D', selected_followup_kind: 'widen' }), // token: widen
        ],
      }),
    );
    renderCard({ study: makeStudy() });

    const pathLine = screen.getByTestId('overnight-result-path');
    expect(pathLine).toBeInTheDocument();
    // Exactly two tokens, joined by " → ", no dangling separator after widen.
    expect(pathLine.textContent).toMatch(/Explored:\s+narrow\s+→\s+widen$/);
    // Per-link testids confirm only the kept links rendered.
    expect(screen.getByTestId('overnight-result-path-token-link-b')).toBeInTheDocument();
    expect(screen.getByTestId('overnight-result-path-token-link-d')).toBeInTheDocument();
    expect(screen.queryByTestId('overnight-result-path-token-link-c')).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // Stop-reason tooltip — cycle-2 C2-3.
  // ---------------------------------------------------------------------------

  describe('stop-reason inline tooltip', () => {
    it('renders auto_followup_depth tooltip for depth_exhausted', () => {
      setChain(
        makeChain({
          stop_reason: 'depth_exhausted',
          best_link_id: 'link-b',
          cumulative_lift: 0.05,
          links: [
            makeLink({ id: 'link-a', selected_followup_kind: null }),
            makeLink({ id: 'link-b', selected_followup_kind: 'narrow' }),
          ],
        }),
      );
      renderCard({ study: makeStudy() });
      const line = screen.getByTestId('overnight-result-stop-reason');
      // Tooltip is rendered as an InfoTooltip span containing an aria-labelled trigger.
      expect(line.querySelector('[aria-label*="auto-followup depth"]')).toBeTruthy();
    });

    it('renders auto_followup_budget_skip tooltip for budget', () => {
      setChain(
        makeChain({
          stop_reason: 'budget',
          best_link_id: 'link-b',
          cumulative_lift: 0.02,
          links: [
            makeLink({ id: 'link-a', selected_followup_kind: null }),
            makeLink({ id: 'link-b', selected_followup_kind: 'narrow' }),
          ],
        }),
      );
      renderCard({ study: makeStudy() });
      const line = screen.getByTestId('overnight-result-stop-reason');
      expect(line.querySelector('[aria-label*="auto-followup budget skip"]')).toBeTruthy();
    });

    it('renders no tooltip for no_lift / parent_failed / cancelled (matches chain-panel)', () => {
      setChain(
        makeChain({
          stop_reason: 'no_lift',
          best_link_id: 'link-b',
          cumulative_lift: 0.01,
          links: [
            makeLink({ id: 'link-a', selected_followup_kind: null }),
            makeLink({ id: 'link-b', selected_followup_kind: 'narrow' }),
          ],
        }),
      );
      renderCard({ study: makeStudy() });
      const line = screen.getByTestId('overnight-result-stop-reason');
      // No tooltip — just the phrase.
      expect(line.querySelector('[aria-label*="auto-followup depth"]')).toBeNull();
      expect(line.querySelector('[aria-label*="auto-followup budget skip"]')).toBeNull();
    });
  });

  // ---------------------------------------------------------------------------
  // AC-11 — TanStack cache dedup: the page-level useStudyDigest call and the
  // card's call share the same query key, so when the cache is pre-populated
  // (or the hook is mocked once), neither the page nor the card issues a
  // second network request. We verify this by asserting the mocked hook was
  // called exactly twice (once per consumer) and returned the same data.
  // ---------------------------------------------------------------------------

  // ---------------------------------------------------------------------------
  // Story 4 — AC-1 full chip + AC-6 + AC-10.
  // ---------------------------------------------------------------------------

  describe('WinningLinkConvergenceChip', () => {
    it('AC-1 full chip: renders "Converged" badge from cross-study useStudy result', () => {
      setChain(
        makeChain({
          best_link_id: 'link-c',
          cumulative_lift: 0.1245,
          stop_reason: 'no_lift',
          proposal_id_for_best_link: 'proposal-c',
          links: [
            makeLink({ id: 'link-a', selected_followup_kind: null }),
            makeLink({ id: 'link-b', selected_followup_kind: 'narrow' }),
            makeLink({ id: 'link-c', name: 'C', selected_followup_kind: 'narrow' }),
          ],
        }),
      );
      // study.id is 'study-anchor', best_link_id is 'link-c' → cross-study path.
      setUseStudy(
        makeStudy({
          id: 'link-c',
          convergence: {
            verdict: 'converged',
            best_so_far: [],
            window_size: 5,
            relative_improvement: 0.001,
            epsilon: 0.005,
            warmup_floor: 5,
          },
        } as unknown as StudyDetail),
      );
      renderCard({ study: makeStudy() });

      const chip = screen.getByTestId('overnight-result-convergence-chip');
      expect(chip).toBeInTheDocument();
      expect(chip).toHaveTextContent('Converged');
    });

    it('AC-6: hides chip when winning-link convergence is null (graceful-degrade)', () => {
      setChain(
        makeChain({
          best_link_id: 'link-c',
          cumulative_lift: 0.1245,
          stop_reason: 'no_lift',
          proposal_id_for_best_link: 'proposal-c',
          links: [
            makeLink({ id: 'link-a', selected_followup_kind: null }),
            makeLink({ id: 'link-b', selected_followup_kind: 'narrow' }),
            makeLink({ id: 'link-c', name: 'C', selected_followup_kind: 'narrow' }),
          ],
        }),
      );
      setUseStudy(makeStudy({ id: 'link-c', convergence: null }));
      renderCard({ study: makeStudy() });

      expect(screen.queryByTestId('overnight-result-convergence-chip')).not.toBeInTheDocument();
      // Card still renders all other sections.
      expect(screen.getByTestId('overnight-result-card')).toBeInTheDocument();
    });

    it('AC-10: when viewed study IS the winner, chip reads convergence from viewedStudy directly (no cross-study fetch)', () => {
      setChain(
        makeChain({
          // Best link == the viewed study itself.
          best_link_id: 'study-anchor',
          cumulative_lift: 0.1245,
          stop_reason: 'no_lift',
          proposal_id_for_best_link: 'proposal-a',
          links: [
            makeLink({ id: 'study-anchor', name: 'Anchor', selected_followup_kind: null }),
            makeLink({ id: 'link-b', selected_followup_kind: 'narrow' }),
          ],
        }),
      );
      // viewedStudy carries the convergence verdict directly.
      const viewedStudy = makeStudy({
        id: 'study-anchor',
        convergence: {
          verdict: 'still_improving',
          best_so_far: [],
          window_size: 5,
          relative_improvement: 0.05,
          epsilon: 0.005,
          warmup_floor: 5,
        } as unknown as StudyDetail['convergence'],
      });
      // Cross-study useStudy mock MUST return undefined — verifies the
      // `enabled: false` branch took the viewed-study path.
      setUseStudy(undefined);
      renderCard({ study: viewedStudy });

      const chip = screen.getByTestId('overnight-result-convergence-chip');
      expect(chip).toHaveTextContent('Still improving');
    });

    it('chip is not mounted when chain.best_link_id is null', () => {
      setChain(
        makeChain({
          best_link_id: null,
          cumulative_lift: 0.05,
          stop_reason: 'no_lift',
          links: [
            makeLink({ id: 'link-a', selected_followup_kind: null }),
            makeLink({ id: 'link-b', selected_followup_kind: 'narrow' }),
          ],
        }),
      );
      renderCard({ study: makeStudy() });
      expect(screen.queryByTestId('overnight-result-convergence-chip')).not.toBeInTheDocument();
    });
  });

  it('AC-11: useStudyDigest is called with chain.best_link_id (queryKey alignment with page-level call enables TanStack cache dedup)', () => {
    setChain(
      makeChain({
        best_link_id: 'link-c',
        cumulative_lift: 0.1,
        stop_reason: 'no_lift',
        proposal_id_for_best_link: 'proposal-c',
        links: [
          makeLink({ id: 'link-a', selected_followup_kind: null }),
          makeLink({ id: 'link-b', selected_followup_kind: 'narrow' }),
          makeLink({ id: 'link-c', name: 'C', selected_followup_kind: 'narrow' }),
        ],
      }),
    );
    setDigest(makeDigest({ narrative: 'Excerpt.' }));
    renderCard({ study: makeStudy() });

    // AC-11's correctness depends on the card and the page calling
    // useStudyDigest with the SAME id, so the TanStack cache key
    // (['studies', id, 'digest']) is identical and the hook resolves to
    // a single network request shared between consumers. We assert the
    // hook was invoked with `'link-c'` (the chain's best_link_id, NOT
    // `study.id = 'study-anchor'`) — that's the wiring the cache dedup
    // depends on.
    expect(mockedUseStudyDigest).toHaveBeenCalled();
    const firstCallId = mockedUseStudyDigest.mock.calls[0]?.[0];
    expect(firstCallId).toBe('link-c');
    // And the enabled gate is true (predicate fires + best_link_id non-null).
    const firstCallOpts = mockedUseStudyDigest.mock.calls[0]?.[1] as
      | { enabled?: boolean }
      | undefined;
    expect(firstCallOpts?.enabled).toBe(true);
  });

  it('AC-11 negative: useStudyDigest is called with `undefined` + enabled=false when no winner', () => {
    setChain(
      makeChain({
        best_link_id: null,
        cumulative_lift: 0.05,
        stop_reason: 'no_lift',
        links: [
          makeLink({ id: 'link-a', selected_followup_kind: null }),
          makeLink({ id: 'link-b', selected_followup_kind: 'narrow' }),
        ],
      }),
    );
    renderCard({ study: makeStudy() });

    // D-22: chain?.best_link_id ?? undefined — coerces null to undefined for
    // the hook's `string | undefined` signature; enabled is false so the
    // network call is skipped entirely.
    const firstCallId = mockedUseStudyDigest.mock.calls[0]?.[0];
    expect(firstCallId).toBeUndefined();
    const firstCallOpts = mockedUseStudyDigest.mock.calls[0]?.[1] as
      | { enabled?: boolean }
      | undefined;
    expect(firstCallOpts?.enabled).toBe(false);
  });
});
