// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

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
export type StudyChainResponse = components['schemas']['StudyChainResponse'];
export type StudyChainLink = components['schemas']['StudyChainLink'];

/** Single-page list response augmented with the parsed `X-Total-Count` header. */
export type StudyListPage = StudyListResponse & { totalCount: number };
export type TrialListPage = TrialListResponse & { totalCount: number };

export interface StudiesFilter {
  status?: string | undefined;
  cluster_id?: string | undefined;
  target?: string | undefined;
  cursor?: string | undefined;
  limit?: number | undefined;
  since?: string | undefined;
  q?: string | undefined;
  sort?: string | undefined;
}

export function useStudies(filter: StudiesFilter = {}): UseQueryResult<StudyListPage, ApiError> {
  const { status, cluster_id, target, cursor, limit, since, q, sort } = filter;
  return useQuery<StudyListPage, ApiError>({
    queryKey: ['studies', { status, cluster_id, target, cursor, limit, since, q, sort }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<StudyListResponse>('/api/v1/studies', {
        params: { status, cluster_id, target, cursor, limit, since, q, sort },
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
      // feat_overnight_autopilot D-10: a cancel may change the chain's tail
      // stop_reason (→ cancelled) and the completed-link subset, so the
      // rolled-up chain summary must refetch.
      qc.invalidateQueries({ queryKey: ['studies', id, 'chain'] });
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

export interface UseStudyChainOptions {
  /** Override the default D-10 refetch contract — primarily for tests. */
  refetchInterval?: number | false;
}

/**
 * Rolled-up overnight-chain summary for a study and its lineage
 * (feat_overnight_autopilot FR-3 / FR-4). Hits GET
 * /api/v1/studies/{id}/chain. The panel consumes this to render the
 * ordered link list + cumulative-lift + best-config + stop-reason rows.
 *
 * Refetch contract (D-10):
 *   - poll every 15s while the chain tail is `in_flight`;
 *   - for `no_lift` / `budget`, poll 15s only inside a 120s grace window
 *     after the tail completed (the chain may still settle), then stop;
 *   - all other stop reasons (depth_exhausted, parent_failed, cancelled)
 *     stop polling immediately;
 *   - refetch on window focus + reconnect.
 * Cancel + status-transition invalidation are wired by `useCancelStudy`
 * and a `useEffect` in the panel respectively.
 */
export function useStudyChain(
  studyId: string,
  options: UseStudyChainOptions = {},
): UseQueryResult<StudyChainResponse, ApiError> {
  return useQuery<StudyChainResponse, ApiError>({
    queryKey: ['studies', studyId, 'chain'],
    queryFn: async () => {
      const { data } = await apiClient.get<StudyChainResponse>(`/api/v1/studies/${studyId}/chain`);
      return data;
    },
    refetchInterval:
      options.refetchInterval ??
      ((query) => {
        const data = query.state.data;
        if (!data) return false;
        if (data.stop_reason === 'in_flight') return 15_000;
        if (data.stop_reason === 'no_lift' || data.stop_reason === 'budget') {
          const tail = data.links[data.links.length - 1];
          if (!tail?.completed_at) return false;
          const ageMs = Date.now() - new Date(tail.completed_at).getTime();
          return ageMs < 120_000 ? 15_000 : false;
        }
        return false;
      }),
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  });
}
