# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Study-comparison pairing + validation (feat_ubi_llm_study_comparison).

Pure read orchestrator for the LLM-vs-UBI comparison surface. No write path,
no ``job_run``, no adapter call, no audit emission — it loads studies +
judgment lists via the repo, classifies each study's judgment kind, and
returns a validated :class:`ComparePairing` (or raises
:class:`CompareValidationError`, which the router maps to the project error
envelope).

``classify_judgment_kind`` is the single source of truth for the kind
discriminator on the Python side (the repo's SQL counterpart mirrors the same
``generation_kind == 'ubi'`` rule). :data:`CompareKind` /
:data:`CompareWarningCode` are imported from the domain layer
(``domain.study.comparison``) — the wire models in ``schemas`` re-import the
same Literals, so there is one canonical definition with the dependency
pointing API → domain (never service → API).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo
from backend.app.domain.study.comparison import CompareKind, CompareWarningCode


def classify_judgment_kind(generation_params: Any) -> CompareKind:
    """Classify a judgment list as ``ubi`` or ``llm`` from its generation params.

    ``ubi`` iff ``generation_params`` is a dict whose ``generation_kind`` is
    exactly ``"ubi"`` (this includes the hybrid converter, which still carries
    ``generation_kind == 'ubi'``). Everything else — ``None``, ``{}``, a
    non-dict, or any other ``generation_kind`` value — classifies as ``llm``.
    """
    if isinstance(generation_params, dict) and generation_params.get("generation_kind") == "ubi":
        return "ubi"
    return "llm"


@dataclass(frozen=True)
class CompareWarning:
    """A non-fatal mismatch surfaced as a banner; never blocks the comparison."""

    code: CompareWarningCode
    message: str


@dataclass(frozen=True)
class ComparePairing:
    """The validated pair returned to the ``/studies/compare`` router."""

    a_study_id: str
    b_study_id: str
    a_kind: CompareKind
    b_kind: CompareKind
    query_set_id: str
    warnings: list[CompareWarning]


class CompareValidationError(Exception):
    """A hard gate failed; carries the router's HTTP status + error code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        """Carry the router's HTTP ``status`` + machine-readable ``code``."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


async def validate_compare_pair(db: AsyncSession, a_id: str, b_id: str) -> ComparePairing:
    """Validate an ``a``/``b`` study pair for side-by-side comparison.

    Hard gates (raise :class:`CompareValidationError`):
      * 404 ``STUDY_NOT_FOUND`` — either study missing.
      * 422 ``COMPARE_STUDY_NOT_COMPLETED`` — either ``status != 'completed'``.
      * 422 ``COMPARE_QUERY_SET_MISMATCH`` — different ``query_set_id``.
      * 422 ``COMPARE_NOT_LLM_UBI_PAIR`` — not exactly one ``llm`` + one ``ubi``.

    Non-fatal warnings (returned, never raised): ``CROSS_CLUSTER`` (different
    ``cluster_id``), ``TARGET_MISMATCH`` (different ``target``),
    ``OBJECTIVE_MISMATCH`` (different objective ``metric`` or ``direction``).
    """
    a = await repo.get_study(db, a_id)
    if a is None:
        raise CompareValidationError(404, "STUDY_NOT_FOUND", f"study {a_id} not found")
    b = await repo.get_study(db, b_id)
    if b is None:
        raise CompareValidationError(404, "STUDY_NOT_FOUND", f"study {b_id} not found")

    if a.status != "completed" or b.status != "completed":
        raise CompareValidationError(
            422,
            "COMPARE_STUDY_NOT_COMPLETED",
            "both studies must be completed to compare",
        )

    if a.query_set_id != b.query_set_id:
        raise CompareValidationError(
            422,
            "COMPARE_QUERY_SET_MISMATCH",
            "studies must share the same query set to compare",
        )

    a_jl = await repo.get_judgment_list(db, a.judgment_list_id)
    b_jl = await repo.get_judgment_list(db, b.judgment_list_id)
    a_kind = classify_judgment_kind(a_jl.generation_params if a_jl else None)
    b_kind = classify_judgment_kind(b_jl.generation_params if b_jl else None)
    if {a_kind, b_kind} != {"llm", "ubi"}:
        raise CompareValidationError(
            422,
            "COMPARE_NOT_LLM_UBI_PAIR",
            "comparison requires exactly one LLM and one UBI study",
        )

    warnings: list[CompareWarning] = []
    if a.cluster_id != b.cluster_id:
        warnings.append(
            CompareWarning(
                code="CROSS_CLUSTER",
                message="the two studies ran on different clusters",
            )
        )
    if a.target != b.target:
        warnings.append(
            CompareWarning(
                code="TARGET_MISMATCH",
                message="the two studies targeted different indices/collections",
            )
        )
    if _objective_key(a.objective) != _objective_key(b.objective):
        warnings.append(
            CompareWarning(
                code="OBJECTIVE_MISMATCH",
                message=(
                    "the two studies optimized different objectives — "
                    "the metric delta is not directly comparable"
                ),
            )
        )

    return ComparePairing(
        a_study_id=a.id,
        b_study_id=b.id,
        a_kind=a_kind,
        b_kind=b_kind,
        query_set_id=a.query_set_id,
        warnings=warnings,
    )


def _objective_key(objective: Any) -> tuple[Any, Any]:
    """``(metric, direction)`` for the OBJECTIVE_MISMATCH comparison.

    Defensive against a malformed ``objective`` JSONB (non-dict → ``(None, None)``).
    ``direction`` defaults to ``"maximize"`` to match the study runner's default.
    """
    if not isinstance(objective, dict):
        return (None, None)
    return (objective.get("metric"), objective.get("direction") or "maximize")


__all__ = [
    "CompareKind",
    "CompareWarning",
    "ComparePairing",
    "CompareValidationError",
    "classify_judgment_kind",
    "validate_compare_pair",
]
