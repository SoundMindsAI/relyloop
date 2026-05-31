# API Reference

!!! abstract "Summary"
    RelyLoop is agent-first: everything the chat agent does, it does through
    the same versioned HTTP API you can call directly. This page is the
    orientation; the live, generated reference is served by your running stack.

## Where the live reference lives

RelyLoop is a FastAPI application, so the authoritative, always-current API
reference is the OpenAPI schema your own stack serves:

- **Swagger UI** — [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc** — [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Raw schema** — [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

Because the schema is generated from the code, it never drifts from what the
server actually accepts.

## Conventions

- **Business endpoints** are versioned under `/api/v1/<resource>`.
- **Operator endpoints** live at the root — e.g. `/healthz`, which is
  unauthenticated by design and reports subsystem status.
- **Webhooks** are under `/webhooks/<provider>` (e.g. `/webhooks/github`).
- **Errors** use a consistent envelope:
  ```json
  {
    "detail": {
      "error_code": "RESOURCE_NOT_FOUND",
      "message": "human-readable description",
      "retryable": false
    }
  }
  ```
- **Pagination** is cursor-based only: `?cursor=<opaque>&limit=<n>` (default
  50, max 200). List endpoints return an `X-Total-Count` header. There is no
  offset/limit pagination.

## Agent tools map to the API

The conversational agent dispatches the same operations as named tools —
`start_study`, `generate_judgments_*`, `open_proposal`, and friends. Anything
the agent can do, you can script against the API directly. See the in-repo
architecture docs:

- [API conventions](https://github.com/SoundMindsAI/relyloop/blob/main/docs/01_architecture/api-conventions.md)
- [Agent tools](https://github.com/SoundMindsAI/relyloop/blob/main/docs/01_architecture/agent-tools.md)

!!! note "Hosted API reference is coming"
    For now the canonical reference is the OpenAPI schema your stack serves. A
    published, browsable API reference on this site is planned as the API
    surface stabilizes toward v1.0.
