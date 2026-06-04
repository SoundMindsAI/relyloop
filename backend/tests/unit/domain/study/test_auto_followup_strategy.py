# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :func:`select_executable_followup` (Story 2.1).

Pure-domain selector. No DB, no fixtures, no I/O. Mirrors the test layout
of ``test_followups_backcompat.py`` — same shared search-space dict so a
single Pydantic-validated payload powers every case.

Coverage matrix per spec §14 Unit tests + plan Story 2.1 DoD list:

* Empty list → ``selected=None``, ``candidate_count=0``,
  ``dropped_template_ids=[]``.
* Text-only list → same.
* Single narrow → narrow selected at source_index=0, candidate_count=1,
  dropped empty.
* Text + narrow (text first) → narrow selected at source_index=1
  (original index preserved, NOT post-filter index — telemetry contract).
* swap to visited template + widen → widen selected, swap recorded in
  ``dropped_template_ids`` (AC-8 selector half).
* swap to non-visited template → swap selected (AC-7 selector half).
* All-swaps-cycle-dropped (only swaps, all visited) → ``selected=None``
  with non-empty ``dropped_template_ids`` (AC-9 selector half — the
  fallback event still carries cycle-guard diagnostics).
* Multiple executable candidates of different kinds → first-by-original-
  index wins (D-5: trust digest ordering, no kind-preference policy).
* Determinism property: same input → same output (run twice, equal).
* ``dropped_template_ids`` is sorted ascending (deterministic telemetry).
"""

from __future__ import annotations

from backend.app.domain.study.auto_followup_strategy import (
    SELECTED_FOLLOWUP_KIND_VALUES,
    SelectionOutcome,
    select_executable_followup,
)
from backend.app.domain.study.followups import (
    FollowupItem,
    FollowupListAdapter,
    NarrowFollowup,
    SwapTemplateFollowup,
    WidenFollowup,
)

# Reused across cases — a single small but valid search space keeps the
# fixtures cheap. (Pydantic-validated via FollowupListAdapter so the test
# inputs match the contract the selector consumes from parse_followup_list.)
_VALID_SEARCH_SPACE = {
    "params": {"title_boost": {"type": "float", "low": 0.5, "high": 2.0}},
}

# Two 36-char template_ids (the SwapTemplateFollowup field requires exact-
# 36-char strings — UUIDs). Using deterministic patterns rather than
# uuid.uuid4() to keep tests readable and order-stable.
TEMPLATE_A = "aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa"
TEMPLATE_B = "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb"
TEMPLATE_C = "cccccccc-cccc-7ccc-8ccc-cccccccccccc"


def _build(items: list[dict[str, object]]) -> list[FollowupItem]:
    """Round-trip via FollowupListAdapter so the test inputs are Pydantic-validated."""
    return FollowupListAdapter.validate_python(items)


# ---------------------------------------------------------------------------
# Empty + text-only cases — no executable candidate available.
# ---------------------------------------------------------------------------


class TestEmptyAndTextOnly:
    def test_empty_list_returns_no_selection(self) -> None:
        outcome = select_executable_followup([], visited_template_ids=set())
        assert outcome == SelectionOutcome(
            selected=None,
            source_index=None,
            candidate_count=0,
            dropped_template_ids=[],
        )

    def test_text_only_list_returns_no_selection(self) -> None:
        followups = _build(
            [
                {"kind": "text", "rationale": "re-run with bigger budget", "search_space": None},
                {"kind": "text", "rationale": "investigate query category X", "search_space": None},
            ]
        )
        outcome = select_executable_followup(followups, visited_template_ids=set())
        assert outcome.selected is None
        assert outcome.source_index is None
        assert outcome.candidate_count == 0
        assert outcome.dropped_template_ids == []


# ---------------------------------------------------------------------------
# Single-kind executable cases.
# ---------------------------------------------------------------------------


class TestSingleKindSelection:
    def test_single_narrow_is_selected(self) -> None:
        followups = _build(
            [
                {
                    "kind": "narrow",
                    "rationale": "narrow around the winner",
                    "search_space": _VALID_SEARCH_SPACE,
                }
            ]
        )
        outcome = select_executable_followup(followups, visited_template_ids=set())
        assert isinstance(outcome.selected, NarrowFollowup)
        assert outcome.source_index == 0
        assert outcome.candidate_count == 1
        assert outcome.dropped_template_ids == []

    def test_single_widen_is_selected(self) -> None:
        followups = _build(
            [
                {
                    "kind": "widen",
                    "rationale": "winner hit upper edge",
                    "search_space": _VALID_SEARCH_SPACE,
                }
            ]
        )
        outcome = select_executable_followup(followups, visited_template_ids=set())
        assert isinstance(outcome.selected, WidenFollowup)
        assert outcome.source_index == 0
        assert outcome.candidate_count == 1

    def test_single_swap_to_non_visited_is_selected(self) -> None:
        """AC-7 selector half — swap to a template not in the visited set
        is selected without modification."""
        followups = _build(
            [
                {
                    "kind": "swap_template",
                    "rationale": "function-score template is a better fit",
                    "template_id": TEMPLATE_B,
                    "search_space": _VALID_SEARCH_SPACE,
                }
            ]
        )
        outcome = select_executable_followup(followups, visited_template_ids={TEMPLATE_A})
        assert isinstance(outcome.selected, SwapTemplateFollowup)
        assert outcome.selected.template_id == TEMPLATE_B
        assert outcome.source_index == 0
        assert outcome.candidate_count == 1
        assert outcome.dropped_template_ids == []


# ---------------------------------------------------------------------------
# Original-index preservation — the `source_index` telemetry field must
# point at the ORIGINAL position in the input list, not the post-filter
# position (D-4: telemetry contract is correlation-friendly with the
# digest's persisted order).
# ---------------------------------------------------------------------------


class TestOriginalIndexPreservation:
    def test_text_then_narrow_selects_narrow_at_original_index_one(self) -> None:
        followups = _build(
            [
                {"kind": "text", "rationale": "first text", "search_space": None},
                {
                    "kind": "narrow",
                    "rationale": "second is the runnable one",
                    "search_space": _VALID_SEARCH_SPACE,
                },
            ]
        )
        outcome = select_executable_followup(followups, visited_template_ids=set())
        assert isinstance(outcome.selected, NarrowFollowup)
        assert outcome.source_index == 1  # original index, NOT 0
        assert outcome.candidate_count == 1

    def test_three_texts_then_widen_selects_widen_at_original_index_three(self) -> None:
        followups = _build(
            [
                {"kind": "text", "rationale": "t0", "search_space": None},
                {"kind": "text", "rationale": "t1", "search_space": None},
                {"kind": "text", "rationale": "t2", "search_space": None},
                {
                    "kind": "widen",
                    "rationale": "the widen one",
                    "search_space": _VALID_SEARCH_SPACE,
                },
            ]
        )
        outcome = select_executable_followup(followups, visited_template_ids=set())
        assert isinstance(outcome.selected, WidenFollowup)
        assert outcome.source_index == 3
        assert outcome.candidate_count == 1


# ---------------------------------------------------------------------------
# Cycle-guard cases — swap_template filtering against the visited set.
# ---------------------------------------------------------------------------


class TestCycleGuard:
    def test_swap_to_visited_template_is_dropped(self) -> None:
        """The single executable is a swap to a visited template — it
        gets dropped, and the outcome is no-selection with the dropped
        id recorded for the fallback telemetry event (AC-9 selector
        half)."""
        followups = _build(
            [
                {
                    "kind": "swap_template",
                    "rationale": "swap to A",
                    "template_id": TEMPLATE_A,
                    "search_space": _VALID_SEARCH_SPACE,
                }
            ]
        )
        outcome = select_executable_followup(followups, visited_template_ids={TEMPLATE_A})
        assert outcome.selected is None
        assert outcome.source_index is None
        assert outcome.candidate_count == 0
        assert outcome.dropped_template_ids == [TEMPLATE_A]

    def test_swap_to_visited_plus_widen_selects_widen_and_records_drop(self) -> None:
        """AC-8 selector half — swap to a visited template is dropped;
        the next executable (a widen) is selected; the dropped template
        id is recorded on the outcome for the strategy-selected
        telemetry event."""
        followups = _build(
            [
                {
                    "kind": "swap_template",
                    "rationale": "swap to already-visited A",
                    "template_id": TEMPLATE_A,
                    "search_space": _VALID_SEARCH_SPACE,
                },
                {
                    "kind": "widen",
                    "rationale": "widen kept on the same template",
                    "search_space": _VALID_SEARCH_SPACE,
                },
            ]
        )
        outcome = select_executable_followup(followups, visited_template_ids={TEMPLATE_A})
        assert isinstance(outcome.selected, WidenFollowup)
        assert outcome.source_index == 1
        assert outcome.candidate_count == 1
        assert outcome.dropped_template_ids == [TEMPLATE_A]

    def test_all_swaps_to_visited_templates_returns_no_selection_with_drops(
        self,
    ) -> None:
        """All executable candidates are swaps to visited templates —
        the chain wanted to ping-pong; the cycle guard fired on every
        one. Worker dispatches the fallback path; the fallback event
        carries the dropped ids."""
        followups = _build(
            [
                {
                    "kind": "swap_template",
                    "rationale": "to A",
                    "template_id": TEMPLATE_A,
                    "search_space": _VALID_SEARCH_SPACE,
                },
                {
                    "kind": "swap_template",
                    "rationale": "to B",
                    "template_id": TEMPLATE_B,
                    "search_space": _VALID_SEARCH_SPACE,
                },
            ]
        )
        outcome = select_executable_followup(
            followups, visited_template_ids={TEMPLATE_A, TEMPLATE_B}
        )
        assert outcome.selected is None
        assert outcome.candidate_count == 0
        assert outcome.dropped_template_ids == [TEMPLATE_A, TEMPLATE_B]

    def test_narrow_keeps_same_template_not_subject_to_cycle_guard(self) -> None:
        """D-9 — the cycle guard is template-based AND swap-only. A
        `narrow` on the visited template is a legitimate continuation of
        the chain (the digest is suggesting tighter bounds), so it must
        be selected even though `parent.template_id` is in the visited
        set."""
        followups = _build(
            [
                {
                    "kind": "narrow",
                    "rationale": "tighter bounds on the same template",
                    "search_space": _VALID_SEARCH_SPACE,
                }
            ]
        )
        outcome = select_executable_followup(
            followups,
            visited_template_ids={TEMPLATE_A},  # whatever this template is
        )
        assert isinstance(outcome.selected, NarrowFollowup)
        assert outcome.dropped_template_ids == []


# ---------------------------------------------------------------------------
# Multi-kind: first-by-original-index wins (D-5 — trust digest ordering).
# ---------------------------------------------------------------------------


class TestFirstByOriginalIndexWins:
    def test_widen_before_narrow_selects_widen(self) -> None:
        """No kind-preference policy. The digest's convergence-aware
        ordering at the prompt layer puts the recommended kind first;
        the autopilot trusts that order without re-ranking."""
        followups = _build(
            [
                {"kind": "widen", "rationale": "first", "search_space": _VALID_SEARCH_SPACE},
                {"kind": "narrow", "rationale": "second", "search_space": _VALID_SEARCH_SPACE},
            ]
        )
        outcome = select_executable_followup(followups, visited_template_ids=set())
        assert isinstance(outcome.selected, WidenFollowup)
        assert outcome.source_index == 0
        assert outcome.candidate_count == 2

    def test_swap_before_narrow_selects_swap(self) -> None:
        followups = _build(
            [
                {
                    "kind": "swap_template",
                    "rationale": "first — swap suggested",
                    "template_id": TEMPLATE_B,
                    "search_space": _VALID_SEARCH_SPACE,
                },
                {"kind": "narrow", "rationale": "second", "search_space": _VALID_SEARCH_SPACE},
            ]
        )
        outcome = select_executable_followup(followups, visited_template_ids={TEMPLATE_A})
        assert isinstance(outcome.selected, SwapTemplateFollowup)
        assert outcome.selected.template_id == TEMPLATE_B
        assert outcome.source_index == 0
        assert outcome.candidate_count == 2

    def test_text_swap_visited_narrow_picks_narrow_records_swap_drop(self) -> None:
        """Mixed: text (drop), swap-to-visited (cycle-drop + recorded),
        narrow (selected). source_index points at the narrow's original
        index (2). The single dropped swap survives in the outcome's
        telemetry list."""
        followups = _build(
            [
                {"kind": "text", "rationale": "t0", "search_space": None},
                {
                    "kind": "swap_template",
                    "rationale": "swap to visited",
                    "template_id": TEMPLATE_A,
                    "search_space": _VALID_SEARCH_SPACE,
                },
                {
                    "kind": "narrow",
                    "rationale": "the survivor",
                    "search_space": _VALID_SEARCH_SPACE,
                },
            ]
        )
        outcome = select_executable_followup(followups, visited_template_ids={TEMPLATE_A})
        assert isinstance(outcome.selected, NarrowFollowup)
        assert outcome.source_index == 2
        assert outcome.candidate_count == 1
        assert outcome.dropped_template_ids == [TEMPLATE_A]


# ---------------------------------------------------------------------------
# Determinism property + dropped_template_ids ordering invariant.
# ---------------------------------------------------------------------------


class TestDeterminismAndOrdering:
    def test_same_input_returns_equal_outcome_twice(self) -> None:
        """Pure-function contract — selector is deterministic. Same input
        produces equal output across any number of calls (the worker
        retries the same job after a transient failure must produce the
        same selection)."""
        followups = _build(
            [
                {
                    "kind": "swap_template",
                    "rationale": "to A",
                    "template_id": TEMPLATE_A,
                    "search_space": _VALID_SEARCH_SPACE,
                },
                {
                    "kind": "narrow",
                    "rationale": "narrow fallback",
                    "search_space": _VALID_SEARCH_SPACE,
                },
            ]
        )
        first = select_executable_followup(followups, visited_template_ids={TEMPLATE_A})
        second = select_executable_followup(followups, visited_template_ids={TEMPLATE_A})
        assert first == second

    def test_dropped_template_ids_is_sorted_ascending(self) -> None:
        """Deterministic telemetry: when multiple swap_templates are
        cycle-dropped, the ``dropped_template_ids`` field on the
        outcome is sorted ascending. Stops the test suite from being
        flaky against arbitrary digest order, and gives runbooks a
        stable grep target."""
        followups = _build(
            [
                {
                    "kind": "swap_template",
                    "rationale": "to C",
                    "template_id": TEMPLATE_C,
                    "search_space": _VALID_SEARCH_SPACE,
                },
                {
                    "kind": "swap_template",
                    "rationale": "to A",
                    "template_id": TEMPLATE_A,
                    "search_space": _VALID_SEARCH_SPACE,
                },
                {
                    "kind": "swap_template",
                    "rationale": "to B",
                    "template_id": TEMPLATE_B,
                    "search_space": _VALID_SEARCH_SPACE,
                },
            ]
        )
        outcome = select_executable_followup(
            followups, visited_template_ids={TEMPLATE_A, TEMPLATE_B, TEMPLATE_C}
        )
        assert outcome.selected is None
        # Ascending — A < B < C — regardless of input order.
        assert outcome.dropped_template_ids == [TEMPLATE_A, TEMPLATE_B, TEMPLATE_C]


# ---------------------------------------------------------------------------
# SELECTED_FOLLOWUP_KIND_VALUES — wire-value source-of-truth lock.
# ---------------------------------------------------------------------------


def test_selected_followup_kind_values_are_canonical() -> None:
    """Frontend mirror in ``ui/src/lib/enums.ts SELECTED_FOLLOWUP_KIND_VALUES``
    (Story 3.2) MUST match this tuple character-for-character + order."""
    assert SELECTED_FOLLOWUP_KIND_VALUES == (
        "narrow_default",
        "narrow",
        "widen",
        "swap_template",
    )
