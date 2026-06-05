# Implementation Plan — `arq_pool_spy` fixture for POST /api/v1/studies integration tests

**Date:** 2026-06-02
**Status:** Ready for Execution
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../../CLAUDE.md) (Integration Test Mocking Policy, test layers); [`docs/05_quality/testing.md`](../../../../05_quality/testing.md)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs (FR-1…FR-4).
- Test-infra only — zero production diff. No migration, no endpoint, no UI.
- Fail-loud assertions: assert exact `spy.calls` contents, not just truthiness.
- Match production await semantics in the double (async, truthy return).
- Keep the fixture opt-in and lifecycle-correct (install after lifespan, restore on teardown).

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Phase | Notes |
|---|---|---|
| FR-1 | Epic 1 / Story 1.1 | `SpyArqPool` recording double (flattened `(name,)+args`, truthy return) |
| FR-2 | Epic 1 / Story 1.1 | `install_arq_pool_spy(app)` contextmanager + `arq_pool_spy` fixture (install-after-lifespan, capture/restore, not autouse) |
| FR-3 | Epic 1 / Story 1.2 | 10 rejection-path tests assert `spy.calls == []` |
| FR-4 | Epic 1 / Story 1.2 | 3 success-path tests assert `spy.calls == [("start_study", <id>)]` |

No FRs are deferred to a future phase. Single-phase plan covering the spec in full. (The other-endpoints generalization is an explicit Out-of-scope follow-up in the spec §3, not a deferred phase requiring a `phase<N>_idea.md` tracking file.)

## 2) Delivery structure

**Epic → Story → Tasks → DoD** (test-only; two stories: build the fixture, then wire the assertions).

### Conventions (project-specific)

```
- Integration fixtures live in backend/tests/integration/conftest.py
- pytest-asyncio fixtures use @pytest_asyncio.fixture; the existing async_client
  fixture (conftest.py:138-160) is the canonical app-mounted client and owns the
  app lifecycle window via asgi_lifespan.LifespanManager
- Integration tests only mock external services (here: the Arq/Redis enqueue sink);
  DB, repos, services, domain all run for real (CLAUDE.md Integration Test Mocking Policy)
- App is the module-level singleton backend.app.main.app; fixtures that mutate
  app.state MUST restore it on teardown
- No production code under backend/app/ is modified by this plan
```

### AI Agent Execution Protocol (applies to every story)

0. **Load context first:** read `architecture.md` and `state.md`.
1. Read scope: verify story outcome + key interfaces + DoD.
2. Implement the fixture (Story 1.1) before wiring assertions (Story 1.2) — Story 1.2 depends on the fixture existing.
3. Run `make test-integration` (or the targeted `pytest backend/tests/integration/test_studies_api.py`) after each story.
4. No frontend, no E2E, no migration.
5. Run `make lint` + `make typecheck` before considering a story done.
6. Attach evidence in the PR description: commands run, pass/fail, files changed.
7. After the final story, evaluate whether `docs/05_quality/testing.md` needs the one-line `arq_pool_spy` note (optional per spec §15).

---

## Epic 1 — `arq_pool_spy` integration fixture + studies-POST enqueue assertions

**Epic gate (hard stop):** `arq_pool_spy` fixture lands and is correctly ordered (FR-1, FR-2); all 10 rejection-path tests assert `spy.calls == []` (FR-3); all 3 success-path tests assert `spy.calls == [("start_study", <id>)]` (FR-4); `make test-integration` + `make lint` + `make typecheck` green.

### Story 1.1 — `SpyArqPool` double + `install_arq_pool_spy` contextmanager + `arq_pool_spy` fixture

**Outcome:** Integration tests can install an in-memory Arq pool double that records `enqueue_job` calls, with correct install-after-lifespan ordering and leak-free teardown.

**New files** (optional)

| File | Purpose |
|---|---|
| `backend/tests/unit/test_arq_pool_spy.py` | **(optional, recommended)** New unit test asserting `SpyArqPool.enqueue_job` records the flattened tuple and returns a truthy sentinel. Imports `SpyArqPool` from `backend.tests.integration.conftest`. |

The fixture/double additions land in the existing `conftest.py` (Modified files below); the only potential new file is the optional unit test above.

**Modified files**

| File | Change |
|---|---|
| `backend/tests/integration/conftest.py` | Add `SpyArqPool` class, `_UNSET` sentinel, `install_arq_pool_spy(app)` contextmanager, and the `arq_pool_spy` pytest-asyncio fixture (depends on `async_client`). Add `contextlib` + `collections.abc` (`Iterator`) imports (`AsyncIterator`, `httpx`, `pytest_asyncio` already imported). |

**Endpoints:** N/A — test-only story.

**Key interfaces**

```python
# backend/tests/integration/conftest.py
import contextlib
from collections.abc import AsyncIterator, Iterator

from fastapi import FastAPI  # for the contextmanager's app param type


class SpyArqPool:
    """In-memory recording double for arq.connections.ArqRedis.

    Records each enqueue_job call as a flattened (name, *args) tuple so the
    studies-POST handler's enqueue_job("start_study", study_id) records
    ("start_study", study_id). Returns a truthy sentinel to mirror
    ArqRedis.enqueue_job's "returns a Job on accept" contract (FR-1 / D-3, D-4).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def enqueue_job(
        self, name: str, *args: object, **kwargs: object
    ) -> object:
        self.calls.append((name, *args))   # flattened: (name,) + args
        return object()                    # truthy sentinel (not None)


_UNSET: object = object()  # sentinel distinguishing "attr unset" from "attr is None"


@contextlib.contextmanager
def install_arq_pool_spy(app: FastAPI) -> Iterator[SpyArqPool]:
    """Install a SpyArqPool on app.state.arq_pool; restore prior value on exit.

    Captures the prior value (or _UNSET if the attribute was never set, which
    happens on Redis-down boots per backend/app/main.py:133-137). On exit,
    deletes the attribute if it was originally unset, else reassigns the captured
    value (FR-2 / D-5).
    """
    prior = getattr(app.state, "arq_pool", _UNSET)
    spy = SpyArqPool()
    app.state.arq_pool = spy
    try:
        yield spy
    finally:
        if prior is _UNSET:
            # delattr is safe: we set it above, so it exists now.
            delattr(app.state, "arq_pool")
        else:
            app.state.arq_pool = prior


@pytest_asyncio.fixture
async def arq_pool_spy(async_client: httpx.AsyncClient) -> AsyncIterator[SpyArqPool]:
    """Yield a SpyArqPool installed on the live app after the lifespan built
    (or skipped) the real pool. Depends on async_client so install ordering is
    correct (FR-2 / D-2). NOT autouse (D-1)."""
    from backend.app.main import app

    with install_arq_pool_spy(app) as spy:
        yield spy
```

> **Typecheck note (mypy --strict):** `app: FastAPI` exposes `.state` (a `starlette.datastructures.State`); `getattr`/`delattr`/attribute-set on `State` are typed `Any`, so the capture/restore lines are clean. `list[tuple[object, ...]]` is a fully-parameterized generic. The optional unit test imports `SpyArqPool` from the integration conftest, which is an import-time-safe module (no DB/Redis side effects at import).

> **Note on `app.state`:** `starlette.datastructures.State` stores attributes in `__dict__`, so `getattr(app.state, "arq_pool", _UNSET)` and `delattr(app.state, "arq_pool")` behave as expected. The fixture imports the same module-level `app` that `async_client` mounts (`backend.app.main.app`), so the spy is installed on the exact instance the handler reads from `request.app.state`.

**Pydantic schemas:** N/A.

**Tasks**
1. Add `import contextlib` and `from collections.abc import AsyncIterator, Iterator` to `conftest.py` (it already imports `httpx`, `pytest_asyncio`).
2. Add the `SpyArqPool` class, `_UNSET` sentinel, `install_arq_pool_spy` contextmanager, and `arq_pool_spy` fixture per the interfaces above.
3. (Optional, recommended) Add `backend/tests/unit/test_arq_pool_spy.py` with a test that constructs `SpyArqPool`, awaits `enqueue_job("start_study", "study-123")`, and asserts `pool.calls == [("start_study", "study-123")]` and that the return value is truthy. Import `SpyArqPool` from `backend.tests.integration.conftest`.
4. Run `make lint` + `make typecheck` to confirm the additions pass ruff + mypy --strict.

**Definition of Done (DoD)**
- `SpyArqPool.enqueue_job` is `async`, records the flattened `(name,)+args` tuple, and returns a truthy (non-`None`) value (FR-1, D-3, D-4).
- `install_arq_pool_spy(app)` captures the prior `app.state.arq_pool` (handling the unset case via `_UNSET`), installs the spy, and on exit restores exactly the prior state — `delattr` when originally unset, reassign otherwise (FR-2, D-5).
- `arq_pool_spy` fixture depends on `async_client`, is NOT autouse, and yields the spy (FR-2, D-1, D-2).
- (If added) `backend/tests/unit/test_arq_pool_spy.py` passes under `make test-unit`.
- `make lint` + `make typecheck` green.

### Story 1.2 — Wire enqueue assertions into studies-POST integration tests

**Outcome:** Every studies-POST rejection path positively asserts no enqueue; every success path asserts exactly the `start_study` enqueue. The AC-3 restore behavior is verified by a self-contained test.

**New files:** none.

**Modified files**

| File | Change |
|---|---|
| `backend/tests/integration/test_studies_api.py` | Add `arq_pool_spy: SpyArqPool` param to the 10 rejection-path tests + assert `spy.calls == []`. Add the param to the 3 success-path tests + assert `spy.calls == [("start_study", <id>)]`. Add one self-contained AC-3 restore test using `install_arq_pool_spy`. Add `from backend.tests.integration.conftest import SpyArqPool, install_arq_pool_spy` import. |

**Endpoints:** N/A — exercises the existing `POST /api/v1/studies`; no contract change.

**Rejection-path tests to update (FR-3, AC-1) — assert `spy.calls == []`:**

| Test | Line | Rejection |
|---|---|---|
| `test_post_study_invalid_search_space_returns_400` | 164 | 400 `INVALID_SEARCH_SPACE` |
| `test_post_study_judgment_query_set_mismatch_returns_422` | 192 | 422 `VALIDATION_ERROR` |
| `test_post_study_rejects_target_mismatch` | 246 | 422 `JUDGMENT_TARGET_MISMATCH` |
| `test_post_study_rejects_cluster_mismatch` | 276 | 422 `JUDGMENT_CLUSTER_MISMATCH` |
| `test_post_study_unknown_judgment_list_returns_404` | 562 | 404 `JUDGMENT_LIST_NOT_FOUND` |
| `test_post_study_unknown_template_returns_404` | 583 | 404 `TEMPLATE_NOT_FOUND` |
| `test_post_study_unknown_query_set_returns_404` | 604 | 404 `QUERY_SET_NOT_FOUND` |
| `test_post_study_unknown_cluster_returns_404` | 625 | 404 `CLUSTER_NOT_FOUND` |
| `test_post_study_insufficient_overlap_returns_422` | 817 | 422 `INSUFFICIENT_JUDGMENT_OVERLAP` |
| `test_post_study_overlap_one_below_threshold_returns_422` | 936 | 422 `INSUFFICIENT_JUDGMENT_OVERLAP` |

**Success-path tests to update (FR-4, AC-2) — assert `spy.calls == [("start_study", <id>)]`:**

| Test | Line | Path |
|---|---|---|
| `test_post_study_happy_path_excludes_unset_config_keys` | 135 | happy path |
| `test_post_study_sufficient_overlap_returns_201` | 869 | overlap sufficient |
| `test_post_study_overlap_at_threshold_returns_201` | 903 | overlap at threshold |

**Key interfaces (per-test edit shape)**

Rejection-path edit (example, `test_post_study_rejects_target_mismatch`):

```python
async def test_post_study_rejects_target_mismatch(
    async_client: httpx.AsyncClient, arq_pool_spy: SpyArqPool
) -> None:
    ...
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 422, resp.text
    ...
    after = await _count_studies(None)
    assert after == before, "JUDGMENT_TARGET_MISMATCH must NOT insert a studies row"
    assert arq_pool_spy.calls == [], "rejection path must not enqueue start_study"
```

Success-path edit (example, `test_post_study_happy_path_excludes_unset_config_keys`):

```python
async def test_post_study_happy_path_excludes_unset_config_keys(
    async_client: httpx.AsyncClient, arq_pool_spy: SpyArqPool
) -> None:
    ...
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 201, resp.text
    detail = resp.json()
    ...
    assert arq_pool_spy.calls == [("start_study", detail["id"])]
```

Self-contained AC-3 restore tests (new — two tests, one per restore branch, each **forcing** its precondition so both branches run deterministically on every CI run regardless of whether Redis was up at boot):

```python
async def test_arq_pool_spy_restores_existing_pool(async_client: httpx.AsyncClient) -> None:
    """AC-3 (attr-present branch): install_arq_pool_spy reassigns the prior pool.

    Forces the attr-present precondition by setting a sentinel pool first, so this
    branch runs even on a Redis-down boot where the lifespan never set the attr.
    Captures and restores the ORIGINAL boot value (real pool or unset) in a
    finally so the app is left exactly as the lifespan provided it — never
    attr-absent when it was attr-present, so lifespan teardown's
    arq_pool.aclose() (main.py:142-146) still finds the real pool.
    """
    from backend.app.main import app

    orig_had = hasattr(app.state, "arq_pool")
    orig = getattr(app.state, "arq_pool", None)
    sentinel = object()
    app.state.arq_pool = sentinel
    try:
        with install_arq_pool_spy(app) as spy:
            assert app.state.arq_pool is spy
            assert isinstance(app.state.arq_pool, SpyArqPool)
        # Restored to the exact prior object (the sentinel), not a SpyArqPool.
        assert app.state.arq_pool is sentinel
        assert not isinstance(app.state.arq_pool, SpyArqPool)
    finally:
        # Restore the ORIGINAL boot state so we don't leak / don't strand the
        # real pool that lifespan shutdown will try to aclose().
        if orig_had:
            app.state.arq_pool = orig
        elif hasattr(app.state, "arq_pool"):
            delattr(app.state, "arq_pool")


async def test_arq_pool_spy_restores_unset_attr(async_client: httpx.AsyncClient) -> None:
    """AC-3 (attr-absent branch): install_arq_pool_spy deletes the attr on exit.

    Forces the attr-absent precondition by deleting any existing pool first
    (capturing it to restore afterwards), so this branch runs even on a Redis-up
    boot where the lifespan set a real pool.
    """
    from backend.app.main import app

    had = hasattr(app.state, "arq_pool")
    saved = getattr(app.state, "arq_pool", None)
    if had:
        delattr(app.state, "arq_pool")
    try:
        assert not hasattr(app.state, "arq_pool")
        with install_arq_pool_spy(app) as spy:
            assert app.state.arq_pool is spy
        # Attr deleted again on exit (original unset state restored).
        assert not hasattr(app.state, "arq_pool")
    finally:
        # Restore whatever the lifespan originally provided.
        if had:
            app.state.arq_pool = saved
```

> The two AC-3 tests deliberately use `async_client` (to establish the lifespan-built state) and the `install_arq_pool_spy` contextmanager directly — NOT the `arq_pool_spy` fixture — so they can observe `app.state.arq_pool` after the contextmanager exits within a single test (resolves GPT-5.5 cycle-1 finding #2; no cross-test ordering dependency). Each test **forces its own precondition** (inject a sentinel pool / delete the attr) so both restore branches are exercised every run, independent of whether CI Redis was reachable at boot (resolves GPT-5.5 plan cycle-1 finding #2). Each test restores the original boot state in a `finally` so it doesn't perturb other tests sharing the module-level `app`.

**Tasks**
1. Add `from backend.tests.integration.conftest import SpyArqPool, install_arq_pool_spy` to the test module's imports.
2. For each of the 10 rejection-path tests: add the `arq_pool_spy: SpyArqPool` param and `assert arq_pool_spy.calls == []` after the existing rejection assertions.
3. For each of the 3 success-path tests: add the `arq_pool_spy: SpyArqPool` param and `assert arq_pool_spy.calls == [("start_study", detail["id"])]` (use the `id` field from the parsed 201 body).
4. Add the two AC-3 restore tests (`test_arq_pool_spy_restores_existing_pool` + `test_arq_pool_spy_restores_unset_attr`), each forcing its own precondition.
5. Run `pytest backend/tests/integration/test_studies_api.py` (or `make test-integration`) and confirm green.
6. Run `make lint` + `make typecheck`.

**Definition of Done (DoD)**
- All 10 rejection-path tests pass with `assert arq_pool_spy.calls == []` (FR-3, AC-1).
- All 3 success-path tests pass with `assert arq_pool_spy.calls == [("start_study", <id>)]` (FR-4, AC-2).
- Both AC-3 tests pass: `test_arq_pool_spy_restores_existing_pool` (forces attr-present → reassign) and `test_arq_pool_spy_restores_unset_attr` (forces attr-absent → delattr). Both restore branches are exercised deterministically every run, independent of CI Redis reachability (AC-3, D-5).
- The success-path assertion proves the spy (not the real Redis pool) received the enqueue, confirming install-after-lifespan ordering (AC-4).
- `make test-integration` + `make lint` + `make typecheck` green.

---

## 3) Testing workstream (required)

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- Scope: `SpyArqPool` recording shape + truthy return.
- Tasks:
  - [ ] (Story 1.1, optional-recommended) `backend/tests/unit/test_arq_pool_spy.py` — assert `enqueue_job` records flattened tuple + returns truthy.
- DoD:
  - [ ] Recording + return-value branches covered deterministically.

### 3.2 Integration tests
- Location: `backend/tests/integration/test_studies_api.py`
- Scope: studies-POST rejection (no enqueue) + success (one enqueue) + spy restore.
- Tasks:
  - [ ] (Story 1.2) 10 rejection-path tests assert `spy.calls == []`.
  - [ ] (Story 1.2) 3 success-path tests assert `spy.calls == [("start_study", <id>)]`.
  - [ ] (Story 1.2) `test_arq_pool_spy_restores_existing_pool` + `test_arq_pool_spy_restores_unset_attr` (AC-3, both branches forced).
- DoD:
  - [ ] Happy path + all listed rejection paths + restore behavior covered.

### 3.3 Contract tests
- N/A — no new endpoint or response shape. The HTTP contract of `POST /api/v1/studies` is unchanged; existing contract tests remain valid.

### 3.4 E2E tests
- N/A — no UI.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/integration/test_studies_api.py` | rejection-path tests with `_count_studies()` only | 10 | Update: add `arq_pool_spy` param + `assert spy.calls == []`. Existing status/error-code/`_count_studies` assertions are preserved (additive change only). |
| `backend/tests/integration/test_studies_api.py` | success-path POST tests | 3 | Update: add `arq_pool_spy` param + `assert spy.calls == [...]`. Existing assertions preserved. |
| `backend/tests/integration/test_studies_api.py` | other studies tests (cancel, list, get, clone, probe-shape) | ~30 | No change needed — they don't request `arq_pool_spy`, so the live (or unset) pool path is unaffected. Clone happy-path tests (`test_clone_happy_path_persists_parent_study_id:1459`) could optionally adopt the spy in a follow-up but are out of scope here. |
| `backend/tests/integration/conftest.py` | `async_client` fixture | 1 | No behavioral change to `async_client`; the new fixture is additive and depends on it. |

For all unchanged files: safe because the spy is opt-in (not autouse) and restores `app.state.arq_pool` on teardown, so no test that doesn't request it observes any difference.

### 3.5 Migration verification
- N/A — no schema change. No Alembic revision is added by this plan.

### 3.6 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make lint`
- [ ] `make typecheck`
- (E2E / contract gates not applicable — no UI, no new endpoint.)

---

## 4) Documentation update workstream (required)

### 4.0 Core context files

**`state.md`** — likely no change required (test-only chore; no Alembic head move, no new feature surface, no new debt). If the active branch/known-debt section references the unbacked "no enqueue" docstring gap, update it to "closed".

**`architecture.md`** — no change (no new service, layer, data flow, or integration).

**`CLAUDE.md`** — no change (no new convention or env var; the spy follows the existing Integration Test Mocking Policy).

### 4.1–4.4 — N/A (no architecture/product/runbook/security surface).

### 4.5 Quality docs (`docs/05_quality`)
- [ ] (Optional, recommended) Add one sentence to `docs/05_quality/testing.md` under the integration-mocking-policy section documenting `arq_pool_spy` as a sanctioned external-sink double for asserting enqueue behavior. Not a release gate.

**Documentation DoD**
- [ ] `state.md` / `architecture.md` / `CLAUDE.md` remain consistent with shipped behavior (expected: no edits required).
- [ ] If the `testing.md` note is added, it accurately describes the fixture's opt-in, install-after-lifespan semantics.

---

## 5) Lean refactor workstream (required)

### 5.1 Refactor goals
- Centralize the install/restore logic in one contextmanager (`install_arq_pool_spy`) so the fixture and the AC-3 test share a single, tested code path (no duplicated app.state-mutation logic).

### 5.2 Planned refactor tasks
- [ ] Factor install/restore into `install_arq_pool_spy` (done as part of Story 1.1, not a separate refactor pass).

### 5.3 Refactor guardrails
- [ ] No production code under `backend/app/` is touched.
- [ ] Lint/typecheck remain green.
- [ ] No expansion of scope to other enqueueing endpoints (tracked as spec §3 Out-of-scope follow-up).

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `async_client` fixture (conftest.py:138-160) | Story 1.1 (ordering) | implemented | none — exists |
| studies-POST enqueue shape `("start_study", study_id)` (studies.py:202) | Story 1.2 (success assertion) | implemented | if the job name/arg changes, FR-4 assertions update in lockstep (intended coupling) |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Spy installed before lifespan builds the pool, getting overwritten | L | H (silent false-green) | Fixture depends on `async_client`; AC-4 success-path assertion catches it (a recorded call proves the spy received the enqueue) |
| Spy leaks to a later test on the module-level `app` singleton | L | M (flaky cross-test) | `install_arq_pool_spy` restores prior state on exit; both AC-3 tests verify the two restore branches (each forces its precondition) |
| `app.state.arq_pool` unset on Redis-down boot breaks teardown `delattr` | L | M | `_UNSET` sentinel + `delattr` only when originally unset; `test_arq_pool_spy_restores_unset_attr` forces and covers the attr-absent branch every run |
| Recording raw varargs `(name, args)` instead of flattened breaks assertions | L | M | FR-1/D-3 lock the flattened shape; optional unit test asserts it directly |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Rejection path accidentally enqueues before raising | future regression in `studies.py` | FR-3 test fails (`spy.calls != []`) | CI red blocks merge |
| Enqueue job name/arg drift | future change to `_enqueue_start_study` | FR-4 test fails (`spy.calls` shape mismatch) | Update assertion in lockstep with the intended change |
| Real pool dispatch instead of spy | wrong install ordering | AC-4 success assertion fails | Fix fixture dependency on `async_client` |

## 7) Sequencing and parallelization

### Suggested sequence
1. Story 1.1 — build `SpyArqPool` + `install_arq_pool_spy` + `arq_pool_spy` fixture (+ optional unit test).
2. Story 1.2 — wire assertions into the 13 studies-POST tests + add AC-3 restore test.

### Parallelization opportunities
- None meaningful — Story 1.2 depends on Story 1.1's fixture. Both are small; ship in one PR.

## 8) Rollout and cutover plan

- Rollout stages: single PR; test-only; no flag.
- Feature flag strategy: N/A.
- Migration/cutover steps: none.
- Reconciliation: N/A.

## 9) Execution tracker (copy/paste section)

### Current sprint
- [x] Story 1.1 — `SpyArqPool` + `install_arq_pool_spy` + `arq_pool_spy` fixture (commit `149b58e`)
- [x] Story 1.2 — wire 10 rejection + 3 success enqueue assertions + AC-3 restore test (commit `f8ee244`)

### Blocked items
- (none)

### Done this sprint
- Story 1.1 (`149b58e`) — `SpyArqPool` double + `install_arq_pool_spy` ctx + `arq_pool_spy` fixture in integration conftest + 5 unit tests in `test_arq_pool_spy.py`.
- Story 1.2 (`f8ee244`) — 13 studies-POST tests carry the enqueue assertion (10 `== []`, 3 `== [("start_study", <id>)]`) + 2 AC-3 restore tests. Counts verified.

## 10) Story-by-Story Verification Gate (Agent Checklist)

- [ ] Files created/modified match story scope (`Modified files` tables)
- [ ] `SpyArqPool` + contextmanager + fixture implemented with the documented signatures
- [ ] All 13 studies-POST tests carry the correct enqueue assertion; AC-3 restore test present
- [ ] Commands executed and passed:
    - [ ] `make test-unit` (if the optional unit test was added)
    - [ ] `make test-integration` (or `pytest backend/tests/integration/test_studies_api.py`)
    - [ ] `make lint`
    - [ ] `make typecheck`
- [ ] No migration (none added — verified `git status` shows no new file under `migrations/versions/`)
- [ ] Optional `testing.md` note added or explicitly skipped

## 11) Plan consistency review (required before execution)

1. **Spec ↔ plan endpoint count:** Spec §7.1 lists only the existing `POST /api/v1/studies` (referenced, not added). Plan adds no endpoint. **Match (0 new endpoints).**
2. **Spec ↔ plan error code coverage:** No new error codes (spec §7.5). The rejection-path tests reference existing codes only, asserted by their already-present `error_code` checks. **No gap.**
3. **Spec ↔ plan FR coverage:** FR-1, FR-2 → Story 1.1; FR-3, FR-4 → Story 1.2. All four FRs assigned. **Complete.**
4. **Story internal consistency:** Story 1.1 modifies `conftest.py` (+ optional unit test file); Story 1.2 modifies `test_studies_api.py`. No file owned by two stories. Both files exist (verified by Read during planning). **Consistent.**
5. **Test file count:** §3 lists `test_arq_pool_spy.py` (Story 1.1, optional) + `test_studies_api.py` edits (Story 1.2). Both assigned to a story. **Match.**
6. **Gate arithmetic:** Epic gate cites 10 rejection + 3 success tests; the tables below enumerate exactly 10 + 3. **Match.**
7. **Open questions resolved:** Spec §19 has no open questions; all forks locked D-1…D-6. **Resolved.**
8. **Infrastructure path verification:** No migration directory, no router, no new infra path. The only paths are existing test files under `backend/tests/` (verified). **N/A / verified.**
9. **Frontend data plumbing:** N/A — no frontend.
10. **Persistence scope:** N/A — no `localStorage`/`sessionStorage`.
11. **Enumerated value contract audit:** N/A — no filter/dropdown/badge/sort. The only fixed value is the enqueue job name `"start_study"`, grounded directly at `studies.py:202` (the success-path assertion source of truth). **No drift surface.**
12. **Admin control / ceiling audit:** N/A — MVP2, no admin/tenant model.
13. **Audit-event coverage audit:** N/A — this plan adds no state-mutating endpoint or service function (test-only). No `audit_log` emission applies.

**No unresolved findings.** Plan is execution-ready.

---

## 12) Definition of plan done

- [x] Every FR (FR-1…FR-4) mapped to stories/tasks/tests.
- [x] Every story includes Modified files, Key interfaces, Tasks, and DoD (Endpoints/Schemas N/A for test-only stories per template).
- [x] Test layers scoped (unit optional, integration required; contract/E2E N/A with rationale).
- [x] Documentation updates planned (expected: none required beyond optional `testing.md` note).
- [x] Lean refactor scope + guardrails explicit.
- [x] Epic gate measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed — no unresolved findings.

---

## Cross-model review log (plan)

Mandatory GPT-5.5 cross-model review per impl-plan-gen Step 6. Model: `gpt-5.5` via OpenAI Chat Completions (`max_completion_tokens`, JSON-mode), spec passed as context. Key resolved from `.env`. **3 cycles to convergence; 4 findings total; 4 accepted, 0 rejected, 0 deferred.**

| Cycle | Finding | Severity / Pass | Adjudication |
|---|---|---|---|
| 1 | Fixture/contextmanager snippet not mypy --strict clean: `app: object` can't access `.state`; `list[tuple]` unparameterized. | Medium / B | **Accept** — typed `app: FastAPI`; `calls: list[tuple[object, ...]]`; added a typecheck note. |
| 1 | Single AC-3 restore test is env-conditional — only one branch runs per environment; DoD/risk overclaimed both-branch coverage. | Low / B | **Accept** — split into two tests, each **forcing** its precondition (inject sentinel pool / delete attr) so both restore branches run every CI run. |
| 1 | File-ownership nit: optional unit test listed under Modified files though it's a new file. | Low / A | **Accept** — moved `test_arq_pool_spy.py` to a "New files (optional)" classification. |
| 2 | `test_arq_pool_spy_restores_existing_pool` overwrote the real pool with a sentinel without saving/restoring it, leaving the app attr-absent and potentially stranding the real pool from lifespan shutdown's `aclose()`. | Medium / B | **Accept** — the test now captures the original boot value (`orig_had`/`orig`) and restores it in `finally` (reassign if present, delattr only if originally absent). |
| 3 | — | — | **Clean pass — `{"findings":[]}`. Converged.** |
