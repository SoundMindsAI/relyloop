# Implementation Plan — infra_study_preflight_real_engine_integration

**Date:** 2026-05-25
**Status:** Draft
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):**
- [CLAUDE.md](../../../../CLAUDE.md) — Absolute Rules #2, #4, #7 (Conventional Commits), test conventions, integration-test mocking policy
- [`docs/05_quality/testing.md`](../../../05_quality/testing.md) — test layer convention + 80% coverage gate

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs from feature_spec.md.
- Single-phase plan — no deferred work; spec §3 "Phase boundaries" explicitly states single phase.
- Behavior parity: the rewritten tests assert the SAME HTTP status, error_code, and message substrings as the monkeypatch versions today. The change is the test mechanism, not the product contract.
- Hard rule: no `bulk_index` or any write-side method added to `SearchAdapter` Protocol (Absolute Rule #4 + spec D-1).
- Hard rule: no basic-auth headers on the helper's httpx writes — both CI and local Compose run ES with security disabled (spec D-9 + CLAUDE.md).

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Story | Notes |
|---|---|---|
| FR-1 — Real-engine rewrite of AC-1..AC-4b | Epic 1 / Story 1.3 | Five test-function rewrites in `backend/tests/integration/test_studies_api.py:791-901`. |
| FR-2 — Bulk-index helper, not on Protocol | Epic 1 / Story 1.2 | New `backend/tests/integration/fixtures/es_overlap_probe.py`. Protocol unchanged (assertion gate in §11). |
| FR-3 — ES service-container only | Epic 1 / Story 1.1 + 1.3 | `es_required` decorator on all 5 rewritten tests; sourced from the new shared reachability module. |
| FR-4 — Per-test index isolation | Epic 1 / Story 1.2 + 1.3 | uuid-suffixed `target_index` from fixture; `try: ... finally: delete_overlap_probe_index(...)` in each rewritten test. |
| FR-5 — Pre-existing AC coverage stays intact | Epic 1 / Story 1.3 (DoD assertion) | No change to AC-5..AC-13, no change to autouse fixture. Verified by diff. |
| FR-6 — Fail-loud on missing local-es credentials | Epic 1 / Story 1.2 | Fixture pre-flight check; `pytest.skip(...)` locally, `RuntimeError` in CI. |
| FR-7 — Match probe-rebind pattern | Epic 1 / Story 1.3 | `monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", study_preflight.probe_judgment_overlap)` in each rewritten test. |
| FR-8 — CI-only sentinels | Epic 1 / Story 1.3 | Two sentinels in `test_es_overlap_probe_helpers.py`: ES reachability + local-es credentials present. |

**Deferred FRs:** none. Spec §3 phase boundaries: "Single phase. Test-infra-only feature; one PR."

## 2) Delivery structure

**Epic → Story → Tasks → DoD** with 3 sequential stories. All stories live on branch `feat/study-preflight-real-engine-integration` (already created).

### AI Agent Execution Protocol (applies to every story)

0. **Load context first**: Read `architecture.md`, `state.md`, and the feature spec at the top of every story.
1. **Read scope**: verify the story's outcome + new/modified files + DoD.
2. **No backend production code is touched** — this is a test-infra-only feature. All work is under `backend/tests/integration/` plus three doc files.
3. **Run targeted tests after each story** (per the story's DoD):
   - Story 1.1: `pytest backend/tests/integration/test_seed_es.py -v` (sanity that the refactor didn't break the original consumer).
   - Story 1.2: `pytest backend/tests/integration/test_es_overlap_probe_helpers.py -v` (helper smoke tests).
   - Story 1.3: `pytest backend/tests/integration/test_studies_api.py -v` (full file — exercises all 5 rewritten tests + 9 unchanged AC-5..AC-13 + 30+ unrelated tests). A `-k "overlap"` selector is NOT used because AC-4b's function name `test_post_study_cap_aware_threshold_allows_small_judgment_lists` lacks the "overlap" substring and would be silently excluded.
4. **Run the full pre-push gate after the final story**: `make fmt && make lint && make typecheck && make test-unit && make test-contract && make test-integration` (the last one with `make up` running so ES + Postgres + Redis are reachable; the new real-engine tests need it). Then run the same suite a second time with `docker compose stop elasticsearch` to verify the 5 rewritten tests SKIP cleanly (not fail) when ES is unreachable — this is the local-graceful-skip release gate the spec §16 requires.
5. **Update docs** in Story 1.3 — `docs/05_quality/testing.md`, `docs/03_runbooks/local-dev.md`, and the upstream `feat_study_preflight_overlap_probe/feature_spec.md` §"Existing test impact" row.
6. **`/impl-execute` post-implementation steps** finalize via the standard pipeline (PR → CI watch → Gemini adjudication → state.md update → move to `implemented_features/`).

### Conventions (project-specific)

- New fixture module: `backend/tests/integration/fixtures/es_overlap_probe.py` and `backend/tests/integration/fixtures/es_reachability.py` — snake_case, no `test_` prefix, matches the existing `fixtures/handbuilt_qrels.py` / `fixtures/run_trial_setup.py` pattern.
- Helper-smoke tests live at the integration-test root (`backend/tests/integration/test_es_overlap_probe_helpers.py`), NOT under `fixtures/`.
- Async helpers use `get_session_factory()` for their own DB sessions (mirrors `_seed_minimum_for_post_studies()` at [`test_studies_api.py:62-64`](../../../../backend/tests/integration/test_studies_api.py#L62-L64)) — do NOT accept `db: AsyncSession` as an argument.
- Conventional Commit prefix for all commits on this branch: `test:` for test-only commits, `docs:` for doc-only commits, `refactor:` for the reachability extraction. No `feat:` / `fix:` (no product behavior changes).
- `httpx.AsyncClient` for ES writes — no basic-auth headers (security disabled in CI + local).
- All new ES interactions wrapped in `try: ... finally: delete_overlap_probe_index(...)`.

---

## Epic 1 — Real-engine integration coverage for AC-1..AC-4b

### Story 1.1 — Extract `_es_base_url` + `es_required` to shared fixture module

**Outcome:** The host-shell-vs-in-container ES reachability probe + the `@es_required` skip marker live in a single shared module that any integration test can import. `backend/tests/integration/test_seed_es.py` continues to work unchanged in observable behavior.

**Rationale (spec D-11):** Importing `_es_base_url` and `es_required` from `test_seed_es.py` (a test-collected module) into a fixture helper is brittle — pytest's collection/import ordering, and a rename of `test_seed_es.py` would silently break the helper. Extracting to `fixtures/es_reachability.py` is the right shape.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/fixtures/es_reachability.py` | Houses `_es_base_url() -> str` (probes `http://localhost:9200` then `http://elasticsearch:9200`, returns `""` on failure) and `es_required = pytest.mark.skipif(not _es_base_url(), reason=...)`. Pure verbatim move from `test_seed_es.py:37-57`. |

**Modified files**

| File | Change |
|---|---|
| `backend/tests/integration/test_seed_es.py` | Replace the local `_es_base_url()` definition (lines 37-47) + `es_required` marker (lines 50-57) with `from backend.tests.integration.fixtures.es_reachability import _es_base_url, es_required`. Keep the module-level `ES_URL = _es_base_url()` assignment + `cleanup_index` fixture unchanged. |

**Key interfaces**

```python
# backend/tests/integration/fixtures/es_reachability.py
def _es_base_url() -> str:
    """Probe localhost:9200 then elasticsearch:9200; return URL or '' if neither reachable.

    Verbatim move from backend/tests/integration/test_seed_es.py:37-47 — keeps the
    2.0s timeout, the GET / probe, and the "version" key check.
    """

es_required: pytest.MarkDecorator
"""pytest.mark.skipif(not _es_base_url(), reason='Elasticsearch not reachable ...')"""
```

**Tasks**

1. Create `backend/tests/integration/fixtures/es_reachability.py` with the verbatim `_es_base_url()` + `es_required` definitions copied from `test_seed_es.py:37-57`.
2. Update `backend/tests/integration/test_seed_es.py` top-of-file imports: replace the local definitions with `from backend.tests.integration.fixtures.es_reachability import _es_base_url, es_required`.
3. Delete lines 37-57 of `test_seed_es.py` (the now-duplicated definitions).
4. Run `pytest backend/tests/integration/test_seed_es.py -v` — both test cases must still pass (or skip cleanly if ES is unreachable, matching their prior behavior).

**Definition of Done (DoD)**

- [ ] `backend/tests/integration/fixtures/es_reachability.py` exists and contains the two exported symbols.
- [ ] `backend/tests/integration/test_seed_es.py` no longer contains a local `_es_base_url` *definition* (`grep -nE '^def _es_base_url|^es_required = pytest' backend/tests/integration/test_seed_es.py` returns 0 matches). The `_es_base_url` IDENTIFIER may still appear via the new `from ... import _es_base_url, es_required` line and the existing `ES_URL = _es_base_url()` module-level call — those are expected; only the local definitions are removed.
- [ ] `test_seed_es.py`'s two integration tests still pass (or skip with the same reason wording) under `make test-integration -- -k test_seed_es`.
- [ ] `make lint` and `make typecheck` clean on the changed files.
- [ ] Commit prefix: `refactor(test-infra)`.

---

### Story 1.2 — Build the new fixture helper module + helper-smoke tests

**Outcome:** A new fixture module `fixtures/es_overlap_probe.py` provides three public helpers (`seed_minimum_for_overlap_probe_real_engine`, `bulk_index_overlap_probe_docs`, `delete_overlap_probe_index`) covered by 4 of the 6 helper-smoke tests in a new `test_es_overlap_probe_helpers.py`. The remaining 2 sentinel tests land in Story 1.3 (they belong with the FR-8 CI gate, not with the per-helper smoke surface).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/fixtures/es_overlap_probe.py` | Three async helpers + a re-export of `_es_base_url` / `es_required` from `fixtures.es_reachability`. ~120 LOC. |
| `backend/tests/integration/test_es_overlap_probe_helpers.py` | Four smoke tests (a–d per spec §14) covering the three helpers' contracts. Tests (e) + (f) — the CI sentinels — land in Story 1.3. ~110 LOC. |

**Modified files**

None.

**Key interfaces**

```python
# backend/tests/integration/fixtures/es_overlap_probe.py

from backend.tests.integration.fixtures.es_reachability import _es_base_url, es_required  # re-export

async def seed_minimum_for_overlap_probe_real_engine() -> dict[str, str]:
    """Seed a cluster + template + query_set + judgment_list for real-engine overlap probe tests.

    Pre-flight: reads `get_settings().cluster_credentials_yaml` (a YAML string, NOT a path —
    the @cached_property returns file CONTENT) and verifies the parsed mapping contains a
    top-level `local-es` key. If absent (or YAML invalid, or mount missing, or value not a
    dict), the helper:
      - in CI (`os.environ.get("CI") == "true"`): raises RuntimeError with operator guidance.
      - elsewhere: calls pytest.skip(...) with substrings matching r"local-es",
        r"cluster_credentials\\.yaml", r"scripts/install\\.sh".

    Acquires its own DB session via get_session_factory() — does NOT accept db as arg.
    Returns six keys: {cluster_id, template_id, query_set_id, judgment_list_id,
                       target_index, es_base_url}.
    The cluster row uses base_url=<es_base_url>, auth_kind='es_basic',
    credentials_ref='local-es' (matching CI's mounted YAML); the judgment_list's target
    matches target_index (per-test unique: f"overlap-probe-test-{uuid.uuid4().hex}").
    """

async def bulk_index_overlap_probe_docs(
    es_base_url: str, target_index: str, doc_ids: list[str]
) -> None:
    """DELETE the index (accept 200/404), PUT it with minimal mapping, optionally /_bulk, refresh.

    When doc_ids is non-empty:
      - PUT mapping {"properties": {"_id_marker": {"type": "keyword"}}}
      - POST /_bulk with NDJSON body (one {"index": {"_index": target, "_id": doc_id}}
        header line + one {"_id_marker": "ok"} doc line per record; terminated by \\n;
        Content-Type: application/x-ndjson). Raise on bulk_resp.json()["errors"] is True.
      - POST /<target>/_refresh.

    When doc_ids is empty:
      - PUT mapping (same).
      - SKIP /_bulk (empty NDJSON body returns ES 400 parse_exception).
      - POST /<target>/_refresh — leaves the index empty but searchable for the probe.

    No basic-auth headers (both CI and local Compose run ES with security disabled per
    CLAUDE.md "Do not install ES + OpenSearch with security plugins enabled in the local
    Compose"). Mirrors the seed_es.py:48-91 pattern.
    """

async def delete_overlap_probe_index(es_base_url: str, target_index: str) -> None:
    """Idempotent DELETE /<target> — accept 200 or 404 as success.

    MUST swallow transport-level errors (httpx.HTTPError, httpx.ConnectError,
    httpx.TimeoutException): log a WARN via the module's structlog logger and return.
    Re-raising in `finally:` blocks would mask the original test failure — the 32-hex
    uuid suffix is the isolation guarantee; cleanup is best-effort.
    """
```

**Tasks**

1. Create `backend/tests/integration/fixtures/es_overlap_probe.py` with the three helpers + the re-export line. Import `httpx`, `yaml`, `pytest`, `uuid`, `os`, `structlog`, `get_settings`, `get_session_factory`, `repo`.
2. Implement `seed_minimum_for_overlap_probe_real_engine()` body per the docstring — mirror `_seed_minimum_for_post_studies()`'s shape at `test_studies_api.py:62-115` (cluster + template + query_set + judgment_list). The cluster row MUST set `engine_type="elasticsearch"`, `environment="dev"`, `auth_kind="es_basic"`, `credentials_ref="local-es"` (NOT `"ref"`), and `base_url=<resolved es_base_url from _es_base_url()>`. The judgment_list's `target` MUST equal the per-test `target_index = f"overlap-probe-test-{uuid.uuid4().hex}"`. Include the FR-6 pre-flight check at the top BEFORE any DB or HTTP work.
3. Implement `bulk_index_overlap_probe_docs()` body — `httpx.AsyncClient(base_url=es_base_url, timeout=30.0)` context manager; the DELETE/PUT/optional-`/_bulk`/refresh sequence per the docstring. Branch on `len(doc_ids) == 0`.
4. Implement `delete_overlap_probe_index()` body — DELETE within a `try: except (httpx.HTTPError, httpx.ConnectError, httpx.TimeoutException) as exc: logger.warning(...)` block. Return None on either path.
5. Create `backend/tests/integration/test_es_overlap_probe_helpers.py` with four tests covering FR-2 + FR-6 + the cleanup idempotency:
   - **(a)** `test_bulk_index_indexes_doc_ids` — seed an index with `doc_ids=["a", "b", "c"]`, then issue an `ids`-query `{"query": {"ids": {"values": ["a","b","c"]}}, "size": 10}` against `/<idx>/_search` and assert: (i) `hits.total.value == 3`, (ii) `set(h["_id"] for h in hits.hits) == {"a","b","c"}` — proves the specific IDs are searchable, not just that some count of docs exists. Carries `@es_required`. Uses `f"overlap-probe-helper-test-{uuid.uuid4().hex}"` as the index name and `try: ... finally: delete_overlap_probe_index(...)`.
   - **(b)** `test_bulk_index_empty_doc_ids_creates_empty_index` — seed with `doc_ids=[]`, assert GET `/<idx>/_count` returns 0 AND assert NO `_bulk` HTTP call was issued. **Instrumentation:** monkeypatch `httpx.AsyncClient.post` with a counting wrapper that records the URL path of every POST call and delegates to the real method (or use `pytest-httpx`/`respx` if already in the project's dev deps — check `pyproject.toml` `[dependency-groups.dev]` first; if neither is present, the monkeypatch wrapper is sufficient and adds no new dep). Assert no recorded POST URL contains `"_bulk"`. Carries `@es_required`. **Caller-supplied `event_hooks=...` does NOT work here** because the helper constructs its own `AsyncClient` — must patch at the class/method level.
   - **(c)** `test_delete_overlap_probe_index_is_idempotent` — DELETE on a non-existent index returns cleanly (no exception), DELETE on an existing index also returns cleanly. Carries `@es_required`.
   - **(d)** `test_seed_helper_missing_local_es_credentials` — parametrized over `[("ci_false", "pytest.skip"), ("ci_true", "RuntimeError")]`. Each case monkeypatches `get_settings().__dict__["cluster_credentials_yaml"]` to `"unrelated:\\n  username: x\\n  password: y\\n"` (no `local-es` key) AND `os.environ["CI"]` to the case-specific value, then awaits the helper. **Message assertions (FR-6 + AC-INFRA-6):** for the `ci_false` case, assert the caught `pytest.skip.Exception` message contains ALL THREE substrings: `"local-es"`, `"cluster_credentials.yaml"`, `"scripts/install.sh"`. For the `ci_true` case, assert the caught `RuntimeError` message contains `"local-es"` AND `"workflow regression"` AND `"Seed cluster credentials"` AND `".github/workflows/pr.yml"` (the explicit workflow-file pointer FR-6 requires, so operators can grep their way to the broken step). Does NOT carry `@es_required` (short-circuits before any HTTP call).
6. Run `pytest backend/tests/integration/test_es_overlap_probe_helpers.py -v` — all 4 (with 5 cases, since (d) is parametrized) must pass or skip cleanly off the host shell.

**Definition of Done (DoD)**

- [ ] All three helpers exist with the documented signatures + behaviors.
- [ ] `grep -nE "bulk_index|index_doc|put_doc|index_bulk" backend/app/adapters/` returns no matches (FR-2 Protocol-unchanged assertion).
- [ ] Test (b) (empty `doc_ids`) MUST verify no `/_bulk` HTTP call is issued. **Instrumentation:** `monkeypatch.setattr(httpx.AsyncClient, "post", counting_wrapper)` where `counting_wrapper` records the URL path and delegates to the original `post`; OR `pytest-httpx` / `respx` mock transport if already in `pyproject.toml` `[dependency-groups.dev]` (check first; don't add a new dep just for this test). **`httpx.AsyncClient(event_hooks=...)` is NOT a valid option here** — the helper constructs its own AsyncClient, so caller-supplied event hooks never run. The assertion is "0 recorded POST URLs contain `_bulk`", NOT just `_count == 0` (the latter wouldn't catch a defensive empty `/_bulk` regression).
- [ ] Test (d) covers BOTH `CI=true` (RuntimeError) and `CI=false` (pytest.skip.Exception) paths via pytest parametrize.
- [ ] Helper-smoke tests touching ES use `f"overlap-probe-helper-test-{uuid.uuid4().hex}"` index names AND wrap interactions in `try: ... finally: await delete_overlap_probe_index(...)`.
- [ ] `make lint` and `make typecheck` clean on the changed files.
- [ ] Commit prefix: `test(infra)`.

---

### Story 1.3 — Rewrite AC-1..AC-4b, add CI sentinels, refresh docs

**Outcome:** The five test functions at `backend/tests/integration/test_studies_api.py:791-901` now exercise the real `probe_judgment_overlap` against the real ES service container. Two CI-only sentinels in `test_es_overlap_probe_helpers.py` fail loudly if ES or `local-es` credentials regress in the workflow. Three doc files reflect the new test-infra reality.

**Modified files**

| File | Change |
|---|---|
| `backend/tests/integration/test_studies_api.py` | Rewrite the 5 test functions at lines 791, 826, 843, 863, 880 per the per-test data tuples in spec §3 B4. Each rewritten test (a) carries `@es_required` (imported from `backend.tests.integration.fixtures.es_reachability`); (b) opens its `try: ... finally: await delete_overlap_probe_index(...)` IMMEDIATELY after the seed call (per spec §3 B3 step 2); (c) seeds ES + judgments inside the `try:` block; (d) rebinds the probe symbol to the real `study_preflight.probe_judgment_overlap`; (e) POSTs `/api/v1/studies`; (f) asserts the same status + envelope + message substrings as today. Removes the 5 `monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", fake_probe)` lines at 806, 836, 857, 873, 897. The `_make_fake_probe_result` helper at lines 773-788 STAYS (used by other AC tests). |
| `backend/tests/integration/test_es_overlap_probe_helpers.py` | Add tests (e) + (f) from Story 1.2's plan — the two CI sentinels. (e) `test_overlap_probe_real_engine_sentinel`: decorated `@pytest.mark.skipif(os.environ.get("CI") != "true", reason="CI-only sentinel")`, asserts `_es_base_url() != ""` with failure message naming `localhost:9200` + `elasticsearch:9200` + `.github/workflows/pr.yml` "elasticsearch:9.4.0" service step. MUST NOT carry `@es_required`. (f) `test_overlap_probe_real_engine_credentials_sentinel`: same `skipif` decorator, asserts `"local-es" in yaml.safe_load(get_settings().cluster_credentials_yaml or "{}")` with failure message naming the workflow's "Seed cluster credentials" step. MUST NOT carry `@es_required`. |
| `docs/05_quality/testing.md` | Append one line to §"Integration test mocking policy" noting that AC-1..AC-4b of `feat_study_preflight_overlap_probe` now run end-to-end via a dedicated test-only bulk-index helper (`fixtures/es_overlap_probe.py`), and that bulk-index is intentionally NOT on the `SearchAdapter` Protocol per this feature's D-1. |
| `docs/03_runbooks/local-dev.md` | Append one line to §"Running integration tests locally" noting that the new real-engine tests require ES reachable at `localhost:9200` AND a `local-es:` entry in `./secrets/cluster_credentials.yaml`; tests skip cleanly otherwise locally. |
| `docs/00_overview/implemented_features/2026_05_22_feat_study_preflight_overlap_probe/feature_spec.md` | Update the §"Existing test impact" row for `test_studies_api.py` AC-1..AC-4b to note "rewritten to real-engine via `infra_study_preflight_real_engine_integration` (PR #___)". |

**New files**

None (Story 1.2 created all the new files this story consumes).

**Endpoints**

No new endpoints. Existing endpoint exercised: `POST /api/v1/studies` (unchanged contract; the probe + 422 envelope are byte-identical to today's `feat_study_preflight_overlap_probe` ship).

**Key interfaces**

No new interfaces. Story consumes the three helpers from Story 1.2.

**Tasks**

> **Persistence-side assertion discipline (applies to all 5 rewrites):** the existing monkeypatch versions assert HTTP status + envelope substrings; AC-1 also asserts `count_after == count_before` to lock the no-row-inserted invariant (see `test_studies_api.py:809-815, 823`). AC-2 / AC-3 / AC-4 / AC-4b do NOT carry an explicit `count_studies` assertion today (verified in spec §12). Each rewrite MUST preserve whatever assertions are present in the current source byte-for-byte and ADD nothing besides the real-engine setup. The success-path implicit DB assertion (the endpoint's `"queued"` response only exists if the row was committed) is sufficient coverage on the 201 paths; the explicit before/after `count_studies` is unique to AC-1's stronger "no row even attempted" gate.

1. **Rewrite AC-1** (`test_post_study_insufficient_overlap_returns_422` at line 791) — per spec §3 B4 row 1: seed 50 distinct judgments (doc IDs `"doc_000".."doc_049"`), bulk-index 0 docs, expect 422 + `"0 of 50 probed"` + `"judged_doc_count=50"`. PRESERVE the existing `count_before` / `count_after` / `assert count_after == count_before` DB-side assertion (lines 809-815, 823). Wrap in `try: ... finally:`.
2. **Rewrite AC-2** (`test_post_study_sufficient_overlap_returns_201` at line 826) — 50 judgments, all 50 indexed → 201 + `"queued"` status. The "queued" assertion implicitly verifies the studies row was committed (response only contains it if persisted).
3. **Rewrite AC-3** (`test_post_study_overlap_at_threshold_returns_201` at line 843) — 5 judgments, first 3 indexed → 201 (boundary `>=`).
4. **Rewrite AC-4** (`test_post_study_overlap_one_below_threshold_returns_422` at line 863) — 5 judgments, first 2 indexed → 422 (boundary `<`). No DB-side count assertion exists today; do not add one.
5. **Rewrite AC-4b** (`test_post_study_cap_aware_threshold_allows_small_judgment_lists` at line 880) — 2 judgments, both 2 indexed → 201 (cap-aware).
6. **Add CI sentinel (e)** `test_overlap_probe_real_engine_sentinel` to `test_es_overlap_probe_helpers.py` per spec §3 B1b → FR-8 → AC-INFRA-7. DO NOT add `@es_required`.
7. **Add CI sentinel (f)** `test_overlap_probe_real_engine_credentials_sentinel` to `test_es_overlap_probe_helpers.py`. DO NOT add `@es_required`.
8. **Verify no production code touched** — `git diff main -- backend/app/ migrations/ ui/` returns empty.
9. **Verify `SearchAdapter` Protocol unchanged** — `git diff main -- backend/app/adapters/protocol.py` returns empty.
10. **Verify AC-5..AC-13 + autouse fixture untouched** — `git diff main -- backend/tests/integration/test_studies_api.py` shows changes ONLY in (a) the top-of-file `import` block (necessary to import `es_required` and the three helper symbols from `fixtures.es_overlap_probe` + `fixtures.es_reachability`), and (b) the 5 target function bodies at lines ~791-901. All other function bodies, the autouse fixture at lines 33-58, `_seed_minimum_for_post_studies` at 61-115, `_study_body_for` / `_seed_judgments` / `_make_fake_probe_result` at 723-788, AC-5..AC-13 at 903+, the `_FakeProbeAdapter` class at 946-980, and `_install_real_probe_with_fake_adapter` at 983-1004 are byte-identical to main.
11. **Update `docs/05_quality/testing.md`**, **`docs/03_runbooks/local-dev.md`**, and the upstream **`feat_study_preflight_overlap_probe/feature_spec.md`** "Existing test impact" row.
12. **Run targeted tests**: `pytest backend/tests/integration/test_studies_api.py -v` (the full file — must pass all 35+ tests including the 5 rewrites + 9 unchanged AC-5..AC-13 + unrelated POST/cancel/GET-trials tests; no `-k` selector to avoid the AC-4b silent-exclusion bug from cycle-1 reviewer A-1). `pytest backend/tests/integration/test_es_overlap_probe_helpers.py -v` (must pass all 6 — 4 helper smoke + 2 sentinels; sentinels skip locally, run in CI).
13. **Run pre-push gate**: `make fmt && make lint && make typecheck && make test-unit && make test-contract`.

**Definition of Done (DoD)**

- [ ] All 5 rewritten tests pass against real ES locally — `make up` then `pytest backend/tests/integration/test_studies_api.py -v` (full file; no `-k` selector — see cycle-1 reviewer A-1 note in §2 about AC-4b's name not containing "overlap").
- [ ] All 5 rewritten tests SKIP cleanly with the `@es_required` reason when ES is stopped: `docker compose stop elasticsearch && pytest backend/tests/integration/test_studies_api.py -v --tb=short`. Assert by name that the 5 rewrites report `SKIPPED` with the canonical `Elasticsearch not reachable…` reason, and that AC-5..AC-13 + the 30+ unrelated tests still pass (their behavior doesn't depend on real ES because the autouse fixture stubs the probe for them).
- [ ] AC-5..AC-13 (the 9 pre-existing AC tests) and the 30+ unrelated tests in `test_studies_api.py` still pass — `pytest backend/tests/integration/test_studies_api.py -v` returns the same pass/skip count as before this feature, except for the 5 rewrites that now skip when ES is unreachable.
- [ ] `git diff main -- backend/app/adapters/protocol.py` returns empty (Protocol unchanged — FR-2 hard rule).
- [ ] `grep -nE "bulk_index|index_doc|put_doc|index_bulk" backend/app/adapters/` returns no production-code matches.
- [ ] `git diff main -- backend/app/ migrations/ ui/` returns empty (test-infra-only — no production code touched).
- [ ] The autouse `_default_overlap_probe_passes` fixture at `test_studies_api.py:33-58` is byte-identical to its pre-feature state.
- [ ] The two CI sentinels (e) + (f) carry ONLY `@pytest.mark.skipif(os.environ.get("CI") != "true", ...)` — NO `@es_required` (cycle-2 reviewer F3 — that decorator would skip the sentinel before its assertion runs, defeating fail-loud).
- [ ] In CI: both sentinels report as PASSED (NOT skipped). Verified by checking the GH Actions job log.
- [ ] In CI: the 5 rewritten tests report as PASSED (NOT skipped) — verified by checking the GH Actions log.
- [ ] 80% backend coverage gate still green (`make test-unit` + coverage report; integration tests don't gate coverage, but unit-test coverage hasn't dropped).
- [ ] `docs/05_quality/testing.md`, `docs/03_runbooks/local-dev.md`, and the upstream feature spec all updated.
- [ ] Pre-push gate passes locally before push.
- [ ] Commit prefixes: `test(integration)` for the rewrites + sentinels, `docs:` for the three doc updates.

---

## UI Guidance

**No legacy behavior parity table** — no user-facing component is being deleted, moved, or modified. This is a test-infra-only feature with no UI surface.

No UI changes in this plan. The feature spec §11 is `N/A — test-infra-only feature with no user-facing surface.`

---

## 3) Testing workstream (required)

### 3.1 Unit tests

- Location: `backend/tests/unit/`
- Scope: N/A — no production code is touched, so no unit tests are added.
- Tasks: none.
- DoD: none.

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Scope: the 5 rewritten study tests + 6 new helper-smoke tests; the existing AC-5..AC-13 + 30+ unrelated tests in `test_studies_api.py` must continue to pass.
- Tasks:
  - [ ] **Story 1.3 — Rewrite 5 tests:** `test_post_study_insufficient_overlap_returns_422`, `test_post_study_sufficient_overlap_returns_201`, `test_post_study_overlap_at_threshold_returns_201`, `test_post_study_overlap_one_below_threshold_returns_422`, `test_post_study_cap_aware_threshold_allows_small_judgment_lists` in `backend/tests/integration/test_studies_api.py`.
  - [ ] **Story 1.2 — 4 helper smoke tests** in `backend/tests/integration/test_es_overlap_probe_helpers.py`: (a) bulk-index indexes the expected doc IDs; (b) empty `doc_ids` skips `/_bulk` and `_count == 0`; (c) delete is idempotent on 200 + 404; (d) FR-6 missing-`local-es` skip path (parametrized over CI true/false).
  - [ ] **Story 1.3 — 2 CI sentinel tests** in `backend/tests/integration/test_es_overlap_probe_helpers.py`: (e) ES reachability sentinel; (f) `local-es` credentials sentinel.
- DoD:
  - [ ] All 5 rewritten tests pass against real ES (CI; local with `make up`).
  - [ ] All 6 helper-smoke tests pass or skip per their respective decorators.
  - [ ] In CI, the 5 rewrites + the 2 sentinels MUST report `passed`, NOT `skipped`.

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Scope: N/A — no new endpoints, no new error codes. The existing `INSUFFICIENT_JUDGMENT_OVERLAP` 422 envelope contract test stays unchanged.
- Tasks: none.
- DoD: existing `backend/tests/contract/test_studies_error_codes.py` still passes.

### 3.4 E2E tests

- Location: `ui/tests/e2e/`
- Scope: N/A — no UI surface.
- Tasks: none.
- DoD: existing UI E2E suite still passes (no expected change).

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/integration/test_studies_api.py` | `monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", fake_probe)` in AC-1..AC-4b | 5 | **Remove** in Story 1.3 — replaced by the real-probe rebind pattern. |
| `backend/tests/integration/test_studies_api.py` | The autouse `_default_overlap_probe_passes` fixture (lines 33-58) | 1 | **No change** — pre-overlap-probe tests still depend on it. The rewritten tests opt out by rebinding to the real probe. |
| `backend/tests/integration/test_studies_api.py` | AC-5..AC-13 (lines 903-end) | 9 | **No change** — exercise different boundaries (FK short-circuit, Tier-1 mismatch, adapter exceptions, empty-judgments, adapter-call-shape locks, read-path tolerance, FR-4 exception matrix). |
| `backend/tests/integration/test_seed_es.py` | `_es_base_url()` + `es_required` local definitions (lines 37-57) | 1 | **Refactor** in Story 1.1 — replace with `from backend.tests.integration.fixtures.es_reachability import ...`. Two test cases must still pass with same skip behavior. |
| `backend/tests/contract/test_studies_error_codes.py` | `INSUFFICIENT_JUDGMENT_OVERLAP` envelope assertions | 1 | **No change** — envelope shape unchanged. |
| `backend/tests/unit/services/test_study_preflight.py` | Probe orchestration unit tests with mocked adapter | 4 | **No change** — these stay as the fast inner-loop coverage. |

### 3.5b Migration verification

N/A — no schema changes, no migration.

### 3.6 CI gates

- [ ] `make test-unit` (full backend unit suite, including the 4 existing `test_study_preflight.py` cases).
- [ ] `make test-integration` (includes the 5 rewritten tests + 6 helper-smoke tests).
- [ ] `make test-contract` (existing `test_studies_error_codes.py` still passes).
- [ ] In CI, GH Actions `pr.yml` workflow's pytest step shows the 5 rewrites + 2 sentinels as `passed`, NOT `skipped`. This is the FR-8 fail-loud guarantee in action.

---

## 4) Documentation update workstream

### 4.0 Core context files

- **`state.md`** — update at finalization: add this PR to "recent changes", reflect that `feat_study_preflight_overlap_probe`'s AC-1..AC-4b are now real-engine. No active-branch / priority change (this is a one-shot test-infra investment).
- **`architecture.md`** — no change. This feature adds no new layers, services, or data flows.
- **`CLAUDE.md`** — no change. No new conventions or rules; the existing "Integration tests only mock external services" rule already covers this work.

### 4.1 Architecture docs (`docs/01_architecture`)

- [ ] No change.

### 4.2 Product docs (`docs/02_product`)

- [ ] Update `docs/00_overview/implemented_features/2026_05_22_feat_study_preflight_overlap_probe/feature_spec.md` §"Existing test impact" row for `test_studies_api.py` to note the AC-1..AC-4b real-engine migration (Story 1.3 Task 11).

### 4.3 Runbooks (`docs/03_runbooks`)

- [ ] Update `docs/03_runbooks/local-dev.md` §"Running integration tests locally" — one line about the new real-engine tests' ES + `local-es` credential requirements (Story 1.3 Task 11).

### 4.4 Security docs (`docs/04_security`)

- [ ] No change.

### 4.5 Quality docs (`docs/05_quality`)

- [ ] Update `docs/05_quality/testing.md` §"Integration test mocking policy" — one line about the new helper module + the Protocol-unchanged invariant (Story 1.3 Task 11).

**Documentation DoD**

- [ ] All three doc files updated in Story 1.3.
- [ ] `state.md` updated at finalization (part of `/impl-execute`'s post-implementation step).

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- Extract the `_es_base_url` + `es_required` pair to a shared fixture module so future integration tests requiring ES reachability have a stable import target (Story 1.1).
- No other refactors in scope.

### 5.2 Planned refactor tasks

- [ ] Story 1.1 — extract reachability helper to `fixtures/es_reachability.py`.

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven by `test_seed_es.py` continuing to pass with byte-identical skip behavior.
- [ ] Lint/typecheck remain green.
- [ ] No expansion of product scope — no new behaviors added in the refactor story.
- [ ] No second refactor target — keep the scope at "extract + update one consumer", do not refactor `test_seed_es.py`'s `cleanup_index` fixture or other unrelated helpers.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| Elasticsearch service container at `elasticsearch:9200` (CI) / `localhost:9200` (local) | Story 1.3 5 rewritten tests + helper smoke tests (a/b/c) + sentinel (e) | Implemented in `.github/workflows/pr.yml` (CI) + `make up` (local) | Local: tests skip cleanly via `@es_required`. CI: sentinel (e) FAILS loudly — that's the design. |
| `./secrets/cluster_credentials.yaml` with `local-es:` entry | Story 1.3 5 rewritten tests + sentinel (f) | Implemented in `pr.yml` step "Seed cluster credentials" (CI) + `bash scripts/install.sh` (local) | Local: helper calls `pytest.skip(...)` with operator guidance. CI: sentinel (f) + FR-6's `RuntimeError`-in-CI both FAIL loudly. |
| `feat_study_preflight_overlap_probe` (PR #193) shipped | Story 1.3 — exists to test its probe | Satisfied 2026-05-22 | N/A. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Helper tests touch a shared index name and collide under pytest-xdist | L | M | Per-test 32-hex uuid suffix (D-13). 128 bits of entropy → essentially zero collision probability for any realistic CI rate. |
| `_default_overlap_probe_passes` autouse fixture accidentally re-stubs the probe during a rewritten test | L | M | Each rewritten test explicitly rebinds the probe symbol back to the real one BEFORE the POST; same pattern as the existing AC-13 service-layer test at `test_studies_api.py:1293-1296`. DoD asserts the autouse fixture's bytes are unchanged. |
| Cleanup transport error in `delete_overlap_probe_index` masks the original test failure | M | L | Helper catches `httpx.HTTPError`/`ConnectError`/`TimeoutException` and logs WARN; never re-raises. The uuid suffix means a leaked index does not poison the next test. (D-12) |
| ES service container starts but the `/_search` is slow (>2s for the probe's wait_for budget) | L | L | The probe has `PROBE_TIMEOUT_S = 2.0` + 1s wall-clock guard; if it times out, the probe falls through (FR-4 of upstream spec) and the test asserts 201 instead of 422 — would manifest as a deterministic test failure, easy to triage. Mitigation: CI uses `elasticsearch:9.4.0` with 256MB heap, well within probe budget for the per-test ≤50-doc index. |
| `xpack.security.enabled` flag re-enabled in CI YAML somehow | L | H | DoD requires the bulk_index helper has NO basic-auth headers (matches the established `seed_es.py` no-auth pattern). If security is re-enabled, ALL existing ES integration tests break too — caught at the workflow level, not just here. |
| Future operator adds a `bulk_index` method to `SearchAdapter` Protocol "for symmetry" | L | M | Story 1.3 DoD: `grep -nE "bulk_index\|index_doc\|put_doc\|index_bulk" backend/app/adapters/` returns no matches. AC-INFRA-5 + the §4 Anti-pattern lock the invariant in spec prose. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| ES service container fails to start in CI | Docker pull error, image not pinned, container fails healthcheck | Sentinel (e) FAILS loudly with a message pointing at `.github/workflows/pr.yml`'s `elasticsearch:9.4.0` service step. The 5 rewritten tests then skip with `@es_required` (but the sentinel failure is the loud signal). | Operator fixes the workflow; CI re-runs. |
| `cluster_credentials.yaml` mounted but missing `local-es:` key in CI | "Seed cluster credentials" workflow step removed/broken | Sentinel (f) FAILS loudly + FR-6's `RuntimeError`-in-CI branch fires when the helper runs in each rewritten test. Both surface clearly. | Operator restores the YAML step in `pr.yml`. |
| `cluster_credentials.yaml` mounted but malformed YAML | Workflow change corrupts the YAML | FR-6's `try: yaml.safe_load(...) except yaml.YAMLError:` catches it and routes through the same skip-or-RuntimeError fallback. In CI: RuntimeError. Locally: pytest.skip. | Operator fixes the YAML. |
| Test fails mid-execution, leaving an ES index behind | Probe assertion failure between bulk-index and the `finally:` block | `delete_overlap_probe_index` in `finally:` removes it. If ES is unreachable mid-test, the uuid suffix prevents cross-test contamination. | None needed — self-cleaning. |
| `_default_overlap_probe_passes` autouse fixture binds AFTER the rewritten test's rebind (unlikely but possible if fixture scoping changes) | A future PR changes autouse fixture scope/order | The rewritten test's `monkeypatch.setattr(...)` happens inside the test body, AFTER all autouse fixtures have run; pytest monkeypatch is teardown-safe. DoD asserts the autouse fixture's bytes are unchanged. | None expected; covered by Story 1.3 DoD. |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** — Extract `_es_base_url` + `es_required` to `fixtures/es_reachability.py`. Tiny refactor; ~5 min.
2. **Story 1.2** — Build the new fixture module (`es_overlap_probe.py`) + 4 helper-smoke tests. Depends on Story 1.1's shared module. ~45 min.
3. **Story 1.3** — Rewrite the 5 AC-1..AC-4b tests + add 2 CI sentinels + refresh 3 doc files. Depends on Story 1.2's helpers. ~45 min.

Total estimated implementation time: ~90 min + CI watch + Gemini adjudication.

### Parallelization opportunities

None — the three stories are strictly sequential (each depends on the prior's artifacts). All work happens on a single branch with a single PR.

---

## 8) Rollout and cutover plan

- **Rollout stages:** N/A — test-infra-only change; no operator-visible behavior. CI gate + PR review are the only gates.
- **Feature flag strategy:** N/A.
- **Migration/cutover steps:** N/A — no schema changes.
- **Reconciliation/repair strategy:** N/A.

After merge, no operator action required. CI will continue to run the workflow; the new sentinels + rewritten tests will exercise the real probe on every PR going forward.

---

## 9) Execution tracker (copy/paste section)

### Current sprint

- [ ] Story 1.1 — Extract reachability helper
- [ ] Story 1.2 — New fixture helper module + 4 smoke tests
- [ ] Story 1.3 — Rewrite AC-1..AC-4b + 2 CI sentinels + docs

### Blocked items

- None.

### Done this sprint

(populated as stories complete)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, the executing agent must attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables — verified by `git status` + `git diff --stat`).
- [ ] No production code touched (`git diff main -- backend/app/ migrations/ ui/` returns empty for all 3 stories).
- [ ] No changes to `SearchAdapter` Protocol (`git diff main -- backend/app/adapters/protocol.py` returns empty after Story 1.3).
- [ ] Required tests pass (story-specific subsets in each story's DoD).
- [ ] Commands executed and passed:
    - [ ] Story 1.1: `pytest backend/tests/integration/test_seed_es.py -v`
    - [ ] Story 1.2: `pytest backend/tests/integration/test_es_overlap_probe_helpers.py -v`
    - [ ] Story 1.3: `pytest backend/tests/integration/test_studies_api.py -v` (full file — see note about `-k "overlap"` silent exclusion) AND `pytest backend/tests/integration/test_es_overlap_probe_helpers.py -v` AND `make fmt && make lint && make typecheck && make test-unit && make test-contract`
- [ ] Migration round-trip: N/A (no migrations).
- [ ] Related docs updated in same PR when behavior/contract changed: Story 1.3 updates 3 docs.

---

## 11) Plan consistency review (performed before finalization)

**Pass 1 — Plan-internal consistency:**

1. **Spec ↔ plan endpoint count:** spec §8.1 lists `POST /api/v1/studies` (existing, unchanged) and explicitly states "No new endpoints introduced." Plan stories add zero new endpoints. ✅
2. **Spec ↔ plan error code coverage:** spec §8.5 lists "No new error codes." Plan adds no contract tests. The existing `INSUFFICIENT_JUDGMENT_OVERLAP` envelope is verified by `test_studies_error_codes.py` (unchanged). ✅
3. **Spec ↔ plan FR coverage:** §1 traceability table covers all 8 FRs (FR-1 → FR-8). Each is assigned to at least one story. ✅
4. **Story internal consistency:**
   - No story claims to add new endpoints or Pydantic schemas (none in scope).
   - New files: `fixtures/es_reachability.py` (Story 1.1) and `fixtures/es_overlap_probe.py` + `test_es_overlap_probe_helpers.py` (Story 1.2). No ownership conflict. ✅
   - Modified files: Story 1.1 modifies `test_seed_es.py`; Story 1.3 modifies `test_studies_api.py`, `test_es_overlap_probe_helpers.py` (adding sentinels), `docs/05_quality/testing.md`, `docs/03_runbooks/local-dev.md`, `feat_study_preflight_overlap_probe/feature_spec.md`. No file is modified by more than one story EXCEPT `test_es_overlap_probe_helpers.py` (created by Story 1.2, extended by Story 1.3). This is intentional and documented. ✅
5. **Test file count and assignment:**
   - `test_es_overlap_probe_helpers.py`: created by Story 1.2 (4 smoke tests a-d), extended by Story 1.3 (2 sentinels e-f). Counted in §3.2 inventory. ✅
   - 5 rewritten test functions in `test_studies_api.py`: owned by Story 1.3. ✅
6. **Gate arithmetic:** No epic/phase gates (single sequential plan). The single feature DoD in spec §18 has 11 items; all are exercised by Story DoDs + the final pre-push gate.
7. **Open questions resolved:** spec §19 has zero open questions ("None — the two scope forks ... are locked at D-1 and D-2"). ✅
8. **Frontend UI Guidance completeness:** N/A — no frontend stories. The plan's UI Guidance section explicitly states "No UI changes" and includes the required "no legacy parity table" justification. ✅

**Pass 2 — Codebase verification:**

| Claim | Verified by | Status |
|---|---|---|
| `_seed_minimum_for_post_studies()` at `test_studies_api.py:61-115` | grep + Read | Verified |
| 5 rewrite targets at lines 791, 826, 843, 863, 880 | grep | Verified |
| Monkeypatch lines 806, 836, 857, 873, 897 | grep | Verified |
| `_es_base_url()` at `test_seed_es.py:37-47` | Read | Verified |
| `_default_overlap_probe_passes` autouse at lines 33-58 | Read | Verified |
| Probe rebind pattern at lines 1293-1296 | Read | Verified |
| `fixtures/` directory exists and houses helper modules only (no test files) | `ls` | Verified |
| `get_settings().cluster_credentials_yaml` is the `@cached_property` accessor | Read `backend/app/core/settings.py:361` | Verified |
| `acquire_adapter()` raises `ClusterUnreachable` on `CredentialsMissing` | Read `backend/app/services/cluster.py:232-260` | Verified |
| `seed_es.py:48-91` NDJSON `/_bulk` pattern | Read | Verified |
| CI workflow's `elasticsearch:9.4.0` + `local-es:` YAML step | Read `.github/workflows/pr.yml:331` | Verified |
| Existing autouse `_restore_settings_mutations` fixture at integration conftest lines 18-26 | Read | Verified |
| Existing `_FakeProbeAdapter` + `_install_real_probe_with_fake_adapter` patterns at lines 946-1004 (AC-10/AC-11/AC-13 will use these unchanged) | Read | Verified |

**Pass 3 — Enumerated value contracts:** N/A — no new filters, dropdowns, status badges, or sort keys.

**Pass 4 — Audit-event coverage:** N/A — MVP1, `audit_log` arrives at MVP2. No state-mutating endpoints touched.

**Pass 5 — Admin control / ceilings:** N/A — MVP1 (no admin model).

No unresolved findings.

---

## 12) Definition of plan done

- [x] Every FR (FR-1 through FR-8) is mapped to at least one story.
- [x] Every story includes New files, Modified files, Tasks, and DoD. (Endpoints / Pydantic schemas omitted — no API surface.)
- [x] Test layers explicitly scoped (integration only; no unit/contract/e2e additions).
- [x] Documentation updates across docs/03 + docs/05 + the upstream implemented_features doc planned and owned.
- [x] Lean refactor scope and guardrails are explicit (Story 1.1 only).
- [x] Phase/epic gates: N/A (single sequential epic, no inter-story gates beyond DoDs).
- [x] Story-by-Story Verification Gate is included.
- [x] Plan consistency review (§11) performed; no unresolved findings.
