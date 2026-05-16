"""Contract: every ``feat_data_table_primitive``-added query param is
declared in the OpenAPI schema so SDK generators + the frontend's
generated-types pipeline see them.

Catches the failure mode where a router gets ``?q=`` / ``?sort=`` added
but the param isn't surfaced on the endpoint's OpenAPI ``parameters``
list (e.g. forgotten ``Annotated[..., Query(...)]`` on a router
function).

Pure-Python smoke test — no DB, no live app — runs against
``app.openapi()`` with a stubbed settings env so it works on host shells
without ``DATABASE_URL_FILE`` set. Mirrors the
``test_openapi_surface.py`` pattern.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(scope="module", autouse=True)
def _settings_env(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """Stub Settings inputs so ``backend.app.main`` imports locally."""
    tmp = tmp_path_factory.mktemp("dt_qparams_env")
    db_url_file = tmp / "db_url"
    db_url_file.write_text("postgresql+asyncpg://x:y@localhost/test")
    pw_file = tmp / "pw"
    pw_file.write_text("test")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL_FILE", str(db_url_file))
        mp.setenv("POSTGRES_PASSWORD_FILE", str(pw_file))
        mp.setenv("REDIS_URL", "redis://redis:6379/0")
        from backend.app.core.settings import get_settings

        get_settings.cache_clear()
        yield
        get_settings.cache_clear()


@pytest.fixture(scope="module")
def openapi_spec() -> dict[str, Any]:
    from backend.app.main import app

    return app.openapi()


def _params_for(spec: dict[str, Any], method: str, path: str) -> set[str]:
    """Return the set of query-param names declared on ``method path``."""
    path_item = spec["paths"].get(path, {})
    op = path_item.get(method, {})
    out: set[str] = set()
    for param in op.get("parameters", []):
        if param.get("in") == "query":
            out.add(param["name"])
    return out


# Six endpoints gain ?q= per Story 1.2.
FTS_ENDPOINTS = [
    "/api/v1/clusters",
    "/api/v1/studies",
    "/api/v1/query-sets",
    "/api/v1/query-templates",
    "/api/v1/judgment-lists",
    "/api/v1/conversations",
]


@pytest.mark.parametrize("path", FTS_ENDPOINTS)
def test_q_param_declared_on_fts_endpoints(path: str, openapi_spec: dict[str, Any]) -> None:
    params = _params_for(openapi_spec, "get", path)
    assert "q" in params, f"{path} GET missing ?q= in OpenAPI parameters; declared: {params}"


# Six top-level endpoints + 1 per-list endpoint gain ?sort= per Story 1.3.
# The seventh sortable surface is /api/v1/judgment-lists/{id}/judgments,
# verified by a dedicated test below. Conversations intentionally does
# NOT gain ?sort= (per the plan's Story 1.3 endpoint list).
SORT_ENDPOINTS = [
    "/api/v1/clusters",
    "/api/v1/studies",
    "/api/v1/query-sets",
    "/api/v1/query-templates",
    "/api/v1/judgment-lists",
    "/api/v1/proposals",
]


@pytest.mark.parametrize("path", SORT_ENDPOINTS)
def test_sort_param_declared_on_sortable_endpoints(path: str, openapi_spec: dict[str, Any]) -> None:
    params = _params_for(openapi_spec, "get", path)
    assert "sort" in params, f"{path} GET missing ?sort= in OpenAPI parameters; declared: {params}"


def test_clusters_has_engine_type_and_environment_filters(
    openapi_spec: dict[str, Any],
) -> None:
    """Story 1.4 adds two new filters on /clusters."""
    params = _params_for(openapi_spec, "get", "/api/v1/clusters")
    assert "engine_type" in params
    assert "environment" in params


def test_query_templates_has_engine_type_filter(openapi_spec: dict[str, Any]) -> None:
    """Story 1.4 keeps the existing ?engine_type= filter declared."""
    params = _params_for(openapi_spec, "get", "/api/v1/query-templates")
    assert "engine_type" in params


def test_proposals_has_template_id_filter(openapi_spec: dict[str, Any]) -> None:
    """Story 1.5 / FR-3 adds ?template_id= on /proposals."""
    params = _params_for(openapi_spec, "get", "/api/v1/proposals")
    assert "template_id" in params


def test_judgment_lists_has_since_param(openapi_spec: dict[str, Any]) -> None:
    """Story 1.5 closes a pre-existing api-conventions drift on /judgment-lists."""
    params = _params_for(openapi_spec, "get", "/api/v1/judgment-lists")
    assert "since" in params


def test_conversations_has_since_param(openapi_spec: dict[str, Any]) -> None:
    """Same Story 1.5 drift-closure on /conversations."""
    params = _params_for(openapi_spec, "get", "/api/v1/conversations")
    assert "since" in params


def test_per_list_judgments_endpoint_has_sort_param(openapi_spec: dict[str, Any]) -> None:
    """Per-list judgments row sort (Story 1.3): ?sort=rating:desc etc."""
    params = _params_for(openapi_spec, "get", "/api/v1/judgment-lists/{judgment_list_id}/judgments")
    assert "sort" in params
