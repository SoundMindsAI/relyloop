'use client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type { ApiError } from '@/lib/api-errors';
import type { ProposalStatus } from '@/lib/enums';
import type { components } from '@/lib/types';

export type ProposalSummary = components['schemas']['ProposalSummary'];
export type ProposalDetail = components['schemas']['ProposalDetail'];
export type ProposalsListResponse = components['schemas']['ProposalsListResponse'];
export type OpenPrResponse = components['schemas']['OpenPrResponse'];

export type ProposalsPage = ProposalsListResponse & { totalCount: number };

export interface ProposalsFilter {
  status?: ProposalStatus | undefined;
  cluster_id?: string | undefined;
  study_id?: string | undefined;
  template_id?: string | undefined;
  // ``study`` → backend filters to proposals with a study_id;
  // ``manual`` → study_id IS NULL. Omit for both. Matches the backend's
  // ProposalSourceWire Literal — values must stay in sync.
  source?: 'study' | 'manual' | undefined;
  // feat_config_repo_baseline_tracking FR-6 — `true` narrows to live-pointer
  // proposals (one per config_repo at most); `false` returns the complement;
  // omit for unfiltered.
  is_last_merged?: boolean | undefined;
  sort?: string | undefined;
  cursor?: string | undefined;
  limit?: number | undefined;
}

type RefetchInterval<TData> =
  | number
  | false
  | ((query: { state: { data: TData | undefined } }) => number | false);

export interface UseProposalsOptions {
  refetchInterval?: RefetchInterval<ProposalsPage>;
}

export function useProposals(
  filter: ProposalsFilter = {},
  options: UseProposalsOptions = {},
): UseQueryResult<ProposalsPage, ApiError> {
  const { status, cluster_id, study_id, template_id, source, is_last_merged, sort, cursor, limit } =
    filter;
  return useQuery<ProposalsPage, ApiError>({
    queryKey: [
      'proposals',
      {
        status,
        cluster_id,
        study_id,
        template_id,
        source,
        is_last_merged,
        sort,
        cursor,
        limit,
      },
    ],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<ProposalsListResponse>('/api/v1/proposals', {
        params: {
          status,
          cluster_id,
          study_id,
          template_id,
          source,
          is_last_merged,
          sort,
          cursor,
          limit,
        },
      });
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
    refetchInterval: options.refetchInterval ?? false,
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

export interface UseProposalOptions {
  refetchInterval?: RefetchInterval<ProposalDetail>;
}

export function useProposal(
  id: string,
  options: UseProposalOptions = {},
): UseQueryResult<ProposalDetail, ApiError> {
  return useQuery<ProposalDetail, ApiError>({
    queryKey: ['proposal', id],
    queryFn: async () => {
      const { data } = await apiClient.get<ProposalDetail>(`/api/v1/proposals/${id}`);
      return data;
    },
    refetchInterval: options.refetchInterval ?? false,
  });
}

export function useOpenPR(): UseMutationResult<OpenPrResponse, ApiError, string> {
  const qc = useQueryClient();
  return useMutation<OpenPrResponse, ApiError, string>({
    mutationFn: async (proposalId) => {
      const { data } = await apiClient.post<OpenPrResponse>(
        `/api/v1/proposals/${proposalId}/open_pr`,
        {},
      );
      return data;
    },
    onSettled: (_data, _err, proposalId) => {
      qc.invalidateQueries({ queryKey: ['proposal', proposalId] });
      qc.invalidateQueries({ queryKey: ['proposals'] });
    },
  });
}

export interface RejectProposalVars {
  proposalId: string;
  reason: string | null;
}

export function useRejectProposal(): UseMutationResult<
  ProposalDetail,
  ApiError,
  RejectProposalVars
> {
  const qc = useQueryClient();
  return useMutation<ProposalDetail, ApiError, RejectProposalVars>({
    mutationFn: async ({ proposalId, reason }) => {
      const { data } = await apiClient.post<ProposalDetail>(
        `/api/v1/proposals/${proposalId}/reject`,
        { reason },
      );
      return data;
    },
    onSettled: (_data, _err, { proposalId }) => {
      qc.invalidateQueries({ queryKey: ['proposal', proposalId] });
      qc.invalidateQueries({ queryKey: ['proposals'] });
    },
  });
}
