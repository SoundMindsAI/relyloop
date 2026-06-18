// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/**
 * TanStack Query hook for the demo-engine capability endpoint.
 *
 * feat_selective_engine_startup_and_demo Story 3.1 / FR-7 / FR-8.
 *
 * The reset-to-demo modal calls this hook when the dialog opens to know
 * which engines are running, then defaults the checkbox group to all
 * reachable engines. The endpoint is `GET /api/v1/_test/demo/engines`
 * — a server-side probe of ES + OS + Solr with deterministic ordering
 * matching ``ENGINE_TYPE_VALUES``.
 *
 * The shape is inlined here (not imported from openapi-types) because
 * the contract test at
 * ``backend/tests/contract/test_openapi_surface.py`` enforces the
 * backend↔frontend agreement; the typed const `ENGINE_TYPE_VALUES` in
 * `ui/src/lib/enums.ts` further guarantees the engine_type field can
 * only take one of the three wire values.
 *
 * Error handling mirrors ``demo-reseed.ts``:
 * - 404 means the operator's backend hasn't been rebuilt with the new
 *   endpoint; we don't retry — the modal falls back to "all enabled"
 *   per FR-8 edge cases.
 * - 5xx / network errors are treated identically (don't retry).
 * - The reset modal sets `enabled: open` so the fetch only fires when
 *   the dialog is actually open — no wasted requests on dashboard load.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import { type ApiError } from '@/lib/api-errors';
import { type EngineType } from '@/lib/enums';

export interface DemoEngineStatus {
  engine_type: EngineType;
  reachable: boolean;
  /**
   * Engine's self-reported version number (ES/OS `version.number`,
   * Solr `lucene.solr-spec-version`). null when the engine is
   * unreachable or the version field is missing / malformed. Optional
   * to match the generated types.ts shape (the field is nullable but
   * not required in the OpenAPI schema, since the backend defaults to
   * None when the model serializes).
   * feat_engine_version_selection FR-7.
   */
  version?: string | null;
}

export interface DemoEnginesResponse {
  engines: DemoEngineStatus[];
}

const CAPABILITY_PATH = '/api/v1/_test/demo/engines';

/**
 * Fetch the demo-engine capability snapshot.
 *
 * Cached per dialog session; refetched on each open via the `enabled`
 * flag flipping false → true. Errors don't retry (a 404 means the
 * backend image is older than this commit; retrying every couple seconds
 * floods the console with no chance of recovery without a rebuild).
 */
export function useDemoEnginesCapability(
  options: { enabled?: boolean } = {},
): UseQueryResult<DemoEnginesResponse, ApiError> {
  const enabled = options.enabled ?? true;
  return useQuery<DemoEnginesResponse, ApiError>({
    queryKey: ['demo-engines', 'capability'],
    enabled,
    queryFn: async () => {
      const { data } = await apiClient.get<DemoEnginesResponse>(CAPABILITY_PATH);
      return data;
    },
    retry: false,
    // Re-fetch on each dialog open — the modal toggles `enabled` from
    // false → true via the trigger button. staleTime: 0 keeps the
    // re-open path honest even if React Query's window-focus refetch
    // would otherwise short-circuit.
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
}
