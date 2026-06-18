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
import { type EngineType, type ReseedSkipReason } from '@/lib/enums';

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
  /**
   * Reason discrimination for each entry in `scenarios_skipped`:
   *   - 'user_excluded' — operator's reset-modal selection excluded the
   *     engine_type via the POST body's `engines` filter.
   *   - 'unreachable'   — the engine container wasn't reachable at probe
   *     time (today's behavior — pre-existing semantics).
   *
   * Additive sibling field, defaulted to `{}` so older Redis-cached
   * payloads still deserialize cleanly. The frontend treats a slug whose
   * key is absent from this map as 'unreachable' for display purposes
   * (see ResetDemoStateButton's partial-completion footer).
   *
   * Matches
   * ``backend.app.services.demo_seeding.ReseedStatusResponse.scenarios_skipped_reasons``.
   * Per feat_selective_engine_startup_and_demo FR-6.
   */
  scenarios_skipped_reasons: Record<string, ReseedSkipReason>;
}

/**
 * Body shape for `POST /api/v1/_test/demo/reseed`.
 *
 * Matches ``backend.app.api.v1._test.ReseedRequest``. When `engines` is
 * null/omitted, the backend reseeds every reachable engine (today's
 * default). When provided, only scenarios whose engine_type is in the
 * list are attempted; others are skipped with reason 'user_excluded'.
 * Empty list is rejected by the backend with 422 (D-7).
 *
 * Per feat_selective_engine_startup_and_demo FR-4.
 */
export interface ReseedRequest {
  engines: EngineType[] | null;
}

const RESEED_PATH = '/api/v1/_test/demo/reseed';

/**
 * Trigger a demo reseed with an optional engine filter.
 *
 * Returns the initial ReseedStatusResponse (status === 'running'). The
 * caller is responsible for kicking the polling hook into life so the
 * progress dialog renders the worker's incremental step updates.
 *
 * Throws ApiError on 409 (SEED_IN_PROGRESS), 422 (VALIDATION_ERROR on
 * a bad engines list), 503 (ARQ_POOL_UNAVAILABLE), or any network error.
 */
export async function postDemoReseed(engines: EngineType[] | null): Promise<ReseedStatusResponse> {
  const body: ReseedRequest = { engines };
  const { data } = await apiClient.post<ReseedStatusResponse>(RESEED_PATH, body);
  return data;
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
    // bug_reset_demo_no_instant_feedback_poll_race (Gemini review) — the
    // component stays mounted on the dashboard and the query stays enabled
    // after a reseed terminates (`refetchInterval` returns false but the
    // observer lingers). Without this, every window-focus would refetch
    // /reseed/status even when nothing is running. During an active run the
    // 2s `refetchInterval` is the update source (the operator is watching the
    // focused dialog), so focus refetches add no value — disable them.
    refetchOnWindowFocus: false,
    // Status payload changes every ~2s during a real reseed; staleTime: 0
    // keeps every refetch propagating to subscribers (the progress copy
    // must visibly update).
    staleTime: 0,
  });
}
