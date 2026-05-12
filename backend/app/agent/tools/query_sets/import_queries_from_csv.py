"""``import_queries_from_csv`` tool — bulk-add queries to a query set from CSV text.

This is a MUTATING tool (per spec FR-5 + §19 Decision log) — the orchestrator's
confirmation guard requires an affirmative user message before dispatch.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.agent.context import ToolContext
from backend.app.db import repo
from backend.app.domain.study.csv_parser import InvalidCsvError, parse_queries_csv


class ImportQueriesFromCsvArgs(BaseModel):
    """Arguments for the ``import_queries_from_csv`` tool."""

    query_set_id: UUID = Field(description="Query set to populate.")
    csv_text: str = Field(
        min_length=1,
        max_length=2_000_000,
        description=(
            "CSV body. Headers must include 'query_text'; optional columns are "
            "'reference_answer' and 'query_metadata' (JSON-encoded string). "
            "Same parser the POST /query-sets/{id}/queries endpoint uses."
        ),
    )


async def import_queries_from_csv_impl(
    args: ImportQueriesFromCsvArgs, ctx: ToolContext
) -> dict[str, Any]:
    """Bulk-add queries to an existing query set from CSV text.

    Returns ``{"added": <count>}``. Raises ``QUERY_SET_NOT_FOUND`` (404) if the
    query set id is unknown, ``INVALID_CSV`` (400) if the CSV body fails the
    parser. Mutating — confirmation required.
    """
    qs = await repo.get_query_set(ctx.db, str(args.query_set_id))
    if qs is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "QUERY_SET_NOT_FOUND",
                "message": f"query set {args.query_set_id} not found",
                "retryable": False,
            },
        )
    try:
        rows = parse_queries_csv(args.csv_text.encode("utf-8"))
    except InvalidCsvError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_CSV",
                "message": str(exc),
                "retryable": False,
            },
        ) from exc
    added = await repo.bulk_create_queries(ctx.db, str(args.query_set_id), rows)
    await ctx.db.commit()
    return {"added": added}


_DESCRIPTION = (import_queries_from_csv_impl.__doc__ or "").split("\n\n", 1)[0].strip()

IMPORT_QUERIES_FROM_CSV_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "import_queries_from_csv",
        "description": _DESCRIPTION,
        "parameters": ImportQueriesFromCsvArgs.model_json_schema(),
    },
}
