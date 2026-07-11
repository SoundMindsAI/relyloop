// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

import { keepPreviousData, useQuery, type UseQueryResult } from '@tanstack/react-query';

import { apiClient } from '@/lib/api-client';
import { isApiError, type ApiError } from '@/lib/api-errors';

/**
 * Wire shapes for the documents endpoints (feat_index_document_browser FR-3/4).
 *
 * Source of truth: ``backend/app/api/v1/schemas.py`` ``DocumentSummary`` /
 * ``DocumentListResponse`` and ``backend/app/adapters/protocol.py`` ``Document``.
 * The generated ``components['schemas']`` types in ``ui/src/lib/types.ts``
 * predate this feature; refresh them via the openapi codegen on the next
 * routine regeneration. Until then these inline types track the backend
 * surface and are covered by the contract test
 * ``backend/tests/contract/test_documents_contract.py``.
 */
export interface DocumentSummary {
  doc_id: string;
  source: Record<string, unknown> | null;
}

export interface DocumentListResponse {
  data: DocumentSummary[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface Document {
  doc_id: string;
  source: Record<string, unknown> | null;
}

export interface DocumentListPage {
  data: DocumentListResponse;
  totalCount: number | null;
}

export interface DocumentListOpts {
  cursor?: string | null;
  limit?: number;
  fields?: string | null;
}

function retryOnRetryableError(failureCount: number, error: unknown): boolean {
  return isApiError(error) ? Boolean(error.retryable) && failureCount < 3 : failureCount < 3;
}

/**
 * Paginated documents browse for one index/collection on a cluster
 * (feat_index_document_browser FR-3 / Story 3.3).
 *
 * `totalCount` is parsed from the response `X-Total-Count` header (F8
 * resolution) so the page header can render `<count> documents` next to
 * the index name. Returns `null` when the header is missing.
 */
export function useTargetDocuments(
  clusterId: string,
  target: string,
  opts: DocumentListOpts = {},
): UseQueryResult<DocumentListPage, ApiError> {
  const { cursor = null, limit = 25, fields = null } = opts;
  return useQuery<DocumentListPage, ApiError>({
    queryKey: ['clusters', clusterId, 'targets', target, 'documents', { cursor, limit, fields }],
    placeholderData: keepPreviousData,
    enabled: Boolean(clusterId && target),
    queryFn: async () => {
      const params: Record<string, string | number> = { limit };
      if (cursor) params.cursor = cursor;
      if (fields) params.fields = fields;
      const resp = await apiClient.get<DocumentListResponse>(
        `/api/v1/clusters/${encodeURIComponent(clusterId)}/targets/${encodeURIComponent(target)}/documents`,
        { params },
      );
      const totalHeader = resp.headers.get('X-Total-Count');
      const totalCount = totalHeader != null ? parseInt(totalHeader, 10) : null;
      return { data: resp.data, totalCount: Number.isNaN(totalCount) ? null : totalCount };
    },
    retry: retryOnRetryableError,
    meta: { suppressErrorCodes: ['TARGETS_FORBIDDEN', 'TARGET_NOT_FOUND'] },
  });
}

/**
 * Fetch one document by its `_id` (feat_index_document_browser FR-4 / Story 3.4).
 *
 * The doc_id segment is encoded by the caller (the catch-all route reconstructs
 * it from `params.doc_id.join('/')` and the hook URL-encodes it before sending).
 */
export function useTargetDocument(
  clusterId: string,
  target: string,
  docId: string,
): UseQueryResult<Document, ApiError> {
  return useQuery<Document, ApiError>({
    queryKey: ['clusters', clusterId, 'targets', target, 'documents', docId],
    enabled: Boolean(clusterId && target && docId),
    queryFn: async () => {
      const { data } = await apiClient.get<Document>(
        `/api/v1/clusters/${encodeURIComponent(clusterId)}/targets/${encodeURIComponent(target)}/documents/${encodeURIComponent(docId)}`,
      );
      return data;
    },
    retry: retryOnRetryableError,
    meta: { suppressErrorCodes: ['DOCUMENT_NOT_FOUND', 'TARGETS_FORBIDDEN', 'TARGET_NOT_FOUND'] },
  });
}
