# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Two-condition confirmation guard (feat_chat_agent Story 2.5).

* The most-recent assistant message must mention the tool name.
* The most-recent user message must be affirmative.

Either condition missing → ``ToolResultEvent(error='confirmation_required')``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.agent.confirmation import MUTATING_TOOL_NAMES
from backend.app.agent.events import ToolResultEvent
from backend.app.agent.orchestrator import _is_authorized_mutation, run_turn

from .conftest import capability_ok, make_text_chunks, make_tool_call_chunks


def test_unit_user_yes_to_unrelated_question_fails() -> None:
    """Assistant didn't propose this tool → guard rejects."""
    assert not _is_authorized_mutation(
        tool_name="create_study",
        last_assistant_text="The schema has these fields: title, body, author.",
        last_user_text="yes",
    )


def test_unit_user_not_affirmative_fails() -> None:
    """Assistant proposed the tool but user said something else → guard rejects."""
    assert not _is_authorized_mutation(
        tool_name="create_study",
        last_assistant_text="I'm about to call create_study with these params...",
        last_user_text="what does that mean?",
    )


def test_unit_both_conditions_pass() -> None:
    """Assistant proposes + user affirms → guard allows."""
    assert _is_authorized_mutation(
        tool_name="create_study",
        last_assistant_text="I'm about to call create_study with these params...",
        last_user_text="yes proceed",
    )


def test_unit_spaced_tool_name_pass() -> None:
    """The matcher accepts the spaced form (``create study``) for natural-language replies."""
    assert _is_authorized_mutation(
        tool_name="create_study",
        last_assistant_text="I'll create study now using product_search v3.",
        last_user_text="go ahead",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(MUTATING_TOOL_NAMES))
async def test_integration_confirmation_required_blocks_dispatch(
    fake_ctx: Any, fake_openai_client: Any, tool_name: str
) -> None:
    """For every mutating tool, dispatch without confirmation yields error event."""
    streams = [
        make_tool_call_chunks(
            call_id=f"call_{tool_name}",
            name=tool_name,
            arguments=_dummy_args_json(tool_name),
        ),
        make_text_chunks("Cancelled — please confirm first."),
    ]
    stream_iter = iter(streams)

    async def _create(**_: Any) -> AsyncIterator[Any]:
        chunks = next(stream_iter)

        async def _iter() -> AsyncIterator[Any]:
            for c in chunks:
                yield c

        return _iter()

    fake_openai_client.chat.completions.create = _create

    # Sentinel impl raises if called — proves the guard fired before dispatch.
    sentinel_impl = AsyncMock(side_effect=AssertionError("impl should not run"))

    with (
        patch(
            "backend.app.agent.orchestrator.read_capability_result",
            AsyncMock(return_value=capability_ok()),
        ),
        patch.dict("backend.app.agent.orchestrator.TOOL_REGISTRY", {tool_name: sentinel_impl}),
    ):
        events = []
        async for ev in run_turn(
            conversation_id="conv_1",
            history=[],
            # No prior assistant message; condition 1 fails.
            last_user_text="yes",
            last_assistant_text=None,
            degraded_notice_already_sent=False,
            ctx=fake_ctx,
            openai_client=fake_openai_client,
        ):
            events.append(ev)

    result_events = [e for e in events if isinstance(e, ToolResultEvent)]
    confirmation_errors = [
        e for e in result_events if e.error == "confirmation_required" and e.name == tool_name
    ]
    assert confirmation_errors, f"no confirmation_required for {tool_name}: {result_events}"
    sentinel_impl.assert_not_called()


@pytest.mark.asyncio
async def test_read_only_tools_dispatch_regardless_of_confirmation(
    fake_ctx: Any, fake_openai_client: Any
) -> None:
    """``list_clusters`` runs even without a prior assistant message + affirmation."""
    streams = [
        make_tool_call_chunks(
            call_id="call_ro",
            name="list_clusters",
            arguments="{}",
        ),
        make_text_chunks("Here are your clusters."),
    ]
    stream_iter = iter(streams)

    async def _create(**_: Any) -> AsyncIterator[Any]:
        chunks = next(stream_iter)

        async def _iter() -> AsyncIterator[Any]:
            for c in chunks:
                yield c

        return _iter()

    fake_openai_client.chat.completions.create = _create

    impl = AsyncMock(return_value={"clusters": []})
    with (
        patch(
            "backend.app.agent.orchestrator.read_capability_result",
            AsyncMock(return_value=capability_ok()),
        ),
        patch.dict("backend.app.agent.orchestrator.TOOL_REGISTRY", {"list_clusters": impl}),
    ):
        async for _ in run_turn(
            conversation_id="conv_1",
            history=[],
            last_user_text="what clusters?",
            last_assistant_text=None,
            degraded_notice_already_sent=False,
            ctx=fake_ctx,
            openai_client=fake_openai_client,
        ):
            pass

    impl.assert_called_once()


def _dummy_args_json(tool_name: str) -> str:
    """Return a Pydantic-valid args JSON for each mutating tool.

    The dispatch loop validates args via TOOL_ARG_MODELS BEFORE the
    confirmation guard. If we hand it args that fail validation, the test
    asserts validation_failed instead of confirmation_required. Use a
    plausible value per tool.
    """
    dummy_uuid = "01234567-89ab-7def-8000-000000000000"
    if tool_name == "create_study":
        return (
            '{"name":"x","cluster_id":"'
            + dummy_uuid
            + '","target":"products","template_id":"'
            + dummy_uuid
            + '","query_set_id":"'
            + dummy_uuid
            + '","judgment_list_id":"'
            + dummy_uuid
            + '","search_space":{"params":{}},'
            '"objective":{"metric":"mrr"},'
            '"config":{"max_trials":1}}'
        )
    if tool_name == "cancel_study":
        return f'{{"study_id":"{dummy_uuid}"}}'
    if tool_name == "open_pr":
        return f'{{"proposal_id":"{dummy_uuid}"}}'
    if tool_name == "create_proposal_from_study":
        return f'{{"study_id":"{dummy_uuid}"}}'
    if tool_name == "create_proposal_manual":
        return (
            '{"cluster_id":"'
            + dummy_uuid
            + '","template_id":"'
            + dummy_uuid
            + '","config_diff":{}}'
        )
    if tool_name == "import_queries_from_csv":
        return f'{{"query_set_id":"{dummy_uuid}","csv_text":"query_text\\nfoo"}}'
    if tool_name == "generate_judgments_llm":
        return (
            '{"name":"x","query_set_id":"'
            + dummy_uuid
            + '","cluster_id":"'
            + dummy_uuid
            + '","target":"products","current_template_id":"'
            + dummy_uuid
            + '","rubric":"r"}'
        )
    if tool_name == "generate_judgments_from_ubi":
        # Pure ctr_threshold converter — no template/rubric (the hybrid
        # conditional validator rejects them for non-hybrid converters).
        return (
            '{"name":"x","query_set_id":"'
            + dummy_uuid
            + '","cluster_id":"'
            + dummy_uuid
            + '","target":"products","since":"2026-05-01T00:00:00Z",'
            '"converter":"ctr_threshold"}'
        )
    raise AssertionError(f"no dummy args for {tool_name}")
