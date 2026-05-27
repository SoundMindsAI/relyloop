"""Shared error envelope builder for /api/v1 routers.

Resolves the cycle-2 F6 circular-import risk: helpers under ``backend/app/api/v1``
(e.g., ``_documents_cursor.py``, ``_strict_query_params.py``) need to raise the
spec §7.5 error envelope from `feat_index_document_browser`/`infra_adapter_elastic`
without importing from ``clusters.py``. This module is the single source of
truth; routers re-export ``_err`` for backwards-compatible call sites.
"""

from __future__ import annotations

from fastapi import HTTPException


def _err(status_code: int, code: str, message: str, retryable: bool) -> HTTPException:
    """Build the spec §7.5 error envelope as an HTTPException detail dict.

    The resulting exception is processed by
    ``backend.app.api.errors.http_exception_handler`` which passes the
    structured ``detail`` through unchanged.
    """
    return HTTPException(
        status_code=status_code,
        detail={"error_code": code, "message": message, "retryable": retryable},
    )
