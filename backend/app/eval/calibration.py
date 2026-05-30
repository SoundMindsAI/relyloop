# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Cohen's kappa + linear-weighted kappa for judgment calibration (Story 1.5).

Pure-Python implementation (no NumPy dep — the formulas are short enough that
a hand-rolled version is easier to audit + adds no transitive deps to the
``eval`` layer).

Consumed by :mod:`backend.app.api.v1.judgments` (the ``POST .../calibration``
endpoint) which collects human samples and pairs them with the LLM rating at
the same ``(query_id, doc_id)``. Per spec FR-5 calibration is advisory:
operators use it to decide whether the rubric needs refinement before relying
on the LLM rating in studies.

Spec §11 edge case: when all ratings are identical (no variance), kappa is
mathematically undefined. We return ``cohens_kappa=None`` and ``weighted_kappa=None``
with ``warning="no rating variance"``.
"""

from __future__ import annotations

from typing import TypedDict

_RATING_VALUES: tuple[int, ...] = (0, 1, 2, 3)
"""Canonical 0..3 rubric scale (matches the CHECK constraint on
``judgments.rating``). Per-class agreement reports one entry per value."""


class CalibrationResult(TypedDict):
    """JSON-shaped calibration report (also the wire shape).

    Mirrors ``judgment_lists.calibration`` JSONB column. ``per_class`` keys are
    string-encoded rating values (``"0"``, ``"1"``, ``"2"``, ``"3"``) so the
    payload round-trips through JSON cleanly. Values are 0..1 agreement
    fractions, ``0.0`` when no human sample uses that rating.
    """

    cohens_kappa: float | None
    weighted_kappa: float | None
    per_class: dict[str, float]
    n_samples: int
    warning: str | None


def _confusion_matrix(pairs: list[tuple[int, int]]) -> list[list[int]]:
    """Build a 4x4 confusion matrix indexed by ``[human][llm]``.

    Pairs with ratings outside 0..3 are skipped silently; the caller is
    expected to enforce :data:`_RATING_VALUES` via the API schema.
    """
    matrix = [[0, 0, 0, 0] for _ in _RATING_VALUES]
    for human, llm in pairs:
        if 0 <= human <= 3 and 0 <= llm <= 3:
            matrix[human][llm] += 1
    return matrix


def _kappa(pairs: list[tuple[int, int]]) -> tuple[float | None, float | None]:
    """Return ``(cohens_kappa, weighted_kappa)`` for the supplied pairs.

    Both kappas return ``None`` when the marginals indicate no rating
    variance (all observers agree everything is the same single rating)
    because ``p_e = 1`` makes the denominator zero. Weighted kappa uses
    linear weights: ``w_ij = 1 - |i - j| / 3``.
    """
    matrix = _confusion_matrix(pairs)
    n = sum(sum(row) for row in matrix)
    if n == 0:
        return None, None

    # Observed agreement (Cohen's): proportion where both raters chose the
    # same rating.
    p_o = sum(matrix[i][i] for i in range(4)) / n

    # Marginal probabilities for chance agreement.
    human_marg = [sum(matrix[i][j] for j in range(4)) / n for i in range(4)]
    llm_marg = [sum(matrix[i][j] for i in range(4)) / n for j in range(4)]

    # Cohen's expected agreement.
    p_e = sum(human_marg[i] * llm_marg[i] for i in range(4))
    cohens_kappa = None if abs(1.0 - p_e) < 1e-12 else (p_o - p_e) / (1.0 - p_e)

    # Linear-weighted kappa.
    max_dist = 3.0  # |0 - 3| is the worst-case disagreement on a 0..3 scale.
    # Observed weighted agreement.
    p_o_w = 0.0
    for i in range(4):
        for j in range(4):
            w = 1.0 - abs(i - j) / max_dist
            p_o_w += w * matrix[i][j] / n
    # Expected weighted agreement under independence.
    p_e_w = 0.0
    for i in range(4):
        for j in range(4):
            w = 1.0 - abs(i - j) / max_dist
            p_e_w += w * human_marg[i] * llm_marg[j]
    weighted_kappa = None if abs(1.0 - p_e_w) < 1e-12 else (p_o_w - p_e_w) / (1.0 - p_e_w)

    return cohens_kappa, weighted_kappa


def _per_class_agreement(pairs: list[tuple[int, int]]) -> dict[str, float]:
    """Per-rating-class agreement.

    Fraction of (query, doc) pairs at a given human rating where the LLM
    rating matched exactly. For a rating ``r`` not represented in the human
    samples, the entry is ``0.0`` rather than absent so the JSON shape is
    stable across runs.
    """
    counts = {str(r): 0 for r in _RATING_VALUES}
    matches = {str(r): 0 for r in _RATING_VALUES}
    for human, llm in pairs:
        if not (0 <= human <= 3 and 0 <= llm <= 3):
            continue
        key = str(human)
        counts[key] += 1
        if human == llm:
            matches[key] += 1
    return {key: (matches[key] / counts[key]) if counts[key] > 0 else 0.0 for key in counts}


def compute_calibration(pairs: list[tuple[int, int]]) -> CalibrationResult:
    """Compute Cohen's + linear-weighted kappa + per-class agreement.

    Args:
        pairs: ``[(human_rating, llm_rating), ...]`` with both values in
            ``0..3``. Pairs outside the valid range are dropped silently
            (the API schema rejects them upstream).

    Returns:
        :class:`CalibrationResult`. ``n_samples`` is the count of pairs the
        caller passed in (not the filtered count) so the operator can see
        the audit trail of submitted samples.
    """
    cohens, weighted = _kappa(pairs)
    per_class = _per_class_agreement(pairs)
    warning: str | None = None
    if cohens is None and weighted is None and pairs:
        # Both kappas undefined → marginals concentrated on a single rating.
        warning = "no rating variance"
    return CalibrationResult(
        cohens_kappa=cohens,
        weighted_kappa=weighted,
        per_class=per_class,
        n_samples=len(pairs),
        warning=warning,
    )
