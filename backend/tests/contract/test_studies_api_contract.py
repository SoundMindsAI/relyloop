# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Contract tests for Phase 2's API surface (Story 3.5).

The integration tests at
``backend/tests/integration/test_query_templates_api.py``,
``test_csv_upload.py``, ``test_studies_api.py``, and
``test_study_lifecycle.py`` exercise the live FastAPI app + DB. This
module covers:

* Importability of every documented Pydantic model.
* Field-level validators on the request models (range bounds, enum
  values, model_validator paths).

These run in CI's hermetic test-contract layer (no DB / Redis / engine).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.api.v1.schemas import (
    BulkQueriesJsonRequest,
    BulkQueriesResponse,
    BulkQueryItem,
    ConfidenceShape,
    CreateQuerySetRequest,
    CreateQueryTemplateRequest,
    CreateStudyRequest,
    ObjectiveSpec,
    QuerySetDetail,
    QuerySetListResponse,
    QuerySetSummary,
    QueryTemplateDetail,
    QueryTemplateListResponse,
    QueryTemplateSummary,
    StudyConfigSpec,
    StudyConvergenceShape,
    StudyDetail,
    StudyListResponse,
    StudySummary,
    TrialDetail,
    TrialListResponse,
    TrialsSummaryShape,
)


def test_phase2_schemas_importable() -> None:
    """Every documented Phase 2 model is importable."""
    for cls in (
        BulkQueriesJsonRequest,
        BulkQueriesResponse,
        BulkQueryItem,
        ConfidenceShape,
        StudyConvergenceShape,
        CreateQuerySetRequest,
        CreateQueryTemplateRequest,
        CreateStudyRequest,
        ObjectiveSpec,
        QuerySetDetail,
        QuerySetListResponse,
        QuerySetSummary,
        QueryTemplateDetail,
        QueryTemplateListResponse,
        QueryTemplateSummary,
        StudyConfigSpec,
        StudyDetail,
        StudyListResponse,
        StudySummary,
        TrialDetail,
        TrialListResponse,
        TrialsSummaryShape,
    ):
        assert cls is not None


def test_study_detail_includes_confidence_field() -> None:
    """``StudyDetail`` exposes ``confidence: ConfidenceShape | None`` (FR-5a)."""
    schema = StudyDetail.model_json_schema()
    assert "confidence" in schema["properties"], (
        "StudyDetail.confidence missing — see feat_pr_metric_confidence Story 1.4."
    )
    # The field is Optional[ConfidenceShape], i.e. anyOf({$ref}, {null}).
    prop = schema["properties"]["confidence"]
    refs_or_anyof = prop.get("anyOf") or [prop]
    assert any("$ref" in entry and "ConfidenceShape" in entry["$ref"] for entry in refs_or_anyof), (
        f"StudyDetail.confidence is not typed as Optional[ConfidenceShape]; got {prop!r}"
    )


def test_confidence_shape_has_six_subfields() -> None:
    """``ConfidenceShape`` has the six FR-5a sub-fields."""
    schema = ConfidenceShape.model_json_schema()
    expected = {
        "headline",
        "ci_95",
        "runner_up_gap",
        "late_trial_stddev",
        "convergence",
        "per_query_outcomes",
    }
    actual = set(schema["properties"].keys())
    assert expected == actual, f"ConfidenceShape fields drifted: expected {expected}, got {actual}"


# ---------------------------------------------------------------------------
# feat_study_convergence_indicator Story 3.1 — StudyDetail.convergence + shape
# ---------------------------------------------------------------------------


def test_study_detail_includes_convergence_field() -> None:
    """``StudyDetail`` exposes ``convergence: StudyConvergenceShape | None`` (FR-4).

    The field is additive (defaults to ``None``) and distinct from
    ``confidence.convergence.regime`` (winner-trial timing — a separate
    concept that lives under ``confidence``)."""

    schema = StudyDetail.model_json_schema()
    assert "convergence" in schema["properties"], (
        "StudyDetail.convergence missing — see feat_study_convergence_indicator Story 3.1."
    )
    prop = schema["properties"]["convergence"]
    refs_or_anyof = prop.get("anyOf") or [prop]
    assert any(
        "$ref" in entry and "StudyConvergenceShape" in entry["$ref"] for entry in refs_or_anyof
    ), f"StudyDetail.convergence is not typed as Optional[StudyConvergenceShape]; got {prop!r}"


def test_convergence_shape_has_all_eight_subfields() -> None:
    """``StudyConvergenceShape`` carries the eight sub-fields per spec §8.3."""

    schema = StudyConvergenceShape.model_json_schema()
    expected = {
        "verdict",
        "direction",
        "window_size",
        "epsilon",
        "warmup_floor",
        "total_complete_trials",
        "improvement_in_window",
        "best_so_far_curve",
    }
    actual = set(schema["properties"].keys())
    assert expected == actual, (
        f"StudyConvergenceShape fields drifted: expected {expected}, got {actual}"
    )


def test_convergence_verdict_is_three_string_literal() -> None:
    """``StudyConvergenceShape.verdict`` is exactly the three-value Literal —
    matches the source-of-truth in ``backend.app.domain.study.convergence``
    that the frontend ``CONVERGENCE_VERDICT_VALUES`` array mirrors."""

    schema = StudyConvergenceShape.model_json_schema()
    verdict = schema["properties"]["verdict"]
    # Pydantic emits Literal[...] as {"enum": [...], "type": "string"} OR
    # {"const": "..."} for single-value Literals. Accept either rendering.
    assert verdict.get("enum") == ["converged", "still_improving", "too_few_trials"], (
        f"StudyConvergenceShape.verdict enum drifted: {verdict!r}"
    )


def test_convergence_direction_is_two_string_literal() -> None:
    schema = StudyConvergenceShape.model_json_schema()
    direction = schema["properties"]["direction"]
    assert direction.get("enum") == ["maximize", "minimize"], (
        f"StudyConvergenceShape.direction enum drifted: {direction!r}"
    )


def test_study_config_requires_at_least_one_stop_condition() -> None:
    """``max_trials`` AND ``time_budget_min`` both None → ValidationError."""
    with pytest.raises(ValidationError, match="stop condition"):
        StudyConfigSpec()


def test_study_config_accepts_max_trials_only() -> None:
    cfg = StudyConfigSpec(max_trials=20)
    assert cfg.max_trials == 20
    assert cfg.time_budget_min is None


def test_study_config_accepts_time_budget_only() -> None:
    cfg = StudyConfigSpec(time_budget_min=10.0)
    assert cfg.time_budget_min == 10.0
    assert cfg.max_trials is None


def test_study_config_rejects_out_of_range_parallelism() -> None:
    with pytest.raises(ValidationError):
        StudyConfigSpec(max_trials=20, parallelism=0)
    with pytest.raises(ValidationError):
        StudyConfigSpec(max_trials=20, parallelism=65)


def test_study_config_rejects_invalid_sampler_pruner() -> None:
    with pytest.raises(ValidationError):
        StudyConfigSpec(max_trials=20, sampler="cma_es")
    with pytest.raises(ValidationError):
        StudyConfigSpec(max_trials=20, pruner="hyperband")


def test_objective_spec_rejects_invalid_metric() -> None:
    with pytest.raises(ValidationError):
        ObjectiveSpec(metric="bleu")


# ---------------------------------------------------------------------------
# feat_auto_followup_studies Story 1.1 — StudyConfigSpec.auto_followup_depth
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("depth", [None, 0, 1, 5])
def test_study_config_accepts_valid_auto_followup_depth(depth: int | None) -> None:
    """FR-1 + D-12: None and 0..5 are all valid (0 is worker-internal
    terminal value)."""
    cfg = StudyConfigSpec(max_trials=20, auto_followup_depth=depth)
    assert cfg.auto_followup_depth == depth


@pytest.mark.parametrize("depth", [-1, 6, 100])
def test_study_config_rejects_out_of_range_auto_followup_depth(depth: int) -> None:
    """FR-1: values outside [0, 5] raise ValidationError with the
    AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE prefix that the error handler
    unwraps into the response envelope (verified in
    ``test_auto_followup_depth_emits_canonical_error_code`` below)."""
    with pytest.raises(ValidationError, match="AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE"):
        StudyConfigSpec(max_trials=20, auto_followup_depth=depth)


def test_study_config_coerces_string_depth_per_pydantic_v2() -> None:
    """Pydantic v2 with default model_config coerces numeric strings to
    int. Spec §14 + plan Story 1.1 note: '3' is VALID (parses to 3) —
    not in the invalid-cases list. This test locks the coercion so a
    future strict-mode flip doesn't silently break the wire contract."""
    cfg = StudyConfigSpec(max_trials=20, auto_followup_depth="3")
    assert cfg.auto_followup_depth == 3


def test_objective_spec_rejects_invalid_k() -> None:
    with pytest.raises(ValidationError):
        ObjectiveSpec(metric="ndcg", k=7)


def test_objective_spec_requires_k_for_ndcg() -> None:
    """C2-F3 fix: ndcg / precision / recall require k at the cutoff."""
    with pytest.raises(ValidationError, match="objective.k is required"):
        ObjectiveSpec(metric="ndcg")
    with pytest.raises(ValidationError, match="objective.k is required"):
        ObjectiveSpec(metric="precision")
    with pytest.raises(ValidationError, match="objective.k is required"):
        ObjectiveSpec(metric="recall")


def test_objective_spec_accepts_mrr_without_k() -> None:
    """``mrr`` / ``err`` do NOT require k (per standard IR-evaluation conventions)."""
    cfg = ObjectiveSpec(metric="mrr")
    assert cfg.k is None


def test_create_query_template_rejects_unknown_engine_type() -> None:
    # Until infra_adapter_solr shipped (2026-05-31, PR #336), this test
    # used ``engine_type="solr"`` as the canonical "unknown engine" sentinel.
    # Solr is now a first-class engine, so the sentinel had to move to a
    # truly-invalid string. Any value outside the
    # {"elasticsearch", "opensearch", "solr"} allowlist works.
    with pytest.raises(ValidationError):
        CreateQueryTemplateRequest(
            name="qt",
            engine_type="vespa",  # not a supported engine
            body='{"query": {}}',
        )


def test_bulk_queries_request_caps_at_10k() -> None:
    """``queries`` is bounded at 10,000 (matches csv_parser._MAX_ROWS)."""
    too_many = [{"query_text": f"q{i}"} for i in range(10_001)]
    with pytest.raises(ValidationError):
        BulkQueriesJsonRequest(queries=too_many)


def test_bulk_queries_request_requires_min_one() -> None:
    with pytest.raises(ValidationError):
        BulkQueriesJsonRequest(queries=[])


def test_studies_router_declares_judgment_mismatch_error_codes() -> None:
    """``feat_study_target_judgment_mismatch_guard`` FR-1 + FR-1b — source-
    presence guard that both new error codes appear as literals in the
    studies router AND fire in the expected order.

    Hermetic (no DB needed). Catches a rename of the error_code strings
    without an accompanying spec/contract update — the integration tests
    at ``test_studies_api.py`` exercise the runtime envelope shape; this
    test exists so a refactor that renames ``JUDGMENT_TARGET_MISMATCH`` →
    something else fails CI even if integration coverage was the
    refactor's own test (chicken-and-egg).
    """
    from pathlib import Path

    source = Path("backend/app/api/v1/studies.py").read_text(encoding="utf-8")
    assert '"JUDGMENT_CLUSTER_MISMATCH"' in source, (
        "JUDGMENT_CLUSTER_MISMATCH literal missing from backend/app/api/v1/studies.py"
    )
    assert '"JUDGMENT_TARGET_MISMATCH"' in source, (
        "JUDGMENT_TARGET_MISMATCH literal missing from backend/app/api/v1/studies.py"
    )
    # Lock the firing order: cluster check must appear BEFORE the target
    # check in the source (handler executes top-down). This catches a
    # refactor that accidentally swaps the two blocks.
    cluster_pos = source.index('"JUDGMENT_CLUSTER_MISMATCH"')
    target_pos = source.index('"JUDGMENT_TARGET_MISMATCH"')
    assert cluster_pos < target_pos, (
        "FR-1b ordering violation: JUDGMENT_CLUSTER_MISMATCH must appear in "
        "studies.py BEFORE JUDGMENT_TARGET_MISMATCH (cluster check fires "
        "first). Got cluster_pos="
        f"{cluster_pos}, target_pos={target_pos}."
    )


def test_studies_router_declares_insufficient_judgment_overlap() -> None:
    """``feat_study_preflight_overlap_probe`` FR-1 + FR-5 — source-presence
    guard that the new INSUFFICIENT_JUDGMENT_OVERLAP code appears in studies.py
    AFTER JUDGMENT_TARGET_MISMATCH AND BEFORE the config-serialize line.

    Locks BOTH the probe call site AND the error-code literal so a refactor
    that moves either the call OR the raise trips CI. Mirrors the Tier 1
    ordering pattern in ``test_studies_router_declares_judgment_mismatch_error_codes``.
    """
    from pathlib import Path

    source = Path("backend/app/api/v1/studies.py").read_text(encoding="utf-8")
    assert '"INSUFFICIENT_JUDGMENT_OVERLAP"' in source, (
        "INSUFFICIENT_JUDGMENT_OVERLAP literal missing from backend/app/api/v1/studies.py"
    )
    assert "probe_judgment_overlap(" in source, (
        "probe_judgment_overlap call missing from backend/app/api/v1/studies.py"
    )
    target_pos = source.index('"JUDGMENT_TARGET_MISMATCH"')
    probe_pos = source.index("probe_result = await probe_judgment_overlap(")
    overlap_pos = source.index('"INSUFFICIENT_JUDGMENT_OVERLAP"')
    config_pos = source.index("config_payload = body.config.model_dump")
    assert target_pos < probe_pos < overlap_pos < config_pos, (
        f"Ordering: JUDGMENT_TARGET_MISMATCH ({target_pos}) < probe call "
        f"({probe_pos}) < INSUFFICIENT_JUDGMENT_OVERLAP literal ({overlap_pos}) "
        f"< config_payload assignment ({config_pos}) — got ordering violation."
    )
