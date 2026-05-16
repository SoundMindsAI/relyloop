'use client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { toast } from 'sonner';

import { apiClient } from '@/lib/api-client';
import { isApiError, toToastMessage, type ApiError } from '@/lib/api-errors';
import type { components } from '@/lib/types';

export type QuerySetSummary = components['schemas']['QuerySetSummary'];
export type QuerySetDetail = components['schemas']['QuerySetDetail'];
export type QuerySetListResponse = components['schemas']['QuerySetListResponse'];
export type CreateQuerySetRequest = components['schemas']['CreateQuerySetRequest'];
export type QueryRow = components['schemas']['QueryRow'];
export type QueryListResponse = components['schemas']['QueryListResponse'];
export type UpdateQueryRequest = components['schemas']['UpdateQueryRequest'];
export type JudgmentListRef = components['schemas']['JudgmentListRef'];
export type QueryHasJudgmentsEnvelope = components['schemas']['QueryHasJudgmentsEnvelope'];
export type QueryHasJudgmentsDetail = components['schemas']['QueryHasJudgmentsDetail'];
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
  q?: string | undefined;
  sort?: string | undefined;
}

export function useQuerySets(
  filter: QuerySetsFilter = {},
): UseQueryResult<QuerySetsPage, ApiError> {
  const { cluster_id, cursor, limit, q, sort } = filter;
  return useQuery<QuerySetsPage, ApiError>({
    queryKey: ['query-sets', { cluster_id, cursor, limit, q, sort }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<QuerySetListResponse>('/api/v1/query-sets', {
        params: { cluster_id, cursor, limit, q, sort },
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

// ---------------------------------------------------------------------------
// feat_query_inline_crud — per-query CRUD hooks (Story 4.0)
// ---------------------------------------------------------------------------

export type QueriesPage = QueryListResponse & { totalCount: number };

export interface QueriesFilter {
  cursor?: string | undefined;
  limit?: number | undefined;
  since?: string | undefined; // ISO 8601
}

export function useQueries(
  querySetId: string,
  filter: QueriesFilter = {},
): UseQueryResult<QueriesPage, ApiError> {
  const { cursor, limit, since } = filter;
  return useQuery<QueriesPage, ApiError>({
    queryKey: ['query-sets', querySetId, 'queries', { cursor, limit, since }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<QueryListResponse>(
        `/api/v1/query-sets/${querySetId}/queries`,
        { params: { cursor, limit, since } },
      );
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
  });
}

export function useUpdateQuery(
  querySetId: string,
): UseMutationResult<QueryRow, ApiError, { queryId: string; patch: UpdateQueryRequest }> {
  const qc = useQueryClient();
  return useMutation<QueryRow, ApiError, { queryId: string; patch: UpdateQueryRequest }>({
    mutationFn: async ({ queryId, patch }) => {
      const { data } = await apiClient.patch<QueryRow>(
        `/api/v1/query-sets/${querySetId}/queries/${queryId}`,
        patch,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['query-sets', querySetId, 'queries'] });
      qc.invalidateQueries({ queryKey: ['query-sets', querySetId] });
    },
    // No local onError — global MutationCache.onError handles the toast.
  });
}

export interface DeleteQueryOptions {
  /** Called with the FIRST affected list's id when 409 QUERY_HAS_JUDGMENTS fires.
   * Wired by the consuming `<DeleteQueryDialog>` to `router.push('/judgments/' + id)`. */
  onOpenJudgmentList: (judgmentListId: string) => void;
  onSuccess?: () => void;
}

/**
 * Custom 409 toast with action link — the documented "modal mutation
 * caller" carve-out per `query-provider.tsx:14-18`. Opts out of the
 * global error toast via `meta.suppressGlobalErrorToast: true` because
 * the QUERY_HAS_JUDGMENTS toast needs a Sonner `action` slot the
 * generic global handler can't produce. Non-409 errors still get the
 * canonical formatted toast via `toToastMessage(err)`.
 */
export function useDeleteQuery(
  querySetId: string,
  options: DeleteQueryOptions,
): UseMutationResult<void, ApiError, string> {
  const qc = useQueryClient();
  return useMutation<void, ApiError, string>({
    meta: { suppressGlobalErrorToast: true },
    mutationFn: async (queryId) => {
      await apiClient.delete(`/api/v1/query-sets/${querySetId}/queries/${queryId}`);
    },
    onSuccess: () => {
      toast.success('Query deleted');
      qc.invalidateQueries({ queryKey: ['query-sets', querySetId, 'queries'] });
      qc.invalidateQueries({ queryKey: ['query-sets', querySetId] });
      options.onSuccess?.();
    },
    onError: (err) => {
      if (isApiError(err) && err.errorCode === 'QUERY_HAS_JUDGMENTS') {
        const detail = (err.detail ?? {}) as QueryHasJudgmentsDetail;
        const sample = detail.judgment_lists ?? [];
        const overflow = detail.overflow_count ?? 0;
        const totalLists = sample.length + overflow;
        const noun = totalLists === 1 ? 'judgment list' : 'judgment lists';
        const overflowSuffix = overflow > 0 ? ` (${overflow} more not shown.)` : '';
        const message = `${totalLists} ${noun} reference this query.${overflowSuffix}`;
        const first = sample[0];
        toast.error(
          message,
          first
            ? {
                action: {
                  label: `Open ${first.name} →`,
                  onClick: () => options.onOpenJudgmentList(first.id),
                },
              }
            : undefined,
        );
      } else if (isApiError(err)) {
        // Non-409 errors fall through to the canonical formatting.
        toast.error(toToastMessage(err));
      } else {
        toast.error('Unknown error');
      }
    },
  });
}
