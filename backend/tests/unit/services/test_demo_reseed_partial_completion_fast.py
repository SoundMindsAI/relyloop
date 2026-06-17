# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Fast guard test for the demo-reseed PARTIAL-completion path.

`infra_solr_ci_readiness` made `reseed_demo_state` engine-tolerant: when an
engine is unreachable its scenario is skipped, the reseed still finishes
``status="complete"`` with a non-empty ``scenarios_skipped``, and exactly one
``demo_reseed_partial_completion_engines_unreachable`` WARN fires (AC-7). The
all-engines-unreachable verdict + the worker's failed-status mapping already
have fast unit coverage in ``test_demo_seeding_partial_completion.py``; the
END-TO-END partial path (ES + OpenSearch + rich seed, Solr skips) was only
asserted by the 13-19 min heavy-lane ``test_demo_seeding_ubi_full.py`` (needs
the full stack + a live OpenAI key).

This is the fast guard for that headline behavior. It drives the real
``reseed_demo_state`` orchestrator with every I/O helper monkeypatched to
canned success (chore_demo_reseed_partial_completion_fast_test, locked
approach b' — patch the module-level helpers, NOT an httpx-URL mock and NOT a
seam extraction, so the orchestrator structure is untouched and the test stays
a pure unit). ``is_engine_reachable`` reports only Solr down, so the loop must
skip exactly ``acme-kb-docs-solr`` and complete everything else.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.services import demo_seeding
from backend.app.services.demo_seeding import (
    SCENARIOS,
    AllEnginesUnreachableError,
    DemoSeedingError,
    ReseedStatusResponse,
    reseed_demo_state,
)

# Union of every scenario's query texts -> a fake id. The reseed body fetches
# the query rows for each scenario and raises DemoSeedingError if any of its
# query texts is absent, so the fake GET returns the full union (each scenario
# filters down to its own texts; extras are harmless).
_ALL_QUERY_TEXTS: list[str] = [
    q["query_text"] for scenario in SCENARIOS for q in scenario["queries"]
]


def _install_canned_seed_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch every demo_seeding I/O helper to canned success.

    Leaves the orchestrator's control flow (reachability gating, skip
    accounting, the partial-completion WARN, status assignment) entirely real —
    that flow is exactly what this test guards.
    """
    counter = {"n": 0}

    async def _fake_post(
        client: Any,
        url: str,
        *,
        json: Any = None,
        auth: Any = None,
        client_label: str = "",
        step: str = "",
    ) -> dict[str, Any]:
        counter["n"] += 1
        n = counter["n"]
        # Order matters: the queries sub-resource ends with "/queries" and must
        # be matched BEFORE the bare "/query-sets" create.
        if url.endswith("/queries"):
            return {}
        if url.endswith("/clusters"):
            return {"id": f"cluster-{n}"}
        if url.endswith("/query-templates"):
            return {"id": f"template-{n}"}
        if url.endswith("/query-sets"):
            return {"id": f"qset-{n}"}
        if url.endswith("/judgment-lists/import"):
            return {"id": f"jlist-{n}"}
        if url.endswith("/judgments/generate-from-ubi"):
            return {"judgment_list_id": f"ubi-jlist-{n}"}
        # Engine _refresh and anything else: shape not consumed.
        return {}

    async def _fake_get(
        client: Any,
        url: str,
        *,
        params: Any = None,
        auth: Any = None,
        client_label: str = "",
        step: str = "",
    ) -> dict[str, Any]:
        return {
            "data": [
                {"query_text": text, "id": f"q-{i}"} for i, text in enumerate(_ALL_QUERY_TEXTS)
            ]
        }

    async def _fake_put(
        client: Any,
        url: str,
        *,
        json: Any = None,
        auth: Any = None,
        client_label: str = "",
        step: str = "",
    ) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(demo_seeding, "_post", _fake_post)
    monkeypatch.setattr(demo_seeding, "_get", _fake_get)
    monkeypatch.setattr(demo_seeding, "_put", _fake_put)
    # High-level seed helpers — return the scalars the body consumes.
    monkeypatch.setattr(
        demo_seeding,
        "_seed_real_study_for_scenario",
        AsyncMock(side_effect=lambda *a, **k: f"study-{counter['n']}"),
    )
    monkeypatch.setattr(
        demo_seeding, "_seed_rich_scenario", AsyncMock(return_value="rich-study-id")
    )
    monkeypatch.setattr(demo_seeding, "ensure_ubi_indices", AsyncMock(return_value=None))
    monkeypatch.setattr(demo_seeding, "seed_synthetic_ubi", AsyncMock(return_value=100))
    monkeypatch.setattr(
        demo_seeding, "_poll_judgment_list_until_terminal", AsyncMock(return_value=None)
    )
    # Pure-domain generator: return empty (events not consumed beyond a count
    # that seed_synthetic_ubi mocks).
    monkeypatch.setattr(demo_seeding, "fabricate_ubi_for_scenario", lambda **k: ([], []))


def _only_solr_unreachable() -> Any:
    """An ``is_engine_reachable`` replacement: every engine up except Solr."""

    async def _probe(url: str, engine_type: str, **kwargs: Any) -> bool:
        # **kwargs absorbs the real is_engine_reachable's keyword-only
        # `timeout_s` (and any future kwargs) so the mock can't TypeError.
        return engine_type != "solr"

    return _probe


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=None)
    db.commit = AsyncMock(return_value=None)
    return db


def _mock_engine_client() -> AsyncMock:
    """Engine client whose only DIRECT call (Step 1b index DELETE) returns a
    tolerated 204. Every other engine call routes through the monkeypatched
    ``_put`` / ``_post`` helpers."""
    client = AsyncMock()
    client.delete = AsyncMock(return_value=MagicMock(status_code=204))
    return client


async def test_partial_completion_skips_only_solr_and_warns_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """ES/OS/rich seed, Solr skips: status=complete, one skip, one WARN."""
    _install_canned_seed_path(monkeypatch)
    monkeypatch.setattr(demo_seeding, "is_engine_reachable", _only_solr_unreachable())

    captured: dict[str, ReseedStatusResponse] = {}

    async def _capture(progress: ReseedStatusResponse) -> None:
        captured["progress"] = progress

    with caplog.at_level(logging.WARNING, logger=demo_seeding.logger.name):
        summary = await reseed_demo_state(
            _mock_db(),
            MagicMock(),  # api_client — unused (every helper is mocked)
            _mock_engine_client(),
            status_callback=_capture,
        )

    progress = captured["progress"]
    # Exactly the Solr scenario skipped; nothing else.
    assert progress.scenarios_skipped == ["acme-kb-docs-solr"]
    # Partial != failure: the reseed completes.
    assert progress.status == "complete"
    # The 4 reachable SCENARIOS + the rich scenario all completed.
    assert progress.scenarios_completed == len(SCENARIOS) - 1 + 1
    assert summary.studies_completed >= len(SCENARIOS) - 1 + 1
    # AC-7: exactly one partial-completion WARN.
    partial_warns = [
        r
        for r in caplog.records
        if r.getMessage() == "demo_reseed_partial_completion_engines_unreachable"
    ]
    assert len(partial_warns) == 1
    # The structured `extra={"scenarios_skipped": ...}` rides on the LogRecord
    # as a runtime attribute (getattr keeps mypy happy — LogRecord has no
    # static field for it).
    assert getattr(partial_warns[0], "scenarios_skipped", None) == ["acme-kb-docs-solr"]


async def test_reachable_scenario_failure_is_hard_error_not_a_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-3: a reachable scenario that fails mid-seed raises a generic
    ``DemoSeedingError`` (NOT ``AllEnginesUnreachableError``) and is never
    silently moved into ``scenarios_skipped``."""
    _install_canned_seed_path(monkeypatch)
    monkeypatch.setattr(demo_seeding, "is_engine_reachable", _only_solr_unreachable())
    # Make a REACHABLE scenario fail mid-seed (the study-create step).
    monkeypatch.setattr(
        demo_seeding,
        "_seed_real_study_for_scenario",
        AsyncMock(side_effect=DemoSeedingError("acme-products-prod/create_study: HTTP 503")),
    )

    captured: dict[str, ReseedStatusResponse] = {}

    async def _capture(progress: ReseedStatusResponse) -> None:
        captured["progress"] = progress

    with pytest.raises(DemoSeedingError) as exc_info:
        await reseed_demo_state(
            _mock_db(), MagicMock(), _mock_engine_client(), status_callback=_capture
        )

    # A mid-seed failure on a REACHABLE engine is a hard error, never the
    # tolerated all-unreachable verdict.
    assert not isinstance(exc_info.value, AllEnginesUnreachableError)
    # And the failing scenario is NOT in scenarios_skipped — skip accounting
    # only happens at the reachability gate, never in the seed body. progress is
    # always captured (several _emit_progress calls precede the step-2h study
    # failure), so access it directly — a missing capture should fail the test.
    progress = captured["progress"]
    assert "acme-products-prod" not in progress.scenarios_skipped


# ---------------------------------------------------------------------------
# feat_selective_engine_startup_and_demo Story 2.2 / FR-5.
# The orchestrator's new ``engines`` parameter filters scenarios by
# engine_type. User-excluded scenarios get reason="user_excluded";
# unreachable scenarios keep reason="unreachable". The rich ESCI scenario
# (engine_type=elasticsearch) is filtered alongside the small SCENARIOS loop.
# ---------------------------------------------------------------------------


def _all_engines_reachable() -> Any:
    """Replacement for is_engine_reachable: every engine reports up."""

    async def _probe(_url: str, _engine_type: str, **_kwargs: Any) -> bool:
        return True

    return _probe


async def test_engines_filter_user_excludes_opensearch_and_solr_scenarios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """engines=['elasticsearch'] → OS + Solr small scenarios skipped as user_excluded.

    ES scenarios (small + rich) attempt and complete; the rich scenario
    is included via the parallel rich-path gate.
    """
    _install_canned_seed_path(monkeypatch)
    monkeypatch.setattr(demo_seeding, "is_engine_reachable", _all_engines_reachable())

    captured: dict[str, ReseedStatusResponse] = {}

    async def _capture(progress: ReseedStatusResponse) -> None:
        captured["progress"] = progress

    await reseed_demo_state(
        _mock_db(),
        MagicMock(),
        _mock_engine_client(),
        status_callback=_capture,
        engines=["elasticsearch"],
    )

    progress = captured["progress"]
    # Find scenarios by engine_type for assertion clarity (no dependency on
    # SCENARIOS literal slug ordering).
    os_slugs = {cast_slug(s) for s in SCENARIOS if s["engine_type"] == "opensearch"}
    solr_slugs = {cast_slug(s) for s in SCENARIOS if s["engine_type"] == "solr"}
    es_slugs = {cast_slug(s) for s in SCENARIOS if s["engine_type"] == "elasticsearch"}

    # Every non-ES small scenario is in scenarios_skipped with user_excluded.
    for slug in os_slugs | solr_slugs:
        assert slug in progress.scenarios_skipped
        assert progress.scenarios_skipped_reasons[slug] == "user_excluded"

    # ES scenarios attempted (not skipped).
    for slug in es_slugs:
        assert slug not in progress.scenarios_skipped

    # The rich ES scenario is NOT in user_excluded (ES was selected).
    assert "acme-products-rich-prod" not in progress.scenarios_skipped
    assert progress.status == "complete"


async def test_engines_filter_user_excludes_elasticsearch_excludes_rich_scenario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """engines=['opensearch'] → every ES scenario (small + rich) gets user_excluded.

    Guards FR-5's "apply the same filter to the rich ESCI scenario" requirement.
    """
    _install_canned_seed_path(monkeypatch)
    monkeypatch.setattr(demo_seeding, "is_engine_reachable", _all_engines_reachable())

    captured: dict[str, ReseedStatusResponse] = {}

    async def _capture(progress: ReseedStatusResponse) -> None:
        captured["progress"] = progress

    await reseed_demo_state(
        _mock_db(),
        MagicMock(),
        _mock_engine_client(),
        status_callback=_capture,
        engines=["opensearch"],
    )

    progress = captured["progress"]
    # Rich scenario is ES → user_excluded.
    assert "acme-products-rich-prod" in progress.scenarios_skipped
    assert progress.scenarios_skipped_reasons["acme-products-rich-prod"] == "user_excluded"


async def test_engines_filter_mixed_reasons_user_excluded_and_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """engines=['elasticsearch','opensearch'] + Solr unreachable.

    Solr scenarios are user_excluded (filtered BEFORE the reachability
    gate); OS + ES scenarios complete normally. Distinct reasons for
    each slug.
    """
    _install_canned_seed_path(monkeypatch)
    monkeypatch.setattr(demo_seeding, "is_engine_reachable", _only_solr_unreachable())

    captured: dict[str, ReseedStatusResponse] = {}

    async def _capture(progress: ReseedStatusResponse) -> None:
        captured["progress"] = progress

    await reseed_demo_state(
        _mock_db(),
        MagicMock(),
        _mock_engine_client(),
        status_callback=_capture,
        engines=["elasticsearch", "opensearch"],
    )

    progress = captured["progress"]
    # Solr scenarios — user_excluded fires FIRST (before reachability), so
    # they're reported with reason "user_excluded" even though Solr is also
    # unreachable. This is correct: from the operator's POV, they deselected
    # Solr; the reachability state is moot.
    for slug, reason in progress.scenarios_skipped_reasons.items():
        if "solr" in slug:
            assert reason == "user_excluded", (
                f"Solr slug {slug} should be user_excluded (filter runs before "
                f"reachability), got {reason!r}"
            )


async def test_engines_filter_none_preserves_today_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """engines=None is the back-compat sentinel — every reachable scenario runs.

    Same shape as the existing partial-completion test but with the new
    ``engines`` parameter explicitly None'd to prove the back-compat
    contract.
    """
    _install_canned_seed_path(monkeypatch)
    monkeypatch.setattr(demo_seeding, "is_engine_reachable", _only_solr_unreachable())

    captured: dict[str, ReseedStatusResponse] = {}

    async def _capture(progress: ReseedStatusResponse) -> None:
        captured["progress"] = progress

    await reseed_demo_state(
        _mock_db(),
        MagicMock(),
        _mock_engine_client(),
        status_callback=_capture,
        engines=None,
    )

    progress = captured["progress"]
    # Solr scenario skipped with reason "unreachable" (not "user_excluded").
    assert "acme-kb-docs-solr" in progress.scenarios_skipped
    assert progress.scenarios_skipped_reasons["acme-kb-docs-solr"] == "unreachable"
    # No user_excluded reasons recorded — engines was None.
    assert not any(r == "user_excluded" for r in progress.scenarios_skipped_reasons.values())


def cast_slug(scenario: dict[str, Any]) -> str:
    """Helper: scenario['slug'] is typed Any in SCENARIOS — strip the cast."""
    return cast_str(scenario["slug"])


def cast_str(value: Any) -> str:
    return value
