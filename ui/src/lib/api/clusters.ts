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

export type ClusterSummary = components['schemas']['ClusterSummary'];
export type ClusterDetail = components['schemas']['ClusterDetail'];
export type ClusterListResponse = components['schemas']['ClusterListResponse'];
export type CreateClusterRequest = components['schemas']['CreateClusterRequest'];
export type Schema = components['schemas']['Schema'];

export type ClusterListPage = ClusterListResponse & { totalCount: number };

export interface ClustersFilter {
  cursor?: string | undefined;
  limit?: number | undefined;
  since?: string | undefined;
  q?: string | undefined;
  sort?: string | undefined;
  engine_type?: string | undefined;
  environment?: string | undefined;
}

export function useClusters(
  filter: ClustersFilter = {},
): UseQueryResult<ClusterListPage, ApiError> {
  const { cursor, limit, since, q, sort, engine_type, environment } = filter;
  return useQuery<ClusterListPage, ApiError>({
    queryKey: ['clusters', { cursor, limit, since, q, sort, engine_type, environment }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<ClusterListResponse>('/api/v1/clusters', {
        params: { cursor, limit, since, q, sort, engine_type, environment },
      });
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
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
  });
}
