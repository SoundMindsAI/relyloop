// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import {
  useMutation,
  useQuery,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import type { ApiError } from '@/lib/api-errors';
import type { UbiConverter, UbiMappingStrategy, UbiReadinessRung } from '@/lib/enums';

// -----------------------------------------------------------------------------
// Wire types — hand-rolled inline until next `pnpm types:gen` regen pulls them
// from the live OpenAPI schema. Source-of-truth in
// backend/app/api/v1/schemas.py (UbiReadinessResponse +
// CreateJudgmentListFromUbiRequest). Keep field shapes in sync with that file.
// -----------------------------------------------------------------------------

export interface UbiReadinessResponse {
  rung: UbiReadinessRung;
  covered_pairs_pct: number | null;
  head_covered: boolean | null;
  checked_at: string;
}

export interface CreateJudgmentListFromUbiRequest {
  name: string;
  description?: string | null;
  query_set_id: string;
  cluster_id: string;
  target: string;
  since: string;
  until?: string | null;
  converter: UbiConverter;
  converter_config?: Record<string, unknown> | null;
  llm_fill_threshold?: number | null;
  min_impressions_threshold?: number | null;
  mapping_strategy?: UbiMappingStrategy;
  current_template_id?: string | null;
  rubric?: string | null;
}

export interface GenerateJudgmentsFromUbiResponse {
  judgment_list_id: string;
  status: 'generating';
}

// -----------------------------------------------------------------------------
// Hooks
// -----------------------------------------------------------------------------

const UBI_READINESS_STALE_MS = 60_000; // matches the backend Redis cache TTL.

/**
 * useUbiReadiness — read-through the GET /clusters/{id}/ubi-readiness endpoint.
 *
 * Gracefully degrades to `rung_0` on 404/503 so the consumer (the
 * generate-judgments dialog's method picker) can default to the LLM
 * path without surfacing a hard error. The backend Redis cache is
 * 60s; the React Query staleTime mirrors so a back-to-back dialog
 * open + submit re-fetches from cache, not from the network.
 *
 * Returns `null` (not Loading) when any of the three required
 * params is missing — callers can safely call the hook before the
 * user has selected a query_set or target.
 */
export function useUbiReadiness(
  clusterId: string | null | undefined,
  querySetId: string | null | undefined,
  target: string | null | undefined,
): UseQueryResult<UbiReadinessResponse, ApiError> {
  const enabled = Boolean(clusterId && querySetId && target);
  return useQuery<UbiReadinessResponse, ApiError>({
    queryKey: ['ubi-readiness', clusterId, querySetId, target],
    enabled,
    staleTime: UBI_READINESS_STALE_MS,
    queryFn: async () => {
      try {
        const { data } = await apiClient.get<UbiReadinessResponse>(
          `/api/v1/clusters/${clusterId}/ubi-readiness`,
          { params: { query_set_id: querySetId, target } },
        );
        return data;
      } catch (err) {
        // Graceful degradation per spec FR-7: unreachable / not-found
        // surfaces as rung_0 so the picker defaults to the LLM path.
        const status = (err as ApiError | undefined)?.status;
        if (status === 404 || status === 503) {
          return {
            rung: 'rung_0' as const,
            covered_pairs_pct: null,
            head_covered: null,
            checked_at: new Date().toISOString(),
          };
        }
        throw err;
      }
    },
  });
}

/**
 * useGenerateJudgmentsFromUbi — TanStack mutation hitting
 * POST /api/v1/judgments/generate-from-ubi. The 13 error envelopes
 * surface unchanged via ApiError; the dialog (Story 4.2) renders
 * them in the toast.
 */
export function useGenerateJudgmentsFromUbi(): UseMutationResult<
  GenerateJudgmentsFromUbiResponse,
  ApiError,
  CreateJudgmentListFromUbiRequest
> {
  return useMutation<GenerateJudgmentsFromUbiResponse, ApiError, CreateJudgmentListFromUbiRequest>({
    mutationFn: async (body) => {
      const { data } = await apiClient.post<GenerateJudgmentsFromUbiResponse>(
        '/api/v1/judgments/generate-from-ubi',
        body,
      );
      return data;
    },
  });
}
