# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Confirmation authorization hardening (security audit 2026-07-12 F1/F2).

* F2 — a NEGATED mutating-tool mention must not count as a proposal.
* F1 — the one-mutation-per-turn invariant lives in the run_turn loop; here we
  cover the pure `_is_authorized_mutation` negation gate (the loop flag is
  exercised by the orchestrator integration tests).
"""

from __future__ import annotations

import pytest

from backend.app.agent.orchestrator import (
    _is_authorized_mutation,
    _tool_mention_is_negated,
)


@pytest.mark.parametrize(
    "assistant_text",
    [
        "i will not cancel_study unless you insist",
        "i won't cancel_study",
        "there is no need to cancel_study",
        "rather than cancel_study we could wait",
    ],
)
def test_negated_mention_is_not_a_proposal(assistant_text: str) -> None:
    assert _tool_mention_is_negated(assistant_text, "cancel_study") is True
    # ...so even with a user "yes" the gate refuses.
    assert (
        _is_authorized_mutation(
            tool_name="cancel_study",
            last_assistant_text=assistant_text,
            last_user_text="yes",
        )
        is False
    )


def test_negated_mention_with_smart_apostrophe_is_not_authorized() -> None:
    """A curly-apostrophe negation ("won’t") must not bypass the gate — the
    assistant text is apostrophe-folded before the negation regex (Gemini review)."""
    assert (
        _is_authorized_mutation(
            tool_name="cancel_study",
            last_assistant_text="i won’t cancel_study",
            last_user_text="yes",
        )
        is False
    )


@pytest.mark.parametrize(
    "assistant_text",
    [
        "shall i cancel_study now?",
        "i can cancel_study for you — confirm?",
        "this won't take long. shall i cancel_study?",  # distant negation, outside window
    ],
)
def test_genuine_proposal_is_authorized(assistant_text: str) -> None:
    assert _tool_mention_is_negated(assistant_text, "cancel_study") is False
    assert (
        _is_authorized_mutation(
            tool_name="cancel_study",
            last_assistant_text=assistant_text,
            last_user_text="yes",
        )
        is True
    )


# --- F1: one mutating dispatch per turn ---------------------------------------

import json  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

from backend.app.agent.events import ToolResultEvent  # noqa: E402
from backend.app.agent.orchestrator import run_turn  # noqa: E402

from .conftest import capability_ok, make_text_chunks, make_tool_call_chunks  # noqa: E402


@pytest.mark.asyncio
async def test_only_one_mutation_dispatches_per_turn(
    fake_ctx: Any, fake_openai_client: Any
) -> None:
    """A single confirmed proposal authorizes exactly ONE mutating dispatch; a
    second mutating call in the same turn is refused (audit 2026-07-12 F1)."""
    args = json.dumps({"study_id": "019000000000700080000000000000aa", "config_diff": {}})
    streams = [
        make_tool_call_chunks(call_id="c1", name="create_proposal_from_study", arguments=args),
        make_tool_call_chunks(call_id="c2", name="create_proposal_from_study", arguments=args),
        make_text_chunks("done"),
    ]
    stream_iter = iter(streams)

    async def _create(**_: Any):
        chunks = next(stream_iter)

        async def _iter() -> Any:
            for c in chunks:
                yield c

        return _iter()

    fake_openai_client.chat.completions.create = _create
    impl = AsyncMock(return_value={"proposal_id": "p1"})

    with (
        patch(
            "backend.app.agent.orchestrator.read_capability_result",
            AsyncMock(return_value=capability_ok()),
        ),
        patch.dict(
            "backend.app.agent.orchestrator.TOOL_REGISTRY",
            {"create_proposal_from_study": impl},
        ),
    ):
        events = [
            ev
            async for ev in run_turn(
                conversation_id="conv_1",
                history=[],
                last_user_text="yes",
                last_assistant_text="Shall I create_proposal_from_study for this run?",
                degraded_notice_already_sent=False,
                ctx=fake_ctx,
                openai_client=fake_openai_client,
            )
        ]

    # Exactly one successful dispatch; the second call is a confirmation_required error.
    assert impl.call_count == 1
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    successes = [e for e in results if e.error is None and e.name == "create_proposal_from_study"]
    refusals = [e for e in results if e.error == "confirmation_required"]
    assert len(successes) == 1
    assert len(refusals) == 1
