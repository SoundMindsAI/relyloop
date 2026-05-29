# chore_ubi_integration_tests — DB-backed integration tests for UBI

**Date:** 2026-05-29
**Status:** Idea — deferred from `feat_ubi_judgments` Stories 3.1 / 3.2 / 3.3 testing workstream
**Origin:** feat_ubi_judgments PR (per-story unit + contract coverage shipped; DB-backed integration layer deferred — needs the test Postgres + Redis + adapter HTTP-transport mocking infrastructure to compose cleanly)
**Depends on:** `feat_ubi_judgments` shipped
**Priority:** P2

## Problem

`feat_ubi_judgments` Stories 3.1 / 3.2 / 3.3 shipped with:

- Unit tests covering the pure service-layer logic (dispatcher
  preflight, readiness rung classification, mapping_strategy join,
  AsyncOpenAI-construction discipline scan).
- Contract tests covering the wire shapes + Pydantic validator gates
  (UbiReadinessResponse, CreateJudgmentListFromUbiRequest including
  the hybrid conditional, GenerateJudgmentsResponse reuse).

The implementation plan §3.2 also scoped these DB-backed integration
tests, which were NOT shipped in the main UBI PR:

- `backend/tests/integration/test_judgments_generate_from_ubi.py` —
  endpoint end-to-end with stubbed `UbiReader` + adapter; assertion
  on persisted `generation_params` JSONB.
- `backend/tests/integration/test_clusters_ubi_readiness.py` — full 4-
  rung paths against a stubbed adapter via the lifespan-managed FastAPI
  client.
- `backend/tests/integration/test_generate_judgments_from_ubi.py`
  (worker) — clean loop / hybrid LLM-fill / resume-skip / ambiguous-
  mapping per-query skip / UbiInsufficientDataError mid-loop /
  BudgetExceededError mid-hybrid.
- `backend/tests/integration/test_judgment_list_detail_breakdown.py`
  — `JudgmentListDetail.source_breakdown == {llm, human, click}`
  end-to-end via the lifespan-managed client.
- `backend/tests/integration/test_migration_0021_generation_params.py`
  — column shape + nullable + round-trip on the test Postgres.
- `backend/tests/integration/agent/test_generate_judgments_from_ubi_tool.py`
  — tool dispatch round-trip through the orchestrator confirmation guard.

## Proposed capabilities

Ship as a focused test-only PR with the 6 integration test files. Use
the existing `db_session` + `async_client` fixtures from
`backend/tests/integration/conftest.py`; stub the engine adapter via
`monkeypatch.setattr("backend.app.services.cluster.build_adapter", ...)`
and stub `count_ubi_events_in_window` at the dispatcher module-level
attribute path (matches the `test_agent_judgments_dispatch_ubi.py`
pattern shipped in the main PR).

The worker integration test pattern follows `test_budget_guardrail.py`
+ the existing `feat_judgments_periodic_resume_sweep` worker test
shape: MagicMock the adapter, monkeypatch `build_adapter`, fake the
AsyncOpenAI client for the hybrid path.

## Scope signals

- Backend: zero non-test changes.
- Frontend: zero changes.
- Migration: none.
- Config: none.
- Tests added: ~6 files, ~600 LOC.

## Why deferred

The unit + contract tests cover the same logic at finer granularity
without needing the lifespan-managed FastAPI client or the test
Postgres fixtures — fast feedback loop. The integration layer adds
defense-in-depth + catches FastAPI middleware drift the unit layer
can't, but isn't load-bearing for the feature shipping. Splitting it
out keeps the main PR reviewable (already ~2600 LOC across 11 stories
plus docs).
