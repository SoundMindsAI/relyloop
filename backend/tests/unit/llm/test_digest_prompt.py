# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``backend.app.llm.digest_prompt`` (Story 2.2).

Covers the new ``parent_search_space`` kwarg added by
feat_digest_executable_followups so the rendered user prompt carries the
``<parent_search_space>`` block when the worker passes it.
"""

from __future__ import annotations

from backend.app.llm.digest_prompt import render_digest_user_prompt


def _base_kwargs() -> dict[str, object]:
    """Minimal valid kwargs covering every required arg of the renderer."""
    return {
        "study_name": "ndcg-tune-v3",
        "cluster_name": "products-prod-es",
        "target": "products-v3",
        "query_set_name": "qs-electronics",
        "query_count": 12,
        "judgment_list_name": "jl-v1",
        "rubric_summary": "5-point relevance",
        "baseline_metric": 0.612,
        "achieved_metric": 0.762,
        "top_trials": [
            {"number": 41, "primary_metric": 0.762, "params": {"title_boost": 4.7}},
        ],
        "parameter_importance": {"title_boost": 0.65, "tie_breaker": 0.20},
        "recommended_config": {"title_boost": 4.7},
        "dropped_template_params": [],
        "include_recommendation": True,
        "confidence": None,
    }


class TestParentSearchSpaceBlock:
    def test_renders_block_when_passed(self) -> None:
        kwargs = _base_kwargs()
        kwargs["parent_search_space"] = {
            "params": {
                "title_boost": {"type": "float", "low": 0.5, "high": 10.0},
                "tie_breaker": {"type": "float", "low": 0.0, "high": 1.0},
            }
        }
        rendered = render_digest_user_prompt(**kwargs)  # type: ignore[arg-type]
        assert "<parent_search_space>" in rendered
        assert "</parent_search_space>" in rendered
        assert "title_boost" in rendered
        # tojson renders structured JSON; the float low/high should appear.
        assert "0.5" in rendered
        assert "10" in rendered

    def test_omits_block_when_none(self) -> None:
        kwargs = _base_kwargs()
        rendered = render_digest_user_prompt(**kwargs)  # type: ignore[arg-type]
        assert "<parent_search_space>" not in rendered
        # other blocks unaffected.
        assert "<parameter_importance>" in rendered

    def test_omits_block_when_omitted_kwarg(self) -> None:
        # The kwarg is optional — omitting entirely is equivalent to passing None.
        kwargs = _base_kwargs()
        rendered = render_digest_user_prompt(**kwargs)  # type: ignore[arg-type]
        assert "<parent_search_space>" not in rendered


# ---------------------------------------------------------------------------
# feat_study_convergence_indicator Story 5.1 — <convergence> block
# ---------------------------------------------------------------------------


def _convergence_payload(
    *,
    verdict: str = "still_improving",
    direction: str = "maximize",
    window_size: int = 20,
    total: int = 200,
    improvement: float = 0.012,
) -> dict[str, object]:
    """Mirror of ``StudyConvergenceShape.model_dump()``. The curve is omitted
    from the prompt block (only the verdict + small numerics ride along) so
    we don't need to spend tokens replicating it in tests."""
    return {
        "verdict": verdict,
        "direction": direction,
        "window_size": window_size,
        "epsilon": 0.005,
        "warmup_floor": 50,
        "total_complete_trials": total,
        "improvement_in_window": improvement,
        "best_so_far_curve": [],
    }


class TestConvergenceBlock:
    def test_renders_block_when_passed(self) -> None:
        kwargs = _base_kwargs()
        kwargs["convergence"] = _convergence_payload(verdict="still_improving")
        rendered = render_digest_user_prompt(**kwargs)  # type: ignore[arg-type]
        assert "<convergence>" in rendered
        assert "</convergence>" in rendered
        assert "<verdict>still_improving</verdict>" in rendered
        assert "<direction>maximize</direction>" in rendered
        assert "<window_size>20</window_size>" in rendered
        assert "<total_complete_trials>200</total_complete_trials>" in rendered
        # Improvement value renders as the raw float.
        assert "<improvement_in_window>0.012</improvement_in_window>" in rendered

    def test_renders_converged_verdict(self) -> None:
        kwargs = _base_kwargs()
        kwargs["convergence"] = _convergence_payload(verdict="converged")
        rendered = render_digest_user_prompt(**kwargs)  # type: ignore[arg-type]
        assert "<verdict>converged</verdict>" in rendered

    def test_renders_too_few_trials_verdict(self) -> None:
        kwargs = _base_kwargs()
        kwargs["convergence"] = _convergence_payload(verdict="too_few_trials", total=30)
        rendered = render_digest_user_prompt(**kwargs)  # type: ignore[arg-type]
        assert "<verdict>too_few_trials</verdict>" in rendered
        assert "<total_complete_trials>30</total_complete_trials>" in rendered

    def test_omits_block_when_none(self) -> None:
        kwargs = _base_kwargs()
        # convergence is unset / None — block must not appear.
        rendered = render_digest_user_prompt(**kwargs)  # type: ignore[arg-type]
        assert "<convergence>" not in rendered

    def test_omits_block_when_omitted_kwarg(self) -> None:
        # Same as None — the kwarg is optional with a None default.
        kwargs = _base_kwargs()
        rendered = render_digest_user_prompt(**kwargs)  # type: ignore[arg-type]
        assert "<convergence>" not in rendered


# ---------------------------------------------------------------------------
# feat_study_convergence_indicator Story 5.2 — system-prompt framing rule
# ---------------------------------------------------------------------------


class TestConvergenceAwareSystemPromptFraming:
    """AC-15: the system prompt instructs the LLM to lead with "re-run with
    a larger trial budget" when the verdict is still_improving or
    too_few_trials. The string-content assertion locks the substring so a
    silent rename doesn't slip through."""

    def test_system_prompt_mentions_still_improving_re_run_framing(self) -> None:
        from backend.app.llm.digest_prompt import render_digest_system_prompt

        rendered = render_digest_system_prompt()
        assert "still_improving" in rendered
        assert "re-run with a larger trial budget" in rendered

    def test_system_prompt_mentions_too_few_trials_re_run_framing(self) -> None:
        from backend.app.llm.digest_prompt import render_digest_system_prompt

        rendered = render_digest_system_prompt()
        assert "too_few_trials" in rendered
        # Same framing copy must surface for the too_few_trials branch.
        assert "re-run with a larger trial budget" in rendered

    def test_system_prompt_mentions_converged_proceeds_normally(self) -> None:
        from backend.app.llm.digest_prompt import render_digest_system_prompt

        rendered = render_digest_system_prompt()
        # The "converged → proceed normally" branch must be documented.
        assert "converged" in rendered
