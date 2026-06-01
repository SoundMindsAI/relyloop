// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * TanStack Query hook for the demo-reseed status endpoint.
 *
 * Per ``bug_demo_reseed_fake_metric_regression`` D-8. The home-button
 * reseed flow:
 *
 * 1. POST `/api/v1/_test/demo/reseed` → 202 + initial ReseedStatusResponse.
 * 2. Polled by ``useDemoReseedStatus`` every 2s while `status === 'running'`.
 * 3. The hook stops polling automatically on terminal states (`complete`,
 *    `failed`, `idle`).
 *
 * The status shape matches ``backend.app.services.demo_seeding.ReseedStatusResponse``.
 * The fields are inlined here (not imported from openapi-types) because the
 * generated types lag the latest endpoint additions; the contract test at
 * ``backend/tests/contract/test_openapi_surface.py`` guards drift.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import { type ApiError } from '@/lib/api-errors';

export type ReseedStatusLiteral = 'idle' | 'running' | 'complete' | 'failed';

export interface ReseedSummary {
  clusters_created: number;
  query_sets_created: number;
  studies_completed: number;
  proposals_created: number;
  duration_ms: number;
}

export interface ReseedStatusResponse {
  status: ReseedStatusLiteral;
  started_at: string | null;
  finished_at: string | null;
  scenarios_total: number;
  scenarios_completed: number;
  current_step: string | null;
  failed_reason: string | null;
  summary: ReseedSummary | null;
  /**
   * Ordered, oldest-first history of every distinct ``current_step`` the
   * worker has set during this run. Rendered by ``ResetDemoStateButton`` as a
   * scrolling log so the operator sees the full progression, not just the
   * latest overwriting line. The worker dedupes consecutive duplicates and
   * caps the list at the 500 most-recent entries. Matches
   * ``backend.app.services.demo_seeding.ReseedStatusResponse.steps``.
   */
  steps: string[];
  /**
   * Slugs of demo scenarios skipped because their engine wasn't reachable at
   * probe time (engine container not running). When `status === 'complete'`
   * and this is non-empty, the reseed is a legitimate PARTIAL completion (some
   * engines were absent — e.g. Solr not started). When `status === 'failed'`
   * with `failed_reason === 'all_engines_unreachable'`, NO engine was
   * reachable. Always present (defaults to `[]`). Matches
   * ``backend.app.services.demo_seeding.ReseedStatusResponse.scenarios_skipped``.
   * Per infra_solr_ci_readiness FR-5.
   */
  scenarios_skipped: string[];
}

const STATUS_PATH = '/api/v1/_test/demo/reseed/status';
const POLL_INTERVAL_MS = 2_000;

/**
 * Poll the reseed status while a reseed is running.
 *
 * The reactive ``refetchInterval`` callback inspects the latest status
 * payload and stops polling on any terminal state — mirrors the
 * proposal-PR-open hook at ``ui/src/lib/api/proposals.ts`` / the polling
 * pattern in ``ui/src/app/proposals/[id]/page.tsx`` (D-8).
 *
 * ``enabled`` defaults to true so the dashboard can render a stale-status
 * card (e.g., "last reseed failed at <time>") without an explicit
 * activation step. When the operator clicks "Reset to demo state", the
 * mutation kicks off a fresh run and this hook starts polling on its
 * next refetch cycle.
 */
export function useDemoReseedStatus(
  options: { enabled?: boolean } = {},
): UseQueryResult<ReseedStatusResponse, ApiError> {
  const enabled = options.enabled ?? true;
  return useQuery<ReseedStatusResponse, ApiError>({
    queryKey: ['demo-reseed', 'status'],
    enabled,
    queryFn: async () => {
      const { data } = await apiClient.get<ReseedStatusResponse>(STATUS_PATH);
      return data;
    },
    refetchInterval: (query) => {
      // Stop polling when the endpoint is unreachable (404 = endpoint not
      // registered — the backend image probably wasn't rebuilt; 5xx /
      // network errors = service unavailable). Continuing to hammer a
      // broken endpoint floods the console and burns React-render cycles.
      if (query.state.error != null) return false;
      const data = query.state.data;
      if (data == null) return POLL_INTERVAL_MS;
      return data.status === 'running' ? POLL_INTERVAL_MS : false;
    },
    // Don't retry on errors — 404 means the endpoint doesn't exist on the
    // running backend (operator hasn't rebuilt the container); retrying
    // every couple seconds for the whole session is noisy and useless.
    retry: false,
    // Status payload changes every ~2s during a real reseed; staleTime: 0
    // keeps every refetch propagating to subscribers (the progress copy
    // must visibly update).
    staleTime: 0,
  });
}
