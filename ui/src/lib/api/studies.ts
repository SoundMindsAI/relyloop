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
  q?: string | undefined;
  sort?: string | undefined;
}

export function useStudies(filter: StudiesFilter = {}): UseQueryResult<StudyListPage, ApiError> {
  const { status, cluster_id, cursor, limit, since, q, sort } = filter;
  return useQuery<StudyListPage, ApiError>({
    queryKey: ['studies', { status, cluster_id, cursor, limit, since, q, sort }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<StudyListResponse>('/api/v1/studies', {
        params: { status, cluster_id, cursor, limit, since, q, sort },
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
  /**
   * feat_digest_executable_followups Story 5.2 — gate the fetch so the
   * proposal-detail page can lazily load the parent study only when at
   * least one ``narrow``/``widen`` followup is actionable, avoiding a
   * wasteful request on proposals whose digests are all ``text`` items.
   */
  enabled?: boolean;
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
    enabled: options.enabled ?? true,
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

/**
 * Cancel-mutation argument shape (feat_auto_followup_studies Story 3.3).
 *
 * The backend's POST /api/v1/studies/{id}/cancel endpoint accepts an
 * optional `?cascade=<bool>` query param (default `true` per spec D-9).
 * When the operator opens the cancel modal on a parent that has in-flight
 * chain children, the radio lets them pick the parent-only (`cascade=false`)
 * or full-cascade (`cascade=true`) path; the mutation forwards whichever
 * the operator selected.
 *
 * Backwards-compat: callers can still pass `undefined` (or `{}`) and get
 * the default cascade=true behavior.
 */
export interface CancelStudyVars {
  cascade?: boolean;
}

export function useCancelStudy(
  id: string,
): UseMutationResult<StudyDetail, ApiError, CancelStudyVars | undefined> {
  const qc = useQueryClient();
  return useMutation<StudyDetail, ApiError, CancelStudyVars | undefined>({
    mutationFn: async (vars) => {
      const cascade = vars?.cascade ?? true;
      const { data } = await apiClient.post<StudyDetail>(
        `/api/v1/studies/${id}/cancel?cascade=${cascade}`,
        {},
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['studies', id] });
      qc.invalidateQueries({ queryKey: ['studies', id, 'trials'] });
      qc.invalidateQueries({ queryKey: ['studies', id, 'children'] });
      qc.invalidateQueries({ queryKey: ['studies'] });
    },
  });
}

/**
 * List direct child studies of a parent (feat_auto_followup_studies Story 3.1,
 * FR-10 backend).
 *
 * Hits GET /api/v1/studies/{id}/children. Returns the same StudyListResponse
 * shape as `useStudies`, but for direct children only (per D-13). Used by
 * the auto-followup chain panel on the study detail page.
 */
export function useStudyChildren(studyId: string): UseQueryResult<StudyListPage, ApiError> {
  return useQuery<StudyListPage, ApiError>({
    queryKey: ['studies', studyId, 'children'],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<StudyListResponse>(
        `/api/v1/studies/${studyId}/children`,
      );
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? data.data.length) };
    },
  });
}
