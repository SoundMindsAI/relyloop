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
