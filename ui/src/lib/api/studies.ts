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
import type { components } from '@/lib/types';

export type StudySummary = components['schemas']['StudySummary'];
export type StudyDetail = components['schemas']['StudyDetail'];
export type StudyListResponse = components['schemas']['StudyListResponse'];
export type TrialDetail = components['schemas']['TrialDetail'];
export type TrialListResponse = components['schemas']['TrialListResponse'];
export type CreateStudyRequest = components['schemas']['CreateStudyRequest'];

/** Single-page list response augmented with the parsed `X-Total-Count` header. */
export type StudyListPage = StudyListResponse & { totalCount: number };
export type TrialListPage = TrialListResponse & { totalCount: number };

export interface StudiesFilter {
  status?: string | undefined;
  cluster_id?: string | undefined;
  cursor?: string | undefined;
  limit?: number | undefined;
  since?: string | undefined;
}

export function useStudies(filter: StudiesFilter = {}): UseQueryResult<StudyListPage, ApiError> {
  const { status, cluster_id, cursor, limit, since } = filter;
  return useQuery<StudyListPage, ApiError>({
    queryKey: ['studies', { status, cluster_id, cursor, limit, since }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<StudyListResponse>('/api/v1/studies', {
        params: { status, cluster_id, cursor, limit, since },
      });
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
  });
}

// Caller-driven polling per spec §4: callers pass either a fixed interval, a
// function form `(query) => number | false` (TanStack v5 contract), or omit
// for no polling.
type RefetchInterval<TData> =
  | number
  | false
  | ((query: { state: { data: TData | undefined } }) => number | false);

export interface UseStudyOptions {
  refetchInterval?: RefetchInterval<StudyDetail>;
}

export function useStudy(
  id: string,
  options: UseStudyOptions = {},
): UseQueryResult<StudyDetail, ApiError> {
  return useQuery<StudyDetail, ApiError>({
    queryKey: ['studies', id],
    queryFn: async () => {
      const { data } = await apiClient.get<StudyDetail>(`/api/v1/studies/${id}`);
      return data;
    },
    refetchInterval: options.refetchInterval ?? false,
  });
}

export interface StudyTrialsFilter {
  sort?: string | undefined;
  cursor?: string | undefined;
  limit?: number | undefined;
  since?: string | undefined;
  refetchInterval?: RefetchInterval<TrialListPage>;
}

export function useStudyTrials(
  studyId: string,
  filter: StudyTrialsFilter = {},
): UseQueryResult<TrialListPage, ApiError> {
  const { sort, cursor, limit, since, refetchInterval } = filter;
  return useQuery<TrialListPage, ApiError>({
    queryKey: ['studies', studyId, 'trials', { sort, cursor, limit, since }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<TrialListResponse>(
        `/api/v1/studies/${studyId}/trials`,
        { params: { sort, cursor, limit, since } },
      );
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
    refetchInterval: refetchInterval ?? false,
  });
}

export function useCreateStudy(): UseMutationResult<StudyDetail, ApiError, CreateStudyRequest> {
  const qc = useQueryClient();
  return useMutation<StudyDetail, ApiError, CreateStudyRequest>({
    mutationFn: async (payload) => {
      const { data } = await apiClient.post<StudyDetail>('/api/v1/studies', payload);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['studies'] });
    },
  });
}

export function useCancelStudy(id: string): UseMutationResult<StudyDetail, ApiError, void> {
  const qc = useQueryClient();
  return useMutation<StudyDetail, ApiError, void>({
    mutationFn: async () => {
      const { data } = await apiClient.post<StudyDetail>(`/api/v1/studies/${id}/cancel`, {});
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['studies', id] });
      qc.invalidateQueries({ queryKey: ['studies', id, 'trials'] });
      qc.invalidateQueries({ queryKey: ['studies'] });
    },
  });
}
