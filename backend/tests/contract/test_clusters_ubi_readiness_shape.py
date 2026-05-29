"""Contract tests for ``GET /api/v1/clusters/{cluster_id}/ubi-readiness``
(feat_ubi_judgments Story 3.1 / FR-7).

Locks the wire shape of :class:`UbiReadinessResponse` and the
documented error envelopes. The full end-to-end behavior (Redis cache
hit, adapter probe, rung classification) is covered by
``backend/tests/unit/services/test_ubi_readiness.py`` against the stub
adapter; this layer just asserts the Pydantic response model matches
the spec §8.5 wire contract.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.api.v1.schemas import UbiReadinessResponse, UbiReadinessRungWire


class TestUbiReadinessResponse:
    def test_minimal_rung_0_payload(self) -> None:
        """rung_0 — nullable fields stay null; matches the spec §8.1 example."""
        payload = {
            "rung": "rung_0",
            "covered_pairs_pct": None,
            "head_covered": None,
            "checked_at": "2026-05-29T12:00:00+00:00",
        }
        resp = UbiReadinessResponse.model_validate(payload)
        assert resp.rung == "rung_0"
        assert resp.covered_pairs_pct is None
        assert resp.head_covered is None
        assert resp.checked_at == datetime(2026, 5, 29, 12, 0, tzinfo=UTC)

    def test_all_four_rungs_accepted(self) -> None:
        for rung in ("rung_0", "rung_1", "rung_2", "rung_3"):
            resp = UbiReadinessResponse.model_validate(
                {
                    "rung": rung,
                    "covered_pairs_pct": None,
                    "head_covered": None,
                    "checked_at": "2026-05-29T12:00:00+00:00",
                }
            )
            assert resp.rung == rung

    def test_unknown_rung_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UbiReadinessResponse.model_validate(
                {
                    "rung": "rung_4",
                    "covered_pairs_pct": None,
                    "head_covered": None,
                    "checked_at": "2026-05-29T12:00:00+00:00",
                }
            )

    def test_required_fields_locked(self) -> None:
        declared = set(UbiReadinessResponse.model_fields.keys())
        assert declared == {"rung", "covered_pairs_pct", "head_covered", "checked_at"}

    def test_rung_wire_literal_locked(self) -> None:
        from typing import get_args

        assert set(get_args(UbiReadinessRungWire)) == {
            "rung_0",
            "rung_1",
            "rung_2",
            "rung_3",
        }
