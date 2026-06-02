# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Regression test for the CLI UBI-seed ``engine_type`` kwarg drift.

When ``infra_adapter_solr`` made ``engine_type`` a required keyword-only
argument on both :func:`backend.app.services.demo_ubi_seed.ensure_ubi_indices`
and :func:`~backend.app.services.demo_ubi_seed.seed_synthetic_ubi`, the
service path (``demo_seeding.py``) was updated but the CLI wrapper
:func:`scripts.seed_meaningful_demos._async_seed_synthetic_ubi` was not.

The result: ``make up`` auto-seed (and ``make seed-demo``) crashed on the
first UBI-enabled scenario with::

    TypeError: ensure_ubi_indices() missing 1 required keyword-only
    argument: 'engine_type'

These tests pin that the CLI wrapper forwards ``engine_type`` to both
helpers so the drift cannot recur silently.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import scripts.seed_meaningful_demos as mod


@pytest.mark.asyncio
async def test_async_seed_synthetic_ubi_forwards_engine_type(monkeypatch) -> None:
    """The CLI wrapper must pass ``engine_type`` to both UBI helpers.

    Patches the two helpers at their source module (the wrapper imports
    them lazily inside the function body, so patching the source binding
    is what the deferred ``from ... import`` resolves to). Before the fix
    the wrapper omitted ``engine_type`` entirely, so the
    ``assert_awaited_once_with(..., engine_type=...)`` checks below fail.
    """
    ensure_mock = AsyncMock(return_value=None)
    seed_mock = AsyncMock(return_value=7)
    monkeypatch.setattr("backend.app.services.demo_ubi_seed.ensure_ubi_indices", ensure_mock)
    monkeypatch.setattr("backend.app.services.demo_ubi_seed.seed_synthetic_ubi", seed_mock)

    event_count = await mod._async_seed_synthetic_ubi(
        scenario_slug="acme-products-prod",
        target_application="products",
        target_rung="rung_3",
        scenario_judgments_map=[(0, "doc-1", 2)],
        query_id_by_index={0: "q-0"},
        query_text_by_index={0: "wireless headphones"},
        seed_anchor_iso="2026-06-02T12:00:00+00:00",
        engine_base_url="http://localhost:9200",
        host_auth=("", ""),
        engine_type="elasticsearch",
    )

    assert event_count == 7
    assert ensure_mock.await_args is not None
    assert ensure_mock.await_args.kwargs["engine_type"] == "elasticsearch"
    assert seed_mock.await_args is not None
    assert seed_mock.await_args.kwargs["engine_type"] == "elasticsearch"


def test_async_seed_synthetic_ubi_signature_has_engine_type() -> None:
    """``engine_type`` must be a declared parameter on the CLI wrapper.

    Cheap static guard mirroring the call-site forwarding test above —
    catches a refactor that drops the parameter from the signature.
    """
    import inspect

    params = inspect.signature(mod._async_seed_synthetic_ubi).parameters
    assert "engine_type" in params, (
        "_async_seed_synthetic_ubi must accept engine_type to forward it to "
        "ensure_ubi_indices / seed_synthetic_ubi"
    )
