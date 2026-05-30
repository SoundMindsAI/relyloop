# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Strict query-param dependency factory.

Per ``feat_index_document_browser`` spec D-21 / FR-12: the documents browse
endpoint must reject any query param not in its declared allowlist with a
422 ``VALIDATION_ERROR``. This protects against forward-compatibility
mistakes (e.g., a client sending ``?since=`` and expecting list filtering
behavior that the endpoint does not implement).

Convention exception (api-conventions.md): engine-pass-through endpoints
are exempt from the implicit ``?since=`` accepted on the rest of the
``/api/v1`` surface.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request

from backend.app.api.v1._errors import _err


def strict_unknown_query_params(allowed: set[str]) -> Callable[[Request], None]:
    """FastAPI dependency factory rejecting unknown query params.

    Usage::

        _strict: Annotated[
            None,
            Depends(strict_unknown_query_params({"cursor", "limit", "fields"})),
        ] = None
    """

    def _dep(request: Request) -> None:
        for name in request.query_params.keys():
            if name not in allowed:
                raise _err(
                    422,
                    "VALIDATION_ERROR",
                    f"unknown query param: {name!r}",
                    False,
                )

    return _dep
