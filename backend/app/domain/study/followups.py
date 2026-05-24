"""Discriminated-union models for LLM-suggested digest follow-ups.

Owner: ``feat_digest_executable_followups``.

Pure-domain helpers (no I/O, no async, no DB). Three concrete kinds:

- :class:`NarrowFollowup` — "the winner sits in a sub-region of the prior
  search space; re-run with a tighter range to confirm."
- :class:`WidenFollowup` — "the winner hit an edge of the prior search
  space; re-run with a broader range to find a possibly-better setting."
- :class:`TextFollowup` — free-form suggestion the operator must interpret
  manually (no auto-prefill).

The discriminator is ``kind``; ``narrow`` and ``widen`` carry a validated
:class:`~backend.app.domain.study.search_space.SearchSpace` while ``text``
carries ``search_space = None``.

:func:`parse_followup_list` is the defensive ingest path for both legacy
``list[str]`` rows (pre-MVP1.X digests) and current
``list[dict]`` payloads emitted by the digest worker's structured-output
contract. It never raises — invalid items either degrade to ``text``
(when a rationale is salvageable) or are dropped, both with structlog
``WARN`` events.

:func:`serialize_followup_list` is the JSONB-safe serializer: SQLAlchemy's
JSONB driver does not know how to serialize Pydantic ``BaseModel``
instances directly, so the worker calls this helper before assigning to
:attr:`backend.app.db.models.digest.Digest.suggested_followups`.

Spec: ``docs/02_product/planned_features/feat_digest_executable_followups/feature_spec.md``
(FR-2 / FR-3 / FR-4).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from backend.app.domain.study.search_space import SearchSpace

# Use stdlib ``logging`` (routed through structlog at runtime per
# ``backend.app.core.logging.configure_logging``) so the WARN events are
# capturable in unit tests via the standard ``caplog`` fixture. Calling
# ``structlog.get_logger`` directly here would emit through structlog's
# native factory before configure_logging wires it into stdlib, and
# caplog wouldn't see the records during pure-domain unit tests.
logger = logging.getLogger(__name__)


# Max length of the validation error or unparseable item string embedded in
# WARN logs or downgrade rationales — keeps log lines bounded.
_TRUNCATE_LIMIT = 200


def _truncate(text: str) -> str:
    """Truncate ``text`` to ``_TRUNCATE_LIMIT`` characters with an ellipsis.

    Used for WARN-log fields and downgrade-rationale prefixes so a runaway
    LLM payload doesn't flood structured logs.
    """
    if len(text) <= _TRUNCATE_LIMIT:
        return text
    return text[:_TRUNCATE_LIMIT] + "..."


class NarrowFollowup(BaseModel):
    """A 'narrow' followup — re-run with a tighter range than the parent."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["narrow"]
    rationale: str
    search_space: SearchSpace


class WidenFollowup(BaseModel):
    """A 'widen' followup — re-run with a broader range than the parent."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["widen"]
    rationale: str
    search_space: SearchSpace


class TextFollowup(BaseModel):
    """A free-form textual suggestion — no auto-prefill, operator interprets."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["text"]
    rationale: str
    search_space: None = None


type FollowupItem = Annotated[
    NarrowFollowup | WidenFollowup | TextFollowup,
    Field(discriminator="kind"),
]
"""Discriminated union over the three concrete followup kinds."""

FollowupItemAdapter: TypeAdapter[FollowupItem] = TypeAdapter(FollowupItem)
FollowupListAdapter: TypeAdapter[list[FollowupItem]] = TypeAdapter(list[FollowupItem])


def _emit_downgrade_warn(
    *,
    study_id: str | None,
    proposal_id: str | None,
    original_kind: str,
    validation_error: str,
) -> None:
    """Emit the canonical ``digest_followup_validation_downgraded`` WARN.

    Centralized so the field names are guaranteed identical across all
    call sites — runbooks grep on these field names.

    Uses stdlib ``logging`` with ``extra=`` so structlog's
    ``ProcessorFormatter`` (configured by
    ``backend.app.core.logging.configure_logging``) renders the fields
    into the canonical JSON shape AND the pytest ``caplog`` fixture
    captures them as LogRecord attributes.
    """
    logger.warning(
        "digest_followup_validation_downgraded",
        extra={
            "event_type": "digest_followup_validation_downgraded",
            "study_id": study_id,
            "proposal_id": proposal_id,
            "original_kind": original_kind,
            "validation_error": _truncate(validation_error),
        },
    )


def _emit_drop_warn(
    *,
    study_id: str | None,
    proposal_id: str | None,
    unparseable_item: str,
) -> None:
    """Emit the canonical ``digest_followup_dropped`` WARN."""
    logger.warning(
        "digest_followup_dropped",
        extra={
            "event_type": "digest_followup_dropped",
            "study_id": study_id,
            "proposal_id": proposal_id,
            "unparseable_item": _truncate(unparseable_item),
        },
    )


def _wrap_legacy_string(rationale: str) -> TextFollowup:
    """Wrap a legacy ``list[str]`` row entry as a structured ``text`` item."""
    return TextFollowup(kind="text", rationale=rationale, search_space=None)


def _try_text_only(
    raw_item: dict[str, Any],
    *,
    study_id: str | None,
    proposal_id: str | None,
    original_kind: str,
    validation_error: str,
) -> FollowupItem | None:
    """Build a downgrade ``TextFollowup`` from the salvageable rationale.

    Returns ``None`` if no usable rationale exists (caller will drop +
    emit the drop WARN).
    """
    rationale = raw_item.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        return None
    _emit_downgrade_warn(
        study_id=study_id,
        proposal_id=proposal_id,
        original_kind=original_kind,
        validation_error=validation_error,
    )
    prefix = f"[validation failed: {_truncate(validation_error)}] "
    return TextFollowup(
        kind="text",
        rationale=prefix + rationale,
        search_space=None,
    )


def parse_followup_list(
    raw: object,
    *,
    study_id: str | None = None,
    proposal_id: str | None = None,
) -> list[FollowupItem]:
    """Defensively parse a JSONB ``suggested_followups`` payload.

    Decision table (FR-4):

    +-----------------------------------------+-------------------------------------------+
    | Input shape                             | Output                                    |
    +=========================================+===========================================+
    | ``None`` / non-list top-level           | ``[]`` (no log — covers fresh-empty case) |
    +-----------------------------------------+-------------------------------------------+
    | ``list[str]`` (legacy)                  | each str → :class:`TextFollowup`          |
    +-----------------------------------------+-------------------------------------------+
    | ``list[dict]`` with valid ``kind`` +    | parsed via :data:`FollowupItemAdapter`    |
    | passing ``search_space``                |                                           |
    +-----------------------------------------+-------------------------------------------+
    | ``list[dict]`` with valid ``kind`` but  | downgraded to ``text`` with               |
    | failing ``search_space`` (e.g.          | ``[validation failed: ...] <rationale>``  |
    | cardinality > 10⁶)                      | + WARN ``digest_followup_validation_      |
    |                                         | downgraded``                              |
    +-----------------------------------------+-------------------------------------------+
    | ``list[dict]`` with unknown ``kind``    | downgraded to ``text`` if rationale       |
    | or otherwise-invalid extras             | salvageable, else dropped                 |
    +-----------------------------------------+-------------------------------------------+
    | ``list[dict]`` with no rationale and    | dropped + WARN                            |
    | otherwise-invalid                       | ``digest_followup_dropped``               |
    +-----------------------------------------+-------------------------------------------+
    | mixed: legal items + invalid items      | legal items pass through; invalid items   |
    |                                         | follow the above rules                    |
    +-----------------------------------------+-------------------------------------------+

    NEVER raises. The contract is: every consumer can blindly call this
    helper on whatever sits in the JSONB column and get a structured
    list back.
    """
    if not isinstance(raw, list):
        # None, dict, scalar, etc. — log ERROR-equivalent WARN with an
        # explicit top-level indicator and return empty.
        if raw is not None:
            logger.warning(
                "digest_followups_top_level_malformed",
                extra={
                    "event_type": "digest_followups_top_level_malformed",
                    "study_id": study_id,
                    "proposal_id": proposal_id,
                    "unparseable_item": _truncate(repr(raw)),
                },
            )
        return []

    result: list[FollowupItem] = []
    for item in raw:
        # Legacy ``list[str]`` row — wrap each string as a ``text`` item
        # WITHOUT emitting a WARN (this is an expected back-compat path,
        # not an error condition).
        if isinstance(item, str):
            result.append(_wrap_legacy_string(item))
            continue

        if not isinstance(item, dict):
            _emit_drop_warn(
                study_id=study_id,
                proposal_id=proposal_id,
                unparseable_item=repr(item),
            )
            continue

        original_kind = item.get("kind") if isinstance(item.get("kind"), str) else "<missing>"

        try:
            validated = FollowupItemAdapter.validate_python(item)
        except ValidationError as exc:
            # Try the downgrade path: keep rationale, drop search_space,
            # mark as ``text``. Only succeeds when the original payload
            # has a usable string rationale.
            downgraded = _try_text_only(
                item,
                study_id=study_id,
                proposal_id=proposal_id,
                original_kind=str(original_kind),
                validation_error=str(exc),
            )
            if downgraded is not None:
                result.append(downgraded)
            else:
                _emit_drop_warn(
                    study_id=study_id,
                    proposal_id=proposal_id,
                    unparseable_item=repr(item),
                )
            continue

        result.append(validated)

    return result


def serialize_followup_list(items: list[FollowupItem]) -> list[dict[str, Any]]:
    """Serialize a list of :data:`FollowupItem` to JSONB-safe dicts.

    Called by the digest worker before assigning to
    :attr:`backend.app.db.models.digest.Digest.suggested_followups`.
    SQLAlchemy's JSONB driver does not know how to serialize Pydantic
    ``BaseModel`` instances directly (per spec D-24); ``model_dump(mode='json')``
    produces a pure-JSON-compatible dict.
    """
    return [item.model_dump(mode="json") for item in items]


__all__ = [
    "FollowupItem",
    "FollowupItemAdapter",
    "FollowupListAdapter",
    "NarrowFollowup",
    "TextFollowup",
    "WidenFollowup",
    "parse_followup_list",
    "serialize_followup_list",
]
