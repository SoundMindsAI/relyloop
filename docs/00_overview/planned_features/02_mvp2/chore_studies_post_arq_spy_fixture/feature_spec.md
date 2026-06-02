# Feature Specification — `arq_pool_spy` fixture for POST /api/v1/studies integration tests

**Date:** 2026-06-02
**Status:** Approved
**Owners:** RelyLoop maintainers (test-infra), Engineering Owner: relevance-platform
**Related docs:**
- [`idea.md`](idea.md)
- [`implementation_plan.md`](implementation_plan.md)
- [`docs/05_quality/testing.md`](../../../../05_quality/testing.md) — test-layer convention + 80% coverage gate
- [`docs/00_overview/implemented_features/2026_05_22_feat_study_preflight_overlap_probe/`](../../../implemented_features/2026_05_22_feat_study_preflight_overlap_probe/) — origin of the gap

---

## 1) Purpose

- **Problem:** The studies POST handler enqueues `start_study` on success (`backend/app/api/v1/studies.py:456` → `_enqueue_start_study` → `arq_pool.enqueue_job("start_study", study_id)` at `studies.py:202`). Every rejection-path integration test asserts no `studies` row was written (`_count_studies()` before/after) but **none asserts that no Arq job was enqueued** — even though several rejection-path docstrings already _claim_ "no Arq job enqueued" (e.g. `test_studies_api.py:248`). A regression in which a rejection branch accidentally enqueued `start_study` before raising would ship undetected.
- **Outcome:** A reusable `arq_pool_spy` integration fixture that records every `enqueue_job(name, *args)` call, letting studies-POST tests positively assert `spy.calls == []` on rejection and `spy.calls == [("start_study", <study_id>)]` on success. The unbacked docstring claims become real, machine-checked assertions across the now-larger rejection-path surface (Tier-1 FK/mismatch rejections + Tier-2 `INSUFFICIENT_JUDGMENT_OVERLAP`).
- **Non-goal:** This does not change any production code in `studies.py`, the worker, or the Arq wiring. It is test-infra only. It does not extend the spy to other enqueueing endpoints (`/judgments/generate`, `/proposals/{id}/open_pr`) — that is a follow-up (see §3 Out of scope).

## 2) Current state audit

### Existing implementations

- `backend/app/api/v1/studies.py:189-202` — `_enqueue_start_study(request, study_id)`: reads `getattr(request.app.state, "arq_pool", None)`; if `None`, returns (no-op); else `await arq_pool.enqueue_job("start_study", study_id)`. Job name + single positional arg is the locked enqueue shape.
- `backend/app/api/v1/studies.py:456` — the call site, inside `create_study`, executed only **after** all validation/FK/overlap-probe rejections have passed (every `raise _err(...)` precedes it).
- `backend/app/main.py:122-137` — `lifespan` builds the real Arq pool via `create_pool(RedisSettings.from_dsn(settings.redis_url))` and assigns `_app.state.arq_pool`. **Best-effort:** if Redis is unreachable the `except` branch logs a warning and `app.state.arq_pool` is **never assigned** (so `getattr(..., None)` yields `None`).
- `backend/tests/integration/conftest.py:138-160` — `async_client` fixture mounts the app via `asgi_lifespan.LifespanManager`, so the lifespan runs and (when CI Redis is up) **builds the real pool**. The fixture docstring (lines 142-148) confirms enqueued `start_study` jobs sit in the queue with no worker consuming them.
- `backend/tests/integration/test_studies_api.py:232-243` — `_count_studies()` helper used by all rejection-path tests to assert no-insert. The spy is the enqueue-side analogue.

### Rejection-path tests that currently lack an enqueue assertion

| Test | Line | Rejection asserted | Has enqueue assertion today? |
|---|---|---|---|
| `test_post_study_invalid_search_space_returns_400` | 164 | 400 `INVALID_SEARCH_SPACE` | No |
| `test_post_study_judgment_query_set_mismatch_returns_422` | 192 | 422 `VALIDATION_ERROR` | No |
| `test_post_study_rejects_target_mismatch` | 246 | 422 `JUDGMENT_TARGET_MISMATCH` | No (docstring claims it — line 248) |
| `test_post_study_rejects_cluster_mismatch` | 276 | 422 `JUDGMENT_CLUSTER_MISMATCH` | No |
| `test_post_study_unknown_judgment_list_returns_404` | 562 | 404 `JUDGMENT_LIST_NOT_FOUND` | No |
| `test_post_study_unknown_template_returns_404` | 583 | 404 `TEMPLATE_NOT_FOUND` | No |
| `test_post_study_unknown_query_set_returns_404` | 604 | 404 `QUERY_SET_NOT_FOUND` | No |
| `test_post_study_unknown_cluster_returns_404` | 625 | 404 `CLUSTER_NOT_FOUND` | No |
| `test_post_study_insufficient_overlap_returns_422` | 817 | 422 `INSUFFICIENT_JUDGMENT_OVERLAP` | No |
| `test_post_study_overlap_one_below_threshold_returns_422` | 936 | 422 `INSUFFICIENT_JUDGMENT_OVERLAP` | No |

Success paths needing a positive assertion: `test_post_study_happy_path_excludes_unset_config_keys` (135), `test_post_study_sufficient_overlap_returns_201` (869), `test_post_study_overlap_at_threshold_returns_201` (903).

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| N/A | — | — |

No UI, no routes — pure test infrastructure.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/integration/test_studies_api.py` | rejection-path tests with `_count_studies()` only | 10 (table above) | Add `arq_pool_spy` param + `assert spy.calls == []` |
| `backend/tests/integration/test_studies_api.py` | success-path POST tests | 3 (135, 869, 903) | Add `arq_pool_spy` param + `assert spy.calls == [("start_study", <id>)]` |
| `backend/tests/integration/conftest.py` | fixture module | 1 | Add `arq_pool_spy` fixture + `SpyArqPool` class (or sibling helper module) |

### Existing behaviors affected by scope change

- **No production behavior changes.** The spy is installed only when a test explicitly requests the `arq_pool_spy` fixture; tests that don't request it are unaffected. Decision needed: no.

---

## 3) Scope

### In scope

- A `SpyArqPool` recording double exposing `async def enqueue_job(self, name, *args, **kwargs)` that appends the **flattened** tuple `(name,) + args` to a `.calls` list (so `enqueue_job("start_study", study_id)` records `("start_study", study_id)`) and returns a truthy sentinel (mirroring `ArqRedis.enqueue_job`'s "returns a `Job` on accept" contract so the handler's `await` resolves like production). See FR-1 / D-3.
- An `install_arq_pool_spy(app)` contextmanager + an `arq_pool_spy` pytest-asyncio fixture in `backend/tests/integration/conftest.py`. The fixture depends on `async_client`, installs the spy into `app.state.arq_pool` **after** the lifespan has built the real pool (via the contextmanager), captures the prior `app.state.arq_pool` value (including the "unset" case), and restores it on teardown.
- Updating the studies-POST rejection-path tests (10, table above) to assert `spy.calls == []`.
- Updating all three studies-POST success-path tests (135, 869, 903) to assert `spy.calls == [("start_study", <created study id>)]`.

### Out of scope

- Extending the spy to other enqueueing endpoints (`POST /api/v1/judgments/generate`, `POST /api/v1/proposals/{id}/open_pr`, config-repo register). Confirmed live enqueue sites in `backend/app/api/v1/judgments.py` + `proposals.py`; generalizing is a natural follow-up but not in this PR.
- Any change to `studies.py`, `main.py`, the worker, or the Arq wiring.
- Asserting enqueue **kwargs** (e.g. `_job_id`); the current handler passes only positionals, so the recorded contract is the flattened `(name, *args)` tuple (kwargs accepted but not recorded).

### API convention check

- **No new endpoint.** This feature touches no router. The only API surface referenced is the existing `POST /api/v1/studies` (prefix + envelope already established in `backend/app/api/v1/studies.py`).
- **Non-auth error envelope** (for reference, unchanged): `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per [`api-conventions.md`](../../../../01_architecture/api-conventions.md) — the rejection tests already assert this shape; the spy adds an orthogonal enqueue assertion.

### Phase boundaries (if multi-phase)

Single-phase. No deferred phases. (The other-endpoints generalization is tracked as an explicit Out-of-scope follow-up, not a deferred phase of this spec.)

## 4) Product principles and constraints

- **Test-infra only, zero production diff.** The fixture must not alter behavior for tests that don't request it.
- **Integration-test mocking policy (CLAUDE.md).** The spy replaces an _external_ side-effect sink (the Arq/Redis `enqueue_job` dispatch), not internal code. DB, repos, services, domain logic still run for real against the test database. Compliant.
- **No leakage across tests.** The app is a module-level singleton (`backend.app.main.app`); the spy MUST restore the prior `app.state.arq_pool` on teardown so a spied test doesn't poison the next test that uses `async_client` directly.
- **Match production await semantics.** `enqueue_job` must be `async` and return a truthy value so `await _enqueue_start_study(...)` behaves identically to production (the handler doesn't inspect the return, but a `None` return could mask a future change that does).

### Anti-patterns

- **Do not** set `app.state.arq_pool = SpyArqPool()` _before_ `async_client`'s `LifespanManager` runs — the lifespan would overwrite the spy with the real pool (or, on Redis-down, leave the spy in place inconsistently). The spy must be installed **after** the lifespan builds the pool. Ordering is guaranteed by depending on `async_client`.
- **Do not** make the fixture autouse. Autouse would silently suppress real enqueues for every integration test, including those that may legitimately exercise the live pool, and would hide the ordering contract. Explicit opt-in per test.
- **Do not** assert on `enqueue_job` **kwargs** or job-id; the handler passes only `("start_study", study_id)` positionally (studies.py:202). Asserting kwargs would couple the test to an implementation detail that isn't part of the contract.
- **Do not** monkeypatch `arq.connections.ArqRedis.enqueue_job` globally — patch the instance on `app.state`, scoped to the test, so the blast radius is one app-state attribute, restored on teardown.
- **Do not** assume `app.state.arq_pool` exists. On Redis-down boots the lifespan leaves it unset (`main.py:133-137`); the teardown restore must handle the "attribute was never set" case (delete it) distinctly from "attribute held a real pool" (reassign it).

## 5) Assumptions and dependencies

- Dependency: `backend/tests/integration/conftest.py` `async_client` fixture (LifespanManager-based).
  - Why required: it owns the app lifecycle window during which `app.state.arq_pool` is valid; the spy must install after it.
  - Status: implemented (conftest.py:138-160).
  - Risk if missing: none — it exists and is the canonical integration client.
- Dependency: the studies-POST enqueue shape `("start_study", study_id)` (studies.py:202).
  - Status: implemented.
  - Risk if missing: if the job name/arg changes, the success-path assertion updates in lockstep — that's the intended coupling (a contract test on the enqueue shape).
- Both features whose deferral this work coordinated with have shipped (`feat_study_preflight_overlap_probe` 2026-05-22, `infra_study_preflight_real_engine_integration` 2026-05-25), so the "infra-sweep" moment has arrived.

## 6) Actors and roles

- Primary actor: RelyLoop maintainers / CI (test execution only).
- Role model: N/A — single-tenant install, no auth surface; this is test code.
- Permission boundaries: N/A.

### Authorization

N/A — single-tenant install, no auth surface. Test infrastructure.

### Audit events

N/A — this feature adds no state-mutating endpoint or service function. It is test code only; no `audit_log` emission applies.

## 7) Functional requirements

### FR-1: `SpyArqPool` recording double
- Requirement:
  - The system **MUST** provide a `SpyArqPool` class with `async def enqueue_job(self, name: str, *args, **kwargs)` that appends a **flattened** call tuple `(name, *args)` (i.e. `(name,) + args`) to an instance `calls: list[tuple]` attribute and returns a truthy sentinel object. For the studies-POST handler's single-positional-arg call `enqueue_job("start_study", study_id)` this records exactly `("start_study", study_id)`.
  - The double **SHOULD** expose `calls` as a public attribute readable by tests without a getter.
  - The double **MAY** accept and ignore `enqueue_job` kwargs (the handler passes none today; tolerating them future-proofs the double — kwargs are NOT recorded, per D-3).
- Notes: mirrors the real `arq.connections.ArqRedis.enqueue_job` async signature + "returns a `Job`-like (truthy) on accept" contract so `await` in `_enqueue_start_study` resolves identically. The flattened recording shape (`(name,) + args`) is the deliberate contract so that `spy.calls == [("start_study", <study_id>)]` reads naturally for single-arg jobs (see D-3 — resolves the spec-internal `args`-tuple ambiguity surfaced by GPT-5.5 cycle 1, finding #1).

### FR-2: `arq_pool_spy` fixture install/restore ordering
- Requirement:
  - The install/restore logic **MUST** be expressed as a single reusable contextmanager helper (e.g. `@contextlib.contextmanager def install_arq_pool_spy(app) -> Iterator[SpyArqPool]`) that captures the prior `app.state.arq_pool` value (or records that the attribute was unset via a sentinel), sets `app.state.arq_pool = SpyArqPool()`, yields the spy, and on exit restores the captured prior value — **deleting** the attribute if it was originally unset, **reassigning** it otherwise.
  - The `arq_pool_spy` pytest fixture **MUST** depend on `async_client` (so installation happens **after** `LifespanManager` builds or skips the real pool) and **MUST** delegate to the contextmanager helper to install/restore, `yield`ing the spy instance.
  - The fixture **MUST NOT** be autouse.
- Notes: handles the Redis-up (attr set to real pool) and Redis-down (attr unset, per main.py:133-137) boot paths. Factoring the install/restore into a contextmanager lets the AC-3 isolation test exercise restoration deterministically **within a single test** (see AC-3) rather than relying on brittle cross-test ordering (GPT-5.5 cycle 1, finding #2).

### FR-3: rejection-path no-enqueue assertions
- Requirement:
  - Every studies-POST rejection-path test listed in §2 **MUST** request `arq_pool_spy` and assert `spy.calls == []` after the rejected POST.
- Notes: this makes the existing unbacked docstring claims (e.g. `test_studies_api.py:248`) real, machine-checked assertions.

### FR-4: success-path positive enqueue assertion
- Requirement:
  - All three studies-POST success-path tests (`test_studies_api.py:135`, `:869`, `:903`) **MUST** request `arq_pool_spy` and assert `spy.calls == [("start_study", <created study id>)]`, where `<created study id>` is the `id` from the 201 response body.
- Notes: locks the enqueue job name + positional-arg shape against regression across the happy path and both overlap-success variants. (FR-4 strengthened to MUST-for-all-three to match §18 DoD — GPT-5.5 cycle 2, finding #2.)

## 8) API and data contract baseline

### 7.1 Endpoint surface

No new or modified endpoints. The only referenced endpoint is the existing `POST /api/v1/studies`.

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/studies` | (existing — referenced only) create study + enqueue `start_study` | `INVALID_SEARCH_SPACE` (400), `JUDGMENT_TARGET_MISMATCH` (422), `JUDGMENT_CLUSTER_MISMATCH` (422), `INSUFFICIENT_JUDGMENT_OVERLAP` (422), `*_NOT_FOUND` (404) |

### 7.2 Contract rules

- No contract change. The spy adds an orthogonal assertion (enqueue count) to existing tests; the HTTP response shape and status codes are unchanged.

### 7.3 Response examples

Unchanged from the existing `POST /api/v1/studies` contract. Success (201) returns a `StudyDetail` with `status: "queued"` (see `test_studies_api.py:156`); rejections return the standard envelope:

```json
{
  "detail": {
    "error_code": "JUDGMENT_TARGET_MISMATCH",
    "message": "judgment_list target='stub-index' does not match study target='docs-articles'; ...",
    "retryable": false
  }
}
```

Auth failure example: N/A — no auth surface.

### 7.4 Enumerated value contracts

N/A — this feature adds no filter, dropdown, sort key, status badge, or any field the backend validates against an allowlist. The only "enumerated" value referenced is the fixed enqueue job name `"start_study"`, whose source of truth is the call at `backend/app/api/v1/studies.py:202` (and the worker function it names). The success-path assertion is grounded directly on that line, not on an invented value.

### 7.5 Error code catalog

No new error codes. Existing codes referenced (for the rejection-path assertions): `INVALID_SEARCH_SPACE`, `VALIDATION_ERROR`, `JUDGMENT_TARGET_MISMATCH`, `JUDGMENT_CLUSTER_MISMATCH`, `INSUFFICIENT_JUDGMENT_OVERLAP`, `JUDGMENT_LIST_NOT_FOUND`, `TEMPLATE_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `CLUSTER_NOT_FOUND`.

## 9) Data model and state transitions

### New/changed entities

None. No migration. No ORM change.

### Required invariants

- Enqueue contract: the studies-POST success path enqueues exactly one job, `("start_study", <study_id>)`; rejection paths enqueue zero. The spy makes this invariant testable.

### State transitions

N/A — no schema, no state machine touched.

### Idempotency/replay behavior

N/A.

## 10) Security, privacy, and compliance

- Threats: none introduced — test-only code path, never reachable in production.
- Controls: N/A.
- Secrets/key handling: N/A — the spy holds no credentials; it replaces the Redis-backed pool with an in-memory recorder.
- Auditability: N/A.
- Data retention: N/A.

## 11) UX flows and edge cases

### Information architecture

N/A — no UI.

### Tooltips and contextual help

N/A — no UI.

### Primary flows

1. A studies-POST integration test requests `arq_pool_spy` + `async_client`; the spy replaces the live pool; the test POSTs; the test reads `spy.calls`.

### Edge/error flows

- **Redis-down boot (CI without Redis service):** lifespan leaves `app.state.arq_pool` unset (main.py:133-137). The spy's capture step records "unset"; install still works (sets the attr); teardown deletes the attr to restore the unset state.
- **Redis-up boot (normal CI):** lifespan sets `app.state.arq_pool` to the real pool. Capture records the real pool; teardown reassigns it.
- **Spy reuse safety:** because teardown restores the prior value, a later test using `async_client` without the spy sees the original (real or unset) pool.

## 12) Given/When/Then acceptance criteria

### AC-1: spy records nothing on a rejection path
- Given a seeded study setup that triggers a target mismatch
- When the test POSTs to `/api/v1/studies` with `arq_pool_spy` installed
- Then the response is 422 `JUDGMENT_TARGET_MISMATCH` AND `spy.calls == []`
- Example values:
  - Input: body with `target="docs-articles"` against a judgment list seeded with `target="stub-index"`
  - Expected: `resp.status_code == 422`; `spy.calls == []`

### AC-2: spy records the enqueue on the success path
- Given a valid study setup that passes all validation + overlap probe
- When the test POSTs to `/api/v1/studies` with `arq_pool_spy` installed
- Then the response is 201 AND `spy.calls == [("start_study", resp.json()["id"])]`
- Example values:
  - Input: `_seed_minimum_for_post_studies()` body with `config={max_trials: 20}`
  - Expected: `resp.status_code == 201`; `spy.calls == [("start_study", <id>)]`

### AC-3: spy install/restore is self-contained (no cross-test leakage)
- Given a single test that uses `async_client` and the `install_arq_pool_spy(app)` contextmanager (NOT the `arq_pool_spy` fixture, so the assertion can observe state after restore)
- When the test records the pre-install `app.state.arq_pool` identity (or its unset-ness), enters the contextmanager, asserts `isinstance(app.state.arq_pool, SpyArqPool)` inside the block, then exits the block
- Then after the block, `app.state.arq_pool` is restored to exactly the pre-install state — same object identity if it was a real pool, or attribute-absent if it was originally unset — and is NOT a `SpyArqPool`
- Example values:
  - If Redis-up: `pre = app.state.arq_pool` (real pool); inside block `isinstance(app.state.arq_pool, SpyArqPool)` is `True`; after block `app.state.arq_pool is pre`.
  - If Redis-down (attr unset): `hasattr(app.state, "arq_pool")` is `False` before; `True` (SpyArqPool) inside; `False` again after.
- Rationale: a self-contained contextmanager-driven test removes the dependency on pytest test ordering that a two-test sequence would have required (GPT-5.5 cycle 1, finding #2).

### AC-4: spy install ordering survives lifespan
- Given the `arq_pool_spy` fixture depends on `async_client`
- When the lifespan builds the real pool
- Then the spy installed by the fixture is the value seen by the handler during the POST (the lifespan does not overwrite it), i.e. `enqueue_job` calls land in `spy.calls`, not on Redis.

## 13) Non-functional requirements

- Performance: negligible — the spy is an in-memory list append; removing the Redis round-trip on spied tests is a marginal speedup.
- Reliability: the fixture must restore state on teardown even if the test body raises (use `yield` + finalizer semantics).
- Operability: N/A — test infra.
- Accessibility: N/A.

## 14) Test strategy requirements (spec-level)

- Unit tests (`backend/tests/unit/`): a focused unit test for `SpyArqPool.enqueue_job` recording behavior + truthy return is acceptable but optional; the double is trivial and exercised by the integration tests. (Recommended: one small unit test asserting `calls` accumulation and truthy return.)
- Integration tests (`backend/tests/integration/test_studies_api.py`): the rejection-path (FR-3) and success-path (FR-4) assertions, plus the self-contained contextmanager restore test (AC-3) and the install-after-lifespan ordering assertion implicit in the success-path test (AC-4 — a recorded `start_study` call proves the spy, not the real pool, received the enqueue).
- Contract tests (`backend/tests/contract/`): N/A — no new endpoint or response shape.
- E2E tests: N/A — no UI.

## 15) Documentation update requirements

- `docs/01_architecture`: N/A.
- `docs/02_product`: N/A.
- `docs/03_runbooks`: optional — a one-line note in the study-lifecycle debugging runbook that `arq_pool_spy` exists for asserting enqueue behavior. Low priority; not a release gate.
- `docs/04_security`: N/A.
- `docs/05_quality`: optional — a sentence in [`testing.md`](../../../../05_quality/testing.md) documenting the `arq_pool_spy` fixture under the integration-mocking-policy section, since it's a sanctioned external-sink double. Recommended.

## 16) Rollout and migration readiness

- Feature flags / staged rollout: N/A — test-only.
- Migration/backfill: none.
- Operational readiness gates: none.
- Release gate: `make test-integration` green (the new assertions pass) + `make lint` + `make typecheck`.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-2, AC-4 | Story 1.1 | `backend/tests/integration/conftest.py`, optional `backend/tests/unit/test_arq_pool_spy.py` | — |
| FR-2 | AC-3, AC-4 | Story 1.1 | `backend/tests/integration/conftest.py`, `test_studies_api.py` (isolation test) | `docs/05_quality/testing.md` (optional) |
| FR-3 | AC-1 | Story 1.2 | `backend/tests/integration/test_studies_api.py` (10 rejection tests) | — |
| FR-4 | AC-2 | Story 1.2 | `backend/tests/integration/test_studies_api.py` (3 success tests) | — |

## 18) Definition of feature done

- [ ] `SpyArqPool` + `arq_pool_spy` fixture land in `conftest.py` with correct install-after-lifespan ordering and capture/restore teardown (FR-1, FR-2).
- [ ] All 10 rejection-path tests assert `spy.calls == []` (FR-3, AC-1).
- [ ] At least the 3 success-path tests assert `spy.calls == [("start_study", <id>)]` (FR-4, AC-2).
- [ ] An isolation test confirms no spy leakage across tests (AC-3).
- [ ] `make test-integration`, `make lint`, `make typecheck` green.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None. All forks locked below.

### Decision log

- 2026-06-02 — **D-1: Fixture is opt-in, not autouse.** Autouse would silently suppress real enqueues for every integration test and hide the ordering contract. Tests opt in by requesting `arq_pool_spy`. Rationale: explicit > implicit; preserves the live-pool path for tests that want it.
- 2026-06-02 — **D-2: Install after lifespan by depending on `async_client`.** The lifespan owns the `app.state.arq_pool` window; installing before it would let the lifespan overwrite the spy. Depending on `async_client` guarantees correct ordering without a manual barrier. Rationale: matches how `main.py:122-137` wires the pool.
- 2026-06-02 — **D-3: Record flattened `(name, *args)` tuples, not kwargs/job-id.** The handler passes only positionals `("start_study", study_id)` (studies.py:202). The double appends `(name,) + args` so a single-arg job records as `("start_study", study_id)` — making `spy.calls == [("start_study", study_id)]` the natural assertion. Recording the raw `(name, args)` (with `args` as a varargs tuple) would instead yield `("start_study", (study_id,))` and silently break every planned assertion. kwargs are accepted but not recorded. Rationale: assert the contract, not the implementation; resolve the spec-internal shape ambiguity (GPT-5.5 cycle 1, finding #1).
- 2026-06-02 — **D-4: `enqueue_job` returns a truthy sentinel.** Mirrors `ArqRedis.enqueue_job`'s "returns a `Job` on accept" so `await` resolves like production and a future handler that inspects the return isn't masked by a `None`. Rationale: production-faithful double.
- 2026-06-02 — **D-5: Teardown handles the unset-attribute case.** On Redis-down boots the lifespan never sets `app.state.arq_pool` (main.py:133-137); teardown deletes the attr to restore "unset", and reassigns the captured real pool otherwise. Rationale: the module-level `app` singleton must not leak the spy.
- 2026-06-02 — **D-6: Other enqueueing endpoints out of scope.** `/judgments/generate` + `/proposals/{id}/open_pr` also enqueue, but generalizing the spy is a follow-up once the studies-POST pattern is proven. Rationale: keep the PR small and reviewable; prove the pattern first.

---

## Cross-model review log (spec)

Mandatory GPT-5.5 cross-model review per spec-gen Step 6. Model: `gpt-5.5` via OpenAI Chat Completions (`max_completion_tokens`, JSON-mode). Key resolved from `.env`. **3 cycles to convergence; 4 findings total; 4 accepted, 0 rejected, 0 deferred.**

| Cycle | Finding | Severity / Pass | Adjudication |
|---|---|---|---|
| 1 | Call-shape inconsistency: FR-1/D-3 said `(name, args)` (varargs tuple) but assertions need `(name, study_id)` — `enqueue_job("start_study", study_id)` would record `("start_study", (study_id,))` and break every planned assertion. | Medium / A | **Accept** — locked the **flattened** `(name,) + args` recording shape in FR-1 and D-3. |
| 1 | AC-3 leakage test relied on brittle two-test ordering; a test cannot inspect its own fixture's post-teardown state. | Low / B | **Accept** — factored install/restore into an `install_arq_pool_spy(app)` contextmanager (FR-2); rewrote AC-3 as a single self-contained test. |
| 2 | Residual `(name, args)` language remained in the §3 In-scope and Out-of-scope bullets, contradicting the fixed FR-1/D-3. | Medium / A | **Accept** — rewrote both §3 bullets to the flattened shape. |
| 2 | FR-4 weaker (1 MUST + 3 SHOULD) than §18 DoD (all 3 required), risking missed positive coverage on the overlap-success variants. | Low / B | **Accept** — strengthened FR-4 to require all three success-path tests as MUST. |
| 3 | — | — | **Clean pass — `{"findings":[]}`. Converged.** |
