"""Shared helpers for the feat_digest_proposal integration tests.

Centralizes the boilerplate:

* :func:`seed_completed_study` — creates a complete (cluster, query_set,
  query_template, judgment_list, study) chain with status='completed' +
  ``best_metric`` set + a winning ``trials`` row + an orchestrator-style
  pending ``proposals`` row.
* :func:`make_openai_response` — synth :class:`openai.types.chat.ChatCompletion`
  shapes for mocking.
* :func:`stub_capability_ok` / :func:`stub_capability_fail` — populate
  the Redis capability cache so the worker's preflight branches as needed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.llm.capability_check import CACHE_TTL_SECONDS, ProbeStatus, cache_key
from backend.app.llm.capability_models import CapabilityResult


async def seed_completed_study(
    *,
    best_metric: float | None = 0.762,
    baseline_metric: float | None = 0.612,
    best_trial_params: dict[str, Any] | None = None,
    declared_params: dict[str, Any] | None = None,
    add_pending_proposal: bool = True,
    study_status: str = "completed",
) -> dict[str, str]:
    """Insert a completed study + winning trial + (optionally) pending proposal.

    Returns a dict with ``study_id``, ``cluster_id``, ``template_id``,
    ``query_set_id``, ``judgment_list_id``, ``trial_id``, and ``proposal_id``
    (None when ``add_pending_proposal=False``).

    Defaults model the AC-1 happy-path scenario:
    baseline 0.612 → achieved 0.762 (+24.5%); 4 declared params; best
    trial used 2 of them.
    """
    if best_trial_params is None:
        best_trial_params = {"field_boosts.title": 4.7, "tie_breaker": 0.34}
    if declared_params is None:
        declared_params = {
            "field_boosts.title": {"type": "float", "min": 1.0, "max": 5.0},
            "tie_breaker": {"type": "float", "min": 0.0, "max": 1.0},
            "field_boosts.body": {"type": "float", "min": 0.5, "max": 3.0},
            "fuzziness": {"type": "categorical", "values": ["AUTO", "0", "1", "2"]},
        }

    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"dh-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"dh-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params=declared_params,
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"dh-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"dh-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="r",
            status="complete",
        )
        study_id = str(uuid.uuid4())
        trial_id: str | None = None
        # Create the study FIRST so the trial's study_id FK target exists.
        # We pass best_trial_id=None initially and patch it post-trial-create.
        await repo.create_study(
            db,
            id=study_id,
            name=f"dh-study-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
            target="stub-index",
            template_id=template.id,
            query_set_id=query_set.id,
            judgment_list_id=jl.id,
            search_space={},
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            config={"max_trials": 100, "parallelism": 4, "sampler": "tpe"},
            status=study_status,
            failed_reason=None,
            optuna_study_name=study_id,
            baseline_metric=baseline_metric,
            best_metric=best_metric,
            best_trial_id=None,
        )
        if best_metric is not None:
            trial = await repo.create_trial(
                db,
                id=str(uuid.uuid4()),
                study_id=study_id,
                optuna_trial_number=0,
                status="complete",
                params=best_trial_params,
                metrics={},
                primary_metric=best_metric,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
                duration_ms=100,
            )
            trial_id = trial.id
            # Patch study.best_trial_id now that the trial row exists.
            from backend.app.db.models import Study as _Study

            study_row = await db.get(_Study, study_id)
            if study_row is not None:
                study_row.best_trial_id = trial_id
                await db.flush()
        proposal_id: str | None = None
        if add_pending_proposal:
            proposal = await repo.create_proposal(
                db,
                id=str(uuid.uuid4()),
                study_id=study_id,
                study_trial_id=trial_id,
                cluster_id=cluster.id,
                template_id=template.id,
                config_diff={},
                metric_delta=None,
                status="pending",
            )
            proposal_id = proposal.id
        await db.commit()
    return {
        "study_id": study_id,
        "cluster_id": cluster.id,
        "template_id": template.id,
        "query_set_id": query_set.id,
        "judgment_list_id": jl.id,
        "trial_id": trial_id or "",
        "proposal_id": proposal_id or "",
    }


def make_openai_response(
    *,
    narrative: str = "Test digest narrative.",
    suggested_followups: list[str] | list[dict[str, Any]] | None = None,
    prompt_tokens: int = 1000,
    completion_tokens: int = 500,
) -> Any:
    """Build a synthetic OpenAI ChatCompletion-shaped object for mocking.

    The worker calls ``client.chat.completions.create(...)`` and expects
    ``.choices[0].message.content`` to be a JSON string and
    ``.usage.prompt_tokens`` / ``.usage.completion_tokens``.

    feat_digest_executable_followups Story 2.1: ``suggested_followups``
    accepts three input shapes:

    1. Legacy ``list[str]`` — each string becomes a ``text``-kind item.
    2. New ``list[dict]`` with ``{kind, rationale, search_space}`` —
       the helper translates ``search_space`` (object | null) into
       ``search_space_json`` (JSON-encoded string) to match the worker's
       structured-output schema (the schema ships search_space as a
       string to satisfy OpenAI strict-mode JSON-schema constraints).
    3. New ``list[dict]`` already in ``{kind, rationale, search_space_json}``
       wire shape — passed through unchanged.
    """
    if suggested_followups is None:
        suggested_followups = ["Try a wider tie_breaker range", "Add brand-disambiguation queries"]
    # Normalize all input shapes to the wire format
    # ``{kind, rationale, search_space_json}`` that the worker's response_format
    # schema expects.
    import json as _json

    normalized: list[dict[str, Any]] = []
    for item in suggested_followups:
        if isinstance(item, str):
            # feat_digest_executable_followups_swap_template Story 2.1: every
            # item must carry ``template_id`` (empty-string sentinel for
            # non-swap kinds — worker pre-cleans per spec D-29).
            normalized.append(
                {
                    "kind": "text",
                    "rationale": item,
                    "search_space_json": "",
                    "template_id": "",
                }
            )
        elif isinstance(item, dict):
            if "search_space_json" in item:
                # Already in wire shape — pass through after defaulting
                # template_id to "" for backwards compatibility with the
                # pre-swap_template (Tier-A) wire shape.
                normalized.append({"template_id": "", **item})
            else:
                # Translate {kind, rationale, search_space[, template_id]}
                # → wire shape.
                ss = item.get("search_space")
                ss_json = "" if ss is None else _json.dumps(ss)
                normalized.append(
                    {
                        "kind": item.get("kind", "text"),
                        "rationale": item.get("rationale", ""),
                        "search_space_json": ss_json,
                        "template_id": item.get("template_id", ""),
                    }
                )
    payload = {"narrative": narrative, "suggested_followups": normalized}

    msg = MagicMock()
    msg.content = _json.dumps(payload)
    choice = MagicMock()
    choice.message = msg
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def make_openai_text_response(
    *,
    narrative: str = "Plain prose digest narrative for the degraded path.",
    prompt_tokens: int = 800,
    completion_tokens: int = 400,
) -> Any:
    """Synth a ChatCompletion-shaped object whose content is plain text (no JSON)."""
    msg = MagicMock()
    msg.content = narrative
    choice = MagicMock()
    choice.message = msg
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


async def stub_capability(
    redis: Redis,
    *,
    structured_output: ProbeStatus = "ok",
) -> None:
    """Write a CapabilityResult into Redis matching the configured model."""
    settings = get_settings()
    cap = CapabilityResult(
        base_url=settings.openai_base_url,
        model=settings.openai_model,
        models_endpoint="ok",
        chat_completion="ok",
        function_calling="ok",
        structured_output=structured_output,
        tested_at=datetime.now(UTC),
    )
    await redis.set(
        cache_key(settings.openai_base_url),
        cap.model_dump_json(),
        ex=CACHE_TTL_SECONDS,
    )


def patch_async_openai(monkeypatch: Any, response: Any) -> AsyncMock:
    """Patch ``openai.AsyncOpenAI`` so ``chat.completions.create`` returns ``response``.

    Returns the AsyncMock so callers can assert on call counts / args.
    """
    create_mock = AsyncMock(return_value=response)

    class _StubCompletions:
        create = create_mock

    class _StubChat:
        completions = _StubCompletions()

    class _StubClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        @property
        def chat(self) -> _StubChat:
            return _StubChat()

        async def close(self) -> None:
            pass

    monkeypatch.setattr("backend.workers.digest.AsyncOpenAI", _StubClient)
    return create_mock
