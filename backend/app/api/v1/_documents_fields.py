"""Parse the ``?fields=`` CSV query param for the documents browse endpoint.

Spec FR-3 / D-21: the ``fields`` param selects which ``_source`` keys are
returned by the engine. We accept dotted paths (``title.keyword``), reject
wildcards (``*``, ``title*``), trim whitespace, drop empty segments, and
de-duplicate preserving first-seen order.
"""

from __future__ import annotations

from backend.app.api.v1._errors import _err


def parse_fields_csv(raw: str | None) -> list[str] | None:
    """Parse a CSV ``fields=`` value into a deduped, trimmed list.

    Returns ``None`` when ``raw`` is ``None`` or when every segment is empty
    after trimming — treats ``?fields=`` and ``?fields=,,,`` as absent.

    Raises ``HTTPException(422, VALIDATION_ERROR)`` on any wildcard segment
    (``*`` or anything containing ``*``).
    """
    if raw is None:
        return None
    seen: set[str] = set()
    out: list[str] = []
    for segment in raw.split(","):
        trimmed = segment.strip()
        if not trimmed:
            continue
        if "*" in trimmed:
            raise _err(
                422,
                "VALIDATION_ERROR",
                f"wildcard not allowed in fields: {trimmed!r}",
                False,
            )
        if trimmed in seen:
            continue
        seen.add(trimmed)
        out.append(trimmed)
    return out or None
