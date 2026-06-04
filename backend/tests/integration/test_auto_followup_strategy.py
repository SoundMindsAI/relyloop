# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``follow_suggestions`` strategy dispatch (Story 2.2).

Real Postgres + real Redis. Covers the eight worker-level assertions from
the plan's Story 2.2 DoD: AC-3 (legacy byte-identical), AC-6 (narrow
consumed), AC-7 (swap branches template_id), AC-8 (cycle guard → widen +
dropped_template_ids in telemetry), AC-9 (fallback on text-only), AC-10
(strategy inherited verbatim), AC-17 (deleted swap target → WARN +
fallback), AC-18 (no parent-kind leak), plus the P1-B4 exception
fallback. Companion to ``test_auto_followup.py`` (the legacy-path tests),
which MUST continue passing unmodified (backward-compat gate, FR-3).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.llm.budget_gate import daily_key
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


# A small valid SearchSpace dict reused across digest fixtures.
_VALID_SEARCH_SPACE_DICT: dict[str, Any] = {
    "params": {"title_boost": {"type": "float", "low": 0.5, "high": 2.0}},
}


async def _seed_parent_with_digest(
    *,
    strategy: str | None,
    auto_followup_depth: int | None = 3,
    digest_followups: list[dict[str, Any]] | None = None,
    visited_template_ids: list[str] | None = None,
    parent_selected_kind: str | None = None,
    extra_template_ids: int = 0,
) -> dict[str, str]:
    """Seed the chain: cluster + parent template + (optional) extra
    swap-target templates + query_set + judgment_list + parent study +
    20 complete trials + (optional) digest row.

    Args:
        strategy: ``auto_followup_strategy`` to set on parent's config.
            ``None`` writes no key (legacy path).
        auto_followup_depth: parent depth.
        digest_followups: ``suggested_followups`` JSONB array — if
            ``None``, no digest row is created at all (tests that
            exercise the missing-digest defensive path).
        visited_template_ids: pre-existing visited-list to seed on
            ``parent.config`` (for the AC-8 cycle-guard test).
        parent_selected_kind: pre-existing ``auto_followup_selected_kind``
            to seed on parent (for the AC-18 stale-leak test).
        extra_template_ids: number of additional swap-target query
            templates to seed (for the swap_template tests). Their ids
            are returned under ``extra_template_ids`` key.
    """
    suffix = uuid.uuid4().hex[:8]
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"af-strat-cluster-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"af-strat-tmpl-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match": {"body": "{{ query }}"}}}',
            declared_params={"title_boost": "float"},
            version=1,
        )
        extra_ids: list[str] = []
        for i in range(extra_template_ids):
            extra = await repo.create_query_template(
                db,
                id=str(uuid.uuid4()),
                name=f"af-strat-extra-{i}-{suffix}",
                engine_type="elasticsearch",
                body='{"query": {"match": {"body": "{{ query }}"}}}',
                declared_params={"title_boost": "float"},
                version=1,
            )
            extra_ids.append(extra.id)
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"af-strat-qs-{suffix}",
            cluster_id=cluster.id,
        )
        await repo.create_query(
            db,
            id=str(uuid.uuid4()),
            query_set_id=query_set.id,
            query_text="q1",
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"af-strat-jl-{suffix}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="r",
            status="complete",
            failed_reason=None,
            calibration=None,
        )

        parent_id = str(uuid.uuid4())
        config: dict[str, Any] = {"max_trials": 20}
        if auto_followup_depth is not None:
            config["auto_followup_depth"] = auto_followup_depth
        if strategy is not None:
            config["auto_followup_strategy"] = strategy
        if visited_template_ids is not None:
            config["auto_followup_visited_template_ids"] = list(visited_template_ids)
        if parent_selected_kind is not None:
            config["auto_followup_selected_kind"] = parent_selected_kind
        parent = await repo.create_study(
            db,
            id=parent_id,
            name=f"af-strat-parent-{suffix}",
            cluster_id=cluster.id,
            target="stub-index",
            template_id=template.id,
            query_set_id=query_set.id,
            judgment_list_id=jl.id,
            search_space={"params": {"title_boost": {"type": "float", "low": 0.5, "high": 5.0}}},
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            config=config,
            status="completed",
            optuna_study_name=parent_id,
        )

        # 20 complete trials — first decile (first 2) at metric=0.30,
        # rest at 0.40. parent.best_metric=0.50 ⇒ lift=0.20 > epsilon.
        best_trial_id: str | None = None
        for i in range(20):
            metric = 0.30 if i < 2 else 0.40
            tid = str(uuid.uuid4())
            await repo.create_trial(
                db,
                id=tid,
                study_id=parent.id,
                optuna_trial_number=i,
                params={"title_boost": 2.0 + (i / 100)},
                primary_metric=metric,
                metrics={"ndcg@10": metric},
                duration_ms=10,
                status="complete",
                error=None,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
            )
            if i == 19:
                best_trial_id = tid

        from backend.app.services.study_state import _GUARD_KEY

        db.sync_session.info[_GUARD_KEY] = True
        try:
            parent.best_metric = 0.50
            parent.best_trial_id = best_trial_id
            await db.flush()
        finally:
            db.sync_session.info.pop(_GUARD_KEY, None)

        if digest_followups is not None:
            await repo.create_digest(
                db,
                id=str(uuid.uuid4()),
                study_id=parent.id,
                narrative="seeded digest for strategy dispatch tests",
                parameter_importance={"title_boost": 1.0},
                recommended_config={"title_boost": 1.5},
                suggested_followups=digest_followups,
                generated_by="local:test-fixture",
            )

        await db.commit()

    return {
        "parent_id": parent_id,
        "cluster_id": cluster.id,
        "template_id": template.id,
        "query_set_id": query_set.id,
        "judgment_list_id": jl.id,
        # Comma-joined for keep-it-flat dict access; tests split when needed.
        "extra_template_ids": ",".join(extra_ids),
    }


async def _clear_budget_key() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await redis.delete(daily_key(datetime.now(UTC)))
    finally:
        await redis.aclose()


def _make_arq_ctx() -> tuple[dict[str, Any], MagicMock]:
    arq_pool = MagicMock()
    arq_pool.enqueue_job = AsyncMock(return_value=None)
    ctx: dict[str, Any] = {"arq_pool": arq_pool}
    return ctx, arq_pool


async def _get_child(parent_id: str) -> Any:
    factory = get_session_factory()
    async with factory() as db:
        children = await repo.list_children_of_study(db, parent_id)
    assert len(children) == 1, f"expected exactly 1 child, got {len(children)}"
    return children[0]


# ---------------------------------------------------------------------------
# AC-3 — legacy/default path: no strategy key → no new config keys on child
# (byte-identical to pre-feature behavior).
# ---------------------------------------------------------------------------


async def test_ac3_legacy_path_persists_no_new_keys() -> None:
    """Per FR-3 + AC-3 + D-12: a parent with NO ``auto_followup_strategy``
    key produces a child whose ``config`` contains NEITHER
    ``auto_followup_selected_kind`` NOR ``auto_followup_visited_template_ids``.
    Backward-compat gate — also verified by ``test_auto_followup.py``
    passing unmodified."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    seeded = await _seed_parent_with_digest(strategy=None, digest_followups=None)
    ctx, _ = _make_arq_ctx()

    await enqueue_followup_study(ctx, seeded["parent_id"])

    child = await _get_child(seeded["parent_id"])
    assert child.template_id == seeded["template_id"]  # same template
    assert "auto_followup_selected_kind" not in child.config
    assert "auto_followup_visited_template_ids" not in child.config
    assert "auto_followup_strategy" not in child.config  # inherited (was None)
    assert child.config["auto_followup_depth"] == 2  # decremented


# ---------------------------------------------------------------------------
# AC-6 — follow_suggestions consumes top-narrow follow-up
# ---------------------------------------------------------------------------


async def test_ac6_follow_suggestions_narrow_consumed() -> None:
    """Top executable is a `narrow` → child uses its search_space verbatim,
    keeps parent.template_id, persists selected_kind="narrow" and the
    visited list at [parent.template_id] (no growth since template
    unchanged — D-12 ordered-unique)."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    seeded = await _seed_parent_with_digest(
        strategy="follow_suggestions",
        digest_followups=[
            {
                "kind": "narrow",
                "rationale": "narrow around the winner",
                "search_space": _VALID_SEARCH_SPACE_DICT,
            },
            {"kind": "text", "rationale": "ignored", "search_space": None},
        ],
    )
    ctx, _ = _make_arq_ctx()

    await enqueue_followup_study(ctx, seeded["parent_id"])

    child = await _get_child(seeded["parent_id"])
    assert child.template_id == seeded["template_id"]  # narrow keeps parent template
    assert child.config["auto_followup_selected_kind"] == "narrow"
    assert child.config["auto_followup_visited_template_ids"] == [seeded["template_id"]]
    assert child.config["auto_followup_strategy"] == "follow_suggestions"  # AC-10
    # The child's search_space mirrors the follow-up's bounds, not the
    # ±50% narrow on the parent's bounds.
    assert child.search_space == _VALID_SEARCH_SPACE_DICT


# ---------------------------------------------------------------------------
# AC-7 — swap_template branches the child's template_id
# ---------------------------------------------------------------------------


async def test_ac7_follow_suggestions_swap_template_branches_template_id() -> None:
    """Top executable is a `swap_template` → child.template_id = swap
    target, search_space from the follow-up verbatim, visited list grows
    to [parent.template_id, swap_target_template_id]."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    seeded = await _seed_parent_with_digest(
        strategy="follow_suggestions",
        extra_template_ids=1,
        digest_followups=[],  # filled in after we know the extra id
    )
    swap_target_id = seeded["extra_template_ids"].split(",")[0]
    # Re-seed digest now that we have the swap target's id. (Two-stage seed
    # keeps the helper signature simple; only this test needs it.)
    factory = get_session_factory()
    async with factory() as db:
        await repo.create_digest(
            db,
            id=str(uuid.uuid4()),
            study_id=seeded["parent_id"],
            narrative="seeded digest",
            parameter_importance={"title_boost": 1.0},
            recommended_config={"title_boost": 1.5},
            suggested_followups=[
                {
                    "kind": "swap_template",
                    "rationale": "function-score template is a better fit",
                    "template_id": swap_target_id,
                    "search_space": _VALID_SEARCH_SPACE_DICT,
                }
            ],
            generated_by="local:test-fixture",
        )
        await db.commit()

    ctx, _ = _make_arq_ctx()
    await enqueue_followup_study(ctx, seeded["parent_id"])

    child = await _get_child(seeded["parent_id"])
    assert child.template_id == swap_target_id
    assert child.template_id != seeded["template_id"]  # branched away from parent
    assert child.config["auto_followup_selected_kind"] == "swap_template"
    assert child.config["auto_followup_visited_template_ids"] == [
        seeded["template_id"],
        swap_target_id,
    ]
    assert child.search_space == _VALID_SEARCH_SPACE_DICT


# ---------------------------------------------------------------------------
# AC-9 — fallback to narrow when digest has only text follow-ups
# ---------------------------------------------------------------------------


async def test_ac9_text_only_digest_falls_back_to_narrow_default() -> None:
    """`follow_suggestions` strategy + text-only digest → narrow fallback,
    child.template_id stays at parent.template_id, selected_kind =
    "narrow_default". Chain does NOT stall."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    seeded = await _seed_parent_with_digest(
        strategy="follow_suggestions",
        digest_followups=[
            {"kind": "text", "rationale": "re-run with bigger budget", "search_space": None},
            {"kind": "text", "rationale": "investigate category X", "search_space": None},
        ],
    )
    ctx, _ = _make_arq_ctx()

    await enqueue_followup_study(ctx, seeded["parent_id"])

    child = await _get_child(seeded["parent_id"])
    assert child.template_id == seeded["template_id"]
    assert child.config["auto_followup_selected_kind"] == "narrow_default"
    assert child.config["auto_followup_visited_template_ids"] == [seeded["template_id"]]
    assert child.config["auto_followup_strategy"] == "follow_suggestions"


# ---------------------------------------------------------------------------
# AC-8 — cycle guard drops swap-to-visited; widen selected; dropped recorded
# ---------------------------------------------------------------------------


async def test_ac8_cycle_guard_drops_swap_to_visited_and_selects_widen() -> None:
    """Worker-level coverage per P1-B3. Parent's visited list pre-populated
    with the swap target's id (simulating a multi-link chain that already
    visited template B). Digest emits both a swap-to-B (dropped) and a
    widen. Child runs the widen; visited list stays the same (widen keeps
    parent template)."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    # Seed with extra templates + pre-populated visited list including both.
    seeded = await _seed_parent_with_digest(
        strategy="follow_suggestions",
        extra_template_ids=1,
        visited_template_ids=None,  # set below once we know the extra id
        digest_followups=[],
    )
    swap_target_id = seeded["extra_template_ids"].split(",")[0]
    # Pre-populate the parent's visited list to include the swap target
    # AND the parent's template.
    factory = get_session_factory()
    async with factory() as db:
        # Re-fetch parent and update its config in-place.
        parent = await repo.get_study(db, seeded["parent_id"])
        assert parent is not None
        new_config = dict(parent.config)
        new_config["auto_followup_visited_template_ids"] = [seeded["template_id"], swap_target_id]
        parent.config = new_config
        await db.flush()
        await repo.create_digest(
            db,
            id=str(uuid.uuid4()),
            study_id=seeded["parent_id"],
            narrative="seeded digest",
            parameter_importance={"title_boost": 1.0},
            recommended_config={"title_boost": 1.5},
            suggested_followups=[
                {
                    "kind": "swap_template",
                    "rationale": "to already-visited",
                    "template_id": swap_target_id,
                    "search_space": _VALID_SEARCH_SPACE_DICT,
                },
                {
                    "kind": "widen",
                    "rationale": "widen kept on the same template",
                    "search_space": _VALID_SEARCH_SPACE_DICT,
                },
            ],
            generated_by="local:test-fixture",
        )
        await db.commit()

    ctx, _ = _make_arq_ctx()
    await enqueue_followup_study(ctx, seeded["parent_id"])

    child = await _get_child(seeded["parent_id"])
    # Widen kept the same template, but the visited list was inherited
    # verbatim (parent already had the swap target in there).
    assert child.template_id == seeded["template_id"]
    assert child.config["auto_followup_selected_kind"] == "widen"
    # Inherited ordered-unique: [parent, swap_target]; adding parent again
    # via the ordered-unique dedup keeps it at length 2.
    assert child.config["auto_followup_visited_template_ids"] == [
        seeded["template_id"],
        swap_target_id,
    ]


# ---------------------------------------------------------------------------
# AC-10 — strategy inherited verbatim down the chain
# (subsumed by AC-6/AC-7/AC-9 assertions on child.config.auto_followup_strategy)
# ---------------------------------------------------------------------------


async def test_ac10_strategy_inherited_verbatim() -> None:
    """Parent on follow_suggestions → child also has
    ``auto_followup_strategy == "follow_suggestions"``. The child's own
    autopilot will dispatch the same branch when its digest lands."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    seeded = await _seed_parent_with_digest(
        strategy="follow_suggestions",
        digest_followups=[
            {
                "kind": "narrow",
                "rationale": "any executable",
                "search_space": _VALID_SEARCH_SPACE_DICT,
            }
        ],
    )
    ctx, _ = _make_arq_ctx()
    await enqueue_followup_study(ctx, seeded["parent_id"])
    child = await _get_child(seeded["parent_id"])
    assert child.config["auto_followup_strategy"] == "follow_suggestions"


# ---------------------------------------------------------------------------
# AC-17 — deleted swap target → WARN + fallback
# ---------------------------------------------------------------------------


async def test_ac17_deleted_swap_target_falls_back_to_narrow(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Digest points at a template_id that doesn't exist (deleted between
    persist + dispatch). Worker logs WARN with event_type
    ``auto_followup_swap_target_missing`` and falls back to narrow on
    parent.template_id (selected_kind = "narrow_default")."""
    import logging

    from backend.workers.auto_followup import enqueue_followup_study

    caplog.set_level(logging.WARNING, logger="backend.workers.auto_followup")

    await _clear_budget_key()
    fake_template_id = str(uuid.uuid4())  # never created in DB
    seeded = await _seed_parent_with_digest(
        strategy="follow_suggestions",
        digest_followups=[
            {
                "kind": "swap_template",
                "rationale": "swap to deleted",
                "template_id": fake_template_id,
                "search_space": _VALID_SEARCH_SPACE_DICT,
            },
        ],
    )
    ctx, _ = _make_arq_ctx()

    await enqueue_followup_study(ctx, seeded["parent_id"])

    child = await _get_child(seeded["parent_id"])
    assert child.template_id == seeded["template_id"]  # fell back
    assert child.config["auto_followup_selected_kind"] == "narrow_default"
    # WARN event captured.
    event_types = [
        getattr(r, "event_type", None) for r in caplog.records if getattr(r, "event_type", None)
    ]
    assert "auto_followup_swap_target_missing" in event_types


# ---------------------------------------------------------------------------
# AC-18 — parent's stale auto_followup_selected_kind does NOT leak to child
# ---------------------------------------------------------------------------


async def test_ac18_legacy_path_pops_inherited_selected_kind() -> None:
    """Defensive contract per AC-18. A parent that happens to carry
    ``auto_followup_selected_kind = "widen"`` on its config (e.g. it was
    itself a chain-link) — but is on the legacy (no-strategy / "narrow")
    path — must produce a child whose config does NOT carry that key at
    all. The worker pops the inherited value before INSERT."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    seeded = await _seed_parent_with_digest(
        strategy=None,  # legacy path
        parent_selected_kind="widen",  # stale inherited value
        digest_followups=None,
    )
    ctx, _ = _make_arq_ctx()

    await enqueue_followup_study(ctx, seeded["parent_id"])

    child = await _get_child(seeded["parent_id"])
    assert "auto_followup_selected_kind" not in child.config


async def test_ac18_follow_suggestions_overwrites_stale_parent_kind() -> None:
    """Same defensive contract on the follow_suggestions path: even
    if parent carries a stale ``"widen"``, the child reflects the
    selection THIS worker invocation made (here: ``"narrow"`` from the
    digest's first executable), NOT the inherited value."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    seeded = await _seed_parent_with_digest(
        strategy="follow_suggestions",
        parent_selected_kind="widen",
        digest_followups=[
            {
                "kind": "narrow",
                "rationale": "narrow",
                "search_space": _VALID_SEARCH_SPACE_DICT,
            }
        ],
    )
    ctx, _ = _make_arq_ctx()

    await enqueue_followup_study(ctx, seeded["parent_id"])

    child = await _get_child(seeded["parent_id"])
    assert child.config["auto_followup_selected_kind"] == "narrow"


# ---------------------------------------------------------------------------
# P1-B4 — unexpected error in dispatch → defensive fallback + WARN
# ---------------------------------------------------------------------------


async def test_exception_in_follow_suggestions_dispatch_falls_back_to_narrow(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Force a synthetic exception inside the follow_suggestions dispatch
    block (by monkeypatching ``select_executable_followup`` to raise). The
    worker must catch it, emit the ``auto_followup_strategy_dispatch_error``
    WARN, and create the child on the legacy narrow path. Chain reliability
    MUST NOT regress vs the legacy path (spec §13 Reliability + P1-B4)."""
    import logging

    from backend.workers import auto_followup as worker_module
    from backend.workers.auto_followup import enqueue_followup_study

    caplog.set_level(logging.WARNING, logger="backend.workers.auto_followup")

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("synthetic failure for the defensive fallback test")

    monkeypatch.setattr(worker_module, "select_executable_followup", boom)

    await _clear_budget_key()
    seeded = await _seed_parent_with_digest(
        strategy="follow_suggestions",
        digest_followups=[
            {
                "kind": "narrow",
                "rationale": "would-be selection",
                "search_space": _VALID_SEARCH_SPACE_DICT,
            },
        ],
    )
    ctx, _ = _make_arq_ctx()

    # Should NOT raise — the worker swallows + falls back.
    await enqueue_followup_study(ctx, seeded["parent_id"])

    child = await _get_child(seeded["parent_id"])
    assert child.template_id == seeded["template_id"]
    # Per D-12: fallback under follow_suggestions persists "narrow_default".
    assert child.config["auto_followup_selected_kind"] == "narrow_default"
    event_types = [
        getattr(r, "event_type", None) for r in caplog.records if getattr(r, "event_type", None)
    ]
    assert "auto_followup_strategy_dispatch_error" in event_types
