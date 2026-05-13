# Idea — proposals source filter on the backend

**Date:** 2026-05-12
**Status:** Idea — deferred follow-up from `feat_proposals_ui`
**Owners:** TBD
**Origin:** `feat_proposals_ui` Story 2.1 + plan §6 risks row "Pagination unaware of client-side source filter" (logged 2026-05-12 during the GPT-5.5 cycle-1 review as finding A5).

---

## Problem

The proposals list page at `/proposals` ships with a three-state source filter chip group (`all` / `study` / `manual`) shipped in `feat_proposals_ui` Story 1.2. Because the backend `GET /api/v1/proposals` endpoint has no `?source=` query parameter, the UI applies the filter **client-side** after the cursor-paginated page lands. The result:

- The filter trims the *visible* rows on the current page.
- The paginator's `has_more` + `next_cursor` are computed by the backend over the unfiltered set.
- Selecting `manual` while the dataset is dominated by study-sourced proposals can show 0–3 rows on the current page even though many `manual` proposals exist further along in the cursor walk.
- `X-Total-Count` reflects the unfiltered backend total, so the operator sees a count that doesn't match the visible row count.

This is acceptable for MVP1 (<50 proposals/page realistically) and is logged inline in `ui/src/app/proposals/page.tsx` next to the `setSource` callback. The fix is a backend-side `?source=study|manual` filter.

## Why deferred

- The MVP1 single-tenant install is unlikely to accumulate enough manual proposals to make the partial-page artifact noticeable.
- Adding a backend filter requires touching `backend/app/api/v1/proposals.py:list_proposals_endpoint` + the matching repo function in `backend/app/db/repo/proposal.py` + a contract-test extension. It's straightforward but out of scope for the UI feature.
- The frontend will switch over cleanly once the backend supports it — the page's `useProposals(filter, options?)` call site just needs an additional `source: sourceFilter` field, and the client-side `visibleRows` filter can be deleted.

## Proposed capabilities

- Backend: extend `GET /api/v1/proposals` with `?source=study|manual` (Pydantic `Literal["study", "manual"]`), implemented as `WHERE study_id IS NOT NULL` / `WHERE study_id IS NULL` filters in `list_proposals_paginated` and `count_proposals`.
- Backend contract test: extend `backend/tests/contract/test_digest_proposal_api_contract.py` (or a sibling file) to assert the new query param appears in the OpenAPI spec.
- Frontend: drop the client-side filter in `ui/src/app/proposals/page.tsx`. Pass `source: sourceFilter !== 'all' ? sourceFilter : undefined` into `useProposals`.

## Scope signals

- **Backend impact:** small — one endpoint signature extension, one repo function change, one contract assertion.
- **Frontend impact:** small — drop ~10 lines, add 1 param pass-through.
- **Migration:** none.
- **Config:** none.

## Dependencies

- `feat_proposals_ui` (this folder's parent) must be merged so the page exists.

## Out of scope

- Renaming the `source` Literal to something more descriptive — leave as `study|manual` for symmetry with the existing UI.
- Adding more source distinctions (e.g. `chat`) — track separately if the chat agent ever creates proposals distinguishable from "manual".
