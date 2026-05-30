# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""BEFORE DELETE trigger integration test (Story 3.5, AC-11).

Asserts ``trg_clear_studies_parent_proposal_on_proposal_delete`` (created
in migration 0018) NULLs the lineage pair atomically when a parent
proposal is hard-deleted, leaving the child study row intact apart from
those two columns.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, text

from backend.app.db.models import Proposal, Study
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._digest_helpers import seed_completed_study

pytestmark = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
)


@pytest.mark.integration
@pytest.mark.asyncio
class TestStudiesParentProposalOnDelete:
    async def test_trigger_clears_lineage_atomically(self) -> None:
        """Hard-delete proposal → child study's lineage columns become NULL."""
        seeded = await seed_completed_study()
        factory = get_session_factory()

        # Insert a child study with the lineage pair set, pointing at the
        # seeded proposal.
        child_study_id = str(uuid.uuid4())
        async with factory() as db:
            await db.execute(
                text(
                    "INSERT INTO studies "
                    "(id, name, cluster_id, target, template_id, query_set_id, "
                    "judgment_list_id, search_space, objective, config, status, "
                    "optuna_study_name, parent_proposal_id, parent_proposal_followup_index, "
                    "created_at) VALUES "
                    "(:id, :name, :cluster, 'stub-index', :tmpl, :qs, :jl, "
                    "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 'queued', :osn, "
                    ":pid, 0, NOW())"
                ),
                {
                    "id": child_study_id,
                    "name": f"on-delete-child-{uuid.uuid4().hex[:8]}",
                    "cluster": seeded["cluster_id"],
                    "tmpl": seeded["template_id"],
                    "qs": seeded["query_set_id"],
                    "jl": seeded["judgment_list_id"],
                    "osn": child_study_id,
                    "pid": seeded["proposal_id"],
                },
            )
            await db.commit()

        # Snapshot the child row before delete.
        async with factory() as db:
            before = await db.get(Study, child_study_id)
            assert before is not None
            assert before.parent_proposal_id == seeded["proposal_id"]
            assert before.parent_proposal_followup_index == 0
            before_snapshot = {
                "id": before.id,
                "name": before.name,
                "cluster_id": before.cluster_id,
                "target": before.target,
                "template_id": before.template_id,
                "query_set_id": before.query_set_id,
                "judgment_list_id": before.judgment_list_id,
                "search_space": before.search_space,
                "objective": before.objective,
                "config": before.config,
                "status": before.status,
                "optuna_study_name": before.optuna_study_name,
            }

        # Hard-delete the parent proposal — trigger fires before delete.
        async with factory() as db:
            await db.execute(delete(Proposal).where(Proposal.id == seeded["proposal_id"]))
            await db.commit()

        # Re-fetch child; lineage cleared, rest unchanged.
        async with factory() as db:
            after = await db.get(Study, child_study_id)
            assert after is not None
            assert after.parent_proposal_id is None
            assert after.parent_proposal_followup_index is None
            # Every other column unchanged.
            after_snapshot = {
                "id": after.id,
                "name": after.name,
                "cluster_id": after.cluster_id,
                "target": after.target,
                "template_id": after.template_id,
                "query_set_id": after.query_set_id,
                "judgment_list_id": after.judgment_list_id,
                "search_space": after.search_space,
                "objective": after.objective,
                "config": after.config,
                "status": after.status,
                "optuna_study_name": after.optuna_study_name,
            }
            assert after_snapshot == before_snapshot
