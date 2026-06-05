// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api-errors';

const pairingMock = vi.fn();
const studyMock = vi.fn();
const digestMock = vi.fn();
const trialsMock = vi.fn();
const clusterMock = vi.fn();

vi.mock('@/lib/api/studies', () => ({
  useStudyComparePairing: (...a: unknown[]) => pairingMock(...a),
  useStudy: (id: string) => studyMock(id),
  useStudyTrials: () => trialsMock(),
}));
vi.mock('@/lib/api/digests', () => ({
  useStudyDigest: (id: string) => digestMock(id),
}));
vi.mock('@/lib/api/clusters', () => ({
  useCluster: (id: string) => clusterMock(id),
}));
vi.mock('@/lib/demo-data', () => ({ isDemoSyntheticUbiClusterName: () => false }));

import { StudyComparisonPage } from '@/components/studies/study-comparison-page';

function ok<T>(data: T) {
  return { data, isError: false, error: null };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('StudyComparisonPage (FR-3)', () => {
  it('AC-18: reversed URL order still renders LLM left / UBI right', () => {
    // a is the UBI study, b is the LLM study (reversed).
    pairingMock.mockReturnValue(
      ok({
        a_study_id: 'A',
        b_study_id: 'B',
        a_kind: 'ubi',
        b_kind: 'llm',
        query_set_id: 'qs',
        warnings: [],
      }),
    );
    studyMock.mockImplementation((id: string) =>
      ok({
        id,
        best_metric: id === 'A' ? 0.9 : 0.1,
        objective: { direction: 'maximize' },
        cluster_id: `c-${id}`,
        convergence: null,
        confidence: null,
      }),
    );
    digestMock.mockImplementation((id: string) =>
      ok({ narrative: `n-${id}`, recommended_config: {} }),
    );
    trialsMock.mockReturnValue(ok({ data: [] }));
    clusterMock.mockImplementation((id: string) => ok({ name: id }));

    render(<StudyComparisonPage a="A" b="B" />);
    // LLM column = the llm-kind study (B, metric 0.1); UBI column = A (0.9).
    expect(screen.getByTestId('compare-best-metric-llm')).toHaveTextContent('0.100');
    expect(screen.getByTestId('compare-best-metric-ubi')).toHaveTextContent('0.900');
  });

  it('renders the keyed error state on a pairing failure', () => {
    pairingMock.mockReturnValue({
      data: undefined,
      isError: true,
      error: new ApiError({
        status: 422,
        errorCode: 'COMPARE_NOT_LLM_UBI_PAIR',
        message: 'comparison requires exactly one LLM and one UBI study',
        retryable: false,
      }),
    });
    studyMock.mockReturnValue(ok(undefined));
    digestMock.mockReturnValue(ok(undefined));
    trialsMock.mockReturnValue(ok({ data: [] }));
    clusterMock.mockReturnValue(ok(undefined));

    render(<StudyComparisonPage a="A" b="B" />);
    const err = screen.getByTestId('compare-error-state');
    expect(err).toHaveTextContent('COMPARE_NOT_LLM_UBI_PAIR');
    expect(err).toHaveTextContent('exactly one LLM and one UBI');
  });

  it('renders the warning banner for a CROSS_CLUSTER pairing', () => {
    pairingMock.mockReturnValue(
      ok({
        a_study_id: 'A',
        b_study_id: 'B',
        a_kind: 'llm',
        b_kind: 'ubi',
        query_set_id: 'qs',
        warnings: [{ code: 'CROSS_CLUSTER', message: 'different clusters' }],
      }),
    );
    studyMock.mockImplementation((id: string) =>
      ok({
        id,
        best_metric: 0.5,
        objective: { direction: 'maximize' },
        cluster_id: `c-${id}`,
        convergence: null,
        confidence: null,
      }),
    );
    digestMock.mockReturnValue(ok({ narrative: 'n', recommended_config: {} }));
    trialsMock.mockReturnValue(ok({ data: [] }));
    clusterMock.mockReturnValue(ok({ name: 'demo' }));

    render(<StudyComparisonPage a="A" b="B" />);
    expect(screen.getByTestId('compare-warning-banner')).toBeInTheDocument();
    expect(screen.getByTestId('compare-warning-CROSS_CLUSTER')).toBeInTheDocument();
  });
});
