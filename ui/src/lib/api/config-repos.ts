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

import { apiClient } from '@/lib/api-client';
import type { ApiError } from '@/lib/api-errors';
import type { components } from '@/lib/types';

export type ConfigRepoDetail = components['schemas']['ConfigRepoDetail'];
export type ConfigReposListResponse = components['schemas']['ConfigReposListResponse'];
export type CreateConfigRepoRequest = components['schemas']['CreateConfigRepoRequest'];

export type ConfigReposPage = ConfigReposListResponse & { totalCount: number };

export interface ConfigReposFilter {
  cursor?: string | undefined;
  limit?: number | undefined;
}

export function useConfigRepos(
  filter: ConfigReposFilter = {},
): UseQueryResult<ConfigReposPage, ApiError> {
  const { cursor, limit } = filter;
  return useQuery<ConfigReposPage, ApiError>({
    queryKey: ['config-repos', { cursor, limit }],
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data, headers } = await apiClient.get<ConfigReposListResponse>(
        '/api/v1/config-repos',
        { params: { cursor, limit } },
      );
      return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
    },
  });
}

export function useCreateConfigRepo(): UseMutationResult<
  ConfigRepoDetail,
  ApiError,
  CreateConfigRepoRequest
> {
  const qc = useQueryClient();
  return useMutation<ConfigRepoDetail, ApiError, CreateConfigRepoRequest>({
    mutationFn: async (body) => {
      const { data } = await apiClient.post<ConfigRepoDetail>('/api/v1/config-repos', body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['config-repos'] });
    },
  });
}
