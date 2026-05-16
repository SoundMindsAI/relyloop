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

export type QueryTemplateSummary = components['schemas']['QueryTemplateSummary'];
export type QueryTemplateDetail = components['schemas']['QueryTemplateDetail'];
export type QueryTemplateListResponse = components['schemas']['QueryTemplateListResponse'];
export type CreateQueryTemplateRequest = components['schemas']['CreateQueryTemplateRequest'];

export type QueryTemplateListPage = QueryTemplateListResponse & { totalCount: number };

export interface TemplatesFilter {
  engine_type?: string | undefined;
  cursor?: string | undefined;
  limit?: number | undefined;
  q?: string | undefined;
  sort?: string | undefined;
}

export function useTemplates(
  filter: TemplatesFilter = {},
): UseQueryResult<QueryTemplateListPage, ApiError> {
  const { engine_type, cursor, limit, q, sort } = filter;
  return useQuery<QueryTemplateListPage, ApiError>({
    queryKey: ['query-templates', { engine_type, cursor, limit, q, sort }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<QueryTemplateListResponse>(
        '/api/v1/query-templates',
        { params: { engine_type, cursor, limit, q, sort } },
      );
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
  });
}

export function useTemplate(id: string): UseQueryResult<QueryTemplateDetail, ApiError> {
  return useQuery<QueryTemplateDetail, ApiError>({
    queryKey: ['query-templates', id],
    queryFn: async () => {
      const { data } = await apiClient.get<QueryTemplateDetail>(`/api/v1/query-templates/${id}`);
      return data;
    },
  });
}

export function useCreateTemplate(): UseMutationResult<
  QueryTemplateDetail,
  ApiError,
  CreateQueryTemplateRequest
> {
  const qc = useQueryClient();
  return useMutation<QueryTemplateDetail, ApiError, CreateQueryTemplateRequest>({
    mutationFn: async (payload) => {
      const { data } = await apiClient.post<QueryTemplateDetail>(
        '/api/v1/query-templates',
        payload,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['query-templates'] });
    },
  });
}
