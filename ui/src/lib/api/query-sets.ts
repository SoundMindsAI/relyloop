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

export type QuerySetSummary = components['schemas']['QuerySetSummary'];
export type QuerySetDetail = components['schemas']['QuerySetDetail'];
export type QuerySetListResponse = components['schemas']['QuerySetListResponse'];
export type CreateQuerySetRequest = components['schemas']['CreateQuerySetRequest'];
// The backend's POST /query-sets/{id}/queries router consumes the raw request and
// parses Content-Type manually, so the BulkQueriesJsonRequest pydantic class isn't
// referenced in the OpenAPI schema. Inline the shape here.
export interface BulkQueryItem {
  query_text: string;
  reference_answer?: string | null;
  query_metadata?: Record<string, unknown> | null;
}
export interface BulkQueriesJsonRequest {
  queries: BulkQueryItem[];
}
export type BulkQueriesResponse = components['schemas']['BulkQueriesResponse'];

export type QuerySetsPage = QuerySetListResponse & { totalCount: number };

export interface QuerySetsFilter {
  cluster_id?: string | undefined;
  cursor?: string | undefined;
  limit?: number | undefined;
}

export function useQuerySets(
  filter: QuerySetsFilter = {},
): UseQueryResult<QuerySetsPage, ApiError> {
  const { cluster_id, cursor, limit } = filter;
  return useQuery<QuerySetsPage, ApiError>({
    queryKey: ['query-sets', { cluster_id, cursor, limit }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<QuerySetListResponse>('/api/v1/query-sets', {
        params: { cluster_id, cursor, limit },
      });
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
  });
}

export function useQuerySet(id: string): UseQueryResult<QuerySetDetail, ApiError> {
  return useQuery<QuerySetDetail, ApiError>({
    queryKey: ['query-sets', id],
    queryFn: async () => {
      const { data } = await apiClient.get<QuerySetDetail>(`/api/v1/query-sets/${id}`);
      return data;
    },
  });
}

export function useCreateQuerySet(): UseMutationResult<
  QuerySetDetail,
  ApiError,
  CreateQuerySetRequest
> {
  const qc = useQueryClient();
  return useMutation<QuerySetDetail, ApiError, CreateQuerySetRequest>({
    mutationFn: async (body) => {
      const { data } = await apiClient.post<QuerySetDetail>('/api/v1/query-sets', body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['query-sets'] });
    },
  });
}

export type AddQueriesPayload =
  | { kind: 'json'; queries: BulkQueriesJsonRequest['queries'] }
  | { kind: 'csv'; csv: string };

export function useAddQueries(
  querySetId: string,
): UseMutationResult<BulkQueriesResponse, ApiError, AddQueriesPayload> {
  const qc = useQueryClient();
  return useMutation<BulkQueriesResponse, ApiError, AddQueriesPayload>({
    mutationFn: async (payload) => {
      if (payload.kind === 'csv') {
        const { data } = await apiClient.postCsv<BulkQueriesResponse>(
          `/api/v1/query-sets/${querySetId}/queries`,
          payload.csv,
        );
        return data;
      }
      const { data } = await apiClient.post<BulkQueriesResponse>(
        `/api/v1/query-sets/${querySetId}/queries`,
        { queries: payload.queries },
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['query-sets', querySetId] });
    },
  });
}
