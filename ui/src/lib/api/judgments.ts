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

export type JudgmentListSummary = components['schemas']['JudgmentListSummary'];
export type JudgmentListDetail = components['schemas']['JudgmentListDetail'];
export type JudgmentListListResponse = components['schemas']['JudgmentListListResponse'];
export type JudgmentRow = components['schemas']['JudgmentRow'];
export type JudgmentListJudgmentsResponse = components['schemas']['JudgmentListJudgmentsResponse'];
export type CreateJudgmentListGenerateRequest =
  components['schemas']['CreateJudgmentListGenerateRequest'];
export type GenerateJudgmentsResponse = components['schemas']['GenerateJudgmentsResponse'];
export type ImportJudgmentListRequest = components['schemas']['ImportJudgmentListRequest'];
export type OverrideJudgmentRequest = components['schemas']['OverrideJudgmentRequest'];
export type CalibrationSamplesRequest = components['schemas']['CalibrationSamplesRequest'];
export type CalibrationResponse = components['schemas']['CalibrationResponse'];

export type JudgmentListsPage = JudgmentListListResponse & { totalCount: number };
export type JudgmentsPage = JudgmentListJudgmentsResponse & { totalCount: number };

export interface JudgmentListsFilter {
  query_set_id?: string | undefined;
  cluster_id?: string | undefined;
  cursor?: string | undefined;
  limit?: number | undefined;
}

export function useJudgmentLists(
  filter: JudgmentListsFilter = {},
): UseQueryResult<JudgmentListsPage, ApiError> {
  const { query_set_id, cluster_id, cursor, limit } = filter;
  return useQuery<JudgmentListsPage, ApiError>({
    queryKey: ['judgment-lists', { query_set_id, cluster_id, cursor, limit }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<JudgmentListListResponse>(
        '/api/v1/judgment-lists',
        { params: { query_set_id, cluster_id, cursor, limit } },
      );
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
  });
}

export function useJudgmentList(id: string): UseQueryResult<JudgmentListDetail, ApiError> {
  return useQuery<JudgmentListDetail, ApiError>({
    queryKey: ['judgment-lists', id],
    queryFn: async () => {
      const { data } = await apiClient.get<JudgmentListDetail>(`/api/v1/judgment-lists/${id}`);
      return data;
    },
  });
}

export interface JudgmentsFilter {
  cursor?: string | undefined;
  limit?: number | undefined;
  source?: 'llm' | 'human' | undefined;
  sort?: string | undefined;
}

export function useJudgments(
  listId: string,
  filter: JudgmentsFilter = {},
): UseQueryResult<JudgmentsPage, ApiError> {
  const { cursor, limit, source, sort } = filter;
  return useQuery<JudgmentsPage, ApiError>({
    queryKey: ['judgments', listId, { cursor, limit, source, sort }],
    queryFn: async () => {
      const { data, headers } = await apiClient.get<JudgmentListJudgmentsResponse>(
        `/api/v1/judgment-lists/${listId}/judgments`,
        { params: { cursor, limit, source, sort } },
      );
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
  });
}

export interface OverrideJudgmentVariables extends OverrideJudgmentRequest {
  judgmentId: string;
}

export function useOverrideJudgment(
  listId: string,
): UseMutationResult<JudgmentRow, ApiError, OverrideJudgmentVariables> {
  const qc = useQueryClient();
  return useMutation<JudgmentRow, ApiError, OverrideJudgmentVariables>({
    mutationFn: async ({ judgmentId, ...body }) => {
      const { data } = await apiClient.patch<JudgmentRow>(
        `/api/v1/judgment-lists/${listId}/judgments/${judgmentId}`,
        body,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['judgments', listId] });
      qc.invalidateQueries({ queryKey: ['judgment-lists', listId] });
    },
  });
}

export function useCalibrate(
  listId: string,
): UseMutationResult<CalibrationResponse, ApiError, CalibrationSamplesRequest> {
  const qc = useQueryClient();
  return useMutation<CalibrationResponse, ApiError, CalibrationSamplesRequest>({
    mutationFn: async (body) => {
      const { data } = await apiClient.post<CalibrationResponse>(
        `/api/v1/judgment-lists/${listId}/calibration`,
        body,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['judgment-lists', listId] });
    },
  });
}

export function useGenerateJudgments(): UseMutationResult<
  GenerateJudgmentsResponse,
  ApiError,
  CreateJudgmentListGenerateRequest
> {
  const qc = useQueryClient();
  return useMutation<GenerateJudgmentsResponse, ApiError, CreateJudgmentListGenerateRequest>({
    mutationFn: async (body) => {
      const { data } = await apiClient.post<GenerateJudgmentsResponse>(
        '/api/v1/judgments/generate',
        body,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['judgment-lists'] });
    },
  });
}

export function useImportJudgmentList(): UseMutationResult<
  JudgmentListDetail,
  ApiError,
  ImportJudgmentListRequest
> {
  const qc = useQueryClient();
  return useMutation<JudgmentListDetail, ApiError, ImportJudgmentListRequest>({
    mutationFn: async (body) => {
      const { data } = await apiClient.post<JudgmentListDetail>(
        '/api/v1/judgment-lists/import',
        body,
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['judgment-lists'] });
    },
  });
}
