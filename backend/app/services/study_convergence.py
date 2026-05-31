# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Async glue for the pure convergence classifier (Story 2.2).

:mod:`backend.app.domain.study.convergence` is the pure-Python classifier
(no DB, no I/O). This module owns:

1. **In-flight short-circuit** — never classify a ``queued`` / ``running``
   study; its trial set is still mutating and any verdict would be
   premature. Mirrors how the chain-summary derivation gates the tail
   link's ``in_flight`` status before computing lift.
2. **Direction resolution** — read ``study.objective.get("direction",
   "maximize")``, mirroring the pattern at ``studies.py:173``. An
   explicitly-invalid value (anything other than ``"maximize"`` or
   ``"minimize"``) returns ``None`` with a WARN log; the absent-key
   path uses the documented "maximize" default rather than warning.
3. **Exception shielding** — wrap :func:`classify_convergence` in
   ``try/except Exception`` so a classifier bug never crashes the
   underlying ``GET /studies/{id}``. The aggregator emits a WARN with
   the exception class + message; the API returns ``convergence: null``
   and the panel renders the null-state badge.

Consumers:

* :func:`backend.app.api.v1.studies._detail` — enriches ``StudyDetail``
  (Story 3.1).
* :func:`backend.workers.digest.generate_digest` — threads the shape
  into the digest user prompt (Story 5.1).

Symmetry note: the in-flight gate fires BEFORE direction resolution so
queued studies with malformed objectives don't emit spurious WARN logs
during their normal lifecycle.
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo
from backend.app.db.models import Study
from backend.app.domain.study.convergence import (
    ConvergenceShape,
    classify_convergence,
)

_log = structlog.get_logger(__name__)

# Statuses for which we never classify. ``queued`` has zero trials by
# definition; ``running`` is mid-flight and would produce a verdict the
# operator can't act on. Matches the autopilot chain-summary stop_reason
# convention (``in_flight`` short-circuits the tail-link classification).
_IN_FLIGHT_STATUSES: frozenset[str] = frozenset({"queued", "running"})


def _resolve_direction(
    objective: dict[str, Any] | None,
) -> Literal["maximize", "minimize"] | None:
    """Resolve a study's optimization direction.

    Returns ``"maximize"`` when the ``direction`` key is absent (the
    documented default — see ``studies.py:173`` precedent). Returns the
    explicit value when it's ``"maximize"`` or ``"minimize"``. Returns
    ``None`` for any other string so the caller can WARN + degrade.

    ``objective`` may itself be ``None`` (defensive against degenerate
    rows) — treated as absent.
    """
    if objective is None:
        return "maximize"
    raw = objective.get("direction")
    if raw is None:
        return "maximize"
    if raw == "maximize":
        return "maximize"
    if raw == "minimize":
        return "minimize"
    return None


async def fetch_study_convergence(db: AsyncSession, study_row: Study) -> ConvergenceShape | None:
    """Build the ``ConvergenceShape`` for a single study or return ``None``.

    Decision flow (matches plan Story 2.2 logic / spec FR-3):

    1. ``study_row.status in {"queued", "running"}`` → return ``None``
       (in-flight short-circuit).
    2. Resolve direction via :func:`_resolve_direction`. ``None`` →
       emit ``convergence_invalid_direction`` WARN; return ``None``.
    3. Load usable trials via the dedicated repo helper.
    4. Wrap :func:`classify_convergence` in ``try/except Exception``.
       On exception: emit ``convergence_classifier_exception`` WARN;
       return ``None`` (GET still succeeds).
    5. On success: emit ``convergence_classified`` DEBUG and return
       the shape.

    This is the single entry point used by ``_detail`` and the digest
    worker. Both call sites treat ``None`` identically — the panel
    renders the null-state badge, the digest skips the
    ``<convergence>`` block.
    """
    # Step 1: in-flight short-circuit.
    if study_row.status in _IN_FLIGHT_STATUSES:
        return None

    # Step 2: direction resolution. ``isinstance(... dict)`` defends against
    # the rare degenerate-row case where ``objective`` deserialized to a
    # non-dict (e.g., a stringified payload from a long-dead migration).
    objective = study_row.objective if isinstance(study_row.objective, dict) else None
    direction = _resolve_direction(objective)
    if direction is None:
        # The raw direction value is preserved verbatim for the operator's
        # debugging — but never the key name or the wider objective dict
        # (defensive against any field that might carry secrets at MVP3+).
        raw = objective.get("direction") if objective is not None else None
        _log.warning(
            "convergence_invalid_direction",
            study_id=str(study_row.id),
            raw_direction=raw,
        )
        return None

    # Step 3: load usable trials.
    usable_trials = await repo.list_complete_optuna_trials_for_study(db, str(study_row.id))

    # Step 4: classifier — wrapped against unexpected exceptions so GET
    # /studies/{id} can never 500 because of a domain-side bug.
    try:
        shape = classify_convergence(usable_trials, direction=direction)
    except Exception as exc:  # noqa: BLE001 — intentional broad catch
        _log.warning(
            "convergence_classifier_exception",
            study_id=str(study_row.id),
            exception_type=type(exc).__name__,
            exception_str=str(exc),
        )
        return None

    # Step 5: success path (or sub-MIN-trials None pass-through — the
    # caller still treats ``None`` as the null-state branch).
    if shape is not None:
        _log.debug(
            "convergence_classified",
            study_id=str(study_row.id),
            verdict=shape.verdict,
            total_complete_trials=shape.total_complete_trials,
            window_size=shape.window_size,
            improvement_in_window=shape.improvement_in_window,
        )
    return shape


__all__ = [
    "fetch_study_convergence",
]
