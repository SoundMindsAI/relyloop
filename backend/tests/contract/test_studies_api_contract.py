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
)


def test_phase2_schemas_importable() -> None:
    """Every documented Phase 2 model is importable."""
    for cls in (
        BulkQueriesJsonRequest,
        BulkQueriesResponse,
        BulkQueryItem,
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


def test_objective_spec_rejects_invalid_k() -> None:
    with pytest.raises(ValidationError):
        ObjectiveSpec(metric="ndcg", k=7)


def test_create_query_template_rejects_unknown_engine_type() -> None:
    with pytest.raises(ValidationError):
        CreateQueryTemplateRequest(
            name="qt",
            engine_type="solr",
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
