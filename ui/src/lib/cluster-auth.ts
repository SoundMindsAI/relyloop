// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

// Frontend mirror of the service-layer engine x auth allowlist
// (infra_adapter_solr Story A11). The canonical source is
// `backend/app/adapters/registry.py ALLOWED_AUTH_PER_ENGINE`.
//
// The cluster-registration modal filters the auth_kind dropdown by the
// currently-selected engine_type so invalid combinations can't be picked.
// A drift-guard unit test
// (`ui/src/__tests__/lib/cluster-auth.test.ts`) compares this map against
// the backend source at test time so a backend allowlist change without a
// frontend update fails CI.
//
// Note: the WIRE-Literal allowlists in `enums.ts` cite `schemas.py
// AuthKind` / `EngineTypeWire` (the wire surface). This file mirrors the
// SERVICE-LAYER allowlist in `registry.py` (the post-validation cross-
// product). Two source-of-truth targets for two distinct concerns — see
// the spec's §"Enumerated Value Contract Discipline" for the rationale.

import type { AuthKind, EngineType } from './enums';

// Values must match backend/app/adapters/registry.py ALLOWED_AUTH_PER_ENGINE
export const ALLOWED_AUTH_PER_ENGINE: Record<EngineType, readonly AuthKind[]> = {
  elasticsearch: ['es_apikey', 'es_basic'],
  opensearch: ['opensearch_basic'],
  solr: ['solr_basic', 'solr_apikey'],
} as const;
