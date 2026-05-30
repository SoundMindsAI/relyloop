# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""CHECK ``studies_parent_proposal_pair_check`` integration test (Story 3.4).

Asserts the pair-set-together-and-index-non-negative CHECK constraint
introduced by migration 0018 blocks every malformed write at the DB layer.

Three negative cases (one per failure mode):

1. ``parent_proposal_id`` set with ``parent_proposal_followup_index`` NULL.
2. ``parent_proposal_followup_index`` set with ``parent_proposal_id`` NULL.
3. Both set with ``parent_proposal_followup_index = -1``.

Raw SQL bypasses the ORM so the CHECK is exercised directly. Seeded
parent rows use the existing helper functions to keep fixture surface
small.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._digest_helpers import seed_completed_study

pytestmark = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
)


_STUDY_INSERT = text(
    "INSERT INTO studies "
    "(id, name, cluster_id, target, template_id, query_set_id, judgment_list_id, "
    "search_space, objective, config, status, optuna_study_name, "
    "parent_proposal_id, parent_proposal_followup_index, created_at) "
    "VALUES (:id, :name, :cluster, 'stub-index', :tmpl, :qs, :jl, "
    "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 'queued', :osn, "
    ":parent_pid, :parent_idx, NOW())"
)


def _params(
    *,
    cluster_id: str,
    template_id: str,
    query_set_id: str,
    judgment_list_id: str,
    parent_pid: str | None,
    parent_idx: int | None,
) -> dict[str, object]:
    study_id = str(uuid.uuid4())
    return {
        "id": study_id,
        "name": f"check-test-{uuid.uuid4().hex[:8]}",
        "cluster": cluster_id,
        "tmpl": template_id,
        "qs": query_set_id,
        "jl": judgment_list_id,
        "osn": study_id,
        "parent_pid": parent_pid,
        "parent_idx": parent_idx,
    }


@pytest.mark.integration
@pytest.mark.asyncio
class TestStudiesParentProposalCheck:
    """The CHECK constraint blocks every half-set or negative-index row."""

    async def test_proposal_id_set_index_null_rejected(self) -> None:
        seeded = await seed_completed_study()
        factory = get_session_factory()
        async with factory() as db:
            with pytest.raises(IntegrityError) as exc:
                await db.execute(
                    _STUDY_INSERT,
                    _params(
                        cluster_id=seeded["cluster_id"],
                        template_id=seeded["template_id"],
                        query_set_id=seeded["query_set_id"],
                        judgment_list_id=seeded["judgment_list_id"],
                        parent_pid=seeded["proposal_id"],
                        parent_idx=None,
                    ),
                )
                await db.commit()
            assert "studies_parent_proposal_pair_check" in str(exc.value)

    async def test_index_set_proposal_id_null_rejected(self) -> None:
        seeded = await seed_completed_study()
        factory = get_session_factory()
        async with factory() as db:
            with pytest.raises(IntegrityError) as exc:
                await db.execute(
                    _STUDY_INSERT,
                    _params(
                        cluster_id=seeded["cluster_id"],
                        template_id=seeded["template_id"],
                        query_set_id=seeded["query_set_id"],
                        judgment_list_id=seeded["judgment_list_id"],
                        parent_pid=None,
                        parent_idx=0,
                    ),
                )
                await db.commit()
            assert "studies_parent_proposal_pair_check" in str(exc.value)

    async def test_negative_index_rejected(self) -> None:
        seeded = await seed_completed_study()
        factory = get_session_factory()
        async with factory() as db:
            with pytest.raises(IntegrityError) as exc:
                await db.execute(
                    _STUDY_INSERT,
                    _params(
                        cluster_id=seeded["cluster_id"],
                        template_id=seeded["template_id"],
                        query_set_id=seeded["query_set_id"],
                        judgment_list_id=seeded["judgment_list_id"],
                        parent_pid=seeded["proposal_id"],
                        parent_idx=-1,
                    ),
                )
                await db.commit()
            assert "studies_parent_proposal_pair_check" in str(exc.value)

    async def test_both_null_accepted(self) -> None:
        """Sanity-check the legal "no lineage" case — both columns NULL is fine."""
        seeded = await seed_completed_study()
        factory = get_session_factory()
        async with factory() as db:
            await db.execute(
                _STUDY_INSERT,
                _params(
                    cluster_id=seeded["cluster_id"],
                    template_id=seeded["template_id"],
                    query_set_id=seeded["query_set_id"],
                    judgment_list_id=seeded["judgment_list_id"],
                    parent_pid=None,
                    parent_idx=None,
                ),
            )
            await db.commit()

    async def test_both_set_with_zero_index_accepted(self) -> None:
        """The legal "lineage with index=0" case — both columns set is fine."""
        seeded = await seed_completed_study()
        factory = get_session_factory()
        async with factory() as db:
            await db.execute(
                _STUDY_INSERT,
                _params(
                    cluster_id=seeded["cluster_id"],
                    template_id=seeded["template_id"],
                    query_set_id=seeded["query_set_id"],
                    judgment_list_id=seeded["judgment_list_id"],
                    parent_pid=seeded["proposal_id"],
                    parent_idx=0,
                ),
            )
            await db.commit()
