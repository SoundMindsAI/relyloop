# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""FTS predicate helper for ``?q=`` parameter handling.

Shared by every list/count repo function that exposes a Postgres full-text
search filter. Returns a parameter-bound ``text()`` clause that the caller
ANDs into its existing ``where``.

Per spec FR-1, results are filtered by FTS match but NOT re-ordered by
``ts_rank`` — the existing ``created_at DESC, id DESC`` ordering is
preserved, which keeps the ``(created_at, id)`` keyset cursor valid.
Rank-ordered FTS is deferred per spec §16.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause


def fts_predicate(q: str | None) -> TextClause | None:
    """Build the FTS WHERE clause for ``?q=`` or return None when not active.

    Uses ``plainto_tsquery('english', :q)`` which is injection-safe — it does
    not parse operator characters or arbitrary expressions. Strings shorter
    than 2 characters or longer than 200 must be rejected by Pydantic at
    the router boundary (FR-1); the repo layer trusts upstream validation.
    """
    if not q:
        return None
    return text("search_vector @@ plainto_tsquery('english', :q)").bindparams(q=q)
