"""Position-bias prior loader (feat_ubi_judgments Story 1.2 / FR-11).

Loads the optional operator-supplied Wang-Bendersky position-bias prior
from a mounted JSON file (env var ``UBI_POSITION_BIAS_PRIOR_FILE``
resolved by :mod:`backend.app.core.settings`). Returns an empty dict
(the uninformed default) when the file is missing, empty, or malformed.
A malformed file logs a structured WARN but does NOT raise — the worker
falls back to the uninformed prior cleanly, so a bad prior degrades the
rating accuracy without crashing the pipeline.

Pure-domain conformance: the I/O is gated by the ``path`` argument
which the caller resolves (typically via the ``Settings`` accessor at
the boot edge); this module is itself synchronous and treats the file
as a value, not an open file handle held across calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def load_position_bias_prior(path: Path | None) -> dict[int, float]:
    """Read the prior file and return ``{rank: weight}``.

    Returns ``{}`` (uninformed — every position weighted 1.0 by
    :func:`backend.app.domain.ubi.features.aggregate_features`) when:

    * ``path is None`` (operator did not set the env var)
    * the file does not exist
    * the file is empty
    * the JSON is malformed
    * the parsed shape is unexpected (not an object, missing
      ``positions`` key, ``positions`` not a dict, key/value not
      numeric)

    Logs ``event_type='ubi_position_bias_prior_malformed'`` WARN with
    the failure cause on any non-trivial fallback (i.e., the file
    exists but is unusable). The trivial "no file" path is silent.

    Expected file shape::

        {
          "positions": {
            "1": 1.0,
            "2": 0.65,
            "3": 0.45,
            "4": 0.30,
            ...
          }
        }

    Keys may be JSON strings or numbers (JSON itself doesn't allow
    integer object keys, but the loader normalizes both forms to
    ``int``).
    """
    if path is None:
        return {}

    try:
        if not path.exists():
            return {}
        raw_text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning(
            "ubi position-bias prior: read failed, falling back to uninformed",
            event_type="ubi_position_bias_prior_malformed",
            path=str(path),
            cause="read_failed",
            error=str(exc),
        )
        return {}

    if not raw_text:
        return {}

    try:
        parsed: Any = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.warning(
            "ubi position-bias prior: invalid JSON, falling back to uninformed",
            event_type="ubi_position_bias_prior_malformed",
            path=str(path),
            cause="invalid_json",
            error=str(exc),
        )
        return {}

    if not isinstance(parsed, dict):
        logger.warning(
            "ubi position-bias prior: top-level value is not an object, falling back to uninformed",
            event_type="ubi_position_bias_prior_malformed",
            path=str(path),
            cause="not_an_object",
            actual_type=type(parsed).__name__,
        )
        return {}

    positions_raw = parsed.get("positions")
    if not isinstance(positions_raw, dict):
        logger.warning(
            "ubi position-bias prior: 'positions' missing or not an object, falling back",
            event_type="ubi_position_bias_prior_malformed",
            path=str(path),
            cause="positions_not_an_object",
            actual_type=type(positions_raw).__name__ if positions_raw is not None else "None",
        )
        return {}

    out: dict[int, float] = {}
    for key, value in positions_raw.items():
        try:
            rank = int(key)
            weight = float(value)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "ubi position-bias prior: non-numeric entry, falling back to uninformed",
                event_type="ubi_position_bias_prior_malformed",
                path=str(path),
                cause="non_numeric_entry",
                key=str(key),
                value=str(value),
                error=str(exc),
            )
            return {}
        if rank < 1:
            logger.warning(
                "ubi position-bias prior: rank < 1, falling back to uninformed",
                event_type="ubi_position_bias_prior_malformed",
                path=str(path),
                cause="rank_below_one",
                rank=rank,
            )
            return {}
        if weight < 0.0:
            logger.warning(
                "ubi position-bias prior: negative weight, falling back to uninformed",
                event_type="ubi_position_bias_prior_malformed",
                path=str(path),
                cause="negative_weight",
                rank=rank,
                weight=weight,
            )
            return {}
        out[rank] = weight
    return out
