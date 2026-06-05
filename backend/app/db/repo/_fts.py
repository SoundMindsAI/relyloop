# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""FTS predicate helper for ``?q=`` parameter handling.

Shared by every list/count repo function that exposes a Postgres full-text
search filter. Returns a parameter-bound ``text()`` clause that the caller
ANDs into its existing ``where``.

Per ``feat_fts_rank_ordering``, when ``?q=`` is present AND no explicit
``?sort=`` is supplied, results are ordered by relevance
(``ts_rank`` descending) via :func:`rank_bucket_expr` + the existing
``parsed=None`` keyset helpers in ``_sort.py``. When ``?sort=`` is present it
overrides the rank ordering; when ``?q=`` is absent the legacy
``created_at DESC, id DESC`` ordering is unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Integer, cast, func, text
from sqlalchemy.sql.elements import ColumnElement, TextClause

if TYPE_CHECKING:
    from backend.app.db.repo._sort import ParsedSort

# Rank resolution: ``ts_rank`` for ``plainto_tsquery`` over these short
# documents lands in ``[0, ~1]``; ×1e6 gives ~6 significant digits of
# relevance resolution before the ``id`` tie-breaker takes over — far finer
# than any user-perceptible difference. The bucket is an integer so the
# keyset cursor stays exact (no float-boundary brittleness). Clients never
# see it (opaque cursor).
RANK_BUCKET_SCALE = 1_000_000


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


def rank_bucket_expr(q: str) -> ColumnElement[int]:
    """Integer relevance bucket: ``floor(ts_rank(...) * RANK_BUCKET_SCALE)``.

    Used as the leading ORDER BY column AND encoded into the keyset cursor on
    the rank path, so the two always agree and the keyset predicate is exact
    (rows sharing a bucket tie-break on ``id DESC``). The ``:q`` bind mirrors
    :func:`fts_predicate`'s injection-safe ``plainto_tsquery`` usage.
    """
    ts_rank = func.ts_rank(
        text("search_vector"),
        func.plainto_tsquery("english", q),
    )
    return cast(func.floor(ts_rank * RANK_BUCKET_SCALE), Integer)


def rank_active(q: str | None, parsed: ParsedSort | None) -> bool:
    """True when the relevance-rank ordering is in effect.

    Single source of truth shared by the repo (which builds the rank ORDER
    BY + keyset) and the router (which decodes the cursor's int value-half +
    reads the transient ``_fts_rank_bucket`` for the next cursor). Keeping
    the predicate in one place prevents the encode/decode paths from
    disagreeing. Rank is active iff a non-empty ``?q=`` is present and no
    explicit ``?sort=`` resolved (an explicit sort overrides relevance).
    """
    return bool(q) and parsed is None


def rank_bucket_of(obj: Any) -> int:
    """Read the transient ``_fts_rank_bucket`` stashed by :func:`rows_with_rank`.

    Centralizes the ``Any``-typed read so routers building the next cursor on
    the rank path don't trip mypy's ``attr-defined`` on the unmapped instance
    attribute. Only call on a row returned from the rank path.
    """
    return int(obj._fts_rank_bucket)


def rows_with_rank(result: Any) -> list[Any]:
    """Stash the labeled ``rank_bucket`` onto each ORM row for the next cursor.

    The rank bucket is a computed SQL column, not a mapped attribute, so the
    rank-path SELECT returns ``(Model, rank_bucket)`` rows. We attach the int
    as a transient instance attribute ``_fts_rank_bucket`` (never flushed —
    not a mapped column; declarative models have no ``__slots__``) so the
    router can read ``last._fts_rank_bucket`` when encoding the next cursor.
    """
    rows: list[Any] = []
    for row in result.all():
        obj = row[0]
        obj._fts_rank_bucket = row[1]
        rows.append(obj)
    return rows
