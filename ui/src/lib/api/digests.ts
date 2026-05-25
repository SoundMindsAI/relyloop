'use client';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type { ApiError } from '@/lib/api-errors';
import type { components } from '@/lib/types';

export type DigestResponse = components['schemas']['DigestResponse'];

/**
 * Fetch the digest for a study.
 *
 * The digest endpoint returns 404 ``DIGEST_NOT_READY`` while a study is still
 * running — ``meta.suppressErrorCodes`` keeps the global error toast quiet
 * for that case so consumers can render their own waiting state.
 *
 * feat_study_clone_narrow_bounds Story 1.2 — the signature was widened from
 * ``(studyId: string)`` to ``(studyId: string | undefined, opts?)`` so the
 * create-study modal can call this hook unconditionally (Rules of Hooks)
 * while suppressing the network request on the non-clone path. The
 * backward-compatible default ``enabled: Boolean(studyId)`` keeps all
 * existing single-argument callers (e.g. ``app/studies/[id]/page.tsx``)
 * working unchanged. Mirrors the ``useStudy(id, { enabled })`` pattern at
 * [`ui/src/lib/api/studies.ts`](../studies.ts).
 */
export function useStudyDigest(
  studyId: string | undefined,
  opts?: { enabled?: boolean },
): UseQueryResult<DigestResponse, ApiError> {
  const enabled = opts?.enabled ?? Boolean(studyId);
  return useQuery<DigestResponse, ApiError>({
    queryKey: ['studies', studyId ?? '', 'digest'],
    queryFn: async () => {
      // The ``enabled`` gate above ensures we only reach here with a
      // truthy ``studyId`` — defend against bypass with an explicit check
      // so a hypothetical caller that forces ``enabled: true`` with
      // ``studyId === undefined`` fails loudly instead of issuing
      // ``GET /api/v1/studies//digest``.
      if (!studyId) throw new Error('useStudyDigest: studyId required when enabled');
      const { data } = await apiClient.get<DigestResponse>(`/api/v1/studies/${studyId}/digest`);
      return data;
    },
    enabled,
    meta: { suppressErrorCodes: ['DIGEST_NOT_READY'] },
    retry: false,
  });
}
