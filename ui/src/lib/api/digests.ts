'use client';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type { ApiError } from '@/lib/api-errors';
import type { components } from '@/lib/types';

export type DigestResponse = components['schemas']['DigestResponse'];

export function useStudyDigest(studyId: string): UseQueryResult<DigestResponse, ApiError> {
  return useQuery<DigestResponse, ApiError>({
    queryKey: ['studies', studyId, 'digest'],
    queryFn: async () => {
      const { data } = await apiClient.get<DigestResponse>(`/api/v1/studies/${studyId}/digest`);
      return data;
    },
    // The digest endpoint returns 404 DIGEST_NOT_READY while a study is still
    // running — suppress the global toast for that case so the panel can
    // render its own waiting state.
    meta: { suppressErrorCodes: ['DIGEST_NOT_READY'] },
    retry: false,
  });
}
