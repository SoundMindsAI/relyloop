# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``FeatureVec`` + ``aggregate_features`` (feat_ubi_judgments Story 1.2 / FR-1 + FR-2 backing).

Pure-domain aggregation of raw UBI events into per-(query, doc)
:class:`FeatureVec`. The caller (``UbiReader``, Story 2.1) does the
two-index scan + client-side join; this module receives the joined
events keyed by ``(query_id, doc_id)`` and applies the Wang-Bendersky
position-bias correction.

No DB, no HTTP, no LLM client. Deterministic given the input event list
+ position-bias prior. Unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(frozen=True, slots=True)
class UbiEvent:
    """One raw UBI event row (post-join from ``ubi_events`` ⨝ ``ubi_queries``).

    Frozen dataclass (not a Pydantic model) because we only construct it
    inside :func:`aggregate_features` from the reader's joined output —
    nothing serializes it across an API boundary.

    Fields:

    * ``query_id`` — from ``ubi_queries.query_id`` (UBI plugin's UUID,
      NOT RelyLoop's ``queries.id``; the reader joins to map between them).
    * ``doc_id`` — from ``ubi_events.doc_id``.
    * ``event_type`` — ``'impression' | 'click' | 'dwell' | 'conversion'
      | 'refinement'``. Other types (e.g., ``'view'`` if the operator
      emits it) are accepted but ignored by the aggregator.
    * ``position`` — 1-indexed rank in the result list at impression
      time. Used for position-bias correction; ``None`` for non-
      impression events.
    * ``dwell_seconds`` — post-click dwell on the document landing
      page. Operator-emitted; ``None`` when absent (matches the rubric
      where dwell is opt-in beyond core impression/click capture).
    """

    query_id: str
    doc_id: str
    event_type: str
    position: int | None
    dwell_seconds: float | None


class FeatureVec(BaseModel):
    """Per-(query, doc) feature vector produced by :func:`aggregate_features`.

    Consumed by the :class:`backend.app.domain.ubi.converter.SignalsConverter`
    Protocol; each converter maps :class:`FeatureVec` → rating ∈ {0, 1, 2, 3}.

    Fields:

    * ``click_count`` — number of ``'click'`` events on this pair within
      the operator's UBI window.
    * ``impression_count`` — number of ``'impression'`` events on this
      pair within the window.
    * ``corrected_ctr`` — position-bias-corrected click-through rate
      computed as ``clicks / sum(impressions_at_position[r] *
      prior[r])`` (Wang-Bendersky). When the prior is uninformed (every
      position weighted 1.0) this reduces to raw CTR. Capped at 1.0 to
      handle the edge case where corrected denominator < click count
      (rare; only when the prior assigns very low weights to high-traffic
      positions).
    * ``dwell_mean_seconds`` — arithmetic mean of ``dwell_seconds`` over
      ``'dwell'`` events on this pair. ``None`` when the operator does
      not emit dwell events for this pair.
    * ``conversion_rate`` — ``conversion_events / click_count`` when at
      least one click exists; ``None`` otherwise (no clicks → no
      conversion ratio).
    * ``refinement_rate`` — ``refinement_events / impression_count``
      when at least one impression exists; ``None`` otherwise.
    """

    click_count: int = Field(ge=0)
    impression_count: int = Field(ge=0)
    corrected_ctr: float = Field(ge=0.0, le=1.0)
    dwell_mean_seconds: float | None = None
    conversion_rate: float | None = None
    refinement_rate: float | None = None


def aggregate_features(
    events_by_pair: dict[tuple[str, str], list[UbiEvent]],
    position_bias_prior: dict[int, float] | None = None,
) -> dict[tuple[str, str], FeatureVec]:
    """Pure aggregation: raw events keyed by ``(query_id, doc_id)`` → :class:`FeatureVec` map.

    The Wang-Bendersky correction uses the operator-supplied prior
    weights per rank. An empty / ``None`` prior is the uninformed
    default — every position weighted ``1.0`` (equivalent to raw CTR).
    Ranks not present in the prior fall back to ``1.0`` so a sparse
    prior table doesn't silently zero out high-position impressions.

    Edge-case behavior (locked by unit test coverage in
    ``backend/tests/unit/domain/ubi/test_features.py``):

    * Zero impressions on a pair → ``impression_count=0``,
      ``corrected_ctr=0.0`` (denominator-zero is treated as 0 rather
      than raising — the converter layer interprets a 0-impression pair
      as "no signal").
    * Single-impression pair → ``corrected_ctr`` = ``click_count /
      (1 * prior_weight)`` (clipped to 1.0).
    * No ``'dwell'`` events → ``dwell_mean_seconds=None`` (not 0.0;
      the distinction matters for the dwell-time converter which
      treats ``None`` as "no rating possible").
    * No ``'click'`` events → ``conversion_rate=None`` (avoids division
      by zero; downstream converters treat None as "no signal").
    """
    if position_bias_prior is None:
        position_bias_prior = {}

    out: dict[tuple[str, str], FeatureVec] = {}
    for pair, events in events_by_pair.items():
        clicks = 0
        impression_weighted_sum = 0.0
        raw_impressions = 0
        dwell_values: list[float] = []
        conversions = 0
        refinements = 0
        for event in events:
            if event.event_type == "click":
                clicks += 1
            elif event.event_type == "impression":
                raw_impressions += 1
                position = event.position or 1
                weight = position_bias_prior.get(position, 1.0)
                impression_weighted_sum += weight
            elif event.event_type == "dwell" and event.dwell_seconds is not None:
                dwell_values.append(event.dwell_seconds)
            elif event.event_type == "conversion":
                conversions += 1
            elif event.event_type == "refinement":
                refinements += 1
            # Unknown event types (e.g., 'view', operator-custom) are silently
            # ignored. This is intentional — the standardized UBI schema is the
            # contract; non-standard event types stay out of the rating
            # derivation rather than crashing the aggregator.

        if impression_weighted_sum > 0:
            corrected_ctr = min(clicks / impression_weighted_sum, 1.0)
        else:
            # No impressions in the window → no CTR signal.
            corrected_ctr = 0.0

        dwell_mean: float | None
        if dwell_values:
            dwell_mean = sum(dwell_values) / len(dwell_values)
        else:
            dwell_mean = None

        conversion_rate: float | None = conversions / clicks if clicks > 0 else None
        refinement_rate: float | None = (
            refinements / raw_impressions if raw_impressions > 0 else None
        )

        out[pair] = FeatureVec(
            click_count=clicks,
            impression_count=raw_impressions,
            corrected_ctr=corrected_ctr,
            dwell_mean_seconds=dwell_mean,
            conversion_rate=conversion_rate,
            refinement_rate=refinement_rate,
        )
    return out
