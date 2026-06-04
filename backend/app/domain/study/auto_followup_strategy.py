# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Pure-domain selector for the autopilot's ``follow_suggestions`` strategy.

Owner: ``feat_overnight_final_solution`` Story 2.1.

When :data:`backend.app.db.models.study.Study.config` carries
``auto_followup_strategy = "follow_suggestions"``, the autopilot worker
(:mod:`backend.app.workers.auto_followup`) consumes the parent's persisted
digest follow-ups instead of always running the ±50% narrow on the same
template. This module is the pure-domain selector that walks the digest's
``suggested_followups`` list, filters to executable kinds, applies the
cycle guard (no ``swap_template`` whose target is already in
``parent.config.auto_followup_visited_template_ids``), and returns a
:class:`SelectionOutcome` carrying everything the worker needs for both
the dispatch decision AND the telemetry it must emit afterwards
(``source_index``, ``candidate_count``, ``dropped_template_ids``).

**Pure** — no DB, no I/O, no async. Deterministic: same input → same
output. Unit-testable without fixtures.

**Always returns a ``SelectionOutcome``** (never ``None``). The
"no executable candidate" case is encoded as ``selected is None`` so the
fallback-event telemetry can still carry ``dropped_template_ids`` for
diagnostics — when every executable item was a ``swap_template`` to an
already-visited template, the operator immediately sees "the chain wanted
to ping-pong but the guard fired" from one log line.

Spec: ``docs/00_overview/planned_features/02_mvp2/feat_overnight_final_solution/feature_spec.md``
(FR-4 + spec FR-3 dispatch + cycle 1 finding C1-A2 + cycle 2 finding C2-A1).
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.domain.study.followups import (
    FollowupItem,
    NarrowFollowup,
    SwapTemplateFollowup,
    TextFollowup,
    WidenFollowup,
)

# feat_overnight_final_solution Story 2.1 / FR-6 — wire-value source of
# truth for ``StudyChainLink.selected_followup_kind``. Mirrored by the
# frontend ``SELECTED_FOLLOWUP_KIND_VALUES`` in ``ui/src/lib/enums.ts``
# (added by Story 3.2). Consumed by the CI grep gate at
# ``scripts/ci/verify_enum_source_of_truth.sh``.
#
# ``"narrow_default"`` marks a chain link the worker took via the narrow
# fallback path under the ``follow_suggestions`` strategy — distinct from
# the legacy/default narrow path (which persists NO ``auto_followup_selected_kind``
# key at all, per D-12).
SELECTED_FOLLOWUP_KIND_VALUES: tuple[str, ...] = (
    "narrow_default",
    "narrow",
    "widen",
    "swap_template",
)


@dataclass(frozen=True, slots=True)
class SelectionOutcome:
    """The result of :func:`select_executable_followup`.

    ``selected`` is ``None`` when no executable candidate remained after
    the cycle-guard filter — the worker dispatches the fallback-to-narrow
    path in that case. ``dropped_template_ids`` is **always** populated
    with the cycle-guard-dropped ``SwapTemplateFollowup.template_id``
    values (sorted ascending for deterministic telemetry) — even when
    ``selected is None``, so the fallback event carries the same
    drop-diagnostics as a successful selection.
    """

    selected: FollowupItem | None
    """The executable follow-up to dispatch, or ``None`` to fall back."""

    source_index: int | None
    """0-based index of the selected item in the ORIGINAL ``followups`` list
    (not in the post-filter list), so telemetry can correlate with the
    digest's persisted order. ``None`` when ``selected is None``."""

    candidate_count: int
    """Count of executable items in contention AFTER cycle-guard filtering.
    ``0`` when no executable item remained."""

    dropped_template_ids: list[str]
    """Cycle-guard-dropped ``SwapTemplateFollowup.template_id`` values,
    sorted ascending. Empty when no swap_template was dropped (e.g. the
    digest had only narrow/widen executables, or only text)."""


def select_executable_followup(
    followups: list[FollowupItem],
    visited_template_ids: set[str],
) -> SelectionOutcome:
    """Select the top executable follow-up for the autopilot to dispatch.

    Walks ``followups`` once, recording each item's original index. Drops:

    * :class:`~backend.app.domain.study.followups.TextFollowup` items
      (no ``search_space`` — nothing to run).
    * :class:`~backend.app.domain.study.followups.SwapTemplateFollowup`
      items whose ``template_id`` is in ``visited_template_ids`` (the
      cycle guard — prevents template ping-pong).

    The first remaining item by original index is the selection.
    Relies on the digest's already-ordered list (convergence-aware
    ordering per ``prompts/digest_narrative.system.md`` lines 99-121) —
    no re-ranking inside the autopilot (D-5).

    The cycle guard is **template-based, NOT search-space-based** (D-9):
    a ``narrow`` / ``widen`` that keeps the same template is allowed
    even if the parent's template is in the visited set — only
    ``swap_template`` items go through the cycle guard, and only against
    their ``template_id``.

    The function is **always** total: it returns a :class:`SelectionOutcome`
    even when no executable item remains (with ``selected=None`` +
    ``source_index=None`` + ``candidate_count=0`` + the dropped IDs). The
    worker uses the populated ``dropped_template_ids`` on the fallback
    path so the telemetry distinguishes "digest was text-heavy" from
    "all executables were cycle-dropped".

    Args:
        followups: The parent digest's ``suggested_followups`` list,
            already parsed by :func:`backend.app.domain.study.followups.parse_followup_list`.
            May be empty.
        visited_template_ids: Templates already visited in this chain,
            constructed by the worker from
            ``parent.config.get("auto_followup_visited_template_ids", [parent.template_id])``.
            The worker does NOT add the prospective child template
            BEFORE calling — the cycle guard's job is to look backward
            only (D-9).

    Returns:
        A :class:`SelectionOutcome` describing the selection (or
        absence thereof) plus telemetry fields. Never raises;
        deterministic (same input → same output).
    """
    dropped_template_ids: list[str] = []
    # Executable candidates that survived BOTH filters, with their
    # original index recorded for the source_index telemetry field.
    candidates: list[tuple[int, FollowupItem]] = []

    for original_index, item in enumerate(followups):
        # Drop text — no search_space to consume.
        if isinstance(item, TextFollowup):
            continue
        # Cycle guard: swap_template to a visited template is dropped.
        if isinstance(item, SwapTemplateFollowup) and item.template_id in visited_template_ids:
            dropped_template_ids.append(item.template_id)
            continue
        # narrow / widen / non-cycled swap_template are all executable.
        if isinstance(item, (NarrowFollowup, WidenFollowup, SwapTemplateFollowup)):
            candidates.append((original_index, item))

    dropped_template_ids.sort()

    if not candidates:
        return SelectionOutcome(
            selected=None,
            source_index=None,
            candidate_count=0,
            dropped_template_ids=dropped_template_ids,
        )

    # First executable item by original index — trust the digest's
    # convergence-aware ordering (D-5).
    source_index, selected = candidates[0]
    return SelectionOutcome(
        selected=selected,
        source_index=source_index,
        candidate_count=len(candidates),
        dropped_template_ids=dropped_template_ids,
    )


__all__ = [
    "SELECTED_FOLLOWUP_KIND_VALUES",
    "SelectionOutcome",
    "select_executable_followup",
]
