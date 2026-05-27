/**
 * Frontend mirror of ``backend/app/services/documents.py`` truncation
 * constants (feat_index_document_browser FR-3 / D-27).
 *
 * The frontend renders the sentinel verbatim with a tooltip linking to the
 * detail view. Source of truth: ``backend/app/services/documents.py``
 * — keep this in sync. A contract test asserts the literal value at
 * ``backend/tests/contract/test_documents_contract.py``.
 */

export const DOCUMENT_FIELD_TRUNCATED = '<…truncated; full value on detail view…>';
export const DOCUMENT_LIST_VIEW_TOO_LARGE_KEY = '__list_view_too_large__';
