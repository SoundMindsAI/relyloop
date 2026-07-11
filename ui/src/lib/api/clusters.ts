// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import type { EntitySelectListPage } from '@/components/common/entity-select';
import { apiClient } from '@/lib/api-client';
import { isApiError, type ApiError } from '@/lib/api-errors';
import type { components } from '@/lib/types';

export type ClusterSummary = components['schemas']['ClusterSummary'];
export type ClusterDetail = components['schemas']['ClusterDetail'];
export type ClusterListResponse = components['schemas']['ClusterListResponse'];
export type CreateClusterRequest = components['schemas']['CreateClusterRequest'];
export type Schema = components['schemas']['Schema'];

/**
 * Re-export the generated TargetInfo type so frontend callers don't reach into
 * the generated `components['schemas']` namespace directly.
 * Source of truth: backend/app/adapters/protocol.py TargetInfo class.
 */
export type TargetSummary = components['schemas']['TargetInfo'];

/**
 * Shared retry predicate (FR-3 / FR-6). Short-circuits on permanent failures
 * (TARGETS_FORBIDDEN, TARGET_NOT_FOUND, CLUSTER_NOT_FOUND) where the
 * backend-supplied `retryable: false` signals retry won't help. Without
 * this, TanStack's default `retry: 3` would fire 4 GETs per misspelled
 * keystroke in manual mode or per ACL-restricted cluster pick.
 *
 * Mocking-layer note: tests asserting "exactly one call" or "up to 4 calls"
 * mock at the `apiClient.get` layer to isolate TanStack's retry from the
 * api-client's own internal 503 retry loop.
 */
function retryOnRetryableError(failureCount: number, error: unknown): boolean {
  return isApiError(error) ? Boolean(error.retryable) && failureCount < 3 : failureCount < 3;
}

export type ClusterListPage = ClusterListResponse & { totalCount: number };

export interface ClustersFilter {
  cursor?: string | undefined;
  limit?: number | undefined;
  since?: string | undefined;
  q?: string | undefined;
  sort?: string | undefined;
  engine_type?: string | undefined;
  environment?: string | undefined;
  /**
   * Passes through to TanStack Query's `enabled` option. When false, the
   * query is parked — no network request fires until it flips back to true.
   * Defaults to `true` so existing callers are unaffected.
   * Added for feat_home_first_run_demo_nudge so the dashboard banner can
   * skip the cluster fetch entirely for already-dismissed users.
   */
  enabled?: boolean | undefined;
}

export function useClusters(
  filter: ClustersFilter = {},
): UseQueryResult<ClusterListPage, ApiError> {
  const { cursor, limit, since, q, sort, engine_type, environment, enabled } = filter;
  return useQuery<ClusterListPage, ApiError>({
    queryKey: ['clusters', { cursor, limit, since, q, sort, engine_type, environment }],
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data, headers } = await apiClient.get<ClusterListResponse>('/api/v1/clusters', {
        params: { cursor, limit, since, q, sort, engine_type, environment },
      });
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
    enabled: enabled ?? true,
  });
}

export function useCluster(id: string): UseQueryResult<ClusterDetail, ApiError> {
  return useQuery<ClusterDetail, ApiError>({
    queryKey: ['clusters', id],
    queryFn: async () => {
      const { data } = await apiClient.get<ClusterDetail>(`/api/v1/clusters/${id}`);
      return data;
    },
  });
}

export function useRegisterCluster(): UseMutationResult<
  ClusterDetail,
  ApiError,
  CreateClusterRequest
> {
  const qc = useQueryClient();
  return useMutation<ClusterDetail, ApiError, CreateClusterRequest>({
    mutationFn: async (body) => {
      const { data } = await apiClient.post<ClusterDetail>('/api/v1/clusters', body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clusters'] });
    },
  });
}

export function useDeleteCluster(): UseMutationResult<void, ApiError, string> {
  const qc = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: async (clusterId) => {
      await apiClient.delete<void>(`/api/v1/clusters/${clusterId}`);
    },
    onSuccess: (_data, clusterId) => {
      // Drop the deleted cluster's detail + schema entries from cache. A blanket
      // `invalidateQueries(['clusters'])` would prefix-match the still-mounted
      // detail subscription on /clusters/[id] and trigger a 404-bound refetch
      // before the caller's onSuccess can router.push away.
      qc.removeQueries({ queryKey: ['clusters', clusterId] });
      qc.invalidateQueries({
        queryKey: ['clusters'],
        predicate: (query) => query.queryKey.length >= 2 && typeof query.queryKey[1] !== 'string',
      });
    },
  });
}

export function useClusterSchema(
  id: string,
  target: string | undefined,
): UseQueryResult<Schema, ApiError> {
  return useQuery<Schema, ApiError>({
    queryKey: ['clusters', id, 'schema', target],
    enabled: Boolean(id && target),
    queryFn: async () => {
      const { data } = await apiClient.get<Schema>(`/api/v1/clusters/${id}/schema`, {
        params: { target: target ?? '' },
      });
      return data;
    },
    // FR-6: short-circuit retries on TARGET_NOT_FOUND (retryable: false).
    // Without this, TanStack's default retry: 3 fires 4 GETs per misspelled
    // keystroke when the operator types into the manual-mode <Input>.
    retry: retryOnRetryableError,
    // FR-6: silence the global toast for misspelled target names. The
    // "{N} fields discovered" hint not-rendering is sufficient signal that
    // the target name is wrong.
    meta: { suppressErrorCodes: ['TARGET_NOT_FOUND'] },
  });
}

/**
 * List the indices/collections on a registered cluster (FR-3).
 *
 * Returns `EntitySelectListPage<TargetSummary>` so the result can be passed
 * directly to `<EntitySelect query={q}>` without translation. The backend
 * response is the bare `{ data: TargetSummary[] }` shape; `next_cursor` /
 * `has_more` are optional on EntitySelectListPage so this consumes correctly.
 *
 * `enabled: Boolean(clusterId)` prevents firing a GET before the operator
 * has picked a cluster — `useClusterTargets("")` returns an idle query with
 * `data === undefined`, no network call.
 *
 * On `TARGETS_FORBIDDEN`: fires exactly one GET (retry predicate
 * short-circuits) and the global error toast is suppressed via
 * `meta.suppressErrorCodes` — the modal's FR-5 inline amber hint is the
 * only user-facing signal for ACL-restricted clusters.
 */
export function useClusterTargets(
  clusterId: string,
): UseQueryResult<EntitySelectListPage<TargetSummary>, ApiError> {
  return useQuery<EntitySelectListPage<TargetSummary>, ApiError>({
    queryKey: ['clusters', clusterId, 'targets'],
    enabled: Boolean(clusterId),
    queryFn: async () => {
      const { data } = await apiClient.get<EntitySelectListPage<TargetSummary>>(
        `/api/v1/clusters/${clusterId}/targets`,
      );
      return data;
    },
    retry: retryOnRetryableError,
    meta: { suppressErrorCodes: ['TARGETS_FORBIDDEN'] },
  });
}
