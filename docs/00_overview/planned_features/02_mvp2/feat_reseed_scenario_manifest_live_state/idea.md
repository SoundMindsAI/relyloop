# Idea — per-run scenario manifest with live per-scenario state (replace "Scenario 0 of 6")

**Date:** 2026-06-18
**Status:** Idea — operator-requested; design chosen via AskUserQuestion ("Checklist + exact live state", the authoritative version)
**Type:** `feat_`
**Priority:** P1 — operator-facing clarity. The current counter is actively misleading: during a scenario's multi-minute Optuna study the dialog reads "Scenario 0 of 6 (0%)" and looks frozen even while the reseed is working. Directly caused two false "it's stuck" reports this session.

## Origin

Operator, looking at the reset-to-demo progress dialog: *"can we provide more details than this… i don't understand what scenario 0 is… nor do i understand what scenario 1 through 6 are"* (screenshot showed "Reseeding demo data… Scenario 0 of 6 (0%)"). Surfaced again immediately after the reseed itself was fixed (`bug_reseed_resolve_engine_base_url_not_idempotent_in_container`, PR #564): with the run genuinely working, "Scenario 0 of 6" still sits still for minutes because the counter only increments when a *whole* scenario completes — and the first scenario runs a full 50-trial study before it does.

## Problem

The reseed status API (`GET /api/v1/_test/demo/reseed/status`, `ReseedStatusResponse`) exposes only `scenarios_total` + `scenarios_completed` (a bare `N of M` counter) plus a free-text `current_step` and a `steps[]` log. The frontend (`ResetDemoStateButton`) renders "Scenario {completed} of {total}". Two concrete failures:

1. **"Scenario 0"** is meaningless — it's the pre-first-scenario window (cleanup/enqueue) plus the entire duration of the first scenario before it finishes. Operators read 0 as "nothing is happening."
2. **The six scenarios are unlabeled** — there's no way to know scenario 1 is "Acme product catalog (ES)" vs scenario 5 being "Support KB (Solr)". `scenarios_skipped` lists raw slugs only, and only at the end.

There is no per-scenario, *live* state surfaced anywhere — the operator can't see "ES product catalog: done · corporate KB: running · news: pending · Solr KB: skipped (engine off)".

## Chosen design (authoritative — "Checklist + exact live state")

A per-run **scenario manifest** carried in the reseed status response, with each scenario's exact live state, rendered as a labeled checklist that replaces the "Scenario N of 6" line.

**Backend:**
- Add `scenarios: list[ScenarioProgress]` to `ReseedStatusResponse`, where `ScenarioProgress = {slug, label, description, engine, state}` and `state ∈ {"pending", "active", "done", "skipped"}`.
- The manifest is built once per run at enqueue/start from the canonical `SCENARIOS` (+ the rich scenario) so its order + membership are deterministic and match what the worker will process. `label`/`description`/`engine` come from a single source-of-truth table (see "Scenario copy" below) keyed by slug.
- The worker (`reseed_demo_state` orchestrator) **stamps per-scenario state transitions** as it goes: `pending → active` when it starts a scenario, `active → done` on success, `→ skipped` when the engine is unreachable or user-excluded (reusing the existing `scenarios_skipped` / `scenarios_skipped_reasons` signal). State is persisted into the same Redis status blob the existing poller already reads (no new endpoint, no new poll loop).
- Keep `scenarios_total` / `scenarios_completed` for back-compat (derive them from the manifest), so nothing else that reads the status breaks.

**Frontend (`ResetDemoStateButton` progress view):**
- Replace the "Scenario {n} of {m}" line with a checklist: one row per manifest entry showing the friendly **label**, an **engine badge** (ES / OpenSearch / Solr), a short **description** (tooltip or muted subtitle), and a **state icon** (pending ○ · active spinner · done ✓ · skipped ⊘-with-reason).
- The active row shows the live `current_step` detail (e.g. "running study — trials 26/50") so a long scenario no longer looks frozen.
- The skipped rows reuse the existing two-reason copy ("you excluded" vs "engine unreachable").

## Scenario copy (proposed — for operator review)

Source-of-truth table keyed by slug. **These labels/descriptions are the operator-facing copy — please review/adjust.**

| Slug | Engine | Proposed label | Proposed one-line description |
|---|---|---|---|
| `acme-products-prod` | Elasticsearch | Acme product catalog | E-commerce product search over an electronics catalog |
| `corp-docs-search` | Elasticsearch | Corporate knowledge base | Internal company docs & wiki article search |
| `news-search-staging` | OpenSearch | News article search | Time-sensitive news/article retrieval |
| `jobs-marketplace-prod` | Elasticsearch | Jobs marketplace | Job-listing search (title + skill matching) |
| `acme-kb-docs-solr` | Solr | Support knowledge base (Solr) | Help-center / support-article search on Apache Solr |
| `acme-products-rich-prod` | Elasticsearch | Rich product demo | 1,000-doc ESCI catalog with LLM-generated relevance judgments |

(Order matches the worker's processing order: the five `SCENARIOS` entries, then the rich ESCI scenario appended as the 6th.)

## Scope signals

- **Backend:** moderate — new `ScenarioProgress` Pydantic model + `scenarios` field on `ReseedStatusResponse`; a slug→{label,description,engine} source-of-truth table (likely beside `SCENARIOS` in `demo_seeding.py` or a small new module); worker orchestrator stamps state transitions into the Redis status blob at each scenario boundary; manifest built at run start. Touches `backend/app/services/demo_seeding.py`, `backend/app/api/v1/_test.py` (status response model), the orchestrator/worker.
- **Frontend:** moderate — rework the `ResetDemoStateButton` progress view from a counter into a checklist; mirror the `ScenarioState` literal + engine labels in `ui/src/lib/`. New `state` enum is an enumerated-value contract → needs the source-of-truth comment + lint-guard discipline (`enums.ts`). Regenerate `ui/openapi.json` + `types.ts`.
- **Migration:** none (Redis-backed test-only status, no DB).
- **Config:** none.
- **Audit events:** N/A (test-only dev endpoint).

## Enumerated-value contract

`ScenarioState` (`pending | active | done | skipped`) and the engine labels become wire values the frontend renders — must follow the §7.4 enumerated-value-contract discipline (backend `Literal[...]` as source of truth, `enums.ts` mirror with a source-of-truth comment, the `form-select`/`data-table` lint guards as applicable).

## Open questions (for spec stage)

1. **Copy** — are the proposed labels/descriptions right, or does the operator want different framing (e.g. lead with the engine, or use the cluster name)?
2. **"Scenario 0" framing** — drop the numeric counter entirely in favor of the checklist, or keep a compact "3 of 6 done" summary above the list? (Recommend: keep a compact summary line for at-a-glance progress, checklist below.)
3. **Description surface** — inline muted subtitle vs hover tooltip (recommend inline subtitle; the dialog has room and tooltips hide the key clarifying text).

## Relationship to other work

- Directly motivated by `bug_reseed_resolve_engine_base_url_not_idempotent_in_container` (PR #564) — fixing the reseed exposed that even a *working* run looks stuck.
- Builds on `feat_selective_engine_startup_and_demo` (the `scenarios_skipped` / `scenarios_skipped_reasons` + reset-modal infrastructure) and `bug_reset_demo_no_instant_feedback_poll_race` (PR #562, the responsive progress view + step log this checklist slots into).
- The separate `feat_reseed_status_sse_streaming` (deferred) would later push these manifest updates over SSE instead of the 2s poll — orthogonal; this feature works fine on the existing poll.
