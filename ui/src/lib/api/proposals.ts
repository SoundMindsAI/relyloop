'use client';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type { ApiError } from '@/lib/api-errors';
import type { components } from '@/lib/types';

export type ProposalSummary = components['schemas']['ProposalSummary'];
export type ProposalDetail = components['schemas']['ProposalDetail'];
export type ProposalsListResponse = components['schemas']['ProposalsListResponse'];

export type ProposalsPage = ProposalsListResponse & { totalCount: number };

export interface ProposalsFilter {
  status?: string | undefined;
  cluster_id?: string | undefined;
  study_id?: string | undefined;
  cursor?: string | undefined;
  limit?: number | undefined;
}

export function useProposals(
  filter: ProposalsFilter = {},
): UseQueryResult<ProposalsPage, ApiError> {
  const { status, cluster_id, study_id, cursor, limit } = filter;
  return useQuery<ProposalsPage, ApiError>({
    queryKey: ['proposals', { status, cluster_id, study_id, cursor, limit }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<ProposalsListResponse>('/api/v1/proposals', {
        params: { status, cluster_id, study_id, cursor, limit },
      });
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
  });
}

/** Find the pending proposal for a given study (if any) — used by the Open-PR button on study detail. */
export function useProposalForStudy(
  studyId: string,
): UseQueryResult<ProposalSummary | null, ApiError> {
  return useQuery<ProposalSummary | null, ApiError>({
    queryKey: ['proposals', { study_id: studyId, status: 'pending' }, 'for-study'],
    queryFn: async () => {
      const { data } = await apiClient.get<ProposalsListResponse>('/api/v1/proposals', {
        params: { study_id: studyId, status: 'pending', limit: 1 },
      });
      return data.data[0] ?? null;
    },
    staleTime: 0,
  });
}
